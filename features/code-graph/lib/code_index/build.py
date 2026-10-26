"""Walk the repo, scan every file, resolve each call site to a confidence tag."""
import os
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from dataclasses import replace
from typing import Callable, Optional, Dict, List

from .constants import (
    DEF_LINE_PREFIXES, HINT_MAX_HOPS, MENTION_CALL_SLACK, MENTION_TOKEN_RE, PAUSE_EVERY_FILES, PY_SUFFIX, RES_AMBIGUOUS, RES_EXTERNAL, RES_IMPORT, RES_LOCAL, RES_SELF, RES_TYPED,
    RES_UNIQUE, SKIP_DIRS, TS_SUFFIXES,
)
from .python_scan import scan_python
from .ts_scan import scan_ts_urls
from .types import CallSite, CodeIndex, FileScan, RouteDef


def _git_dirs(repo: str):
    """(dir holding HEAD, dir holding refs): both .git, or a worktree's gitdir and its common dir."""
    dot_git = os.path.join(repo, ".git")
    if not os.path.isfile(dot_git):
        return dot_git, dot_git
    with open(dot_git, encoding="utf-8") as fh:
        gitdir = os.path.join(repo, fh.read().strip()[len("gitdir: "):])
    common = gitdir
    common_file = os.path.join(gitdir, "commondir")
    if os.path.isfile(common_file):
        with open(common_file, encoding="utf-8") as fh:
            common = os.path.normpath(os.path.join(gitdir, fh.read().strip()))
    return gitdir, common


def git_head(repo: str) -> str:
    """Version of the checkout: the git commit (read without spawning git, worktrees too), else the first line
    of VERSION.txt when there is no readable .git (deployed copies)."""
    head = _git_commit(repo)
    if head:
        return head
    try:
        with open(os.path.join(repo, "VERSION.txt"), encoding="utf-8") as fh:
            return fh.readline().strip().replace("current:", "")
    except OSError:
        return ""


def _git_commit(repo: str) -> str:
    try:
        head_dir, refs_dir = _git_dirs(repo)
        with open(os.path.join(head_dir, "HEAD"), encoding="utf-8") as fh:
            head = fh.read().strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        ref_file = os.path.join(refs_dir, ref)
        if os.path.isfile(ref_file):
            with open(ref_file, encoding="utf-8") as fh:
                return fh.read().strip()
        packed = os.path.join(refs_dir, "packed-refs")
        with open(packed, encoding="utf-8") as fh:
            for line in fh:
                if line.strip().endswith(ref):
                    return line.split()[0]
    except OSError:
        pass
    return ""


def _iter_files(repo: str):
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(PY_SUFFIX) or name.endswith(TS_SUFFIXES):
                full = os.path.join(dirpath, name)
                yield full, os.path.relpath(full, repo).replace(os.sep, "/")


