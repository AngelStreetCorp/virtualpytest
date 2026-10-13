"""Unit tests: every Grafana dashboard reads devices through the viewer's scope (TASK-31 phase D).

- the committed dashboards pass _check_device_scope.py (a new or edited dashboard that reads a
  device table directly fails here);
- _apply_device_scope.py is idempotent on every committed dashboard;
- the SQL rewrite keeps aliases, skips functions and already-scoped reads, and uses the right key.

SQL validity was checked separately by EXPLAINing every original and scoped query on a database;
this test only guards the shape.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DASHBOARDS = Path(__file__).resolve().parents[2] / 'infra' / 'monitoring' / 'grafana' / 'dashboards'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, DASHBOARDS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply_mod = _load('_apply_device_scope')
check_mod = _load('_check_device_scope')
FILES = apply_mod.dashboard_files()


def test_committed_dashboards_are_scoped():
    issues = [i for p in FILES for i in check_mod.problems(p)]
    assert not issues, '\n'.join(issues) + '\nRun infra/monitoring/grafana/dashboards/_apply_device_scope.py'


@pytest.mark.parametrize('path', FILES, ids=lambda p: p.name)
def test_apply_is_idempotent(path):
    dashboard = json.loads(path.read_text(encoding='utf-8'))
    if 'panels' not in dashboard or path.name in apply_mod.SKIP_DASHBOARDS:
        pytest.skip('not a scoped dashboard')
    again = copy.deepcopy(dashboard)
    assert apply_mod.apply(again) == 0
    assert again == dashboard


def test_planted_unscoped_read_is_caught(tmp_path):
    dashboard = json.loads((DASHBOARDS / 'script-results.json').read_text(encoding='utf-8'))
    dashboard['panels'].append({'title': 'planted', 'targets': [{'rawSql': 'SELECT count(*) FROM script_results'}]})
    planted = tmp_path / 'script-results.json'
    planted.write_text(json.dumps(dashboard), encoding='utf-8')
    assert any('planted' in i and 'script_results' in i for i in check_mod.problems(planted))


class TestWrap:

    def test_keeps_alias(self):
        sql, n = apply_mod.wrap_sql('SELECT sr.id FROM script_results sr JOIN alerts AS a ON true')
        assert n == 2
        assert ') sr JOIN' in sql and ') a ON true' in sql

    def test_table_name_becomes_the_alias(self):
        sql, _ = apply_mod.wrap_sql('SELECT script_results.id FROM script_results WHERE true')
        assert ') script_results WHERE true' in sql

    def test_key_column_per_table(self):
        by_name, _ = apply_mod.wrap_sql('SELECT 1 FROM script_results')
        by_id, _ = apply_mod.wrap_sql('SELECT 1 FROM fleet_health')
        by_host, _ = apply_mod.wrap_sql('SELECT 1 FROM system_metrics')
        assert "|| ':' || device_name" in by_name
        assert "|| ':' || device_id" in by_id
        assert "split_part(k, ':', 1)" in by_host

    def test_leaves_other_tables_and_functions_alone(self):
        for sql in ('SELECT 1 FROM navigation_trees', 'SELECT * FROM grafana_device_scope(1, 2, 3)',
                    'SELECT 1 FROM script_results_archive'):
            assert apply_mod.wrap_sql(sql)[1] == 0

    def test_variables_come_first_and_allowed_devices_is_hidden(self):
        dashboard = {'panels': [], 'templating': {'list': [{'name': 'host', 'query': 'SELECT 1'}]}}
        apply_mod.apply(dashboard)
        names = [v['name'] for v in dashboard['templating']['list']]
        assert names == ['workspace', 'allowed_devices', 'host']
        allowed = dashboard['templating']['list'][1]
        assert allowed['hide'] == 2 and 'grafana_device_scope' in allowed['query']
        assert '__user.email' in allowed['query'] and '__user.login' in allowed['query']
        assert dashboard['templating']['list'][0].get('hide', 0) == 0
        workspace = dashboard['templating']['list'][0]
        # BUG-0212: the login is what identifies Grafana's built-in admin (no profile, no email match).
        assert 'grafana_user_workspaces' in workspace['query']
        assert '__user.email' in workspace['query'] and '__user.login' in workspace['query']
