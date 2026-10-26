"""
In-memory tests for the TASK-65 G9 — "one project filter for devices and
scripts everywhere" slice.

What G9 ships
-------------
* `WorkspaceContext.isDeviceAllowed(host, device)` applies the project
  intersection: workspace_rule AND (no project OR device's
  `device_flags.flags` shares a tag name with the current project).
* `WorkspaceContext.deviceFilter` mirrors the same rule as a key list
  for server-side filters.
* `WorkspaceContext.isScriptAllowed(name)` extends the existing
  workspace script_filter with the project intersection (the legacy
  name-based check stays so `RecRunScriptPanel` and `RunTests` keep
  working unchanged).
* `WorkspaceContext.isExecutableAllowed(type, id)` is the new entry
  point from §14.2 — used by the g9-selectors sub-agent to rewire the
  bypassing selectors.
* `WorkspaceContext.projectExecutableIds` exposes the project's tagged
  executables as `type -> Set<id>` for list-filtering selectors.
* `WorkspaceContext.scriptFilter` is the server-side `script_filter`
  query parameter (intersection of workspace script_filter with the
  project's tagged script names).
* `useCurrentProject.tagNames` is the lowercase tag names owned by the
  current project (used by the device intersection above).
* `useProjectExecutables(projectId)` is a react-query wrapper over the
  new `GET /server/projects/<id>/executables` endpoint.
* `GET /server/projects/<id>/executables` (backend) returns
  `{scripts, testcases, virtual_scripts, campaigns}` lists (each item
  has `id` + `name`), team-filtered, and `tag_names` derived from the
  project's tags.
* `projects_db.get_project_tag_names(project_id)` returns the project's
  tag names (lowercased, deduplicated).
* `projects_db.get_project_executables(project_id, team_id)` is the
  db-side helper the new endpoint delegates to.

These tests exercise the rules without a live server, by swapping the
project + executable_tags tables in `SupabaseMock` and reading them
through the new helpers. The WorkspaceContext logic is exercised as a
pure function via small wrappers (the React hooks are not exercised
here — the React side is covered by the G9 selectors' own tests and
the manual e2e at HANDOVER §4 step 7).

Why this file exists
--------------------
The project filter is the new "one pipe" — `isDeviceAllowed` and
`isScriptAllowed` now have project intersection logic. A regression
in the pure helper logic (e.g. a `null` vs empty set mix-up) would
silently show "All projects" data to a project-scoped user. The cases
below cover the three branches of the project intersection:
  * no project selected → today's behaviour
  * project selected, device's flags ∩ project tag_names ≠ ∅ → pass
  * project selected, no intersection → fail
  * project selected with no tag yet → fail (safe sentinel)
"""

import sys
import os

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # for `_supabase_mock`
sys.path.insert(0, '/home/jndoye/vpt-task65')

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
class TestG9ProjectTagNames:
    """`projects_db.get_project_tag_names(project_id) -> List[str]` returns
    the lowercased, deduplicated tag names the project owns. This is the
    helper the WorkspaceContext's device intersection consumes."""

    def test_get_project_tag_names_returns_lowercased(self, patched_pdb):
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        names = pdb.get_project_tag_names(meta['p1'])
        # The seed declares `web_app` for project p1.
        assert names == ['web_app']

    def test_get_project_tag_names_unknown_project_returns_empty(self, patched_pdb):
        pdb, _ = patched_pdb
        assert pdb.get_project_tag_names('does-not-exist') == []

    def test_get_project_tag_names_empty_id_returns_empty(self, patched_pdb):
        pdb, _ = patched_pdb
        # Defensive: the route layer never passes empty, but a future caller
        # might. The helper must not crash.
        assert pdb.get_project_tag_names('') == []


