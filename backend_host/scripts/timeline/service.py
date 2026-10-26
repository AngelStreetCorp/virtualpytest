#!/usr/bin/env python3
"""vpt-timeline: builds the Timeline sprites and tracks for finished archive chunks (TASK-94).

Separate low-priority process (like vpt-avq). Every 60 s, per opted-in capture device, reads
`segments/archive_manifest.json` and, for each finished chunk without a sprite, writes into
`thumbnails/<hour>/`: `timeline_<n>_30s.jpg|json` and `timeline_<n>_6s.jpg|json` (sprites + tile maps) and `timeline_<n>_tracks.json`.
Backfills newest first. Deletes its own files older than 26 h.

Opt-in per device: DEVICE{N}_TIMELINE=true (N = the capture folder number), or TIMELINE_ALL=true.
(A monitor profile with a `ui.timeline` block will opt a device in once TASK-90 lands.)

    python3 service.py --once --root /path/to/capture3     # one pass on one capture dir, ignore opt-in
    python3 service.py                                     # continuous
"""
import argparse
import json
import logging
import os
import re
import sys
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(current_dir)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))

from backend_host.scripts.timeline import sprites, tracks  # noqa: E402

try:   # DEVICE{N}_TIMELINE may be in the project .env (the unit loads it) or in backend_host/src/.env (where DEVICE{N}_* live)
    from dotenv import load_dotenv
    _root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    for _env in (os.path.join(_root, '.env'), os.path.join(_root, 'backend_host', 'src', '.env')):
        if os.path.isfile(_env):
            load_dotenv(_env, override=False)
except Exception:   # a missing or unreadable .env just means only the unit's environment counts
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [TIMELINE] %(levelname)s: %(message)s')
log = logging.getLogger('timeline')

LOOP_S = 60
KEEP_S = 26 * 3600
MIN_FINISHED_AGE_S = 90       # a chunk younger than this may still be growing (progressive append)


def device_enabled(capture_dir: str) -> bool:
    if os.getenv('TIMELINE_ALL', '').lower() in ('1', 'true', 'yes', 'on'):
        return True
    m = re.search(r'capture(\d+)$', capture_dir.rstrip('/'))
    return bool(m) and os.getenv(f'DEVICE{m.group(1)}_TIMELINE', '').lower() in ('1', 'true', 'yes', 'on')


def _paths(capture_dir: str, hour: int, idx: int):
    """(dir, [every file that must exist for a chunk to count as built], tile map of the first level, tracks)."""
    d = os.path.join(capture_dir, 'thumbnails', str(hour))
    files = []
    for step_s, _ in sprites.LEVELS:
        files += [os.path.join(d, n) for n in sprites.sprite_names(idx, step_s)]
    first_map = os.path.join(d, sprites.sprite_names(idx, sprites.LEVELS[0][0])[1])
    trk = os.path.join(d, f'timeline_{idx}_tracks.json')
    return d, files + [trk], first_map, trk


def load_manifest(capture_dir: str) -> list:
    try:
        with open(os.path.join(capture_dir, 'segments', 'archive_manifest.json')) as f:
            return json.load(f).get('chunks', [])
    except (OSError, ValueError):
        return []


def pending_chunks(capture_dir: str, now: float = None) -> list:
    """Finished chunks (manifest `created` = chunk end) with no sprite yet, newest first."""
    now = now or time.time()
    out = []
    for ch in load_manifest(capture_dir):
        end = ch.get('created')
        if not end or now - end < MIN_FINISHED_AGE_S or now - end > KEEP_S:
            continue
        _, files, js, trk = _paths(capture_dir, ch['hour'], ch['chunk_index'])
        mp4 = os.path.join(capture_dir, 'segments', str(ch['hour']), ch['name'])
        if not os.path.exists(mp4):
            continue
        if all(os.path.exists(f) for f in files):
            # stale if the chunk was rewritten after we built it (size changed)
            try:
                if json.load(open(js)).get('chunk_size') == ch.get('size'):
                    continue
            except (OSError, ValueError):
                pass
        out.append(ch)
    out.sort(key=lambda c: c['created'], reverse=True)
    return out


