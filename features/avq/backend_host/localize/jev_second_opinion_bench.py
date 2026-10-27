#!/usr/bin/env python3
"""Jev as a second opinion on localize and borderline image/text verifications (TASK-47 G13).

OFFLINE benchmark. It changes nothing live: no device, no host, no production code is touched.
Data lives OUTSIDE the repo (default /tmp/claude-1000/locbench, override with LOCBENCH_DIR).

Stages (run in this order; every stage reads the files of the one before):
  nodes      node reference screenshots (DB read + object storage) -> fresh v6 fingerprints
  loc-items  labelled frames of a review bundle (scripts/jev_review `export`) -> localize items + truth
  loc-run    today's rule (ImageHelpers.identify_screen) and the rule + Jev, same items
  ver-items  every image / text check of the bundle's groups on every frame -> borderline items
  ver-label  (done by blind judges, see README) -> labels.json
  ver-run    today's rule (score >= threshold) and rule + Jev, same items
  report     the numbers

Environment: VPT_TEAM_ID, JEV_URL, JEV_API_KEY (read from ~/ghosty-sessions/.env when unset, never
printed); MINIO_* for the node screenshots (the repo .env). The DB is read with SELECT only,
every query filtered by team_id.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
sys.path.insert(0, REPO)
DATA = os.environ.get('LOCBENCH_DIR', '/tmp/claude-1000/locbench')
BUNDLE = os.environ.get('LOCBENCH_BUNDLE', os.path.expanduser('~/jr'))
BORDER = 0.10                       # verification borderline band: |score - threshold| <= BORDER
LOC_UIS = tuple(filter(None, [os.environ.get('VPT_LOCALIZE_UI'), 'youtube-web', 'web_tv', 'iad_gui']))
GATES = (0.9, 0.8)
PRICE_IN = 0.042e-6                 # $ per input token (docs/agent/ai/JEV.md); decide() returns the real cost too


def _load_env():
    for path in (os.path.expanduser('~/ghosty-sessions/.env'), os.path.expanduser('~/virtualpytest/.env')):
        if os.path.exists(path):
            for line in open(path):
                m = re.match(r'^([A-Z0-9_]+)=(.*)$', line.strip())
                if m and m.group(1) not in os.environ:
                    os.environ[m.group(1)] = m.group(2).strip().strip('"\'')


def _path(*p):
    return os.path.join(DATA, *p)


def _write(name, obj):
    os.makedirs(DATA, exist_ok=True)
    with open(_path(name), 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def _read(name):
    with open(_path(name)) as f:
        return json.load(f)


# ---- DB (SELECT only, team filtered) -----------------------------------------------------------

def sql_rows(query: str):
    """Run a SELECT on the database VM; returns a list of dict rows."""
    wrapped = f"select coalesce(json_agg(t),'[]'::json) from ({query}) t"
    out = subprocess.run(['ssh', 'database', 'PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U supabase_admin '
                          '-d postgres -At -c ' + json.dumps(wrapped)], capture_output=True, text=True, timeout=120)
    if out.returncode:
        raise RuntimeError(out.stderr[:300])
    return json.loads(out.stdout.strip() or '[]')


def _helpers():
    """ImageHelpers with title translation off (the pivot is a network call; titles of one device are
    compared in the same language, so the normalised raw text is what the rule would use anyway)."""
    with contextlib.redirect_stdout(io.StringIO()):
        from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    h = ImageHelpers(None, None)
    h.title_pivot = lambda text: h._normalize_text((text or '').strip())
    return h


# ---- stage nodes -------------------------------------------------------------------------------

def stage_nodes(_a):
    import boto3
    import cv2
    from botocore.config import Config
    team = os.environ['VPT_TEAM_ID']
    s3 = boto3.client('s3', endpoint_url=os.environ['MINIO_ENDPOINT'], aws_access_key_id=os.environ['MINIO_ACCESS_KEY'],
                      aws_secret_access_key=os.environ['MINIO_SECRET_KEY'], region_name='us-east-1',
                      config=Config(connect_timeout=8, retries={'max_attempts': 1}))
    uis = "','".join(LOC_UIS)
    rows = sql_rows(f"select u.name ui, n.node_id, n.label, n.data->>'screenshot' shot from navigation_nodes n "
                    f"join navigation_trees t on t.id=n.tree_id join userinterfaces u on u.id=t.userinterface_id "
                    f"where n.team_id='{team}' and u.name in ('{uis}') and n.data->>'screenshot' is not null")
    h = _helpers()
    out, miss = defaultdict(dict), Counter()
    os.makedirs(_path('nodes'), exist_ok=True)
    for r in rows:
        m = re.search(r'(navigation/.+)$', r['shot'])
        if not m:
            miss['bad_key'] += 1
            continue
        dest = _path('nodes', f"{r['ui']}__{r['node_id']}.jpg")
        try:
            if not os.path.exists(dest):
                s3.download_file('virtualpytest', m.group(1), dest)
        except Exception:
            miss['download'] += 1
            continue
        img = cv2.imread(dest)
        if img is None:
            miss['unreadable'] += 1
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            fp = h.compute_fingerprint(img)
        if fp and r['node_id'] not in out[r['ui']]:
            out[r['ui']][r['node_id']] = {'node_id': r['node_id'], 'label': r['label'], 'fingerprint': fp,
                                          'image': dest}
    _write('nodes.json', {ui: list(v.values()) for ui, v in out.items()})
    print({ui: len(v) for ui, v in out.items()}, dict(miss))


# ---- stage loc-items ---------------------------------------------------------------------------

def _groups(ui):
    p = os.path.join(BUNDLE, 'ui', ui, 'groups.json')
    return json.load(open(p)) if os.path.exists(p) else []


def stage_loc_items(_a):
    """Truth per frame. human rows: the exact node (ground_truth.node). agreed rows (run label and AI
    teacher agree): any member node of the labelled group. disputed rows are left out (no trusted truth).
    A truth with no fingerprinted node in the candidate set = the right answer is to ABSTAIN.
    Every frame also gets a leave-one-out twin (id ':loo'): its true node(s) removed from the candidate set,
    so the screen is unknown to the tree and the right answer is again to abstain."""
    nodes = _read('nodes.json')
    items = []
    for line in open(os.path.join(BUNDLE, 'rows.jsonl')):
        r = json.loads(line)
        ui = r['userinterface']
        if r['set'] not in ('human', 'agreed') or ui not in nodes:
            continue
        cand = {n['node_id'] for n in nodes[ui]}
        gt = r['ground_truth']
        groups = {g['node_id']: [m['node_id'] for m in g['members']] for g in _groups(ui)}
        if r['set'] == 'human' and gt.get('node'):
            truth, kind = [gt['node']], 'node'
        else:
            truth, kind = groups.get(gt.get('node_id')) or [gt.get('node_id')], 'group'
        hit = [t for t in truth if t in cand]
        base = {'id': r['id'], 'ui': ui, 'frame': os.path.join(BUNDLE, 'frames', r['id'] + '.jpg'),
                'set': r['set'], 'truth_label': gt.get('node_label') or gt.get('label'), 'truth_kind': kind,
                'truth_nodes': hit, 'expect': 'node' if hit else 'abstain', 'removed': []}
        items.append(base)
        if hit:   # leave-one-out: the same frame, its true node(s) taken out of the tree = an unknown screen
            items.append({**base, 'id': r['id'] + ':loo', 'expect': 'abstain', 'removed': hit})
    _write('loc_items.json', items)
    print(len(items), Counter((i['ui'], i['expect']) for i in items))


# ---- Jev ---------------------------------------------------------------------------------------

class Jev:
    """POST {server}/server/ai/decide, usage text.decision, profile jev, log:false."""
    def __init__(self):
        u = urllib.parse.urlsplit(os.environ['JEV_URL'])
        self.url = f'{u.scheme}://{u.netloc}'          # the server origin; the route is /server/ai/decide
        self.key = os.environ['JEV_API_KEY']
        self.team = os.environ['VPT_TEAM_ID']
        self.calls, self.cost, self.ms = 0, 0.0, []

    def decide(self, state, questions, retries=2):
        body = {'team_id': self.team, 'usage': 'text.decision', 'profile': 'jev', 'log': False,
                'state': state, 'questions': questions}
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                req = urllib.request.Request(self.url + '/server/ai/decide', json.dumps(body).encode(),
                                             {'Content-Type': 'application/json', 'X-API-Key': self.key})
                res = json.loads(urllib.request.urlopen(req, timeout=60).read())
                self.calls += 1
                self.ms.append((time.time() - t0) * 1000)
                self.cost += float(res.get('cost') or 0)
                return res
            except Exception as e:  # noqa: BLE001
                err = str(e)
                time.sleep(1 + attempt)
        return {'success': False, 'error': err}


def _jev_probe():
    _load_env()
    return Jev()


# ---- stage loc-run -----------------------------------------------------------------------------

from backend_host.src.controllers.verification.jev_second_opinion import (  # noqa: E402  (production builders)
    LOC_INSTRUCTIONS, VER_Q, live_signature, loc_band, loc_question, text_state)


def loc_one(h, item, nodes):
    import cv2
    img = cv2.imread(item['frame'])
    cands_nodes = [n for n in nodes[item['ui']] if n['node_id'] not in set(item['removed'])]
    fps = [{'node_id': n['node_id'], 'label': n['label'], 'fingerprint': n['fingerprint']} for n in cands_nodes]
    with contextlib.redirect_stdout(io.StringIO()):
        res = h.identify_screen(img, fps)
    with contextlib.redirect_stdout(io.StringIO()):
        live = live_signature(h, img)
    cands = [{'node_id': c['node_id'], 'label': c['label'], 'confidence': c.get('confidence'),
              'dist': c.get('dist')} for c in (res.get('candidates') or [])]
    band = loc_band(cands)
    state, options = loc_question(h, live, cands_nodes, cands)
    return {'id': item['id'], 'ui': item['ui'], 'band': band, 'rule_candidates': cands[:6],
            'rule_state': res.get('state'), 'state': state, 'options': options,
            'expect': item['expect'], 'truth_nodes': item['truth_nodes']}


def stage_loc_run(a):
    _load_env()
    nodes = _read('nodes.json')
    items = _read('loc_items.json')
    h = _helpers()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        recs = list(pool.map(lambda it: loc_one(h, it, nodes), items))
    print(f'rule done {len(recs)} items in {time.time() - t0:.0f}s', Counter(r['band'] for r in recs))
    jev = Jev()
    todo = [r for r in recs if r['band'] != 'single']

    def ask(r):
        crit = {o['id']: o['facts'] for o in r['options']}
        res = jev.decide(r['state'], {'choice': {'type': 'choice', 'instructions': LOC_INSTRUCTIONS, 'criteria': crit}})
        ans = (res.get('answers') or {}).get('choice') or {}
        r['jev'] = {'ok': bool(res.get('success')) and ans.get('choice') in crit, 'choice': ans.get('choice'),
                    'confidence': ans.get('confidence'), 'probabilities': ans.get('probabilities'),
                    'cost': res.get('cost'), 'ms': res.get('ms'), 'error': res.get('error')}
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(ask, todo))
    _write('loc_results.json', {'recs': recs, 'jev_calls': jev.calls, 'jev_cost': jev.cost, 'jev_ms': jev.ms})
    print('jev calls', jev.calls, 'cost', jev.cost)


# ---- report ------------------------------------------------------------------------------------

def loc_outcome(rec, answer):
    """answer: a node_id, or None = abstain. -> 'right' | 'wrong' | 'abstain' (a missed node)."""
    if rec['expect'] == 'abstain':
        return 'right' if answer is None else 'wrong'
    if answer is None:
        return 'abstain'
    return 'right' if answer in rec['truth_nodes'] else 'wrong'


def loc_rule_answer(rec):
    c = rec['rule_candidates']
    return c[0]['node_id'] if len(c) == 1 else None


def loc_jev_answer(rec, gate):
    j = rec.get('jev') or {}
    if rec['band'] != 'single' and j.get('ok') and (j.get('confidence') or 0) >= gate:
        return None if j['choice'] == 'none' else j['choice']
    return loc_rule_answer(rec)


def report_loc(_a=None):
    res = _read('loc_results.json')
    recs = res['recs']
    groups = {'known screens (frame of a node in the tree)': [r for r in recs if r['expect'] == 'node'],
              'unknown screens (leave-one-out twins + non-node)': [r for r in recs if r['expect'] == 'abstain'],
              'ALL': recs}
    print('\n## Localize  (right / wrong / abstain; abstain on an unknown screen counts as right)')
    print('| set | n | rule R/W/A | +Jev 0.9 R/W/A | +Jev 0.8 R/W/A | new wrong @0.9 | new wrong @0.8 | fixed @0.9 | fixed @0.8 |')
    print('|---|---|---|---|---|---|---|---|---|')
    for name, rs in groups.items():
        row = [name, len(rs)]
        base = Counter(loc_outcome(r, loc_rule_answer(r)) for r in rs)
        row.append(f"{base['right']}/{base['wrong']}/{base['abstain']}")
        nw, fx = [], []
        for g in GATES:
            c = Counter(loc_outcome(r, loc_jev_answer(r, g)) for r in rs)
            row.append(f"{c['right']}/{c['wrong']}/{c['abstain']}")
            nw.append(sum(1 for r in rs if loc_outcome(r, loc_rule_answer(r)) != 'wrong'
                          and loc_outcome(r, loc_jev_answer(r, g)) == 'wrong'))
            fx.append(sum(1 for r in rs if loc_outcome(r, loc_rule_answer(r)) != 'right'
                          and loc_outcome(r, loc_jev_answer(r, g)) == 'right'))
        print('| ' + ' | '.join(map(str, row + nw + fx)) + ' |')
    by_ui = Counter(r['ui'] for r in recs)
    print('\nitems per interface:', dict(by_ui), '| bands:', dict(Counter(r['band'] for r in recs)))
    jr = [r for r in recs if r.get('jev')]
    print(f"Jev calls {res['jev_calls']}, cost ${res['jev_cost']:.5f}, "
          f"latency p50 {sorted(res['jev_ms'])[len(res['jev_ms']) // 2]:.0f} ms, p95 "
          f"{sorted(res['jev_ms'])[int(len(res['jev_ms']) * .95)]:.0f} ms" if res['jev_ms'] else 'no Jev calls')
    for g in GATES:   # the new-wrong cases, for the write-up
        for r in recs:
            if loc_outcome(r, loc_rule_answer(r)) != 'wrong' and loc_outcome(r, loc_jev_answer(r, g)) == 'wrong':
                j = r['jev']
                print(f"  new wrong @{g}: {r['id'][:8]} {r['ui']} expect={r['expect']} band={r['band']} "
                      f"jev={j['choice']} {j['confidence']}")


# ---- stage ver-items ---------------------------------------------------------------------------

def _matchers():
    sys.path.insert(0, REPO)
    from scripts.jev_review import matchers
    return matchers


def _checks_of(ui):
    """Every image / text check of every member node of the app's screen groups (bundle groups.json)."""
    out = []
    for g in _groups(ui):
        for m in g['members']:
            for c in m.get('checks') or []:
                out.append({**c, 'node_id': m['node_id'], 'node_label': m['label'], 'group': g['label'],
                            'ui': ui, 'base': os.path.join(BUNDLE, 'ui', ui)})
    return out


