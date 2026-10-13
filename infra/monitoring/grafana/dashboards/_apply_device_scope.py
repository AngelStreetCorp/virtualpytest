#!/usr/bin/env python3
"""Make every Grafana dashboard show the viewer only the devices they may see (TASK-31 phase D).

For each dashboard JSON given (default: every *.json next to this script):

1. Adds two variables at the top of the templating list:
   - `workspace`        visible drop-down — "None" plus the viewer's workspaces
                        (grafana_user_workspaces(email, login)). The only new filter people see.
   - `allowed_devices`  hidden — one '|'-joined string of device keys from
                        grafana_device_scope('${__user.email}', '${__user.login}', '${workspace}'):
                        '*' = no limit, '-' = nothing, else host_name:device_id and
                        host_name:device_name keys. Team, role and user limits apply here, unseen.
2. Wraps every read of a device table, in panels AND variable queries:
       FROM script_results sr   ->   FROM (SELECT * FROM script_results /*device-scope*/ WHERE <scope>) sr
   so aggregates, CTEs and joins keep working. <scope> matches host_name + the table's device key
   (device_id when the table has it, else device_name; host-only tables on the host).

Idempotent: wrapped reads carry /*device-scope*/ and are never wrapped twice; the variables are
replaced, not duplicated. A filter on what dashboards show — not authorization.

Usage:  python3 _apply_device_scope.py [dashboard.json ...]     (rewrites in place; default: this
        folder and features/*/grafana/*.json)
Check:  python3 _check_device_scope.py
"""

import json
import re
import sys
from pathlib import Path

MARKER = '/*device-scope*/'
DATASOURCE = {'type': 'grafana-postgresql-datasource', 'uid': 'supabase-postgres'}

# table -> the column that identifies the device next to host_name (None = host-level table)
DEVICE_TABLES = {
    'script_results': 'device_name',
    'campaign_executions': 'device_name',
    'execution_results': 'device_name',
    'zap_results': 'device_name',
    'campaigns': 'device_name',
    'gw_info_latest': 'device_name',
    'device_info_overrides': 'device_name',
    'device_info_latest': 'device_name',
    'alerts': 'device_id',
    'device_control_sessions': 'device_id',
    'device_flags': 'device_id',
    'fleet_health': 'device_id',
    'deployments': 'device_id',
    'system_device_metrics': 'device_id',
    'system_incident': 'device_id',
    'quality_metrics': 'device_id',
    'test_prompt_executions': 'device_id',
    'system_metrics': None,
}

# Dashboards about the platform itself, not about devices: left unscoped on purpose.
SKIP_DASHBOARDS = {'system-server-monitoring.json',
                   'system-service-status.json',  # infra VMs and services, no device data
                   'cicd-quality.json'}  # own datasource and schema (cicd), no device data


def dashboard_files():
    """Every dashboard in the repo: this folder and each feature's grafana/ folder.

    template.json (the Atlas dashboard house style) is not a dashboard and is left out."""
    here = Path(__file__).resolve().parent
    root = here.parents[3]
    files = sorted(here.glob('*.json')) + sorted(root.glob('features/*/grafana/*.json'))
    return [f for f in files if not (f.parent == here and f.name == 'template.json')]

KEYS = "string_to_array(${allowed_devices:sqlstring}, '|')"
_SQL_WORDS = (r'WHERE|ON|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|CROSS|NATURAL|LATERAL|GROUP|ORDER|LIMIT|'
              r'OFFSET|UNION|EXCEPT|INTERSECT|WINDOW|HAVING|USING|FETCH|FOR|AND|OR|SELECT|AS')


def scope_predicate(key_column):
    if key_column is None:
        return (f"('*' = ANY({KEYS}) OR host_name = ANY(ARRAY("
                f"SELECT split_part(k, ':', 1) FROM unnest({KEYS}) AS k)))")
    return f"('*' = ANY({KEYS}) OR host_name || ':' || {key_column} = ANY({KEYS}))"


def _table_pattern():
    tables = '|'.join(sorted(DEVICE_TABLES, key=len, reverse=True))
    return re.compile(
        r'\b(?P<kw>FROM|JOIN)(?P<sp>\s+)(?:public\.)?(?P<table>' + tables + r')\b'
        r'(?!\s*' + re.escape(MARKER) + r')'
        r'(?!\s*\()'                                         # a function call, not a table
        r'(?P<alias>\s+(?:AS\s+)?(?!(?:' + _SQL_WORDS + r')\b)[A-Za-z_][A-Za-z0-9_]*)?',
        re.IGNORECASE,
    )


