"""One sprite JPEG per 10-min chunk and level: 30 s = 20 tiles (5x4), 6 s = 100 tiles (10x10), 160x90 each (90x160 for a portrait
video: a phone's picture is not squeezed into 16:9; the tile map and the tracks file say which).

One decode pass (measured on vpt-pi1: 2.2 s for a 17.7 MB chunk; one ffmpeg per tile is slower).
Tile i is the frame AT i*step (its label is its time, so a click seeks to what is shown).
"""
import json
import math
import os
import subprocess
from typing import Optional

TILE_W = 160
TILE_H = 90


def tile_size_for(width: Optional[int], height: Optional[int]) -> tuple:
    """(w, h) of one tile: landscape 160x90, portrait (taller than wide) 90x160. Unknown size = landscape."""
    if width and height and height > width:
        return TILE_H, TILE_W
    return TILE_W, TILE_H


def probe_size(path: str) -> tuple:
    """(width, height) of the first video stream, or (None, None)."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x', path],
                       capture_output=True, text=True, timeout=30)
    try:
        w, h = r.stdout.strip().split('x')
        return int(w), int(h)
    except ValueError:
        return None, None
CHUNK_S = 600


def grid_for(step_s: int, cols: int):
    """Fixed geometry per level whatever the chunk length (a short chunk leaves black tiles at the end), so the
    page needs no per-chunk tile map: 30 s = 5x4, 6 s = 10x10."""
    return cols, (CHUNK_S // step_s) // cols


LEVELS = ((30, 5), (6, 10))   # (seconds per tile, grid columns): the Hour grid and the 10-min grid


def sprite_names(chunk_index: int, step_s: int):
    base = f'timeline_{chunk_index}_{step_s}s'
    return f'{base}.jpg', f'{base}.json'


def probe_keyframe_interval(path: str) -> Optional[float]:
    """Seconds between keyframes when they are regular and the first one is at the start of the chunk, else None."""
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-skip_frame', 'nokey', '-show_entries',
                            'frame=pts_time', '-of', 'csv=p=0', '-read_intervals', '%+10', path],
                           capture_output=True, text=True, timeout=30)
        times = [float(x.strip(',')) for x in r.stdout.split() if x.strip(',') not in ('', 'N/A')]
    except (ValueError, subprocess.SubprocessError, OSError):
        return None
    if len(times) < 3 or times[0] > 0.05:
        return None
    diffs = [b - a for a, b in zip(times, times[1:])]
    gop = diffs[0]
    if gop <= 0 or any(abs(d - gop) > 0.01 for d in diffs):
        return None
    return gop


def keyframes_land_on_marks(gop: Optional[float], base_s: int) -> bool:
    """True when a keyframe falls exactly on every `base_s` mark (gop divides base_s)."""
    if not gop or gop > base_s:
        return False
    ratio = base_s / gop
    return abs(ratio - round(ratio)) < 0.001


def _decode_keyframes_only(chunk_path: str, base_s: int, fc: str, maps: list, timeout: int) -> bool:
    """Two processes in a pipe: the first copies the packets and DROPS every one except the keyframe on each `base_s`
    mark (no decoding), the second decodes just those (100 per 10 min) and tiles them. The video is decoded once per
    tile instead of once per frame: about 18x less CPU on a 720p chunk. (`-bsf` is output-only in ffmpeg 5.1, hence the pipe.)"""
    # The pipeline's timestamps drift +0.011 s per 2-min segment (a keyframe at 120.011, 240.022, ...): a tight window
    # dropped every mark after the first segment (19 of 100 tiles). Keyframes are >= 0.4 s apart, so 0.2 s keeps one.
    bsf = f"noise=drop='not(key)+gt(mod(pts*tb+0.001\\,{base_s})\\,0.2)'"
    p1 = subprocess.Popen(['nice', '-n', '19', 'ffmpeg', '-v', 'error', '-an', '-i', chunk_path, '-map', '0:v', '-c', 'copy',
                           '-bsf:v', bsf, '-f', 'nut', '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        r2 = subprocess.run(['nice', '-n', '19', 'ffmpeg', '-v', 'error', '-y', '-threads', '1', '-f', 'nut', '-i', '-',
                             '-filter_complex', fc] + maps, stdin=p1.stdout, capture_output=True, text=True, timeout=timeout)
        p1.stdout.close()
        p1.wait(timeout=30)
    except (subprocess.SubprocessError, OSError):
        p1.kill()
        return False
    return r2.returncode == 0 and p1.returncode == 0


def build_sprites(chunk_path: str, out_dir: str, chunk_index: int, *, chunk_end_epoch: Optional[float] = None,
                  duration_s: Optional[float] = None, levels=LEVELS, timeout: int = 180, force_full: bool = False) -> dict:
    """Writes every level's sprite JPEG + tile map into `out_dir`; returns {step_s: tile_map}.
    Tile i of a level is the frame at i*step_s of the chunk (the time it is labelled with). Raises on ffmpeg failure.
    When the chunk has a keyframe on every smallest-step mark (the capture pipeline writes one every 0.4 s) only those
    keyframes are decoded; any other chunk, or any failure of that path, falls back to decoding everything."""
    duration = duration_s if duration_s is not None else probe_duration(chunk_path)
    tile_w, tile_h = tile_size_for(*probe_size(chunk_path))
    os.makedirs(out_dir, exist_ok=True)
    chains, maps, tmps, geom = [], [], [], {}
    n = len(levels)
    split = ''.join(f'[a{i}]' for i in range(n))
    for i, (step_s, cols) in enumerate(levels):
        count = max(1, min(math.ceil(duration / step_s), CHUNK_S // step_s))
        cols_, rows = grid_for(step_s, cols)
        geom[step_s] = (count, cols_, rows)
        chains.append(f'[a{i}]fps=1/{step_s}:round=down,scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease:flags=fast_bilinear,pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2:black,tile={cols_}x{rows},format=yuvj420p[o{i}]')
        tmp = os.path.join(out_dir, f'.tmp_{chunk_index}_{step_s}s.jpg')
        tmps.append(tmp)
        maps += ['-map', f'[o{i}]', '-frames:v', '1', '-q:v', '6', tmp]
    fc = f'[0:v]split={n}{split};' + ';'.join(chains)
    base_s = min(step for step, _ in levels)
    decode = 'full'
    if not force_full and all(step % base_s == 0 for step, _ in levels) and keyframes_land_on_marks(probe_keyframe_interval(chunk_path), base_s):
        if _decode_keyframes_only(chunk_path, base_s, fc, maps, timeout) and all(os.path.exists(t) for t in tmps):
            decode = 'keyframes'
        else:
            for t in tmps:
                _rm(t)
    if decode == 'full':
        cmd = ['nice', '-n', '19', 'ffmpeg', '-v', 'error', '-y', '-an', '-i', chunk_path, '-filter_complex', fc] + maps
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not all(os.path.exists(t) for t in tmps):
            for t in tmps:
                _rm(t)
            raise RuntimeError(f'ffmpeg sprite failed for {chunk_path}: {r.stderr.strip()[-300:]}')
    out = {}
    for (step_s, _), tmp in zip(levels, tmps):
        count, cols_, rows = geom[step_s]
        jpg, js = (os.path.join(out_dir, x) for x in sprite_names(chunk_index, step_s))
        os.replace(tmp, jpg)
        tile_map = {
            'step_s': step_s, 'tile_w': tile_w, 'tile_h': tile_h, 'cols': cols_, 'rows': rows,
            'count': count, 'duration_s': round(duration, 1), 'chunk_end': chunk_end_epoch,
            'chunk_start': (chunk_end_epoch - duration) if chunk_end_epoch else None,
            'decode': decode,
        }
        tmpj = js + '.tmp'
        with open(tmpj, 'w') as f:
            json.dump(tile_map, f)
        os.replace(tmpj, js)
        out[step_s] = tile_map
    return out


def probe_duration(path: str) -> float:
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                       capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(f'ffprobe could not read {path}: {r.stderr.strip()[-200:]}')


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass
