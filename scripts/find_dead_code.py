#!/usr/bin/env python3
r"""Report unreachable files and never-imported exports in a TypeScript/JavaScript tree.

Why it is needed: nothing in the toolchain complains about a file no one imports.
`tsc` type-checks it, ESLint lints it, and a repo-wide sweep (a dependency bump, an
auth change, a URL refactor) edits it — so dead code keeps costing review time and
keeps showing up in diffs while never running. It also inflates every "how big is
this codebase" number, which makes the real size impossible to reason about.

Two questions, answered separately:

  --files    Which files are unreachable from the entry points? This walks the import
             graph forward from main.tsx/App.tsx rather than grepping for basenames.
             Grepping cannot tell a barrel file (`components/foo/index.ts`, imported
             as the directory `../foo`) from a genuinely orphaned one, and reports
             every barrel as dead. Resolving specifiers the way the bundler does is
             the only way to get this right.

  --exports  Which exported symbols are never referenced outside the file that
             defines them? These are weaker signals — usually a type that wants to be
             local, sometimes an API built for a caller that never arrived. Worth
             skimming, not worth a blanket deletion.

Scan `frontend/src` and `features/*/frontend` together, which is the default. They are
one graph, not two: `frontend/vite.config.ts` synthesises a module with a static import
of every `features/<name>/frontend/routes.tsx`, so each of those is an entry point, and
feature code imports freely out of `frontend/src`. Scanning only `frontend/src` reports
anything used solely by a feature as dead — `types/pages/TestCase_Types.ts` is imported
by `features/quicktest` and by nothing else, and a frontend-only scan calls it orphaned.

Two caveats, both of which mean the file list is a starting point and not a delete
queue:

  - A specifier built at runtime (an `import()` with an interpolated path) is invisible
    here. This repo does not currently do that, but a future one would need checking.
  - `vite-env.d.ts` and other ambient .d.ts files are reachable by nobody by design;
    they are excluded, and any new ambient file must be added to KEEP.

Usage:
    python scripts/find_dead_code.py [path ...] [--files] [--exports]

Defaults to frontend/src plus every features/*/frontend, and to showing both. Exits 0
always — this reports, it does not gate.

**Orphans marked `[+test]` have a test importing them.** Those are still dead — a test
is not a user — but the test has to be deleted in the same commit or the suite breaks
with "Failed to resolve import". This is not hypothetical: the 2026-09-30 deletion took
`tests/frontend` from 10 failing files to 15 by removing five pages whose tests were
never looked at, because the scan roots did not include the test tree and an import
from a test was therefore invisible.
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTS = ('.ts', '.tsx', '.js', '.jsx')
SKIP_DIRS = {'node_modules', 'dist', 'build', '.git', 'coverage'}

# Entry points: reachability is measured from these. `routes.tsx` is here because
# vite.config.ts static-imports one per feature folder, making each an entry the same
# way main.tsx is. The cost is that a feature whose whole routes.tsx went unused would
# not be reported; the benefit is that no feature's dependencies look dead.
ENTRIES = ('main.tsx', 'main.ts', 'App.tsx', 'index.tsx', 'routes.tsx')

# Files that are legitimately imported by nobody. Ambient declarations are picked up
# by tsconfig's `include`, not by an import statement.
KEEP = ('vite-env.d.ts',)

# Where the tests live. Scanned as a side channel, NOT as entry points: a test importing
# a page does not make the page reachable from the app — it makes it dead code with a
# dead test attached. Treating tests as entries would hide exactly the pages worth
# deleting.
TEST_ROOTS = (REPO_ROOT / 'tests' / 'frontend',)
_IS_TEST = re.compile(r'\.(test|spec)\.[jt]sx?$')

_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*['"]([^'"]+)['"]""")
_EXPORT = re.compile(
    r'^export\s+(?:default\s+)?(?:async\s+)?(?:const|function|class|interface|type|enum)\s+([A-Za-z0-9_$]+)',
    re.M,
)
_IDENT = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')


def collect(roots):
    src = {}
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if name.endswith(EXTS) and not name.endswith(KEEP):
                    p = os.path.abspath(os.path.join(dirpath, name))
                    try:
                        src[p] = Path(p).read_text(encoding='utf-8', errors='ignore')
                    except OSError:
                        continue
    return src


def resolve(specifier, importer, alias_root, src):
    """The file a specifier points at, or None for a package import.

    Mirrors the bundler's extension and index resolution: `./foo` may be foo.ts,
    foo.tsx, foo/index.ts or foo/index.tsx. Order matters — a directory containing
    both foo.ts and foo/ resolves to the file.
    """
    if specifier.startswith('.'):
        base = os.path.normpath(os.path.join(os.path.dirname(importer), specifier))
    elif specifier.startswith(('@/', 'src/')):
        # Aliases always point into frontend/src, including from a feature folder.
        base = os.path.normpath(os.path.join(alias_root, specifier.split('/', 1)[1]))
    else:
        return None  # a node_modules package
    for candidate in (base + '.ts', base + '.tsx', base + '.js', base + '.jsx',
                      os.path.join(base, 'index.ts'), os.path.join(base, 'index.tsx'),
                      base):
        if candidate in src:
            return candidate
    return None


