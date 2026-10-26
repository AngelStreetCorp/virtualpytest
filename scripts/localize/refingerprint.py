#!/usr/bin/env python3
"""Recompute node fingerprints from their STORED screenshots with the current matcher code
(TASK-110 §7). Same as the node dialog's "Recompute fingerprint", for whole interfaces.

A fingerprint made by an older matcher can carry layers the live frame never produces (a
`row` focus, no nav underline), so its node never matches even on its own screenshot. This
rebuilds the pixels layers and keeps everything else of the old fingerprint: the operator's
`extra` samples and `negatives`, the device `identity`, and `captured_at` (the screenshot is
as old as before: a recompute is not a recapture, so the audit's STALE age stays honest).

    python3 scripts/localize/refingerprint.py --ui stb3_live,stb3_sim --out DIR
        -> DIR/backup.json (every old fingerprint), DIR/new.json, DIR/apply.sql (one UPDATE,
           team-filtered: one statement = one navigation MV refresh)

Read-only on the DB: apply.sql is run by hand (psql) after reading the diff it prints.
Undo: the same with --restore DIR/backup.json (writes DIR/restore.sql).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bench  # noqa: E402  (env, db, download helpers)

KEEP = ('extra', 'negatives', 'identity', 'captured_at')


def _rows(db, team_id: str, uis):
    ui_rows = db.table('userinterfaces').select('id, name').eq('team_id', team_id).in_('name', uis).execute().data or []
    trees = (db.table('navigation_trees').select('id, userinterface_id').eq('team_id', team_id)
             .in_('userinterface_id', [u['id'] for u in ui_rows]).execute().data or [])
    if not trees:
        return []
    return (db.table('navigation_nodes').select('tree_id, node_id, label, data').eq('team_id', team_id)
            .in_('tree_id', [t['id'] for t in trees]).execute().data or [])


def _sql(team_id: str, rows) -> str:
    """One UPDATE for every (tree_id, node_id, fingerprint), dollar-quoted JSON."""
    values = ',\n'.join(f"('{r['tree_id']}'::uuid, '{r['node_id']}', $fp${json.dumps(r['fingerprint'])}$fp$::jsonb)"
                        for r in rows)
    return (f"UPDATE navigation_nodes n SET data = jsonb_set(n.data, '{{fingerprint}}', v.fp)\n"
            f"FROM (VALUES\n{values}\n) AS v(tree_id, node_id, fp)\n"
            f"WHERE n.team_id = '{team_id}' AND n.tree_id = v.tree_id AND n.node_id = v.node_id;\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ui', help='comma-separated userinterface names')
    ap.add_argument('--out', required=True, help='output directory')
    ap.add_argument('--team', default=bench.DEFAULT_TEAM)
    ap.add_argument('--restore', help='a backup.json to turn into restore.sql')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.restore:
        rows = json.load(open(a.restore))
        open(os.path.join(a.out, 'restore.sql'), 'w').write(_sql(a.team, rows))
        print(f"restore.sql: {len(rows)} fingerprints")
        return 0
    bench._env()
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    helpers = ImageHelpers(None, None)
    db = bench._db()
    backup, new = [], []
    for r in _rows(db, a.team, a.ui.split(',')):
        data = r.get('data') or {}
        old = data.get('fingerprint')
        shot = data.get('screenshot')
        if not old or not shot:
            continue
        img = bench._download(shot)
        fp = helpers.compute_fingerprint(img) if img is not None else None
        if not fp:
            print(f"  {r['tree_id'][:8]} {r['node_id']}: no fingerprint from {shot}")
            continue
        fp.pop('captured_at', None)
        fp.update({k: old[k] for k in KEEP if k in old})
        backup.append({'tree_id': r['tree_id'], 'node_id': r['node_id'], 'fingerprint': old})
        new.append({'tree_id': r['tree_id'], 'node_id': r['node_id'], 'fingerprint': fp})
        of, nf = (old.get('focus') or {}).get('kind'), (fp.get('focus') or {}).get('kind')
        print(f"  {r['tree_id'][:8]} {r['node_id']:<22} {r.get('label', '')[:24]:<24} focus {of} -> {nf}")
    json.dump(backup, open(os.path.join(a.out, 'backup.json'), 'w'))
    json.dump(new, open(os.path.join(a.out, 'new.json'), 'w'))
    open(os.path.join(a.out, 'apply.sql'), 'w').write(_sql(a.team, new))
    print(f"{len(new)} fingerprints recomputed -> {a.out}/apply.sql (backup.json holds the old ones)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
