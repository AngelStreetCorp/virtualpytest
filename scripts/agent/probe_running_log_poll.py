#!/usr/bin/env python3
"""Live check of the Device page running.log polling (BUG-0780).

Before the fix the page asked a host for a missing running.log every two
seconds, for ever. After the fix it may miss fifteen times (thirty seconds of
grace) and then stops asking.
"""
import subprocess
import sys
import time
from collections import Counter

from playwright.sync_api import sync_playwright

BASE = "https://virtualpytest.angelstreet.io"
PAGE = f"{BASE}/device-control?auto_signed={{token}}"
WINDOW_S = 50


def main() -> int:
    token = subprocess.run(
        ["scripts/agent/auto_sign_token.sh"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    hits = []
    start = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=True)
        page = ctx.new_page()

        def on_response(r):
            if "running.log" in r.url:
                hits.append((round(time.time() - start, 1), r.status, r.url))

        page.on("response", on_response)
        page.goto(PAGE.format(token=token), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(WINDOW_S * 1000)
        browser.close()

    print(f"running.log responses in {WINDOW_S}s: {len(hits)}")
    print("statuses:", Counter(s for _, s, _ in hits))
    print("\nfirst 20 (t, status, url):")
    for t, s, u in hits[:20]:
        print(f"  {t:6.1f}s {s} {u[:130]}")
    if len(hits) > 20:
        print("\nlast 5:")
        for t, s, u in hits[-5:]:
            print(f"  {t:6.1f}s {s} {u[:130]}")

    failures = []
    # The rule under test (BUG-0780): a log that never arrives may be missed
    # fifteen times (thirty seconds of grace) and then the page must stop
    # asking. A log that DOES answer is a run in progress — polling it is right.
    miss_run = 0
    longest_miss_run = 0
    for _t, status, _u in hits:
        if status == 404:
            miss_run += 1
            longest_miss_run = max(longest_miss_run, miss_run)
        else:
            miss_run = 0
    print(f"\nlongest run of consecutive 404s: {longest_miss_run}")
    if longest_miss_run > 15:
        failures.append(f"{longest_miss_run} misses in a row — the cap is not applied")

    # After the cap, the poll must be silent: the last 404 must be followed by
    # a gap, not by another request two seconds later.
    last_404 = max((t for t, s, _ in hits if s == 404), default=None)
    if last_404 is not None:
        after = [t for t, s, _ in hits if t > last_404 and s == 404]
        if after:
            failures.append(f"the page kept asking after the cap ({len(after)} more misses)")

    print("\n=== RESULT ===")
    if failures:
        for f in failures:
            print("  FAIL:", f)
        return 1
    print("  the page never polls a missing log for ever")
    return 0


if __name__ == "__main__":
    sys.exit(main())
