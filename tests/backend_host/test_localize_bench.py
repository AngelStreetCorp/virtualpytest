"""TASK-107 goal 1: the benchmark's synthetic labels are what the cascade's detectors read, and
scoring follows each sample's label."""
import importlib
import sys

import numpy as np
import pytest

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'localize'))
bench = importlib.import_module('bench')
ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')
ssc = importlib.import_module('shared.src.lib.ai.screen_state_cv')

pytestmark = pytest.mark.unit
H = ih.ImageHelpers(None, None)


def test_synthetic_signal_frames_are_signal_states():
    assert H.classify_special_state(bench._black(1)) == 'blackscreen'
    assert H.classify_special_state(bench._bars()) == 'no_signal'


def test_synthetic_popup_reads_as_a_popup():
    rng = np.random.default_rng(3)
    page = np.full((720, 1280, 3), 70, dtype=np.uint8)
    for _ in range(60):
        x, y = int(rng.integers(0, 1200)), int(rng.integers(0, 660))
        page[y:y + 40, x:x + 120] = int(rng.integers(90, 250))
    assert ssc.overlay_plate(bench._popup(page))[0] == 'popup'


def test_scoring():
    assert bench.correct({'kind': 'node', 'expect_node': 'a'}, {'kind': 'node', 'node_id': 'a'})
    assert not bench.correct({'kind': 'node', 'expect_node': 'a'}, {'kind': 'node', 'node_id': 'b'})
    assert bench.correct({'kind': 'unknown', 'expect_not_node': 'a'}, {'kind': 'node', 'node_id': 'b'})
    assert not bench.correct({'kind': 'unknown', 'expect_not_node': 'a'}, {'kind': 'node', 'node_id': 'a'})
    assert bench.correct({'kind': 'live'}, {'kind': 'live', 'node_id': None})
    assert not bench.correct({'kind': 'unknown'}, {'kind': 'known_screen'})
    # a node whose screenshot is the same picture as another node's: either is right
    assert bench.correct({'kind': 'node', 'expect_node': 'a', 'same_pixels': ['b']}, {'kind': 'node', 'node_id': 'b'})
    # a foreign frame the screen memory knows: not this tree's screen, seen before (TASK-110 §7)
    assert bench.correct({'kind': 'unknown', 'source': 'foreign_ui'}, {'kind': 'known_screen'})
    assert not bench.correct({'kind': 'unknown', 'source': 'foreign_ui'}, {'kind': 'node', 'node_id': 'a'})


audit = importlib.import_module('audit')


def _cov(name, models, screens, fp, ident=0, live=None, age=None):
    return {'userinterface_name': name, 'models': models, 'screens': screens, 'fingerprinted': fp,
            'identity': ident, 'live_node': live, 'fingerprint_age_days': {'median': age} if age is not None else None}


def test_audit_flags():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)
    cov = [_cov('acc-stb4', ['stb'], 30, 0), _cov('stb-testop', ['stb'], 68, 65, live={'label': 'live'}, age=120),
           _cov('youtube-web', ['web'], 4, 4, age=10), _cov('phone_home', ['android_mobile'], 3, 2, ident=2, age=0),
           _cov('empty', ['stb'], 0, 0)]
    runs = [{'ran_at': '2026-10-14T03:40:00+00:00', 'accuracy': 52.4, 'per_kind': {'node': {'pct': 40.0}, 'live': {'pct': 75.0}}},
            {'ran_at': '2026-10-15T03:40:00+00:00', 'accuracy': 50.0, 'per_kind': {'node': {'pct': 33.2}, 'live': {'pct': 75.0}}}]
    flags = audit.flags_for(cov, runs, stale_days=90, drop=3, now=now)
    kinds = sorted(f.split()[0] + ' ' + f.split()[1].rstrip(':') for f in flags)
    assert kinds == ['NO_IDENTITY youtube-web', 'NO_LIVE acc-stb4', 'REGRESSION node', 'STALE stb-testop', 'ZERO acc-stb4']
    assert audit.flags_for(cov[1:2], runs[:1], 200, 3, now=datetime(2026, 10, 20, tzinfo=timezone.utc)) == \
        ['BENCH_OLD latest bench run 2026-10-14T03:40:00+00:00 (> 36 h): check vpt-localize-bench.timer']


def test_audit_flags_tier2_gap_and_overlay_fp():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)
    run = {'ran_at': '2026-10-15T03:40:00+00:00', 'accuracy': 52.4, 'per_kind': {},
           'tier2': {'gaps_open': {'overlay_over_firing': ['exp01_broadcast_b=tooltip']}},
           'overlay': {'fp_pct': 2.7, 'verdict_fp_pct': 0.4}}
    flags = audit.flags_for([], [run], 90, 3, now=now)
    assert flags[0].startswith('TIER2_GAP overlay_over_firing') and flags[1].startswith('OVERLAY_FP')
    run['tier2'] = {'gaps_open': {}}
    run['overlay'] = {'fp_pct': 2.7, 'verdict_fp_pct': 0.0}
    assert audit.flags_for([], [run], 90, 3, now=now) == []
