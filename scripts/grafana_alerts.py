#!/usr/bin/env python3
"""
Apply the predefined VirtualPyTest alert rules to Grafana (unified alerting, Grafana 11+).

The rules live in infra/monitoring/grafana/alerting/vpt-alert-rules.json. Applying creates, all
idempotent and safe to re-run:
  - the folder "VirtualPyTest Alerts" (uid vpt-alerts)
  - an email contact point "VirtualPyTest email" (uid vpt-email) with --email addresses, using the
    notification template "vpt-email" (subject "[VirtualPyTest] 3 firing, 1 resolved", one line
    per alert — instead of Grafana's default mail with its raw "A=2 C=1" query values)
  - a notification policy (route) for label source=virtualpytest -> that contact point, which sets
    how alerts are grouped into one mail and how often mails go out (--group-by, --group-wait,
    --group-interval, --repeat-interval). Other routes of the policy tree are left as they are.
  - one rule group per catalog group, holding the selected rules
Rules are created editable in the Grafana UI. Re-running resets VPT rules to the catalog (thresholds
edited in the UI are overwritten) and removes rules of a VPT group that are no longer selected —
keep your own rules out of the "VirtualPyTest Alerts" folder.

Email delivery needs SMTP configured in grafana.ini ([smtp]) — see docs/user-guide/grafana-alerting.md.

Reads GRAFANA_URL / GRAFANA_ADMIN_USER / GRAFANA_ADMIN_PASSWORD (and TEAM_ID) from the
environment or the repo .env, like the server does.

Usage:
    python3 scripts/grafana_alerts.py list
    python3 scripts/grafana_alerts.py status
    python3 scripts/grafana_alerts.py test-email --email ops@example.com
    python3 scripts/grafana_alerts.py apply --email ops@example.com,qa@example.com --team-id <uuid>
    python3 scripts/grafana_alerts.py apply --email ops@example.com --rules vpt-host-disk-high,vpt-host-offline
    python3 scripts/grafana_alerts.py apply --email ops@example.com --rules all --team-id <uuid>
    python3 scripts/grafana_alerts.py apply --email ops@example.com --group-by rule --group-interval 30m
    python3 scripts/grafana_alerts.py remove
"""

import argparse
import json
import os
import sys
import time

import requests
import urllib3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(PROJECT_ROOT, 'infra', 'monitoring', 'grafana', 'alerting', 'vpt-alert-rules.json')

FOLDER_UID = 'vpt-alerts'
FOLDER_TITLE = 'VirtualPyTest Alerts'
CONTACT_UID = 'vpt-email'
CONTACT_NAME = 'VirtualPyTest email'
TEMPLATE_NAME = 'vpt-email'
ROUTE_MATCHER = ['source', '=', 'virtualpytest']
# What lands in the same mail: everything / one mail per rule / one mail per host.
GROUP_BY = {'all': ['grafana_folder'], 'rule': ['grafana_folder', 'alertname'],
            'host': ['grafana_folder', 'host_name']}

# Go template (Grafana notification template). Summaries already carry the measured value.
TEMPLATE = '''{{ define "vpt.subject" }}[VirtualPyTest] {{ if .Alerts.Firing }}{{ len .Alerts.Firing }} firing{{ end }}{{ if and .Alerts.Firing .Alerts.Resolved }}, {{ end }}{{ if .Alerts.Resolved }}{{ len .Alerts.Resolved }} resolved{{ end }}{{ end }}

{{ define "vpt.message" }}{{ if .Alerts.Firing }}FIRING ({{ len .Alerts.Firing }})
{{ range .Alerts.Firing }}- [{{ .Labels.severity }}] {{ .Labels.alertname }}: {{ .Annotations.summary }}
{{ end }}{{ end }}{{ if .Alerts.Resolved }}
RESOLVED ({{ len .Alerts.Resolved }})
{{ range .Alerts.Resolved }}- {{ .Labels.alertname }}: {{ .Annotations.summary }}
{{ end }}{{ end }}
All VirtualPyTest alerts: {{ .ExternalURL }}alerting/list?search=label:source%3Dvirtualpytest
{{ end }}'''
TIMEOUT = 20

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'), override=False, encoding='utf-8-sig')
except ImportError:
    pass