class _TypeResolver:
    """Turns a receiver hint into a class name across files: Cls(...) builds a Cls, f() returns what f is
    annotated or seen to return, a test parameter is the fixture of that name, self.x is what was stored."""

    def __init__(self, defs: Dict[str, list], attr_hints: Dict[str, str]):
        self.defs = defs
        self.attr_hints = attr_hints
        self.classes = {n for n, ds in defs.items() if any(d.kind == "class" for d in ds)}
        self.bases = {n: {b for d in defs[n] if d.kind == "class" for b in d.bases} for n in self.classes}
        self.memo: Dict[tuple, str] = {}

    def ancestors(self, cls: str) -> set:
        """cls and every class it derives from (by name)."""
        seen, todo = set(), [cls]
        while todo:
            c = todo.pop()
            if c not in seen:
                seen.add(c)
                todo.extend(self.bases.get(c, ()))
        return seen

    def resolve(self, hint: str, file: str, hops: int = 0) -> str:
        if not hint or hops > HINT_MAX_HOPS:
            return ""
        key = (hint, file)
        if key not in self.memo:
            self.memo[key] = ""  # cycle guard
            self.memo[key] = self._resolve(hint, file, hops)
        return self.memo[key]

    def _one(self, hints, file, hops) -> str:
        found = {self.resolve(h, file, hops + 1) for h in hints if h}
        found.discard("")
        return found.pop() if len(found) == 1 else ""

    def _resolve(self, hint: str, file: str, hops: int) -> str:
        kind, _, name = hint.partition(":")
        if kind == "class":
            return name if name in self.classes else ""
        if kind == "call":
            if name in self.classes:
                return name
            return self._one([d.returns for d in self.defs.get(name, []) if d.kind != "class"], file, hops)
        if kind == "param":
            fixtures = [d for d in self.defs.get(name, []) if d.fixture]
            here = [d for d in fixtures if d.file == file]
            return self._one([d.returns for d in (here or fixtures)], file, hops)
        if kind == "selfattr":
            return self.resolve(self._attr_hint(name), file, hops + 1)
        if kind == "attr":  # y.attr / getattr(y, "attr"): the attribute's type on y's class
            obj, _, attr = name.rpartition("|")
            cls = self.resolve(obj, file, hops + 1)
            return self.resolve(self._attr_hint(f"{cls}.{attr}"), file, hops + 1) if cls else ""
        if kind == "elem":  # self.items[k] / y.items.get(k): one item of a stored container
            hint = self._stored_hint(name, file, hops)
            return self.resolve(hint[len("items:"):], file, hops + 1) if hint.startswith("items:") else ""
        return ""

    def _stored_hint(self, hint: str, file: str, hops: int) -> str:
        """The hint stored for an attribute reference: 'selfattr:C.a' or 'attr:<obj hint>|a'."""
        kind, _, name = hint.partition(":")
        if kind == "selfattr":
            return self._attr_hint(name)
        if kind == "attr":
            obj, _, attr = name.rpartition("|")
            cls = self.resolve(obj, file, hops + 1)
            return self._attr_hint(f"{cls}.{attr}") if cls else ""
        return ""

    def _attr_hint(self, cls_attr: str) -> str:
        """Hint stored for 'Class.attr', looking in the class first, then its bases."""
        found = self.attr_hints.get(cls_attr)
        if found:
            return found
        cls, _, attr = cls_attr.partition(".")
        for base in sorted(self.ancestors(cls) - {cls}):
            found = self.attr_hints.get(f"{base}.{attr}")
            if found:
                return found
        return ""


def _resolve(call: CallSite, scan: FileScan, defs_by_name: Dict[str, list], file_defs: set,
             receiver_types: frozenset = frozenset()) -> str:
    candidates = defs_by_name.get(call.name, [])
    if not candidates:
        return RES_EXTERNAL
    if receiver_types and call.receiver not in ("self", "cls") \
            and any(d.owner in receiver_types for d in candidates):
        return RES_TYPED
    if call.receiver in ("self", "cls"):
        owner = call.enclosing.split(".")[0]
        if any(d.file == call.file and d.owner == owner for d in candidates):
            return RES_SELF
    if not call.receiver:
        if call.name in file_defs:
            return RES_LOCAL
        source = scan.imported_names.get(call.name, "")
        if source and any(source.endswith("." + call.name) and _module_of(d.file) == source.rsplit(".", 1)[0]
                          for d in candidates):
            return RES_IMPORT
    elif call.receiver in scan.imported_names:
        # module.func(...) where module was imported
        mod = scan.imported_names[call.receiver]
        if any(_module_of(d.file) == mod for d in candidates):
            return RES_IMPORT
    return RES_UNIQUE if len(candidates) == 1 else RES_AMBIGUOUS


