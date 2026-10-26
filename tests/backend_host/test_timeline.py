"""Timeline sprites/tracks/service (TASK-94 phase 1). Real ffmpeg on a generated 70 s chunk; no host, no DB."""
import json
import os
import shutil
import subprocess
import time

import pytest

from backend_host.scripts.timeline import service, sprites, tracks

pytestmark = pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not installed')


@pytest.fixture
def capture_dir(tmp_path):
    cap = tmp_path / 'capture3'
    seg = cap / 'segments' / '10'
    seg.mkdir(parents=True)
    mp4 = seg / 'chunk_10min_0.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=70',
                    '-pix_fmt', 'yuv420p', str(mp4)], check=True)
    end = time.time() - 600
    (cap / 'segments' / 'archive_manifest.json').write_text(json.dumps({'chunks': [
        {'hour': 10, 'chunk_index': 0, 'name': 'chunk_10min_0.mp4', 'size': mp4.stat().st_size, 'created': end}]}))
    meta = cap / 'metadata' / '10'
    meta.mkdir(parents=True)
    frames = [{'timestamp': f'2026-10-13T10:{i // 60:02d}:{i % 60:02d}', 'freeze': 20 <= i < 25,
               'events': {'ad_break': {'start': 1, 'duration_ms': 1000, 'kind': 'new'}} if 35 <= i < 65 else {}}
              for i in range(70)]
    (meta / 'chunk_10min_0.json').write_text(json.dumps({'frames': frames}))
    return str(cap)


def test_sprite_tile_count_and_grid(tmp_path, capture_dir):
    mp4 = os.path.join(capture_dir, 'segments', '10', 'chunk_10min_0.mp4')
    m = sprites.build_sprites(mp4, str(tmp_path), 0)
    assert m[30]['count'] == 3 and (m[30]['cols'], m[30]['rows']) == (5, 4)      # 70 s: frames at 0, 30, 60 s
    assert m[6]['count'] == 12 and (m[6]['cols'], m[6]['rows']) == (10, 10)
    for step in (30, 6):
        assert m[step]['cols'] * m[step]['rows'] >= m[step]['count']
        assert os.path.getsize(tmp_path / f'timeline_0_{step}s.jpg') > 1000
        assert json.load(open(tmp_path / f'timeline_0_{step}s.json'))['count'] == m[step]['count']


def test_reduce_chunk_ad_and_freeze_bands():
    frames = [{'timestamp': f'2026-10-13T10:{i // 60:02d}:{i % 60:02d}', 'freeze': 20 <= i < 25,
               'events': {'ad_break': {'kind': 'confirmed'}} if 35 <= i < 65 else {}}
              for i in range(70) if i != 50]      # a lost frame must not shift later ones
    r = tracks.reduce_chunk({'frames': frames}, chunk_start=1000.0, levels={30: 3, 6: 12})
    by = {t['id']: t for t in r['tracks']}
    ad = by['ad']['spans']
    assert len(ad) == 1 and ad[0]['kind'] == 'confirmed'
    assert ad[0]['s'] == (1000 + 35) * 1000 and ad[0]['e'] == (1000 + 65) * 1000   # the 1 s gap is bridged
    assert by['freeze']['spans'] and not by['blackscreen']['spans']
    assert r['tiles']['30'][1]['ad'] > 0.5 and r['tiles']['30'][0]['ad'] == 0
    assert r['tiles']['6'][6]['ad'] == 1.0 and r['tiles']['6'][0]['ad'] == 0 and len(r['tiles']['6']) == 12


def test_service_builds_once_then_is_idempotent(capture_dir):
    assert service.run_once(capture_dir) == 1
    d = os.path.join(capture_dir, 'thumbnails', '10')
    assert sorted(os.listdir(d)) == ['timeline_0_30s.jpg', 'timeline_0_30s.json', 'timeline_0_6s.jpg',
                                     'timeline_0_6s.json', 'timeline_0_tracks.json']
    assert service.run_once(capture_dir) == 0   # nothing pending
    assert service.status(capture_dir)['backlog'] == 0


def test_growing_chunk_is_not_built(capture_dir):
    mf = os.path.join(capture_dir, 'segments', 'archive_manifest.json')
    data = json.load(open(mf))
    data['chunks'][0]['created'] = time.time() - 5
    json.dump(data, open(mf, 'w'))
    assert service.pending_chunks(capture_dir) == []


def test_changed_chunk_size_rebuilds(capture_dir):
    service.run_once(capture_dir)
    mf = os.path.join(capture_dir, 'segments', 'archive_manifest.json')
    data = json.load(open(mf))
    data['chunks'][0]['size'] += 1
    json.dump(data, open(mf, 'w'))
    assert len(service.pending_chunks(capture_dir)) == 1


def test_opt_in(monkeypatch):
    monkeypatch.delenv('TIMELINE_ALL', raising=False)
    monkeypatch.delenv('DEVICE3_TIMELINE', raising=False)
    assert not service.device_enabled('/var/www/html/stream/capture3')
    monkeypatch.setenv('DEVICE3_TIMELINE', 'true')
    assert service.device_enabled('/var/www/html/stream/capture3')
    assert not service.device_enabled('/var/www/html/stream/capture4')


