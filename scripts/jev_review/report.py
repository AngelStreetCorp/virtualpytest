"""Phase 4, anywhere: score ``decisions.jsonl`` against the truth with the dataset's own
``comparators.compare('screen-id', ...)`` and write ``report.md``.

Truth: ``ground_truth`` of the ``agreed`` and ``human`` sets. The ``disputed`` set has no truth: it
reports whose side Jev takes (the run label, the blind AI answers). The blind Sonnet teacher is
scored on the same rows with its ``teacher_label``.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import load_lib
from .evidence import load_groups, read_jsonl

FAMILY = 'screen-id'
BUCKETS = (('>=0.9', 0.9, 2.0), ('0.8-0.9', 0.8, 0.9), ('0.6-0.8', 0.6, 0.8), ('<0.6', -1.0, 0.6))
Compare = Callable[[str, dict, Optional[dict]], Tuple[bool, str]]


def jev_answer(decision: Mapping[str, Any], labels: Mapping[str, str]) -> Optional[dict]:
    """The comparator's answer shape for a Jev choice (a group node id), None when it chose nothing."""
    choice = decision.get('choice')
    return None if choice is None else {'node_id': choice, 'label': labels.get(choice, choice)}


def bucket_of(confidence: Any) -> str:
    c = float(confidence) if confidence is not None else 0.0
    return next(name for name, lo, hi in BUCKETS if lo <= c < hi)


def pct(correct: int, n: int) -> str:
    return f"{100 * correct / n:.1f}%" if n else 'n/a'


def score(rows: Sequence[Mapping[str, Any]], decisions: Mapping[str, Mapping[str, Any]],
          evidence: Mapping[str, Mapping[str, Any]], labels_of: Mapping[str, Mapping[str, str]],
          compare: Compare) -> List[Dict[str, Any]]:
    """One record per decided row: the answers and who is right."""
    out = []
    for row in rows:
        dec, ev = decisions.get(row['id']), evidence.get(row['id'])
        if dec is None or ev is None:
            continue
        triage = row.get('triage') or {}
        truth = row.get('ground_truth')
        answer = jev_answer(dec, labels_of.get(row['userinterface'], {}))
        rec = {'id': row['id'], 'set': row['set'], 'informative': bool(ev.get('informative')),
               'confidence': dec.get('confidence'), 'cost': float(dec.get('cost') or 0),
               'jev': answer, 'truth': truth, 'decided': answer is not None}
        if row['set'] != 'disputed':
            rec['jev_ok'] = compare(FAMILY, truth, answer)[0]
            if triage.get('teacher_label') is not None:
                rec['teacher_ok'] = compare(FAMILY, truth, triage['teacher_label'])[0]
        else:
            first = (triage.get('first_pass') or {}).get('teacher_label')
            for key, other in (('with_run', truth), ('with_teacher', triage.get('teacher_label')), ('with_first_pass', first)):
                rec[key] = other is not None and compare(FAMILY, other, answer)[0]
        out.append(rec)
    return out


def _table(title: str, recs: Sequence[Mapping[str, Any]]) -> List[str]:
    n = len(recs)
    ok = sum(1 for r in recs if r['jev_ok'])
    teach = [r for r in recs if 'teacher_ok' in r]
    lines = [f"**{title}**: n={n}, Jev correct {ok} ({pct(ok, n)})"]
    if teach:
        lines.append(f"  blind Sonnet teacher on {len(teach)} rows with its answer: "
                     f"{sum(r['teacher_ok'] for r in teach)} ({pct(sum(r['teacher_ok'] for r in teach), len(teach))}); "
                     f"Jev on the same rows: {sum(r['jev_ok'] for r in teach)} ({pct(sum(r['jev_ok'] for r in teach), len(teach))})")
    lines += ['', '| confidence | n | Jev correct |', '|---|---|---|']
    for name, _lo, _hi in BUCKETS:
        sub = [r for r in recs if bucket_of(r['confidence']) == name]
        lines.append(f"| {name} | {len(sub)} | {pct(sum(r['jev_ok'] for r in sub), len(sub))} |")
    return lines + ['']


