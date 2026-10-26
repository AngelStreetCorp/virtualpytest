#!/usr/bin/env python3
"""Build the code reference index and answer one code_refs query, same text as the MCP tool.

  python3 features/code-graph/scripts/gen_code_index.py --query call_host [--depth 2]
  python3 features/code-graph/scripts/gen_code_index.py            # index stats only
"""
import argparse
import hashlib
import importlib
import os
import pickle
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
query = importlib.import_module('features.code-graph.lib.code_index.query')
store = importlib.import_module('features.code-graph.lib.code_index.store')
build = importlib.import_module('features.code-graph.lib.code_index.build')
CACHE_DIR = os.path.expanduser('~/.cache/vpt-code-refs')


def _cached_index(repo: str):
    """The server keeps the index in memory; the CLI keeps one pickle per repo + git HEAD (~1 s instead of ~15 s)."""
    head = build.git_head(repo)
    if not head:
        return store.get_index(repo)
    key = hashlib.sha1(os.path.abspath(repo).encode()).hexdigest()[:12]
    path = os.path.join(CACHE_DIR, f'{key}-{head}.pickle')
    try:
        with open(path, 'rb') as fh:
            return pickle.load(fh)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError):
        pass
    index = store.get_index(repo)
    os.makedirs(CACHE_DIR, exist_ok=True)
    for old in os.listdir(CACHE_DIR):
        if old.startswith(key + '-'):
            os.remove(os.path.join(CACHE_DIR, old))
    with open(path + '.tmp', 'wb') as fh:
        pickle.dump(index, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(path + '.tmp', path)
    return index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--query', help="name, Class.method, module, or /server/... URL")
    ap.add_argument('--depth', type=int, default=1)
    ap.add_argument('--no-tests', action='store_true', help='drop test files')
    ap.add_argument('--max-files', type=int, default=60)
    ap.add_argument('--repo', default=str(ROOT), help='repo to index (default: this checkout)')
    args = ap.parse_args()

    t0 = time.time()
    index = _cached_index(args.repo)
    if not args.query:
        print(f"files {index.files_scanned} defs {sum(map(len, index.defs.values()))} "
              f"calls {sum(map(len, index.calls.values()))} routes {len(index.routes)} urls {len(index.urls)} "
              f"head {index.git_head[:9] or 'no-git'} built in {time.time() - t0:.1f}s")
        return 0
    print(query.code_refs(index, args.query, depth=args.depth, include_tests=not args.no_tests,
                          max_files=args.max_files))
    return 0


if __name__ == '__main__':
    sys.exit(main())
