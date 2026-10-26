#!/usr/bin/env python3
"""Drive the Status page in a real browser and report the host rows.

Usage:  T=<auto-sign token> python3 scripts/agent/status_host_rows.py <base-url> <out-png> [label]

Reads the number of "Host: <name>" sections and the "Services healthy" tile of
the /status page. The token is read from the environment and never printed.
"""
import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5087"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/status.png"
LABEL = sys.argv[3] if len(sys.argv) > 3 else "status"

TOKEN = os.environ.get("T", "")
if not TOKEN:
    sys.exit("T (auto-sign token) must be in the environment")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_context(viewport={"width": 1440, "height": 1000}).new_page()
    page.goto(f"{BASE}/?auto_signed={TOKEN}", wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    page.goto(f"{BASE}/status?auto_signed={TOKEN}", wait_until="domcontentloaded")

    # The page polls every 15 s; wait until the host list stops changing so a
    # half-loaded catalog is not measured.
    previous = None
    stable = 0
    for _ in range(24):
        page.wait_for_timeout(2500)
        current = page.evaluate(
            "() => { const t = document.body.innerText;"
            " return [...t.matchAll(/Host:\\s*([A-Za-z0-9_.-]+)/g)].map((m) => m[1]).join(','); }"
        )
        if current == previous and current:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        previous = current

    data = page.evaluate(
        """() => {
            const text = document.body.innerText;
            const hosts = [...text.matchAll(/Host:\\s*([A-Za-z0-9_.-]+)/g)].map((m) => m[1]);
            const tile = [...document.querySelectorAll('p,span,div')]
                .map((el) => (el.textContent || '').trim())
                .filter((t) => /^\\d+\\s*\\/\\s*\\d+$/.test(t));
            return { hosts, tiles: tile.slice(0, 6), title: document.title };
        }"""
    )

    page.screenshot(path=OUT, full_page=False)
    browser.close()

counts = {}
for h in data["hosts"]:
    counts[h] = counts.get(h, 0) + 1
print(f"[{LABEL}] host rows: {counts}")
print(f"[{LABEL}] ratio tiles: {data['tiles']}")
print(f"[{LABEL}] screenshot: {OUT}")
dupes = {k: v for k, v in counts.items() if v > 1}
print(f"[{LABEL}] duplicated: {dupes or 'none'}")
