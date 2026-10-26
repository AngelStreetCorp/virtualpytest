#!/usr/bin/env python3
"""Capture the /monitoring/timeline network traffic (BUG-0778).

Prints every response the page makes for the timeline thumbnail files, so the
request storm and the status codes can be counted.
"""
import os
import subprocess
import sys
from collections import Counter

from playwright.sync_api import sync_playwright

BASE = "https://virtualpytest.angelstreet.io"
PAGE = f"{BASE}/monitoring/timeline?auto_signed={{token}}"


def main() -> int:
    token = subprocess.run(
        ["scripts/agent/auto_sign_token.sh"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    url = PAGE.format(token=token)

    seen = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=True)
        page = ctx.new_page()
        page.on("response", lambda r: seen.append((r.status, r.request.method, r.url)))
        page.on("requestfailed", lambda r: seen.append(("FAILED", r.method, r.url)))
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(9000)
        browser.close()

    interesting = [s for s in seen if "timeline" in s[2] or "thumbnails" in s[2]]
    other = [s for s in seen if s not in interesting]

    print(f"total responses: {len(seen)}")
    print(f"timeline/thumbnail responses: {len(interesting)}")
    counts = Counter((s[1], s[0]) for s in interesting)
    for (method, status), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {method:5} {str(status):7} x{n}")
    print("\nfirst 20 timeline/thumbnail requests:")
    for status, method, u in interesting[:20]:
        print(f"  {str(status):7} {method:5} {u[:150]}")
    print("\nnon-timeline responses (status count):", Counter(s[0] for s in other))
    return 0


if __name__ == "__main__":
    sys.exit(main())