class Grafana:
    def __init__(self, base, user, password, verify):
        self.base = base.rstrip('/')
        self.s = requests.Session()
        self.s.auth = (user, password)
        self.s.verify = verify
        # Without this header provisioned objects are locked in the UI.
        self.s.headers['X-Disable-Provenance'] = 'true'

    def call(self, method, path, ok=(200, 201, 202, 204), **kw):
        r = self.s.request(method, f'{self.base}{path}', timeout=TIMEOUT, **kw)
        if r.status_code not in ok:
            raise SystemExit(f'{method} {path} -> {r.status_code}: {r.text[:400]}')
        return r.json() if r.content and r.headers.get('content-type', '').startswith('application/json') else None


def seconds(duration):
    """'30s' / '5m' / '1h' -> seconds."""
    return int(duration[:-1]) * {'s': 1, 'm': 60, 'h': 3600}[duration[-1]]


def load_catalog():
    with open(CATALOG, encoding='utf-8') as f:
        return json.load(f)['groups']


def select_rules(groups, wanted):
    """Return {group_name: (interval, [rule, ...])} for the wanted selection."""
    all_uids = {r['uid'] for g in groups for r in g['rules']}
    if wanted not in ('recommended', 'all'):
        asked = {u.strip() for u in wanted.split(',') if u.strip()}
        unknown = asked - all_uids
        if unknown:
            raise SystemExit(f'Unknown rule uid(s): {", ".join(sorted(unknown))} — see `list`')
    out = {}
    for g in groups:
        rules = [r for r in g['rules']
                 if wanted == 'all'
                 or (wanted == 'recommended' and r['recommended'])
                 or (wanted not in ('recommended', 'all') and r['uid'] in asked)]
        out[g['name']] = (g['interval'], rules)
    return out


def missing_tables(gf, ds_uid, tables):
    """Tables (of `tables`) the datasource does not have — asked through Grafana itself."""
    if not tables:
        return set()
    names = ','.join(f"'{t}'" for t in sorted(tables))
    sql = (f"SELECT t FROM unnest(ARRAY[{names}]) AS t "
           f"WHERE to_regclass('public.' || t) IS NULL")
    res = gf.call('POST', '/api/ds/query', json={
        'from': 'now-5m', 'to': 'now',
        'queries': [{'refId': 'A', 'datasource': {'uid': ds_uid}, 'rawSql': sql, 'format': 'table'}]})
    frames = res['results']['A'].get('frames') or []
    values = frames[0]['data']['values'] if frames and frames[0].get('data') else []
    return set(values[0]) if values else set()


def build_rule(rule, group, ds_uid, team_id):
    sql = rule['sql']
    if '{{team_id}}' in sql:
        if not team_id:
            raise SystemExit(f'{rule["uid"]} needs --team-id (or TEAM_ID in .env)')
        sql = sql.replace('{{team_id}}', team_id)
    th = rule['threshold']
    return {
        'uid': rule['uid'],
        'title': rule['title'],
        'folderUID': FOLDER_UID,
        'ruleGroup': group,
        'condition': 'C',
        'data': [
            {'refId': 'A', 'datasourceUid': ds_uid, 'relativeTimeRange': {'from': 600, 'to': 0},
             'model': {'refId': 'A', 'rawSql': sql, 'rawQuery': True, 'editorMode': 'code', 'format': 'table'}},
            {'refId': 'C', 'datasourceUid': '__expr__', 'relativeTimeRange': {'from': 0, 'to': 0},
             'model': {'refId': 'C', 'type': 'threshold', 'expression': 'A',
                       'conditions': [{'evaluator': {'type': th['op'], 'params': [th['value']]}}]}},
        ],
        # Zero rows means nothing is wrong; a broken query must still be visible.
        'noDataState': 'OK',
        'execErrState': 'Error',
        'for': rule['for'],
        'labels': {'severity': rule['severity'], 'source': 'virtualpytest'},
        'annotations': {'summary': rule['summary'], 'description': rule['description']},
    }


