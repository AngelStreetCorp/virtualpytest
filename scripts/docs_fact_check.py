#!/usr/bin/env python3
"""Check a rewritten docs page kept every fact: code lines, inline code, links, numbers.

Usage: docs_fact_check.py <repo> <path/to/page.md> [...]
Compares each page against `git show main:<path>`. Prints what is missing; exit 1 if anything is.
"""
import re, subprocess, sys

repo, pages = sys.argv[1], sys.argv[2:]


def facts(text):
    out = set()
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, re.S):
        out |= {('code', l.strip()) for l in block.splitlines() if l.strip()}
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    out |= {('inline', m) for m in re.findall(r"`([^`\n]+)`", prose)}
    out |= {('link', m) for m in re.findall(r"\]\(([^)\s]+)\)", text)}
    out |= {('number', m) for m in re.findall(r"\b\d+(?:[.,]\d+)?\s?(?:GB|MB|TB|%|ms|s|min|vCPU|cores?)\b", prose)}
    return out


def norm(text):
    return re.sub(r"\s+", " ", text)


bad = 0
for p in pages:
    old = subprocess.run(['git', '-C', repo, 'show', f'main:{p}'], capture_output=True, text=True).stdout
    new = open(f'{repo}/{p}').read()
    new_n = norm(new)
    missing = [f for f in sorted(facts(old)) if norm(f[1]) not in new_n]
    status = 'OK' if not missing else f'{len(missing)} missing'
    print(f'{p}: {status}')
    for kind, val in missing:
        print(f'   - {kind}: {val}')
    bad += bool(missing)
sys.exit(1 if bad else 0)
