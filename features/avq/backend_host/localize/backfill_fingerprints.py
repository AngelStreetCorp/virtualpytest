#!/usr/bin/env python3
"""
Backfill screen fingerprints (Localize) for an existing userinterface.

For every node that has a stored screenshot (navigation_nodes.data.screenshot)
but no current fingerprint, download the screenshot, compute the dHash + focus
fingerprint, and write it back into data.fingerprint. Idempotent: nodes whose
fingerprint.v already matches are skipped unless --force.

Only BASE node screenshots exist today, so this backfills base fingerprints;
per-variant fingerprints are populated as users (re)capture screenshots while a
variant scope is selected.

Usage (run on a host or server VM with the repo + .env):
    python3 features/avq/backend_host/localize/backfill_fingerprints.py example_tv
    python3 features/avq/backend_host/localize/backfill_fingerprints.py example_tv --force
"""
import argparse
import os
import re
import sys
import tempfile

# Repo root on path (script lives at features/avq/backend_host/localize/)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))

import cv2  # noqa: E402

from shared.src.lib.config.constants import get_team_id  # noqa: E402
from shared.src.lib.database.userinterface_db import get_userinterface_by_name  # noqa: E402
from shared.src.lib.database.navigation_trees_db import get_tree_nodes, save_node, get_supabase  # noqa: E402
from shared.src.lib.utils.cloudflare_utils import CloudflareUtils  # noqa: E402
from backend_host.src.controllers.verification.image_helpers import ImageHelpers  # noqa: E402


def _remote_key(screenshot: str, bucket: str) -> str:
    """Normalize a stored screenshot (full signed URL or relative path) to a storage key."""
    key = re.sub(r'^https?://[^/]+/', '', screenshot)   # strip host
    key = key.split('?', 1)[0]                          # strip query (signed params)
    if bucket and key.startswith(f'{bucket}/'):         # strip leading bucket segment
        key = key[len(bucket) + 1:]
    return key


def main():
    ap = argparse.ArgumentParser(description='Backfill Localize fingerprints for a userinterface')
    ap.add_argument('userinterface_name')
    ap.add_argument('--team-id', default=None)
    ap.add_argument('--force', action='store_true', help='recompute even if fingerprint.v is current')
    args = ap.parse_args()

    team_id = args.team_id or get_team_id()
    ui = get_userinterface_by_name(args.userinterface_name, team_id)
    if not ui:
        print(f"❌ userinterface '{args.userinterface_name}' not found for team {team_id}")
        sys.exit(1)

    supabase = get_supabase()
    trees = supabase.table('navigation_trees').select('id, name')\
        .eq('userinterface_id', ui['id']).eq('team_id', team_id).execute().data or []
    print(f"Backfilling '{args.userinterface_name}' ({len(trees)} trees)")

    cf = CloudflareUtils()
    helpers = ImageHelpers(None, None)
    cur_v = ImageHelpers.FINGERPRINT_VERSION
    done = skipped = no_shot = failed = 0

    for tree in trees:
        res = get_tree_nodes(tree['id'], team_id, limit=500)
        for node in res.get('nodes', []):
            data = node.get('data') or {}
            shot = data.get('screenshot') or data.get('screenshot_url')
            label = node.get('label') or node.get('node_id')
            if not shot:
                no_shot += 1
                continue
            if not args.force and (data.get('fingerprint') or {}).get('v') == cur_v:
                skipped += 1
                continue

            tmp = os.path.join(tempfile.gettempdir(), f"fp_{node['node_id']}.jpg")
            try:
                dl = cf.download_file(_remote_key(shot, cf.bucket_name), tmp)
                if not dl.get('success'):
                    print(f"  ✗ {label}: download failed ({dl.get('error')})")
                    failed += 1
                    continue
                img = cv2.imread(tmp)
                fp = helpers.compute_fingerprint(img)   # v4: full-frame dHash + focus
                if not fp:
                    print(f"  ✗ {label}: fingerprint failed (bad image)")
                    failed += 1
                    continue
                data['fingerprint'] = fp
                save = save_node(tree['id'], {'node_id': node['node_id'], 'data': data}, team_id)
                if save.get('success'):
                    print(f"  ✓ {label}: {fp['dhash'][:12]}… focus={fp['focus'].get('kind')}")
                    done += 1
                else:
                    print(f"  ✗ {label}: save failed ({save.get('error')})")
                    failed += 1
            except Exception as e:
                print(f"  ✗ {label}: {e}")
                failed += 1
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

    print(f"\nDone: {done} fingerprinted, {skipped} already current, "
          f"{no_shot} without screenshot, {failed} failed")

    # Invalidate the host's cached unified graph so the new fingerprints are picked
    # up without a restart. The graph bakes each node's fingerprint at BUILD time, so
    # this bulk DB write otherwise leaves vpt-host serving the pre-backfill graph
    # (stale fingerprints → Localize ignores the just-added nodes). Clears the LOCAL
    # host where this script runs; other hosts serving the same UI rebuild on their
    # own next cache build (take-control / tree edit) or need their own clear.
    if done:
        try:
            from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface
            import requests
            root = get_root_tree_for_interface(ui['id'], team_id)
            root_id = (root or {}).get('id')
            api_key = os.getenv('API_KEY')
            if root_id and api_key:
                resp = requests.post(
                    f"http://localhost:6109/host/navigation/cache/clear/{root_id}",
                    params={'team_id': team_id},
                    headers={'X-API-Key': api_key},
                    timeout=10,
                )
                if resp.ok:
                    print(f"✓ Cleared host navigation cache (root tree {root_id}) — "
                          f"Localize will rebuild with the new fingerprints")
                else:
                    print(f"⚠ Host cache clear returned {resp.status_code}: {resp.text[:200]}")
            elif not api_key:
                print("⚠ API_KEY not set — source the host .env first, or restart "
                      "vpt-host so Localize picks up the new fingerprints")
        except Exception as e:
            print(f"⚠ Could not clear host navigation cache ({e}); restart vpt-host "
                  "or take control to rebuild it with the new fingerprints")


if __name__ == '__main__':
    main()