def ensure_folder(gf):
    r = gf.s.get(f'{gf.base}/api/folders/{FOLDER_UID}', timeout=TIMEOUT)
    if r.status_code == 404:
        gf.call('POST', '/api/folders', json={'uid': FOLDER_UID, 'title': FOLDER_TITLE})
        print(f'folder     created  {FOLDER_TITLE}')
    elif r.status_code == 200:
        print(f'folder     exists   {FOLDER_TITLE}')
    else:
        raise SystemExit(f'GET folder -> {r.status_code}: {r.text[:300]}')


def ensure_template(gf):
    gf.call('PUT', f'/api/v1/provisioning/templates/{TEMPLATE_NAME}', json={'template': TEMPLATE})
    print(f'template   applied  {TEMPLATE_NAME}')


def is_vpt_route(route):
    return ROUTE_MATCHER in (route.get('object_matchers') or [])


def ensure_policy(gf, args):
    tree = gf.call('GET', '/api/v1/provisioning/policies')
    route = {'receiver': CONTACT_NAME, 'object_matchers': [ROUTE_MATCHER],
             'group_by': GROUP_BY[args.group_by], 'group_wait': args.group_wait,
             'group_interval': args.group_interval, 'repeat_interval': args.repeat_interval}
    tree['routes'] = [route] + [r for r in tree.get('routes') or [] if not is_vpt_route(r)]
    gf.call('PUT', '/api/v1/provisioning/policies', json=tree)
    print(f'policy     applied  source=virtualpytest -> {CONTACT_NAME}: group by {args.group_by}, '
          f'first mail after {args.group_wait}, then at most every {args.group_interval}, '
          f'unchanged alerts repeated every {args.repeat_interval}')
    # Grafana's running Alertmanager reloads the saved config on a ~60 s poll. Rules created before
    # that would send their first alerts through the old tree (the default contact point).
    for _ in range(45):
        running = (gf.call('GET', '/api/alertmanager/grafana/api/v2/status') or {}).get('config', {})
        if any(is_vpt_route(r) and r.get('group_interval') == args.group_interval
               for r in running.get('route', {}).get('routes') or []):
            print('policy     active in the running Alertmanager')
            return
        time.sleep(3)
    print('policy     WARNING: not active yet after 135 s; the first alerts may go to the default contact point')


def ensure_contact_point(gf, emails):
    body = {'uid': CONTACT_UID, 'name': CONTACT_NAME, 'type': 'email',
            'settings': {'addresses': ';'.join(emails), 'singleEmail': True,
                         'subject': '{{ template "vpt.subject" . }}',
                         'message': '{{ template "vpt.message" . }}'},
            'disableResolveMessage': False}
    existing = gf.call('GET', '/api/v1/provisioning/contact-points', params={'name': CONTACT_NAME}) or []
    if any(cp.get('uid') == CONTACT_UID for cp in existing):
        gf.call('PUT', f'/api/v1/provisioning/contact-points/{CONTACT_UID}', json=body)
        print(f'contact    updated  {CONTACT_NAME} -> {", ".join(emails)}')
    else:
        gf.call('POST', '/api/v1/provisioning/contact-points', json=body)
        print(f'contact    created  {CONTACT_NAME} -> {", ".join(emails)}')


def connect(args):
    base = args.grafana_url or os.environ.get('GRAFANA_URL')
    user = os.environ.get('GRAFANA_ADMIN_USER', 'admin')
    pw = os.environ.get('GRAFANA_ADMIN_PASSWORD')
    if not (base and pw):
        raise SystemExit('Set GRAFANA_URL and GRAFANA_ADMIN_PASSWORD (env or .env), or pass --grafana-url')
    if args.insecure:
        urllib3.disable_warnings()
    return Grafana(base, user, pw, verify=not args.insecure)


def split_emails(value):
    emails = [e.strip() for e in value.replace(';', ',').split(',') if e.strip()]
    if not emails:
        raise SystemExit('--email needs at least one address')
    return emails


