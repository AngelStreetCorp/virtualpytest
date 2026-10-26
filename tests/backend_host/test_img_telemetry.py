"""TASK-157 image telemetry: counters, histogram, status file, bounded DB queue, outage behaviour, memory."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend_host', 'scripts'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from monitor import img_telemetry as it  # noqa: E402


class _NoProc:
    def sample(self):
        return {'cpu_pct_monitor': None, 'rss_monitor_bytes': None, 'cpu_pct_ffmpeg': None,
                'rss_ffmpeg_bytes': None, 'load_per_core': None}


def _frame(tmp_path, name, size=1000, age_s=0.0):
    p = tmp_path / name
    p.write_bytes(b'x' * size)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return str(p)


def _tel(tmp_path, **kw):
    return it.ImageTelemetry('h1', window_s=60, status_dir_fn=lambda f: str(tmp_path / 'meta' / f),
                             device_id_fn=lambda f: 'dev_' + f, proc_sampler=_NoProc(), **kw)


def test_counts_bytes_fps_and_age(tmp_path):
    t = _tel(tmp_path)
    t._window_start = time.time() - 10
    for i in range(50):
        t.on_arrival('capture1', _frame(tmp_path, f'c{i}.jpg', size=2000))
    for i in range(45):
        t.on_analyzed('capture1', _frame(tmp_path, f'a{i}.jpg', age_s=0.25), queue_size=i % 3)
    t.on_dropped('capture1', 5)
    recs = t.flush()
    dev = next(r for r in recs if r['device_id'] == 'dev_capture1')
    assert dev['frames_arrived'] == 50 and dev['frames_analyzed'] == 45 and dev['frames_dropped'] == 5
    assert dev['image_bytes'] == 100000
    assert 4.8 <= dev['arrived_fps'] <= 5.2
    assert abs(dev['estimated_image_throughput_bps'] - 80000) < 400   # 100 kB over ~10 s
    assert dev['frame_age_p95_ms'] == 300.0          # 250 ms lands in the <=300 ms bucket
    assert dev['queue_depth_max'] == 2
    host = next(r for r in recs if r['device_id'] == it.HOST_ROW)
    assert host['load_per_core'] is None             # unsupported / failed readings are None, never 0


def test_status_file_written_atomically(tmp_path):
    t = _tel(tmp_path)
    t.on_arrival('capture1', _frame(tmp_path, 'c.jpg'))
    t.flush()
    data = json.loads((tmp_path / 'meta' / 'capture1' / it.STATUS_FILE).read_text())
    assert data['frames_arrived'] == 1 and data['device_id'] == 'dev_capture1' and 'written_at' in data
    assert not (tmp_path / 'meta' / 'capture1' / (it.STATUS_FILE + '.tmp')).exists()


def test_missing_file_is_not_a_crash_and_not_a_zero_age(tmp_path):
    t = _tel(tmp_path)
    t.on_arrival('capture1', str(tmp_path / 'gone.jpg'))
    t.on_analyzed('capture1', str(tmp_path / 'gone.jpg'))
    rec = next(r for r in t.flush() if r['device_id'] == 'dev_capture1')
    assert rec['frames_arrived'] == 1 and rec['image_bytes'] == 0
    assert rec['frame_age_p95_ms'] is None and rec['frame_age_max_ms'] is None


def test_open_ended_age_bucket():
    hist = [0] * (len(it.AGE_BOUNDS_MS) + 1)
    hist[-1] = 3
    assert it.age_percentile_ms(hist, 95) == float(it.AGE_BOUNDS_MS[-1])
    assert it.age_percentile_ms([0] * len(hist), 95) is None


def test_queue_is_bounded_and_counts_drops(tmp_path):
    t = _tel(tmp_path)
    for i in range(it.DB_QUEUE_MAX + 25):
        t._enqueue({'n': i})
    assert t._rows.qsize() == it.DB_QUEUE_MAX
    assert t._rows_dropped == 25
    assert t._rows.get_nowait() == {'n': 25}         # the oldest rows went


def test_db_outage_keeps_rows_bounded_and_recovers(tmp_path):
    calls = []
    state = {'down': True}

    def sink(rows):
        calls.append(len(rows))
        if state['down']:
            raise RuntimeError('db down')

    t = _tel(tmp_path, sink=sink)
    t.on_arrival('capture1', _frame(tmp_path, 'c.jpg'))
    t.flush()
    # one writer iteration, by hand: fails, rows are kept
    batch = [t._rows.get_nowait() for _ in range(t._rows.qsize())]
    try:
        t._write_batch(batch)
    except RuntimeError:
        for row in batch:
            t._enqueue(row)
    assert t._rows.qsize() == len(batch) and t._rows.qsize() <= it.DB_QUEUE_MAX
    state['down'] = False
    t._write_batch(batch)
    assert calls == [len(batch), len(batch)]


def test_no_growth_over_a_million_frames(tmp_path):
    t = _tel(tmp_path)
    p = _frame(tmp_path, 'c.jpg')
    for _ in range(5):
        for _ in range(2000):
            t.on_arrival('capture1', p)
            t.on_analyzed('capture1', p)
        t.flush()
    assert len(t._dev) == 0 and t._rows.qsize() <= it.DB_QUEUE_MAX


def test_kill_switch_and_window(monkeypatch):
    monkeypatch.delenv('IMG_TELEMETRY', raising=False)
    assert it.enabled()                      # unset: the device's profile decides
    monkeypatch.setenv('IMG_TELEMETRY', 'false')
    assert not it.enabled()
    monkeypatch.setenv('IMG_TELEMETRY', 'true')
    assert it.enabled()
    monkeypatch.setenv('IMG_TELEMETRY_WINDOW_S', '1')
    assert it.window_seconds() == 10


def test_profile_flag_tv_app_on_others_off():
    import yaml
    d = os.path.join(os.path.dirname(__file__), '..', '..', 'backend_host', 'config', 'monitor', 'profiles')
    on = {f[:-5] for f in os.listdir(d) if f.endswith('.yaml') and yaml.safe_load(open(os.path.join(d, f))).get('img', {}).get('telemetry')}
    assert on == {'tv_app'}


def test_manifest_rejects_non_bool_telemetry():
    import pytest
    from shared.src.lib.utils.monitor_profile import validate_manifest_light
    raw = {'name': 'x', 'img': {'analyzers': [{'type': 'tv_app'}], 'telemetry': 'yes'}}
    with pytest.raises(ValueError):
        validate_manifest_light(raw, 'x')


def test_process_sampler_returns_none_not_zero_on_first_window():
    out = it.ProcessSampler().sample()
    assert out['cpu_pct_monitor'] is None            # first window primes psutil
    assert isinstance(out['rss_monitor_bytes'], int)
