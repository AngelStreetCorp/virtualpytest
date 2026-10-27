#!/usr/bin/env python3
"""Localize accuracy benchmark (TASK-107 goal 1).

Builds a labelled frame set covering the six verdict kinds and runs the DEPLOYED cascade
(`navigation_executor.run_localize_cascade`: localize_verdict.py + ImageHelpers.identify_screen +
overlay / screen memory) over it, reporting accuracy per kind and per interface.

    python3 scripts/localize/bench.py build [--set DIR] [--per-ui 20]   # (re)build the labelled set
    python3 scripts/localize/bench.py run   [--set DIR]                  # score it, write results/<date>.json
    python3 scripts/localize/bench.py nightly                            # build + run (the timer calls this)
    python3 scripts/localize/bench.py harvest-live --capture-dir DIR --ui stb-<operator>   # keep live triplets
    python3 scripts/localize/bench.py harvest-nodes --capture-dir DIR --ui stb-<operator> --host H --device D --targets a,b
                                                                         # keep live frames of nodes after a goto
    python3 scripts/localize/bench.py overlay-set              # once: fixed overlay calibration set (reviewed labels)
    python3 scripts/localize/bench.py cheap23-import --src DIR # once: the 22 cheap Tier-2 frames

`run` also scores the overlay calibration set (false-positive rate on plain screens, recall per
kind) and the cheap Tier-2 check (scripts/localize/cheap23.py, its three gaps must stay closed).

Where each kind's label comes from (stored per sample as `source`):

| kind         | source          | label                                                              |
|--------------|-----------------|--------------------------------------------------------------------|
| node         | node_screenshot | the node's own saved screenshot -> that node (operator-captured)   |
| node / not   | correction      | a "Wrong screen?" row's frame -> the true node / not the wrong one  |
| node         | harvested_goto  | 3 live capture frames ~4 s after a navigate_to_node that passed the |
|              |                 | target's verifications (`harvest-nodes`): the node as the device    |
|              |                 | shows it today, not its own screenshot; kept in nodes_fixed.json    |
| overlay      | synthetic_popup | a node screenshot dimmed under a centred plate                     |
| unknown      | foreign_ui      | another interface's screenshot (no shared name prefix); a          |
|              |                 | `known_screen` answer is right too: the bench's screen memory holds |
|              |                 | another tree's copy of that very screen (TASK-110 §7)               |
| signal       | synthetic       | black frames, SMPTE colour bars                                    |
| signal       | real_standby    | real standby frames kept in signal_fixed.json (stbv1+ level 16)    |
| live         | harvested_live  | 3 frames ~0.4 s apart from the monitor's capture folder, harvested  |
|              |                 | (`harvest-live`) while the device was on a live channel (an        |
|              |                 | operator checked it); kept across rebuilds in live_fixed.json       |
| known_screen | screen_memory   | a re-encoded copy of a frame held in the bench's own screen memory  |
|              |                 | (real frames, fingerprinted by shared/src/lib/screen_memory.py)    |

Jev (the AI second opinion on a low-confidence match) is OFF in the benchmark (`team_id=None`):
the number is the rule cascade alone, deterministic, and the nightly run costs no tokens. A
single right candidate that the rule leaves to Jev (low confidence) is scored wrong and counted
apart as `awaits_jev`, so the report shows what Jev could add.
Node fingerprints are read from the DB at run time (base data, every active node), so a
recapture, a correction or a matcher change shows up in the next night's number.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

DEFAULT_SET = os.path.expanduser(os.environ.get('LOCALIZE_BENCH_DIR', '~/.local/share/vpt/localize_bench'))
DEFAULT_TEAM = os.environ.get('TEAM_ID', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
KINDS = ('signal', 'live', 'node', 'overlay', 'known_screen', 'unknown')
FOREIGN_PER_UI = 5
KNOWN_SAMPLES = 12
OVERLAY_PER_UI = 5


def _env():
    try:
        from dotenv import load_dotenv
        for p in ('/opt/virtualpytest/.env', os.path.join(ROOT, '.env')):
            if os.path.exists(p):
                load_dotenv(p, override=False)
    except ImportError:
        pass


def _db():
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    return get_supabase_client()


def _cv2():
    import cv2
    return cv2


# ---------------------------------------------------------------- labelled set

def _save(img, set_dir: str, name: str) -> str:
    path = os.path.join(set_dir, 'frames', name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _cv2().imwrite(path, img)
    return os.path.relpath(path, set_dir)


def _download(url: str):
    """A frame from an http(s) URL, or from a storage path (node screenshots are stored as
    `navigation/<ui>/<node>.jpg` in R2 / MinIO, private mode: read through the storage client)."""
    import tempfile
    import numpy as np
    try:
        if url.startswith(('http://', 'https://')):
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 vpt-localize-bench'})
            data = urllib.request.urlopen(req, timeout=20).read()
        else:
            from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
            with tempfile.NamedTemporaryFile(suffix='.jpg') as tmp:
                res = get_cloudflare_utils().download_file(url, tmp.name)
                if not (res or {}).get('success'):
                    raise RuntimeError((res or {}).get('error') or 'download failed')
                data = open(tmp.name, 'rb').read()
        return _cv2().imdecode(np.frombuffer(data, np.uint8), _cv2().IMREAD_COLOR)
    except Exception as e:
        print(f"  skip {url[:90]}: {e}")
        return None


def _ui_nodes(db, team_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """{ui_name: [node rows with a screenshot]} for every dev-mode interface (distinct node ids)."""
    uis = db.table('userinterfaces').select('id, name, mode').eq('team_id', team_id).execute().data or []
    uis = {u['id']: u['name'] for u in uis if (u.get('mode') or 'dev') == 'dev'}
    trees = db.table('navigation_trees').select('id, userinterface_id').eq('team_id', team_id).execute().data or []
    ui_of_tree = {t['id']: uis[t['userinterface_id']] for t in trees if t['userinterface_id'] in uis}
    out: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    page = 0
    while True:
        rows = (db.table('navigation_nodes')
                .select('node_id, tree_id, label, node_type, shot:data->>screenshot, dhash:data->fingerprint->>dhash')
                .eq('team_id', team_id).range(page * 1000, page * 1000 + 999).execute().data or [])
        for r in rows:
            ui = ui_of_tree.get(r['tree_id'])
            if ui and r.get('shot') and (r.get('node_type') or 'screen') not in ('entry', 'action'):
                out[ui].setdefault(r['node_id'], r)
        if len(rows) < 1000:
            break
        page += 1
    return {ui: list(nodes.values()) for ui, nodes in out.items()}


def _popup(img):
    """A centred bright plate over a dimmed page (the shape screen_state_cv._dialog_plate reads)."""
    h, w = img.shape[:2]
    out = (img * 0.15).astype('uint8')
    y0, y1, x0, x1 = int(h * 0.3), int(h * 0.7), int(w * 0.3), int(w * 0.7)
    out[y0:y1, x0:x1] = 230
    out[y0 + (y1 - y0) // 4: y0 + (y1 - y0) // 4 + max(4, h // 40), x0 + (x1 - x0) // 8: x1 - (x1 - x0) // 8] = 40
    return out


def _text_lines(img, x0, y0, x1, y1, colour, rows=1):
    """Short dark/light strokes standing in for a line of text inside a plate."""
    lh = max(3, (y1 - y0) // (2 * rows + 1))
    for r in range(rows):
        y = y0 + lh * (2 * r + 1)
        x = x0 + (x1 - x0) // 10
        while x < x1 - (x1 - x0) // 10:
            wlen = max(4, (x1 - x0) // 9)
            img[y:y + lh, x:min(x + wlen, x1 - 2)] = colour
            x += wlen + max(3, wlen // 3)
    return img


def _tooltip(img, seed: int):
    """A small callout with one line of text and a 2-px border, contrasting with the page under it
    (a light callout on a dark page, a dark one on a light page), next to a random spot."""
    rng = random.Random(seed)
    out = img.copy()
    h, w = out.shape[:2]
    tw, th = int(w * rng.uniform(0.10, 0.20)), int(h * rng.uniform(0.04, 0.07))
    x, y = rng.randint(int(w * 0.1), int(w * 0.85) - tw), rng.randint(int(h * 0.15), int(h * 0.85) - th)
    light = float(out[y:y + th, x:x + tw].mean()) < 128
    fill, ink, edge = (225, 40, 15) if light else (35, 220, 240)
    out[y - 2:y + th + 2, x - 2:x + tw + 2] = edge
    out[y:y + th, x:x + tw] = fill
    return _text_lines(out, x, y, x + tw, y + th, ink)


def _keyboard(img):
    """An on-screen keyboard: a dark panel on the bottom 40 % with a grid of lighter keys."""
    out = img.copy()
    h, w = out.shape[:2]
    top = int(h * 0.6)
    out[top:, :] = 45
    kh, kw = (h - top) // 5, w // 11
    for r in range(4):
        for c in range(10):
            y, x = top + kh // 2 + r * kh, kw // 2 + c * kw
            out[y:y + kh - 6, x:x + kw - 6] = 95
    return out


def _notification(img):
    """A system banner in the top-right corner: a light band with two text lines."""
    out = img.copy()
    h, w = out.shape[:2]
    bw, bh = int(w * 0.30), int(h * 0.12)
    x, y = w - bw - 2, 2
    out[y:y + bh, x:x + bw] = 235
    return _text_lines(out, x, y, x + bw, y + bh, 50, rows=2)


def _bars(h=720, w=1280):
    import numpy as np
    colours = [(192, 192, 192), (0, 192, 192), (192, 192, 0), (0, 192, 0), (192, 0, 192), (0, 0, 192), (192, 0, 0)]
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for i, c in enumerate(colours):
        img[:, i * w // 7:(i + 1) * w // 7] = c
    return img


def _black(seed: int, h=720, w=1280):
    import numpy as np
    rng = np.random.default_rng(seed)
    return rng.integers(0, 6, size=(h, w, 3), dtype=np.uint8)


SAME_PIXELS_DHASH_BITS = 4     # prefilter: full-frame dHash this close ...
SAME_PIXELS_MEAN_DIFF = 2.0    # ... and a mean grey difference below this on a 320x180 thumbnail


def _same_pixels(img, node: Dict[str, Any], nodes: List[Dict[str, Any]], shot) -> List[str]:
    """Other nodes of the tree whose stored screenshot is the same picture as this node's (an autobuild
    step whose key moved an invisible focus: `replay` -> RIGHT -> `replay_discover`, same pixels). No
    matcher can tell them apart, so the benchmark takes either as right (TASK-110 §7). The graph keeps
    both: the key press between them is a real step of every goto."""
    cv2 = _cv2()
    def bits(a, b):
        return bin(int(a, 16) ^ int(b, 16)).count('1') if a and b and len(a) == len(b) else 999
    thumb = lambda im: cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (320, 180), interpolation=cv2.INTER_AREA)
    mine = thumb(img)
    out = []
    for other in nodes:
        if other['node_id'] == node['node_id'] or bits(other.get('dhash'), node.get('dhash')) > SAME_PIXELS_DHASH_BITS:
            continue
        o = shot(other['shot']) if other.get('shot') else None
        if o is not None and float(cv2.absdiff(mine, thumb(o)).mean()) < SAME_PIXELS_MEAN_DIFF:
            out.append(other['node_id'])
    return out


def build(set_dir: str, team_id: str, per_ui: int, seed: int = 7) -> Dict[str, Any]:
    random.seed(seed)
    os.makedirs(set_dir, exist_ok=True)
    db = _db()
    samples: List[Dict[str, Any]] = []
    shots: Dict[str, List[Dict[str, Any]]] = {}
    ui_nodes = _ui_nodes(db, team_id)
    cache: Dict[str, Any] = {}

    def shot(url):
        if url not in cache:
            cache[url] = _download(url)
        return cache[url]

    # node: each node's own screenshot (fingerprinted nodes only: the others are not in the race)
    for ui, nodes in sorted(ui_nodes.items()):
        fp_nodes = [n for n in nodes if n.get('dhash')]
        random.shuffle(fp_nodes)
        for n in fp_nodes[:per_ui]:
            img = shot(n['shot'])
            if img is None:
                continue
            key = hashlib.sha1(n['shot'].encode()).hexdigest()[:12]
            rel = _save(img, set_dir, f"node/{key}.jpg")
            shots.setdefault(ui, []).append({'path': rel, 'node_id': n['node_id']})
            sample = {'id': f"node:{ui}:{n['node_id']}", 'kind': 'node', 'ui': ui, 'frames': [rel],
                      'expect_node': n['node_id'], 'label': n.get('label'), 'source': 'node_screenshot'}
            same = _same_pixels(img, n, nodes, shot)
            if same:
                sample['same_pixels'] = same
            samples.append(sample)
        # overlay: a popup over some of them
        for s in (shots.get(ui) or [])[:OVERLAY_PER_UI]:
            img = _cv2().imread(os.path.join(set_dir, s['path']))
            rel = _save(_popup(img), set_dir, f"overlay/{os.path.basename(s['path'])}")
            samples.append({'id': f"overlay:{ui}:{s['node_id']}", 'kind': 'overlay', 'ui': ui, 'frames': [rel],
                            'source': 'synthetic_popup'})
    # known_screen: a screen memory of real frames the trees do not hold (TASK-84 rows keep only a
    # host-local hot path, rotated out within minutes, so their own images cannot be replayed). The
    # memory rows are fingerprinted at run time by the deployed screen_memory code (no DB write);
    # each sample is a re-encoded, slightly brighter copy of one memory frame, run against an
    # interface the frame does not belong to.
    import numpy as np
    memory: List[str] = []
    names = sorted(shots)
    pool = [(ui, s) for ui in names for s in shots[ui][:2]]
    random.shuffle(pool)
    for ui, s in pool[:KNOWN_SAMPLES]:
        img = _cv2().imread(os.path.join(set_dir, s['path']))
        other = next((o for o in names if o[:3] != ui[:3]), None)
        if img is None or not other:
            continue
        memory.append(s['path'])
        ok, buf = _cv2().imencode('.jpg', np.clip(img.astype('int16') + 3, 0, 255).astype('uint8'),
                                  [_cv2().IMWRITE_JPEG_QUALITY, 60])
        rel = _save(_cv2().imdecode(buf, _cv2().IMREAD_COLOR), set_dir, f"known/{os.path.basename(s['path'])}")
        samples.append({'id': f"known:{other}:{os.path.basename(s['path'])}", 'kind': 'known_screen', 'ui': other,
                        'frames': [rel], 'source': 'screen_memory'})
    # unknown: screenshots of an unrelated interface (no shared 3-char name prefix)
    for ui in names:
        # a frame held in the screen memory would rightly read as known_screen, not unknown
        foreign = [s for other in names if other[:3] != ui[:3] for s in shots[other] if s['path'] not in memory]
        random.shuffle(foreign)
        for s in foreign[:FOREIGN_PER_UI]:
            samples.append({'id': f"unknown:{ui}:{os.path.basename(s['path'])}", 'kind': 'unknown', 'ui': ui,
                            'frames': [s['path']], 'source': 'foreign_ui'})
    # corrections: the operator's "Wrong screen?" answers that kept a frame
    try:
        rows = (db.table('localize_verdicts').select('id, userinterface_name, frame_url, action, true_node_id, wrong_node_id')
                .eq('team_id', team_id).is_('undone_at', 'null').execute().data or [])
    except Exception as e:
        rows = []
        print(f"corrections not read: {e}")
    for r in rows:
        img = shot(r['frame_url']) if r.get('frame_url') else None
        if img is None:
            continue
        rel = _save(img, set_dir, f"correction/{r['id']}.jpg")
        s = {'id': f"correction:{r['id']}", 'ui': r['userinterface_name'], 'frames': [rel], 'source': 'correction'}
        if r['action'] == 'add_sample':
            s.update({'kind': 'node', 'expect_node': r['true_node_id']})
        else:
            s.update({'kind': 'unknown', 'expect_not_node': r['wrong_node_id']})
        samples.append(s)
    # signal: synthetic black / colour bars (interface-agnostic: run against the largest tree)
    big = max(shots, key=lambda u: len(shots[u])) if shots else None
    for i in range(3):
        frames = [_save(_black(10 * i + k), set_dir, f"signal/black_{i}_{k}.jpg") for k in range(3)]
        samples.append({'id': f"signal:black:{i}", 'kind': 'signal', 'ui': big, 'frames': frames, 'source': 'synthetic'})
    bars = _save(_bars(), set_dir, 'signal/bars.jpg')
    samples.append({'id': 'signal:bars', 'kind': 'signal', 'ui': big, 'frames': [bars] * 3, 'source': 'synthetic'})
    # signal: REAL standby frames (uniform 7-16 on the capture dongles), kept across rebuilds in
    # signal_fixed.json — the guard for the black rule (BUG-0661)
    sig_fixed = os.path.join(set_dir, 'signal_fixed.json')
    if os.path.exists(sig_fixed):
        samples.extend(json.load(open(sig_fixed)))
    # live: triplets harvested while a device was on a live channel (harvest-live), kept across rebuilds
    fixed = os.path.join(set_dir, 'live_fixed.json')
    if os.path.exists(fixed):
        samples.extend(json.load(open(fixed)))
    # node frames harvested on a device after a goto (harvest-nodes), kept across rebuilds
    nodes_fixed = os.path.join(set_dir, 'nodes_fixed.json')
    if os.path.exists(nodes_fixed):
        samples.extend(json.load(open(nodes_fixed)))
    manifest = {'version': 1, 'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'team_id': team_id, 'samples': samples, 'memory': memory}
    json.dump(manifest, open(os.path.join(set_dir, 'manifest.json'), 'w'), indent=1)
    by_kind = defaultdict(int)
    for s in samples:
        by_kind[s['kind']] += 1
    print(f"built {len(samples)} samples in {set_dir}: {dict(by_kind)}")
    return manifest


def harvest_live(set_dir: str, capture_dir: str, ui: str, count: int = 12, step: int = 2) -> int:
    """Keep `count` triplets of a capture folder (capture_<n>.jpg, 5 fps: step 2 = 0.4 s) as live
    samples. Run it only while the device is on a live channel (check it first); the triplets are
    appended to live_fixed.json, which every rebuild keeps."""
    names = sorted(f for f in os.listdir(capture_dir) if f.startswith('capture_') and f.endswith('.jpg')
                   and '_thumbnail' not in f)[:-10]          # skip the newest: may still be written
    names = names[-count * 3 * step:]                       # only the last seconds: the device is on live NOW
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    fixed = os.path.join(set_dir, 'live_fixed.json')
    kept = json.load(open(fixed)) if os.path.exists(fixed) else []
    stride = 3 * step
    added = 0
    for i in range(0, len(names) - 2 * step, stride):
        trio = [names[i], names[i + step], names[i + 2 * step]]
        frames = [_cv2().imread(os.path.join(capture_dir, n)) for n in trio]
        if any(f is None for f in frames):
            continue
        rels = [_save(f, set_dir, f"live_fixed/{stamp}_{added}_{k}.jpg") for k, f in enumerate(frames)]
        kept.append({'id': f"live:{stamp}:{added}", 'kind': 'live', 'ui': ui, 'frames': rels,
                     'source': 'harvested_live', 'capture_dir': capture_dir})
        added += 1
        if added >= count:
            break
    json.dump(kept, open(fixed, 'w'), indent=1)
    print(f"kept {added} live triplets ({len(kept)} in {fixed})")
    return added


def harvest_nodes(set_dir: str, capture_dir: str, ui: str, host: str, device: str, targets: List[str],
                  team_id: str, server: str = 'https://localhost', settle_s: float = 4.0, step: int = 2) -> int:
    """Drive the device to each target (MCP navigate_to_node, as an agent does) and keep a triplet of
    its live capture frames ~settle_s later, labelled with the node, when the goto passed the target's
    verifications (nodes without any are skipped). Measures drift (a real frame vs a fingerprint of an older screenshot), which the
    node screenshots cannot. Hold a lease on the device while it runs. Appends to nodes_fixed.json."""
    import requests
    import urllib3
    urllib3.disable_warnings()
    token = os.environ['MCP_SECRET_KEY']
    db = _db()
    by_label = {}
    for n in _node_fps(db, team_id, ui):
        by_label.setdefault(n['label'], n['node_id'])
    # a goto to a node without verifications "passes" wherever it lands: such a frame is no label
    verified = {r['node_id'] for r in (db.table('navigation_nodes').select('node_id, verifications')
                                       .eq('team_id', team_id).in_('node_id', list(by_label.values()))
                                       .execute().data or []) if r.get('verifications')}
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    fixed = os.path.join(set_dir, 'nodes_fixed.json')
    kept = json.load(open(fixed)) if os.path.exists(fixed) else []
    added = 0
    for target in targets:
        node_id = by_label.get(target)
        if not node_id:
            print(f"  {target}: no fingerprinted node with that label in {ui}")
            continue
        if node_id not in verified:
            print(f"  {target}: no verification on the node, a passing goto proves nothing, not kept")
            continue
        body = {'jsonrpc': '2.0', 'id': int(time.time() * 1000), 'method': 'tools/call',
                'params': {'name': 'navigate_to_node', 'arguments': {
                    'host_name': host, 'device_id': device, 'userinterface_name': ui,
                    'target_node_label': target, 'include_screenshot': False}}}
        res = requests.post(f"{server}/server/mcp", json=body, timeout=300, verify=False,
                            headers={'Authorization': f'Bearer {token}'}).json().get('result') or {}
        if res.get('isError'):
            print(f"  {target}: goto failed, not kept")
            continue
        time.sleep(settle_s)
        names = sorted(f for f in os.listdir(capture_dir) if f.startswith('capture_') and f.endswith('.jpg')
                       and '_thumbnail' not in f)[-(2 * step + 3):-2]     # the newest may still be written
        trio = [names[0], names[step], names[2 * step]] if len(names) > 2 * step else []
        frames = [_cv2().imread(os.path.join(capture_dir, n)) for n in trio]
        if not frames or any(f is None for f in frames):
            print(f"  {target}: no frames in {capture_dir}")
            continue
        rels = [_save(f, set_dir, f"nodes_fixed/{stamp}_{node_id}_{k}.jpg") for k, f in enumerate(frames)]
        kept.append({'id': f"goto:{ui}:{node_id}:{stamp}", 'kind': 'node', 'ui': ui, 'frames': rels,
                     'expect_node': node_id, 'label': target, 'source': 'harvested_goto'})
        added += 1
        print(f"  {target}: kept")
    json.dump(kept, open(fixed, 'w'), indent=1)
    print(f"kept {added} node triplets ({len(kept)} in {fixed})")
    return added


def import_nav_language(set_dir: str, src: str, ui: str, variant: Optional[str], team_id: str) -> int:
    """Frames `<lang>_<node label>.jpg` (TASK-133, the same Home tab in German / English / French) as node
    samples scored through `variant`. Appends to nodes_fixed.json (replaces earlier nav_language samples)."""
    db = _db()
    by_label = {n['label']: n['node_id'] for n in _node_fps(db, team_id, ui, variant)}
    fixed = os.path.join(set_dir, 'nodes_fixed.json')
    kept = [k for k in (json.load(open(fixed)) if os.path.exists(fixed) else []) if k.get('source') != 'nav_language']
    n = 0
    for p in sorted(glob_frames(src)):
        lang, _, label = os.path.basename(p)[:-4].partition('_')
        if label not in by_label:
            print(f"  {os.path.basename(p)}: no node labelled {label}")
            continue
        rel = _save(_cv2().imread(p), set_dir, f"nodes_fixed/nav_language_{lang}_{label}.jpg")
        kept.append({'id': f"navlang:{ui}:{lang}:{label}", 'kind': 'node', 'ui': ui, 'variant': variant, 'frames': [rel],
                     'expect_node': by_label[label], 'label': f"{label} ({lang})", 'source': 'nav_language'})
        n += 1
    json.dump(kept, open(fixed, 'w'), indent=1)
    print(f"nav-language-import: {n} frames -> {fixed}")
    return n


TRANSIENTS = ('popup', 'keyboard', 'notification', 'tooltip')
VERDICT_TRANSIENTS = ('popup', 'keyboard', 'notification')   # the ones Localize turns into kind=overlay
OVERLAY_SYNTH_PER_KIND = 40
REVIEW_FILE = os.path.join(os.path.dirname(__file__), 'overlay_review.json')


def build_overlay_set(set_dir: str, seed: int = 5) -> int:
    """Fixed overlay calibration set (TASK-107 goal 7), built once from the node frames of the
    current set: every frame labelled 'none' unless scripts/localize/overlay_review.json (reviewed
    by eye) says popup / keyboard, plus OVERLAY_SYNTH_PER_KIND synthetic tooltips, keyboards,
    notifications and popups drawn on plain frames. Kept in overlay_fixed.json across rebuilds."""
    review = json.load(open(REVIEW_FILE))
    src = sorted(glob_frames(os.path.join(set_dir, 'frames', 'node')))
    items = []
    for p in src:
        key = os.path.basename(p)[:-4]
        img = _cv2().imread(p)
        rel = _save(img, set_dir, f"overlay_fixed/{key}.jpg")
        items.append({'path': rel, 'label': review.get(key, 'none'), 'source': 'node_screenshot'})
    plain = [i for i in items if i['label'] == 'none']
    random.seed(seed)
    for k, it in enumerate(random.sample(plain, min(OVERLAY_SYNTH_PER_KIND, len(plain)))):
        img = _cv2().imread(os.path.join(set_dir, it['path']))
        base = os.path.basename(it['path'])[:-4]
        for label, drawn in (('tooltip', _tooltip(img, k)), ('keyboard', _keyboard(img)),
                             ('notification', _notification(img)), ('popup', _popup(img))):
            items.append({'path': _save(drawn, set_dir, f"overlay_fixed/{label}_{base}.jpg"), 'label': label,
                          'source': 'synthetic'})
    json.dump(items, open(os.path.join(set_dir, 'overlay_fixed.json'), 'w'), indent=1)
    print(f"overlay set: {len(items)} frames ({sum(1 for i in items if i['label'] == 'none')} plain)")
    return len(items)


def glob_frames(folder: str) -> List[str]:
    return [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith('.jpg')] if os.path.isdir(folder) else []


def overlay_calibration(set_dir: str) -> Optional[Dict[str, Any]]:
    """screen_state_cv.overlay over the fixed set: recall per kind and the false-positive rate on
    plain screens (any transient, and the ones that become a Localize verdict)."""
    path = os.path.join(set_dir, 'overlay_fixed.json')
    if not os.path.exists(path):
        return None
    from shared.src.lib.ai import screen_state_cv as scv
    conf: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for it in json.load(open(path)):
        img = _cv2().imread(os.path.join(set_dir, it['path']))
        if img is not None:
            conf[it['label']][scv.overlay(img)] += 1
    plain = conf.get('none', {})
    n_plain = sum(plain.values())
    fp = sum(v for k, v in plain.items() if k in TRANSIENTS)
    vfp = sum(v for k, v in plain.items() if k in VERDICT_TRANSIENTS)
    pct = lambda a, b: round(100.0 * a / b, 1) if b else None
    return {'plain': n_plain, 'fp_pct': pct(fp, n_plain), 'verdict_fp_pct': pct(vfp, n_plain),
            'recall': {k: pct(conf[k].get(k, 0), sum(conf[k].values())) for k in TRANSIENTS if conf.get(k)},
            'confusion': {k: dict(v) for k, v in conf.items()}}


def import_cheap23(set_dir: str, src: str) -> int:
    """Copy the cheap-check frames (scripts/localize/cheap23.json `source`, relative to `src`) into the set."""
    import shutil
    rows = json.load(open(os.path.join(os.path.dirname(__file__), 'cheap23.json')))['rows']
    out = os.path.join(set_dir, 'frames', 'cheap23')
    os.makedirs(out, exist_ok=True)
    n = 0
    for r in rows:
        p = os.path.join(src, r['source'])
        if os.path.exists(p):
            shutil.copy(p, os.path.join(out, f"{r['id']}.jpg"))
            n += 1
    print(f"cheap23: {n}/{len(rows)} frames copied to {out}")
    return n


# ---------------------------------------------------------------- scoring

def _node_fps(db, team_id: str, ui: str, variant: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every fingerprinted active node of the interface, as NavigationExecutor.localize builds them;
    with `variant`, through that variant's node_overrides (disabled nodes dropped, fingerprints replaced)."""
    ui_row = (db.table('userinterfaces').select('id').eq('team_id', team_id).eq('name', ui).execute().data or [])
    if not ui_row:
        return []
    trees = (db.table('navigation_trees').select('id').eq('team_id', team_id)
             .eq('userinterface_id', ui_row[0]['id']).execute().data or [])
    if not trees:
        return []
    rows = (db.table('navigation_nodes').select('node_id, label, data').eq('team_id', team_id)
            .in_('tree_id', [t['id'] for t in trees]).execute().data or [])
    over = {}
    if variant:
        v = (db.table('userinterface_variants').select('node_overrides').eq('team_id', team_id)
             .eq('userinterface_id', ui_row[0]['id']).eq('name', variant).execute().data or [])
        over = (v[0]['node_overrides'] if v else {}) or {}
    seen, out = set(), []
    for r in rows:
        fp = (r.get('data') or {}).get('fingerprint') or {}
        e = over.get(r['node_id']) or {}
        if e.get('disabled'):
            continue
        if isinstance(e.get('fingerprint'), dict):
            from shared.src.lib.utils.navigation_graph import with_base_corrections
            fp = with_base_corrections(e['fingerprint'], fp)
        if fp.get('dhash') and r['node_id'] not in seen:
            seen.add(r['node_id'])
            out.append({'node_id': r['node_id'], 'label': r.get('label') or r['node_id'], 'fingerprint': fp})
    return out


