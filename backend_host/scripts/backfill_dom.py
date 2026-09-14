#!/usr/bin/env python3
"""
Backfill LLM DOM (GPT-5.5, no hints) for an existing userinterface.

For every node with a stored screenshot (navigation_nodes.data.screenshot) but no
current DOM, download the screenshot, run dom_generator.generate_dom(), render the
`<stem>_dom.jpg` overlay, upload it to R2 next to the screenshot, and write both
into node.data:
    data['dom']       = full DOM json (focusable_elements / focused_element_id / navigation)
    data['dom_image'] = R2 key of the overlay shown in the Edit-node DOM tab

Idempotent: nodes whose data.dom._dom_meta.v already matches DOM_SCHEMA_VERSION are
skipped unless --force. Use --limit to try a handful first, --node to target a label,
--workers to parallelize (DOM calls are ~60s each, so concurrency dominates wall time).

Requires OPENAI_API_KEY in the environment (loaded from the project .env).

Usage (run on a host/server VM with the repo + .env):
    python3 backend_host/scripts/backfill_dom.py example_tv --limit 5
    python3 backend_host/scripts/backfill_dom.py example_tv --workers 6      # all nodes
    python3 backend_host/scripts/backfill_dom.py example_tv --node home --force
"""
import argparse
import os
import re
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

# Repo root on path (script lives at backend_host/scripts/)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from shared.src.lib.config.constants import get_team_id  # noqa: E402
from shared.src.lib.database.userinterface_db import get_userinterface_by_name  # noqa: E402
from shared.src.lib.database.navigation_trees_db import get_tree_nodes, save_node, get_supabase  # noqa: E402
from shared.src.lib.utils.cloudflare_utils import CloudflareUtils, upload_navigation_screenshot  # noqa: E402
from backend_host.src.services.ai_exploration.dom_generator import (  # noqa: E402
    generate_dom, render_dom_overlay, DOM_SCHEMA_VERSION,
)

# GPT-5.5 rates ($/1M) for the running cost estimate.
RATE_IN, RATE_OUT = 5.0, 30.0


def _remote_key(screenshot: str, bucket: str) -> str:
    """Normalize a stored screenshot (full signed URL or relative path) to a storage key."""
    key = re.sub(r'^https?://[^/]+/', '', screenshot)   # strip host
    key = key.split('?', 1)[0]                          # strip query (signed params)
    if bucket and key.startswith(f'{bucket}/'):         # strip leading bucket segment
        key = key[len(bucket) + 1:]
    return key