def _one_frame_checks(row):
    import cv2
    mt = _matchers()
    frame = cv2.imread(os.path.join(BUNDLE, 'frames', row['id'] + '.jpg'))
    ocr_cache, out = {}, []
    for c in _checks_of(row['userinterface']):
        thr = float(c.get('threshold') or mt.DEFAULT_THRESHOLD)
        if c['command'] == mt.TEXT_APPEAR:
            key = json.dumps(c.get('area'), sort_keys=True)
            if key not in ocr_cache:
                ocr_cache[key] = mt.ocr_area(frame, c.get('area'))
            res = mt.check_text(ocr_cache[key], c['name'], thr)
            res['ocr'] = ocr_cache[key][:200]
        elif c.get('reference_file') and c['command'] == mt.IMAGE_APPEAR:
            ref = cv2.imread(os.path.join(c['base'], c['reference_file']))
            if ref is None:
                continue
            res = mt.check_image(frame, ref, c.get('area'), thr)
        else:
            continue
        if abs(res['score'] - thr) <= BORDER:
            out.append({'frame_id': row['id'], 'set': row['set'], 'ui': row['userinterface'], 'kind': res['kind'],
                        'check': c['name'], 'node': c['node_label'], 'group': c['group'],
                        'area': c.get('area'), 'reference_file': (os.path.join(c['base'], c['reference_file'])
                                                                  if c.get('reference_file') else None),
                        'score': res['score'], 'threshold': thr, 'passed': res['passed'],
                        'ocr': res.get('ocr'), 'truth_group': (row['ground_truth'] or {}).get('label')})
    return out


