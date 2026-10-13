#!/usr/bin/env python3
"""freeze_injection.py — real freeze examples for the av-fault family (TASK-27, 2026-10-05).

Every freeze strip the monitor recorded so far was a false alarm (menus, still screens, moving
video), so no model could learn what a real freeze looks like. This script makes real ones on a
VNC host: ``ffplay`` plays an HLS stream full-screen on the host's display, the player is frozen
with SIGSTOP (no pause icon: the picture just stops, a true "video got stuck") and resumed with
SIGCONT. Three frames per phase are copied from the host's own capture, rendered with
``freeze_strip.render_strip`` (the monitor's strip format) and labelled from what the script did:
``{"incident_type": "freeze"}`` for a frozen phase, ``{"incident_type": null, "static_screen":
false}`` (moving) for a playing phase. ``label_source='run'``; ``source_ref.experiment =
freeze_injection``.

It does not need the monitor (2026-10-05: the monitor's freeze incident was stuck "ongoing" for
hours on the VNC hosts, so a frozen player raised no alert). A phase whose frames do not show
what it should (a playing phase that does not move, a frozen phase that does) is dropped.

Two steps, because a VNC host has no training bucket:

    # on the VNC host, as vpt_user, with a lease (vpt-lease claim ... --kind run):
    venv/bin/python features/ai-dataset/scripts/freeze_injection.py collect --out /tmp/freeze_strips --cycles 4
    # copy /tmp/freeze_strips to the server, then there (as vpt_user with the .env loaded):
    venv/bin/python features/ai-dataset/scripts/freeze_injection.py record --in /tmp/freeze_strips --team <uuid>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
if os.path.isdir(os.path.join(_REPO_ROOT, 'shared')) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DEFAULT_STREAM = 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8'  # Big Buck Bunny (HLS)
HOT = '/var/www/html/stream/capture/hot/captures'
PLAY_TIMES = (0, 10, 20)       # seconds: three frames of a playing phase
FREEZE_TIMES = (0, 35, 70)     # seconds: three frames of a 70 s freeze (a freeze alert needs ~30 s+)
SETTLE_S = 4                   # after SIGSTOP / SIGCONT: let the capture catch up before the first frame
MOVING_MIN_PCT = 20.0          # a playing phase must change at least this much between frames
FROZEN_MAX_PCT = 1.0           # a frozen phase must change at most this much (after SETTLE_S)


def change_pct(a: str, b: str) -> float:
    """Share of pixels (in %) that change by more than 20 grey levels between two frames."""
    import cv2
    import numpy as np
    ia, ib = cv2.imread(a, 0), cv2.imread(b, 0)
    return round(float((np.abs(ia.astype(int) - ib.astype(int)) > 20).mean()) * 100, 2)


def phase_ok(frozen: bool, diffs) -> bool:
    return max(diffs) <= FROZEN_MAX_PCT if frozen else min(diffs) >= MOVING_MIN_PCT


def _newest(folder: str) -> str:
    return max((f for f in glob.glob(folder + '/capture_*.jpg') if 'thumb' not in f), key=os.path.getmtime)


def _grab(folder: str, tmp: str, times) -> list:
    out, t0 = [], time.time()
    for t in times:
        time.sleep(max(0.0, t0 + t - time.time()))
        dst = os.path.join(tmp, f'{len(os.listdir(tmp)):04d}.jpg')
        shutil.copy(_newest(folder), dst)
        out.append((dst, round(time.time() - t0, 1)))
    return out


def _write(out: str, frames, frozen: bool, stream: str, phase: str) -> bool:
    import cv2
    from shared.src.lib.ai import freeze_strip as fs
    diffs = [change_pct(frames[i][0], frames[i + 1][0]) for i in range(len(frames) - 1)]
    if not phase_ok(frozen, diffs):
        print(f'{phase}: dropped, frames do not show a {"freeze" if frozen else "moving picture"} (diffs {diffs} %)')
        return False
    duration_ms = int(frames[-1][1] * 1000)
    jpeg = fs.render_strip([(cv2.imread(p), t) for p, t in frames], fs._footer_text(duration_ms if frozen else 0, diffs))
    meta = {'file': f'{phase}.jpg',
            'truth': {'incident_type': 'freeze'} if frozen else {'incident_type': None, 'static_screen': False},
            'model_answer': {'incident_type': 'freeze' if frozen else None, 'evidence': 'strip',
                             'duration_ms': duration_ms, 'diffs': diffs, 'frames': [t for _p, t in frames]},
            'source_ref': {'experiment': 'freeze_injection', 'host': os.uname().nodename, 'stream': stream,
                           'phase': phase, 'method': 'ffplay SIGSTOP'}}
    with open(os.path.join(out, meta['file']), 'wb') as f:
        f.write(jpeg)
    with open(os.path.join(out, 'meta.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(meta) + '\n')
    print(f'{phase}: {"freeze" if frozen else "moving"} diffs {diffs} %')
    return True


def collect(out: str, stream: str, cycles: int, display: str, folder: str) -> int:
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    tmp = out + '.frames'
    os.makedirs(tmp, exist_ok=True)
    env = dict(os.environ, DISPLAY=display, XAUTHORITY=os.path.expanduser('~/.Xauthority'))
    player = subprocess.Popen(['ffplay', '-fs', '-an', '-loglevel', 'error', '-window_title', 'vpt-freeze-injection',
                               stream], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    kept = 0
    try:
        time.sleep(20)  # the stream starts and fills the screen
        for c in range(cycles):
            kept += _write(out, _grab(folder, tmp, PLAY_TIMES), False, stream, f'play{c}')
            os.kill(player.pid, signal.SIGSTOP)
            time.sleep(SETTLE_S)
            kept += _write(out, _grab(folder, tmp, FREEZE_TIMES), True, stream, f'freeze{c}')
            os.kill(player.pid, signal.SIGCONT)
            time.sleep(SETTLE_S + 4)
    finally:
        player.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'kept {kept} strips in {out}')
    return 0


def record(folder: str, team_id: str) -> int:
    from shared.src.lib.ai import training_samples as ts
    if not ts.enabled():
        print('training data is not enabled here (TRAINING_DATA_ENABLED + training bucket): run record on the server')
        return 2
    for line in open(os.path.join(folder, 'meta.jsonl'), encoding='utf-8'):
        m = json.loads(line)
        with open(os.path.join(folder, m['file']), 'rb') as f:
            jpeg = f.read()
        sid = ts.record_sample(jpeg, family='av-fault', team_id=team_id, device_model='host_vnc',
                               model_answer=m['model_answer'], ground_truth=m['truth'], label_source='run',
                               source_ref=m['source_ref'], force=True, skip_cap=True)
        print(f"{m['source_ref']['phase']}: {m['truth']} -> {sid}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='Real freeze examples for the av-fault family (TASK-27).')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('collect', help='on a VNC host: play, freeze, write strips + meta.jsonl')
    c.add_argument('--out', default='/tmp/freeze_strips')
    c.add_argument('--stream', default=DEFAULT_STREAM)
    c.add_argument('--cycles', type=int, default=4, help='play + freeze cycles (about 1 min 45 s each)')
    c.add_argument('--display', default=':1')
    c.add_argument('--captures', default=HOT, help="the host's live capture folder")
    r = sub.add_parser('record', help='on the server: store the strips as av-fault samples')
    r.add_argument('--in', dest='in_dir', default='/tmp/freeze_strips')
    r.add_argument('--team', required=True)
    a = p.parse_args(argv)
    if a.cmd == 'collect':
        return collect(a.out, a.stream, a.cycles, a.display, a.captures)
    return record(a.in_dir, a.team)


if __name__ == '__main__':
    sys.exit(main())
