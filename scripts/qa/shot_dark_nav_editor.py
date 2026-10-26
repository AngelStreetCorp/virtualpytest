"""Dark-theme capture of the BUG-0774 not-found screen.

Run:  python3 scripts/qa/shot_dark_nav_editor.py
Needs: the CORS forwarder on :5109 and the worktree's Vite dev server on :5073.
"""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "tasks" / "qa-evidence" / "fix"
BASE = "http://127.0.0.1:5073"


def token() -> str:
    out = subprocess.run(["scripts/agent/auto_sign_token.sh"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    tok = out.stdout.strip()
    if len(tok) < 10:
        raise SystemExit(f"could not read the auto-sign token: {out.stderr.strip()}")
    return tok


def main() -> int:
    tok = token()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script("localStorage.setItem('theme-mode', 'dark');")
        page = context.new_page()
        page.goto(f"{BASE}/navigation-editor/does-not-exist-xyz?auto_signed={tok}",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(9000)
        page.screenshot(path=str(OUT / "bug-0774-nav-editor-not-found-dark.png"))
        body = page.inner_text("body")
        print("not-found text present:", "cannot be opened" in body)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
