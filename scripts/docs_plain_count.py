#!/usr/bin/env python3
"""Plain-layer word count of docs pages (prose outside <div data-technical> blocks, code fences and tables).

Usage: docs_plain_count.py <repo> <page.md> [...]   # prints old prose words (main), plain words now, target (60 %, floor 250)
Exit 1 when a page's plain layer is over its target, so an agent can loop until it passes.
"""
import re, subprocess, sys


def words(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*\|.*$", "", text)  # tables are values, not prose
    text = re.sub(r"<[^>]+>", " ", text)
    return len(re.findall(r"[A-Za-z0-9][\w'’.-]*", text))


repo, pages = sys.argv[1], sys.argv[2:]
over = 0
for p in pages:
    old = subprocess.run(['git', '-C', repo, 'show', f'main:{p}'], capture_output=True, text=True).stdout
    new = open(f'{repo}/{p}').read()
    plain = re.sub(r"<div data-technical>.*?</div>", "", new, flags=re.S)
    o, n = words(old), words(plain)
    target = max(250, int(o * 0.6))
    ok = n <= target * 1.1
    over += not ok
    print(f"{'OK  ' if ok else 'OVER'} {p}: old {o} -> plain {n} (target <= {target})")
sys.exit(1 if over else 0)
