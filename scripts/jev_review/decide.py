"""Phase 3, ON THE SERVER (OpenRouter key): Jev picks the screen group of each frame from the
text facts of ``evidence.jsonl`` alone, through ``decisions.choose``. Blind: the state and the
options never hold the run label or any earlier AI answer; those travel in ``refs`` only
(logged to ai_decisions, never shown to the model).

Writes ``decisions.jsonl``: {id, set, choice, confidence, probabilities (top 3), cost, ms,
decision_id, success, error}. A rerun skips the ids already written.
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import LAB_TEAM
from .evidence import read_jsonl

USAGE = 'text.decision.screen_review'
INSTRUCTIONS = ("Which screen is this frame? Use the check scores: a passed image or text check is "
                "strong evidence; a seed frame far closer than 128 of 256 bits (unrelated) is strong.")
NOTE = 'facts come from comparing the frame with each screen\'s checks and reference frame'


def label_name(label: Any) -> Optional[str]:
    return label.get('label') if isinstance(label, Mapping) else None


def build_request(row: Mapping[str, Any], record: Mapping[str, Any]) -> Tuple[dict, List[dict], str, dict]:
    """``(state, options, instructions, refs)`` of one sample. state and options carry only what
    the checks found; refs carry the ids and labels that must stay hidden from the model."""
    informative = bool(record.get('informative'))
    state = {'userinterface': row.get('userinterface'), 'device_model': row.get('device_model'),
             'frame': 'informative' if informative else 'low-information', 'note': NOTE}
    options = [{'id': g['group_id'], 'facts': g['facts']} for g in record['groups']]
    triage = row.get('triage') or {}
    refs = {'sample_id': row['id'], 'set': row.get('set'),
            'truth': None if row.get('set') in ('disputed', 'open') else label_name(row.get('ground_truth')),
            'run_label': label_name(row.get('ground_truth')) if row.get('label_source') == 'run' else None,
            'teacher_label': label_name(triage.get('teacher_label')), 'source': 'jev-review'}
    return state, options, INSTRUCTIONS, refs


def top3(probabilities: Mapping[str, Any]) -> Dict[str, float]:
    ranked = sorted(((k, float(v)) for k, v in (probabilities or {}).items()), key=lambda kv: -kv[1])[:3]
    return {k: round(v, 3) for k, v in ranked}


def decision_record(row: Mapping[str, Any], out: Mapping[str, Any]) -> Dict[str, Any]:
    return {'id': row['id'], 'set': row.get('set'), 'choice': out.get('choice'),
            'confidence': out.get('confidence'), 'probabilities': top3(out.get('probabilities') or {}),
            'cost': out.get('cost'), 'ms': out.get('ms'), 'decision_id': out.get('decision_id'),
            'success': bool(out.get('success')), 'error': out.get('error')}


def ensure_usage() -> None:
    """Register the usage when the deployed usages.py lacks it (like jev_bridge.py)."""
    from shared.src.lib.ai import usages
    if 'text.decision' not in usages.USAGES:
        usages.register(usages._u('text.decision', 'Decision (closed choice)',
                                  'Decision models picking among options (TASK-38)'))
    if USAGE not in usages.USAGES:
        usages.register(usages._u(USAGE, 'Screen review (decision model, shadow)',
                                  'Jev picks the screen group of a stored frame from text facts '
                                  '(scripts/jev_review)', 'text.decision'))


def run_decide(bundle: str, team_id: str = LAB_TEAM, limit: Optional[int] = None, workers: int = 1,
               choose=None, resolution=None) -> Dict[str, Any]:
    """The whole phase. ``choose`` / ``resolution`` replace the model call in tests."""
    rows = {r['id']: r for r in read_jsonl(os.path.join(bundle, 'rows.jsonl'))}
    if choose is None:
        ensure_usage()
        from shared.src.lib.ai import decisions, gateway, router
        if not decisions.enabled(USAGE):  # JEV_ENABLED off: write no failed rows that a re-run would skip as done
            print('[jev] disabled by JEV_ENABLED / JEV_DISABLED_USAGES: nothing decided')
            return {'decided': 0, 'already_done': 0, 'cost': 0.0, 'disabled': True}
        gateway.use_local_routing()
        resolution, choose = router.resolve(USAGE, team_id), decisions.choose
    path = os.path.join(bundle, 'decisions.jsonl')
    done = {d['id'] for d in read_jsonl(path)}
    todo = [e for e in read_jsonl(os.path.join(bundle, 'evidence.jsonl'))
            if not e.get('error') and e['id'] in rows and e['id'] not in done]
    todo = todo[:limit] if limit else todo

    def one(record):
        row = rows[record['id']]
        state, options, instructions, refs = build_request(row, record)
        out = choose(resolution, state, options, instructions=instructions, refs=refs, log=True)
        return decision_record(row, out)

    cost = 0.0
    with open(path, 'a', encoding='utf-8') as f, ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for rec in pool.map(one, todo):
            cost += float(rec['cost'] or 0)
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()
    return {'decided': len(todo), 'already_done': len(done), 'cost': cost}
