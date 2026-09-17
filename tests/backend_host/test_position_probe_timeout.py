"""
tests/backend_host/test_position_probe_timeout.py — the cap applied to a node's verifications
when NavigationExecutor asks "where am I?".

Both pre-flight probes (am I at the target? am I at home?) used to honour the node's own
verification timeouts, which are sized for "wait for this screen to appear after we acted on
it" rather than "is it showing right now". On youtube-android-mobile that was 60s for the
target plus 20s+20s for home — 101 seconds of a 139-second run before the first command
reached the phone.

The trap the cap has to survive: `timeout` is MILLISECONDS for every verification type except
`video`, whose helpers read it as seconds. Capping generically without knowing that turns a 60s
video wait into 60ms.
"""
import importlib

import pytest

verification_executor = importlib.import_module(
    'backend_host.src.services.verifications.verification_executor')
VerificationExecutor = verification_executor.VerificationExecutor
cap = VerificationExecutor._capped_verifications

CAP_MS = 5000


def test_millisecond_types_are_capped_in_milliseconds():
    out = cap([{'verification_type': 'adb', 'command': 'waitForElementToAppear',
                'params': {'search_term': 'Subscriptions', 'timeout': 20000}}], CAP_MS)
    assert out[0]['params']['timeout'] == 5000


def test_video_is_capped_in_seconds_not_milliseconds():
    """The whole point of the type table: 5000 here would be 5000 SECONDS."""
    out = cap([{'verification_type': 'video', 'command': 'WaitForVideoToAppear',
                'params': {'motion_threshold': 3.0, 'duration': 3.0, 'timeout': 60}}], CAP_MS)
    assert out[0]['params']['timeout'] == 5.0


def test_a_timeout_already_shorter_than_the_cap_is_left_alone():
    out = cap([{'verification_type': 'adb', 'params': {'timeout': 1500}}], CAP_MS)
    assert out[0]['params']['timeout'] == 1500
    out = cap([{'verification_type': 'video', 'params': {'timeout': 2}}], CAP_MS)
    assert out[0]['params']['timeout'] == 2


@pytest.mark.parametrize('params', [{}, {'timeout': None}, {'timeout': 'soon'}])
def test_a_missing_or_unusable_timeout_gets_the_cap(params):
    """No timeout at all means each controller's own default, which can be longer than the cap."""
    out = cap([{'verification_type': 'adb', 'params': dict(params)}], CAP_MS)
    assert out[0]['params']['timeout'] == 5000


def test_a_verification_with_no_params_key_still_gets_one():
    out = cap([{'verification_type': 'text', 'command': 'waitForTextToAppear'}], CAP_MS)
    assert out[0]['params']['timeout'] == 5000


def test_the_nodes_own_verifications_are_never_mutated():
    """These dicts come out of the cached unified graph. Writing to them would shorten the
    node's real verifications for the rest of the run — and for every later run that reads the
    same cache entry."""
    original = [{'verification_type': 'video', 'params': {'timeout': 60, 'duration': 3.0}}]
    out = cap(original, CAP_MS)
    assert original[0]['params']['timeout'] == 60, 'the source was modified in place'
    assert out[0]['params']['timeout'] == 5.0
    assert out[0]['params'] is not original[0]['params']


def test_several_verifications_are_capped_independently():
    out = cap([
        {'verification_type': 'adb', 'params': {'timeout': 20000}},
        {'verification_type': 'video', 'params': {'timeout': 60}},
        {'verification_type': 'image', 'params': {'timeout': 800}},
    ], CAP_MS)
    assert [v['params']['timeout'] for v in out] == [5000, 5.0, 800]