def test_sweep_removes_only_old_timeline_files(capture_dir):
    service.run_once(capture_dir)
    d = os.path.join(capture_dir, 'thumbnails', '10')
    keep = os.path.join(d, 'capture_1_thumbnail.jpg')
    open(keep, 'w').write('x')
    old = time.time() - 27 * 3600
    for n in os.listdir(d):
        os.utime(os.path.join(d, n), (old, old))
    assert service.sweep_old(capture_dir) == 5
    assert os.path.exists(keep)


def test_a_chunk_that_cannot_be_built_is_not_retried_every_round(tmp_path, monkeypatch):
    from backend_host.scripts.timeline import service as svc
    chunks = [{'hour': 1, 'chunk_index': i, 'created': i} for i in range(5)]
    calls = []
    monkeypatch.setattr(svc, 'pending_chunks', lambda d: chunks)
    monkeypatch.setattr(svc, 'sweep_old', lambda d: 0)
    monkeypatch.setattr(svc, 'build_chunk', lambda d, ch: (calls.append(ch['chunk_index']), (_ for _ in ()).throw(RuntimeError('corrupt')))[1])
    svc._failed.clear()
    assert svc.run_once('/x', max_chunks=1) == 0 and calls == [0]            # one attempt per round, not one per pending chunk
    assert svc.run_once('/x', max_chunks=1) == 0 and calls == [0, 1]         # the failed one is skipped, the next is tried
    assert [c['chunk_index'] for c in svc.buildable_chunks('/x')] == [2, 3, 4]


def test_tile_shape_follows_the_video_orientation():
    from backend_host.scripts.timeline import sprites
    assert sprites.tile_size_for(1280, 720) == (160, 90)
    assert sprites.tile_size_for(720, 1280) == (90, 160)       # a phone is not squeezed into 16:9
    assert sprites.tile_size_for(500, 500) == (160, 90)        # square: landscape
    assert sprites.tile_size_for(None, None) == (160, 90)      # unknown size: the old behaviour


@pytest.mark.skipif(shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None, reason='needs ffmpeg')
@pytest.mark.parametrize('size,tile', [('640x360', (160, 90)), ('360x640', (90, 160)), ('1280x400', (160, 90))])
def test_a_built_sprite_has_the_tile_shape_of_the_video(tmp_path, size, tile):
    from backend_host.scripts.timeline import sprites
    mp4 = tmp_path / 'c.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate=2', '-t', '70', '-pix_fmt', 'yuv420p', str(mp4)], check=True)
    maps = sprites.build_sprites(str(mp4), str(tmp_path / 'out'), 0, chunk_end_epoch=1.0)
    assert (maps[6]['tile_w'], maps[6]['tile_h']) == tile
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x', str(tmp_path / 'out' / 'timeline_0_6s.jpg')]).decode().strip()
    assert out == f'{tile[0] * 10}x{tile[1] * 10}'             # 10x10 tiles of that size


def _chunk(path, gop_frames, seconds=70):
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'testsrc=size=640x360:rate=10:duration={seconds}',
                    '-c:v', 'libx264', '-g', str(gop_frames), '-keyint_min', str(gop_frames), '-sc_threshold', '0',
                    '-pix_fmt', 'yuv420p', str(path)], check=True)
    return str(path)


def _luma(path):
    from PIL import Image
    import numpy as np
    return np.asarray(Image.open(path).convert('L'), dtype=float)


def test_keyframe_gop_detection(tmp_path):
    assert sprites.probe_keyframe_interval(_chunk(tmp_path / 'g04.mp4', 4)) == pytest.approx(0.4, abs=0.01)
    assert sprites.probe_keyframe_interval(_chunk(tmp_path / 'g250.mp4', 250)) is None     # one keyframe: irregular
    assert sprites.keyframes_land_on_marks(0.4, 6) and sprites.keyframes_land_on_marks(1.0, 6)
    assert not sprites.keyframes_land_on_marks(0.8, 6) and not sprites.keyframes_land_on_marks(None, 6)


def test_keyframe_only_path_matches_full_decode(tmp_path):
    mp4 = _chunk(tmp_path / 'g04.mp4', 4)
    fast = sprites.build_sprites(mp4, str(tmp_path / 'fast'), 0)
    full = sprites.build_sprites(mp4, str(tmp_path / 'full'), 0, force_full=True)
    assert fast[6]['decode'] == 'keyframes' and full[6]['decode'] == 'full'
    for step in (30, 6):
        assert fast[step]['count'] == full[step]['count']
        a, b = _luma(tmp_path / 'fast' / f'timeline_0_{step}s.jpg'), _luma(tmp_path / 'full' / f'timeline_0_{step}s.jpg')
        assert a.shape == b.shape
        # the clock burned into testsrc moves every frame, so tiles of the two paths may differ by a frame: same picture overall
        assert abs(a.mean() - b.mean()) < 8


def test_irregular_gop_falls_back_to_full_decode(tmp_path):
    mp4 = _chunk(tmp_path / 'g08.mp4', 8)           # 0.8 s: no keyframe on every 6 s mark
    assert sprites.build_sprites(mp4, str(tmp_path / 'o'), 0)[6]['decode'] == 'full'


def test_failed_fast_path_falls_back(tmp_path, monkeypatch):
    mp4 = _chunk(tmp_path / 'g04.mp4', 4)
    monkeypatch.setattr(sprites, '_decode_keyframes_only', lambda *a, **k: False)
    m = sprites.build_sprites(mp4, str(tmp_path / 'o'), 0)
    assert m[6]['decode'] == 'full' and os.path.getsize(tmp_path / 'o' / 'timeline_0_6s.jpg') > 1000
