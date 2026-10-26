#!/usr/bin/env python3
"""Measure the /remote-test layout and its orientation request (BUG-0781).

Reports the bounding boxes of the pieces that are said to overlap, and the
method/status of every /server/remote/ request the page makes.
"""
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "https://virtualpytest.angelstreet.io"


def box(page, needle: str):
    return page.evaluate(
        """(needle) => {
            const els = [...document.querySelectorAll('*')].filter(e => {
                const t = (e.textContent || '').trim();
                return t.startsWith(needle) && t.length < 80 && e.children.length < 6;
            });
            const el = els[els.length - 1];
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
        }""",
        needle,
    )


def overlap(a, b):
    if not a or not b:
        return None
    x = max(0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    y = max(0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return x * y


def main() -> int:
    token = subprocess.run(
        ["scripts/agent/auto_sign_token.sh"], capture_output=True, text=True, check=True
    ).stdout.strip()
    reqs = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=True)
        pg = ctx.new_page()
        pg.on("response", lambda r: reqs.append((r.request.method, r.status, r.url)))
        pg.goto(f"{BASE}/remote-test?auto_signed={token}", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(9000)

        mock = box(pg, "Mock AV Stream")
        testing = box(pg, "Testing Area")
        recmodal = box(pg, "Use RecHostStreamModal Layout")
        android = box(pg, "Test Android Mobile")
        print("Mock AV Stream box :", mock)
        print("Testing Area box   :", testing)
        print("RecHostStreamModal :", recmodal)
        print("Test Android Mobile :", android)
        print("mock x testing area :", overlap(mock, testing))
        print("mock x android      :", overlap(mock, android))
        print("mock x recmodal     :", overlap(mock, recmodal))

        # The remote panel: the box that holds the remote buttons.
        panel = pg.evaluate(
            """() => {
                const btns = [...document.querySelectorAll('button')].filter(b => /Scr/.test(b.textContent || ''));
                if (!btns.length) return null;
                const r = btns[0].getBoundingClientRect();
                const last = btns[btns.length - 1].getBoundingClientRect();
                return {
                    first: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                    last: {x: Math.round(last.x), y: Math.round(last.y), w: Math.round(last.width), h: Math.round(last.height)},
                    count: btns.length,
                    labels: btns.map(x => (x.textContent || '').trim().slice(0, 12)),
                    viewportH: window.innerHeight,
                };
            }"""
        )
        print("remote panel buttons:", panel)
        b.close()

    print("\n/server/remote requests:")
    for method, status, url in reqs:
        if "/server/remote" in url:
            print(f"  {method:5} {status} {url[:130]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