def _module_of(rel_file: str) -> str:
    parts = rel_file[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class _BlueprintPrefixes:
    """url_prefix given at `register_blueprint(bp, url_prefix=...)` (and nested blueprints) over the one in
    `Blueprint(..., url_prefix=...)`. A blueprint is a (file, variable); an imported one is followed to its file."""

    def __init__(self, scans: List[FileScan], module_files: Dict[str, str]):
        self.by_file = {s.file: s for s in scans}
        self.module_files = module_files
        self.by_suffix: Dict[str, List[str]] = defaultdict(list)  # 'routes.x' -> files of 'backend.src.routes.x'
        for mod, f in module_files.items():
            parts = mod.split(".")
            for i in range(1, len(parts)):
                self.by_suffix[".".join(parts[i:])].append(f)
        self.regs: Dict[tuple, list] = defaultdict(list)  # child -> [(parent or None, url_prefix or None)]
        for s in scans:
            for parent, child, prefix in s.registrations:
                child_key = self.resolve(s.file, child)
                if child_key:
                    self.regs[child_key].append((self.resolve(s.file, parent) if parent else None, prefix))
        self.memo: Dict[tuple, list] = {}

    def _file_of(self, module: str) -> str:
        if module in self.module_files:
            return self.module_files[module]
        found = self.by_suffix.get(module, [])
        return found[0] if len(found) == 1 else ""

    def resolve(self, file: str, dotted: str, hops: int = 0) -> Optional[tuple]:
        """(file, variable) of the blueprint a name in `file` stands for, or None when it is not one."""
        scan = self.by_file.get(file)
        if not scan or hops > HINT_MAX_HOPS:
            return None
        head, _, attr = dotted.partition(".")
        if not attr and head in scan.blueprints:
            return file, head
        source = scan.imported_names.get(head, "")
        if not source:
            return None
        if attr:  # module.bp
            target = self._file_of(source)
            return self.resolve(target, attr, hops + 1) if target and "." not in attr else None
        module, _, var = source.rpartition(".")
        target = self._file_of(module)
        return self.resolve(target, var, hops + 1) if target else None

    def prefixes(self, key: tuple, seen: tuple = ()) -> List[str]:
        """Every url_prefix `key` is mounted under (its own when it is never registered with another)."""
        if key in self.memo:
            return self.memo[key]
        own = self.by_file[key[0]].blueprints.get(key[1], "")
        out = []
        for parent, prefix in self.regs.get(key, []):
            mine = own if prefix is None else prefix
            if parent and parent != key and parent not in seen:
                out += [(p.rstrip("/") + "/" + mine.lstrip("/")) if p else mine for p in self.prefixes(parent, seen + (key,))]
            else:
                out.append(mine)
        self.memo[key] = out = list(dict.fromkeys(out)) or [own]
        return out

    def apply(self, route: RouteDef) -> List[RouteDef]:
        if not route.bp or not (route.rest.startswith("/") or not route.rest):
            return [route]
        key = self.resolve(route.file, route.bp)
        if not key:
            return [route]
        return [replace(route, path=p + route.rest) for p in self.prefixes(key)]


def _index_mentions(repo: str, index: CodeIndex, scans: List[FileScan], pause: Callable[[], None]) -> None:
    """Second read of the Python files: record, for every name defined in the repo, the `name(` lines that are not
    AST calls or defs (comments, docstrings, strings) and the longer names ending in it (`fake_call_host`)."""
    explained: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))  # name -> file -> call line starts
    for name, cs in index.calls.items():
        for c in cs:
            explained[name][c.file].append(c.line)
    def_lines: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for name, ds in index.defs.items():
        for d in ds:
            def_lines[name][d.file].add(d.line)

    def is_explained(name: str, file: str, lineno: int) -> bool:
        """The line is a def, or lies within a few lines after the start of a call of `name` (a multi-line call)."""
        return lineno in def_lines.get(name, {}).get(file, ()) or \
            any(0 <= lineno - start <= MENTION_CALL_SLACK for start in explained.get(name, {}).get(file, ()))

    suffix_memo: Dict[str, tuple] = {}

    def defined_suffixes(token: str) -> tuple:
        found = suffix_memo.get(token)
        if found is None:
            found = tuple(token[i:] for i in range(len(token)) if token[i:] in index.defs)
            suffix_memo[token] = found
        return found

    hits: Dict[str, List[tuple]] = defaultdict(list)
    longer: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for n, s in enumerate(sorted(scans, key=lambda s: s.file)):
        if n % PAUSE_EVERY_FILES == 0:
            pause()
        try:
            with open(os.path.join(repo, s.file), encoding="utf-8", errors="ignore") as fh:
                source = fh.read()
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if "(" not in line:
                continue
            per_name: Dict[str, List[str]] = {}
            for token in MENTION_TOKEN_RE.findall(line):
                for name in defined_suffixes(token):
                    per_name.setdefault(name, []).append(token)
            for name, tokens in per_name.items():
                for token in tokens:  # in line order; the first plain mention that is no call/def ends the line
                    if token != name:
                        longer[name][token].add(s.file)
                    elif not is_explained(name, s.file, lineno) and not line.lstrip().startswith(DEF_LINE_PREFIXES):
                        hits[name].append((s.file, lineno))
                        break
    index.text_hits = dict(hits)
    index.longer_names = {name: {t: tuple(sorted(fs)) for t, fs in by.items()} for name, by in longer.items()}