def stage_ver_items(_a):
    _load_env()
    rows = [json.loads(l) for l in open(os.path.join(BUNDLE, 'rows.jsonl'))]
    with ThreadPoolExecutor(max_workers=5) as pool:
        per = list(pool.map(_one_frame_checks, rows))
    items = [dict(i, id=f"v{n:04d}") for n, i in enumerate(x for p in per for x in p)]
    _write('ver_items_all.json', items)
    print(len(items), Counter((i['kind'], i['passed']) for i in items), Counter(i['ui'] for i in items))


# ---- stage ver-prep: pick the items, draw what the blind judges look at -------------------------

PER_CHECK_CAP = 12       # the same check on many near-identical frames would dominate the set


def _compose(item, dest):
    import cv2
    import numpy as np
    frame = cv2.imread(os.path.join(BUNDLE, 'frames', item['frame_id'] + '.jpg'))
    area = item.get('area') or {}
    H, W = frame.shape[:2]
    sx, sy = W / 1280.0, H / 720.0
    x, y, w, h = [int(area.get(k, 0) * s) for k, s in (('x', sx), ('y', sy), ('width', sx), ('height', sy))]
    if not (w and h):
        x, y, w, h = 0, 0, W, H
    big = frame.copy()
    cv2.rectangle(big, (x, y), (x + w, y + h), (0, 0, 255), 3)
    if area.get('fx') is not None:
        fx, fy, fw, fh = [int(area[k] * s) for k, s in (('fx', sx), ('fy', sy), ('fwidth', sx), ('fheight', sy))]
        cv2.rectangle(big, (fx, fy), (fx + fw, fy + fh), (255, 128, 0), 2)
        x0, y0, x1, y1 = min(x, fx), min(y, fy), max(x + w, fx + fw), max(y + h, fy + fh)
    else:
        x0, y0, x1, y1 = x, y, x + w, y + h
    pad = 25
    crop = frame[max(0, y0 - pad):min(H, y1 + pad), max(0, x0 - pad):min(W, x1 + pad)]
    scale = max(1.0, min(500 / max(crop.shape[1], 1), 300 / max(crop.shape[0], 1)))
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    panels = [crop]
    if item.get('reference_file'):
        ref = cv2.imread(item['reference_file'])
        if ref is not None:
            rs = max(1.0, min(500 / ref.shape[1], 300 / ref.shape[0]))
            panels.append(cv2.resize(ref, None, fx=rs, fy=rs, interpolation=cv2.INTER_CUBIC))
    th = max(p.shape[0] for p in panels)
    row = np.full((th, sum(p.shape[1] + 10 for p in panels), 3), 255, np.uint8)
    cx = 0
    for p in panels:
        row[:p.shape[0], cx:cx + p.shape[1]] = p
        cx += p.shape[1] + 10
    full = cv2.resize(big, (960, int(960 * H / W)))
    width = max(row.shape[1], full.shape[1])
    canvas = np.full((row.shape[0] + full.shape[0] + 10, width, 3), 255, np.uint8)
    canvas[:row.shape[0], :row.shape[1]] = row
    canvas[row.shape[0] + 10:, :full.shape[1]] = full
    cv2.imwrite(dest, canvas)


