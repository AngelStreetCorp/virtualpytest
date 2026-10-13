"""Phase 2, ON CODEBOX (cv2 + tesseract, no network): measure every strip, write ``facts.jsonl``.
Incremental: ids already in ``facts.jsonl`` are skipped."""
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict

import cv2

from . import append_jsonl, read_jsonl
from shared.src.lib.ai.freeze_facts import measure


def _one(args) -> Dict[str, Any]:
    sample_id, path = args
    img = cv2.imread(path)
    if img is None:
        return {'id': sample_id, 'error': 'unreadable strip'}
    try:
        return {'id': sample_id, **measure(img)}
    except Exception as e:  # one bad strip must not stop the batch
        return {'id': sample_id, 'error': str(e)[:200]}


def run_facts(bundle: str, workers: int = 0) -> Dict[str, Any]:
    out = os.path.join(bundle, 'facts.jsonl')
    done = {r['id'] for r in read_jsonl(out)}
    todo = [(r['id'], os.path.join(bundle, 'strips', f"{r['id']}.jpg"))
            for r in read_jsonl(os.path.join(bundle, 'rows.jsonl')) if r['id'] not in done]
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        n = append_jsonl(out, pool.map(_one, todo))
    return {'measured': n, 'already_done': len(done)}