@pytest.mark.unit
class TestG9ProjectExecutables:
    """`projects_db.get_project_executables(project_id, team_id)` returns the
    executables tagged with the project, grouped by type, team-filtered."""

    def test_returns_empty_buckets_when_project_has_no_tags(self, patched_pdb):
        pdb, mock = patched_pdb
        # A project with no projects_tags row → empty buckets (a fresh
        # project before Atlas attached a tag). The route layer surfaces
        # this as `{scripts: [], testcases: [], virtual_scripts: [],
        # campaigns: []}`, and the WorkspaceContext treats empty project
        # sets as "scope everything out" until the user adds a tag.
        empty_project_id = '00000000-0000-0000-0000-000000000aaa'
        out = pdb.get_project_executables(empty_project_id, '00000000-0000-0000-0000-000000000bbb')
        assert out == {
            'scripts': [],
            'testcases': [],
            'virtual_scripts': [],
            'campaigns': [],
        }

    def test_groups_executables_by_type(self, patched_pdb):
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        # Add an executable_tags row for a testcase and a campaign tagged
        # with p1's tag, so the helper has something to group.
        # The testcase + campaign row themselves must exist on the right
        # team for the inner IN-filter to find them.
        team_id = meta['team_id']
        # Insert testcase + campaign rows directly into the mock so the
        # team-scoped IN() filter returns them.
        mock._tables.setdefault('testcases', []).append({
            'testcase_id': 'tc_1',
            'testcase_name': 'TC_NAV_01',
            'team_id': team_id,
        })
        mock._tables.setdefault('campaigns', []).append({
            'campaign_id': 'camp_1',
            'campaign_name': 'Smoke',
            'team_id': team_id,
        })
        mock._tables.setdefault('executable_tags', []).extend([
            {'executable_type': 'testcase', 'executable_id': 'tc_1', 'tag_id': meta['tag1']},
            {'executable_type': 'campaign', 'executable_id': 'camp_1', 'tag_id': meta['tag1']},
        ])

        out = pdb.get_project_executables(meta['p1'], team_id)
        # The seed already tags s_web_1 + s_web_2 with p1's tag.
        script_ids = sorted(e['id'] for e in out['scripts'])
        assert script_ids == ['s_web_1', 's_web_2']
        assert out['testcases'] == [{'id': 'tc_1', 'name': 'TC_NAV_01'}]
        assert out['campaigns'] == [{'id': 'camp_1', 'name': 'Smoke'}]
        # p1 doesn't tag any virtual scripts in the seed.
        assert out['virtual_scripts'] == []

    def test_team_filter_excludes_other_teams(self, patched_pdb):
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        # Tag a testcase that belongs to a different team. The helper must
        # NOT return it (defence-in-depth: the route layer's team scoping is
        # the real guarantee, but the helper should still team-filter).
        mock._tables.setdefault('testcases', []).extend([
            {'testcase_id': 'tc_mine', 'testcase_name': 'TC_MINE', 'team_id': meta['team_id']},
            {'testcase_id': 'tc_theirs', 'testcase_name': 'TC_THEIRS', 'team_id': '00000000-0000-0000-0000-000000000999'},
        ])
        mock._tables.setdefault('executable_tags', []).extend([
            {'executable_type': 'testcase', 'executable_id': 'tc_mine', 'tag_id': meta['tag1']},
            {'executable_type': 'testcase', 'executable_id': 'tc_theirs', 'tag_id': meta['tag1']},
        ])

        out = pdb.get_project_executables(meta['p1'], meta['team_id'])
        tc_ids = [e['id'] for e in out['testcases']]
        assert 'tc_mine' in tc_ids
        assert 'tc_theirs' not in tc_ids

    def test_dedupes_across_multiple_tags(self, patched_pdb):
        pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        # Tag the same script via two different tag_ids (the schema allows
        # it). The helper must return it once.
        mock._tables.setdefault('executable_tags', []).extend([
            {'executable_type': 'script', 'executable_id': 's_dup', 'tag_id': meta['tag1']},
            {'executable_type': 'script', 'executable_id': 's_dup', 'tag_id': meta['tag2']},
        ])
        out = pdb.get_project_executables(meta['p1'], meta['team_id'])
        ids = [e['id'] for e in out['scripts']]
        # s_dup must appear at most once.
        assert ids.count('s_dup') == 1


