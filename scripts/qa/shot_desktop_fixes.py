"""Retake the desktop-width evidence shots (the phone viewport leaked into them).

Run:  python3 scripts/qa/shot_desktop_fixes.py
Needs: the CORS forwarder on :5109 and the worktree's Vite dev server on :5073.
"""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "tasks" / "qa-evidence" / "fix"
BASE = "http://127.0.0.1:5073"

SHOTS = [
    ("bug-0797-openrouter-redirect.png", "/configuration/openrouter"),
    ("bug-0800-api-reference-specs.png", "/docs/api"),
    ("bug-0796-api-workspaces-id.png", "/api/workspaces"),
]


def token() -> str:
    out = subprocess.run(["scripts/agent/auto_sign_token.sh"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    tok = out.stdout.strip()
    if len(tok) < 10:
        raise SystemExit(f"could not read the auto-sign token: {out.stderr.strip()}")
    return tok


def main() -> int:
    tok = token()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        for name, path in SHOTS:
            page.goto(f"{BASE}{path}?auto_signed={tok}", wait_until="domcontentloaded")
            page.wait_for_timeout(7000)
            page.screenshot(path=str(OUT / name))
            print(f"[shot] {name} -> {page.url}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