def build_chunk(capture_dir: str, ch: dict) -> str:
    d, _, first_map, trk = _paths(capture_dir, ch['hour'], ch['chunk_index'])
    mp4 = os.path.join(capture_dir, 'segments', str(ch['hour']), ch['name'])
    maps = sprites.build_sprites(mp4, d, ch['chunk_index'], chunk_end_epoch=ch['created'])
    for step_s, tile_map in maps.items():      # stamp the manifest size: a rewritten chunk is rebuilt
        tile_map['chunk_size'] = ch.get('size')
        with open(os.path.join(d, sprites.sprite_names(ch['chunk_index'], step_s)[1]), 'w') as f:
            json.dump(tile_map, f)
    first = maps[sprites.LEVELS[0][0]]
    meta = tracks.load_meta(os.path.join(capture_dir, 'metadata', str(ch['hour']),
                                         f"chunk_10min_{ch['chunk_index']}.json")) or {'frames': []}
    red = tracks.reduce_chunk(meta, chunk_start=first['chunk_start'],
                              levels={step_s: m['count'] for step_s, m in maps.items()})
    red['tile'] = {'w': first['tile_w'], 'h': first['tile_h']}     # the page sizes its tiles from this (a phone's are portrait)
    tmp = trk + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(red, f)
    os.replace(tmp, trk)
    return first.get('decode', 'full')


def sweep_old(capture_dir: str, now: float = None) -> int:
    now = now or time.time()
    n = 0
    base = os.path.join(capture_dir, 'thumbnails')
    if not os.path.isdir(base):
        return 0
    for hour in os.listdir(base):
        d = os.path.join(base, hour)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.startswith('timeline_') and now - os.path.getmtime(os.path.join(d, name)) > KEEP_S:
                os.remove(os.path.join(d, name))
                n += 1
    return n


def status(capture_dir: str) -> dict:
    pend = pending_chunks(capture_dir)
    total = len(load_manifest(capture_dir))
    return {'enabled': device_enabled(capture_dir), 'chunks': total, 'backlog': len(pend),
            'newest_pending': pend[0]['created'] if pend else None}


FAILED_RETRY_S = 1800
_failed = {}   # (capture_dir, hour, chunk_index) -> when it failed: a chunk that cannot be built (corrupt mp4) is not decoded again every round


def buildable_chunks(capture_dir: str) -> list:
    now = time.time()
    return [ch for ch in pending_chunks(capture_dir)
            if now - _failed.get((capture_dir, ch['hour'], ch['chunk_index']), 0) > FAILED_RETRY_S]


def run_once(capture_dir: str, max_chunks: int = None) -> int:
    built = tried = 0
    for ch in buildable_chunks(capture_dir):
        if max_chunks is not None and tried >= max_chunks:     # attempts count, not successes: a failing chunk must not turn the round into a loop over every pending one
            break
        t0 = time.time()
        tried += 1
        try:
            mode = build_chunk(capture_dir, ch)
            built += 1
            log.info('%s h%s c%s built in %.1fs (%s)', os.path.basename(capture_dir), ch['hour'], ch['chunk_index'], time.time() - t0, mode)
        except Exception as e:   # one bad chunk must not stop the backfill
            _failed[(capture_dir, ch['hour'], ch['chunk_index'])] = time.time()
            log.warning('%s h%s c%s failed: %s (not retried for %d min)', os.path.basename(capture_dir), ch['hour'], ch['chunk_index'], e, FAILED_RETRY_S // 60)
    sweep_old(capture_dir)
    return built


def capture_dirs() -> list:
    from shared.src.lib.utils.storage_path_utils import get_capture_base_directories
    return [d for d in get_capture_base_directories() if device_enabled(d)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--root', help='one capture dir (testing); ignores the opt-in')
    a = ap.parse_args()
    if a.root:
        run_once(a.root)
        return
    idle_logged = False
    dirs, dirs_at = [], 0.0
    while True:
        if time.time() - dirs_at >= LOOP_S:
            dirs, dirs_at = capture_dirs(), time.time()
        if not dirs and not idle_logged:
            log.info('no device opted in (DEVICE{N}_TIMELINE=true or TIMELINE_ALL=true); idle')
        idle_logged = not dirs
        for d in dirs:
            run_once(d, max_chunks=1)     # one chunk per device per round: backfill without a burst
        if a.once:
            return
        time.sleep(LOOP_S if not any(buildable_chunks(d) for d in dirs) else 5)


if __name__ == '__main__':
    main()