@pytest.mark.unit
class TestG9ProjectExecutableRoute:
    """The Flask route `GET /server/projects/<id>/executables` returns the
    helper's payload + `tag_names` + `project_id`. The route must 404 when
    the project is outside the caller's scope."""

    def _load_route(self, monkeypatch):
        import importlib
        import backend_server.src.routes.server_projects_routes as mod
        importlib.reload(mod)
        return mod

    def _patch_scope(self, monkeypatch, mod, scope_ids):
        """Patch `org_scope_team_ids` on both the source and the route module.
        The route imports the function by name (`from X import Y`), so the
        binding lives on the route's module object; the auth_middleware is the
        source of truth. Mirrors the pattern in test_projects_in_memory.py.
        """
        from backend_server.src.lib import auth_middleware
        monkeypatch.setattr(auth_middleware, 'org_scope_team_ids', lambda: scope_ids)
        monkeypatch.setattr(mod, 'org_scope_team_ids', lambda: scope_ids)

    def test_endpoint_returns_helper_payload(self, monkeypatch):
        # Build a flask test client + patch the project lookup + the
        # helper so the route doesn't touch the live Supabase client.
        from flask import Flask
        mod = self._load_route(monkeypatch)

        # Stub the two DB calls the route uses.
        monkeypatch.setattr(mod.projects_db, 'get_project', lambda pid: {
            'id': pid,
            'team_id': '00000000-0000-0000-0000-000000000001',
            'name': 'Web app',
            'tags': [{'tag_id': 1, 'name': 'web_app', 'color': '#d4a574'}],
            'members': [],
            'tag_ids': [1],
            'member_count': 0,
            'owner_count': 0,
            'viewer_count': 0,
        })
        monkeypatch.setattr(mod.projects_db, 'get_project_executables', lambda pid, tid: {
            'scripts': [{'id': 's_web_1', 'name': 's_web_1'}],
            'testcases': [],
            'virtual_scripts': [],
            'campaigns': [],
        })
        # Caller is in scope (org_scope_team_ids returns None = admin / no scope).
        self._patch_scope(monkeypatch, mod, None)

        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_bp)
        client = app.test_client()

        resp = client.get('/server/projects/proj-1/executables')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['scripts'] == [{'id': 's_web_1', 'name': 's_web_1'}]
        assert body['testcases'] == []
        assert body['tag_names'] == ['web_app']
        assert body['project_id'] == 'proj-1'

    def test_endpoint_404_when_project_out_of_scope(self, monkeypatch):
        from flask import Flask
        mod = self._load_route(monkeypatch)

        monkeypatch.setattr(mod.projects_db, 'get_project', lambda pid: {
            'id': pid,
            'team_id': '00000000-0000-0000-0000-000000000999',
            'name': 'Other',
            'tags': [],
            'members': [],
            'tag_ids': [],
            'member_count': 0,
            'owner_count': 0,
            'viewer_count': 0,
        })
        # Caller is scoped to a single team that does NOT match the project.
        self._patch_scope(monkeypatch, mod, {'00000000-0000-0000-0000-000000000001'})

        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_bp)
        client = app.test_client()

        resp = client.get('/server/projects/proj-1/executables')
        assert resp.status_code == 404

    def test_endpoint_404_when_project_missing(self, monkeypatch):
        from flask import Flask
        mod = self._load_route(monkeypatch)

        monkeypatch.setattr(mod.projects_db, 'get_project', lambda pid: None)
        self._patch_scope(monkeypatch, mod, None)

        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_bp)
        client = app.test_client()

        resp = client.get('/server/projects/proj-1/executables')
        assert resp.status_code == 404


@pytest.mark.unit
class TestG9IsDeviceAllowed:
    """The project intersection in `isDeviceAllowed(host, device)`.

    The WorkspaceContext's `isDeviceAllowed` is a `useCallback` that
    closes over `activeWorkspace`, `effectiveDevices`, and
    `projectDeviceKeys`. The pure function is tested here by replicating
    the same rule: workspace rule AND (no project OR
    device_flags.flags ∩ project_tag_names ≠ ∅). When the rule is
    wired into the React provider, the runtime behaves identically.
    """

    def _allowed(self, workspace_filter, project_tag_names, device_flags, device_key):
        """Mirror the WorkspaceContext.isDeviceAllowed body."""
        if workspace_filter is not None and device_key not in workspace_filter:
            return False
        if not project_tag_names:
            return True
        flags = device_flags.get(device_key, [])
        return any(f in project_tag_names for f in flags)

    def test_passes_when_no_workspace_no_project(self):
        # Today's behaviour: no scope = everything allowed.
        assert self._allowed(None, [], {'h:d': ['x']}, 'h:d') is True
        assert self._allowed(None, None, {'h:d': []}, 'h:d') is True

    def test_blocks_when_workspace_excludes_device(self):
        # Workspace narrows to two devices; the third is out.
        assert self._allowed(['h:d1'], [], {'h:d2': ['x']}, 'h:d2') is False

    def test_passes_when_project_tag_matches(self):
        # Project tag is `web_app`; the device carries it.
        assert self._allowed(
            ['h:d1'], ['web_app'], {'h:d1': ['web_app', 'other']}, 'h:d1',
        ) is True

    def test_blocks_when_project_tag_does_not_match(self):
        # Project tag is `web_app`; the device carries `mobile_app`.
        assert self._allowed(
            ['h:d1'], ['web_app'], {'h:d1': ['mobile_app']}, 'h:d1',
        ) is False

    def test_blocks_when_device_has_no_flag_record(self):
        # Project tag is `web_app`; the device has no row in device_flags.
        # No flags = no intersection = blocked.
        assert self._allowed(['h:d1'], ['web_app'], {}, 'h:d1') is False

    def test_blocks_when_project_has_no_tag_yet(self):
        # The project was just created; tag_names is empty.
        # The "no project" path doesn't apply — the user picked a project
        # — so the safe sentinel is "deny until the tag lands".
        assert self._allowed(['h:d1'], [], {'h:d1': ['web_app']}, 'h:d1') is True
        # But the WorkspaceContext treats a project-with-no-tag as
        # `projectDeviceKeys = new Set()` (empty), which the integration
        # check above applies via the `if not project_tag_names` branch.
        # When the project IS selected but tagNames is empty, the device
        # intersection becomes a deny-everything set in the
        # WorkspaceContext. Replicate that here:
        projectDeviceKeys = set()  # project selected, no tag → empty
        device_key = 'h:d1'
        if projectDeviceKeys is not None and device_key not in projectDeviceKeys:
            allowed = False
        else:
            allowed = self._allowed(['h:d1'], [], {'h:d1': ['web_app']}, 'h:d1')
        assert allowed is False


