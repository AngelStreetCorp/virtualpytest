#!/usr/bin/env python3
"""Recapture every fingerprinted screen node of an interface on a device (Localize audit §4, STALE /
ZERO). For each node: MCP navigate_to_node by label, then save_node_screenshot, exactly the calls
the runbook lists, so the fingerprint is rebuilt, `captured_at` stamped and the operator's
corrections carried. Saved only when the device is provably on the node: the node has its own verifications (a goto
to a node without any always "passes", wherever it lands — TASK-110 §7: 117 autobuild nodes were
overwritten with app splash screens and the TV guide that way) and they passed, and the frame is
not black / no signal (Localize `signal`). Every other node is listed with the reason, not saved.

    MCP_SECRET_KEY=... python3 scripts/localize/recapture.py --ui stb3_live --host vpt-pi1 --device device3 \\
        [--server https://localhost] [--only node_0002,node_0004] [--out result.json]

Hold a lease on the device while it runs (deploy skill).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bench  # noqa: E402  (env, db)


def _call(server: str, name: str, args: dict) -> dict:
    import requests
    body = {'jsonrpc': '2.0', 'id': int(time.time() * 1000), 'method': 'tools/call',
            'params': {'name': name, 'arguments': args}}
    r = requests.post(f"{server}/server/mcp", json=body, timeout=300, verify=False,
                      headers={'Authorization': f"Bearer {os.environ['MCP_SECRET_KEY']}"})
    return r.json().get('result') or {}


def _text(res: dict) -> str:
    return ' '.join(c.get('text', '') for c in res.get('content') or [] if c.get('type') == 'text')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ui', required=True)
    ap.add_argument('--host', required=True)
    ap.add_argument('--device', required=True)
    ap.add_argument('--server', default='https://localhost')
    ap.add_argument('--team', default=bench.DEFAULT_TEAM)
    ap.add_argument('--only', help='comma-separated node ids (default: every fingerprinted screen node)')
    ap.add_argument('--settle', type=float, default=2.0, help='seconds between the goto and the capture')
    ap.add_argument('--out')
    a = ap.parse_args()
    import urllib3
    urllib3.disable_warnings()
    bench._env()
    db = bench._db()
    ui = (db.table('userinterfaces').select('id').eq('team_id', a.team).eq('name', a.ui).execute().data or [])
    if not ui:
        print(f"interface '{a.ui}' not found for team {a.team} in the database this shell points to "
              f"({os.environ.get('SUPABASE_URL', '?')}): run it where the host's .env is the lab database "
              f"(vpt-pi1 for the rpitest server), not on a laptop with another project's .env.", file=sys.stderr)
        return 2
    trees = (db.table('navigation_trees').select('id').eq('team_id', a.team)
             .eq('userinterface_id', ui[0]['id']).execute().data or [])
    rows = (db.table('navigation_nodes').select('tree_id, node_id, label, node_type, data, verifications').eq('team_id', a.team)
            .in_('tree_id', [t['id'] for t in trees]).execute().data or []) if trees else []
    only = set(a.only.split(',')) if a.only else None
    seen, todo = set(), []
    for r in rows:
        fp = (r.get('data') or {}).get('fingerprint')
        if (r['node_id'] in seen or (r.get('node_type') or 'screen') in ('entry', 'action')
                or (only is None and not fp) or (only is not None and r['node_id'] not in only)):
            continue
        seen.add(r['node_id'])
        todo.append(r)
    out = {'ui': a.ui, 'saved': [], 'no_verification': [], 'goto_failed': [], 'signal': [], 'save_failed': []}
    for r in todo:
        base = {'host_name': a.host, 'device_id': a.device, 'userinterface_name': a.ui}
        if not r.get('verifications'):
            out['no_verification'].append({'node_id': r['node_id'], 'label': r.get('label')})
            print(f"  {r['node_id']:<22} {r.get('label', '')[:28]:<28} no verification: cannot prove the screen, skipped")
            continue
        # by label: the tool takes exactly one of id / label and its schema requires the label
        res = _call(a.server, 'navigate_to_node', {**base, 'target_node_label': r.get('label') or r['node_id'],
                                                       'include_screenshot': False})
        if res.get('isError'):
            out['goto_failed'].append({'node_id': r['node_id'], 'label': r.get('label'), 'why': _text(res)[:200]})
            print(f"  {r['node_id']:<22} {r.get('label', '')[:28]:<28} goto failed, not saved")
            continue
        time.sleep(a.settle)
        loc = _text(_call(a.server, 'localize', base))
        if loc.startswith('kind=signal'):
            out['signal'].append({'node_id': r['node_id'], 'label': r.get('label'), 'why': loc[:120]})
            print(f"  {r['node_id']:<22} {r.get('label', '')[:28]:<28} black / no signal, not saved")
            continue
        res = _call(a.server, 'save_node_screenshot', {**base, 'tree_id': r['tree_id'], 'node_id': r['node_id'],
                                                       'label': r.get('label') or r['node_id']})
        key = 'save_failed' if res.get('isError') else 'saved'
        out[key].append({'node_id': r['node_id'], 'label': r.get('label')})
        print(f"  {r['node_id']:<22} {r.get('label', '')[:28]:<28} {key}")
    print(f"{a.ui}: saved {len(out['saved'])} of {len(todo)}; " + ', '.join(
        f"{k.replace('_', ' ')} {len(v)}" for k, v in out.items() if k not in ('ui', 'saved')))
    if a.out:
        json.dump(out, open(a.out, 'w'), indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
