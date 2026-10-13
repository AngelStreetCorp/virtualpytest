#!/usr/bin/env python3
"""
One-shot: set every existing Grafana user's org role from their VirtualPyTest role (TASK-31 D1).

The Grafana mirror only runs when a user is provisioned or their role changes, so after the role
map changed (every non-admin role is now a Grafana Viewer) existing accounts keep their old role
until this runs once. Matches on email, the key both systems share. Grafana's built-in server admin
(GRAFANA_ADMIN_USER) is never touched, and neither is any Grafana account without a VirtualPyTest
profile.

Reads GRAFANA_URL / GRAFANA_ADMIN_USER / GRAFANA_ADMIN_PASSWORD and the Supabase keys from the
server's .env, like the server does.

Usage (on the server VM, as the service user):
    python3 scripts/grafana_sync_org_roles.py            # dry run: prints what would change
    python3 scripts/grafana_sync_org_roles.py --apply
"""

import argparse
import os
import sys

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, '.env'), override=False, encoding='utf-8-sig')

from backend_server.src.lib.utils.grafana_config import grafana_org_id, grafana_role_for  # noqa: E402
from shared.src.lib.database import users_db  # noqa: E402
from shared.src.lib.utils import grafana_admin  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='Sync Grafana org roles from VirtualPyTest roles.')
    parser.add_argument('--apply', action='store_true', help='write the roles (default: dry run)')
    args = parser.parse_args()

    base, auth = grafana_admin._cfg()
    builtin_admin = (os.environ.get('GRAFANA_ADMIN_USER') or 'admin').lower()
    org_id = grafana_org_id()
    resp = requests.get(f'{base}/api/orgs/{org_id}/users', auth=auth, timeout=15)
    resp.raise_for_status()
    members = {(m.get('email') or '').lower(): m for m in resp.json()}

    changed = unchanged = skipped = 0
    for user in users_db.get_all_users():
        email = (user.get('email') or '').strip().lower()
        member = members.get(email)
        if not member or (member.get('login') or '').lower() == builtin_admin:
            skipped += 1
            continue
        target = grafana_role_for(user.get('role', 'viewer'))
        if member.get('role') == target:
            unchanged += 1
            continue
        print(f"{'set' if args.apply else 'would set'} {email}: {member.get('role')} -> {target}")
        if args.apply:
            grafana_admin.grafana_set_org_role(email, target, org_id=org_id)
        changed += 1

    print()
    print(f"{changed} {'changed' if args.apply else 'to change'}, {unchanged} already right, "
          f"{skipped} skipped (built-in admin, or not a Grafana member).")
    if not args.apply and changed:
        print('Dry run. Re-run with --apply to write them.')


if __name__ == '__main__':
    main()