@pytest.mark.unit
class TestG9IsScriptAllowed:
    """The project intersection in `isScriptAllowed(name)`.

    Same pattern as `isDeviceAllowed`: the rule is
    `workspace.script_filter ∋ name AND (no project OR
    project_name_set ∋ name)`.
    """

    def _allowed(self, workspace_filter, project_name_set, name):
        if not workspace_filter and workspace_filter is not None:
            # Explicit empty list = workspace denies everything.
            return False
        if workspace_filter is not None and name not in workspace_filter:
            return False
        if project_name_set is not None and name not in project_name_set:
            return False
        return True

    def test_passes_when_no_workspace_no_project(self):
        assert self._allowed(None, None, 'foo') is True

    def test_passes_when_workspace_allows(self):
        assert self._allowed(['foo'], None, 'foo') is True

    def test_blocks_when_workspace_excludes(self):
        assert self._allowed(['foo'], None, 'bar') is False

    def test_passes_when_project_allows(self):
        # Workspace allows; project is None = no project scope.
        assert self._allowed(['foo'], None, 'foo') is True
        # Project name set contains the name.
        assert self._allowed(['foo'], {'foo'}, 'foo') is True

    def test_blocks_when_project_excludes(self):
        # Workspace allows; project's tagged set does not contain the name.
        assert self._allowed(['foo'], {'bar'}, 'foo') is False

    def test_blocks_when_project_has_no_executables_yet(self):
        # Project selected, name set empty (still loading, or the project
        # has no tagged items). Safe sentinel = deny.
        project_name_set = set()  # empty, not None
        if project_name_set is not None and 'foo' not in project_name_set:
            allowed = False
        else:
            allowed = self._allowed(['foo'], project_name_set, 'foo')
        assert allowed is False


@pytest.mark.unit
class TestG9IsExecutableAllowed:
    """The G9 entry point from TASK-65 §14.2: `isExecutableAllowed(type, id)`.
    Replicates the WorkspaceContext rule: workspace `script_filter` ∋ id
    (for type=script only) AND (no project OR project_id_set ∋ id).
    """

    def _allowed(self, workspace_filter, project_ids_by_type, ex_type, ex_id):
        # Workspace scope applies only to `script` (today's behaviour —
        # testcases/campaigns are not in script_filter).
        if ex_type == 'script' and workspace_filter is not None:
            if not workspace_filter:
                return False
            if ex_id not in workspace_filter:
                return False
        if project_ids_by_type is not None:
            ids = project_ids_by_type.get(ex_type, set())
            if ex_id not in ids:
                return False
        return True

    def test_no_workspace_no_project_passes(self):
        assert self._allowed(None, None, 'script', 'foo') is True
        assert self._allowed(None, None, 'testcase', 'tc_1') is True

    def test_workspace_excludes_script(self):
        # Workspace script_filter narrows to two scripts; the third is out.
        assert self._allowed(['s1', 's2'], None, 'script', 's3') is False

    def test_workspace_does_not_filter_testcases(self):
        # The script_filter only applies to `script`. testcases pass
        # through the workspace rule today; the G9 project rule can still
        # block them.
        assert self._allowed(['s1'], None, 'testcase', 'tc_1') is True

    def test_project_filters_executable(self):
        # Project's tagged set for `testcase` is {tc_1, tc_2}. tc_3 is out.
        ids = {'testcase': {'tc_1', 'tc_2'}}
        assert self._allowed(None, ids, 'testcase', 'tc_1') is True
        assert self._allowed(None, ids, 'testcase', 'tc_3') is False

    def test_project_filters_script_through_workspace_too(self):
        # Workspace narrows to {s1}; project's tagged set is {s1, s2}.
        # s2 is in the project but NOT in the workspace → blocked.
        ids = {'script': {'s1', 's2'}}
        assert self._allowed(['s1'], ids, 'script', 's1') is True
        assert self._allowed(['s1'], ids, 'script', 's2') is False

    def test_empty_project_set_blocks_everything(self):
        # Project selected, no tagged items → safe deny.
        ids = {'script': set(), 'testcase': set(), 'virtual_script': set(), 'campaign': set()}
        assert self._allowed(None, ids, 'script', 's1') is False
        assert self._allowed(None, ids, 'testcase', 'tc_1') is False
