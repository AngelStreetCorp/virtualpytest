#!/usr/bin/env python3
"""Add `focus.tab_index` / `focus.tab_count` to the nav fingerprints of an interface (TASK-133).

The index of the tab that carries the underline is language independent; the underline x is not
(FINGERPRINT.md, "nav underline across languages, measured"). Base nodes: the index is read from the
node's stored screenshot, accepted only when that frame's underline agrees with the stored focus x
(+- FP_NAV_X_TOL). Variant overrides (a variant re-orders tabs and has no screenshot of its own): the
index is read from reference frames of the same layout (`--ref-frames DIR`, German `de_*.jpg` frames
of the variant's box), matched on the underline x. Only those two keys are written; the rest of the
fingerprint is untouched.

    python3 scripts/localize/backfill_tab_index.py --ui stb_tv --variant vip7002w-6.04 --ref-frames DIR [--apply]

Dry run by default; --apply writes the DB of the shell it runs in (run it on vpt-pi1) and saves the
old rows to --backup (JSON). Run again to confirm: an already filled node is skipped.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bench  # noqa: E402


def _nav(helpers, img):
    sig = helpers._focus_signature(img) if img is not None else None
    return sig if sig and sig.get('kind') == 'nav' and sig.get('tab_index') is not None else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ui', default='stb_tv')
    ap.add_argument('--variant', action='append', default=[])
    ap.add_argument('--ref-frames')
    ap.add_argument('--team', default=bench.DEFAULT_TEAM)
    ap.add_argument('--backup', default='/tmp/tab_index_backup.json')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    bench._env()
    import cv2
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    helpers = ImageHelpers(None, None)
    tol = helpers.FP_NAV_X_TOL
    db = bench._db()
    ui = db.table('userinterfaces').select('id').eq('team_id', a.team).eq('name', a.ui).execute().data[0]['id']
    trees = [t['id'] for t in db.table('navigation_trees').select('id').eq('team_id', a.team).eq('userinterface_id', ui).execute().data]
    refs = []
    for p in sorted(glob.glob(os.path.join(a.ref_frames or '', '*.jpg'))):
        sig = _nav(helpers, cv2.imread(p))
        if sig:
            refs.append(sig)
    backup, changed = {'nodes': [], 'variants': []}, 0
    for r in db.table('navigation_nodes').select('tree_id, node_id, label, data').eq('team_id', a.team).in_('tree_id', trees).execute().data:
        data = r.get('data') or {}
        fp = data.get('fingerprint') or {}
        foc = fp.get('focus') or {}
        if foc.get('kind') != 'nav' or foc.get('tab_index') is not None:
            continue
        sig = _nav(helpers, bench._download(data['screenshot'])) if data.get('screenshot') else None
        if not sig and str(r.get('label') or '').startswith('home'):   # unreadable screenshot: the Home bar reference frames
            idx = {(s['tab_index'], s['tab_count']) for s in refs if abs(s['x'] - foc['x']) <= tol}
            if len(idx) == 1:
                sig = {'x': foc['x'], 'tab_index': next(iter(idx))[0], 'tab_count': next(iter(idx))[1]}
        ok = bool(sig and abs(sig['x'] - foc['x']) <= tol)
        print(f"  node {r['node_id'][:22]:<22} {str(r.get('label'))[:22]:<22} x={foc['x']} -> "
              + (f"index {sig['tab_index']}/{sig['tab_count']}" if ok else f"SKIPPED (screenshot x {sig and sig['x']})"))
        if ok:
            backup['nodes'].append({'tree_id': r['tree_id'], 'node_id': r['node_id'], 'data': data})
            new = copy.deepcopy(data)
            new['fingerprint']['focus'].update(tab_index=sig['tab_index'], tab_count=sig['tab_count'])
            changed += 1
            if a.apply:
                db.table('navigation_nodes').update({'data': new}).eq('team_id', a.team).eq('tree_id', r['tree_id']).eq('node_id', r['node_id']).execute()
    for name in a.variant:
        v = db.table('userinterface_variants').select('id, node_overrides').eq('team_id', a.team).eq('userinterface_id', ui).eq('name', name).execute().data[0]
        over = copy.deepcopy(v['node_overrides'] or {})
        touched = False
        for nid, e in over.items():
            foc = ((e or {}).get('fingerprint') or {}).get('focus') or {}
            if foc.get('kind') != 'nav' or foc.get('tab_index') is not None:
                continue
            hit = [s for s in refs if abs(s['x'] - foc['x']) <= tol]
            idx = {(s['tab_index'], s['tab_count']) for s in hit}
            print(f"  variant {name} {nid[:22]:<22} x={foc['x']} -> " + (f"index {idx}" if len(idx) == 1 else f"SKIPPED ({idx or 'no ref'})"))
            if len(idx) == 1:
                foc['tab_index'], foc['tab_count'] = next(iter(idx))
                touched = True
                changed += 1
        if touched:
            backup['variants'].append({'id': v['id'], 'node_overrides': v['node_overrides']})
            if a.apply:
                db.table('userinterface_variants').update({'node_overrides': over}).eq('id', v['id']).execute()
    if a.apply:
        json.dump(backup, open(a.backup, 'w'))
    print(f"{changed} fingerprints {'written' if a.apply else 'would change'}" + (f", old rows in {a.backup}" if a.apply else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
