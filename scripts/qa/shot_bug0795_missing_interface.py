"""BUG-0795 — the unknown-screens page for an interface that does not exist.

The live backend still answers 200 with an empty report for an unknown name;
the fix makes it answer 404. This script intercepts that one call in the
browser and answers it with the 404 the new backend route returns, so the
page's behaviour can be checked before the backend is deployed.

Run:  python3 scripts/qa/shot_bug0795_missing_interface.py
Needs: the CORS forwarder on :5109 and the worktree's Vite dev server on :5073.
"""
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "tasks" / "qa-evidence" / "fix"
BASE = "http://127.0.0.1:5073"
NAME = "no-such-interface"


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

        def stub(route):
            # What backend_server/src/routes/server_userinterface_routes.py
            # answers for an interface that does not exist.
            route.fulfill(
                status=404,
                content_type="application/json",
                body=json.dumps({"success": False, "error": f'User interface "{NAME}" not found'}),
            )

        page.route(f"**/getUnknownScreens**", stub)

        page.goto(f"{BASE}/configuration/interface/{NAME}/unknown?auto_signed={tok}",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        page.screenshot(path=str(OUT / "bug-0795-unknown-screens-missing-interface.png"))
        body = page.inner_text("body")
        print("error shown:", f'User interface "{NAME}" not found' in body)
        print("all-clear hidden:", "has a node in its tree" not in body)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
