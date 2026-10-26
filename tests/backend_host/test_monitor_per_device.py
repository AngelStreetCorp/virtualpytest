"""One host, two devices, two profiles (TASK-90 goal 7): device1 tv_app next to device2 counting_cars."""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import shared.src.lib.utils.monitor_profile as mp  # noqa: E402
from monitor.analyzers import pipeline as pl  # noqa: E402
from monitor.analyzers.hsv_colour import HsvColour  # noqa: E402
from tests.backend_host.test_counting_cars import FakeDetector  # noqa: E402
from tests.backend_host.test_monitor_replay import _drop_goal4_keys, run_replay  # noqa: E402

FRAMES = 60


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if mp._PROFILE_KEY.match(k):
            monkeypatch.delenv(k)


def run_two_devices(tmp_path, monkeypatch):
    seen = {}

    def configure():
        monkeypatch.setattr(pl, '_build_stage', lambda spec: FakeDetector() if spec.type == 'coco_detect' else HsvColour())
        monkeypatch.setattr(pl.PipelineAnalyzer, 'start', lambda self: None)

    def after_frame(fm, name, folder):
        seen['fm'] = fm
        for a in fm.device_analyzers[folder]:
            if hasattr(a, 'run_pending'):
                a.run_pending()

    out = run_replay(str(tmp_path), env_extra={'DEVICE2_MONITOR_PROFILE': 'counting_cars'}, frames=FRAMES,
                     configure=configure, after_frame=after_frame, device_count=2)
    return out, seen['fm']


def test_each_device_runs_its_own_profile(tmp_path, monkeypatch):
    out, fm = run_two_devices(tmp_path, monkeypatch)
    one = [out['devices']['capture1']['frames'][n] for n in sorted(out['devices']['capture1']['frames'])]
    two = [out['devices']['capture2']['frames'][n] for n in sorted(out['devices']['capture2']['frames'])]
    assert len(one) == len(two) == FRAMES
    assert all(f['profile'] == 'tv_app' and f['subtitle_ocr_pending'] is True for f in one)
    assert all(f['profile'] == 'counting_cars' and f['subtitle_ocr_pending'] is False for f in two)
    assert 'blackscreen' in one[-1] and 'freeze' in one[-1]
    assert 'blackscreen' not in two[-1] and two[-1]['kpis']['count_per_min'] == 1
    # one analyzer set per profile, shared by the devices that run it
    assert [type(a).__name__ for a in fm.device_analyzers['capture1']] == ['TvAppAnalyzer']
    assert [type(a).__name__ for a in fm.device_analyzers['capture2']] == ['PipelineAnalyzer']
    assert fm.incident_manager.profile_of('device1')[0] == 'tv_app'
    assert fm.incident_manager.profile_of('device2') == ('counting_cars', frozenset())


def test_tv_app_output_does_not_change_next_to_another_profile(tmp_path, monkeypatch):
    out, _ = run_two_devices(tmp_path / 'two', monkeypatch)
    alone = run_replay(str(tmp_path / 'one'), frames=FRAMES)
    beside = out['devices']['capture1']
    for result in (alone, beside):
        _drop_goal4_keys(result)
    assert beside['frames'] == alone['frames']
    assert beside['chunks'] == alone['chunks']
    assert beside['detections'] == alone['detections']


def test_services_only_serve_the_devices_whose_profile_uses_them(monkeypatch, tmp_path):
    import shared.src.lib.utils.storage_path_utils as spu
    monkeypatch.setenv('STREAM_BASE_PATH', str(tmp_path))
    monkeypatch.setattr(spu, '_STREAM_BASE_PATH', str(tmp_path))
    spu._device_mapping_cache.clear()
    for i in (1, 2):
        monkeypatch.setenv(f'DEVICE{i}_VIDEO_CAPTURE_PATH', str(tmp_path / f'capture{i}'))
    monkeypatch.setenv('DEVICE2_MONITOR_PROFILE', 'counting_cars')
    folders = ['capture1', 'capture2']
    assert mp.folders_needing_service('img', folders) == ['capture1', 'capture2']
    assert mp.folders_needing_service('audio', folders) == ['capture1']        # vpt-monitor-audio only checks device1
    assert mp.folders_needing_service('subtitle', folders) == ['capture1']
    spu._device_mapping_cache.clear()