def cmd_list(_args):
    for g in load_catalog():
        print(f'\n{g["name"]}  (evaluated every {g["interval"]})')
        for r in g['rules']:
            th = r['threshold']
            tag = 'recommended' if r['recommended'] else 'opt-in     '
            print(f'  {tag}  {r["uid"]:<28} {r["severity"]:<8} value {th["op"]} {th["value"]:<4} for {r["for"]:<4} {r["title"]}')


def cmd_apply(args):
    gf = connect(args)
    if seconds(args.repeat_interval) < seconds(args.group_interval):
        raise SystemExit('--repeat-interval must be >= --group-interval')
    team_id = args.team_id or os.environ.get('TEAM_ID')
    selection = select_rules(load_catalog(), args.rules)
    # A rule reading a table whose migration is not applied yet would only raise DatasourceError.
    missing = missing_tables(gf, args.datasource_uid,
                             {t for _, rules in selection.values() for r in rules for t in r.get('requires', [])})
    for group, (interval, rules) in selection.items():
        for r in [r for r in rules if missing & set(r.get('requires', []))]:
            print(f'rule       skipped  {r["uid"]}: table {", ".join(sorted(missing & set(r["requires"])))} '
                  f'not in the database yet (apply its migration, then re-run)')
        selection[group] = (interval, [r for r in rules if not missing & set(r.get('requires', []))])
    # Build every group before touching Grafana, so a missing --team-id applies nothing.
    bodies = {group: ({'title': group, 'interval': seconds(interval),
                       'rules': [build_rule(r, group, args.datasource_uid, team_id) for r in rules]}, rules)
              for group, (interval, rules) in selection.items() if rules}
    if not bodies:
        raise SystemExit('No rule selected')
    emails = split_emails(args.email)
    ensure_folder(gf)
    ensure_template(gf)
    ensure_contact_point(gf, emails)
    # The route exists before the rules, so their first alerts are routed (and grouped) correctly.
    ensure_policy(gf, args)
    for group, (body, rules) in bodies.items():
        path = f'/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{requests.utils.quote(group, safe="")}'
        gf.call('PUT', path, json=body)
        print(f'group      applied  {group}: {", ".join(r["uid"] for r in rules)}')
    print('\nDone. Check Alerting > Alert rules > folder "VirtualPyTest Alerts" in Grafana.')


def cmd_remove(args):
    gf = connect(args)
    for g in load_catalog():
        path = f'/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{requests.utils.quote(g["name"], safe="")}'
        r = gf.s.delete(f'{gf.base}{path}', timeout=TIMEOUT)
        print(f'group      {"removed " if r.status_code in (200, 204) else "absent  "} {g["name"]}')
    tree = gf.call('GET', '/api/v1/provisioning/policies')
    if any(is_vpt_route(r) for r in tree.get('routes') or []):
        tree['routes'] = [r for r in tree['routes'] if not is_vpt_route(r)]
        gf.call('PUT', '/api/v1/provisioning/policies', json=tree)
        print('policy     removed  source=virtualpytest')
    r = gf.s.delete(f'{gf.base}/api/v1/provisioning/contact-points/{CONTACT_UID}', timeout=TIMEOUT)
    print(f'contact    {"removed " if r.status_code in (200, 202, 204) else "kept    "} {CONTACT_NAME}'
          + ('' if r.status_code in (200, 202, 204) else f' ({r.status_code}: {r.text[:120]})'))
    r = gf.s.delete(f'{gf.base}/api/v1/provisioning/templates/{TEMPLATE_NAME}', timeout=TIMEOUT)
    print(f'template   {"removed " if r.status_code in (200, 202, 204) else "absent  "} {TEMPLATE_NAME}')


