"""
Convert on-disk test scripts into virtual scripts.

A virtual script is materialized at `test_scripts/.vs_<uuid>.py` — the
test_scripts ROOT, not the folder the file came from. Two things break as a
result, and this module fixes both:

  1. Cross-file helper imports. `test_scripts/gw/superping.py` does
     `from test_scripts.gw.utils_gw_network import (...)`; after materialization
     that package path no longer resolves. The supported mechanism is
     `_script_libs = ["utils_gw_network"]`, which makes another virtual script's
     source importable by bare name (script_executor.resolve_virtual_script_libs
     writes each one to `.vslib_<uuid>/<name>.py` and puts that on PYTHONPATH).
     So: follow the import graph, convert each helper too, and rewrite the
     imports to the bare form.

  2. Names. A converted script is named by its BASENAME, with the disk subfolder
     becoming its folder. A slashed virtual-script name would crash lib
     materialization, which does `os.path.join(vslib_dir, f'{name}.py')` with no
     mkdir — and folders are first-class for virtual scripts since TASK-11.

Rewrites are line-range surgery on the original text, never `ast.unparse`:
comments, blank lines and formatting have to survive, because the result is what
the user sees and edits in the virtual-script editor.

Pure module — no Flask, no DB, no network. It lives in shared/ (not under
features/virtual-scripts/) so the sync CLI still works on a deploy where the
optional feature directory was stripped.

See docs/agent/execution/VIRTUAL_SCRIPTS.md.
"""

import ast
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

LOCAL_PKG = 'test_scripts'
ROOT_FOLDER = '(Root)'

# Error codes surfaced on ConversionPlan.errors.
ERR_NOT_FOUND = 'not_found'
ERR_SYNTAX = 'syntax_error'
ERR_UNSUPPORTED_IMPORT = 'unsupported_import'
ERR_DEPTH_EXCEEDED = 'depth_exceeded'
ERR_REWRITE_BROKE_SYNTAX = 'rewrite_broke_syntax'
ERR_NAME_COLLISION = 'name_collision'


