"""
In-memory tests for TASK-65 G10 — virtual scripts + campaigns carry tags,
and the UI save path sends `X-Project-Id` so the server can auto-tag.

What G10 ships
--------------
* `setup/db/migrations/20261015a_executable_tags_virtual_script_campaign.sql`
  widens `executable_tags.executable_type` to VARCHAR(20) and the CHECK to
  `('script', 'testcase', 'virtual_script', 'campaign')`.
* `shared/src/lib/database/folder_tag_db.py` documents and accepts the new
  types; the helpers (`set_executable_tags`, `get_executable_tags`,
  `get_executable_tags_bulk`) were already trip-free — the constraint
  widened underneath.
* `backend_server/src/routes/server_executable_routes.py` drops the
  "virtual scripts carry no tags yet" filter and surfaces the tags
  (display id `name.py`, mirroring the disk-script convention).
* `shared/src/lib/database/campaign_db.py` `list_campaigns` now emits a
  `tags: List[str]` per row, batch-fetched via the existing
  `get_executable_tags_bulk('campaign', ...)` path.
* The UI save paths (`useTestCaseSave`, `useVirtualScripts`, `BuildCampaigns`)
  read `localStorage['virtualpytest:project_id']` and pass it on the
  request as `X-Project-Id`, mirroring G5's `AgentChat`.

The tests below cover the migration, the helpers, and the
`/server/executable/list` change — without a live backend, using
`SupabaseMock` + `apply_migration_sql` to mirror the post-apply state.
"""
import sys
import os
from typing import Any, Dict, List

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))  # for `_supabase_mock`
sys.path.insert(0, REPO_ROOT)

