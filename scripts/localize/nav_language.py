#!/usr/bin/env python3
"""Does the nav (tab-bar underline) fingerprint hold across UI languages? (TASK-133, 2026-10-19)

Runs the deployed Localize cascade on frames named `<lang>_<node>.jpg` against the base `stb_tv` node
fingerprints resolved through a variant (`node_overrides`, same as NavigationExecutor), and prints per frame
the predicted node, right / wrong / unknown, and the measured vs stored underline x / width.

    python3 scripts/localize/nav_language.py --dir FRAMES --ui stb_tv --variant vip7002w-6.04

Reads the database of the shell it runs in: run it on vpt-pi1 (/opt/virtualpytest), like audit.py.
"""
import argparse
import glob
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--ui', default='stb_tv')
    ap.add_argument('--variant')
    ap.add_argument('--team', default=bench.DEFAULT_TEAM)
    a = ap.parse_args()
    import copy
    import cv2
    bench._env()
    db = bench._db()
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    from backend_host.src.services.navigation.navigation_executor import run_localize_cascade
    from shared.src.lib.utils.navigation_graph import with_base_corrections
    ui = db.table('userinterfaces').select('id').eq('team_id', a.team).eq('name', a.ui).execute().data[0]['id']
    over = {}
    if a.variant:
        v = (db.table('userinterface_variants').select('node_overrides').eq('team_id', a.team)
             .eq('userinterface_id', ui).eq('name', a.variant).execute().data or [])
        over = (v[0]['node_overrides'] if v else {}) or {}
    node_fps = []
    for n in bench._node_fps(db, a.team, a.ui):
        e = over.get(n['node_id']) or {}
        if e.get('disabled'):
            continue
        fp = n['fingerprint']
        if isinstance(e.get('fingerprint'), dict):
            fp = copy.deepcopy(with_base_corrections(e['fingerprint'], fp))
        n['fingerprint'] = fp
        node_fps.append(n)
    labels = {n['node_id']: n['label'] for n in node_fps}
    helpers = ImageHelpers(None, None)
    print('lang | expected | got | result | best candidate | live x/w | stored x/w')
    for p in sorted(glob.glob(os.path.join(a.dir, '*.jpg'))):
        lang, _, exp = os.path.basename(p)[:-4].partition('_')
        img = cv2.imread(p)
        r, verdict, _m = run_localize_cascade(helpers, [img, img, img], node_fps, None, team_id=None,
                                               userinterface_name=a.ui)
        got = verdict.get('node_id') if verdict.get('kind') == 'node' else None
        got_label = labels.get(got, got)
        cand = (r.get('unconfirmed_candidate') or (r.get('candidates') or [{}])[0] or {}).get('node_id')
        cand_label = labels.get(cand, cand)
        res = 'unknown' if not got else ('right' if got_label == exp or got == exp else 'wrong')
        lf = (helpers.compute_fingerprint(img) or {}).get('focus') or {}
        sf = next((n['fingerprint'].get('focus') or {} for n in node_fps if n['label'] == exp or n['node_id'] == exp), {})
        f = lambda d: f"{d.get('x', float('nan')):.3f}/{d.get('width', float('nan')):.3f}" if d else '-'
        print(f"{lang} | {exp} | {got_label or verdict.get('kind')} | {res} | {cand_label} | {f(lf)} | {f(sf)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
