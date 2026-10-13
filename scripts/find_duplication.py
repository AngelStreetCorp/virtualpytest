#!/usr/bin/env python3
"""Report copy-pasted blocks in a source tree (TypeScript/JavaScript or Python).

Why it is needed: `count_lines.py` answers "how much code is there", which on its own
says nothing about whether the code is good. A large tree is only a problem if the
size comes from the same logic written repeatedly. This answers that second question
directly — what share of the tree sits inside a block that also exists somewhere else.

Method: every file is reduced to its *effective* lines (blank lines and comments
dropped, runs of whitespace collapsed), then a sliding window of WINDOW effective
lines is hashed. Two windows with the same hash are the same code modulo formatting.
Hashing normalized windows rather than diffing file pairs is what keeps this O(n)
instead of O(n^2) — the frontend alone is 630 files, and a pairwise diff of those
takes minutes where this takes seconds.

Reading the output: not every hit is a defect. Three kinds show up, and only the
third is worth acting on:

  - Import blocks and JSX prop lists. `<ConfirmDialog open=... title=... />` repeated
    across 16 pages is MUI boilerplate, not duplicated logic.
  - Config tables. `config/remote/*.ts` are key layouts that genuinely repeat; the
    duplication is in the data, and collapsing it would only obscure it.
  - Repeated *logic* — the same fetch-and-cache, the same branch, the same handler.
    That is the kind that drifts, and the kind this script exists to surface.

The per-file table at the end is the useful half: a file that is 40% duplicated is
one where someone copied a section rather than looping over it.

Python is scanned too, with the same method — a larger `--window` suits it better, since
Python's lower line-noise means 12 lines of it carry more meaning than 12 lines of JSX:

    python scripts/find_duplication.py backend_host/src --window 20

Usage:
    python scripts/find_duplication.py [path] [--window N] [--min-chars N]

Defaults to frontend/src. Exits 0 always — this reports, it does not gate.
"""
import argparse
import hashlib
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTS = ('.ts', '.tsx', '.js', '.jsx', '.py')
SKIP_DIRS = {'node_modules', 'dist', 'build', '.git', 'coverage', '__pycache__', 'venv', '.venv'}

# Comment prefixes, by language. A line starting with one of these carries no code.
# `*` and `/*` cover the continuation lines of a JSDoc block; `#` covers Python.
COMMENT_PREFIXES = ('//', '*', '/*', '#')

# A window shorter than this is too small to be meaningful: any two files that both
# destructure a few props will collide.
DEFAULT_WINDOW = 12

# Twelve lines of `}` and `});` hash identically everywhere and mean nothing. Requiring
# the window to carry real text filters that out without needing a syntax parser.
DEFAULT_MIN_CHARS = 200

_WS = re.compile(r'\s+')


def effective_lines(text):
    """(line_number, normalized_text) for lines that carry code.

    Comments are dropped by prefix rather than by parsing: a `/* ... */` block whose
    continuation lines do not start with `*` will leak a line or two through, and a
    Python docstring is kept as code. That is acceptable here — a false positive costs a
    glance, and a real parser costs a dependency this repo does not otherwise need.
    Note the one consequence worth knowing: two files sharing a long copied docstring
    will register as duplicated, which is usually a true finding anyway.
    """
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith(COMMENT_PREFIXES):
            continue
        out.append((i, _WS.sub(' ', s)))
    return out


def collect(root):
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(EXTS):
                continue
            p = os.path.join(dirpath, name)
            try:
                files[p] = effective_lines(Path(p).read_text(encoding='utf-8', errors='ignore'))
            except OSError:
                continue
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path', nargs='?', default=str(REPO_ROOT / 'frontend' / 'src'))
    ap.add_argument('--window', type=int, default=DEFAULT_WINDOW,
                    help=f'block size in effective lines (default {DEFAULT_WINDOW})')
    ap.add_argument('--min-chars', type=int, default=DEFAULT_MIN_CHARS,
                    help=f'ignore windows with less text than this (default {DEFAULT_MIN_CHARS})')
    ap.add_argument('--top', type=int, default=25, help='how many clone groups to print')
    args = ap.parse_args()

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        sys.exit(f'not a directory: {root}')

    files = collect(root)
    if not files:
        sys.exit(f'no {"/".join(EXTS)} files under {root}')

    buckets = defaultdict(list)
    for path, lines in files.items():
        for i in range(len(lines) - args.window + 1):
            block = '\n'.join(t for _, t in lines[i:i + args.window])
            if len(block) < args.min_chars:
                continue
            h = hashlib.md5(block.encode()).hexdigest()
            buckets[h].append((path, lines[i][0], lines[i + args.window - 1][0]))

    clones = {h: occ for h, occ in buckets.items() if len(occ) > 1}

    # Overlapping windows are merged by counting distinct line numbers rather than
    # windows: a 30-line copied section produces ~19 overlapping hits at window 12,
    # and counting those as 19 would wildly overstate the duplication.
    dup_lines = defaultdict(set)
    for occ in clones.values():
        for path, start, end in occ:
            dup_lines[path].update(range(start, end + 1))

    total = sum(len(v) for v in files.values())
    dup = sum(len(v) for v in dup_lines.values())
    print(f'Scanned:   {len(files)} files under {os.path.relpath(root, REPO_ROOT)}')
    print(f'Effective: {total} lines (blank and comment lines excluded)')
    print(f'Duplicated: {dup} lines in a >= {args.window}-line repeated block '
          f'({100.0 * dup / total:.1f}%)')
    print()

    print(f'=== Most-repeated blocks (top {args.top}) ===')
    ranked = sorted(clones.items(), key=lambda kv: -len(kv[1]))
    seen_groups = set()
    shown = 0
    for _, occ in ranked:
        group = tuple(sorted({p for p, _, _ in occ}))
        if group in seen_groups:
            continue
        seen_groups.add(group)
        if len(occ) < 3 and len(group) < 3:
            continue
        print(f'\n[{len(occ)} copies across {len(group)} file(s)]')
        for path, start, end in occ[:8]:
            print(f'   {os.path.relpath(path, root)}:{start}-{end}')
        if len(occ) > 8:
            print(f'   ... +{len(occ) - 8} more')
        shown += 1
        if shown >= args.top:
            break

    print()
    print('=== Files with the most duplicated lines ===')
    ranked_files = sorted(dup_lines.items(), key=lambda kv: -len(kv[1]))[:30]
    for path, lines in ranked_files:
        total_f = len(files[path])
        print(f'{len(lines):6d} dup / {total_f:6d} lines ({100.0 * len(lines) / total_f:5.1f}%)  '
              f'{os.path.relpath(path, root)}')


if __name__ == '__main__':
    main()
