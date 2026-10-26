"""
In-memory tests for BUG-0578 — the in-scope + manual linking surface.

Covers:
  * `projects_db.list_in_scope_devices`      (grouped by host, run/pass per device)
  * `projects_db.list_in_scope_executables`  (scripts/testcases/virtuals as peers)
  * `projects_db.list_in_scope_campaigns`    (separate list, run/pass per campaign)
  * `projects_db.add_executable_to_project`  (idempotent)
  * `projects_db.remove_executable_from_project`
  * `projects_db.get_or_create_tag_by_name`  (idempotent)
  * `projects_db.add_user_tag_to_project`    (with `is_scope=false`)
  * `projects_db.remove_user_tag_from_project` (refuses to drop scope tag)
  * GET  /server/projects/<id>/in-scope       (the in-scope aggregator)
  * POST /server/projects/<id>/link           (admin/owner gate + idempotency)
  * DELETE /server/projects/<id>/link         (admin/owner gate + idempotency)
  * POST /server/projects/<id>/tags/names     (admin/owner gate + scope protection)
  * DELETE /server/projects/<id>/tags/names/<name>  (admin/owner gate + scope protection)

Pattern: same as `test_projects_g6_audit_in_memory.py` / `test_projects_g9_scope_in_memory.py`
— `_supabase_mock.SupabaseMock` for the DB, `monkeypatch` to bind the
service-role factory, and a per-test Flask `app.test_client()` for the
HTTP layer.
"""

from __future__ import annotations

import os
import sys

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # for `tests._supabase_mock`


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
class _Req:
    def __init__(self, user_id: str | None = None, user_role: str | None = None):
        self.user_id = user_id
        self.user_role = user_role


