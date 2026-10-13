"""The open 10-min chunk is built in RAM and written to cold storage once.

Appending a minute rewrites the whole chunk, so doing it on the SD card wrote ~110x one minute
of video per chunk and stalled the Pi's card. The chunk now grows in a RAM stage with a symlink
at its cold path, and is copied to cold once when the next chunk starts or the device idles.
ffmpeg is replaced by a byte concat, so file contents show exactly which minutes a chunk holds.
"""
import os
import sys
import time
from datetime import datetime

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "backend_host", "scripts"))

import hot_cold_archiver as archiver  # noqa: E402
from shared.src.lib.utils import video_utils  # noqa: E402


def _fake_merge(inputs, output, *args, **kwargs):
    with open(output, 'wb') as out:
        for path in inputs:
            with open(path, 'rb') as f:
                out.write(f.read())
    return output


@pytest.fixture
def env(tmp_path, monkeypatch):
    stage = tmp_path / 'shm'
    capture = tmp_path / 'stream' / 'capture1'
    (capture / 'segments' / '7').mkdir(parents=True)
    room = {'ok': True}
    manifest = []
    monkeypatch.setattr(archiver, 'STAGE_ROOT', str(stage))
    monkeypatch.setattr(archiver, '_stage_has_room', lambda need: room['ok'])
    monkeypatch.setattr(archiver, 'update_archive_manifest', lambda c, h, i, p: manifest.append((h, i)))
    monkeypatch.setattr(video_utils, 'merge_video_files', _fake_merge)
    return {'tmp': tmp_path, 'capture': str(capture), 'stage': str(stage), 'room': room, 'manifest': manifest}


def _minute(env, data):
    path = os.path.join(str(env['tmp']), 'one_min.mp4')
    with open(path, 'wb') as f:
        f.write(data)
    return path


def _chunk(env, idx, hour=7):
    return os.path.join(env['capture'], 'segments', str(hour), f'chunk_10min_{idx}.mp4')


def _append(env, idx, data, now=None):
    return archiver.append_minute_to_chunk(env['capture'], _chunk(env, idx), _minute(env, data), 7, idx,
                                           now or datetime.now())


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def test_open_chunk_grows_in_ram_behind_a_symlink(env):
    for data in (b'm0', b'm1', b'm2'):
        assert _append(env, 0, data) == _chunk(env, 0)
    path = _chunk(env, 0)
    assert os.path.islink(path)
    assert os.readlink(path).startswith(env['stage'])
    assert _read(path) == b'm0m1m2'


def test_next_chunk_writes_the_previous_one_to_cold_once(env):
    _append(env, 0, b'm0')
    _append(env, 0, b'm1')
    _append(env, 1, b'n0')
    done = _chunk(env, 0)
    assert os.path.isfile(done) and not os.path.islink(done)
    assert _read(done) == b'm0m1'
    assert not os.path.exists(archiver._staged_chunk_path('capture1', 7, 0))
    assert os.path.islink(_chunk(env, 1))
    assert (7, 0) in env['manifest']


def test_no_room_in_ram_appends_on_cold(env):
    env['room']['ok'] = False
    _append(env, 0, b'm0')
    _append(env, 0, b'm1')
    path = _chunk(env, 0)
    assert not os.path.islink(path)
    assert _read(path) == b'm0m1'


def test_ram_running_short_mid_window_finishes_on_cold(env):
    _append(env, 0, b'm0')
    env['room']['ok'] = False
    _append(env, 0, b'm1')
    path = _chunk(env, 0)
    assert not os.path.islink(path)
    assert _read(path) == b'm0m1'
    assert not os.listdir(os.path.join(env['stage'], 'capture1'))


def test_lost_stage_after_reboot_restarts_the_window(env):
    _append(env, 0, b'm0')
    os.remove(archiver._staged_chunk_path('capture1', 7, 0))  # /dev/shm cleared
    assert not os.path.exists(_chunk(env, 0))  # readers skip it
    _append(env, 0, b'm1')
    assert _read(_chunk(env, 0)) == b'm1'


def test_startup_drops_dangling_links(env):
    _append(env, 0, b'm0')
    os.remove(archiver._staged_chunk_path('capture1', 7, 0))
    assert archiver.drop_lost_staged_links(env['capture']) == 1
    assert not os.path.lexists(_chunk(env, 0))


def test_idle_device_chunk_is_written_after_eleven_minutes(env):
    _append(env, 0, b'm0')
    staged = archiver._staged_chunk_path('capture1', 7, 0)
    assert archiver.finalize_staged_chunks(env['capture']) == 0
    old = time.time() - archiver.STAGE_IDLE_FINALIZE_SECONDS - 5
    os.utime(staged, (old, old))
    assert archiver.finalize_staged_chunks(env['capture']) == 1
    assert _read(_chunk(env, 0)) == b'm0' and not os.path.islink(_chunk(env, 0))


def test_yesterdays_chunk_in_the_same_slot_is_replaced(env):
    path = _chunk(env, 0)
    with open(path, 'wb') as f:
        f.write(b'yesterday')
    old = time.time() - 86400
    os.utime(path, (old, old))
    _append(env, 0, b'm0')
    assert os.path.islink(path)
    assert _read(path) == b'm0'
