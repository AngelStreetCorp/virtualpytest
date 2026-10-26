#!/usr/bin/env python3
"""Cheap Tier-2 regression on the 22 cold-pulled frames (TASK-107 goal 8; was cheap_23_v2.py, run by hand).

Drives the production `MonitorLocalizer._screen_state` (the four Tier-2 checks, each with its own
input: a window of motion.pct for `loaded`, the frame for `overlay`, is_media + pct for `playback`,
OCR tokens for `error`) over the rows of scripts/localize/cheap23.json, and keeps the three gaps the
hand-run check found closed:

  playback_without_is_media  a row run with is_media=None must abstain ('unknown'); run with the
                             interface's media flag it must answer (playing / not_applicable)
  error_without_ocr          error(None) must abstain ('unknown'); with the OCR pass it must answer
  overlay_over_firing        a plain screen must never read tooltip / keyboard / notification
                             (/ popup on a row that has no dialog)

    python3 scripts/localize/cheap23.py [--set DIR]      # frames in <set>/frames/cheap23/<id>.jpg
    python3 scripts/localize/bench.py cheap23-import --src DIR   # once: copy the frames into the set

`bench.py run` (and so the nightly timer) runs it too and puts the result in the report.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import deque
from typing import Any, Dict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

ROWS_FILE = os.path.join(os.path.dirname(__file__), 'cheap23.json')
GAPS = ('playback_without_is_media', 'error_without_ocr', 'overlay_over_firing')


def run(frame_dir: str) -> Dict[str, Any]:
    import cv2
    from backend_host.scripts.monitor_localize import MonitorLocalizer
    from shared.src.lib.ai import screen_state_cv as scv
    rows = json.load(open(ROWS_FILE))['rows']
    ml = MonitorLocalizer(team_id='cheap23')
    started = time.perf_counter()
    out_rows, fields_ok, fields_n = [], {}, {}
    gaps = {g: [] for g in GAPS}
    for r in rows:
        img = cv2.imread(os.path.join(frame_dir, f"{r['id']}.jpg"))
        if img is None:
            out_rows.append({'id': r['id'], 'unreachable': True})
            continue
        win = r['pct_window']
        motion = {'kind': 'static', 'state': 'static', 'pct': win[-1]}
        ml._pct_window['d1'] = deque(win, maxlen=8)
        with_media = ml._screen_state(img, motion, is_media=r['is_media'], device_id='d1') or {}
        no_media = scv.playback(None, win[-1])
        no_ocr = scv.error(None)
        exp = r['expect']
        checks = {
            'loaded': with_media.get('loaded') == exp['loaded'],
            'overlay': with_media.get('overlay') not in exp['overlay_not'],
            'playback': with_media.get('playback') == exp['playback_with_media'],
            # on a media surface the monitor skips OCR (a broadcast bears no error keyword): error abstains
            'error': with_media.get('error') == (exp['error'] if not r['is_media'] else 'unknown'),
        }
        for f, ok in checks.items():
            fields_ok[f] = fields_ok.get(f, 0) + int(ok)
            fields_n[f] = fields_n.get(f, 0) + 1
        if no_media != 'unknown' or with_media.get('playback') != exp['playback_with_media']:
            gaps['playback_without_is_media'].append(r['id'])
        if no_ocr != 'unknown' or (not r['is_media'] and with_media.get('error') in (None, 'unknown')):
            gaps['error_without_ocr'].append(r['id'])
        if not checks['overlay']:
            gaps['overlay_over_firing'].append(f"{r['id']}={with_media.get('overlay')}")
        out_rows.append({'id': r['id'], 'actual': with_media, 'playback_no_media': no_media, 'checks': checks})
    elapsed = round(time.perf_counter() - started, 2)
    reachable = sum(1 for r in out_rows if not r.get('unreachable'))
    return {'ran_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'seconds': elapsed, 'frames': len(rows), 'reachable': reachable,
            'fields': {f: {'ok': fields_ok[f], 'n': fields_n[f]} for f in fields_ok},
            'gaps_open': {g: v for g, v in gaps.items() if v}, 'rows': out_rows}


def summary(res: Dict[str, Any]) -> str:
    fields = ', '.join(f"{f} {v['ok']}/{v['n']}" for f, v in res['fields'].items())
    gaps = '; '.join(f"{g}: {', '.join(v[:4])}" for g, v in res['gaps_open'].items()) or 'none'
    return (f"cheap Tier-2 check: {res['reachable']}/{res['frames']} frames in {res['seconds']} s — {fields}; "
            f"gaps open: {gaps}")


def main() -> int:
    import argparse
    sys.path.insert(0, os.path.dirname(__file__))
    import bench
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', default=bench.DEFAULT_SET)
    a = ap.parse_args()
    res = run(os.path.join(a.set, 'frames', 'cheap23'))
    print(summary(res))
    return 1 if res['gaps_open'] or res['reachable'] < res['frames'] else 0


if __name__ == '__main__':
    sys.exit(main())
