"""The auto_proxy catch-all must not blame a device parameter for an endpoint that is not a route.

The catch-all answers for every `/server/*` path that matched no blueprint, so a caller with a
wrong path lands there too — and the host helper's reply, "host_name required", names a device
parameter. That misdirection is what made BUG-0507 hard to diagnose: a GitLab route whose project
carried an encoded slash matched no route, fell into the catch-all, and answered a question about
device hosts while the page showed an empty repository.

The message lives in `lib/utils/unmatched_endpoint.py`, which imports nothing, so this runs in the
unit-test job with no Flask and no backend. Testing it through the Flask app instead would mean
importing the whole server (anthropic, supabase, …) and the test would skip in every CI run that
lacks those — i.e. never guard anything.
"""
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[2] / 'backend_server/src/lib/utils/unmatched_endpoint.py'
_spec = importlib.util.spec_from_file_location('unmatched_endpoint', _PATH)
ue = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ue)

MISSING_HOST = 'host_name required in request body or query parameters'


def test_names_the_path_that_matched_no_route():
    out = ue.explain_unmatched_endpoint(
        'gitlab/projects/root%2Fdemo/tree',
        {'success': False, 'error': MISSING_HOST}, 400)

    assert out['success'] is False
    # The headline is the real problem, not the device parameter.
    assert not out['error'].startswith('host_name required')
    assert 'No /server route matched /server/gitlab/projects/root%2Fdemo/tree' in out['error']
    # Both readings stay on the table: the catch-all cannot tell them apart.
    assert 'host_name' in out['error']
    # Machine-readable, so a caller branches on it instead of parsing prose.
    assert out['unmatched_endpoint'] == '/server/gitlab/projects/root%2Fdemo/tree'
    assert out[ue.FALLBACK_FLAG] is True


def test_keeps_the_original_reason_for_the_device_reading():
    out = ue.explain_unmatched_endpoint('actions/run', {'success': False, 'error': MISSING_HOST}, 400)
    assert MISSING_HOST in out['error']


def test_a_different_400_is_left_exactly_as_it_was():
    original = {'success': False, 'error': 'targets is required'}
    out = ue.explain_unmatched_endpoint('actions/run', original, 400)
    assert out == original
    assert ue.FALLBACK_FLAG not in out


def test_a_success_is_untouched():
    original = {'success': True, 'stream_url': 'http://host/stream'}
    assert ue.explain_unmatched_endpoint('av/getStreamUrl', original, 200) == original


def test_a_502_is_untouched():
    # A host that did not answer is not a "wrong path", and must not be relabelled as one.
    original = {'success': False, 'error': 'host unreachable'}
    assert ue.explain_unmatched_endpoint('actions/run', original, 502) == original


def test_a_non_dict_payload_is_untouched():
    assert ue.explain_unmatched_endpoint('actions/run', 'boom', 400) == 'boom'


def test_the_caller_payload_is_not_mutated():
    original = {'success': False, 'error': MISSING_HOST}
    ue.explain_unmatched_endpoint('actions/run', original, 400)
    assert original == {'success': False, 'error': MISSING_HOST}


def test_unchanged_results_are_the_same_object():
    """auto_proxy decides whether to log a warning with `is not`, so "unchanged" has to mean
    identity, not just equal value. Returning a copy would silence the log line — which is the
    signal that a feature's requests are being forwarded to a host that never heard of them."""
    payload = {'success': False, 'error': 'targets is required'}
    assert ue.explain_unmatched_endpoint('actions/run', payload, 400) is payload
    assert ue.explain_unmatched_endpoint('actions/run', payload, 502) is payload
    assert ue.explain_unmatched_endpoint('actions/run', 'raw', 400) is not None
    assert ue.explain_unmatched_endpoint('actions/run', payload, 400) is not None


def test_a_rewritten_result_is_a_different_object():
    payload = {'success': False, 'error': MISSING_HOST}
    assert ue.explain_unmatched_endpoint('actions/run', payload, 400) is not payload