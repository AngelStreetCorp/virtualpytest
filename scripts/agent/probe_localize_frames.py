#!/usr/bin/env python3
"""Capture the /monitoring/localize (and /match-runs) capture-image traffic (BUG-0779).

Prints every response for /host/<name>/stream/.../capture_*.jpg so the
401 -> 404 retry sequence can be counted.
"""
import subprocess
import sys
from collections import Counter

from playwright.sync_api import sync_playwright

BASE = "https://virtualpytest.angelstreet.io"


def probe(path: str, wait_ms: int = 9000) -> int:
    token = subprocess.run(
        ["scripts/agent/auto_sign_token.sh"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    url = f"{BASE}{path}?auto_signed={token}"

    seen = []
    console = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=True)
        page = ctx.new_page()
        page.on("response", lambda r: seen.append((r.status, r.request.method, r.url)))
        page.on("requestfailed", lambda r: seen.append(("FAILED", r.method, r.url)))
        page.on("console", lambda m: console.append((m.type, m.text)) if m.type in ("error", "warning") else None)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(wait_ms)
        browser.close()

    print(f"===== {path}")
    print(f"total responses: {len(seen)}")
    print("status counts (all):", dict(Counter(s[0] for s in seen)))
    imgs = [s for s in seen if "/stream/" in s[2]]
    print(f"host stream responses: {len(imgs)}")
    for status, method, u in imgs[:14]:
        print(f"  {str(status):7} {method:5} {u[:140]}")
    if len(imgs) > 14:
        print(f"  ... and {len(imgs) - 14} more")
    errs = [c for c in console if "Failed to load resource" in c[1] or "401" in c[1] or "404" in c[1]]
    print(f"console errors/warnings about loads: {len(errs)}")
    for t, m in errs[:6]:
        print(f"  [{t}] {m[:160]}")
    return 0


def main() -> int:
    for path in (sys.argv[1:] or ["/monitoring/localize", "/match-runs"]):
        probe(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
