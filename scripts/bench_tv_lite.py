#!/usr/bin/env python3
"""Measure what one capture ffmpeg costs in `full` and `lean` (tv_lite) mode (TASK-95).

N copies of the v4l2 branch of backend_host/scripts/run_ffmpeg.sh run side by side on a synthetic source: an
MJPEG 1280x720 clip decoded in real time (what a USB grabber delivers; `-re` paces it) instead of /dev/video0, a
sine tone as the audio, the same filter graph, the same libx264/mjpeg/aac settings and the same HLS options.
`full` writes captures at 5 fps, thumbnails at 5 fps and latest.jpg at 5 fps; `lean` writes captures and latest.jpg at 2 fps and no thumbnails.

Per run it reports CPU % (all ffmpeg processes together, in cores, and per stream), RSS and USS, and what was
written per second per stream: files, and bytes (every file ever created, counted from the capture numbers and the
HLS media sequence, times the mean size of the files on disk at the end; latest.jpg is rewritten in place and
counted by its rate).

  python3 scripts/bench_tv_lite.py --streams 4 8 16 --seconds 60 --out /tmp/bench.json
No host is touched. The output folder is created under --work (default: a temp dir) and removed afterwards.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

import psutil

FPS = 10  # the grabber's input_fps for a v4l2 device


def make_clip(path: str) -> None:
    """20 s of 1280x720 MJPEG with motion and detail (a noisy gradient + moving test pattern), looped by the run."""
    subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=size=1280x720:rate={FPS}',
         '-f', 'lavfi', '-i', f'mandelbrot=size=1280x720:rate={FPS}', '-filter_complex',
         '[0:v][1:v]blend=all_mode=average,noise=alls=12:allf=t[v]', '-map', '[v]', '-t', '20',
         '-c:v', 'mjpeg', '-q:v', '5', path], check=True)


def command(clip: str, out: str, lean: bool) -> list:
    cap_fps = 2 if lean else 5
    if lean:
        thm = f'[thm]fps={cap_fps},scale=320:180:flags=neighbor[latestout]'
    else:
        thm = '[thm]fps=5,scale=320:180:flags=neighbor,split=2[thumbout][latestout]'
    graph = ('[0:v]split=3[str][cap][thm];'
             f'[str]fps={FPS},scale=320:180:flags=fast_bilinear[streamout];'
             f'[cap]fps={cap_fps},scale=1280:720:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];{thm}')
    seg, cap, thumb = f'{out}/segments', f'{out}/captures', f'{out}/thumbnails'
    cmd = ['ffmpeg', '-loglevel', 'error', '-stats', '-y',
           '-fflags', '+nobuffer+genpts+flush_packets', '-re', '-stream_loop', '-1', '-i', clip,
           '-re', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
           '-filter_complex', graph,
           '-map', '[streamout]', '-map', '1:a',
           '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-b:v', '150k', '-maxrate', '200k',
           '-bufsize', '400k', '-x264opts', 'keyint=4:min-keyint=4:no-scenecut:bframes=0', '-pix_fmt', 'yuv420p',
           '-profile:v', 'baseline', '-level', '3.0', '-c:a', 'aac', '-b:a', '32k', '-ar', '48000', '-ac', '2',
           '-f', 'tee',
           f'[f=hls:select=0,1:onfail=abort:hls_time=0.4:hls_list_size=300:hls_delete_threshold=300:'
           f'hls_flags=delete_segments+omit_endlist+split_by_time+program_date_time:start_number=0:'
           f'hls_segment_filename={seg}/segment_%09d.ts]{seg}/output.m3u8',
           '-map', '[captureout]', '-fps_mode', 'passthrough', '-c:v', 'mjpeg', '-q:v', '8', '-f', 'image2',
           '-atomic_writing', '1', '-start_number', '0', f'{cap}/capture_%09d.jpg']
    if not lean:
        cmd += ['-map', '[thumbout]', '-fps_mode', 'passthrough', '-c:v', 'mjpeg', '-q:v', '8', '-f', 'image2',
                '-atomic_writing', '1', '-start_number', '0', f'{thumb}/capture_%09d_thumbnail.jpg']
    cmd += ['-map', '[latestout]', '-fps_mode', 'passthrough', '-c:v', 'mjpeg', '-q:v', '8', '-f', 'image2',
            '-update', '1', '-atomic_writing', '1', f'{thumb}/latest.jpg']
    return cmd


def newest_number(folder: str, prefix: str, suffix: str) -> int:
    best = -1
    try:
        for name in os.listdir(folder):
            if name.startswith(prefix) and name.endswith(suffix):
                try:
                    best = max(best, int(name[len(prefix):len(name) - len(suffix)]))
                except ValueError:
                    pass
    except OSError:
        pass
    return best + 1


def mean_size(folder: str, suffix: str) -> float:
    sizes = []
    try:
        for name in os.listdir(folder):
            if name.endswith(suffix) and name != 'latest.jpg':
                try:
                    sizes.append(os.path.getsize(os.path.join(folder, name)))
                except OSError:
                    pass
    except OSError:
        pass
    return statistics.mean(sizes) if sizes else 0.0


def run(n: int, lean: bool, seconds: int, warmup: int, clip: str, work: str) -> dict:
    root = os.path.join(work, f'{"lean" if lean else "full"}_{n}')
    procs = []
    for i in range(n):
        out = os.path.join(root, f'dev{i}')
        for d in ('segments', 'captures', 'thumbnails'):
            os.makedirs(os.path.join(out, d))
        procs.append(subprocess.Popen(command(clip, out, lean), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    ps = [psutil.Process(p.pid) for p in procs]
    time.sleep(warmup)
    alive = [p for p in procs if p.poll() is None]
    if len(alive) != n:
        for p in procs:
            p.kill()
        raise SystemExit(f'only {len(alive)} of {n} ffmpeg processes survived the warm-up')
    t0 = time.time()
    cpu0 = sum(sum(p.cpu_times()[:2]) for p in ps)
    n0 = [(newest_number(os.path.join(root, f'dev{i}', 'captures'), 'capture_', '.jpg'),
           newest_number(os.path.join(root, f'dev{i}', 'thumbnails'), 'capture_', '_thumbnail.jpg'),
           newest_number(os.path.join(root, f'dev{i}', 'segments'), 'segment_', '.ts')) for i in range(n)]
    rss, uss = [], []
    while time.time() - t0 < seconds:
        time.sleep(2)
        rss.append(sum(p.memory_info().rss for p in ps) / 1e6)
        try:
            uss.append(sum(p.memory_full_info().uss for p in ps) / 1e6)
        except (psutil.Error, AttributeError):
            pass
    dt = time.time() - t0
    cpu = (sum(sum(p.cpu_times()[:2]) for p in ps) - cpu0) / dt
    n1 = [(newest_number(os.path.join(root, f'dev{i}', 'captures'), 'capture_', '.jpg'),
           newest_number(os.path.join(root, f'dev{i}', 'thumbnails'), 'capture_', '_thumbnail.jpg'),
           newest_number(os.path.join(root, f'dev{i}', 'segments'), 'segment_', '.ts')) for i in range(n)]
    d0 = os.path.join(root, 'dev0')
    cap_b, thm_b, seg_b = (mean_size(os.path.join(d0, 'captures'), '.jpg'), mean_size(os.path.join(d0, 'thumbnails'), '_thumbnail.jpg'),
                           mean_size(os.path.join(d0, 'segments'), '.ts'))
    lat_b = os.path.getsize(os.path.join(d0, 'thumbnails', 'latest.jpg')) if os.path.exists(os.path.join(d0, 'thumbnails', 'latest.jpg')) else 0
    caps = sum(b[0] - a[0] for a, b in zip(n0, n1)) / dt / n
    thms = sum(b[1] - a[1] for a, b in zip(n0, n1)) / dt / n
    segs = sum(b[2] - a[2] for a, b in zip(n0, n1)) / dt / n
    lat = 2 if lean else 5
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    shutil.rmtree(root, ignore_errors=True)
    return {
        'mode': 'lean' if lean else 'full', 'streams': n, 'seconds': round(dt),
        'cpu_cores_total': round(cpu, 2), 'cpu_cores_per_stream': round(cpu / n, 3),
        'rss_mb_per_stream': round(statistics.mean(rss) / n, 1), 'uss_mb_per_stream': round(statistics.mean(uss) / n, 1) if uss else None,
        'files_per_s_per_stream': round(caps + thms + segs + (lat if lat_b else 0), 1),
        'captures_per_s': round(caps, 2), 'thumbs_per_s': round(thms, 2), 'segments_per_s': round(segs, 2), 'latest_per_s': lat,
        'kb_per_s_per_stream': round((caps * cap_b + thms * thm_b + segs * seg_b + lat * lat_b) / 1000, 1),
        'kb_per_s_split': {'captures': round(caps * cap_b / 1000, 1), 'thumbnails': round(thms * thm_b / 1000, 1),
                           'segments': round(segs * seg_b / 1000, 1), 'latest': round(lat * lat_b / 1000, 1)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--streams', type=int, nargs='+', default=[4, 8, 16])
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--warmup', type=int, default=12)
    ap.add_argument('--work', default=None)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    work = args.work or tempfile.mkdtemp(prefix='bench_tv_lite_')
    os.makedirs(work, exist_ok=True)
    clip = os.path.join(work, 'clip.mkv')
    make_clip(clip)
    results = []
    for n in args.streams:
        for lean in (False, True):
            r = run(n, lean, args.seconds, args.warmup, clip, work)
            results.append(r)
            print(json.dumps(r), flush=True)
            time.sleep(3)
    if args.out:
        with open(args.out, 'w') as f:
            json.dump(results, f, indent=1)
    shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
