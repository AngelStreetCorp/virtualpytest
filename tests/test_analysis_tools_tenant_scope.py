"""P0-4 — `script_results` reads/writes must be tenant-scoped (team_id filter).

Regression for the tenant-safety blocker found in the P0-1 review: the MCP
`analysis_tools` queried `script_results` without a `team_id` filter while the
shared DB layer always filters it. Both `get_execution_results` and
`update_execution_analysis` must scope by team.
"""
from backend_server.src.mcp.tools.analysis_tools import AnalysisTools


class _Response:
    data = []


class _Query:
    def __init__(self, rec):
        self.rec = rec

    def select(self, *a, **k):
        return self

    def update(self, data):
        self.rec['update'] = data
        return self

    def eq(self, column, value):
        self.rec.setdefault('eq', []).append((column, value))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Response()


class _Supabase:
    def __init__(self, rec):
        self.rec = rec

    def table(self, name):
        self.rec['table'] = name
        return _Query(self.rec)


def _tools(rec):
    tools = AnalysisTools()
    tools._get_supabase = lambda: _Supabase(rec)
    return tools


def test_get_execution_results_scopes_by_team():
    rec = {}
    _tools(rec).get_execution_results({'team_id': 'team-x'})
    assert rec['table'] == 'script_results'
    assert ('team_id', 'team-x') in rec['eq']


def test_update_execution_analysis_scopes_by_team():
    rec = {}
    _tools(rec).update_execution_analysis({
        'script_result_id': 'r1', 'discard': False,
        'classification': 'VALID_PASS', 'explanation': 'ok', 'team_id': 'team-x'})
    assert ('id', 'r1') in rec['eq']
    assert ('team_id', 'team-x') in rec['eq']
    assert rec['update']['checked'] is True