def _make_in_scope_seed():
    """Build a fresh in-memory state for BUG-0578 tests.

    Layout:
        * project `p1` owned by `owner_tm_id`, scope tag = `qa-test`.
        * user tag `nightly` linked to `p1` as `is_scope=false`.
        * devices (host=pi4) with flags carrying `qa-test`.
        * executables: 2 scripts, 1 testcase, 1 virtual, 1 campaign.
        * 1 device in scope, 1 device OUT of scope (its flag doesn't match).
    """
    import uuid
    from _supabase_mock import SupabaseMock

    team_id = str(uuid.uuid4())
    owner_tm_id = str(uuid.uuid4())
    p1 = str(uuid.uuid4())
    scope_tag_id = 100
    user_tag_id = 101

    seed = {
        'projects': [{
            'id': p1, 'team_id': team_id, 'name': 'QA — Nightly',
            'description': 'nightly smoke', 'color': '#d4a574',
            'created_by': owner_tm_id,
            'created_at': '2026-09-01T00:00:00+00:00',
        }],
        'projects_tags': [
            # scope tag (is_scope=true is the convention; mock doesn't filter
            # on it, the in-scope helper just reads both rows for tag_names).
            {'project_id': p1, 'tag_id': scope_tag_id, 'is_scope': True,
             'tags': {'tag_id': scope_tag_id, 'name': 'qa-test', 'color': '#d4a574'}},
            {'project_id': p1, 'tag_id': user_tag_id, 'is_scope': False,
             'tags': {'tag_id': user_tag_id, 'name': 'nightly', 'color': '#22c55e'}},
        ],
        'projects_members': [{
            'project_id': p1, 'team_member_id': owner_tm_id,
            'role': 'owner', 'created_at': '2026-09-01T00:00:00+00:00',
        }],
        'team_members': [{
            'id': owner_tm_id, 'user_id': 'user-1', 'team_id': team_id,
            'profile': {'id': 'user-1', 'display_name': 'Owner', 'email': 'o@example.com'},
        }],
        'tags': [
            {'tag_id': scope_tag_id, 'name': 'qa-test', 'color': '#d4a574'},
            {'tag_id': user_tag_id,  'name': 'nightly', 'color': '#22c55e'},
        ],
        'device_flags': [
            {'host_name': 'pi4', 'device_id': 'firetv-01', 'device_name': 'Fire TV 1',
             'flags': ['qa-test', 'fire_tv']},
            {'host_name': 'pi4', 'device_id': 'firetv-02', 'device_name': 'Fire TV 2',
             'flags': ['qa-test']},
            {'host_name': 'mf1', 'device_id': 'android-tv-01', 'device_name': 'Android TV 1',
             'flags': ['mobile_app']},
        ],
        'executable_tags': [
            {'executable_type': 'script',          'executable_id': 'login.test.js', 'tag_id': scope_tag_id},
            {'executable_type': 'script',          'executable_id': 'checkout.py',   'tag_id': scope_tag_id},
            {'executable_type': 'testcase',        'executable_id': 'tc-online',     'tag_id': scope_tag_id},
            {'executable_type': 'virtual_script',  'executable_id': 'vs-smoke',      'tag_id': scope_tag_id},
            {'executable_type': 'campaign',        'executable_id': 'cmp-nightly',   'tag_id': scope_tag_id},
        ],
        'testcases': [{
            'testcase_id': 'tc-online', 'testcase_name': 'Device online', 'team_id': team_id,
        }],
        'virtual_scripts': [{
            'id': 'vs-smoke', 'name': 'Smoke HLS', 'team_id': team_id,
        }],
        'campaigns': [{
            'campaign_id': 'cmp-nightly', 'campaign_name': 'Nightly',
            'schedule': 'every day at 02:00', 'team_id': team_id,
        }],
        'script_results': [
            # 5 pass + 1 fail for login.test.js on pi4/firetv-01
            {'team_id': team_id, 'script_name': 'login.test.js', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': True,  'started_at': '2026-10-15T10:00:00+00:00'},
            {'team_id': team_id, 'script_name': 'login.test.js', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': True,  'started_at': '2026-10-15T10:05:00+00:00'},
            {'team_id': team_id, 'script_name': 'login.test.js', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': True,  'started_at': '2026-10-15T10:10:00+00:00'},
            {'team_id': team_id, 'script_name': 'login.test.js', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': True,  'started_at': '2026-10-15T10:15:00+00:00'},
            {'team_id': team_id, 'script_name': 'login.test.js', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': True,  'started_at': '2026-10-15T10:20:00+00:00'},
            {'team_id': team_id, 'script_name': 'login.test.js', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': False, 'started_at': '2026-10-15T10:25:00+00:00'},
            # 2 pass for checkout.py
            {'team_id': team_id, 'script_name': 'checkout.py', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': True, 'started_at': '2026-10-15T11:00:00+00:00'},
            {'team_id': team_id, 'script_name': 'checkout.py', 'host_name': 'pi4',
             'device_name': 'Fire TV 1', 'success': True, 'started_at': '2026-10-15T11:05:00+00:00'},
            # virtual script run
            {'team_id': team_id, 'script_name': None, 'virtual_script_id': 'vs-smoke',
             'host_name': 'pi4', 'device_name': 'Fire TV 1', 'success': True,
             'started_at': '2026-10-15T12:00:00+00:00'},
            # 1 pass for login.test.js on pi4/firetv-02
            {'team_id': team_id, 'script_name': 'login.test.js', 'host_name': 'pi4',
             'device_name': 'Fire TV 2', 'success': True,
             'started_at': '2026-10-15T10:00:00+00:00'},
        ],
        'campaign_executions': [
            {'id': str(uuid.uuid4()), 'team_id': team_id, 'campaign_id': 'cmp-nightly',
             'success': True,  'started_at': '2026-10-15T02:00:00+00:00'},
            {'id': str(uuid.uuid4()), 'team_id': team_id, 'campaign_id': 'cmp-nightly',
             'success': True,  'started_at': '2026-10-16T02:00:00+00:00'},
            {'id': str(uuid.uuid4()), 'team_id': team_id, 'campaign_id': 'cmp-nightly',
             'success': False, 'started_at': '2026-10-17T02:00:00+00:00'},
        ],
        'ai_usage_stats': [],
        '_meta': [{
            'team_id': team_id, 'p1': p1,
            'owner_tm_id': owner_tm_id,
            'scope_tag_id': scope_tag_id, 'user_tag_id': user_tag_id,
            # `tag1` keeps the same name as the previous fixture so tests that
            # use `meta['tag1']` work.
            'tag1': scope_tag_id,
        }],
    }
    mock = SupabaseMock(initial=seed)
    return mock, seed, seed['_meta'][0]


@pytest.fixture
def in_scope_env(monkeypatch):
    """Seed the in-memory Supabase mock and return `(mock, seed, meta, pdb)`.

    Pattern mirrors `test_projects_can_edit_in_memory.py` — we patch
    `pdb._supabase` (the module-level helper projects_db uses to grab the
    service-role client) and leave the module itself alone. Any code
    that imported `projects_db` already got a reference to the module
    object, so the patched `_supabase` propagates through the
    `from shared.src.lib.database import projects_db` import that
    `server_projects_in_scope_routes` does at module load.
    """
    mock, seed, meta = _make_in_scope_seed()
    import shared.src.lib.database.projects_db as pdb
    monkeypatch.setattr(pdb, '_supabase', lambda: mock)
    return mock, seed, meta, pdb


# ---------------------------------------------------------------------------
# projects_db helpers
# ---------------------------------------------------------------------------
class TestListInScopeDevices:
    @pytest.mark.unit
    def test_returns_only_devices_with_matching_flag(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        devs = pdb.list_in_scope_devices(meta['p1'], meta['team_id'])
        # 2 devices carry `qa-test` (firetv-01, firetv-02). android-tv-01 carries
        # `mobile_app` and must NOT show up.
        ids = sorted(d['device_id'] for d in devs)
        assert ids == ['firetv-01', 'firetv-02']
        for d in devs:
            assert d['in_scope_via'] == 'qa-test'
            assert 'qa-test' in d['flags']

    @pytest.mark.unit
    def test_run_counts_aggregate_per_device(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        devs = pdb.list_in_scope_devices(meta['p1'], meta['team_id'])
        d1 = next(d for d in devs if d['device_id'] == 'firetv-01')
        # 6 login + 2 checkout + 1 virtual = 9 runs on this device.
        # The virtual-script run joins through `device_name`, not just
        # `script_name` — every script_result row for the device counts.
        assert d1['runs_30d'] == 9
        # 8 pass / 9 runs = 88.9 → round() → 89
        assert d1['pct_pass'] == 89

    @pytest.mark.unit
    def test_last_seen_at_picks_most_recent_run(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        devs = pdb.list_in_scope_devices(meta['p1'], meta['team_id'])
        d1 = next(d for d in devs if d['device_id'] == 'firetv-01')
        # The most-recent run for firetv-01 was the virtual-script run at
        # 12:00 on 2026-10-15 (later than the login.test.js fail at 10:25).
        assert d1['last_seen_at'] == '2026-10-15T12:00:00+00:00'

    @pytest.mark.unit
    def test_empty_when_project_has_no_tags(self, in_scope_env):
        mock, _, meta, pdb = in_scope_env
        # Force the project to have no `projects_tags` rows — that's the
        # source of truth for `tag_names`, and the helper short-circuits
        # when the project carries no tags. `mock.get_table` returns a
        # copy of the live list, so we reach into `_tables` directly.
        mock._tables['projects_tags'] = [
            r for r in mock._tables.get('projects_tags', [])
            if r['project_id'] != meta['p1']
        ]
        assert pdb.list_in_scope_devices(meta['p1'], meta['team_id']) == []


class TestListInScopeExecutables:
    @pytest.mark.unit
    def test_returns_scripts_testcases_virtuals_as_peers(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        rows = pdb.list_in_scope_executables(meta['p1'], meta['team_id'])
        # 2 scripts + 1 testcase + 1 virtual = 4
        assert len(rows) == 4
        types = sorted(r['type'] for r in rows)
        assert types == ['script', 'script', 'testcase', 'virtual_script']

    @pytest.mark.unit
    def test_script_runs_aggregate_correctly(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        rows = pdb.list_in_scope_executables(meta['p1'], meta['team_id'])
        login = next(r for r in rows if r['name'] == 'login.test.js')
        # 5 pass + 1 fail (firetv-01) + 1 pass (firetv-02) = 7 runs, 6 pass
        assert login['runs_30d'] == 7
        assert login['pct_pass'] == 86  # 6/7 = 85.71 → 86

    @pytest.mark.unit
    def test_virtual_script_runs_via_virtual_script_id(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        rows = pdb.list_in_scope_executables(meta['p1'], meta['team_id'])
        vs = next(r for r in rows if r['type'] == 'virtual_script')
        assert vs['id'] == 'vs-smoke'
        assert vs['runs_30d'] == 1
        assert vs['pct_pass'] == 100

    @pytest.mark.unit
    def test_testcase_runs_show_zero(self, in_scope_env):
        """Today testcases don't have a dedicated runs table; we report 0
        instead of fabricating a number. Documented in the in-scope route
        docstring as a v2 enhancement.
        """
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        rows = pdb.list_in_scope_executables(meta['p1'], meta['team_id'])
        tc = next(r for r in rows if r['type'] == 'testcase')
        assert tc['runs_30d'] == 0
        assert tc['pct_pass'] is None


class TestListInScopeCampaigns:
    @pytest.mark.unit
    def test_returns_only_campaigns_tagged_with_project(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        meta = in_scope_env[2]
        rows = pdb.list_in_scope_campaigns(meta['p1'], meta['team_id'])
        assert len(rows) == 1
        c = rows[0]
        assert c['id'] == 'cmp-nightly'
        assert c['name'] == 'Nightly'
        assert c['schedule'] == 'every day at 02:00'
        # 2 pass + 1 fail = 3 runs, 67%
        assert c['runs_30d'] == 3
        assert c['pct_pass'] == 67


class TestAddRemoveExecutableLink:
    @pytest.mark.unit
    def test_add_inserts_executable_tags_row(self, in_scope_env):
        mock, _, meta, pdb = in_scope_env
        # Add a new script link that the seed didn't include.
        ok = pdb.add_executable_to_project(meta['p1'], 'script', 'scr-new')
        assert ok
        rows = [
            r for r in mock.get_table('executable_tags')
            if r['executable_type'] == 'script' and r['executable_id'] == 'scr-new'
        ]
        assert len(rows) == 1
        assert rows[0]['tag_id'] == meta['tag1']

    @pytest.mark.unit
    def test_add_is_idempotent(self, in_scope_env):
        _, _, meta, pdb = in_scope_env
        # login.test.js is already in the seed.
        ok = pdb.add_executable_to_project(meta['p1'], 'script', 'login.test.js')
        assert ok
        # Count rows for that id+type — should still be 1.
        rows = [
            r for r in in_scope_env[0].get_table('executable_tags')
            if r['executable_type'] == 'script' and r['executable_id'] == 'login.test.js'
        ]
        assert len(rows) == 1

    @pytest.mark.unit
    def test_add_rejects_unknown_type(self, in_scope_env):
        _, _, meta, pdb = in_scope_env
        ok = pdb.add_executable_to_project(meta['p1'], 'unknown_type', 'x')
        assert ok is False

    @pytest.mark.unit
    def test_remove_severs_link_only(self, in_scope_env):
        mock, _, meta, pdb = in_scope_env
        # Before: login.test.js has 1 executable_tags row.
        before = sum(
            1 for r in mock.get_table('executable_tags')
            if r['executable_type'] == 'script' and r['executable_id'] == 'login.test.js'
        )
        assert before == 1
        ok = pdb.remove_executable_from_project(meta['p1'], 'script', 'login.test.js')
        assert ok
        # After: 0 rows for that id+type.
        after = sum(
            1 for r in mock.get_table('executable_tags')
            if r['executable_type'] == 'script' and r['executable_id'] == 'login.test.js'
        )
        assert after == 0

    @pytest.mark.unit
    def test_remove_unknown_id_is_noop(self, in_scope_env):
        _, _, meta, pdb = in_scope_env
        ok = pdb.remove_executable_from_project(meta['p1'], 'script', 'never-existed')
        # Idempotent — returns True even if there was no row.
        assert ok


class TestTagByName:
    @pytest.mark.unit
    def test_get_or_create_returns_existing_tag(self, in_scope_env):
        _, _, _, pdb = in_scope_env
        # `web_app` is in the seed's `tags` table.
        tag = pdb.get_or_create_tag_by_name('web_app')
        assert tag is not None
        assert tag['name'] == 'web_app'

    @pytest.mark.unit
    def test_get_or_create_inserts_new_tag(self, in_scope_env):
        mock, _, _, pdb = in_scope_env
        before = len(mock.get_table('tags'))
        tag = pdb.get_or_create_tag_by_name('fresh-tag-99')
        assert tag is not None
        assert tag['name'] == 'fresh-tag-99'
        # Mock list-append, so we should see +1 row.
        assert len(mock.get_table('tags')) == before + 1

    @pytest.mark.unit
    def test_add_user_tag_sets_is_scope_false(self, in_scope_env):
        mock, _, meta, pdb = in_scope_env
        ok = pdb.add_user_tag_to_project(meta['p1'], 1234)
        assert ok
        rows = [
            r for r in mock.get_table('projects_tags')
            if r['project_id'] == meta['p1'] and r['tag_id'] == 1234
        ]
        assert len(rows) == 1
        assert rows[0]['is_scope'] is False

    @pytest.mark.unit
    def test_remove_user_tag_refuses_to_drop_scope_tag(self, in_scope_env):
        _, _, meta, pdb = in_scope_env
        # tag1 is the SCOPE tag for p1 (no is_scope row in the seed, but
        # the API contract is "is_scope = false" filter; the seed didn't
        # write is_scope=True explicitly. Set it now to mirror the real
        # migration: `projects_tags` has the auto scope row with
        # `is_scope = TRUE`).
        pt = in_scope_env[0].get_table('projects_tags')
        scope_row = next(
            r for r in pt
            if r['project_id'] == meta['p1'] and r['tag_id'] == meta['tag1']
        )
        scope_row['is_scope'] = True
        # Now try to remove it via the user-tag helper. The SQL has
        # `.eq('is_scope', False)`, so the row is untouched.
        ok = pdb.remove_user_tag_from_project(meta['p1'], meta['tag1'])
        assert ok
        rows = [
            r for r in pt
            if r['project_id'] == meta['p1'] and r['tag_id'] == meta['tag1']
        ]
        assert len(rows) == 1  # the scope row is still there

    @pytest.mark.unit
    def test_remove_user_tag_drops_only_user_tag_rows(self, in_scope_env):
        _, _, meta, pdb = in_scope_env
        # user_tag_id is already linked to p1 as is_scope=false.
        ok = pdb.remove_user_tag_from_project(meta['p1'], meta['user_tag_id'])
        assert ok
        rows = [
            r for r in in_scope_env[0]._tables.get('projects_tags', [])
            if r['project_id'] == meta['p1'] and r['tag_id'] == meta['user_tag_id']
        ]
        assert rows == []  # the user-tag row is gone
        # The scope tag row is intact.
        scope_rows = [
            r for r in in_scope_env[0]._tables.get('projects_tags', [])
            if r['project_id'] == meta['p1'] and r['tag_id'] == meta['tag1']
        ]
        assert len(scope_rows) == 1


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
class TestInScopeEndpoint:
    @pytest.mark.unit
    def test_get_in_scope_returns_full_payload(self, in_scope_env, monkeypatch):
        from flask import Flask
        from backend_server.src.routes import server_projects_in_scope_routes as mod

        mock, seed, meta = in_scope_env[0], in_scope_env[1], in_scope_env[2]
        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env[3])
        monkeypatch.setattr(
            in_scope_env[3], 'get_project',
            lambda pid: {
                'id': pid, 'team_id': meta['team_id'], 'name': 'QA — Nightly',
                'description': None, 'color': '#d4a574',
                'created_by': meta['owner_tm_id'],
                'created_at': '2026-09-01T00:00:00+00:00',
                'tags': [
                    {'tag_id': meta['tag1'],    'name': 'qa-test', 'color': '#d4a574', 'is_scope': True},
                    {'tag_id': meta['user_tag_id'], 'name': 'nightly', 'color': '#22c55e', 'is_scope': False},
                ],
                'members': [], 'tag_ids': [meta['tag1'], meta['user_tag_id']],
                'member_count': 1, 'owner_count': 1, 'viewer_count': 0,
            },
        )
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()

        resp = client.get(f'/server/projects/{meta["p1"]}/in-scope?days=30')
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body['project_id'] == meta['p1']
        assert body['days'] == 30
        assert sorted(body['tag_names']) == ['nightly', 'qa-test']
        # Totals
        t = body['totals']
        assert t['devices'] == 2  # 2 in-scope devices
        assert t['hosts'] == 1  # both on pi4
        assert t['executables']['total'] == 4
        assert t['executables']['scripts'] == 2
        assert t['executables']['testcases'] == 1
        assert t['executables']['virtual'] == 1
        assert t['campaigns'] == 1
        # Devices
        device_ids = sorted(d['device_id'] for d in body['devices'])
        assert device_ids == ['firetv-01', 'firetv-02']
        # Executables
        types = sorted(r['type'] for r in body['executables'])
        assert types == ['script', 'script', 'testcase', 'virtual_script']
        # Campaigns
        assert body['campaigns'][0]['name'] == 'Nightly'
        assert body['campaigns'][0]['pct_pass'] == 67
        # BUG-0609 — AI summary default (mock has no `ai_calls` rows for
        # this project, so the helper returns the zero dict). After
        # 79ac4deb9 the empty-case summary also exposes empty top_features /
        # top_senders lists.
        assert body['summary'] == {
            'tokens': 0, 'calls': 0, 'cost_usd': 0.0,
            'top_features': [], 'top_senders': [],
        }

    @pytest.mark.unit
    def test_in_scope_summary_sums_ai_calls_for_project(
        self, in_scope_env, monkeypatch,
    ):
        """BUG-0609 — `_ai_tokens_for_project` reads `ai_calls` filtered by
        `project_id` and sums tokens + cost. The mock's `sb.table()` is a
        thin wrapper around `_tables['ai_calls']`, so we seed the rows
        directly and assert the helper produces the expected rollup.
        """
        from backend_server.src.routes import server_projects_in_scope_routes as mod

        mock = in_scope_env[0]
        # Seed `ai_calls` rows for two projects across the 30-day window.
        ai_calls_table = mock._tables.setdefault('ai_calls', [])
        ai_calls_table.extend([
            {'project_id': 'p1', 'tokens_in': 100, 'tokens_out': 50,
             'cost_usd': 12, 'ts': '2026-10-10T00:00:00+00:00'},
            {'project_id': 'p1', 'tokens_in': 20, 'tokens_out': 30,
             'cost_usd': 7, 'ts': '2026-10-11T00:00:00+00:00'},
            # Other-project rows must NOT contribute.
            {'project_id': 'p_other', 'tokens_in': 9999, 'tokens_out': 9999,
             'cost_usd': 999, 'ts': '2026-10-10T00:00:00+00:00'},
            # Out-of-window rows must NOT contribute either.
            {'project_id': 'p1', 'tokens_in': 1, 'tokens_out': 1,
             'cost_usd': 0, 'ts': '2020-01-01T00:00:00+00:00'},
        ])
        # The helper reads via the module's `_supabase` wrapper, so patch
        # it to return the mock. In production it returns the real client.
        monkeypatch.setattr(mod, '_supabase', lambda: mock)

        result = mod._ai_tokens_for_project('p1', 30)
        # 100 + 50 + 20 + 30 = 200 tokens; cost = (12 + 7) / 1000 = 0.019
        assert result['tokens'] == 200
        assert result['calls'] == 2
        assert result['cost_usd'] == 0.019

    @pytest.mark.unit
    def test_in_scope_404_when_project_missing(self, in_scope_env, monkeypatch):
        from flask import Flask
        from backend_server.src.routes import server_projects_in_scope_routes as mod

        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env[3])
        monkeypatch.setattr(in_scope_env[3], 'get_project', lambda pid: None)
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.get('/server/projects/does-not-exist/in-scope')
        assert resp.status_code == 404


class TestLinkAddRemoveEndpoint:
    @pytest.mark.unit
    def _load_route(self, monkeypatch):
        from backend_server.src.routes import server_projects_in_scope_routes as mod
        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env.__self__ if False else None)  # placeholder
        return mod

    def _admin_or_owner(self, monkeypatch, *, as_admin: bool, as_owner: bool):
        from backend_server.src.routes import server_projects_routes as base
        # Patch `_can_edit_project` directly so the test doesn't depend on
        # `caller_is_admin` + `caller_project_role` plumbing.
        # Patch in the in-scope module (it imported the symbol at module load).
        from backend_server.src.routes import server_projects_in_scope_routes as mod
        monkeypatch.setattr(
            mod, '_can_edit_project',
            lambda pid: as_admin or as_owner,
        )

    def test_link_add_succeeds_for_admin(self, in_scope_env, monkeypatch):
        from flask import Flask
        from backend_server.src.routes import server_projects_in_scope_routes as mod

        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env[3])
        monkeypatch.setattr(mod, '_supabase', lambda: in_scope_env[0])
        self._admin_or_owner(monkeypatch, as_admin=True, as_owner=False)
        # Mock _not_in_scope_or_missing by patching the symbol in the in-scope
        # module (it imported the function from server_projects_routes at load).
        monkeypatch.setattr(
            mod, '_not_in_scope_or_missing',
            lambda pid: (None, {'id': pid, 'team_id': in_scope_env[2]['team_id']}),
        )
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.post(
            f'/server/projects/{in_scope_env[2]["p1"]}/link',
            json={'type': 'script', 'id': 'new-script-99'},
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body['type'] == 'script'
        assert body['id'] == 'new-script-99'
        assert body['already_linked'] is False

    def test_link_add_403_for_viewer(self, in_scope_env, monkeypatch):
        from flask import Flask
        from backend_server.src.routes import server_projects_in_scope_routes as mod

        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env[3])
        monkeypatch.setattr(mod, '_supabase', lambda: in_scope_env[0])
        self._admin_or_owner(monkeypatch, as_admin=False, as_owner=False)
        monkeypatch.setattr(
            mod, '_not_in_scope_or_missing',
            lambda pid: (None, {'id': pid, 'team_id': in_scope_env[2]['team_id']}),
        )
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.post(
            f'/server/projects/{in_scope_env[2]["p1"]}/link',
            json={'type': 'script', 'id': 'x'},
        )
        assert resp.status_code == 403

    def test_link_add_400_for_unknown_type(self, in_scope_env, monkeypatch):
        from flask import Flask
        from backend_server.src.routes import server_projects_in_scope_routes as mod

        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env[3])
        self._admin_or_owner(monkeypatch, as_admin=True, as_owner=False)
        monkeypatch.setattr(
            mod, '_not_in_scope_or_missing',
            lambda pid: (None, {'id': pid, 'team_id': in_scope_env[2]['team_id']}),
        )
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.post(
            f'/server/projects/{in_scope_env[2]["p1"]}/link',
            json={'type': 'invalid', 'id': 'x'},
        )
        assert resp.status_code == 400

    def test_link_remove_is_idempotent(self, in_scope_env, monkeypatch):
        from flask import Flask
        from backend_server.src.routes import server_projects_in_scope_routes as mod

        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env[3])
        self._admin_or_owner(monkeypatch, as_admin=True, as_owner=False)
        monkeypatch.setattr(
            mod, '_not_in_scope_or_missing',
            lambda pid: (None, {'id': pid, 'team_id': in_scope_env[2]['team_id']}),
        )
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        # Removing a non-existent link is still 200 with was_linked=false.
        resp = client.delete(
            f'/server/projects/{in_scope_env[2]["p1"]}/link',
            json={'type': 'script', 'id': 'never-existed'},
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()['was_linked'] is False


class TestTagByNameEndpoint:
    def _setup(self, in_scope_env, monkeypatch, *, can_edit: bool):
        from backend_server.src.routes import server_projects_in_scope_routes as mod
        monkeypatch.setattr(mod, '_in_team_scope', lambda team_id: True)
        monkeypatch.setattr(mod, 'projects_db', in_scope_env[3])
        # The route module imports `get_supabase_client` and wraps it in a
        # local `_supabase()` for its own queries (the tag-by-name lookup
        # in `remove_user_tag_by_name`). Patch that local too.
        monkeypatch.setattr(mod, '_supabase', lambda: in_scope_env[0])
        monkeypatch.setattr(mod, '_can_edit_project', lambda pid: can_edit)
        monkeypatch.setattr(
            mod, '_not_in_scope_or_missing',
            lambda pid: (None, {'id': pid, 'team_id': in_scope_env[2]['team_id']}),
        )
        return mod

    @pytest.mark.unit
    def test_add_user_tag_by_name(self, in_scope_env, monkeypatch):
        from flask import Flask
        mod = self._setup(in_scope_env, monkeypatch, can_edit=True)
        # The mock's insert auto-generates an `id` UUID but no `tag_id`
        # int. Pre-create the `tags` rows so `get_or_create_tag_by_name`
        # hits the existing-row branch (the production path is the same
        # shape: PostgREST returns the row including the auto-generated
        # `tag_id` on insert; the in-memory mock can't do that without
        # schema knowledge). `mock.get_table` returns a copy, so we
        # mutate `_tables` directly.
        next_tag_id = 200
        for n in ('fresh-tag-1', 'fresh-tag-2'):
            in_scope_env[0]._tables['tags'].append({
                'tag_id': next_tag_id, 'name': n, 'color': '#aabbcc',
            })
            next_tag_id += 1
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.post(
            f'/server/projects/{in_scope_env[2]["p1"]}/tags/names',
            json={'names': ['fresh-tag-1', 'fresh-tag-2']},
        )
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert sorted(body['added']) == ['fresh-tag-1', 'fresh-tag-2']
        assert body['skipped'] == []
        # And both must be linked to the project as user tags.
        linked = [
            r for r in in_scope_env[0]._tables.get('projects_tags', [])
            if r['project_id'] == in_scope_env[2]['p1']
        ]
        # 2 existing (qa-test scope + nightly user) + 2 new = 4
        assert len(linked) == 4

    @pytest.mark.unit
    def test_add_user_tag_403_for_viewer(self, in_scope_env, monkeypatch):
        from flask import Flask
        mod = self._setup(in_scope_env, monkeypatch, can_edit=False)
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.post(
            f'/server/projects/{in_scope_env[2]["p1"]}/tags/names',
            json={'names': ['sneaky']},
        )
        assert resp.status_code == 403

    @pytest.mark.unit
    def test_add_user_tag_400_for_invalid_name(self, in_scope_env, monkeypatch):
        from flask import Flask
        mod = self._setup(in_scope_env, monkeypatch, can_edit=True)
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.post(
            f'/server/projects/{in_scope_env[2]["p1"]}/tags/names',
            json={'names': ['ok name with spaces']},
        )
        assert resp.status_code == 400

    @pytest.mark.unit
    def test_remove_user_tag_by_name(self, in_scope_env, monkeypatch):
        from flask import Flask
        mod = self._setup(in_scope_env, monkeypatch, can_edit=True)
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        # `nightly` is the user tag we linked in the seed.
        resp = client.delete(f'/server/projects/{in_scope_env[2]["p1"]}/tags/names/nightly')
        assert resp.status_code == 200, resp.get_json()
        # The user-tag row must be gone; the scope tag must remain.
        linked = [
            r for r in in_scope_env[0].get_table('projects_tags')
            if r['project_id'] == in_scope_env[2]['p1']
        ]
        assert len(linked) == 1
        assert linked[0]['tag_id'] == in_scope_env[2]['tag1']  # the scope tag

    @pytest.mark.unit
    def test_remove_user_tag_400_for_scope_tag(self, in_scope_env, monkeypatch):
        from flask import Flask
        from backend_server.src.routes import server_projects_in_scope_routes as mod
        mod = self._setup(in_scope_env, monkeypatch, can_edit=True)
        # Mark qa-test as the scope tag in projects_tags so list_project_tags
        # surfaces the is_scope flag. The mock's `get_table` returns a copy,
        # so we mutate `_tables` directly.
        pt = in_scope_env[0]._tables.get('projects_tags', [])
        for r in pt:
            if r['project_id'] == in_scope_env[2]['p1'] and r['tag_id'] == in_scope_env[2]['tag1']:
                r['is_scope'] = True
        app = Flask(__name__)
        app.register_blueprint(mod.server_projects_in_scope_bp)
        client = app.test_client()
        resp = client.delete(f'/server/projects/{in_scope_env[2]["p1"]}/tags/names/qa-test')
        assert resp.status_code == 400
        assert 'scope' in resp.get_json()['error'].lower()
