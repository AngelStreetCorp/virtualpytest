"""BUG-0756 (framework leg): a check that was never configured is not a failure.

Run them with:

    timeout 300 python3 -m pytest tests/test_skipped_outcome.py -q

Nothing here touches the network, a browser, a host, a device or a database:
the Supabase client is the repo's own in-memory mock, the campaign-results
route is driven through Flask's test client, and the nightly poller is fed the
payload that route produces.

The negative control is the point: the same tests fail against the pre-fix
sources (`ff35a0524`), where `script_results` has no `skipped` column and an
unconfigured check is written as a plain failure.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The migration that adds the column, and the fresh-database schema.
MIGRATION_PATH = REPO_ROOT / 'setup' / 'db' / 'migrations' / '20261024a_script_results_skipped.sql'
SCHEMA_PATH = REPO_ROOT / 'setup' / 'db' / 'schema' / '084_script_results_skipped.sql'
POLLER_PATH = REPO_ROOT / 'scripts' / 'nightly_campaigns' / 'poll_results.py'

TEAM_ID = '11111111-1111-1111-1111-111111111111'
# Placeholders only: no real host name, device name or account in this file.
PLACEHOLDER_HOST = 'placeholder-host'
PLACEHOLDER_DEVICE = 'placeholder-device'

try:
    from shared.src.lib.database import campaign_executions_db as campaign_db
    from shared.src.lib.database import script_results_db as script_db
    from shared.src.lib.utils.web_video_legibility import (
        build_not_configured_verdict,
        build_playback_verdict,
    )
except Exception:  # pragma: no cover - the control must fail on an assertion, not on an import
    campaign_db = None
    script_db = None
    build_not_configured_verdict = None
    build_playback_verdict = None

try:
    from shared.src.lib.utils.script_skipped import derive_skipped
except Exception:  # pragma: no cover - same reason
    derive_skipped = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _not_configured_metadata():
    """The metadata a check that never ran (no account configured) carries."""
    verdict = build_not_configured_verdict(['--email'])
    return {
        'outcome': verdict['outcome'],
        'status': verdict['status'],
        'stage': verdict['stage'],
        'reason': verdict['reason'],
        'counts_as_playback_failure': verdict['counts_as_playback_failure'],
        'exit_code': verdict['exit_code'],
    }


def _failed_playback_metadata():
    """The metadata of a check that WAS configured, looked at a video and failed."""
    return {
        'outcome': 'playback_failed',
        'status': 'playback_failed',
        'stage': 'playback',
        'reason': 'a video element was found but it never started playing',
        'play_outcome': 'resolved',
        'counts_as_playback_failure': True,
    }


@pytest.fixture
def sb():
    """An in-memory stand-in for the Supabase client."""
    from tests._supabase_mock import SupabaseMock

    return SupabaseMock({'script_results': [], 'campaign_executions': []})


def _write_result(sb, monkeypatch, *, success, metadata, execution_time_ms=1000):
    """Write one script result row through the real writer."""
    monkeypatch.setattr(script_db, 'get_supabase', lambda: sb)
    script_result_id = script_db.record_script_execution_start(
        team_id=TEAM_ID,
        script_name='web/netflix_video_check.py',
        script_type='web/netflix_video_check.py',
        host_name=PLACEHOLDER_HOST,
        device_name=PLACEHOLDER_DEVICE,
    )
    assert script_result_id, 'the script result row was not created'
    written = script_db.update_script_execution_result(
        script_result_id=script_result_id,
        success=success,
        execution_time_ms=execution_time_ms,
        error_msg=None if success else 'the check did not pass',
        metadata=metadata,
    )
    assert written, 'the script result row was not updated'
    return script_result_id


def _seed_campaign(sb, monkeypatch, campaign_id, script_result_ids):
    """A running campaign waiting for the given script results."""
    monkeypatch.setattr(campaign_db, 'get_supabase', lambda: sb)
    now = datetime.now(timezone.utc).isoformat()
    sb.table('campaign_executions').insert({
        'id': campaign_id,
        'team_id': TEAM_ID,
        'campaign_name': 'nightly_video_check',
        'host_name': PLACEHOLDER_HOST,
        'status': 'running',
        'success': None,
        'started_at': now,
        'created_at': now,
        'updated_at': now,
        'script_result_ids': list(script_result_ids),
        'script_configurations': [
            {'script_name': 'web/netflix_video_check.py'} for _ in script_result_ids
        ],
        'execution_config': {},
    }).execute()
    return campaign_id


def _load_poller():
    """The nightly poller, loaded from its file (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location('vpt_poll_results', POLLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _route_script_columns(monkeypatch):
    """Ask the campaign-results route which script_results columns it selects."""
    import flask
    from backend_server.src.routes import server_campaign_results_routes as routes_mod

    captured = {}

    def _fake_get_campaign_results(team_id, limit=50, script_columns='*', host_names=None):
        captured['script_columns'] = script_columns
        return {'success': True, 'data': []}

    monkeypatch.setattr(routes_mod, 'check_supabase', lambda: None)
    monkeypatch.setattr(
        routes_mod,
        'get_host_manager',
        lambda: types.SimpleNamespace(get_all_hosts=lambda: {PLACEHOLDER_HOST: {}}),
    )
    monkeypatch.setattr(routes_mod, 'get_campaign_results', _fake_get_campaign_results)
    monkeypatch.setattr(routes_mod, 'publication_statuses_by_source', lambda team_id: {})
    monkeypatch.setattr(
        routes_mod,
        'testrail_service',
        types.SimpleNamespace(
            load_config=lambda team_id: {},
            has_mapping=lambda team_id, script_name: False,
        ),
    )

    app = flask.Flask('e73-campaign-results-test')
    app.register_blueprint(routes_mod.server_campaign_results_bp)
    client = app.test_client()
    response = client.get(f'/server/campaign-results/getAllCampaignResults?team_id={TEAM_ID}')
    assert response.status_code == 200, f'the campaign-results route answered {response.status_code}'
    assert 'script_columns' in captured, 'the route read no campaign results at all'
    return captured['script_columns']


# ---------------------------------------------------------------------------
# 1. A campaign whose only check was never configured completes
# ---------------------------------------------------------------------------
def test_a_campaign_whose_only_check_was_never_configured_completes(sb, monkeypatch):
    """The row is skipped, and the campaign is not read as a broken video."""
    script_result_id = _write_result(
        sb, monkeypatch, success=False, metadata=_not_configured_metadata()
    )
    _seed_campaign(sb, monkeypatch, 'campaign-not-configured', [script_result_id])

    campaign_db.reconcile_stale_campaign_executions(TEAM_ID)

    row = sb.get_table('script_results')[0]
    campaign = sb.get_table('campaign_executions')[0]
    assert row.get('skipped') is True, 'the never-configured row is not marked as skipped'
    assert campaign['status'] == 'completed', f"the campaign status is {campaign['status']!r}"
    assert campaign['success'] is True, f"the campaign success is {campaign['success']!r}"


# ---------------------------------------------------------------------------
# 2. A genuinely failed row still fails its campaign
# ---------------------------------------------------------------------------
def test_a_genuinely_failed_row_still_fails_the_campaign(sb, monkeypatch):
    """A video that never played is a failure, and it stays one."""
    script_result_id = _write_result(
        sb, monkeypatch, success=False, metadata=_failed_playback_metadata()
    )
    _seed_campaign(sb, monkeypatch, 'campaign-broken-video', [script_result_id])

    campaign_db.reconcile_stale_campaign_executions(TEAM_ID)

    row = sb.get_table('script_results')[0]
    campaign = sb.get_table('campaign_executions')[0]
    assert row.get('skipped') is False, 'a configured run that failed must not be marked skipped'
    assert campaign['status'] == 'failed', f"the campaign status is {campaign['status']!r}"
    assert campaign['success'] is False, f"the campaign success is {campaign['success']!r}"


# ---------------------------------------------------------------------------
# 3. One passed row + one skipped row -> completed
# ---------------------------------------------------------------------------
def test_a_campaign_with_one_passed_and_one_skipped_row_completes(sb, monkeypatch):
    passed_id = _write_result(sb, monkeypatch, success=True, metadata=None)
    skipped_id = _write_result(
        sb, monkeypatch, success=False, metadata=_not_configured_metadata()
    )
    _seed_campaign(sb, monkeypatch, 'campaign-mixed', [passed_id, skipped_id])

    campaign_db.reconcile_stale_campaign_executions(TEAM_ID)

    campaign = sb.get_table('campaign_executions')[0]
    assert campaign['status'] == 'completed', f"the campaign status is {campaign['status']!r}"
    assert campaign['success'] is True, f"the campaign success is {campaign['success']!r}"


# ---------------------------------------------------------------------------
# 4. The writer records the flag, and only the flag it should
# ---------------------------------------------------------------------------
def test_a_configured_run_that_failed_is_written_as_not_skipped(sb, monkeypatch):
    _write_result(sb, monkeypatch, success=False, metadata=_failed_playback_metadata())

    row = sb.get_table('script_results')[0]
    assert row.get('skipped') is False, 'a configured run that failed must not be marked skipped'


def test_a_successful_run_is_never_skipped(sb, monkeypatch):
    _write_result(sb, monkeypatch, success=True, metadata=None)

    row = sb.get_table('script_results')[0]
    assert row.get('skipped') is False, 'a run that succeeded must not be marked skipped'


def test_a_never_configured_run_is_written_as_skipped(sb, monkeypatch):
    _write_result(sb, monkeypatch, success=False, metadata=_not_configured_metadata())

    row = sb.get_table('script_results')[0]
    assert row.get('skipped') is True, 'the never-configured row is not marked as skipped'


def test_the_flag_comes_from_the_run_outcome_and_not_from_the_error_text():
    """The signal is the run's own outcome metadata, never the wording."""
    assert derive_skipped is not None, 'the skipped derivation is missing'
    assert derive_skipped(False, {'status': 'not_configured'}) is True
    assert derive_skipped(False, {'outcome': 'not_configured'}) is True
    assert derive_skipped(False, {'counts_as_playback_failure': False}) is True
    # A run that was configured and then failed is not a skip.
    assert derive_skipped(False, {'status': 'playback_failed'}) is False
    assert derive_skipped(False, {'outcome': 'playback_failed'}) is False
    # The error text alone decides nothing.
    assert derive_skipped(
        False, {'error_msg': 'the check is not configured: missing --email'}
    ) is False
    # A run that succeeded is never skipped.
    assert derive_skipped(True, {'status': 'not_configured'}) is False


def test_a_real_failure_verdict_is_not_treated_as_not_configured():
    """The verdict the shared builder produces for a broken video is a failure."""
    verdict = build_playback_verdict()
    assert verdict['outcome'] == 'playback_failed'
    assert derive_skipped is not None, 'the skipped derivation is missing'
    assert derive_skipped(False, verdict) is False


# ---------------------------------------------------------------------------
# 5. The field reaches the nightly poller
# ---------------------------------------------------------------------------
def test_the_nightly_poller_counts_a_skipped_row_as_skipped_not_failed(
    sb, monkeypatch, capsys, tmp_path
):
    """The poller's own counting, over a payload that can finally carry the field."""
    _write_result(sb, monkeypatch, success=False, metadata=_not_configured_metadata())
    _write_result(sb, monkeypatch, success=False, metadata=_failed_playback_metadata())

    # The payload the route actually serves: its slim column set decides what
    # the poller can even see.
    columns = _route_script_columns(monkeypatch)
    rows = sb.table('script_results').select(columns).execute().data
    payload = [{
        'campaign_name': 'nightly_video_check',
        'status': 'completed',
        'success': False,
        'started_at': '2026-10-24T20:00:00+00:00',
        'execution_time_ms': 4200,
        'script_results': rows,
    }]

    poller = _load_poller()
    monkeypatch.setattr(poller, 'http_get', lambda base, path, params, token: (200, payload))
    monkeypatch.setattr(sys, 'argv', [
        'poll_results.py',
        '--team-id', TEAM_ID,
        '--auto-signed', 'not-a-real-token',
        '--out-dir', str(tmp_path),
        '--interval', '1',
        '--deadline', '30',
    ])
    poller.main()

    out = capsys.readouterr().out
    assert 'pass=0 fail=1 skip=1' in out, (
        'the poller did not count the skipped row as skipped:\n' + out
    )


# ---------------------------------------------------------------------------
# 6. The migration is additive and idempotent
# ---------------------------------------------------------------------------
def _strip_sql_comments(sql):
    sql = re.sub(r'--[^\n]*', '', sql)
    return re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)


def test_the_migration_adds_the_column_and_changes_nothing_else():
    assert MIGRATION_PATH.is_file(), 'the skipped column migration is missing'
    body = _strip_sql_comments(MIGRATION_PATH.read_text())
    assert re.search(
        r'ALTER\s+TABLE\s+(?:public\.)?script_results\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+'
        r"skipped\s+boolean\s+NOT\s+NULL\s+DEFAULT\s+false",
        body,
        re.IGNORECASE,
    ), 'the migration does not add the column the way it must:\n' + body
    upper = body.upper()
    for forbidden in ('DROP ', 'ALTER TYPE', 'UPDATE ', 'DELETE ', 'TRUNCATE '):
        assert forbidden not in upper, f'the migration contains a forbidden statement: {forbidden}'


def test_the_migration_is_idempotent_and_keeps_the_existing_rows():
    from tests._supabase_mock import SupabaseMock, apply_migration_sql

    assert MIGRATION_PATH.is_file(), 'the skipped column migration is missing'
    sql = MIGRATION_PATH.read_text()
    client = SupabaseMock({
        'script_results': [{'id': 'row-1', 'script_name': 'web/netflix_video_check.py',
                            'success': False, 'execution_time_ms': 1000}],
    })

    first = apply_migration_sql(client, sql)
    assert ('script_results', 'skipped') in first['columns_added']
    after_first = [dict(row) for row in client.get_table('script_results')]

    second = apply_migration_sql(client, sql)
    after_second = [dict(row) for row in client.get_table('script_results')]

    assert after_first == after_second, 'applying the migration twice changed the table'
    assert after_second[0]['success'] is False, 'the migration rewrote an existing row'
    assert after_second[0]['id'] == 'row-1'
    assert after_second[0]['script_name'] == 'web/netflix_video_check.py'


def test_a_fresh_database_gets_the_column_from_the_schema():
    text = SCHEMA_PATH.read_text()
    assert re.search(
        r"skipped\s+boolean\s+NOT\s+NULL\s+DEFAULT\s+false", text
    ), 'the fresh schema does not create the skipped column'
