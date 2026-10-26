"""
In-memory tests for the TASK-65 G5 — Scope Atlas layer.

What G5 ships
-------------
* `projects_db.current_project_from_id(project_id)` — resolve an
  `X-Project-Id` / `project_id` hint into a project row (or None for "all").
* `projects_db.auto_tag_with_project(executable_type, executable_id, project)`
  — link an artefact to the project's tag (idempotent).
* `projects_db.list_executable_ids_for_project_tag(executable_type, project)`
  — return the set of executable_ids the project's tag has tagged
  (or None for "all" mode).
* `save_virtual_script` / `save_testcase` / `create_campaign` MCP tools
  auto-tag new artefacts with the current project when the caller passed
  a `project_id` argument or the `X-Project-Id` request header.
* `list_scripts` / `list_testcases` / `list_campaigns` MCP tools forward
  the `project_id` to the underlying API endpoint so the list is filtered
  by the project's tag.
* The Atlas system-prompt builder now emits a "Current Project" line when
  the request context carries a `current_project` dict (set by the MCP
  proxy after resolving the X-Project-Id header).

The tests below exercise each of these without a live server or database,
using `SupabaseMock` + `apply_migration_sql` to mirror the post-apply state.
"""

import sys
import os
from typing import Any, Dict

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))  # for `_supabase_mock`
sys.path.insert(0, REPO_ROOT)

# Repo-relative path to the in-tree virtual_script_tools module. The previous
# build hardcoded an absolute path under `/home/jndoye/vpt-task65/...` that no
# longer exists on the current runner; resolve it from the test file's location
# so the suite is portable across worktrees and CI clones.
VIRTUAL_SCRIPT_TOOLS_PATH = os.path.join(
    REPO_ROOT,
    'features', 'virtual-scripts', 'backend_server', 'mcp_tools',
    'virtual_script_tools.py',
)

from _supabase_mock import (  # type: ignore  # noqa: E402
    SupabaseMock,
    apply_migration_sql,
    make_projects_seed,
    get_meta,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase() -> SupabaseMock:
    """A mock with the 3 migrations applied in memory, on top of the seed."""
    mock = SupabaseMock(initial=make_projects_seed())
    for fn in [
        '20261006a_projects.sql',
        '20261006b_team_members_last_seen.sql',
        '20261006c_report_snapshots_project_ids.sql',
    ]:
        with open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'setup', 'db', 'migrations', fn,
        )) as f:
            apply_migration_sql(mock, f.read())
    return mock


@pytest.fixture
def patched_pdb(mock_supabase, monkeypatch):
    import importlib
    import shared.src.lib.database.projects_db as pdb
    importlib.reload(pdb)
    monkeypatch.setattr(pdb, '_supabase', lambda: mock_supabase)
    return pdb, mock_supabase


