#!/usr/bin/env python3
"""Fail when a Grafana dashboard would show devices outside the viewer's scope (TASK-31 phase D).

Every dashboard (except the ones _apply_device_scope.SKIP_DASHBOARDS names) must:
  - carry the `workspace` and hidden `allowed_devices` variables, and
  - read every device table through the /*device-scope*/ wrapper, in panels and variable queries.

Exit 1 with one line per problem. Fix with:  python3 _apply_device_scope.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _apply_device_scope import SKIP_DASHBOARDS, TABLE_RE, dashboard_files  # noqa: E402


def problems(path):
    dashboard = json.loads(path.read_text(encoding='utf-8'))
    if 'panels' not in dashboard or path.name in SKIP_DASHBOARDS:
        return []
    found = []
    names = [v.get('name') for v in dashboard.get('templating', {}).get('list', [])]
    for required in ('workspace', 'allowed_devices'):
        if required not in names:
            found.append(f'{path.name}: missing variable `{required}`')

    def walk(node, where):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('rawSql', 'query', 'definition') and isinstance(value, str):
                    for m in TABLE_RE.finditer(value):
                        found.append(f"{path.name}: {where}: unscoped read of `{m.group('table')}`")
                else:
                    walk(value, node.get('title') or node.get('name') or where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    walk(dashboard.get('templating', {}), 'variables')
    walk(dashboard.get('panels', []), 'panel')
    return found


def main(paths):
    here = Path(__file__).parent
    files = [Path(p) for p in paths] or dashboard_files()
    issues = [issue for path in files for issue in problems(path)]
    for issue in issues:
        print(issue)
    if issues:
        print(f'\n{len(issues)} problem(s). Run: python3 {here.name}/_apply_device_scope.py')
        return 1
    print(f'device scope OK ({len(files)} dashboards)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