def confusions(recs: Sequence[Mapping[str, Any]], key_fn: Callable[[Optional[dict]], str], top: int = 10) -> List[Tuple[str, str, int]]:
    counts = Counter((key_fn(r['truth']), key_fn(r['jev'])) for r in recs if not r['jev_ok'])
    return [(t, j, n) for (t, j), n in counts.most_common(top)]


def render(recs: Sequence[Mapping[str, Any]], meta: Mapping[str, Any], key_fn: Callable[[Optional[dict]], str],
           expected: int) -> str:
    known = [r for r in recs if r['set'] != 'disputed']
    cost = sum(r['cost'] for r in recs)
    lines = ['# Jev screen review', '',
             f"Rows with evidence and a decision: {len(recs)} of {expected} exported. "
             f"Undecided (Jev chose nothing): {sum(1 for r in recs if not r['decided'])}.",
             f"Skipped (app has no tree): {json.dumps(meta.get('skipped_no_tree') or {})}",
             f"Jev cost: ${cost:.4f} total, ${cost / len(recs) if recs else 0:.6f} per decision.", '']
    for name in ('agreed', 'human'):
        sub = [r for r in known if r['set'] == name]
        if sub:
            lines += [f"## Set {name}", ''] + _table('informative frames', [r for r in sub if r['informative']])
            low = [r for r in sub if not r['informative']]
            if low:
                lines += _table('low-information frames (separately)', low)
    if known:
        lines += ['## Overall (agreed + human)', ''] + _table('informative frames', [r for r in known if r['informative']])
        low = [r for r in known if not r['informative']]
        if low:
            lines += _table('low-information frames (separately)', low)
        lines += ['## Top 10 confusions (truth -> Jev)', '', '| truth | Jev | n |', '|---|---|---|']
        lines += [f"| {t} | {j} | {n} |" for t, j, n in confusions(known, key_fn)] + ['']
    disputed = [r for r in recs if r['set'] == 'disputed']
    if disputed:
        n = len(disputed)
        total = lambda k: sum(1 for r in disputed if r[k])  # noqa: E731
        neither = sum(1 for r in disputed if not (r['with_run'] or r['with_teacher'] or r['with_first_pass']))
        lines += ['## Set disputed (no truth)', '', f"n={n}",
                  f"- Jev sides with the run label: {total('with_run')} ({pct(total('with_run'), n)})",
                  f"- Jev sides with the final AI answer (teacher_label): {total('with_teacher')} ({pct(total('with_teacher'), n)})",
                  f"- Jev sides with the first-pass AI answer: {total('with_first_pass')} ({pct(total('with_first_pass'), n)})",
                  f"- with none of them: {neither}", '']
    return '\n'.join(lines)


def run_report(bundle: str, compare: Optional[Compare] = None, out_path: Optional[str] = None) -> str:
    comparators = load_lib('comparators')
    compare = compare or comparators.compare
    rows = read_jsonl(os.path.join(bundle, 'rows.jsonl'))
    decisions = {d['id']: d for d in read_jsonl(os.path.join(bundle, 'decisions.jsonl'))}
    evidence = {e['id']: e for e in read_jsonl(os.path.join(bundle, 'evidence.jsonl'))}
    labels_of = {ui: {g['node_id']: g['label'] for g in load_groups(bundle, ui)}
                 for ui in sorted({r['userinterface'] for r in rows})}
    meta_path = os.path.join(bundle, 'export_meta.json')
    meta = json.load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else {}
    recs = score(rows, decisions, evidence, labels_of, compare)
    key_fn = lambda v: comparators.confusion_key(FAMILY, v)  # noqa: E731
    text = render(recs, meta, key_fn, len(rows))
    with open(out_path or os.path.join(bundle, 'report.md'), 'w', encoding='utf-8') as f:
        f.write(text + '\n')
    return text
