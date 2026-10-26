"""A failed artifact upload must say why (BUG-0770).

labox-backend produced "No Report" / "No Logs" rows for every run because its
storage credentials were stale: each boto3 call was rejected with
``InvalidAccessKeyId``. The run row carried no trace of it -- the error was
printed on the host and thrown away -- so a green run with no report looked
exactly like a run that never had one.

These tests pin the two places the reason now survives:
  * the verification review pack ("Artifact upload failed: ...")
  * the run metadata (``artifact_upload_error``)
"""

import importlib
import os
import sys

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

script_executor_mod = importlib.import_module('shared.src.lib.executors.script_executor')
ScriptExecutor = script_executor_mod.ScriptExecutor
ScriptExecutionContext = script_executor_mod.ScriptExecutionContext

UPLOAD_ERROR = (
    "An error occurred (InvalidAccessKeyId) when calling the PutObject operation: "
    "The Access Key Id you provided does not exist in our records."
)


@pytest.fixture
def executor():
    return ScriptExecutor('TC_UPLOAD')


@pytest.fixture
def context():
    ctx = ScriptExecutionContext('TC_UPLOAD')
    ctx.overall_success = True
    return ctx


def test_review_pack_names_the_upload_failure(executor, context):
    markdown = executor._build_verification_review_markdown(
        context,
        {'success': False, 'report_url': '', 'logs_url': '', 'error': UPLOAD_ERROR},
        1234,
    )

    assert 'Artifact upload failed' in markdown
    assert 'InvalidAccessKeyId' in markdown


def test_review_pack_stays_quiet_when_the_upload_worked(executor, context):
    markdown = executor._build_verification_review_markdown(
        context,
        {
            'success': True,
            'report_url': 'https://storage/report.html',
            'logs_url': 'https://storage/execution.txt',
        },
        1234,
    )

    assert 'Artifact upload failed' not in markdown


def test_metadata_carries_the_upload_failure(executor, context):
    merged = executor._build_final_metadata_with_review(
        context,
        {'success': False, 'report_url': '', 'logs_url': '', 'error': UPLOAD_ERROR},
        1234,
    )

    expected = 'InvalidAccessKeyId: storage key rejected'
    assert merged['artifact_upload_error'] == expected
    assert merged['verification_review']['artifact_upload_error'] == expected


def test_metadata_has_no_upload_error_when_the_upload_worked(executor, context):
    merged = executor._build_final_metadata_with_review(
        context,
        {
            'success': True,
            'report_url': 'https://storage/report.html',
            'logs_url': 'https://storage/execution.txt',
        },
        1234,
    )

    assert 'artifact_upload_error' not in merged
    assert 'artifact_upload_error' not in merged['verification_review']


def test_report_generation_keeps_the_upload_error(monkeypatch):
    """generate_and_upload_script_report must not drop the reason on the floor."""
    report_generation_utils = importlib.import_module('shared.src.lib.utils.report_generation_utils')
    cloudflare_utils = importlib.import_module('shared.src.lib.utils.cloudflare_utils')

    # The storage client is a singleton built from the environment; give it
    # enough to construct and start from scratch.
    monkeypatch.setenv('MINIO_ENDPOINT', 'http://localhost:9000')
    monkeypatch.setenv('MINIO_ACCESS_KEY', 'test-access-key')
    monkeypatch.setenv('MINIO_SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('MINIO_BUCKET', 'virtualpytest')
    monkeypatch.setattr(cloudflare_utils.CloudflareUtils, '_instance', None)
    monkeypatch.setattr(cloudflare_utils.CloudflareUtils, '_initialized', False)

    def failed_upload(*args, **kwargs):
        return {'success': False, 'error': UPLOAD_ERROR}

    monkeypatch.setattr(cloudflare_utils, 'upload_script_report', failed_upload)

    result = report_generation_utils.generate_and_upload_script_report(
        script_name='x.py',
        device_info={'device_model': 'host_vnc'},
        host_info={},
        execution_time=1234,
        success=True,
    )

    assert result['success'] is False
    assert result['error'] == UPLOAD_ERROR
    assert result['report_url'] == ''


def test_report_generation_keeps_the_exception(monkeypatch):
    """An exception during generation must also reach the caller as an error."""
    report_generation_utils = importlib.import_module('shared.src.lib.utils.report_generation_utils')
    cloudflare_utils = importlib.import_module('shared.src.lib.utils.cloudflare_utils')

    monkeypatch.setenv('MINIO_ENDPOINT', 'http://localhost:9000')
    monkeypatch.setenv('MINIO_ACCESS_KEY', 'test-access-key')
    monkeypatch.setenv('MINIO_SECRET_KEY', 'test-secret-key')
    monkeypatch.setenv('MINIO_BUCKET', 'virtualpytest')
    monkeypatch.setattr(cloudflare_utils.CloudflareUtils, '_instance', None)
    monkeypatch.setattr(cloudflare_utils.CloudflareUtils, '_initialized', False)

    def boom(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(cloudflare_utils, 'upload_script_report', boom)

    result = report_generation_utils.generate_and_upload_script_report(
        script_name='x.py',
        device_info={'device_model': 'host_vnc'},
        host_info={},
        execution_time=1234,
        success=True,
    )

    assert result['success'] is False
    assert 'boom' in (result.get('error') or '')


def test_upload_error_text_has_no_url_path_or_backtick():
    from shared.src.lib.utils.upload_error_utils import sanitize_upload_error
    raw = ("An error occurred (InvalidAccessKeyId) when calling PutObject at "
           "http://192.168.1.50:9000/bucket/script-reports/host/run/report.html "
           "key `/opt/app/.env` " + 'x' * 500)
    out = sanitize_upload_error(raw)
    assert out == 'InvalidAccessKeyId: storage key rejected'
    for bad in ('192.168', 'http', '/opt', '`', 'bucket'):
        assert bad not in out
    assert len(sanitize_upload_error('(Weird) ' + 'y' * 900)) <= 200
    assert sanitize_upload_error('') == ''
    assert '`' not in sanitize_upload_error('boom `x`')


def test_review_pack_never_prints_the_raw_error(executor, context):
    markdown = executor._build_verification_review_markdown(
        context,
        {'success': False, 'report_url': '', 'logs_url': '',
         'error': 'refused (AccessDenied) at http://192.168.1.50:9000/b/k'},
        1,
    )
    assert 'AccessDenied: storage key rejected' in markdown
    assert '192.168' not in markdown
