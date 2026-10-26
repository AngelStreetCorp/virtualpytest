"""Browser check of the fixed pages, against the worktree's own build.

Run:  python3 scripts/qa/check_fixes_browser.py
Needs: the CORS forwarder on :5109 and the worktree's Vite dev server on :5073
       (see the frontend-worktree-e2e skill). The auto-sign token comes from
       scripts/agent/auto_sign_token.sh and is never printed.
"""
import os
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
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        def shot(name: str, path: str, wait: int = 6000, viewport=None) -> None:
            nonlocal errors
            errors = []
            if viewport:
                page.set_viewport_size(viewport)
            page.goto(f"{BASE}{path}?auto_signed={tok}", wait_until="domcontentloaded")
            page.wait_for_timeout(wait)
            page.screenshot(path=str(OUT / name), full_page=False)
            print(f"[shot] {name}  errors={len(errors)}")
            for e in errors[:5]:
                print(f"    {e}")

        # BUG-0774 — the navigation editor says the tree does not exist.
        shot("bug-0774-nav-editor-not-found.png", "/navigation-editor/does-not-exist-xyz")

        # BUG-0813 — the unknown-screens table headers at 390 px.
        shot("bug-0813-unknown-screens-phone-headers.png", "/configuration/interface/stb_tv/unknown",
             viewport={"width": 390, "height": 844})

        # BUG-0795 — the unknown-screens page for an interface that does not exist.
        shot("bug-0795-unknown-screens-bogus-interface.png",
             "/configuration/interface/no-such-interface/unknown")

        # BUG-0797 — the retired OpenRouter debug address.
        page.set_viewport_size({"width": 1440, "height": 900})
        shot("bug-0797-openrouter-redirect.png", "/configuration/openrouter")

        # BUG-0800 — the API reference offers every published spec.
        shot("bug-0800-api-reference-specs.png", "/docs/api")

        # BUG-0796 — the API workspaces page prints the id that opens the workspace.
        shot("bug-0796-api-workspaces-id.png", "/api/workspaces")

        # BUG-0799 — the first tab stop shows where the keyboard is.
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{BASE}/?auto_signed={tok}", wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        page.keyboard.press("Tab")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "bug-0799-scope-picker-focus.png"))
        print(f"[shot] bug-0799-scope-picker-focus.png")

        # BUG-0775 — the AI Dataset review: the screenshot cannot be loaded
        # (the server route that serves it is not deployed yet), and the page
        # says so instead of showing a broken image.
        shot("bug-0775-training-review-missing-image.png", "/training-review", wait=12000)

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