from _supabase_mock import (  # type: ignore  # noqa: E402
    SupabaseMock,
    apply_migration_sql,
    make_projects_seed,
    get_meta,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _read_migration(filename: str) -> str:
    """Load a TASK-65 migration file relative to the repo root."""
    path = os.path.join(REPO_ROOT, 'setup', 'db', 'migrations', filename)
    with open(path) as f:
        return f.read()


@pytest.fixture
def mock_supabase() -> SupabaseMock:
    """A mock with the 3 G1–G4 migrations + G10 applied in memory.

    `executable_tags` already exists in `make_projects_seed()` (the
    G1–G4 mock seed carries three 'script' rows). The G10 forward
    migration widens its `executable_type` column to VARCHAR(20) and
    the CHECK to include 'virtual_script' + 'campaign' — that's all we
    need to assert on for the schema shape.
    """
    mock = SupabaseMock(initial=make_projects_seed())
    for fn in [
        '20261006a_projects.sql',
        '20261006b_team_members_last_seen.sql',
        '20261006c_report_snapshots_project_ids.sql',
        '20261015a_executable_tags_virtual_script_campaign.sql',
    ]:
        apply_migration_sql(mock, _read_migration(fn))
    return mock


# ---------------------------------------------------------------------------
# Migration checks
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG10Migration:
    """The G10 forward migration widens the executable_tags CHECK and the
    column width so virtual scripts and campaigns can carry tags."""

    def test_forward_migration_lists_in_migration_checker(self):
        """`scripts/check_projects_migrations.py` knows about both files."""
        import importlib.util
        path = os.path.join(REPO_ROOT, 'scripts', 'check_projects_migrations.py')
        spec = importlib.util.spec_from_file_location('proj_chk', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        expected = mod.EXPECTED
        assert '20261015a_executable_tags_virtual_script_campaign.sql' in expected
        rollback = '20261015a_executable_tags_virtual_script_campaign_rollback.sql'
        assert rollback in expected

    def test_migration_checker_passes_for_g10(self):
        """`scripts/check_projects_migrations.py` returns exit 0 with the G10
        files in place. The script writes to stdout and exits with 0/1; the
        importlib-loaded module lets us invoke the inner functions."""
        import importlib.util
        path = os.path.join(REPO_ROOT, 'scripts', 'check_projects_migrations.py')
        spec = importlib.util.spec_from_file_location('proj_chk', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for filename in (
            '20261015a_executable_tags_virtual_script_campaign.sql',
            '20261015a_executable_tags_virtual_script_campaign_rollback.sql',
        ):
            failures = mod.check_migration(
                filename,
                mod.EXPECTED[filename],
                mod._strip_comments(_read_migration(filename)),
            )
            assert failures == [], f'{filename}: {failures}'

    def test_forward_migration_sql_contains_required_pieces(self):
        """Spot-check the SQL file has the four CHECK values, the column
        width, and the data_migrations guard row is COMMENTED OUT (so the
        blueprint stays a blueprint — we don't accidentally double-apply)."""
        sql = _read_migration('20261015a_executable_tags_virtual_script_campaign.sql')
        for piece in (
            'ALTER TABLE public.executable_tags',
            'executable_type TYPE VARCHAR(20)',
            "executable_tags_executable_type_check",
            "'virtual_script'",
            "'campaign'",
            # The data_migrations guard row must stay commented out.
            '-- INSERT INTO public.data_migrations',
        ):
            assert piece in sql, f'forward migration missing: {piece!r}'

    def test_rollback_migration_sql_contains_required_pieces(self):
        """Spot-check the rollback has the wipe-DELETE, the original two
        values, and the type narrowing."""
        sql = _read_migration('20261015a_executable_tags_virtual_script_campaign_rollback.sql')
        for piece in (
            'DELETE FROM public.executable_tags',
            "'virtual_script'",
            "'campaign'",
            "executable_type TYPE VARCHAR(10)",
            "'script'",
            "'testcase'",
        ):
            assert piece in sql, f'rollback migration missing: {piece!r}'


# ---------------------------------------------------------------------------
# Helper checks — `folder_tag_db` accepts the new types
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG10FolderTagDb:
    """`folder_tag_db.set_executable_tags` accepts virtual_script + campaign.

    The helper itself doesn't validate; the DB CHECK is what enforces it.
    These tests stub the Supabase client to confirm a 'virtual_script' or
    'campaign' insert makes it to the table without the helper refusing.
    """

    def _make_mock_supabase(self) -> SupabaseMock:
        return SupabaseMock(initial=make_projects_seed())

    def test_set_executable_tags_accepts_virtual_script(self, monkeypatch):
        """Inserting an `executable_tags` row with `executable_type =
        'virtual_script'` succeeds through `set_executable_tags`."""
        import importlib
        import shared.src.lib.database.folder_tag_db as ftd
        # Reload so the patch below lands on a fresh module dict (mirrors
        # the G5 in-memory fixture's `importlib.reload(pdb)`).
        importlib.reload(ftd)

        mock = self._make_mock_supabase()
        monkeypatch.setattr(ftd, 'get_supabase_client', lambda: mock)

        # Pre-create the tag with `tag_id` explicitly. The mock's auto-id
        # generator only fills `id` (UUID); the `tags` PK is `tag_id` (serial),
        # and the helper reads `tag['tag_id']` on the returned row. Pre-seed
        # the row so `get_or_create_tag` finds it and returns a dict with
        # `tag_id` set. (Same pattern the G5 in-memory test uses for
        # `_get_or_create_tag`.)
        mock._tables.setdefault('tags', []).append(
            {'tag_id': 101, 'name': 'vs_only_tag', 'color': '#d4a574'}
        )

        ok = ftd.set_executable_tags(
            'virtual_script',
            'vs_001',
            ['vs_only_tag'],
        )
        assert ok is True
        rows = [
            r for r in mock.get_table('executable_tags')
            if r.get('executable_type') == 'virtual_script'
            and r.get('executable_id') == 'vs_001'
        ]
        assert len(rows) == 1
        assert rows[0]['tag_id'] == 101

    def test_set_executable_tags_accepts_campaign(self, monkeypatch):
        """Inserting an `executable_tags` row with `executable_type =
        'campaign'` succeeds through `set_executable_tags`."""
        from shared.src.lib.database import folder_tag_db as ftd

        mock = self._make_mock_supabase()
        monkeypatch.setattr(ftd, 'get_supabase_client', lambda: mock)

        mock._tables.setdefault('tags', []).append(
            {'tag_id': 201, 'name': 'camp_only_tag', 'color': '#22c55e'}
        )

        ok = ftd.set_executable_tags(
            'campaign',
            'camp_001',
            ['camp_only_tag'],
        )
        assert ok is True
        rows = [
            r for r in mock.get_table('executable_tags')
            if r.get('executable_type') == 'campaign'
            and r.get('executable_id') == 'camp_001'
        ]
        assert len(rows) == 1
        assert rows[0]['tag_id'] == 201

    def test_get_executable_tags_returns_virtual_script_tags(self, monkeypatch):
        """Round-trip: tag a virtual script, read it back."""
        from shared.src.lib.database import folder_tag_db as ftd

        mock = self._make_mock_supabase()
        monkeypatch.setattr(ftd, 'get_supabase_client', lambda: mock)

        # Pre-seed the tag so `set_executable_tags` (which calls
        # `get_or_create_tag` and then reads `tag['tag_id']`) finds a row
        # with the PK column the helper expects.
        mock._tables.setdefault('tags', []).append(
            {'tag_id': 301, 'name': 'vs_only_tag', 'color': '#d4a574'}
        )
        # Set the tag.
        ftd.set_executable_tags('virtual_script', 'vs_002', ['vs_only_tag'])
        # The mock doesn't auto-join `executable_tags` with `tags`. To
        # exercise `get_executable_tags` we augment the just-inserted row
        # with the embedded `tags` relation the way real Supabase would
        # return it.
        inserted = next(
            r for r in mock.get_table('executable_tags')
            if r.get('executable_id') == 'vs_002'
            and r.get('executable_type') == 'virtual_script'
        )
        inserted['tags'] = {'name': 'vs_only_tag', 'color': '#d4a574'}

        out = ftd.get_executable_tags('virtual_script', 'vs_002')
        assert out and out[0]['name'] == 'vs_only_tag'

    def test_get_executable_tags_bulk_includes_campaign_and_virtual_script(self, monkeypatch):
        """`get_executable_tags_bulk` returns both kinds when both are asked."""
        from shared.src.lib.database import folder_tag_db as ftd

        mock = self._make_mock_supabase()
        monkeypatch.setattr(ftd, 'get_supabase_client', lambda: mock)

        # Insert two fresh tags and map them to a virtual_script and a campaign
        # via the public API (so the mock's `_tables` stays internally valid).
        mock._tables.setdefault('tags', []).extend([
            {'tag_id': 401, 'name': 'bulk_vs_tag', 'color': '#000000'},
            {'tag_id': 402, 'name': 'bulk_camp_tag', 'color': '#ffffff'},
        ])
        # The bulk helper needs the nested relation populated; the test data
        # simulates a join. (See SupabaseMock._project_row for the relation
        # detection rule.)
        mock._tables.setdefault('executable_tags', []).extend([
            {
                'executable_type': 'virtual_script', 'executable_id': 'vs_x',
                'tag_id': 401, 'tags': {'name': 'bulk_vs_tag', 'color': '#000000'},
            },
            {
                'executable_type': 'campaign', 'executable_id': 'camp_x',
                'tag_id': 402, 'tags': {'name': 'bulk_camp_tag', 'color': '#ffffff'},
            },
        ])

        vs_map = ftd.get_executable_tags_bulk('virtual_script', ['vs_x'])
        assert vs_map['vs_x'] and vs_map['vs_x'][0]['name'] == 'bulk_vs_tag'

        camp_map = ftd.get_executable_tags_bulk('campaign', ['camp_x'])
        assert camp_map['camp_x'] and camp_map['camp_x'][0]['name'] == 'bulk_camp_tag'


# ---------------------------------------------------------------------------
# Server-routes checks
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG10ExecutableListVirtualScripts:
    """`server_executable_routes.list_executables` no longer drops virtual
    scripts when a tag filter is set, and now surfaces their tags."""

    def _build_route(self, mock_supabase):
        """Import the route module with `_supabase_client` stubbed so the
        executable list builds its folder/tag tree from the in-memory mock."""
        import importlib.util
        path = os.path.join(
            REPO_ROOT,
            'backend_server', 'src', 'routes',
            'server_executable_routes.py',
        )
        spec = importlib.util.spec_from_file_location('exec_route', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Patch the imported binding in every helper the route imports —
        # `from X import Y` captures Y in the importer's __dict__ at load
        # time, so the patch has to land there, not just on the source.
        from shared.src.lib.utils import supabase_utils
        supabase_utils.get_supabase_client = lambda: mock_supabase
        from shared.src.lib.database import (
            folder_tag_db,
            testcase_db,
            virtual_scripts_db,
            library_visibility_db,
        )
        # folder_tag_db uses get_supabase_client (imported); the others use
        # their local `get_supabase` wrapper.
        folder_tag_db.get_supabase_client = lambda: mock_supabase
        testcase_db.get_supabase = lambda: mock_supabase
        virtual_scripts_db.get_supabase = lambda: mock_supabase
        library_visibility_db.get_supabase = lambda: mock_supabase
        return mod

    def test_virtual_script_surfaces_tags_in_response(self, monkeypatch):
        """`/server/executable/list` returns virtual scripts with their tag
        list populated when the underlying row has tags."""
        mock = SupabaseMock(initial=make_projects_seed())
        team_id = mock._tables['_meta'][0]['team_id']
        # Two virtual scripts — one tagged, one untagged.
        mock._tables.setdefault('virtual_scripts', []).extend([
            {
                'id': 'vs_t1', 'name': 'vs_t1', 'team_id': team_id,
                'description': 'tagged one', 'environment': 'dev', 'folder_id': 0,
                'prod_version': None,
            },
            {
                'id': 'vs_u1', 'name': 'vs_u1', 'team_id': team_id,
                'description': 'untagged one', 'environment': 'dev', 'folder_id': 0,
                'prod_version': None,
            },
        ])
        # Tag the first one with 'web_app'.
        mock._tables.setdefault('tags', []).append(
            {'tag_id': 500, 'name': 'web_app', 'color': '#d4a574'}
        )
        # Seed the joined row with the embedded `tags` relation so the mock's
        # `_project_row` finds it (SupabaseMock._project_row rule).
        mock._tables.setdefault('executable_tags', []).append({
            'executable_type': 'virtual_script',
            'executable_id': 'vs_t1.py',
            'tag_id': 500,
            'tags': {'name': 'web_app', 'color': '#d4a574'},
        })
        # Stub the disk script discovery to empty (we only want the virtual
        # scripts to appear, no fixture pollution from real scripts).
        from backend_server.src.lib.utils import script_utils
        monkeypatch.setattr(script_utils, 'list_available_scripts', lambda: [])
        monkeypatch.setattr(script_utils, 'extract_script_target_rules', lambda s: None)
        monkeypatch.setattr(script_utils, 'extract_script_description', lambda s: None)

        mod = self._build_route(mock)
        # Build the request context by hand: list_executables reads
        # `request.args.get(...)` and `list_virtual_scripts(team_id)` etc.
        from flask import Flask
        app = Flask(__name__)
        with app.test_request_context(
            '/?team_id=' + team_id,
        ):
            resp = mod.list_executables()
            data = resp.get_json() if hasattr(resp, 'get_json') else resp[0].get_json()

        # Pull all items across folders — we only care about virtual ones.
        items: List[Dict[str, Any]] = []
        for folder in data['folders']:
            items.extend(folder.get('items', []))

        vs_items = [i for i in items if i.get('is_virtual')]
        by_name = {i['name']: i for i in vs_items}
        assert 'vs_t1' in by_name and 'vs_u1' in by_name
        assert by_name['vs_t1']['tags'] == ['web_app']
        assert by_name['vs_u1']['tags'] == []

    def test_virtual_script_kept_when_filter_tags_matches(self, monkeypatch):
        """When the caller filters `?tags=web_app`, a virtual script tagged
        'web_app' is kept (and untagged ones dropped)."""
        mock = SupabaseMock(initial=make_projects_seed())
        team_id = mock._tables['_meta'][0]['team_id']
        mock._tables.setdefault('virtual_scripts', []).extend([
            {
                'id': 'vs_match', 'name': 'vs_match', 'team_id': team_id,
                'description': '', 'environment': 'dev', 'folder_id': 0,
                'prod_version': None,
            },
            {
                'id': 'vs_skip', 'name': 'vs_skip', 'team_id': team_id,
                'description': '', 'environment': 'dev', 'folder_id': 0,
                'prod_version': None,
            },
        ])
        mock._tables.setdefault('tags', []).append(
            {'tag_id': 600, 'name': 'web_app', 'color': '#d4a574'}
        )
        mock._tables.setdefault('executable_tags', []).append({
            'executable_type': 'virtual_script',
            'executable_id': 'vs_match.py',
            'tag_id': 600,
            'tags': {'name': 'web_app', 'color': '#d4a574'},
        })
        from backend_server.src.lib.utils import script_utils
        monkeypatch.setattr(script_utils, 'list_available_scripts', lambda: [])
        monkeypatch.setattr(script_utils, 'extract_script_target_rules', lambda s: None)
        monkeypatch.setattr(script_utils, 'extract_script_description', lambda s: None)

        mod = self._build_route(mock)
        from flask import Flask
        app = Flask(__name__)
        with app.test_request_context(
            f'/?team_id={team_id}&tags=web_app',
        ):
            resp = mod.list_executables()
            data = resp.get_json() if hasattr(resp, 'get_json') else resp[0].get_json()

        items: List[Dict[str, Any]] = []
        for folder in data['folders']:
            items.extend(folder.get('items', []))
        vs_names = sorted(i['name'] for i in items if i.get('is_virtual'))
        assert vs_names == ['vs_match']


# ---------------------------------------------------------------------------
# list_campaigns surfaces tags
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG10CampaignListEmitsTags:
    """`list_campaigns` now emits a `tags` field per row."""

    def _seed_campaigns(self, mock: SupabaseMock, campaign_ids: List[str]) -> str:
        """Seed two campaigns for the seed's team_id and return the team id."""
        team_id = mock._tables['_meta'][0]['team_id']
        mock._tables.setdefault('campaigns', []).extend([
            {
                'campaign_id': cid,
                'team_id': team_id,
                'campaign_name': f'C_{cid}',
                'description': None,
                'userinterface_name': None,
                'host_name': None,
                'device_name': None,
                'created_at': '2026-10-15T00:00:00+00:00',
                'updated_at': '2026-10-15T00:00:00+00:00',
                'created_by': None,
            }
            for cid in campaign_ids
        ])
        return team_id

    def test_list_campaigns_emits_tags_per_row(self, monkeypatch):
        """Every row has a `tags: List[str]` field, populated from
        `executable_tags`."""
        import importlib
        import shared.src.lib.database.campaign_db as cdb
        # Reload so the patch below lands on a fresh module dict (mirrors
        # the G5 in-memory fixture's `importlib.reload(pdb)`).
        importlib.reload(cdb)

        mock = SupabaseMock(initial=make_projects_seed())
        team_id = self._seed_campaigns(mock, ['camp_1', 'camp_2'])
        # Tag camp_1 with 'web_app'.
        mock._tables.setdefault('tags', []).append(
            {'tag_id': 700, 'name': 'web_app', 'color': '#d4a574'}
        )
        # Seed the joined row with the embedded `tags` relation.
        mock._tables.setdefault('executable_tags', []).append({
            'executable_type': 'campaign',
            'executable_id': 'camp_1',
            'tag_id': 700,
            'tags': {'name': 'web_app', 'color': '#d4a574'},
        })

        # Patch the imported binding in `campaign_db` AND in `folder_tag_db`
        # (the bulk tag lookup goes through folder_tag_db.get_executable_tags
        # _bulk, which has its own imported `get_supabase_client` from
        # `from X import Y` at module load — captured before any patch).
        monkeypatch.setattr(cdb, 'get_supabase_client', lambda: mock)
        from shared.src.lib.database import folder_tag_db
        monkeypatch.setattr(folder_tag_db, 'get_supabase_client', lambda: mock)
        from shared.src.lib.utils import supabase_utils
        monkeypatch.setattr(supabase_utils, 'get_supabase_client', lambda: mock)

        rows = cdb.list_campaigns(team_id)
        assert rows, 'expected seeded campaigns'
        by_id = {str(r['campaign_id']): r for r in rows}
        assert 'tags' in by_id['camp_1']
        assert 'tags' in by_id['camp_2']
        assert by_id['camp_1']['tags'] == ['web_app']
        assert by_id['camp_2']['tags'] == []


# ---------------------------------------------------------------------------
# Front-end helpers — the project header lookup
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG10ProjectHeader:
    """The UI save paths read `localStorage['virtualpytest:project_id']` and
    pass it as `X-Project-Id`. We don't run a browser, but we DO verify the
    constant we use is the right key (the same key G5's AgentChat uses)."""

    def test_project_id_localstorage_key_is_stable(self):
        """Every frontend save path uses `virtualpytest:project_id`. If this
        key ever drifts, the auto-tag silently breaks. Lock it down with a
        test that asserts the single canonical source — the `useCurrentProject`
        hook — declares the constant."""
        path = os.path.join(
            REPO_ROOT, 'frontend', 'src', 'hooks', 'common', 'useCurrentProject.ts'
        )
        with open(path) as f:
            contents = f.read()
        assert "'virtualpytest:project_id'" in contents

    def test_useTestCaseSave_reads_localstorage_project_id(self):
        """`useTestCaseSave` reads the localStorage key on every save."""
        path = os.path.join(
            REPO_ROOT,
            'frontend', 'src', 'hooks', 'testcase', 'useTestCaseSave.ts',
        )
        with open(path) as f:
            contents = f.read()
        assert "virtualpytest:project_id" in contents
        assert "X-Project-Id" in contents

    def test_useVirtualScripts_saveScript_reads_localstorage_project_id(self):
        """`useVirtualScripts.saveScript` reads the localStorage key."""
        path = os.path.join(
            REPO_ROOT,
            'features', 'virtual-scripts', 'frontend',
            'hooks', 'useVirtualScripts.ts',
        )
        with open(path) as f:
            contents = f.read()
        assert "virtualpytest:project_id" in contents
        assert "X-Project-Id" in contents

    def test_BuildCampaigns_saveCampaign_reads_localstorage_project_id(self):
        """`BuildCampaigns`'s save path reads the localStorage key."""
        path = os.path.join(REPO_ROOT, 'frontend', 'src', 'pages', 'BuildCampaigns.tsx')
        with open(path) as f:
            contents = f.read()
        assert "virtualpytest:project_id" in contents
        assert "X-Project-Id" in contents