def cmd_status(args):
    gf = connect(args)
    health = gf.call('GET', '/api/health')
    print(f'grafana    {health.get("version")}')
    cps = gf.call('GET', '/api/v1/provisioning/contact-points') or []
    for cp in cps:
        print(f'contact    {cp["name"]:<28} {cp["type"]:<8} {cp.get("settings", {}).get("addresses", "")}')
    rules = gf.call('GET', '/api/v1/provisioning/alert-rules') or []
    vpt = [r for r in rules if r.get('folderUID') == FOLDER_UID]
    print(f'rules      {len(rules)} total, {len(vpt)} in "{FOLDER_TITLE}"')
    states = gf.call('GET', '/api/prometheus/grafana/api/v1/rules') or {}
    for grp in states.get('data', {}).get('groups', []):
        if grp.get('folderUid') not in (None, FOLDER_UID) and grp.get('file') != FOLDER_TITLE:
            continue
        for r in grp.get('rules', []):
            firing = [a for a in r.get('alerts', []) if a.get('state', '').lower().startswith('alerting')]
            print(f'  {r.get("health", ""):<6} {r.get("state", ""):<8} {len(firing):>3} firing  {r.get("name")}')
            for a in firing[:args.max_alerts]:
                print(f'           - {a.get("annotations", {}).get("summary", a.get("labels"))}')


def cmd_test_email(args):
    gf = connect(args)
    emails = split_emails(args.email)
    body = {'receivers': [{'name': 'vpt-test', 'grafana_managed_receiver_configs': [
        {'uid': '', 'name': 'vpt-test', 'type': 'email', 'settings': {'addresses': ';'.join(emails)}}]}],
            'alert': {'annotations': {'summary': 'VirtualPyTest alerting test email'},
                      'labels': {'alertname': 'VirtualPyTest test', 'source': 'virtualpytest'}}}
    r = gf.s.post(f'{gf.base}/api/alertmanager/grafana/config/api/v1/receivers/test', json=body, timeout=60)
    data = r.json() if r.content else {}
    for rcv in data.get('receivers', []):
        for cfg in rcv.get('grafana_managed_receiver_configs', []):
            if cfg.get('status') == 'ok':
                print(f'sent       test email to {", ".join(emails)}')
            else:
                print(f'FAILED     {cfg.get("error", "unknown error")}')
                sys.exit(1)
    if r.status_code not in (200, 207):
        raise SystemExit(f'test -> {r.status_code}: {r.text[:400]}')


def main():
    p = argparse.ArgumentParser(description='Apply predefined VirtualPyTest alert rules to Grafana.')
    p.add_argument('--grafana-url', help='Grafana base URL incl. sub-path (default: $GRAFANA_URL)')
    p.add_argument('--insecure', action='store_true', help='Do not verify TLS (self-signed certificate)')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('list', help='Show the rule catalog')

    a = sub.add_parser('apply', help='Create/update folder, contact point and rules')
    a.add_argument('--email', required=True, help='Recipients, comma separated')
    a.add_argument('--rules', default='recommended', help='recommended (default), all, or comma separated uids')
    a.add_argument('--team-id', help='Team whose script results are watched (default: $TEAM_ID)')
    a.add_argument('--datasource-uid', default='supabase-postgres')
    a.add_argument('--group-by', choices=sorted(GROUP_BY), default='all',
                   help='all = one mail for every VPT alert (default), rule = one mail per rule, host = per host')
    a.add_argument('--group-wait', default='1m', help='Wait before the first mail of a new group (default 1m)')
    a.add_argument('--group-interval', default='1h',
                   help='At most one mail per group per this interval when alerts change (default 1h)')
    a.add_argument('--repeat-interval', default='24h',
                   help='Re-send a group whose alerts did not change (default 24h)')

    sub.add_parser('remove', help='Delete the VPT rule groups and contact point')

    s = sub.add_parser('status', help='Show contact points and rule states')
    s.add_argument('--max-alerts', type=int, default=5)

    t = sub.add_parser('test-email', help='Send a test notification through Grafana SMTP')
    t.add_argument('--email', required=True)

    args = p.parse_args()
    {'list': cmd_list, 'apply': cmd_apply, 'remove': cmd_remove,
     'status': cmd_status, 'test-email': cmd_test_email}[args.cmd](args)


if __name__ == '__main__':
    main()
