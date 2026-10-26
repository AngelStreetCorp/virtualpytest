"""Blackscreen / no_signal must replace a stale live motion dict (vpt-mf1 stbv1)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor.analyzers.tv_app import TvAppAnalyzer  # noqa: E402

STALE_LIVE = {'kind': 'full', 'pct': 81.3, 'cells': 16, 'rows': 4, 'cols': 4, 'raw_state': 'live', 'state': 'ui'}


def _analyzer():
    a = TvAppAnalyzer(core=None)
    a._last_motion['device2'] = dict(STALE_LIVE)
    a._motion_gate['device2'] = {'shown': 'live', 'cand': 'live', 'n': 0}
    return a


def test_fuse_blackscreen_clears_stale_live_when_motion_missing():
    a = _analyzer()
    data = {'blackscreen': True, 'blackscreen_percentage': 100.0, 'no_signal': False}
    a._fuse_motion_state('device2', data)
    motion = data['motion']
    assert motion['state'] == 'blackscreen' and motion['kind'] == 'static' and motion['pct'] == 0.0
    assert a._last_motion['device2']['state'] == 'blackscreen'
    assert STALE_LIVE['kind'] == 'full'  # original cache copy was not mutated in place


def test_fuse_no_signal_outranks_blackscreen_flag():
    a = _analyzer()
    data = {'blackscreen': True, 'no_signal': True, 'motion': dict(STALE_LIVE)}
    a._fuse_motion_state('device2', data)
    assert data['motion']['state'] == 'no_signal' and data['motion']['kind'] == 'static'
