#!/usr/bin/env python3
"""Localize unknown-screen classification benchmark.

Measures the two questions the product asks of a frame:

1. **Is it a known node?** — the deterministic matcher (`run_localize_cascade` /
   `identify_screen`), scored against the tree's node fingerprints.
2. **If not, what is it?** — the vision classifier (`vision.dom`) on abstentions,
   scored against the screen's label.

Sets (built from the product's own screenshots, no device needed):

| kind | source | ground truth |
|---|---|---|
| `known` | each node's stored screenshot | the node id |
| `modified` | the same screenshot + one deterministic transform (brightness, contrast, jpeg, rescale, letterbox, colour shift, overlay plate) | the same node id |
| `unknown` | another interface's node screenshot (3-char name prefix differs) | that screen's label (the matcher must abstain) |
| `negative` | synthetic black frames / SMPTE bars | no node |

The classifier is **opt-in** (`run --classify`) because it is one LLM call per
abstention; the default run is the free matcher arm. Reuses
`scripts/localize/bench.py` for the DB, R2 download, frame saving and the same
`run_localize_cascade` the product uses, so the numbers are comparable with the
TASK-110 bench.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402  (sibling module in scripts/localize)

DEFAULT_SET = os.path.expanduser(
    os.environ.get('LOCALIZE_CLASSIFY_BENCH_DIR', '~/.local/share/vpt/localize_classify_bench'))
DEFAULT_TEAM = os.environ.get('TEAM_ID', bench.DEFAULT_TEAM)
TRANSFORMS = ('brightness_up', 'brightness_down', 'contrast', 'jpeg40',
              'rescale60', 'letterbox', 'colour_shift', 'overlay')


# ---------------------------------------------------------------- transforms

def apply_transform(img, name: str):
    """One deterministic visual modification of a known frame."""
    cv2 = bench._cv2()
    if img is None:
        return None
    if name == 'brightness_up':
        return np.clip(img.astype('int16') + 28, 0, 255).astype('uint8')
    if name == 'brightness_down':
        return np.clip(img.astype('int16') - 28, 0, 255).astype('uint8')
    if name == 'contrast':
        return np.clip((img.astype('float32') - 128.0) * 1.25 + 128.0, 0, 255).astype('uint8')
    if name == 'jpeg40':
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 40])
        return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img
    if name == 'rescale60':
        h, w = img.shape[:2]
        small = cv2.resize(img, (max(1, int(w * 0.6)), max(1, int(h * 0.6))), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if name == 'letterbox':
        h, w = img.shape[:2]
        pad = max(2, int(round(h * 0.05)))
        out = np.zeros((h + 2 * pad, w + 2 * pad, 3), dtype=img.dtype)
        out[pad:pad + h, pad:pad + w] = img
        return out
    if name == 'colour_shift':
        out = img.astype('int16')
        out[..., 0] = np.clip(out[..., 0] + 18, 0, 255)
        out[..., 2] = np.clip(out[..., 2] - 18, 0, 255)
        return out.astype('uint8')
    if name == 'overlay':
        return bench._popup(img)
    raise ValueError(f'unknown transform: {name}')


# ------------------------------------------------------------------ scoring

def _tokens(text: str) -> set:
    return {t for t in re.split(r'[^a-z0-9]+', (text or '').lower()) if len(t) >= 3}


def label_match(expected: Optional[str], proposal: Optional[str]) -> bool:
    """Fuzzy name match: at least half of the expected tokens appear in the proposal.

    Proposals are slugs (`tvguide`, `settings_main_menu`), so a token also counts
    when it is a substring of a proposal token.
    """
    expected_tokens, proposal_tokens = _tokens(expected or ''), _tokens(proposal or '')
    if not expected_tokens or not proposal_tokens:
        return False
    hits = [token for token in expected_tokens
            if any(token in proposed for proposed in proposal_tokens)]
    return len(hits) >= max(1, (len(expected_tokens) + 1) // 2)


def score_verdict(sample: Dict[str, Any], verdict: Dict[str, Any]) -> bool:
    """Did the matcher answer this sample correctly?"""
    kind = verdict.get('kind')
    if sample['kind'] in ('known', 'modified'):
        return kind == 'node' and verdict.get('node_id') == sample.get('expect_node')
    if sample['kind'] == 'unknown':
        # Must not claim one of this tree's nodes. known_screen is also an
        # abstention from the tree (the device has seen it elsewhere before).
        return kind in ('unknown', 'known_screen')
    if sample['kind'] == 'negative':
        return kind in ('signal', 'unknown')
    return False


def classify_frame(frame_path: str, team_id: str, *,
                   classifier=None, propose=None) -> Dict[str, Any]:
    """Run the unknown-screen classifier on one frame; never raises."""
    if classifier is None or propose is None:
        from features.avq.backend_host.localize.unknown_screen_scan import (
            classify_with_vision_dom, propose_name)
        classifier = classifier or classify_with_vision_dom
        propose = propose or propose_name
    started = time.time()
    try:
        dom = classifier(frame_path, team_id=team_id)
    except Exception as e:  # noqa: BLE001 — a failed call is a data point
        return {'ok': False, 'error': str(e)[:300], 'ms': int((time.time() - started) * 1000)}
    ms = int((time.time() - started) * 1000)
    if not isinstance(dom, dict) or dom.get('error'):
        return {'ok': False, 'error': str((dom or {}).get('error'))[:300], 'ms': ms}
    label = propose(dom, dom.get('screen_type'))
    return {'ok': bool(label), 'label': label, 'screen_type': dom.get('screen_type'), 'ms': ms}


def classify_hybrid(frame_path: str, team_id: str,
                    options: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Two-stage: Jev closed choice over ``options``, then Qwen open-set on ``none``."""
    from shared.src.lib.utils.screen_classifier import classify_screen
    started = time.time()
    out = classify_screen(frame_path, team_id, options=options)
    out['ms'] = int((time.time() - started) * 1000)
    return out



