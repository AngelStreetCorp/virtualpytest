"""Phase 4, anywhere: Jev's accuracy by class and confidence, against a fitted no-AI threshold."""
import os
from collections import Counter
from typing import Any, Dict, List

from . import CLASSES, read_jsonl
from shared.src.lib.ai.freeze_facts import best_threshold

BUCKETS = (('>=0.9', 0.9, 1.01), ('0.8-0.9', 0.8, 0.9), ('0.6-0.8', 0.6, 0.8), ('<0.6', 0.0, 0.6))


def _pct(a: int, n: int) -> str:
    return f'{a}/{n} ({a / n:.0%})' if n else '0/0'


def build_report(bundle: str) -> str:
    rows = {r['id']: r for r in read_jsonl(os.path.join(bundle, 'rows.jsonl'))}
    facts = {f['id']: f for f in read_jsonl(os.path.join(bundle, 'facts.jsonl')) if not f.get('error')}
    decided = [d for d in read_jsonl(os.path.join(bundle, 'decisions.jsonl'))
               if d.get('success') and d['id'] in rows and d['id'] in facts]
    lines: List[str] = ['# Freeze triage: Jev on strip facts', '']
    lines.append(f"Strips: {len(rows)}; measured {len(facts)}; decided {len(decided)}. "
                 f"Truth: {dict(Counter(r['truth'] for r in rows.values()))}.")
    cost = sum(float(d.get('cost') or 0) for d in decided)
    lines.append(f"Jev cost ${cost:.4f} (${cost / max(1, len(decided)):.6f} per decision).")

    def block(title: str, ds: List[Dict[str, Any]]) -> None:
        right = sum(1 for d in ds if d['choice'] == rows[d['id']]['truth'])
        lines.extend(['', f'## {title}', '', f'Jev right: {_pct(right, len(ds))}', '',
                      '| truth | n | Jev right |', '|---|---|---|'])
        for c in CLASSES:
            sel = [d for d in ds if rows[d['id']]['truth'] == c]
            lines.append(f"| {c} | {len(sel)} | {_pct(sum(1 for d in sel if d['choice'] == c), len(sel))} |")
        lines.extend(['', '| confidence | n | Jev right |', '|---|---|---|'])
        for name, lo, hi in BUCKETS:
            sel = [d for d in ds if lo <= float(d.get('confidence') or 0) < hi]
            lines.append(f"| {name} | {len(sel)} | "
                         f"{_pct(sum(1 for d in sel if d['choice'] == rows[d['id']]['truth']), len(sel))} |")

    real = [d for d in decided if rows[d['id']]['truth'] == 'freeze']
    false = [d for d in decided if rows[d['id']]['truth'] != 'freeze']
    owner = [d for d in false if rows[d['id']]['label_source'] == 'human']
    lines.extend(['', '## Triage (keep a real freeze, dismiss the rest)', '',
                  f"Real freezes kept: {_pct(sum(d.get('triage') == 'keep' for d in real), len(real))}",
                  f"False alerts dismissed: {_pct(sum(d.get('triage') == 'dismiss' for d in false), len(false))}"
                  f" (owner-labelled: {_pct(sum(d.get('triage') == 'dismiss' for d in owner), len(owner))})",
                  'By device, false alerts still kept: ' + ', '.join(
                      f'{k} {v}' for k, v in Counter(rows[d['id']].get('device_model') or 'unknown'
                                                     for d in false if d.get('triage') == 'keep').most_common())])
    block('All labelled strips', decided)
    block('Human-labelled only', [d for d in decided if rows[d['id']]['label_source'] == 'human'])
    confusion = Counter((rows[d['id']]['truth'], d['choice']) for d in decided
                        if d['choice'] != rows[d['id']]['truth'])
    lines.extend(['', '## Confusions (truth -> Jev)', ''] +
                 [f'- {t} -> {j}: {n}' for (t, j), n in confusion.most_common(10)])
    base = best_threshold([{'changed_pct': facts[i]['first_last']['changed_pct'], 'truth': rows[i]['truth']}
                           for i in facts if i in rows])
    lines.extend(['', '## No-AI baseline (threshold fitted on these same rows: optimistic)', '',
                  f"moving if first->last changed >= {base['threshold']}% else still: "
                  f"{_pct(base['correct'], base['n'])} of the still/moving strips."])
    return '\n'.join(lines) + '\n'


def run_report(bundle: str) -> str:
    text = build_report(bundle)
    with open(os.path.join(bundle, 'report.md'), 'w') as f:
        f.write(text)
    return text