def stage_ver_prep(_a):
    import random
    items = _read('ver_items_all.json')
    nodes = _read('nodes.json')
    rnd = random.Random(7)
    rnd.shuffle(items)
    taken, per = [], Counter()
    for it in items:
        if per[it['check']] < PER_CHECK_CAP:
            per[it['check']] += 1
            taken.append(it)
    taken.sort(key=lambda i: i['id'])
    os.makedirs(_path('ver_img'), exist_ok=True)
    for it in taken:
        by_label = {n['label']: n['node_id'] for n in nodes.get(it['ui'], [])}
        it['node_id'] = by_label.get(it['node'])
        _compose(it, _path('ver_img', it['id'] + '.png'))
    _write('ver_items.json', taken)
    print(len(taken), Counter((i['kind'], i['passed']) for i in taken))


# ---- stage ver-run -------------------------------------------------------------------------------

def ver_facts(h, mt, it, nodes):
    """The compact text state of one borderline check: score vs threshold, where it was found vs the
    expected area, the OCR text, and how close the node's stored fingerprint is to this frame."""
    import cv2
    frame = cv2.imread(os.path.join(BUNDLE, 'frames', it['frame_id'] + '.jpg'))
    area = it.get('area') or {}
    if it['kind'] == 'text':
        st = text_state(it['check'], it['score'], it['threshold'], it.get('ocr'), area)
    else:
        st = {'check_type': 'image template check', 'expected': f"reference image '{it['check']}'",
              'score': it['score'], 'threshold': it['threshold'],
              'score_minus_threshold': round(it['score'] - it['threshold'], 3)}
    if it['kind'] == 'image':
        ref = cv2.imread(it['reference_file'])
        sx, sy = frame.shape[1] / 1280.0, frame.shape[0] / 720.0
        a = mt.scale_area(area, sx, sy)
        rf = cv2.resize(ref, (max(1, round(ref.shape[1] * sx)), max(1, round(ref.shape[0] * sy)))) if (sx, sy) != (1, 1) else ref
        found, score, loc = mt.match_image(rf, frame, a, it['threshold'])
        if loc and a:
            dx, dy = loc['x'] - a['x'], loc['y'] - a['y']
            win = a if a.get('fx') is None else {'x': a['fx'], 'y': a['fy'], 'width': a['fwidth'], 'height': a['fheight']}
            inside = (win['x'] <= loc['x'] and loc['x'] + loc['width'] <= win['x'] + win['width']
                      and win['y'] <= loc['y'] and loc['y'] + loc['height'] <= win['y'] + win['height'])
            st['location'] = (f"best match at ({loc['x']},{loc['y']}), expected area at ({a['x']},{a['y']}) "
                              f"size {a['width']}x{a['height']}: offset ({dx},{dy}) px, "
                              f"{'inside' if inside else 'outside'} the search window")
        elif loc:
            st['location'] = f"best match at ({loc['x']},{loc['y']}) of a {frame.shape[1]}x{frame.shape[0]} frame (no area set)"
    nid = it.get('node_id')
    n = next((n for n in nodes.get(it['ui'], []) if n['node_id'] == nid), None)
    if n:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        d = h._region_dists(h._region_dhashes(gray), n['fingerprint'].get('regions') or {'full': n['fingerprint']['dhash']})
        st['node_fingerprint'] = (f"the node's stored screen is {d[0]} of 256 bits from this frame (14 or less = same "
                                  f"screen)" if d else "the node's stored screen has no comparable region")
    return st