# ------------------------------------------------------- classifier comparison

def _pct(values, pct):
    if not values:
        return None
    ordered = sorted(int(v or 0) for v in values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _timed(fn):
    """Run one classifier call and stamp its wall time; a failed call is data."""
    started = time.time()
    try:
        out = fn()
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': str(e)[:300],
                'ms': int((time.time() - started) * 1000)}
    out = dict(out or {})
    out.setdefault('ms', int((time.time() - started) * 1000))
    return out


def score_jev(sample: Dict[str, Any], res: Dict[str, Any]):
    """Closed-choice outcome: correct node / wrong node / abstain / error."""
    if not res or not res.get('ok'):
        return 'error', None
    choice = res.get('choice')
    if sample['kind'] in ('known', 'modified'):
        if choice == sample.get('expect_node'):
            return 'correct', choice
        if choice == 'none':
            return 'abstain', None
        return 'false_node', choice
    # unknown: the only correct closed answer is none
    if choice == 'none':
        return 'abstain', None
    return 'false_node', choice


def score_qwen(sample: Dict[str, Any], res: Dict[str, Any]) -> bool:
    expected = sample.get('label') or sample.get('expect_label')
    return bool(res and res.get('ok') and label_match(expected, res.get('label')))


def score_hybrid(sample: Dict[str, Any], res: Dict[str, Any]):
    """Production two-stage answer: Jev node, else Qwen name."""
    if not res:
        return False, 'error', None
    source = res.get('source')
    choice = res.get('choice')
    if source == 'jev' and choice and choice != 'none':
        if sample['kind'] in ('known', 'modified') and choice == sample.get('expect_node'):
            return True, 'jev_node', choice
        return False, 'jev_false_node', choice
    expected = sample.get('label') or sample.get('expect_label')
    ok = bool(res.get('ok') and label_match(expected, res.get('label')))
    return ok, 'qwen', res.get('label')


def _selected_samples(manifest: Dict[str, Any], uis=None, transforms=None,
                      kinds=None, limit=None) -> List[Dict[str, Any]]:
    samples = []
    for sample in manifest.get('samples') or []:
        if sample.get('kind') not in ('known', 'modified', 'unknown'):
            continue
        if kinds and sample['kind'] not in kinds:
            continue
        if uis and sample.get('ui') not in uis:
            continue
        if (transforms and sample['kind'] == 'modified'
                and sample.get('transform') not in transforms):
            continue
        samples.append(sample)
    return samples[:limit] if limit else samples


