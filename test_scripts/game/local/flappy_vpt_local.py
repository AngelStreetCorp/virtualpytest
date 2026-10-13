#!/usr/bin/env python3
"""
Run the real Flappy Bird runner (shared/src/lib/game/flappy/runner.py) against the game in a
local Chromium, before using a host (TASK-33 phase 3c).

LocalIO (_local_io.py) stands in for the executors and plays the flappy-web tree's own actions.
--action-ms adds a delay per action to mimic the host's executor overhead (~25 ms); --url can point
at a local copy of github.com/nebez/floppybird (the public site throttles repeated loads).

Usage (from the repo root, see README.md):
  DISPLAY=:98 python test_scripts/game/local/flappy_vpt_local.py --max-pipes 30 --action-ms 25
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from playwright.sync_api import sync_playwright  # noqa: E402

from shared.src.lib.game.flappy.runner import FlappyRunner, kpi_metadata, summary  # noqa: E402
from shared.src.lib.game.flappy.ui import URL, build_manifest  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _local_io import Context, LocalIO  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pipes", type=int, default=30)
    ap.add_argument("--max-duration", type=int, default=180)
    ap.add_argument("--min-pipes", type=int, default=10)
    ap.add_argument("--action-ms", type=float, default=25.0)
    ap.add_argument("--url", default=URL)
    a = ap.parse_args()
    out = tempfile.mkdtemp(prefix="flappy_local_")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--window-size=1280,720"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        ctx = Context()
        io = LocalIO(page, a.action_ms, out, build_manifest(a.url))
        data = FlappyRunner(io, ctx, a.max_pipes, a.max_duration, a.min_pipes).run()
        browser.close()
    print(summary(data, bool(data.get("success")), data.get("error", "")))
    print(json.dumps({k: v for k, v in kpi_metadata(data).items() if k != "last_readings"}))
    if not data.get("success"):
        for r in data.get("last_readings") or []:
            print(" ", r)
    sys.exit(0 if data.get("success") else 1)


if __name__ == "__main__":
    main()