def build_index(repo: str, pause: Optional[Callable[[], None]] = None) -> CodeIndex:
    """Scan the checkout. `pause` (e.g. gevent.sleep) is called every few files so a cooperative server keeps
    serving other requests while this runs in one of its greenlets."""
    pause = pause or (lambda: None)
    scans: List[FileScan] = []
    index = CodeIndex(repo=repo, built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      git_head=git_head(repo))
    for full, rel in _iter_files(repo):
        try:
            with open(full, encoding="utf-8", errors="ignore") as fh:
                source = fh.read()
        except OSError:
            continue
        index.files_scanned += 1
        if index.files_scanned % PAUSE_EVERY_FILES == 0:
            pause()
        if rel.endswith(PY_SUFFIX):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)  # bad escapes in scanned files
                scan = scan_python(rel, source)
            if scan:
                scans.append(scan)
        else:
            index.urls.extend(scan_ts_urls(rel, source))

    defs = defaultdict(list)
    for s in scans:
        index.module_files[s.module] = s.file
        for d in s.definitions:
            defs[d.name].append(d)
    index.defs = dict(defs)

    attr_hints: Dict[str, str] = {}
    for s in scans:
        attr_hints.update(s.attr_hints)
    types = _TypeResolver(index.defs, attr_hints)

    blueprints = _BlueprintPrefixes(scans, index.module_files)
    calls = defaultdict(list)
    importers = defaultdict(set)
    for n, s in enumerate(scans):
        if n % PAUSE_EVERY_FILES == 0:
            pause()
        file_defs = {d.name for d in s.definitions if d.kind != "method"}
        for c in s.calls:
            if c.name not in index.defs:
                continue  # stdlib / third party: keeps the index small
            rtype = types.resolve(c.receiver_hint, c.file) if c.receiver_hint else ""
            calls[c.name].append(CallSite(c.name, c.file, c.line, c.enclosing, c.receiver,
                                          _resolve(c, s, index.defs, file_defs,
                                                   frozenset(types.ancestors(rtype)) if rtype else frozenset()),
                                          receiver_type=rtype))
        index.imported_names[s.file] = s.imported_names
        for m in s.imported_modules:
            importers[m].add(s.file)
        for source in s.imported_names.values():
            if source in index.module_files:  # `from pkg import module`
                importers[source].add(s.file)
        for r in s.routes:
            index.routes.extend(blueprints.apply(r))
        index.urls.extend(s.urls)
    index.calls = dict(calls)
    index.importers = {k: sorted(v) for k, v in importers.items()}
    _index_mentions(repo, index, scans, pause)
    return index