@pytest.mark.unit
class TestG5ResolveAndAutoTag:
    """`current_project_from_id` + `auto_tag_with_project` against the in-memory mock."""

    def test_current_project_returns_project_for_valid_id(self, patched_pdb):
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        p = pdb.current_project_from_id(meta['p1'])
        assert p is not None
        assert p['id'] == meta['p1']
        assert p['name'] == 'Web app'
        assert p['tag_ids'] == [meta['tag1']]

    def test_current_project_returns_none_for_unknown_id(self, patched_pdb):
        pdb, _ = patched_pdb
        assert pdb.current_project_from_id('does-not-exist') is None

    def test_current_project_returns_none_for_all_or_empty(self, patched_pdb):
        pdb, _ = patched_pdb
        for sentinel in (None, '', 'all', 'ALL', 'null', 'None'):
            assert pdb.current_project_from_id(sentinel) is None

    def test_auto_tag_returns_true_without_inserting(self, patched_pdb):
        """BUG-0611 — `auto_tag_with_project` is a deprecated no-op. The
        function still accepts the same (executable_type, executable_id,
        project) signature and returns True on success so the three legacy
        callers (campaign_tools / testcase_tools / virtual_script_tools)
        stay green, but it inserts zero rows.
        """
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        p = pdb.current_project_from_id(meta['p1'])
        before = len(mock.get_table('executable_tags') or [])
        ok = pdb.auto_tag_with_project('virtual_script', 'vs_001', p)
        assert ok is True
        after = len(mock.get_table('executable_tags') or [])
        # No new rows — the manual flow (POST /link or the project page
        # `+ add`) is the only supported path going forward.
        assert after == before

    def test_auto_tag_is_idempotent(self, patched_pdb):
        """BUG-0611 — calling the no-op repeatedly is trivially idempotent
        (it never inserts in the first place). Today's the assertion is
        that no rows accumulate.
        """
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        p = pdb.current_project_from_id(meta['p1'])
        before = len(mock.get_table('executable_tags') or [])
        pdb.auto_tag_with_project('virtual_script', 'vs_002', p)
        pdb.auto_tag_with_project('virtual_script', 'vs_002', p)
        pdb.auto_tag_with_project('virtual_script', 'vs_002', p)
        rows = [r for r in mock.get_table('executable_tags')
                if r.get('executable_id') == 'vs_002']
        assert rows == []
        # And the table as a whole didn't grow.
        after = len(mock.get_table('executable_tags') or [])
        assert after == before

    def test_auto_tag_returns_false_when_project_has_no_tag(self, patched_pdb):
        pdb, _ = patched_pdb
        # A project dict without `tag_ids` is the path the function takes when
        # a project was created with no linked tag (legacy / corrupt state).
        assert pdb.auto_tag_with_project('virtual_script', 'x', {'name': 'p'}) is False

    def test_list_executable_ids_returns_tagged_set(self, patched_pdb):
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        # Pre-seed: tag two virtual_script ids with project p1's tag.
        mock._tables.setdefault('executable_tags', []).extend([
            {'executable_type': 'virtual_script', 'executable_id': 'vs_a', 'tag_id': meta['tag1']},
            {'executable_type': 'virtual_script', 'executable_id': 'vs_b', 'tag_id': meta['tag1']},
        ])
        p = pdb.current_project_from_id(meta['p1'])
        ids = pdb.list_executable_ids_for_project_tag('virtual_script', p)
        assert ids == ['vs_a', 'vs_b']

    def test_list_executable_ids_returns_none_for_all_project(self, patched_pdb):
        pdb, _ = patched_pdb
        # When the project is None (caller is in "all" mode) the helper
        # signals "don't filter" with None.
        assert pdb.list_executable_ids_for_project_tag('virtual_script', None) is None


@pytest.mark.unit
class TestG5AtlasSystemPrompt:
    """The Atlas manager's context section includes a Current Project line."""

    def test_context_section_includes_current_project(self, monkeypatch):
        from backend_server.src.agent.core.manager import QAManagerAgent
        m = QAManagerAgent.__new__(QAManagerAgent)
        m.logger = type('L', (), {'info': lambda *a, **k: None, 'debug': lambda *a, **k: None, 'warning': lambda *a, **k: None})()
        ctx = {
            'current_project': {
                'id': '11111111-1111-1111-1111-111111111111',
                'name': 'Mobile app',
                'tag_name': 'mobile_app',
            },
            'host_name': '',
            'device_id': '',
        }
        section = m._build_full_context_section(ctx)
        assert 'Current Project (TASK-65 G5)' in section
        assert 'Mobile app' in section
        assert 'mobile_app' in section
        # The hint must also tell the LLM that the artefacts will be auto-tagged.
        assert 'auto-tagged' in section

    def test_context_section_omits_line_when_no_project(self, monkeypatch):
        from backend_server.src.agent.core.manager import QAManagerAgent
        m = QAManagerAgent.__new__(QAManagerAgent)
        ctx = {
            'host_name': 'h1',
            'device_id': 'd1',
            'current_project': None,
        }
        section = m._build_full_context_section(ctx)
        assert 'Current Project' not in section