def correct(sample: Dict[str, Any], verdict: Dict[str, Any]) -> bool:
    kind = verdict.get('kind')
    if sample.get('source') == 'foreign_ui' and kind == 'known_screen':
        return True       # not this tree's screen, and the device has seen it before: both answers are right
    if sample.get('expect_not_node'):
        return not (kind == 'node' and verdict.get('node_id') == sample['expect_not_node'])
    if sample['kind'] == 'node':
        return kind == 'node' and (verdict.get('node_id') == sample.get('expect_node')
                                   or verdict.get('node_id') in (sample.get('same_pixels') or []))
    return kind == sample['kind']


def run(set_dir: str, team_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    from backend_host.src.services.navigation.navigation_executor import run_localize_cascade
    from shared.src.lib import screen_memory
    from shared.src.lib.utils.localize_verdict import find_live_node
    manifest = json.load(open(os.path.join(set_dir, 'manifest.json')))
    samples = manifest['samples'][:limit] if limit else manifest['samples']
    db = _db()
    helpers = ImageHelpers(None, None)
    fps_cache: Dict[str, List[Dict[str, Any]]] = {}
    mem_rows = []
    for i, rel in enumerate(manifest.get('memory') or []):
        fp = screen_memory.fingerprint_frame(_cv2().imread(os.path.join(set_dir, rel)))
        if fp:
            mem_rows.append({'id': f'mem{i}', **fp, 'verdict': 'expected', 'seen_count': 1, 'scope': 'bench', 'label': None})
    known = lambda img: (screen_memory.match_screen(screen_memory.fingerprint_frame(img), mem_rows)
                         if mem_rows and screen_memory.fingerprint_frame(img) else None)
    per_kind, per_ui = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    per_source = defaultdict(lambda: [0, 0])
    awaits_jev: Dict[str, int] = defaultdict(int)
    confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    rows, started = [], time.time()
    for i, s in enumerate(samples):
        ui = s.get('ui')
        key = f"{ui}|{s.get('variant') or ''}"
        if ui and key not in fps_cache:
            fps_cache[key] = _node_fps(db, team_id, ui, s.get('variant'))
        node_fps = fps_cache.get(key, []) if ui else []
        frames = [_cv2().imread(os.path.join(set_dir, f)) for f in s['frames']]
        if any(f is None for f in frames):
            continue
        live_node = find_live_node({'node_id': n['node_id'], 'label': n['label']}
                                   for n in node_fps)
        lookup = known if s['kind'] in ('known_screen', 'unknown') else None
        t0 = time.time()
        _result, verdict, _motion = run_localize_cascade(helpers, frames, node_fps, live_node, team_id=None,
                                                         userinterface_name=ui, known_lookup=lookup)
        ok = correct(s, verdict)
        unconfirmed = (_result.get('unconfirmed_candidate') or {}).get('node_id')
        awaits = bool(not ok and unconfirmed and unconfirmed == s.get('expect_node'))
        awaits_jev[s['kind']] += awaits
        per_kind[s['kind']][0] += ok
        per_kind[s['kind']][1] += 1
        per_ui[ui or '(screen memory)'][0] += ok
        per_ui[ui or '(screen memory)'][1] += 1
        per_source[s['source']][0] += ok
        per_source[s['source']][1] += 1
        confusion[s['kind']][verdict.get('kind')] += 1
        rows.append({'id': s['id'], 'kind': s['kind'], 'ui': ui, 'source': s['source'], 'ok': ok,
                     'got': verdict.get('kind'), 'got_node': verdict.get('node_id'), 'awaits_jev': awaits,
                     'tied': (verdict.get('evidence') or {}).get('tied'),
                     'expect_node': s.get('expect_node'), 'ms': int((time.time() - t0) * 1000)})
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(samples)} scored")
    total_ok = sum(v[0] for v in per_kind.values())
    total = sum(v[1] for v in per_kind.values())
    pct = lambda a, b: round(100.0 * a / b, 1) if b else None
    report = {
        'ran_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'set_built_at': manifest.get('built_at'),
        'jev': False, 'samples': total, 'accuracy': pct(total_ok, total),
        'per_kind': {k: {'ok': per_kind[k][0], 'n': per_kind[k][1], 'pct': pct(*per_kind[k]),
                         'awaits_jev': awaits_jev[k]} for k in KINDS if per_kind[k][1]},
        'per_ui': {u: {'ok': v[0], 'n': v[1], 'pct': pct(*v)} for u, v in sorted(per_ui.items())},
        'per_source': {k: {'ok': v[0], 'n': v[1], 'pct': pct(*v)} for k, v in sorted(per_source.items())},
        'confusion': {k: dict(v) for k, v in confusion.items()},
        'seconds': int(time.time() - started), 'rows': rows,
    }
    report['overlay'] = overlay_calibration(set_dir)
    if os.path.isdir(os.path.join(set_dir, 'frames', 'cheap23')):
        import cheap23
        tier2 = cheap23.run(os.path.join(set_dir, 'frames', 'cheap23'))
        report['tier2'] = {k: tier2[k] for k in ('seconds', 'frames', 'reachable', 'fields', 'gaps_open')}
    out_dir = os.path.join(set_dir, 'results')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{datetime.now().strftime('%Y-%m-%d_%H%M')}.json")
    json.dump(report, open(path, 'w'), indent=1)
    json.dump(report, open(os.path.join(out_dir, 'latest.json'), 'w'), indent=1)
    print(markdown(report))
    print(f"results: {path}")
    return report