TABLE_RE = _table_pattern()


def wrap_sql(sql):
    """Wrap every unscoped device-table read in `sql`. Returns (new_sql, count)."""
    def repl(m):
        table = m.group('table').lower()
        alias = (m.group('alias') or '').strip()
        alias = re.sub(r'^AS\s+', '', alias, flags=re.IGNORECASE) or table
        pred = scope_predicate(DEVICE_TABLES[table])
        return (f"{m.group('kw')}{m.group('sp')}(SELECT * FROM {table} {MARKER} WHERE {pred}) {alias}")
    return TABLE_RE.subn(repl, sql)


def _variables():
    workspace_sql = ("SELECT __text, __value FROM (SELECT 0 AS o, 'None' AS __text, 'none' AS __value "
                     "UNION ALL SELECT 1, name, id FROM grafana_user_workspaces(${__user.email:sqlstring}, ${__user.login:sqlstring})) w "
                     "ORDER BY o, __text")
    allowed_sql = ("SELECT string_agg(device_key, '|') FROM grafana_device_scope("
                   "${__user.email:sqlstring}, ${__user.login:sqlstring}, ${workspace:sqlstring})")
    workspace = {
        'current': {'text': 'None', 'value': 'none'},
        'datasource': dict(DATASOURCE),
        'definition': workspace_sql,
        'includeAll': False,
        'label': 'Workspace',
        'multi': False,
        'name': 'workspace',
        'query': workspace_sql,
        'refresh': 1,
        'regex': '',
        'sort': 0,
        'type': 'query',
    }
    allowed = {
        'current': {},
        'datasource': dict(DATASOURCE),
        'definition': allowed_sql,
        'hide': 2,
        'includeAll': False,
        'label': 'Allowed devices',
        'multi': False,
        'name': 'allowed_devices',
        'query': allowed_sql,
        'refresh': 1,
        'regex': '',
        'sort': 0,
        'type': 'query',
    }
    return [workspace, allowed]


def _walk_sql(node, counter):
    """Rewrite every SQL string (rawSql, variable query/definition) under `node` in place."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ('rawSql', 'query', 'definition') and isinstance(value, str):
                new, n = wrap_sql(value)
                if n:
                    node[key] = new
                    counter[0] += n
            else:
                _walk_sql(value, counter)
    elif isinstance(node, list):
        for item in node:
            _walk_sql(item, counter)


def apply(dashboard):
    """Scope one dashboard dict in place. Returns the number of reads wrapped."""
    templating = dashboard.setdefault('templating', {}).setdefault('list', [])
    others = [v for v in templating if v.get('name') not in ('workspace', 'allowed_devices')]
    counter = [0]
    _walk_sql(others, counter)
    _walk_sql(dashboard.get('panels', []), counter)
    dashboard['templating']['list'] = _variables() + others
    return counter[0]


def _write_like(path, raw, dashboard):
    """Write `dashboard` in the file's own style (indent, escaping, final newline, LF) so the
    diff shows only the scope changes."""
    m = re.search(r'\n( +)"', raw)
    indent = len(m.group(1)) if m else None
    text = json.dumps(dashboard, indent=indent, ensure_ascii='\\u' in raw)
    if raw.endswith('\n'):
        text += '\n'
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def main(paths):
    files = [Path(p) for p in paths] or dashboard_files()
    for path in files:
        if path.name in SKIP_DASHBOARDS:
            print(f'skip   {path.name} (not about devices)')
            continue
        raw = path.read_text(encoding='utf-8')
        dashboard = json.loads(raw)
        if 'panels' not in dashboard:
            continue
        before = json.dumps(dashboard, sort_keys=True)
        wrapped = apply(dashboard)
        if json.dumps(dashboard, sort_keys=True) != before:
            _write_like(path, raw, dashboard)
            print(f'scoped {path.name}: {wrapped} device-table read(s) wrapped')
        else:
            print(f'ok     {path.name}')


if __name__ == '__main__':
    main(sys.argv[1:])