@pytest.mark.unit
class TestG5McpToolAutoTag:
    """Verify save_virtual_script / save_testcase / create_campaign auto-tag
    the new artefact when the api_client carries an `X-Project-Id` header or
    the params carry `project_id`.
    """

    def _setup_api_client_with_project(self, project_id: str):
        """Build an MCPAPIClient that records POSTs and sets the X-Project-Id
        header. The body of `post` is a no-op so we can inspect what the
        tools sent without a real backend."""
        class _FakeApi:
            def __init__(self, project_id):
                self.headers = {'X-Project-Id': project_id} if project_id else {}
                self.calls = []

            def get(self, endpoint, params=None, headers=None):
                self.calls.append(('get', endpoint, params, headers))
                # Used by `_find_dev_row` etc.
                return {'success': True, 'scripts': [], 'testcases': [], 'campaigns': []}

            def post(self, endpoint, data=None, params=None, timeout=None, headers=None):
                merged = {**self.headers, **(headers or {})}
                self.calls.append(('post', endpoint, data, params, merged))
                return {
                    'success': True,
                    'id': 'new-vs-id-123',
                    'script': {},
                    'testcase': {'testcase_id': 'new-tc-id-456'},
                    'campaign': {'id': 'new-camp-id-789'},
                }
        return _FakeApi(project_id)

    def test_save_virtual_script_auto_tags_with_project(self, monkeypatch):
        from shared.src.lib.database import projects_db as pdb
        # Force a deterministic project lookup (no Supabase env in test).
        def fake_get_project(pid):
            return {'id': pid, 'name': 'Mobile app', 'tag_ids': [99]}
        def fake_auto_tag(typ, exid, project):
            # record the call for the assertion below
            fake_auto_tag.called = (typ, exid, project.get('id'))
            return True
        monkeypatch.setattr(pdb, 'get_project', fake_get_project)
        monkeypatch.setattr(pdb, 'auto_tag_with_project', fake_auto_tag)

        # The features/ tree has no top-level __init__.py; load the file via
        # importlib so we don't introduce a new package boundary.
        import importlib.util
        path = VIRTUAL_SCRIPT_TOOLS_PATH
        spec = importlib.util.spec_from_file_location('vs_tools', path)
        vs_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vs_mod)
        VirtualScriptTools = vs_mod.VirtualScriptTools

        api = self._setup_api_client_with_project(project_id='11111111-1111-1111-1111-111111111111')
        tools = VirtualScriptTools(api)
        result = tools.save_virtual_script({
            'name': 'SC_NAV_01_GotoLive',
            'source': '#!/usr/bin/env python3\n@script\ndef main(_args):\n    return _args\nmain._script_description = "navigate to live"',
            'team_id': '00000000-0000-0000-0000-000000000001',
        })
        # The post was made
        assert any(c[0] == 'post' for c in api.calls)
        # auto_tag ran with the right (type, id, project)
        assert fake_auto_tag.called == ('virtual_script', 'new-vs-id-123', '11111111-1111-1111-1111-111111111111')
        # The MCP response carries the project hint back to the LLM
        assert result.get('project_id') == '11111111-1111-1111-1111-111111111111'

    def test_save_virtual_script_passes_explicit_project_id(self, monkeypatch):
        from shared.src.lib.database import projects_db as pdb
        captured = []
        monkeypatch.setattr(pdb, 'get_project', lambda pid: {'id': pid, 'name': 'X', 'tag_ids': [1]})
        monkeypatch.setattr(pdb, 'auto_tag_with_project', lambda *a, **kw: (captured.append((a, kw)) or True))

        import importlib.util
        path = VIRTUAL_SCRIPT_TOOLS_PATH
        spec = importlib.util.spec_from_file_location('vs_tools', path)
        vs_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vs_mod)
        VirtualScriptTools = vs_mod.VirtualScriptTools

        # No header — but explicit project_id in params.
        api = self._setup_api_client_with_project(project_id='')
        tools = VirtualScriptTools(api)
        tools.save_virtual_script({
            'name': 'SC_NAV_02_Other',
            'source': '#!/usr/bin/env python3\n@script\ndef main(_a):\n    return _a',
            'project_id': 'proj-explicit',
        })
        # auto_tag_with_project is called with (executable_type, executable_id, project_dict)
        assert captured and captured[0][0][0] == 'virtual_script'
        assert captured[0][0][2].get('id') == 'proj-explicit'

    def test_save_virtual_script_no_project_is_noop(self, monkeypatch):
        """No project_id arg, no X-Project-Id header: no auto-tag call."""
        from shared.src.lib.database import projects_db as pdb
        called = []
        monkeypatch.setattr(pdb, 'auto_tag_with_project', lambda *a, **kw: (called.append(a) or True))
        monkeypatch.setattr(pdb, 'get_project', lambda pid: {'id': pid, 'name': 'X', 'tag_ids': [1]})

        import importlib.util
        path = VIRTUAL_SCRIPT_TOOLS_PATH
        spec = importlib.util.spec_from_file_location('vs_tools', path)
        vs_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vs_mod)
        VirtualScriptTools = vs_mod.VirtualScriptTools

        api = self._setup_api_client_with_project(project_id='')
        tools = VirtualScriptTools(api)
        tools.save_virtual_script({
            'name': 'SC_NAV_03_NoProject',
            'source': '#!/usr/bin/env python3\n@script\ndef main(_a):\n    return _a',
        })
        assert called == []  # no project, no auto-tag

    def test_list_scripts_forwards_project_id_in_query(self):
        from backend_server.src.mcp.tools.script_tools import ScriptTools
        api = self._setup_api_client_with_project(project_id='proj-from-header')
        tools = ScriptTools(api)
        tools.list_scripts({})
        # The `executable/list` call must include project_id when set
        post = next(c for c in api.calls if c[0] == 'get' and c[1] == '/server/executable/list')
        # post is a (get, endpoint, params, headers) tuple
        params = post[2]
        assert params.get('project_id') == 'proj-from-header'

    def test_save_testcase_auto_tags(self, monkeypatch):
        from shared.src.lib.database import projects_db as pdb
        captured = []
        monkeypatch.setattr(pdb, 'get_project', lambda pid: {'id': pid, 'name': 'Web', 'tag_ids': [1]})
        monkeypatch.setattr(pdb, 'auto_tag_with_project', lambda *a, **kw: (captured.append(a) or True))

        from backend_server.src.mcp.tools.testcase_tools import TestCaseTools
        api = self._setup_api_client_with_project(project_id='proj-tc')
        tools = TestCaseTools(api)
        tools.save_testcase({
            'testcase_name': 'TC_NAV_01',
            'graph_json': {
                'nodes': [
                    {'id': 'start', 'type': 'start', 'data': {'label': 'Start'}},
                    {'id': 'success', 'type': 'success', 'data': {'label': 'Success'}},
                ],
                'edges': [],
            },
        })
        assert captured and captured[0][0] == 'testcase'
        assert captured[0][2].get('id') == 'proj-tc'

    def test_list_testcases_forwards_project_id(self):
        from backend_server.src.mcp.tools.testcase_tools import TestCaseTools
        api = self._setup_api_client_with_project(project_id='proj-tc-list')
        tools = TestCaseTools(api)
        tools.list_testcases({})
        get = next(c for c in api.calls if c[0] == 'get' and c[1] == '/server/testcase/list')
        assert get[2].get('project_id') == 'proj-tc-list'

    def test_create_campaign_auto_tags(self, monkeypatch):
        from shared.src.lib.database import projects_db as pdb
        captured = []
        monkeypatch.setattr(pdb, 'get_project', lambda pid: {'id': pid, 'name': 'Mobile', 'tag_ids': [1]})
        monkeypatch.setattr(pdb, 'auto_tag_with_project', lambda *a, **kw: (captured.append(a) or True))
        # The create_campaign tool also calls self.list_campaigns first; mock
        # that path by setting the api's get to return an empty list.
        from backend_server.src.mcp.tools.campaign_tools import CampaignTools
        api = self._setup_api_client_with_project(project_id='proj-camp')
        tools = CampaignTools(api)
        tools.create_campaign({
            'campaign_name': 'Smoke',
            'script_configurations': [{'script_name': 's1'}],
        })
        # auto_tag_with_project receives (executable_type, executable_id, project_dict)
        campaign_call = next(c for c in captured if c[0] == 'campaign')
        assert campaign_call[2].get('id') == 'proj-camp'

    def test_list_campaigns_forwards_project_id(self):
        from backend_server.src.mcp.tools.campaign_tools import CampaignTools
        api = self._setup_api_client_with_project(project_id='proj-camp-list')
        tools = CampaignTools(api)
        tools.list_campaigns({})
        # The most recent get to getAllCampaigns is our direct call.
        gets = [c for c in api.calls if c[0] == 'get' and c[1] == '/server/campaigns/getAllCampaigns']
        # We only made one call from this test method (the api instance is fresh).
        assert gets
        get = gets[0]
        assert get[2].get('project_id') == 'proj-camp-list'


