"""Diagnostic for BUG-0774: what does the browser actually see?

Run:  python3 scripts/qa/diag_nav_editor.py
Needs: the CORS forwarder on :5109 and the worktree's Vite dev server on :5073.
"""
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        log: list[str] = []
        page.on("console", lambda m: log.append(f"CONSOLE {m.type}: {m.text}"))
        page.on("pageerror", lambda e: log.append(f"PAGEERROR: {e}"))

        def on_response(resp):
            if "userinterface" in resp.url.lower():
                log.append(f"RESPONSE {resp.status} {resp.request.headers.get('x-auto-sign', 'NO-TOKEN') and 'HAS-TOKEN' or 'NO-TOKEN'} {resp.url}")

        page.on("response", on_response)

        page.goto(f"{BASE}/navigation-editor/does-not-exist-xyz?auto_signed={tok}",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(15000)

        print("=== network / console ===")
        for line in log:
            if "userinterface" in line or "PAGEERROR" in line or "CONSOLE error" in line:
                print(line)

        print("=== sessionStorage ===")
        storage = page.evaluate("() => Object.fromEntries(Object.entries(sessionStorage))")
        for key, value in storage.items():
            if "auto" in key.lower():
                print(f"{key} = <set, {len(str(value))} chars>")
            else:
                print(f"{key} = {value}")

        print("=== dom ===")
        body = page.inner_text("body")
        print("not-found text present:", "cannot be opened" in body)
        print("body head:", body[:600].replace("\n", " | "))

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
