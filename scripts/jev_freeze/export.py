"""Phase 1, ON THE SERVER: labelled freeze strips (family ``av-fault``) and their files.

A human label wins over a teacher label of the same alert. Writes ``rows.jsonl``
{id, label_source, truth, alert_id, device_model, object_key} and ``strips/<id>.jpg``.
"""
import json
import os
from typing import Any, Dict, List, Mapping, Sequence

from . import LAB_TEAM
from shared.src.lib.ai.freeze_facts import truth_of

FAMILY = 'av-fault'
PAGE_SIZE = 500


def fetch_rows(team_id: str, list_fn=None) -> List[Dict[str, Any]]:
    if list_fn is None:
        from shared.src.lib.database.ai_training_samples_db import list_samples as list_fn
    rows, offset = [], 0
    while True:
        page, total = list_fn(team_id, family=FAMILY, label_sources=['human', 'teacher'],
                              limit=PAGE_SIZE, offset=offset)
        rows.extend(page)
        offset += len(page)
        if not page or offset >= (total or 0):
            return rows


def select(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One labelled row per alert, the human one first."""
    out: Dict[str, Dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: r.get('label_source') != 'human'):
        truth = truth_of(row.get('ground_truth'))
        if truth is None:
            continue
        alert = (row.get('source_ref') or {}).get('alert_id') or row['id']
        if alert in out:
            continue
        out[alert] = {'id': row['id'], 'label_source': row.get('label_source'), 'truth': truth,
                      'alert_id': alert, 'device_model': row.get('device_model'),
                      'object_key': row.get('object_key')}
    return list(out.values())


def run_export(bundle: str, team_id: str = LAB_TEAM, limit=None, list_fn=None, storage=None) -> Dict[str, Any]:
    rows = select(fetch_rows(team_id, list_fn))[:limit] if limit else select(fetch_rows(team_id, list_fn))
    if storage is None:
        from shared.src.lib.utils.cloudflare_utils import get_training_storage
        storage = get_training_storage()
    os.makedirs(os.path.join(bundle, 'strips'), exist_ok=True)
    kept, missing = [], 0
    for row in rows:
        dest = os.path.join(bundle, 'strips', f"{row['id']}.jpg")
        if os.path.exists(dest) or storage.download_file(row['object_key'], dest).get('success'):
            kept.append(row)
        else:
            missing += 1
    with open(os.path.join(bundle, 'rows.jsonl'), 'w') as f:
        for row in kept:
            f.write(json.dumps(row) + '\n')
    meta = {'rows': len(kept), 'strip_missing': missing,
            'by_truth': {c: sum(1 for r in kept if r['truth'] == c) for c in ('still', 'moving', 'freeze')},
            'human': sum(1 for r in kept if r['label_source'] == 'human')}
    with open(os.path.join(bundle, 'export_meta.json'), 'w') as f:
        json.dump(meta, f, indent=1)
    return meta