def ver_jev_p(res):
    a = (res.get('answers') or {}).get('q') or {}
    return a.get('noul') if res.get('success') else None


def stage_ver_run(_a):
    _load_env()
    items = _read('ver_items.json')
    nodes = _read('nodes.json')
    labels = {}
    for fn in sorted(os.listdir(DATA)):
        if re.match(r'labels_\d+\.json$', fn):
            for r in _read(fn):
                labels[r['id']] = r['label']
    h, mt, jev = _helpers(), _matchers(), Jev()

    def one(it):
        with contextlib.redirect_stdout(io.StringIO()):
            st = ver_facts(h, mt, it, nodes)
        res = jev.decide(st, {'q': VER_Q})
        return {**it, 'label': labels.get(it['id']), 'state': st, 'jev_p': ver_jev_p(res), 'cost': res.get('cost'),
                'ms': res.get('ms'), 'error': res.get('error')}
    with ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(one, items))
    _write('ver_results.json', {'items': out, 'jev_calls': jev.calls, 'jev_cost': jev.cost, 'jev_ms': jev.ms})
    print('items', len(out), 'labelled', sum(1 for r in out if r['label']), 'jev calls', jev.calls, 'cost', jev.cost)


def ver_decision(it, gate):
    """pass/fail of the rule + Jev: Jev only when sure (p >= gate -> pass, p <= 1-gate -> fail)."""
    p = it.get('jev_p')
    if p is not None and p >= gate:
        return True
    if p is not None and p <= 1 - gate:
        return False
    return bool(it['passed'])


