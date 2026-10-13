"""Phase 3, ON THE SERVER (OpenRouter key): Jev picks still / moving / freeze from the strip facts.
The truth travels in ``refs`` only. Writes ``decisions.jsonl``; reruns skip done ids."""
import os
from typing import Any, Dict, Mapping, Optional

from shared.src.lib.ai import freeze_triage

from . import LAB_TEAM, append_jsonl, read_jsonl

USAGE = freeze_triage.USAGE


def build_refs(row: Mapping[str, Any]) -> dict:
    return {'sample_id': row['id'], 'truth': row['truth'], 'label_source': row.get('label_source'),
            'source': 'jev-freeze'}


def ensure_usage() -> None:
    from shared.src.lib.ai import usages
    if 'text.decision' not in usages.USAGES:
        usages.register(usages._u('text.decision', 'Decision (closed choice)',
                                  'Decision models picking among options (TASK-38)'))
    if USAGE not in usages.USAGES:
        usages.register(usages._u(USAGE, 'Freeze triage (decision model)',
                                  'Jev: real freeze, still screen or moving video, from strip facts '
                                  '(scripts/jev_freeze)', 'text.decision'))


def run_decide(bundle: str, team_id: str = LAB_TEAM, limit: Optional[int] = None,
               choose=None, resolution=None, decide=None) -> Dict[str, Any]:
    rows = {r['id']: r for r in read_jsonl(os.path.join(bundle, 'rows.jsonl'))}
    if choose is None:
        ensure_usage()
        from shared.src.lib.ai import decisions, gateway, router
        if not decisions.enabled(USAGE):  # JEV_ENABLED off: write no failed rows that a re-run would skip as done
            print('[jev] disabled by JEV_ENABLED / JEV_DISABLED_USAGES: nothing decided')
            return {'decided': 0, 'already_done': 0, 'cost': 0.0, 'disabled': True}
        gateway.use_local_routing()
        resolution, choose, decide = router.resolve(USAGE, team_id), decisions.choose, decisions.decide
    path = os.path.join(bundle, 'decisions.jsonl')
    done = {d['id'] for d in read_jsonl(path)}
    todo = [f for f in read_jsonl(os.path.join(bundle, 'facts.jsonl'))
            if not f.get('error') and f['id'] in rows and f['id'] not in done][:limit]
    cost = 0.0

    def records():
        nonlocal cost
        for record in todo:
            row = rows[record['id']]
            out = freeze_triage.ask(resolution, record, row.get('device_model'), build_refs(row), choose, decide)
            cost += out['cost']
            yield {'id': record['id'], 'choice': out['choice'], 'confidence': out['confidence'],
                   'ui': out['ui'], 'triage': out['triage'], 'probabilities': out['probabilities'],
                   'cost': out['cost'], 'ms': out['ms'], 'decision_ids': out['decision_ids'],
                   'success': out['success'], 'error': out['error']}

    n = append_jsonl(path, records())
    return {'decided': n, 'already_done': len(done), 'cost': round(cost, 6)}
