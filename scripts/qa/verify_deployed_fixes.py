"""Verify the QA fixes on the deployed app (not the worktree build).

Run:  python3 scripts/qa/verify_deployed_fixes.py
Needs: the deployed frontend (https://virtualpytest.angelstreet.io) and the
       auto-sign token from scripts/agent/auto_sign_token.sh.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/tmp/vpt-deploy-check")
BASE = "https://virtualpytest.angelstreet.io"


def token() -> str:
    out = subprocess.run(["scripts/agent/auto_sign_token.sh"], cwd=ROOT,
                         capture_output=True, text=True, timeout=180)
    tok = out.stdout.strip()
    if len(tok) < 10:
        raise SystemExit(f"could not read the auto-sign token: {out.stderr.strip()}")
    return tok


def main() -> int:
    tok = token()
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, bool, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()

        def go(path: str, wait: int = 8000):
            page.goto(f"{BASE}{path}?auto_signed={tok}", wait_until="domcontentloaded")
            page.wait_for_timeout(wait)

        # BUG-0774 — the navigation editor says the tree does not exist.
        go("/navigation-editor/does-not-exist-xyz")
        body = page.inner_text("body")
        ok = "cannot be opened" in body and "0/0 nodes" not in body
        results.append(("BUG-0774 nav editor says the tree does not exist", ok,
                        "not-found screen" if ok else body[:200]))
        page.screenshot(path=str(OUT / "bug-0774.png"))

        # BUG-0795 — the unknown-screens page for an interface that does not exist.
        go("/configuration/interface/no-such-interface/unknown")
        body = page.inner_text("body")
        ok = 'User interface "no-such-interface" not found' in body and "has a node in its tree" not in body
        results.append(("BUG-0795 unknown screens says the interface does not exist", ok,
                        "404 shown" if ok else body[:200]))
        page.screenshot(path=str(OUT / "bug-0795.png"))

        # BUG-0775 — the review page shows the screenshot it asks the reviewer to judge.
        go("/training-review", wait=14000)
        body = page.inner_text("body")
        imgs = page.evaluate("""() => Array.from(document.querySelectorAll('img'))
            .filter(i => !(i.getAttribute('src') || '').includes('/logo'))
            .map(i => ({src: (i.getAttribute('src') || '').slice(0, 30), w: i.naturalWidth}))""")
        shown = [i for i in imgs if i["w"] > 0]
        ok = bool(shown) and "could not be loaded" not in body
        results.append((f"BUG-0775 training review shows the screenshot ({len(shown)}/{len(imgs)} loaded)", ok,
                        "picture on screen" if ok else body[:200]))
        page.screenshot(path=str(OUT / "bug-0775.png"))

        # BUG-0798 — every thumbnail of the unknown-screens page loads.
        go(f"/configuration/interface/{os.environ['QA_UI']}/unknown", wait=12000)
        for _ in range(10):
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(400)
        page.wait_for_timeout(6000)
        imgs = page.evaluate("""() => Array.from(document.querySelectorAll('img'))
            .filter(i => !(i.getAttribute('src') || '').includes('/logo'))
            .map(i => ({data: (i.getAttribute('src') || '').startsWith('data:'), w: i.naturalWidth}))""")
        shown = [i for i in imgs if i["w"] > 0]
        data_shown = [i for i in shown if i["data"]]
        ok = len(shown) == len(imgs) and len(imgs) > 0
        results.append((f"BUG-0798 unknown screens thumbnails load ({len(shown)}/{len(imgs)}, "
                        f"{len(data_shown)} inline)", ok,
                        "all thumbnails" if ok else f"{len(imgs) - len(shown)} still empty"))
        page.screenshot(path=str(OUT / "bug-0798.png"))

        # BUG-0797 — the retired OpenRouter page points at the AI settings.
        go("/configuration/openrouter")
        ok = "/configuration/settings" in page.url and "tab=ai" in page.url
        results.append(("BUG-0797 OpenRouter address opens Settings -> AI", ok, page.url))
        page.screenshot(path=str(OUT / "bug-0797.png"))

        # BUG-0800 — the API reference offers every published spec.
        go("/docs/api")
        page.locator('[role="combobox"]').first.click()
        page.wait_for_timeout(1500)
        options = page.locator('[role="option"]').all_inner_texts()
        ok = len(options) >= 17
        results.append((f"BUG-0800 API reference offers every spec ({len(options)})", ok,
                        f"{len(options)} specs"))
        page.screenshot(path=str(OUT / "bug-0800.png"))
        page.keyboard.press("Escape")

        # BUG-0796 — the workspaces page prints the id that opens the workspace.
        go("/api/workspaces")
        body = page.inner_text("body")
        # The label and the value sit on their own lines; compare on one line.
        flat = " ".join(body.split())
        ok = "Workspace ID: workspace-virtualpytest" in flat and "Postman workspace ID:" in flat
        results.append(("BUG-0796 API workspaces prints the id that opens the workspace", ok,
                        "both ids labelled" if ok else flat[:200]))
        page.screenshot(path=str(OUT / "bug-0796.png"))

        # BUG-0799 — the first tab stop shows where the keyboard is.
        go("/", wait=8000)
        page.keyboard.press("Tab")
        page.wait_for_timeout(800)
        outline = page.evaluate("""() => {
            const el = document.activeElement;
            if (!el) return null;
            const s = getComputedStyle(el);
            return {tag: el.tagName, outline: s.outlineWidth + ' ' + s.outlineStyle + ' ' + s.outlineColor};
        }""")
        ok = bool(outline) and outline["outline"].split(" ")[0] not in ("0px", "none")
        results.append((f"BUG-0799 scope picker shows the focus ({outline['outline'] if outline else 'no element'})", ok,
                        "outline on the first tab stop"))
        page.screenshot(path=str(OUT / "bug-0799.png"))

        browser.close()

    print(json.dumps({"build": "main-2026.10.22-89628", "results": [
        {"check": c, "ok": ok, "detail": d} for c, ok, d in results]}, indent=2))
    failed = [c for c, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