def _usage_by_pass(db, windows) -> Dict[str, Any]:
    """Billed calls of the whole run, attributed to the pass they belong to.

    ``windows`` is [(arm, started, finished)].  The first call of a pass can be
    logged a few hundred ms before our wall-clock start, so the query starts
    10 s early and each row is assigned to the latest pass that had started.
    """
    if not windows:
        return {}
    run_start = windows[0][1]
    try:
        res = (db.table('ai_calls').select('usage_key, cost, latency_ms, ts')
               .gte('ts', (run_start - timedelta(seconds=10)).isoformat())
               .like('usage_key', '%vision.classify%').execute())
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)[:200]}
    starts = [window[1] for window in windows]
    buckets = {window[0]: defaultdict(lambda: {'calls': 0, 'cost': 0.0, 'latency': []})
               for window in windows}
    for row in res.data or []:
        try:
            ts = datetime.fromisoformat(str(row.get('ts')).replace('Z', '+00:00'))
        except ValueError:
            continue
        index = 0
        for i, started in enumerate(starts):
            if ts >= started:
                index = i
        arm = windows[index][0]
        key = 'jev' if row.get('usage_key') == 'vision.classify' else 'qwen'
        buckets[arm][key]['calls'] += 1
        buckets[arm][key]['cost'] += float(row.get('cost') or 0)
        buckets[arm][key]['latency'].append(int(row.get('latency_ms') or 0))
    out = {}
    for arm, by_key in buckets.items():
        out[arm] = {}
        for key, value in by_key.items():
            out[arm][key] = {'calls': value['calls'], 'cost': round(value['cost'], 6),
                             'p50_ms': _pct(value['latency'], 50),
                             'p95_ms': _pct(value['latency'], 95)}
    return out


def _agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    ok = sum(1 for r in rows if r.get('ok'))
    return {'n': n, 'ok': ok, 'pct': round(100.0 * ok / n, 1) if n else None,
            'p50_ms': _pct([r.get('ms') for r in rows], 50),
            'p95_ms': _pct([r.get('ms') for r in rows], 95)}


def _arm_item(arm: str, kind: str, subset: List[Dict[str, Any]]) -> Dict[str, Any]:
    item = _agg(subset)
    if arm == 'jev':
        for outcome in ('correct', 'false_node', 'abstain', 'error'):
            item[outcome] = sum(1 for r in subset if r['outcome'] == outcome)
        item['false'] = item['false_node']
        if kind == 'unknown':
            # On a foreign screen the only correct closed answer is none.
            item['ok'] = item['abstain']
            item['pct'] = (round(100.0 * item['abstain'] / item['n'], 1)
                           if item['n'] else None)
    elif arm == 'qwen':
        item['false'] = sum(1 for r in subset if not r['ok'])
        item['error'] = sum(1 for r in subset if r['outcome'] == 'error')
    else:
        item['false'] = sum(1 for r in subset if not r['ok'])
        item['error'] = sum(1 for r in subset if r.get('mode') == 'error')
        item['by_mode'] = {mode: sum(1 for r in subset if r.get('mode') == mode)
                           for mode in ('jev_node', 'qwen', 'jev_false_node', 'error')}
    return item


def _combine(items) -> Dict[str, Any]:
    items = [item for item in items if item]
    ok = sum(int(item.get('ok') or 0) for item in items)
    n = sum(int(item.get('n') or 0) for item in items)
    return {'ok': ok, 'n': n, 'pct': round(100.0 * ok / n, 1) if n else None}


def _cell(items) -> str:
    combined = _combine(items)
    if not combined['n']:
        return '—'
    return f"{combined['ok']}/{combined['n']} ({combined['pct']}%)"