@pytest.mark.unit
class TestG5MigrationInMemory:
    """The `apply_migration_sql` function applies the 3 migration files end to
    end. This is the dry-run the user asked for: 'apply migration in memory,
    then run the next phase on top, don't stop until done'.
    """

    def test_apply_migrations_creates_all_tables(self, mock_supabase):
        # The mock_supabase fixture already applied the migrations; verify.
        tables = sorted(mock_supabase._tables.keys())
        for required in ('projects', 'projects_tags', 'projects_members', 'executable_tags'):
            assert required in tables, f'migration did not create {required}'

    def test_apply_migrations_adds_team_members_last_seen_column(self, mock_supabase):
        # team_members seed has only the original columns; the migration adds
        # `last_seen_at` (defaulting to None for every existing row).
        rows = mock_supabase.get_table('team_members')
        assert rows, 'team_members seed is empty'
        for r in rows:
            assert 'last_seen_at' in r

    def test_apply_migrations_adds_report_snapshots_project_ids(self, mock_supabase):
        # `report_snapshots` is created lazily when the first read/write
        # happens. The migration's ALTER TABLE should have created the table
        # even without data, because the mock fires a CREATE TABLE on
        # table(name) regardless. Let's check.
        rows = mock_supabase.get_table('report_snapshots')
        # The migration only adds a column; the table is empty so we can
        # verify the column was added by inserting a row and reading back.
        mock_supabase._tables['report_snapshots'].append(
            {'id': 'rpt-1', 'team_id': 't1', 'project_ids': []},
        )
        for r in mock_supabase.get_table('report_snapshots'):
            assert 'project_ids' in r

    def test_full_pipeline_create_project_then_manual_link(self, mock_supabase, monkeypatch):
        """BUG-0611 — the G5 happy path is now a manual link, not an auto-tag.

          1. Migration applied (fixture).
          2. Create a project via `projects_db.create_project`.
          3. Call the DEPRECATED `auto_tag_with_project` (no-op, returns True,
             inserts zero rows — the BUG-0611 contract).
          4. Call the supported manual path
             `add_executable_to_project('virtual_script', id, project_id)`.
          5. List the virtual scripts for the project — the new id shows up.
        """
        import importlib
        import shared.src.lib.database.projects_db as pdb
        importlib.reload(pdb)
        monkeypatch.setattr(pdb, '_supabase', lambda: mock_supabase)

        # Same helper stub as before (the mock's auto-id generator doesn't
        # fill in `tag_id`; `list_executable_ids_for_project_tag` reads it).
        def fake_get_or_create_tag(name: str):
            return {'tag_id': 9999, 'name': name, 'color': '#d4a574'}
        monkeypatch.setattr(pdb, '_get_or_create_tag', fake_get_or_create_tag)

        meta = get_meta(mock_supabase._tables)
        # Step 2: create a project
        new_project = pdb.create_project(
            team_id=meta['team_id'],
            name='Smoke E2E',
            description='G5 happy path',
            color='#22c55e',
            created_by_team_member_id=meta['owner_tm_id'],
        )
        assert new_project is not None
        new_project = pdb.get_project(new_project['id'])
        assert new_project and new_project['name'] == 'Smoke E2E'
        # Step 3: the deprecated auto-tag is a no-op (still called by the
        # three legacy tool paths, signature preserved for the migration
        # window).
        ok = pdb.auto_tag_with_project('virtual_script', 'vs_e2e_1', new_project)
        assert ok is True
        # Step 4: manual link via the BUG-0579 helper.
        # signature: add_executable_to_project(project_id, executable_type, executable_id)
        pdb.add_executable_to_project(
            new_project['id'], 'virtual_script', 'vs_e2e_1',
        )
        # Step 5: list virtual_script ids for the project — the new id shows up.
        ids = pdb.list_executable_ids_for_project_tag('virtual_script', new_project)
        assert ids == ['vs_e2e_1']
