#!/usr/bin/env python3
"""Open the status / monitoring / settings pages in a real browser and report console errors.

Usage:  T=<auto-sign token> python3 scripts/agent/page_console_sweep.py <base-url> [out-dir]

Reads the console of every page of one group and prints the errors and the page
errors of each, so a regression that another deploy introduced shows up as text
instead of a silent blank panel. The token is read from the environment and
never printed.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5087"
OUT_DIR = sys.argv[2] if len(sys.argv) > 2 else "/tmp"

PAGES = [
    ("status", "/status"),
    ("monitoring-system", "/monitoring/system"),
    ("monitoring-analytics", "/monitoring/analytics"),
    ("monitoring-incidents", "/monitoring/incidents"),
    ("configuration-settings", "/configuration/settings"),
]

TOKEN = os.environ.get("T", "")
if not TOKEN:
    sys.exit("T (auto-sign token) must be in the environment")

SKIP = (
    "favicon",
    "Download the React DevTools",
    "webpack",
    "sourcemap",
)


def main() -> int:
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        for label, path in PAGES:
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            console: list[str] = []
            page_errors: list[str] = []
            page.on(
                "console",
                lambda msg: console.append(f"{msg.type}: {msg.text}")
                if msg.type in ("error", "warning")
                else None,
            )
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            try:
                page.goto(f"{BASE}{path}?auto_signed={TOKEN}", wait_until="domcontentloaded")
                page.wait_for_timeout(7000)
                body = page.inner_text("body") or ""
                shot = os.path.join(OUT_DIR, f"sweep-{label}.png")
                page.screenshot(path=shot, full_page=False)
                empty = len(body.strip()) < 40
                errors = [c for c in console if not any(s in c for s in SKIP)]
                print(f"[{label}] {path}")
                print(f"[{label}]   body chars: {len(body.strip())}  empty page: {empty}")
                print(f"[{label}]   console errors/warnings: {len(errors)}")
                for line in errors[:8]:
                    print(f"[{label}]     {line[:220]}")
                print(f"[{label}]   page errors: {len(page_errors)}")
                for line in page_errors[:8]:
                    print(f"[{label}]     {line[:220]}")
                print(f"[{label}]   screenshot: {shot}")
                if empty or page_errors:
                    failures += 1
            finally:
                context.close()
        browser.close()
    print(f"[sweep] pages with a blank page or an uncaught error: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
