from types import SimpleNamespace

from backend_host.src.controllers.verification.video_verification_helpers import VideoVerificationHelpers


class _AV:
    def __init__(self, state):
        self.state = state

    def get_signal_state(self):
        return self.state


def _run(state, **params):
    helpers = VideoVerificationHelpers(SimpleNamespace(av_controller=_AV(state)))
    return helpers.execute_verification_workflow({'command': 'IsStandby', 'params': {'timeout': 0, **params}})


def test_standby_passes_when_no_hdmi_signal():
    r = _run({'standby': True, 'signal': False, 'source': 'hdmi_hid'})
    assert r['success'] and r['details']['source'] == 'hdmi_hid'


def test_awake_box_fails_is_standby_and_passes_awake():
    awake = {'standby': False, 'signal': True, 'source': 'hdmi_hid'}
    assert not _run(awake)['success']
    assert _run(awake, awake=True)['success']


def test_unknown_state_is_an_error_not_a_pass():
    r = _run({'standby': None, 'signal': None, 'source': None})
    assert not r['success'] and 'Cannot tell' in r['message']