def test_devices_beyond_four_are_found(monkeypatch, tmp_path):
    import shared.src.lib.utils.storage_path_utils as spu
    monkeypatch.setattr(spu, '_STREAM_BASE_PATH', str(tmp_path))
    spu._device_mapping_cache.clear()
    monkeypatch.setenv('DEVICE7_VIDEO_CAPTURE_PATH', str(tmp_path / 'capture7'))
    monkeypatch.setenv('DEVICE7_NAME', 'Seventh')
    info = spu.get_device_info_from_capture_folder('capture7')
    # the id stays what it was before DEVICE5+ were scanned (alert and heatmap keys must not split); only the index is new
    assert info['device_id'] == 'capture7' and info['device_index'] == 7 and info['device_name'] == 'capture7'
    monkeypatch.setenv('DEVICE3_VIDEO_CAPTURE_PATH', str(tmp_path / 'capture3'))
    assert spu.get_device_info_from_capture_folder('capture3')['device_id'] == 'device3'
    monkeypatch.setenv('HOST_VIDEO_CAPTURE_PATH', str(tmp_path / 'capture9'))
    assert spu.get_device_info_from_capture_folder('capture9')['device_index'] is None
    spu._device_mapping_cache.clear()


# ---- a device whose profile cannot start must not stop the others (review BLOCK 1 and 2) ------------

@pytest.mark.parametrize('model', ['missing', 'corrupt'])
def test_a_failing_profile_leaves_only_that_device_out(tmp_path, monkeypatch, model):
    if model == 'corrupt':
        bad = tmp_path / 'bad.onnx'
        bad.write_bytes(b'not an onnx file at all')
        monkeypatch.setenv('MONITOR_COCO_MODEL', str(bad))     # cv2.error, not FileNotFoundError
    else:
        monkeypatch.delenv('MONITOR_COCO_MODEL', raising=False)
    seen = {}
    out = run_replay(str(tmp_path / 'run'), env_extra={'DEVICE2_MONITOR_PROFILE': 'counting_cars'}, frames=FRAMES,
                     device_count=2, after_frame=lambda fm, name, folder: seen.setdefault('fm', fm))
    fm = seen['fm']
    one = out['devices']['capture1']['frames']
    assert len(one) == FRAMES and all(f['profile'] == 'tv_app' for f in one.values())   # device1 analysed as always
    assert out['devices']['capture2']['frames'] == {}
    caps2 = os.path.join(str(tmp_path / 'run'), 'stream', 'capture2', 'captures')
    assert 'capture2' not in fm.device_analyzers and caps2 not in fm.dir_to_info and 'capture2' not in fm.device_queues
    # a capture dir found after startup with the same problem: nothing half-registered, and a frame event is harmless
    monkeypatch.setenv('DEVICE2_MONITOR_PROFILE', 'counting_cars')   # run_replay restored the environment
    fm._register_capture_dir(caps2)
    assert caps2 not in fm.dir_to_info and 'capture2' not in fm.device_queues
    fm._handle_file_event(caps2, 'capture_000000001.jpg')


def test_the_failure_is_logged_once_per_distinct_error(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv('MONITOR_COCO_MODEL', raising=False)
    seen = {}
    with caplog.at_level('ERROR', logger='capture_monitor'):
        run_replay(str(tmp_path / 'run'), env_extra={'DEVICE2_MONITOR_PROFILE': 'counting_cars'}, frames=3, device_count=2,
                   after_frame=lambda fm, name, folder: seen.setdefault('fm', fm))
        caps2 = os.path.join(str(tmp_path / 'run'), 'stream', 'capture2', 'captures')
        monkeypatch.setenv('DEVICE2_MONITOR_PROFILE', 'counting_cars')
        for _ in range(5):                                      # the 10 s rescan keeps asking
            seen['fm']._register_capture_dir(caps2)
    assert sum('cannot start this device' in r.message for r in caplog.records) == 1
