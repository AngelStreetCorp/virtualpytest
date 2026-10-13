#!/usr/bin/env python3
"""
Run the real Tetris runner (shared/src/lib/game/tetris/runner.py) against the real page in a
local Chromium, before using a host (TASK-33 phase 3).

LocalIO (_local_io.py) stands in for the executors and plays the tetris-web tree's own actions.
--action-ms adds a delay per action to mimic the host's executor overhead (~25 ms).

Usage (from the repo root, see README.md):
  DISPLAY=:97 python test_scripts/game/local/tetris_vpt_local.py --max-pieces 200 --action-ms 25
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from playwright.sync_api import sync_playwright  # noqa: E402

from shared.src.lib.game.tetris.runner import TetrisRunner, kpi_metadata, summary  # noqa: E402
from shared.src.lib.game.tetris.ui import build_manifest  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _local_io import Context, LocalIO  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pieces", type=int, default=200)
    ap.add_argument("--max-duration", type=int, default=3600)
    ap.add_argument("--min-rows", type=int, default=10)
    ap.add_argument("--action-ms", type=float, default=0.0)
    a = ap.parse_args()
    out = tempfile.mkdtemp(prefix="tetris_local_")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-size=1280,720"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        ctx = Context()
        data = TetrisRunner(LocalIO(page, a.action_ms, out, build_manifest()), ctx, a.max_pieces, a.max_duration, a.min_rows).run()
        browser.close()
    print(summary(data, bool(data.get("success")), data.get("error", "")))
    print(json.dumps({k: v for k, v in kpi_metadata(data).items() if k != "final_court"}))
    print(f"frames in {out}")
    sys.exit(0 if data.get("success") else 1)


if __name__ == "__main__":
    main()
