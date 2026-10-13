"""Phase 2, ON CODEBOX (tesseract deu+eng, cv2, numpy; no DB, no network): compare every frame
of the bundle with each candidate screen group and write ``evidence.jsonl``.

Per sample: ``{id, informative, frame_fact, groups: [{group_id, label, facts, best_image,
best_text, seed_distance}]}``. Per-sample results are cached in ``evidence_cache/<id>.json``, so a
rerun only does the new samples (delete the folder to recompute). A frame or reference that is not
1280x720 has its areas scaled; the sizes seen are counted once in ``evidence_meta.json``.
"""
from __future__ import annotations

import functools
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Mapping, Optional

import cv2

from . import matchers

LOW_INFO_FACT = 'low-information frame (black / bars / loading)'


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def load_groups(bundle: str, ui: str) -> List[Dict[str, Any]]:
    with open(os.path.join(bundle, 'ui', ui, 'groups.json'), encoding='utf-8') as f:
        return json.load(f)


@functools.lru_cache(maxsize=2048)
def _hash_of(path: str) -> Optional[str]:
    from shared.src.lib.ai.training_samples import DHASH_BITS, DHASH_GRID
    from shared.src.lib.utils.image_hash import dhash_hex
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return None if img is None else dhash_hex(img, DHASH_GRID, DHASH_BITS)


@functools.lru_cache(maxsize=512)
def _reference(path: str):
    return cv2.imread(path, cv2.IMREAD_COLOR)


def group_evidence(group: Mapping[str, Any], frame, frame_hash: Optional[str], base: str, ocr) -> Dict[str, Any]:
    """Checks and seed distance of one group's members on one frame. ``ocr(area) -> text``."""
    checks: List[Dict[str, Any]] = []
    seed: Optional[int] = None
    for member in group['members']:
        if member.get('seed'):
            bits = matchers.seed_bits(frame_hash, _hash_of(os.path.join(base, member['seed'])))
            if bits is not None:
                seed = bits if seed is None else min(seed, bits)
        for check in member.get('checks') or []:
            threshold = float(check.get('threshold') or matchers.DEFAULT_THRESHOLD)
            if check['command'] == matchers.TEXT_APPEAR:
                result = matchers.check_text(ocr(check.get('area')), check['name'], threshold)
            elif check.get('reference_file'):
                ref = _reference(os.path.join(base, check['reference_file']))
                if ref is None:
                    continue
                result = matchers.check_image(frame, ref, check.get('area'), threshold,
                                              disappear=check['command'] == matchers.IMAGE_DISAPPEAR)
            else:
                continue
            checks.append({**result, 'name': check['name'], 'node': member['node_id']})
    total = len(frame_hash) * 4 if frame_hash else 256
    return {'group_id': group['node_id'], 'label': group['label'],
            'facts': matchers.format_facts(checks, seed, total),
            'best_image': matchers.best_score(checks, 'image'), 'best_text': matchers.best_score(checks, 'text'),
            'seed_distance': seed}


def sample_evidence(bundle: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    """Evidence of one row (uncached). ``error`` set when the frame cannot be read."""
    from shared.src.lib.ai.training_samples import is_informative
    frame = cv2.imread(os.path.join(bundle, 'frames', f"{row['id']}.jpg"), cv2.IMREAD_COLOR)
    if frame is None:
        return {'id': row['id'], 'error': 'frame-unreadable'}
    informative = is_informative(row.get('dhash'))
    frame_hash = row.get('dhash') or _hash_of(os.path.join(bundle, 'frames', f"{row['id']}.jpg"))
    base = os.path.join(bundle, 'ui', row['userinterface'])
    ocr_cache: Dict[str, str] = {}

    def ocr(area):  # the same area is shared by many nodes: read it once
        key = json.dumps(area, sort_keys=True)
        if key not in ocr_cache:
            ocr_cache[key] = matchers.ocr_area(frame, area)
        return ocr_cache[key]

    groups = [group_evidence(g, frame, frame_hash, base, ocr) for g in load_groups(bundle, row['userinterface'])]
    out = {'id': row['id'], 'informative': informative, 'size': [frame.shape[1], frame.shape[0]], 'groups': groups}
    if not informative:
        out['frame_fact'] = LOW_INFO_FACT
    return out


def _cached(args) -> Dict[str, Any]:
    bundle, row = args
    path = os.path.join(bundle, 'evidence_cache', f"{row['id']}.json")
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    result = sample_evidence(bundle, row)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(path + '.tmp', path)
    return result


def run_evidence(bundle: str, workers: Optional[int] = None) -> Dict[str, Any]:
    rows = read_jsonl(os.path.join(bundle, 'rows.jsonl'))
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    jobs = [(bundle, r) for r in rows]
    if workers == 1:
        results = [_cached(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_cached, jobs, chunksize=4))
    sizes = Counter(f"{r['size'][0]}x{r['size'][1]}" for r in results if r.get('size'))
    with open(os.path.join(bundle, 'evidence.jsonl'), 'w', encoding='utf-8') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    meta = {'samples': len(results), 'errors': sum(1 for r in results if r.get('error')),
            'frame_sizes': dict(sizes), 'scaled': {k: n for k, n in sizes.items() if k != '1280x720'},
            'workers': workers}
    with open(os.path.join(bundle, 'evidence_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=1)
    return meta
