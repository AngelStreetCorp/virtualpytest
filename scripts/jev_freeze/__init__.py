"""Freeze-alert triage from facts measured on the strip (TASK-38 goal 5, TASK-39 section 4b).

The first probe gave Jev the detector's own numbers and got 15/90. Here the harness measures the
strip's pixels instead (how much changes between its frames, where, whether the on-screen text
stays), writes that as text, and Jev picks still / moving / freeze.

Same shape as ``scripts/jev_review``: ``export`` on the server (DB + storage), ``facts`` on codebox
(cv2 + tesseract, no network), ``decide`` on the server (OpenRouter), ``report`` anywhere. The bundle
directory is the only thing passed between them.
"""
import json
import os
import sys
from typing import Any, Dict, Iterator, List

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if os.path.isdir(os.path.join(REPO_ROOT, 'shared')) and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

LAB_TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'
CLASSES = ('still', 'moving', 'freeze')


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path: str, records: Iterator[Dict[str, Any]]) -> int:
    n = 0
    with open(path, 'a') as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
            f.flush()
            n += 1
    return n
