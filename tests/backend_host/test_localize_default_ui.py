"""A device with no userinterface gets Localize's default tree-less one (screen memory names its still frames)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import monitor_localize as ml  # noqa: E402
import shared.src.lib.database.screen_fingerprints_bump  # noqa: E402,F401  (imported before a test patches Thread)
import shared.src.lib.database.screen_fingerprints_db  # noqa: E402,F401


def test_no_userinterface_resolves_to_the_default(monkeypatch):
    monkeypatch.delenv('DEVICE2_USERINTERFACE', raising=False)
    monkeypatch.delenv('HOST_USERINTERFACE', raising=False)
    m = ml.MonitorLocalizer()
    assert m._resolve_ui('device2') == (ml.NO_TREE, 'base')
    assert m._resolve_ui('host') == (ml.NO_TREE, 'base')


def test_a_configured_userinterface_wins(monkeypatch):
    monkeypatch.setenv('DEVICE3_USERINTERFACE', 'stb-testop')
    monkeypatch.setenv('DEVICE3_VARIANT', 'v2')
    assert ml.MonitorLocalizer()._resolve_ui('device3') == ('stb-testop', 'v2')


def test_device5_and_up_arrive_as_their_capture_folder(monkeypatch):
    monkeypatch.setenv('DEVICE5_USERINTERFACE', 'android_tv_ui')
    monkeypatch.setattr('shared.src.lib.utils.storage_path_utils.get_device_info_from_capture_folder',
                        lambda folder: {'device_id': folder, 'device_index': 5})
    assert ml.MonitorLocalizer()._resolve_ui('capture5') == ('android_tv_ui', 'base')


def test_a_screen_flipping_between_two_rows_counts_once_per_window(monkeypatch):
    """Two near-identical rows of one frozen screen: the matcher alternates, each row is counted once per window."""
    import threading
    bumps = []
    monkeypatch.setattr(threading, 'Thread', lambda target, kwargs, daemon: type('T', (), {'start': lambda self: bumps.append(kwargs['screen_id'])})())
    m = ml.MonitorLocalizer()
    for sid in ('a', 'b') * 50:
        m._track_screen('capture5', 'h/capture5', {'kind': 'known_screen', 'evidence': {'screen_id': sid, 'verdict': 'unknown'}})
    assert bumps == ['a', 'b']


def test_an_unknown_picture_is_registered_once_after_it_settles(monkeypatch):
    """TASK-159: 3 consecutive ticks on one unknown picture register it once; a 10-minute freeze stays one registration."""
    import numpy as np
    import threading
    started = []
    monkeypatch.setattr(threading, 'Thread', lambda target, args=(), kwargs=None, daemon=None:
                        type('T', (), {'start': lambda self: started.append(target.__name__)})())
    img = (np.random.RandomState(7).rand(180, 320, 3) * 255).astype('uint8')
    clock = [1000.0]
    monkeypatch.setattr(ml.time, 'monotonic', lambda: clock[0])
    m = ml.MonitorLocalizer()
    unknown = {'kind': 'unknown', 'evidence': {}}
    m._track_screen('device3', 'h/device3', unknown, img)
    clock[0] += 2
    m._track_screen('device3', 'h/device3', unknown, img)
    assert started == []
    for _ in range(600):   # a frozen picture re-read for 10 minutes
        clock[0] += 1
        m._track_screen('device3', 'h/device3', unknown, img)
    assert started == ['_register_unknown']


def test_a_known_screen_counts_one_sighting_per_transition(monkeypatch):
    import threading
    bumps = []
    monkeypatch.setattr(threading, 'Thread', lambda target, kwargs, daemon: type('T', (), {'start': lambda self: bumps.append(kwargs['screen_id'])})())
    m = ml.MonitorLocalizer()
    known = {'kind': 'known_screen', 'evidence': {'screen_id': 'a', 'verdict': 'unknown'}}
    for _ in range(100):
        m._track_screen('device3', 'h/device3', known, None)
    assert bumps == ['a']


def test_registry_bookkeeping_failure_keeps_the_verdict(monkeypatch):
    """BLOCK 2: an exception in the registry step must not cost the frame its Localize verdict."""
    import shared.src.lib.utils.localize_verdict as lv
    m = ml.MonitorLocalizer()
    verdict = {'kind': 'unknown', 'evidence': {}}
    monkeypatch.setattr(lv, 'after_match', lambda *a, **k: verdict)
    monkeypatch.setattr(ml, 'after_match', lambda *a, **k: verdict)
    monkeypatch.setattr(m, '_track_screen', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('db down')))
    monkeypatch.setattr('shared.src.lib.database.screen_fingerprints_db.known_screen_lookup', lambda t, s: None)
    assert m._after_match({'kind': 'unknown'}, None, [], None, 'device3') is verdict


def test_new_unknown_rows_are_budgeted_per_device(monkeypatch):
    import numpy as np
    import threading
    started = []
    monkeypatch.setattr(threading, 'Thread', lambda target, args=(), kwargs=None, daemon=None:
                        type('T', (), {'start': lambda self: started.append(1)})())
    clock = [1000.0]
    monkeypatch.setattr(ml.time, 'monotonic', lambda: clock[0])
    m = ml.MonitorLocalizer()
    unknown = {'kind': 'unknown', 'evidence': {}}
    for seed in range(30):   # 30 different settled pictures within the hour
        img = (np.random.RandomState(seed).rand(180, 320, 3) * 255).astype('uint8')
        m._registering.clear()
        m._track_screen('device3', 'h/device3', unknown, img)
        clock[0] += m.SETTLE_SECONDS + 1
        m._track_screen('device3', 'h/device3', unknown, img)
    assert len(started) == m.MAX_NEW_PER_HOUR


def test_the_thread_leaves_its_id_in_the_mailbox_and_the_loop_applies_it(monkeypatch):
    import shared.src.lib.database.screen_fingerprints_db as sdb
    m = ml.MonitorLocalizer()
    monkeypatch.setattr(sdb, 'register_screen', lambda *a, **k: {'id': 'new', 'label': 'unknown_1', 'is_new': True})
    m._registering['device3'] = True
    m._register_unknown('device3', 'h/device3', {'dhash': 'a', 'region_center': 'b'}, None)
    assert m._on_screen.get('device3') is None and m._reg_result['device3'] == 'new'   # the thread wrote no episode state
    m._track_screen('device3', 'h/device3', {'kind': 'known_screen', 'evidence': {'screen_id': 'new', 'verdict': 'unknown'}}, None)
    assert m._on_screen['device3'] == 'new'