class ConversionError(Exception):
    """A script cannot be converted. Carries a machine-readable `code`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ConversionUnit:
    """One script to write as a virtual script."""
    vs_name: str                      # 'superping' | 'utils_gw_network'
    folder: str                       # 'gw'  ('(Root)' for a root-level script)
    disk_ref: str                     # 'gw/superping'
    source: str                       # REWRITTEN source
    doc: Optional[str] = None         # sibling .md contents
    libs: List[str] = field(default_factory=list)
    is_helper: bool = False           # reached via an import, not requested directly
    warnings: List[str] = field(default_factory=list)


@dataclass
class ConversionPlan:
    root_ref: str
    units: List[ConversionUnit] = field(default_factory=list)   # helpers first
    errors: List[Dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def root_unit(self) -> Optional[ConversionUnit]:
        return next((u for u in self.units if u.disk_ref == self.root_ref), None)


def ref_to_name_and_folder(script_ref: str) -> Tuple[str, str]:
    """'gw/superping' -> ('superping', 'gw'); 'goto' -> ('goto', '(Root)')."""
    ref = (script_ref or '').strip().strip('/')
    if '/' not in ref:
        return ref, ROOT_FOLDER
    folder, _, name = ref.rpartition('/')
    return name, folder or ROOT_FOLDER


def find_local_imports(source: str) -> List[Tuple[str, str, str]]:
    """Module-level and nested imports of `test_scripts.*`.

    Returns [(pkg, mod, kind)] where kind is one of:
      'from_module'  — from test_scripts.gw.utils_x import a, b
      'from_package' — from test_scripts.gw import utils_x
      'import'       — import test_scripts.gw.utils_x [as alias]
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ConversionError(ERR_SYNTAX, f'source does not parse: {e}') from e

    found: List[Tuple[str, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if node.level or not module.startswith(f'{LOCAL_PKG}.'):
                continue
            parts = module.split('.')
            if len(parts) >= 3:
                # from test_scripts.<pkg...>.<mod> import names
                found.append(('/'.join(parts[1:-1]), parts[-1], 'from_module'))
            else:
                # from test_scripts.<pkg> import <mod>[, <mod>]
                for alias in node.names:
                    found.append((parts[1], alias.name, 'from_package'))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith(f'{LOCAL_PKG}.'):
                    continue
                parts = alias.name.split('.')
                found.append(('/'.join(parts[1:-1]), parts[-1], 'import'))

    # Dedupe, preserving order.
    seen = set()
    unique: List[Tuple[str, str, str]] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _find_script_libs_assign(tree: ast.Module) -> Optional[ast.Assign]:
    """Top-level `_script_libs = [...]` or `main._script_libs = [...]`.

    Only tree.body is searched, matching extract_script_libs — a nested
    assignment is invisible to the reader, so writing one would be a silent bug.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            is_bare = isinstance(target, ast.Name) and target.id == '_script_libs'
            is_attr = (isinstance(target, ast.Attribute)
                       and isinstance(target.value, ast.Name)
                       and target.value.id == 'main'
                       and target.attr == '_script_libs')
            if is_bare or is_attr:
                return node
    return None


def _splice_node(lines: List[str], node: ast.AST, replacement: str) -> Tuple[int, int, str]:
    """Build an edit that replaces only the node's own text, keeping whatever
    else shares its first and last line (e.g. the `_script_libs = ` prefix).

    ast column offsets are UTF-8 byte offsets, so slice the encoded line.
    """
    def cut(line: str, start: Optional[int] = None, end: Optional[int] = None) -> str:
        raw = line.encode('utf-8')
        return raw[start:end].decode('utf-8')

    prefix = cut(lines[node.lineno - 1], None, node.col_offset)
    suffix = cut(lines[node.end_lineno - 1], node.end_col_offset, None)
    return (node.lineno, node.end_lineno, f'{prefix}{replacement}{suffix}')


def _bootstrap_block(tree: ast.Module) -> Optional[Tuple[int, int, set, set]]:
    """Locate the `sys.path.insert(0, project_root)` bootstrap.

    Returns (start_lineno, end_lineno, names_defined, names_reused_after) or None.
    `names_reused_after` is the subset of the block's own variables that later
    code still reads — the block can only be removed when that set is empty.
    """
    for index, node in enumerate(tree.body):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_syspath_guard = (
            isinstance(test, ast.Compare)
            and test.ops and isinstance(test.ops[0], ast.NotIn)
            and test.comparators
            and isinstance(test.comparators[0], ast.Attribute)
            and test.comparators[0].attr == 'path'
        )
        if not is_syspath_guard:
            continue

        start = node.lineno
        defined: set = set()
        # Pull in the immediately preceding `current_dir` / `project_root`
        # assignments so the block reads as one unit.
        for previous in reversed(tree.body[:index]):
            if not isinstance(previous, ast.Assign):
                break
            names = {t.id for t in previous.targets if isinstance(t, ast.Name)}
            if not names & {'current_dir', 'project_root', 'parent_dir'}:
                break
            start = previous.lineno
            defined |= names

        reused = {
            n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            and n.lineno > node.end_lineno and n.id in defined
        }
        return (start, node.end_lineno, defined, reused)
    return None


# The executor runs every script with cwd=<project root> — disk and virtual alike
# (script_executor.py, `cwd=project_root` on the Popen). So os.getcwd() is the one
# location a virtual script can derive reliably; __file__ is not.
_REWRITABLE_BOOTSTRAP_NAMES = {'project_root'}


def _bootstrap_edit(tree: ast.Module, lines: List[str]) -> Optional[Tuple[int, int, str]]:
    """Neutralize the sys.path bootstrap, which is wrong for a virtual script.

    From `test_scripts/<folder>/<script>.py` the usual two `dirname` calls reach
    the project root. From `test_scripts/.vs_<uuid>.py` the file sits one level
    higher, so every count is off by one: `project_root` lands ABOVE the repo and
    `current_dir` points at `test_scripts/` instead of the script's own folder.

    Three outcomes, by what the rest of the script still reads:

    * nothing        -> comment the block out. The insert was only ever there to
                        make `import shared.src...` work, and the executor already
                        prepends the real project root to the child's PYTHONPATH.
    * project_root   -> comment it out and re-derive from `os.getcwd()`, which the
                        executor guarantees. Scripts that build a path under the
                        repo (e.g. tmp/local_debug/...) then behave identically.
    * anything else  -> leave the block alone and let _file_warnings refuse the
                        conversion. `current_dir` means "my own folder", which a
                        virtual script genuinely does not have.
    """
    block = _bootstrap_block(tree)
    if not block:
        return None
    start, end, _defined, reused = block

    if reused - _REWRITABLE_BOOTSTRAP_NAMES:
        return None

    body = lines[start - 1:end]
    commented = ''.join(f'# [virtual] {line}' if line.strip() else line for line in body)

    if not reused:
        return (start, end, commented)

    # `os` is necessarily imported — the commented block itself called os.path.
    replacement = (
        commented
        + '# [virtual] ^ replaced: this file runs from the test_scripts/ root, so the\n'
        + '# [virtual]   __file__ math above resolves one level too high. The executor\n'
        + '# [virtual]   runs every script with cwd=<project root>.\n'
        + 'project_root = os.getcwd()\n'
    )
    return (start, end, replacement)


def rewrite_source_for_virtual(
    source: str,
    lib_names: Sequence[str],
    *,
    strip_syspath_bootstrap: bool = True,
) -> Tuple[str, List[str]]:
    """Rewrite disk-script source so it runs as a virtual script.

    Rewrites `test_scripts.*` imports to the bare module name, merges `lib_names`
    into `_script_libs`, and (optionally) comments out the sys.path bootstrap.

    Returns (rewritten_source, warnings). Raises ConversionError on an import
    form that cannot be rewritten safely, or if the result does not compile.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ConversionError(ERR_SYNTAX, f'source does not parse: {e}') from e

    lines = source.splitlines(keepends=True)
    warnings: List[str] = []
    # (start_lineno, end_lineno, replacement_text), 1-indexed inclusive.
    edits: List[Tuple[int, int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if node.level or not module.startswith(f'{LOCAL_PKG}.'):
                continue
            parts = module.split('.')
            original = ''.join(lines[node.lineno - 1:node.end_lineno])

            if len(parts) >= 3:
                # `from test_scripts.gw.utils_x import (a, b)` — swap only the
                # module path, so a parenthesized multi-line name list, trailing
                # comments and indentation all survive untouched.
                replacement = original.replace(f'from {module}', f'from {parts[-1]}', 1)
            else:
                # `from test_scripts.gw import utils_x [as y]` -> plain imports.
                indent = original[:len(original) - len(original.lstrip())]
                pieces = [
                    f'{indent}import {alias.name}'
                    + (f' as {alias.asname}' if alias.asname else '')
                    for alias in node.names
                ]
                replacement = '\n'.join(pieces) + '\n'

            edits.append((node.lineno, node.end_lineno, replacement))

        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith(f'{LOCAL_PKG}.'):
                    continue
                bare = alias.name.split('.')[-1]
                if not alias.asname:
                    # `import test_scripts.gw.utils_x` then `test_scripts.gw.utils_x.f()`
                    # — the call sites use the dotted path and cannot be rewritten
                    # by touching the import line alone.
                    raise ConversionError(
                        ERR_UNSUPPORTED_IMPORT,
                        f"'import {alias.name}' without 'as' cannot be converted "
                        f"— rewrite it as 'from {bare} import ...' first",
                    )
                original = ''.join(lines[node.lineno - 1:node.end_lineno])
                indent = original[:len(original) - len(original.lstrip())]
                edits.append((node.lineno, node.end_lineno,
                              f'{indent}import {bare} as {alias.asname}\n'))

    # _script_libs: merge with whatever the file already declares.
    existing_libs: List[str] = []
    libs_node = _find_script_libs_assign(tree)
    if libs_node is not None:
        try:
            value = ast.literal_eval(libs_node.value)
            existing_libs = [v.strip() for v in value if isinstance(v, str) and v.strip()]
        except Exception:
            warnings.append('_script_libs is not a plain list literal; it was left as-is '
                            'and the detected libraries were NOT merged in')
            libs_node = None

    merged: List[str] = []
    for name in list(existing_libs) + list(lib_names):
        if name and name not in merged:
            merged.append(name)

    if merged and (libs_node is not None or lib_names):
        literal = '[' + ', '.join(f'"{n}"' for n in merged) + ']'
        if libs_node is not None:
            edits.append(_splice_node(lines, libs_node.value, literal))
        else:
            # Insert after the last top-level import — it must land in tree.body,
            # because extract_script_libs only reads top-level assignments.
            last_import_line = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    last_import_line = max(last_import_line, node.end_lineno)
            anchor = last_import_line or 0
            insertion = ('\n# Shared libraries resolved from other virtual scripts '
                         '(see docs/agent/execution/VIRTUAL_SCRIPTS.md).\n'
                         f'_script_libs = {literal}\n')
            # Pure insertion AFTER the anchor line: an empty range (start = end + 1)
            # means lines[end:end] = [text]. Replacing the anchor line instead would
            # collide with the import rewrite that usually targets the same line.
            edits.append((anchor + 1, anchor, insertion))

    if strip_syspath_bootstrap:
        bootstrap = _bootstrap_edit(tree, lines)
        if bootstrap:
            edits.append(bootstrap)

    # Apply in reverse line order so earlier offsets stay valid.
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[start - 1:end] = [replacement]

    rewritten = ''.join(lines)

    try:
        compile(rewritten, '<virtual>', 'exec')
    except SyntaxError as e:
        raise ConversionError(
            ERR_REWRITE_BROKE_SYNTAX,
            f'rewritten source does not compile (line {e.lineno}): {e.msg}',
        ) from e

    return rewritten, warnings


def _file_warnings(source: str) -> List[str]:
    """Flag path math that changes meaning once the file moves to test_scripts/ root.

    A virtual script materializes at `test_scripts/.vs_<uuid>.py`, so anything
    derived from `__file__` points at `test_scripts/` rather than the script's
    original folder, and a `project_root` computed with two `dirname` calls lands
    one level ABOVE the repo. Scripts that only used that to bootstrap sys.path
    are fine (the block is commented out, and the executor sets PYTHONPATH
    itself); scripts that go on to open a sibling data file or build a path from
    it are not, and there is no data-file mechanism for virtual scripts today.
    """
    warnings: List[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return warnings

    block = _bootstrap_block(tree)
    bootstrap_range = (block[0], block[1]) if block else None
    reused = block[3] if block else set()

    def in_bootstrap(lineno: int) -> bool:
        return bool(bootstrap_range and bootstrap_range[0] <= lineno <= bootstrap_range[1])

    # project_root is re-derived from os.getcwd() by _bootstrap_edit, so it is not
    # a problem; only the names with no virtual-script equivalent are.
    unfixable = reused - _REWRITABLE_BOOTSTRAP_NAMES
    if unfixable:
        warnings.append(
            f"reads {', '.join(sorted(unfixable))} after the sys.path bootstrap — that "
            f"means the script's OWN folder, which a virtual script does not have: it "
            f"materializes at the test_scripts/ root, so a sibling data file (e.g. "
            f"*_profiles.json) is not found. Load that file some other way before converting."
        )

    stray = sorted({
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == '__file__'
        and not in_bootstrap(node.lineno)
    })
    if stray:
        warnings.append(
            f"uses __file__ outside the sys.path bootstrap (line(s) "
            f"{', '.join(str(n) for n in stray)}) — it resolves to the test_scripts/ root "
            f"for a virtual script, not the script's original folder."
        )

    return warnings


def plan_conversion(
    script_ref: str,
    scripts_dir: str,
    *,
    include_helpers: bool = True,
    strip_syspath_bootstrap: bool = True,
    max_depth: int = 5,
    read_file: Optional[Callable[[str], str]] = None,
) -> ConversionPlan:
    """Walk the import graph from <scripts_dir>/<script_ref>.py and plan the writes.

    Cycle-safe and deduped, same contract as resolve_virtual_script_libs. Helpers
    come first in `units` so they can be written before the scripts importing them
    — a half-converted state fails at import time with a confusing error.

    Errors are collected rather than raised; a plan with any error must not be
    written.
    """
    root_ref = (script_ref or '').strip().strip('/')
    if root_ref.endswith('.py'):
        root_ref = root_ref[:-3]

    plan = ConversionPlan(root_ref=root_ref)
    reader = read_file or (lambda path: open(path, 'r', encoding='utf-8').read())

    visited: set = set()
    units_by_ref: Dict[str, ConversionUnit] = {}
    ordered: List[str] = []   # post-order: dependencies before dependents

    def visit(ref: str, depth: int, is_helper: bool) -> None:
        if ref in visited:
            return
        visited.add(ref)

        if depth > max_depth:
            plan.errors.append({'ref': ref, 'code': ERR_DEPTH_EXCEEDED,
                                'message': f'import chain deeper than {max_depth}'})
            return

        script_path = os.path.abspath(os.path.join(scripts_dir, f'{ref}.py'))
        scripts_root = os.path.abspath(scripts_dir)
        if not script_path.startswith(f'{scripts_root}{os.sep}'):
            plan.errors.append({'ref': ref, 'code': ERR_NOT_FOUND,
                                'message': 'resolves outside test_scripts/'})
            return
        if not os.path.exists(script_path):
            plan.errors.append({'ref': ref, 'code': ERR_NOT_FOUND,
                                'message': f'{ref}.py not found under {scripts_dir}'})
            return

        source = reader(script_path)

        try:
            local_imports = find_local_imports(source)
        except ConversionError as e:
            plan.errors.append({'ref': ref, 'code': e.code, 'message': e.message})
            return

        lib_names: List[str] = []
        for pkg, mod, _kind in local_imports:
            lib_names.append(mod)
            if include_helpers:
                visit(f'{pkg}/{mod}' if pkg else mod, depth + 1, True)

        try:
            rewritten, warnings = rewrite_source_for_virtual(
                source, lib_names, strip_syspath_bootstrap=strip_syspath_bootstrap)
        except ConversionError as e:
            plan.errors.append({'ref': ref, 'code': e.code, 'message': e.message})
            return

        doc_path = os.path.join(scripts_dir, f'{ref}.md')
        doc = reader(doc_path) if os.path.exists(doc_path) else None

        vs_name, folder = ref_to_name_and_folder(ref)
        units_by_ref[ref] = ConversionUnit(
            vs_name=vs_name,
            folder=folder,
            disk_ref=ref,
            source=rewritten,
            doc=doc,
            libs=lib_names,
            is_helper=is_helper,
            warnings=warnings + _file_warnings(rewritten),
        )
        ordered.append(ref)

    visit(root_ref, 0, False)

    # Virtual-script names are global per team, and _script_libs resolves by bare
    # name — two folders contributing the same basename would silently shadow
    # each other, so refuse rather than auto-suffix.
    by_name: Dict[str, str] = {}
    for ref in ordered:
        unit = units_by_ref[ref]
        clash = by_name.get(unit.vs_name)
        if clash:
            plan.errors.append({
                'ref': ref, 'code': ERR_NAME_COLLISION,
                'message': f"'{ref}' and '{clash}' both become virtual script "
                           f"'{unit.vs_name}' — rename one first",
            })
        else:
            by_name[unit.vs_name] = ref

    plan.units = [units_by_ref[ref] for ref in ordered]
    return plan
