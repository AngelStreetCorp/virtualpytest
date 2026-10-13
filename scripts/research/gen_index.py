#!/usr/bin/env python3
"""Rebuilds docs/research/INDEX.md from every docs/tasks/*/results.tsv: one row per task with its
metric, best value, kept/total and last run. Run after a research session."""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from loop import ROOT, best_kept, find_doc, parse_spec, read_rows  # noqa: E402


def main() -> int:
    rows_out = []
    for tsv in sorted(glob.glob(os.path.join(ROOT, 'docs', 'tasks', '*', 'results.tsv'))):
        task = os.path.basename(os.path.dirname(tsv))
        rows = read_rows(tsv)
        try:
            doc = find_doc(task, ROOT)
            spec = parse_spec(task, open(doc, encoding='utf-8').read(), os.path.relpath(doc, ROOT))
            metric, higher, docrel = spec.metric_name, spec.higher, spec.doc
        except SystemExit:
            metric, higher, docrel = '?', True, ''
        best = best_kept(rows, higher)
        kept = sum(1 for r in rows if r.get('kept') == 'yes')
        last = rows[-1] if rows else None
        link = f'[{task}]({os.path.relpath(doc, os.path.join(ROOT, "docs", "research"))})' if docrel else task
        rows_out.append(f'| {link} | {metric} | {best["metric"] if best else "-"} | {kept}/{len(rows)} | '
                        f'{last["ts"] if last else "-"} | {(last["note"] if last else "")[:60]} |')
    out = ['# Research index', '',
           'Every task with a `## Loop` and at least one try. Regenerate with `python3 scripts/research/gen_index.py`.',
           'Convention: `docs/agent/research/LOOP.md`.', '',
           '| task | metric | best | kept/tries | last run | last note |', '|---|---|---|---|---|---|',
           *rows_out, '']
    path = os.path.join(ROOT, 'docs', 'research', 'INDEX.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print(f'{path}: {len(rows_out)} task(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