def report_ver(_a=None):
    res = _read('ver_results.json')
    items = [i for i in res['items'] if i.get('label') in ('yes', 'no')]
    unsure = sum(1 for i in res['items'] if i.get('label') not in ('yes', 'no'))
    print(f"\n## Verifications  (borderline: |score - threshold| <= {BORDER}; blind label yes/no; {unsure} unsure dropped)")
    print(f"items {len(items)}: label yes {sum(1 for i in items if i['label'] == 'yes')}, "
          f"no {sum(1 for i in items if i['label'] == 'no')}; "
          f"image {sum(1 for i in items if i['kind'] == 'image')}, text {sum(1 for i in items if i['kind'] == 'text')}")

    def tally(decide):
        ff = sum(1 for i in items if i['label'] == 'yes' and not decide(i))     # false fail
        fp = sum(1 for i in items if i['label'] == 'no' and decide(i))          # false pass
        return ff, fp, len(items) - ff - fp
    print('| arm | false fails | false passes | right |')
    print('|---|---|---|---|')
    ff, fp, ok = tally(lambda i: bool(i['passed']))
    print(f'| rule (score >= threshold) | {ff} | {fp} | {ok} |')
    for g in GATES:
        ff2, fp2, ok2 = tally(lambda i, g=g: ver_decision(i, g))
        fixed_ff = sum(1 for i in items if i['label'] == 'yes' and not i['passed'] and ver_decision(i, g))
        fixed_fp = sum(1 for i in items if i['label'] == 'no' and i['passed'] and not ver_decision(i, g))
        new_fp = sum(1 for i in items if i['label'] == 'no' and not i['passed'] and ver_decision(i, g))
        new_ff = sum(1 for i in items if i['label'] == 'yes' and i['passed'] and not ver_decision(i, g))
        called = sum(1 for i in items if i.get('jev_p') is not None and (i['jev_p'] >= g or i['jev_p'] <= 1 - g))
        print(f'| rule + Jev {g} | {ff2} | {fp2} | {ok2} |   (false fails fixed {fixed_ff}, false passes fixed {fixed_fp}, '
              f'NEW false passes {new_fp}, NEW false fails {new_ff}; Jev sure on {called}/{len(items)})')
    for g in GATES:   # distinct checks behind the counts (the same check repeats on near-identical frames)
        fixed = Counter(i['check'][:28] for i in items if i['label'] == 'no' and i['passed'] and not ver_decision(i, g))
        print(f'  false passes fixed @{g} by check: {dict(fixed)}')
    print('  false fails by check:', dict(Counter(i['check'][:28] for i in items if i['label'] == 'yes' and not i['passed'])))
    print('  false passes by check:', dict(Counter(i['check'][:28] for i in items if i['label'] == 'no' and i['passed'])))
    for kind in ('image', 'text'):
        sub = [i for i in items if i['kind'] == kind]
        r = Counter(('yes' if i['label'] == 'yes' else 'no', bool(i['passed'])) for i in sub)
        print(f"  rule on {kind}: label yes passed/failed {r[('yes', True)]}/{r[('yes', False)]}, "
              f"label no passed/failed {r[('no', True)]}/{r[('no', False)]}")
    ms = sorted(res['jev_ms'])
    print(f"Jev calls {res['jev_calls']}, cost ${res['jev_cost']:.5f}"
          + (f", latency p50 {ms[len(ms) // 2]:.0f} ms, p95 {ms[int(len(ms) * .95)]:.0f} ms" if ms else ''))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stage', choices=['nodes', 'loc-items', 'loc-run', 'ver-items', 'ver-prep', 'ver-run', 'report'])
    a = ap.parse_args()
    _load_env()
    {'nodes': stage_nodes, 'loc-items': stage_loc_items, 'loc-run': stage_loc_run, 'ver-items': stage_ver_items,
     'ver-prep': stage_ver_prep, 'ver-run': stage_ver_run,
     'report': lambda _a: (report_loc(), report_ver())}[a.stage](a)


if __name__ == '__main__':
    main()
