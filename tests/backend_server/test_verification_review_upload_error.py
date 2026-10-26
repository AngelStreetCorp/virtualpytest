"""The review pack must say WHY a run has no report (BUG-0770).

A host whose storage credentials are wrong cannot upload the report, the logs
or its own review pack. The reader then gets the server's fallback pack, and
that pack used to say only `report_url: n/a` — a missing report looked like a
missing test. The host keeps the reason in the run metadata
(`artifact_upload_error`); the fallback pack must say it too.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

pytestmark = pytest.mark.unit

UPLOAD_ERROR = (
    'An error occurred (InvalidAccessKeyId) when calling the PutObject operation: '
    'The Access Key Id you provided does not exist in our records.'
)


@pytest.fixture
def route(monkeypatch):
    try:
        from backend_server.src.routes import server_script_results_routes as mod
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f'server deps not installed: {exc}')

    state = {'record': None, 'storage': {'success': False, 'error': 'not found'}}

    monkeypatch.setattr(mod, 'check_supabase', lambda: None)
    monkeypatch.setattr(mod, 'get_script_by_id', lambda _id: state['record'])
    monkeypatch.setattr(mod, 'fetch_text_from_storage', lambda _src: state['storage'])
    return mod, state


def _markdown(route, record, team_id='team-1'):
    mod, state = route
    state['record'] = record
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context(
        f'/server/script-results/getVerificationReviewMarkdown/{record["id"]}?team_id={team_id}'
    ):
        response = mod.get_verification_review_markdown_route(record['id'])
        return response.get_json()['markdown']


def test_the_fallback_pack_says_the_upload_failed(route):
    markdown = _markdown(route, {
        'id': 'res-1',
        'team_id': 'team-1',
        'script_name': 'av_check',
        'success': False,
        'execution_time_ms': 1302,
        'html_report_r2_url': None,
        'logs_r2_url': None,
        'metadata': {'artifact_upload_error': UPLOAD_ERROR},
    })

    assert 'Artifact upload failed' in markdown
    assert 'InvalidAccessKeyId' in markdown
    assert 'report_url: n/a' in markdown


def test_the_fallback_pack_reads_the_error_from_the_verification_review_block(route):
    markdown = _markdown(route, {
        'id': 'res-1',
        'team_id': 'team-1',
        'script_name': 'av_check',
        'success': False,
        'execution_time_ms': 1302,
        'html_report_r2_url': None,
        'logs_r2_url': None,
        'metadata': {'verification_review': {'artifact_upload_error': UPLOAD_ERROR}},
    })

    assert 'Artifact upload failed' in markdown
    assert 'InvalidAccessKeyId' in markdown


def test_a_run_without_an_upload_error_reads_as_before(route):
    markdown = _markdown(route, {
        'id': 'res-1',
        'team_id': 'team-1',
        'script_name': 'av_check',
        'success': False,
        'execution_time_ms': 1302,
        'html_report_r2_url': None,
        'logs_r2_url': None,
        'metadata': {},
    })

    assert 'Artifact upload failed' not in markdown
    assert 'report_url: n/a' in markdown


def test_a_run_that_has_a_report_does_not_claim_an_upload_failure(route):
    markdown = _markdown(route, {
        'id': 'res-1',
        'team_id': 'team-1',
        'script_name': 'av_check',
        'success': True,
        'execution_time_ms': 1302,
        'html_report_r2_url': 'https://storage.example/report.html',
        'logs_r2_url': 'https://storage.example/logs.txt',
        'metadata': {'artifact_upload_error': UPLOAD_ERROR},
    })

    assert 'Artifact upload failed' not in markdown
    assert 'https://storage.example/report.html' in markdown


def test_the_fallback_pack_sanitizes_an_old_raw_error(route):
    markdown = _markdown(route, {
        'id': 'res-1', 'team_id': 'team-1', 'script_name': 'av_check', 'success': False,
        'execution_time_ms': 1, 'html_report_r2_url': None, 'logs_r2_url': None,
        'metadata': {'artifact_upload_error': 'x (InvalidAccessKeyId) http://192.168.1.50:9000/b/k `t`'},
    })
    assert 'InvalidAccessKeyId: storage key rejected' in markdown
    assert '192.168' not in markdown