def main():
    ap = argparse.ArgumentParser(description='Backfill LLM DOM for a userinterface')
    ap.add_argument('userinterface_name')
    ap.add_argument('--team-id', default=None)
    ap.add_argument('--limit', type=int, default=0, help='process at most N nodes (0 = all)')
    ap.add_argument('--node', default=None, help='only nodes whose label/node_id contains this substring')
    ap.add_argument('--workers', type=int, default=6, help='concurrent DOM generations')
    ap.add_argument('--force', action='store_true', help='regenerate even if dom._dom_meta.v is current')
    ap.add_argument('--model', default=None, help='override DOM model (default gpt-5.5)')
    ap.add_argument('--effort', default=None, help='reasoning effort (default medium)')
    args = ap.parse_args()

    if not os.getenv('OPENAI_API_KEY', '').strip():
        print("❌ OPENAI_API_KEY not set — source the host .env first")
        sys.exit(1)

    team_id = args.team_id or get_team_id()
    ui = get_userinterface_by_name(args.userinterface_name, team_id)
    if not ui:
        print(f"❌ userinterface '{args.userinterface_name}' not found for team {team_id}")
        sys.exit(1)

    supabase = get_supabase()
    trees = supabase.table('navigation_trees').select('id, name')\
        .eq('userinterface_id', ui['id']).eq('team_id', team_id).execute().data or []

    cf = CloudflareUtils()

    # 1) Build the worklist (filter + idempotency skip) before fanning out.
    worklist = []
    skipped = no_shot = 0
    for tree in trees:
        res = get_tree_nodes(tree['id'], team_id, limit=500)
        for node in res.get('nodes', []):
            data = node.get('data') or {}
            shot = data.get('screenshot') or data.get('screenshot_url')
            label = node.get('label') or node.get('node_id')
            if args.node and args.node.lower() not in f"{label} {node.get('node_id', '')}".lower():
                continue
            if not shot:
                no_shot += 1
                continue
            if not args.force and (data.get('dom') or {}).get('_dom_meta', {}).get('v') == DOM_SCHEMA_VERSION:
                skipped += 1
                continue
            worklist.append((tree['id'], node, data, shot, label))
            if args.limit and len(worklist) >= args.limit:
                break
        if args.limit and len(worklist) >= args.limit:
            break

    print(f"Backfilling DOM for '{args.userinterface_name}': {len(worklist)} to process, "
          f"{skipped} already current, {no_shot} without screenshot, {args.workers} workers")

    lock = threading.Lock()
    stats = {'done': 0, 'failed': 0, 'cost': 0.0}

    def process(item):
        tree_id, node, data, shot, label = item
        key = _remote_key(shot, cf.bucket_name)
        stem = os.path.splitext(os.path.basename(key))[0]
        # Unique per task — the same node_id can appear in multiple trees (root /
        # parent-reference nodes), so node_id-based tmp paths race across workers.
        token = uuid.uuid4().hex
        tmp_shot = os.path.join(tempfile.gettempdir(), f"dom_{token}.jpg")
        tmp_overlay = os.path.join(tempfile.gettempdir(), f"dom_{token}_dom.jpg")
        try:
            dl = cf.download_file(key, tmp_shot)
            if not dl.get('success'):
                with lock:
                    stats['failed'] += 1
                print(f"  ✗ {label}: download failed ({dl.get('error')})")
                return

            dom = generate_dom(tmp_shot, model=args.model, effort=args.effort)
            u = dom.get('_dom_meta', {}).get('usage', {})
            cost = u.get('prompt_tokens', 0) * RATE_IN / 1e6 + u.get('completion_tokens', 0) * RATE_OUT / 1e6

            render_dom_overlay(tmp_shot, dom, tmp_overlay)
            dom_key = re.sub(r'\.(jpe?g|png)$', r'_dom.\1', key, flags=re.IGNORECASE)
            up = upload_navigation_screenshot(tmp_overlay, args.userinterface_name, f"{stem}_dom.jpg")

            data['dom'] = dom
            data['dom_image'] = dom_key if up.get('success') else None
            save = save_node(tree_id, {'node_id': node['node_id'], 'data': data}, team_id)
            with lock:
                stats['cost'] += cost
                if save.get('success'):
                    stats['done'] += 1
                    n = stats['done'] + stats['failed']
                    print(f"  ✓ [{n}/{len(worklist)}] {label}: focus={dom.get('focused_element_id')} "
                          f"els={len(dom.get('focusable_elements', []))} {dom['_dom_meta']['elapsed_sec']}s  (${stats['cost']:.2f})")
                else:
                    stats['failed'] += 1
                    print(f"  ✗ {label}: save failed ({save.get('error')})")
        except Exception as e:
            with lock:
                stats['failed'] += 1
            print(f"  ✗ {label}: {e}")
        finally:
            for p in (tmp_shot, tmp_overlay):
                if os.path.exists(p):
                    os.unlink(p)

    # 2) Fan out.
    if worklist:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            list(pool.map(process, worklist))

    print(f"\nDone: {stats['done']} DOM generated (~${stats['cost']:.2f}), {skipped} already current, "
          f"{no_shot} without screenshot, {stats['failed']} failed")


if __name__ == '__main__':
    main()