def markdown(report: Dict[str, Any]) -> str:
    lines = [f"Localize benchmark {report['ran_at']} — {report['accuracy']}% of {report['samples']} samples (Jev off)", '',
             '| kind | correct | n | % | right but left to Jev | verdicts given |', '|---|---|---|---|---|---|']
    for k, v in report['per_kind'].items():
        got = ', '.join(f"{g} {c}" for g, c in sorted(report['confusion'].get(k, {}).items(), key=lambda x: -x[1]))
        lines.append(f"| {k} | {v['ok']} | {v['n']} | {v['pct']} | {v.get('awaits_jev', 0)} | {got} |")
    ov = report.get('overlay')
    if ov:
        lines += ['', f"Overlay calibration ({ov['plain']} plain screens): false positives {ov['fp_pct']} % "
                      f"(verdict kinds {ov['verdict_fp_pct']} %); recall "
                      + ', '.join(f"{k} {v} %" for k, v in ov['recall'].items())]
    t2 = report.get('tier2')
    if t2:
        lines += ['', f"Cheap Tier-2 check: {t2['reachable']}/{t2['frames']} frames, "
                      + ', '.join(f"{f} {v['ok']}/{v['n']}" for f, v in t2['fields'].items())
                      + f"; gaps open: {', '.join(t2['gaps_open']) or 'none'}"]
    if report.get('per_source'):
        lines += ['', 'By label source: ' + ', '.join(f"{k} {v['ok']}/{v['n']} ({v['pct']} %)"
                                                    for k, v in report['per_source'].items())]
    lines += ['', '| interface | correct | n | % |', '|---|---|---|---|']
    lines += [f"| {u} | {v['ok']} | {v['n']} | {v['pct']} |" for u, v in report['per_ui'].items()]
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('command', choices=('build', 'run', 'nightly', 'harvest-live', 'harvest-nodes', 'overlay-set',
                                        'cheap23-import', 'nav-language-import'))
    ap.add_argument('--host', help='harvest-nodes: host name')
    ap.add_argument('--device', help='harvest-nodes: device id')
    ap.add_argument('--targets', help='harvest-nodes: comma-separated node labels')
    ap.add_argument('--src', help='cheap23-import: folder holding the cold-pulled frames (cheap23.json `source`)')
    ap.add_argument('--capture-dir', help='harvest-live: the capture folder of a device on a live channel')
    ap.add_argument('--variant', help='nav-language-import: score the frames through this variant')
    ap.add_argument('--ui', default=os.environ.get('VPT_LOCALIZE_UI'), help='harvest-live: the interface the device runs (default env VPT_LOCALIZE_UI)')
    ap.add_argument('--count', type=int, default=12, help='harvest-live: triplets to keep')
    ap.add_argument('--set', default=DEFAULT_SET, help=f'labelled set directory (default {DEFAULT_SET})')
    ap.add_argument('--team', default=DEFAULT_TEAM)
    ap.add_argument('--per-ui', type=int, default=20, help='node screenshots per interface')
    ap.add_argument('--limit', type=int, default=None, help='score only the first N samples')
    a = ap.parse_args()
    _env()
    if a.command == 'harvest-live':
        harvest_live(a.set, a.capture_dir, a.ui, a.count)
        return 0
    if a.command == 'harvest-nodes':
        harvest_nodes(a.set, a.capture_dir, a.ui, a.host, a.device, a.targets.split(','), a.team)
        return 0
    if a.command == 'overlay-set':
        build_overlay_set(a.set)
        return 0
    if a.command == 'nav-language-import':
        import_nav_language(a.set, a.src, a.ui, a.variant, a.team)
        return 0
    if a.command == 'cheap23-import':
        import_cheap23(a.set, a.src)
        return 0
    if a.command in ('build', 'nightly'):
        build(a.set, a.team, a.per_ui)
    if a.command in ('run', 'nightly'):
        run(a.set, a.team, a.limit)
    if a.command == 'nightly':
        try:  # TASK-154: one cron.run audit row per nightly
            from shared.src.lib.database import audit_events_db
            audit_events_db.cron('vpt-localize-bench')
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