def summarize(rows: List[Dict[str, Any]], samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {'date': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                              'n': len(samples), 'rows': rows}
    arms = {}
    for arm in ('jev', 'qwen', 'hybrid'):
        for kind in ('known', 'modified', 'unknown'):
            subset = [r for r in rows if r['arm'] == arm and r['kind'] == kind]
            if subset:
                arms[f'{arm}:{kind}'] = _arm_item(arm, kind, subset)
    report['arms'] = arms

    per_ui = {}
    for ui in sorted({s['ui'] for s in samples if s.get('ui')}):
        per_ui[ui] = {}
        for arm in ('jev', 'qwen', 'hybrid'):
            for kind in ('known', 'modified', 'unknown'):
                subset = [r for r in rows
                          if r['ui'] == ui and r['arm'] == arm and r['kind'] == kind]
                if subset:
                    per_ui[ui][f'{arm}:{kind}'] = _arm_item(arm, kind, subset)
    report['per_ui'] = per_ui

    per_transform = {}
    for name in sorted({r.get('transform') for r in rows
                        if r['kind'] == 'modified' and r.get('transform')}):
        per_transform[name] = {
            arm: _arm_item(arm, 'modified', [r for r in rows if r['kind'] == 'modified'
                                             and r.get('transform') == name
                                             and r['arm'] == arm])
            for arm in ('jev', 'qwen', 'hybrid')}
    report['per_transform'] = per_transform
    return report


def markdown_report(report: Dict[str, Any]) -> str:
    lines = [f"# Jev vs Qwen closed-choice benchmark — {report['date']}", '',
             f"{report['n']} samples · interfaces: {', '.join(report.get('uis') or [])}",
             f"transforms: {', '.join(report.get('transforms') or [])}", '']
    lines += ['| arm | kind | n | correct | % | false | abstain | error | p50 ms |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm in ('jev', 'qwen', 'hybrid'):
        for kind in ('known', 'modified', 'unknown'):
            item = report['arms'].get(f'{arm}:{kind}')
            if not item:
                continue
            false = item.get('false', item.get('false_node', ''))
            lines.append(f"| {arm} | {kind} | {item['n']} | {item['ok']} | {item['pct']} | "
                         f"{false} | {item.get('abstain', '')} | {item.get('error', '')} | "
                         f"{item['p50_ms']} |")
    if report.get('per_transform'):
        lines += ['', '| transform | Jev correct | Jev n | Jev % | Hybrid % | Qwen % |',
                  '|---|---:|---:|---:|---:|---:|']
        for name, item in report['per_transform'].items():
            jev = item.get('jev') or {}
            lines.append(f"| {name} | {jev.get('ok', 0)} | {jev.get('n', 0)} | "
                         f"{jev.get('pct', '')} | {(item.get('hybrid') or {}).get('pct', '')} | "
                         f"{(item.get('qwen') or {}).get('pct', '')} |")
    if report.get('per_ui'):
        lines += ['', '| interface | Jev node k+m | Jev abstain unknown | '
                      'Qwen label k+m | Qwen label unknown | Hybrid k+m | Hybrid unknown |',
                  '|---|---:|---:|---:|---:|---:|---:|']
        for ui, item in report['per_ui'].items():
            lines.append(
                f"| {ui} | "
                f"{_cell([item.get('jev:known'), item.get('jev:modified')])} | "
                f"{_cell([item.get('jev:unknown')])} | "
                f"{_cell([item.get('qwen:known'), item.get('qwen:modified')])} | "
                f"{_cell([item.get('qwen:unknown')])} | "
                f"{_cell([item.get('hybrid:known'), item.get('hybrid:modified')])} | "
                f"{_cell([item.get('hybrid:unknown')])} |")
    passes = report.get('passes') or {}
    if passes:
        lines += ['', '| pass | Jev calls | Jev cost | Qwen calls | Qwen cost | total |',
                  '|---|---:|---:|---:|---:|---:|']
        for name in ('jev', 'qwen', 'hybrid'):
            item = passes.get(name) or {}
            jev = item.get('jev') or {}
            qwen = item.get('qwen') or {}
            total = round(float(jev.get('cost') or 0) + float(qwen.get('cost') or 0), 6)
            lines.append(f"| {name} | {jev.get('calls', 0)} | ${jev.get('cost', 0)} | "
                         f"{qwen.get('calls', 0)} | ${qwen.get('cost', 0)} | ${total} |")
    return '\n'.join(lines)


def classify_set(set_dir: str, team_id: str, *, uis=None, transforms=None,
                 kinds=None, limit=None) -> Dict[str, Any]:
    """Three passes: Jev-only, Qwen-only, hybrid, on the same samples."""
    from shared.src.lib.utils.screen_classifier import (
        classify_open, classify_screen, classify_with_options)

    manifest = json.load(open(os.path.join(set_dir, 'manifest.json')))
    samples = _selected_samples(manifest, uis, transforms, kinds, limit)
    if not samples:
        raise SystemExit('no samples selected')
    print(f'classify: {len(samples)} samples · {len({s["ui"] for s in samples})} interfaces')
    db = bench._db()
    rows: List[Dict[str, Any]] = []
    windows = []
    for arm in ('jev', 'qwen', 'hybrid'):
        started = datetime.now(timezone.utc)
        for index, sample in enumerate(samples):
            path = os.path.join(set_dir, sample['frames'][0])
            options = sample.get('options') or []
            base = {'id': sample['id'], 'kind': sample['kind'], 'ui': sample['ui'],
                    'transform': sample.get('transform'), 'arm': arm}
            if arm == 'jev':
                res = _timed(lambda p=path, o=options: classify_with_options(p, o, team_id))
                outcome, choice = score_jev(sample, res)
                rows.append({**base, 'ok': outcome == 'correct', 'outcome': outcome,
                             'choice': choice, 'label': res.get('label'),
                             'ms': res.get('ms'), 'error': res.get('error')})
            elif arm == 'qwen':
                res = _timed(lambda p=path: classify_open(p, team_id))
                ok = score_qwen(sample, res)
                rows.append({**base, 'ok': ok,
                             'outcome': 'correct' if ok else
                             ('error' if not res.get('ok') else 'false'),
                             'label': res.get('label'), 'ms': res.get('ms'),
                             'error': res.get('error')})
            else:
                res = _timed(lambda p=path, o=options: classify_screen(p, team_id, options=o or None))
                ok, mode, detail = score_hybrid(sample, res)
                rows.append({**base, 'ok': ok,
                             'outcome': 'correct' if ok else
                             ('error' if not res.get('ok') else 'false'),
                             'mode': mode, 'detail': detail,
                             'source': res.get('source'), 'choice': res.get('choice'),
                             'label': res.get('label'), 'ms': res.get('ms'),
                             'error': res.get('error')})
            if (index + 1) % 10 == 0:
                print(f'  {arm}: {index + 1}/{len(samples)}', flush=True)
        finished = datetime.now(timezone.utc)
        windows.append((arm, started, finished))
        print(f'  {arm} pass done', flush=True)
    time.sleep(2)  # the last ai_calls row is written asynchronously
    passes = _usage_by_pass(db, windows)
    report = summarize(rows, samples)
    report['set'] = set_dir
    report['team_id'] = team_id
    report['uis'] = sorted({s['ui'] for s in samples if s.get('ui')})
    report['transforms'] = sorted({s.get('transform') for s in samples if s.get('transform')})
    report['passes'] = passes
    return report


# -------------------------------------------------------------------- build

def build(set_dir: str, team_id: str, per_ui: int, seed: int = 7,
          uis: Optional[List[str]] = None) -> Dict[str, Any]:
    random.seed(seed)
    os.makedirs(set_dir, exist_ok=True)
    db = bench._db()
    ui_nodes = bench._ui_nodes(db, team_id)
    if uis:
        ui_nodes = {name: nodes for name, nodes in ui_nodes.items() if name in uis}
    if not ui_nodes:
        raise SystemExit(f'no interfaces matched {uis}')
    cache: Dict[str, Any] = {}

    def shot(url):
        if url not in cache:
            cache[url] = bench._download(url)
        return cache[url]

    samples: List[Dict[str, Any]] = []
    for ui, nodes in sorted(ui_nodes.items()):
        fingerprinted = [n for n in nodes if n.get('dhash')]
        random.shuffle(fingerprinted)
        ui_options = [{'id': n['node_id'], 'description': n.get('label') or n['node_id']}
                      for n in fingerprinted][:60]
        for node in fingerprinted[:per_ui]:
            img = shot(node['shot'])
            if img is None:
                continue
            safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', node['node_id'])
            rel = bench._save(img, set_dir, f'known/{ui}_{safe}.jpg')
            samples.append({'id': f"known:{ui}:{node['node_id']}", 'kind': 'known', 'ui': ui,
                            'frames': [rel], 'expect_node': node['node_id'],
                            'label': node.get('label') or node['node_id'], 'options': ui_options})
            for name in TRANSFORMS:
                rel2 = bench._save(apply_transform(img, name), set_dir,
                                   f'modified/{name}/{ui}_{safe}.jpg')
                samples.append({'id': f"modified:{name}:{ui}:{node['node_id']}", 'kind': 'modified',
                                'transform': name, 'ui': ui, 'frames': [rel2],
                                'expect_node': node['node_id'],
                                'label': node.get('label') or node['node_id'],
                                'options': ui_options})

    # unknown: another interface's screenshots, run against THIS interface's tree
    for ui in sorted(ui_nodes):
        foreign = [(other, n) for other in ui_nodes if other[:3] != ui[:3]
                   for n in ui_nodes[other] if n.get('dhash')]
        random.shuffle(foreign)
        for other, node in foreign[:per_ui]:
            img = shot(node['shot'])
            if img is None:
                continue
            safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', f'{other}_{node["node_id"]}')
            rel = bench._save(img, set_dir, f'unknown/{ui}_{safe}.jpg')
            samples.append({'id': f"unknown:{ui}:{other}:{node['node_id']}", 'kind': 'unknown',
                            'ui': ui, 'frames': [rel],
                            'expect_label': node.get('label') or node['node_id'],
                            'options': [{'id': n['node_id'], 'description': n.get('label') or n['node_id']}
                                        for n in ui_nodes[ui] if n.get('dhash')][:60]})

    # negatives: interface-agnostic synthetic frames
    big_ui = max(ui_nodes, key=lambda u: len(ui_nodes[u])) if ui_nodes else None
    for i in range(2):
        frames = [bench._save(bench._black(10 * i + k), set_dir, f'negative/black_{i}_{k}.jpg')
                  for k in range(3)]
        samples.append({'id': f'negative:black:{i}', 'kind': 'negative', 'ui': big_ui, 'frames': frames})
    samples.append({'id': 'negative:bars', 'kind': 'negative', 'ui': big_ui,
                    'frames': [bench._save(bench._bars(), set_dir, 'negative/bars.jpg')] * 3})

    manifest = {'version': 1, 'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'team_id': team_id, 'samples': samples}
    json.dump(manifest, open(os.path.join(set_dir, 'manifest.json'), 'w'), indent=1)
    by_kind = defaultdict(int)
    for sample in samples:
        by_kind[sample['kind']] += 1
    print(f'built {len(samples)} samples in {set_dir}: {dict(by_kind)}')
    return manifest


# ---------------------------------------------------------------------- run

def run(set_dir: str, team_id: str, limit: Optional[int] = None,
        classify: bool = False, kinds: Optional[List[str]] = None,
        classifier: str = 'hybrid') -> Dict[str, Any]:
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    from backend_host.src.services.navigation.navigation_executor import run_localize_cascade
    from shared.src.lib.utils.localize_verdict import find_live_node

    manifest = json.load(open(os.path.join(set_dir, 'manifest.json')))
    samples = manifest['samples']
    if kinds:
        samples = [s for s in samples if s['kind'] in kinds]
    if limit:
        samples = samples[:limit]
    db = bench._db()
    helpers = ImageHelpers(None, None)
    fps_cache: Dict[str, List[Dict[str, Any]]] = {}
    rows: List[Dict[str, Any]] = []
    started = time.time()

    for sample in samples:
        ui = sample.get('ui')
        if ui and ui not in fps_cache:
            fps_cache[ui] = bench._node_fps(db, team_id, ui)
        node_fps = fps_cache.get(ui, []) if ui else []
        frames = [bench._cv2().imread(os.path.join(set_dir, f)) for f in sample['frames']]
        if any(f is None for f in frames):
            continue
        live_node = find_live_node({'node_id': n['node_id'], 'label': n['label']}
                                   for n in node_fps)
        t0 = time.time()
        _result, verdict, _motion = run_localize_cascade(
            helpers, frames, node_fps, live_node, team_id=None, userinterface_name=ui)
        ms = int((time.time() - t0) * 1000)
        ok = score_verdict(sample, verdict)
        row = {'id': sample['id'], 'kind': sample['kind'], 'transform': sample.get('transform'),
               'ui': ui, 'ok': ok, 'got': verdict.get('kind'), 'got_node': verdict.get('node_id'),
               'expect_node': sample.get('expect_node'), 'expect_label': sample.get('expect_label'),
               'ms': ms}
        if classify and verdict.get('kind') in ('unknown', 'known_screen'):
            frame_path = os.path.join(set_dir, sample['frames'][0])
            if classifier == 'dom':
                cls = classify_frame(frame_path, team_id)
                expected = sample.get('expect_label') or sample.get('label')
                match = bool(expected and cls.get('ok')
                             and label_match(expected, cls.get('label')))
            else:
                options = sample.get('options')
                if options is None:
                    options = [{'id': n['node_id'], 'description': n['label']}
                               for n in node_fps][:60] or None
                cls = classify_hybrid(frame_path, team_id, options)
                if cls.get('source') == 'jev' and cls.get('ok'):
                    if sample.get('expect_node'):
                        match = cls.get('choice') == sample['expect_node']
                    elif sample['kind'] == 'unknown':
                        match = cls.get('choice') == 'none'
                    else:
                        match = None
                else:
                    expected = sample.get('expect_label') or sample.get('label')
                    match = bool(expected and cls.get('ok')
                                 and label_match(expected, cls.get('label')))
            row['classification'] = cls
            row['label_match'] = match
        rows.append(row)
        if len(rows) % 25 == 0:
            print(f'  {len(rows)}/{len(samples)} scored')

    def pct(a: int, b: int):
        return round(100.0 * a / b, 1) if b else None

    per_kind = defaultdict(lambda: {'n': 0, 'ok': 0, 'false_match': 0})
    per_transform = defaultdict(lambda: {'n': 0, 'ok': 0})
    for row in rows:
        item = per_kind[row['kind']]
        item['n'] += 1
        item['ok'] += int(row['ok'])
        if row['kind'] in ('unknown', 'negative') and row['got'] == 'node':
            item['false_match'] += 1
        if row['kind'] == 'modified':
            t = per_transform[row['transform']]
            t['n'] += 1
            t['ok'] += int(row['ok'])
    for item in per_kind.values():
        item['pct'] = pct(item['ok'], item['n'])
    for item in per_transform.values():
        item['pct'] = pct(item['ok'], item['n'])

    classified = [r['classification'] for r in rows if r.get('classification')]
    matched = [r for r in rows if r.get('classification')]
    report = {
        'ran_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'set_built_at': manifest.get('built_at'), 'classify': classify,
        'samples': len(rows),
        'per_kind': {k: per_kind[k] for k in ('known', 'modified', 'unknown', 'negative') if per_kind[k]['n']},
        'per_transform': dict(sorted(per_transform.items())),
        'unknown_abstain_pct': pct(
            sum(1 for r in rows if r['kind'] == 'unknown' and r['got'] != 'node'),
            sum(1 for r in rows if r['kind'] == 'unknown')),
        'classification': {
            'calls': len(classified),
            'jev_calls': sum(1 for c in classified
                             if isinstance(c.get('jev'), dict) and c['jev'].get('ok')),
            'jev_final': sum(1 for c in classified if c.get('source') == 'jev'),
            'qwen_calls': sum(1 for c in classified if c.get('source') == 'qwen'),
            'jev_none': sum(1 for c in classified
                            if isinstance(c.get('jev'), dict) and c['jev'].get('choice') == 'none'),
            'jev_false_node': sum(
                1 for r in rows if r['kind'] == 'unknown'
                and isinstance((r.get('classification') or {}).get('jev'), dict)
                and ((r['classification']['jev'].get('choice') or 'none') != 'none')),
            'ok': sum(1 for c in classified if c.get('ok')),
            'label_matches': sum(1 for r in matched if r.get('label_match')),
            'p50_ms': sorted(c.get('ms', 0) for c in classified)[len(classified) // 2] if classified else None,
        },
        'seconds': int(time.time() - started), 'rows': rows,
    }
    out_dir = os.path.join(set_dir, 'results')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json")
    json.dump(report, open(path, 'w'), indent=1)
    json.dump(report, open(os.path.join(out_dir, 'latest.json'), 'w'), indent=1)
    print(markdown(report))
    print(f'results: {path}')
    return report


def markdown(report: Dict[str, Any]) -> str:
    lines = [f"Unknown-screen classification benchmark {report['ran_at']} — "
             f"{report['samples']} samples (classifier {'on' if report['classify'] else 'off'})", '',
             '| kind | correct | n | % | false matches |', '|---|---|---|---|---|']
    for kind, item in report['per_kind'].items():
        lines.append(f"| {kind} | {item['ok']} | {item['n']} | {item['pct']} | {item.get('false_match', 0)} |")
    if report.get('unknown_abstain_pct') is not None:
        lines += ['', f"Unknown abstain rate: {report['unknown_abstain_pct']} %"]
    if report.get('per_transform'):
        lines += ['', '| transform | correct | n | % |', '|---|---|---|---|']
        for name, item in report['per_transform'].items():
            lines.append(f"| {name} | {item['ok']} | {item['n']} | {item['pct']} |")
    cls = report.get('classification') or {}
    if cls.get('calls'):
        lines += ['', f"Classifier: {cls['calls']} calls · Jev {cls.get('jev_calls', 0)} "
                      f"(none {cls.get('jev_none', 0)}, false node {cls.get('jev_false_node', 0)}) · "
                      f"Qwen {cls.get('qwen_calls', 0)} · {cls['ok']} named · "
                      f"{cls['label_matches']} label matches · p50 {cls['p50_ms']} ms"]
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    build_p = sub.add_parser('build', help='build the known/modified/unknown/negative set')
    build_p.add_argument('--set', default=DEFAULT_SET)
    build_p.add_argument('--team-id', default=DEFAULT_TEAM)
    build_p.add_argument('--per-ui', type=int, default=4)
    build_p.add_argument('--uis', default='',
                         help='comma-separated interface names (default: all dev interfaces)')
    run_p = sub.add_parser('run', help='score the set with the production matcher')
    run_p.add_argument('--set', default=DEFAULT_SET)
    run_p.add_argument('--team-id', default=DEFAULT_TEAM)
    run_p.add_argument('--limit', type=int, default=0)
    run_p.add_argument('--classify', action='store_true',
                       help='also run vision.dom on abstentions (one LLM call each)')
    run_p.add_argument('--kinds', default='',
                       help='comma-separated subset: known,modified,unknown,negative')
    run_p.add_argument('--classifier', choices=('hybrid', 'dom'), default='hybrid',
                       help='hybrid = Jev options + Qwen open-set; dom = the original vision.dom call')
    class_p = sub.add_parser(
        'classify', help='Jev-only vs Qwen-only vs hybrid on every sample (known/modified/unknown)')
    class_p.add_argument('--set', default=DEFAULT_SET)
    class_p.add_argument('--team-id', default=DEFAULT_TEAM)
    class_p.add_argument('--uis', default='', help='comma-separated interface names')
    class_p.add_argument('--transforms', default='', help='comma-separated modified transforms')
    class_p.add_argument('--kinds', default='known,modified,unknown')
    class_p.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    uis = [u.strip() for u in (getattr(args, 'uis', '') or '').split(',') if u.strip()] or None
    if args.command == 'build':
        build(args.set, args.team_id, args.per_ui, uis=uis)
    elif args.command == 'classify':
        transforms = ([t.strip() for t in (args.transforms or '').split(',') if t.strip()]
                      or None)
        kinds = [k.strip() for k in (args.kinds or '').split(',') if k.strip()] or None
        report = classify_set(args.set, args.team_id, uis=uis, transforms=transforms,
                              kinds=kinds, limit=(args.limit or None))
        print(markdown_report(report))
        out_dir = os.path.join(args.set, 'results')
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')
        json_path = os.path.join(out_dir, f'{stamp}-classify.json')
        md_path = os.path.join(out_dir, f'{stamp}-classify.md')
        json.dump(report, open(json_path, 'w'), indent=1)
        with open(md_path, 'w') as fh:
            fh.write(markdown_report(report) + '\n')
        print('results:', json_path, md_path)
    else:
        kinds = [k.strip() for k in (args.kinds or '').split(',') if k.strip()] or None
        run(args.set, args.team_id, limit=(args.limit or None), classify=args.classify,
            kinds=kinds, classifier=args.classifier)
    return 0


if __name__ == '__main__':
    sys.exit(main())
