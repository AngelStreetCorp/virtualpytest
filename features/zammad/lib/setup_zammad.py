"""One-off, re-runnable Zammad setup for the ticket model (TASK-96). Idempotent: run it after every new
Zammad instance and after any change to model.py; a second run changes nothing.

    set -a; . .env; set +a            # ZAMMAD_URL and ZAMMAD_API_TOKEN (an admin's token)
    python3 -m features.zammad.lib.setup_zammad

It creates (or updates) on the instance:
  * the ticket states of the workflow (accepted, assigned, in progress, need info, fixed, delivered,
    reopened, duplicate, won't fix) with the right state types - model.CUSTOM_ZAMMAD_STATES;
  * the Object Manager ticket attributes vpt_type, vpt_family, vpt_category, vpt_target, vpt_severity,
    vpt_frequency, vpt_fixed_in_build, then runs the object manager migration (Zammad restarts its
    application server for a moment; the script waits until the API answers again).
The groups (Devices, Hosts & System, Scripts, Dashboards, Platform) are created elsewhere and only checked here.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

from features.zammad.lib.model import (
    ALL_GROUPS, CUSTOM_ZAMMAD_STATES, FAMILIES, FREQUENCIES, SEVERITIES, TICKET_TYPES,
)

# Cloudflare in front of the instance rejects the default python user agent.
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
# Zammad's built-in ticket state types (stable ids in a stock install; looked up by an existing state first).
STATE_TYPE_IDS = {'new': 1, 'open': 2, 'pending reminder': 3, 'pending action': 4, 'closed': 5, 'merged': 6}
BUILTIN_STATE_FOR_TYPE = {'new': 'new', 'open': 'open', 'pending reminder': 'pending reminder',
                          'pending action': 'pending close', 'closed': 'closed', 'merged': 'merged'}

LABELS = {
    'incident': 'Incident', 'bug': 'Bug', 'request': 'Request', 'question': 'Question',
    'blocker': 'Blocker', 'major': 'Major', 'minor': 'Minor',
    'always': 'Always', 'frequent': 'Frequent', 'random': 'Random', 'once': 'Seen once',
    'platform': 'Platform', 'scripting': 'Scripting', 'monitoring': 'Monitoring', 'dashboards': 'Dashboards',
    'ai': 'AI', 'server': 'Server', 'host': 'Host', 'device': 'Device', 'service': 'Service',
    'script': 'Script', 'campaign': 'Campaign', 'virtual_script': 'Virtual script', 'testcase': 'Testcase',
    'heatmap': 'Heatmap', 'timeline': 'Timeline', 'grafana': 'Grafana', 'report': 'Report', 'agent': 'Agent',
}
# 'incident' is both a ticket type and a monitoring category: one option set per attribute, so no clash.


def _select(keys: List[str]) -> Dict[str, Any]:
    return {'data_type': 'select', 'data_option': {
        'options': {k: LABELS[k] for k in keys}, 'default': '', 'null': True, 'nulloption': True, 'translate': False}}


def _input() -> Dict[str, Any]:
    return {'data_type': 'input', 'data_option': {'type': 'text', 'maxlength': 255, 'null': True, 'translate': False}}


def attribute_specs() -> List[Dict[str, Any]]:
    categories = [c for cats in FAMILIES.values() for c in cats]
    specs = [
        ('vpt_type', 'VPT type', _select(list(TICKET_TYPES))),
        ('vpt_family', 'VPT family', _select(list(FAMILIES))),
        ('vpt_category', 'VPT category', _select(categories)),
        ('vpt_target', 'VPT target', _input()),
        ('vpt_severity', 'VPT severity', _select(list(SEVERITIES))),
        ('vpt_frequency', 'VPT frequency', _select(list(FREQUENCIES))),
        ('vpt_fixed_in_build', 'VPT fixed in build', _input()),
    ]
    out = []
    for position, (name, display, body) in enumerate(specs, start=1600):
        out.append({
            'name': name, 'object': 'Ticket', 'display': display, 'active': True, 'position': position,
            'screens': {'create_middle': {'-all-': {'shown': True, 'required': False}},
                        'edit': {'-all-': {'shown': True, 'required': False}}},
            **body,
        })
    return out


class Setup:
    def __init__(self, base_url: str, token: str) -> None:
        self.base = base_url.rstrip('/') + '/api/v1'
        self.http = requests.Session()
        self.http.headers.update({'Authorization': f'Token token={token}', 'Accept': 'application/json',
                                  'User-Agent': USER_AGENT})

    def call(self, method: str, path: str, **kw) -> Any:
        resp = self.http.request(method, f'{self.base}{path}', timeout=60, **kw)
        if resp.status_code >= 400:
            # the body can describe the request; keep the hint short and token-free
            raise RuntimeError(f'{method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}')
        return resp.json() if resp.content else None

    def states(self) -> List[str]:
        states = self.call('GET', '/ticket_states')
        by_name = {s['name']: s for s in states}
        done: List[str] = []
        for name, type_name in CUSTOM_ZAMMAD_STATES.items():
            builtin = by_name.get(BUILTIN_STATE_FOR_TYPE[type_name])
            type_id = builtin['state_type_id'] if builtin else STATE_TYPE_IDS[type_name]
            if name in by_name:
                if by_name[name]['state_type_id'] != type_id or not by_name[name].get('active'):
                    self.call('PUT', f"/ticket_states/{by_name[name]['id']}",
                              json={'name': name, 'state_type_id': type_id, 'active': True})
                    done.append(f'{name}: updated')
                continue
            self.call('POST', '/ticket_states', json={
                'name': name, 'state_type_id': type_id, 'active': True,
                'ignore_escalation': False, 'note': 'VirtualPyTest ticket workflow'})
            done.append(f'{name}: created')
        return done

    @staticmethod
    def _same(current: Dict[str, Any], spec: Dict[str, Any]) -> bool:
        """Zammad adds defaults to data_option, so compare only the keys we set."""
        have = current.get('data_option') or {}
        return current.get('display') == spec['display'] and current.get('data_type') == spec['data_type'] \
            and all(have.get(k) == v for k, v in spec['data_option'].items())

    def attributes(self) -> List[str]:
        existing = {a['name']: a for a in self.call('GET', '/object_manager_attributes') if a['object'] == 'Ticket'}
        done: List[str] = []
        for spec in attribute_specs():
            current = existing.get(spec['name'])
            if current is None:
                self.call('POST', '/object_manager_attributes', json=spec)
                done.append(f"{spec['name']}: created")
            elif not self._same(current, spec):
                self.call('PUT', f"/object_manager_attributes/{current['id']}", json={**spec, 'id': current['id']})
                done.append(f"{spec['name']}: updated")
        return done

    def migrate(self) -> None:
        self.call('POST', '/object_manager_attributes_execute_migrations')
        # Zammad restarts its application server for the migration; wait for the API to answer again.
        for _ in range(60):
            time.sleep(3)
            try:
                pending = [a for a in self.call('GET', '/object_manager_attributes')
                           if a['object'] == 'Ticket' and a['name'].startswith('vpt_') and a.get('to_create')]
                if not pending:
                    return
            except (RuntimeError, requests.RequestException):
                continue
        raise RuntimeError('the object manager migration did not finish within 3 minutes')

    def check_groups(self) -> List[str]:
        names = {g['name'] for g in self.call('GET', '/groups')}
        return sorted(ALL_GROUPS - names)


def main(argv: Optional[List[str]] = None) -> int:
    url, token = os.environ.get('ZAMMAD_URL', ''), os.environ.get('ZAMMAD_API_TOKEN', '')
    if not url or not token:
        print('ZAMMAD_URL and ZAMMAD_API_TOKEN are required', file=sys.stderr)
        return 2
    setup = Setup(url, token)
    missing = setup.check_groups()
    if missing:
        print(f'missing groups (create them in Zammad first): {", ".join(missing)}', file=sys.stderr)
        return 1
    states = setup.states()
    attrs = setup.attributes()
    for line in states + attrs:
        print(line)
    if attrs:
        setup.migrate()
        print('object manager migration executed')
    print('zammad ticket model is in place' if (states or attrs) else 'nothing to change, already in place')
    return 0


if __name__ == '__main__':
    sys.exit(main())