def unreachable_files(alias_root, src):
    """Files not reachable from any entry point, by forward walk of the import graph.

    A forward walk, not a reverse one: a cluster of dead files that import each other
    would each look "imported" to a reverse check, and the whole cluster would hide.
    """
    edges = defaultdict(set)
    for path, text in src.items():
        for m in _IMPORT.finditer(text):
            target = resolve(m.group(1), path, alias_root, src)
            if target:
                edges[path].add(target)

    roots = [p for p in src if os.path.basename(p) in ENTRIES]
    seen, stack = set(roots), list(roots)
    while stack:
        cur = stack.pop()
        for nxt in edges[cur]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return sorted(p for p in src if p not in seen)


def unused_exports(src):
    """Exports whose name never appears in any other file.

    Identifier counting, not import parsing: a re-export through a barrel means the
    name appears in the barrel, which is enough to call it used. That errs toward
    under-reporting, which is the right direction for a signal meant to be skimmed.
    """
    tokens = {p: Counter(_IDENT.findall(t)) for p, t in src.items()}
    total = Counter()
    for c in tokens.values():
        total.update(c)
    out = []
    for path, text in src.items():
        for m in _EXPORT.finditer(text):
            name = m.group(1)
            if total[name] - tokens[path][name] == 0:
                out.append((path, name))
    return out


def tests_importing(orphans, src, alias_root):
    """orphan path -> set of test files importing it.

    The test tree is read here rather than added to the scan roots. Tests are never
    imported by anything, so as scan roots they would all report as orphans; as entry
    points they would make every page they cover look reachable, hiding the ones worth
    deleting. Neither is what is wanted — what is wanted is to know that deleting the
    page means deleting its test too.
    """
    orphan_set = set(orphans)
    hits = defaultdict(set)
    graph = dict(src)
    for root in TEST_ROOTS:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if not _IS_TEST.search(name):
                    continue
                tp = os.path.abspath(os.path.join(dirpath, name))
                try:
                    text = Path(tp).read_text(encoding='utf-8', errors='ignore')
                except OSError:
                    continue
                # Resolve the test's specifiers against the scanned graph plus itself,
                # so a relative "../../frontend/src/pages/X" lands on the real file.
                graph[tp] = text
                for m in _IMPORT.finditer(text):
                    target = resolve(m.group(1), tp, alias_root, graph)
                    if target in orphan_set:
                        hits[target].add(tp)
                graph.pop(tp, None)
    return hits


def loc(path):
    return len(Path(path).read_text(encoding='utf-8', errors='ignore').splitlines())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path', nargs='*', help='defaults to frontend/src + features/*/frontend')
    ap.add_argument('--files', action='store_true', help='only unreachable files')
    ap.add_argument('--exports', action='store_true', help='only unused exports')
    args = ap.parse_args()
    show_files = args.files or not args.exports
    show_exports = args.exports or not args.files

    alias_root = str(REPO_ROOT / 'frontend' / 'src')
    if args.path:
        roots = [os.path.abspath(p) for p in args.path]
    else:
        roots = [alias_root] + [str(p) for p in sorted((REPO_ROOT / 'features').glob('*/frontend'))]
    for r in roots:
        if not os.path.isdir(r):
            sys.exit(f'not a directory: {r}')

    src = collect(roots)
    if not src:
        sys.exit('no source files under: ' + ', '.join(roots))
    rel = lambda p: os.path.relpath(p, REPO_ROOT)

    if show_files:
        orphans = unreachable_files(alias_root, src)
        tested = tests_importing(orphans, src, alias_root)
        lines = sum(loc(p) for p in orphans)
        print(f'Scanned {len(src)} files in {len(roots)} root(s)')
        print(f'=== Unreachable from {", ".join(ENTRIES)}: {len(orphans)} files, {lines} lines ===')
        for p in orphans:
            mark = f'  [+test] {", ".join(sorted(rel(t) for t in tested[p]))}' if tested[p] else ''
            print(f'  {loc(p):5d}  {rel(p)}{mark}')
        if any(tested.values()):
            print()
            print('  [+test] = a test imports this. Still dead, but delete the test in the')
            print('            same commit or the suite breaks on an unresolved import.')
        print()

    if show_exports:
        unused = unused_exports(src)
        print(f'=== Exports never referenced outside their own file: {len(unused)} ===')
        by_file = defaultdict(list)
        for path, name in unused:
            by_file[rel(path)].append(name)
        for path, names in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:25]:
            head = ', '.join(names[:5]) + ('...' if len(names) > 5 else '')
            print(f'  {len(names):3d}  {path} -> {head}')


if __name__ == '__main__':
    main()
