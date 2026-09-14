#!/usr/bin/env python3
"""
Export a UserInterface to a local fixture for OFFLINE auto-build testing.

Dumps the FULL ground-truth graph of a UI (every tree: root + all subtrees) plus the
per-node DOM / fingerprint / screenshot / verifications and every edge's action_sets to a
single `graph.json`, and downloads each node's screenshot from R2 (reusing any copy already
present in the local screenshot dir, only fetching what's missing/stale).

The result feeds `ReplayAdapter` (a simulated STB) so the autonomous UI builder can run end
to end with NO device and NO OpenAI cost. Run this on a host that can reach the real DB + R2
(e.g. host1), then copy the fixture dir to wherever you run the offline test.

Usage:
    python3 features/avq/backend_host/localize/export_ui_fixture.py example_tv \
        --team-id 7fdeb4bb-3639-4ec3-959f-b54769a219ce \
        --out features/avq/backend_host/localize/fixtures/example_tv \
        --reuse-shots ~/virtualpytest/screenshot/example_tv
"""
import os
import sys
import json
import argparse

# Repo root on path (this file is features/avq/backend_host/localize/)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))

from shared.src.lib.database.navigation_trees_db import get_supabase  # noqa: E402
from shared.src.lib.database.userinterface_db import get_userinterface_by_name  # noqa: E402

NODE_DATA_KEYS = ('dom', 'fingerprint', 'screenshot', 'dom_image', 'menu_type',
                  'is_root', 'type', 'depth', 'description')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('userinterface_name')
    ap.add_argument('--team-id', required=True)
    ap.add_argument('--out', default=None, help='fixture dir (default features/avq/backend_host/localize/fixtures/<ui>)')
    ap.add_argument('--reuse-shots', default=None,
                    help='existing local screenshot dir to reuse before hitting R2')
    ap.add_argument('--no-download', action='store_true', help='skip R2 download (json only)')
    args = ap.parse_args()

    team = args.team_id
    out_dir = args.out or os.path.join(os.path.dirname(__file__), 'fixtures', args.userinterface_name)
    shots_dir = os.path.join(out_dir, 'screenshots')
    os.makedirs(shots_dir, exist_ok=True)

    ui = get_userinterface_by_name(args.userinterface_name, team)
    if not ui:
        print(f"❌ UI '{args.userinterface_name}' not found for team {team}")
        sys.exit(1)
    ui_id = ui['id']
    sb = get_supabase()

    trees = sb.table('navigation_trees').select(
        'id,name,is_root_tree,parent_tree_id,parent_node_id,tree_depth'
    ).eq('userinterface_id', ui_id).eq('team_id', team).execute().data or []
    tree_ids = [t['id'] for t in trees]
    print(f"Trees: {len(trees)} (root + {len(trees)-1} subtrees)")

    nodes, edges = [], []
    for t in trees:
        tn = sb.table('navigation_nodes').select(
            'node_id,label,node_type,verifications,data'
        ).eq('tree_id', t['id']).eq('team_id', team).execute().data or []
        for n in tn:
            d = n.get('data') or {}
            nodes.append({
                'tree_id': t['id'],
                'node_id': n['node_id'],
                'label': n.get('label'),
                'node_type': n.get('node_type'),
                'verifications': n.get('verifications') or [],
                'data': {k: d.get(k) for k in NODE_DATA_KEYS if k in d},
            })
        te = sb.table('navigation_edges').select(
            'edge_id,source_node_id,target_node_id,default_action_set_id,action_sets'
        ).eq('tree_id', t['id']).eq('team_id', team).execute().data or []
        for e in te:
            e['tree_id'] = t['id']
            edges.append(e)

    print(f"Nodes: {len(nodes)}  Edges: {len(edges)}")

    fixture = {
        'userinterface': {'id': ui_id, 'name': ui['name'], 'models': ui.get('models') or ['stb']},
        'team_id': team,
        'trees': trees,
        'nodes': nodes,
        'edges': edges,
    }
    graph_path = os.path.join(out_dir, 'graph.json')
    with open(graph_path, 'w') as f:
        json.dump(fixture, f, indent=2)
    print(f"✅ wrote {graph_path}")

    # Screenshots: reuse local copy, else download from R2 by the stored key.
    if args.no_download:
        return
    from shared.src.lib.utils.cloudflare_utils import CloudflareUtils
    cf = CloudflareUtils()
    have = downloaded = missing = 0
    for n in nodes:
        key = (n['data'] or {}).get('screenshot')
        if not key:
            continue
        base = os.path.basename(key)
        dest = os.path.join(shots_dir, base)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            have += 1
            continue
        # reuse from an existing local dir if present
        if args.reuse_shots:
            src = os.path.join(os.path.expanduser(args.reuse_shots), base)
            if os.path.exists(src) and os.path.getsize(src) > 0:
                import shutil
                shutil.copy2(src, dest)
                have += 1
                continue
        res = cf.download_file(key, dest)
        if res.get('success'):
            downloaded += 1
        else:
            missing += 1
            print(f"  ✗ {n['label']}: {key} -> {res.get('error')}")
    print(f"Screenshots: {have} reused, {downloaded} downloaded, {missing} missing -> {shots_dir}")


if __name__ == '__main__':
    main()
