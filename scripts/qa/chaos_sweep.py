#!/usr/bin/env python3
"""
QA chaos walker — VirtualPyTest app.

Reads the auto-sign token from a file, walks every route in routes.json at a
given viewport/theme, and records: console errors, uncaught exceptions, failed
requests, HTTP >=400 responses, blank/white screens, stuck spinners, horizontal
overflow and clipped text. Screenshots go to an evidence dir.

Usage:
  python3 scripts/qa/chaos_sweep.py --viewport desktop --theme dark \
      --out /tmp/qa-chaos/pass-desktop-dark.json
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "https://virtualpytest.angelstreet.io"
TOKEN_FILE = "/tmp/vpt_qa_chaos.token"
EVIDENCE_DEFAULT = "docs/tasks/qa-evidence/chaos"

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "phone": {"width": 390, "height": 844},
}

# Noise we do not want to report as a finding.
IGNORE_CONSOLE = re.compile(
    r"(Download the React DevTools|"
    r"\[vite\] connect|"
    r"favicon|"
    r"was preloaded using link preload|"
    r"Consider using the .link. rel=preconnect|"
    r"MUI: You are using the deprecated|"
    r"prop `components` is deprecated|"
    r"Support for defaultProps will be removed|"
    r"React Router Future Flag|"
    r"Cannot update a component|"
    r"styled-components|"
    r"Each child in a list should have a unique|"
    r"Warning: An update to|"
    r"validateDOMNesting|"
    r"Unexpected text node|"
    r"Warning: React does not recognize|"
    r"not wrapped in act|"
    r"findDOMNode is deprecated|"
    r"style prop expects a mapping|"
    r"Warning: Each child)",
    re.I,
)

# Network noise that is not a page bug (websocket, beacons, trackers).
IGNORE_URL = re.compile(
    r"(ws://|wss://|/sockjs|favicon|/api/heartbeat|"
    r"google-analytics|googletagmanager|doubleclick|hotjar|"
    r"/server/system/getSessionStatus)",
    re.I,
)

DESTRUCTIVE = re.compile(
    r"(delete|remove|reset|restart|re-?start|deploy|publish|promote|rotat|"
    r"revoke|uninstall|stop|kill|discard|purge|clear all|wipe|terminat|"
    r"downgrade|factory|deprovision|revoke access|erase|drop\b|truncate|"
    r"deactivate|disable\s+account|move to trash)",
    re.I,
)
SAFE_WORDS = re.compile(
    r"(cancel|close|back|dismiss|esc|no thanks|not now|keep|abort)",
    re.I,
)


def scrub(text: str, token: str) -> str:
    if not text:
        return text
    if token:
        text = text.replace(token, "<TOKEN>")
    # scrub any 64-hex looking token in query strings
    text = re.sub(r"(auto_signed=)[A-Za-z0-9_\-]{16,}", r"\1<TOKEN>", text)
    text = re.sub(r"(X-Auto-Sign[':= ]+)[A-Za-z0-9_\-]{16,}", r"\1<TOKEN>", text)
    return text


PROBE_JS = r"""
() => {
  const de = document.documentElement;
  const body = document.body;
  const text = (body.innerText || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };
  // spinners
  const spinnerSel = '[role="progressbar"], .MuiCircularProgress-root, .MuiLinearProgress-root, .vpt-spinner';
  const spinners = Array.from(document.querySelectorAll(spinnerSel)).filter(visible);
  // media / canvas
  const media = Array.from(document.querySelectorAll('img,canvas,video,svg')).filter(visible).length;
  // overflow
  const vw = window.innerWidth;
  const over = [];
  const all = document.querySelectorAll('body *');
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const st = getComputedStyle(el);
    if (st.position === 'fixed') continue;
    if (r.right > vw + 12 || r.left < -12) {
      let p = el, id = '';
      while (p && p !== document.body) {
        if (p.id) { id = p.id; break; }
        p = p.parentElement;
      }
      const cls = (typeof el.className === 'string' ? el.className : '').slice(0, 60);
      over.push({ tag: el.tagName, id, cls, right: Math.round(r.right), left: Math.round(r.left), w: Math.round(r.width) });
      if (over.length > 6) break;
    }
  }
  // clipped text: scrollWidth > clientWidth with overflow hidden
  const clipped = [];
  for (const el of all) {
    if (el.children.length > 0) continue;
    const t = (el.textContent || '').trim();
    if (!t) continue;
    const st = getComputedStyle(el);
    if (st.overflow === 'visible' || st.overflowX === 'visible') continue;
    if (el.scrollWidth > el.clientWidth + 4 && el.clientWidth > 0) {
      clipped.push({ tag: el.tagName, cls: (typeof el.className === 'string' ? el.className : '').slice(0, 50), text: t.slice(0, 60), sw: el.scrollWidth, cw: el.clientWidth });
      if (clipped.length > 5) break;
    }
  }
  const h1 = document.querySelector('h1,h2');
  return {
    textLen: text.length,
    text: text.slice(0, 400),
    bodyChildren: body.children.length,
    media,
    spinners: spinners.length,
    docScrollW: de.scrollWidth,
    docClientW: de.clientWidth,
    innerW: window.innerWidth,
    scrollH: de.scrollHeight,
    overflowEls: over,
    clipped,
    heading: h1 ? (h1.textContent || '').trim().slice(0, 120) : '',
    bg: getComputedStyle(body).backgroundColor,
    title: document.title,
  };
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewport", default="desktop", choices=list(VIEWPORTS))
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--routes", default="/tmp/qa-chaos/routes.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--evidence", default=EVIDENCE_DEFAULT)
    ap.add_argument("--settle", type=float, default=6.0, help="seconds to wait after load before probing")
    ap.add_argument("--only", default="", help="comma-separated paths to limit to")
    ap.add_argument("--prefix", default="", help="screenshot filename prefix")
    ap.add_argument("--label", default="", help="label for this pass")
    args = ap.parse_args()

    token = Path(TOKEN_FILE).read_text().strip()
    routes = json.loads(Path(args.routes).read_text())
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        routes = [r for r in routes if r["path"] in wanted]

    ev = Path(args.evidence)
    ev.mkdir(parents=True, exist_ok=True)

    results = []
    vp = VIEWPORTS[args.viewport]

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--autoplay-policy=no-user-gesture-required"],
        )
        ctx = browser.new_context(
            viewport=vp,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        # theme + auto-sign must be in place before the first navigation
        ctx.add_init_script(
            "try { localStorage.setItem('theme-mode', %s); localStorage.setItem('vpt_auto_signed','true');"
            " sessionStorage.setItem('vpt_auto_signed','true'); } catch(e) {}" % json.dumps(args.theme)
        )
        page = ctx.new_page()

        console_msgs = []
        page_errors = []
        failed_reqs = []
        http_errors = []

        def on_console(msg):
            t = msg.text or ""
            if IGNORE_CONSOLE.search(t):
                return
            console_msgs.append({"type": msg.type, "text": scrub(t, token)[:600]})

        def on_pageerror(exc):
            page_errors.append(scrub(str(exc), token)[:800])

        def on_requestfailed(req):
            if IGNORE_URL.search(req.url):
                return
            failed_reqs.append({"url": scrub(req.url, token)[:300], "err": (req.failure or "")[:200]})

        def on_response(resp):
            if resp.status >= 400 and not IGNORE_URL.search(resp.url):
                http_errors.append({"url": scrub(resp.url, token)[:300], "status": resp.status})

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("requestfailed", on_requestfailed)
        page.on("response", on_response)

        for idx, r in enumerate(routes):
            path = r["path"]
            console_msgs.clear()
            page_errors.clear()
            failed_reqs.clear()
            http_errors.clear()
            url = f"{BASE}{path}"
            nav_url = f"{BASE}/?auto_signed={token}" if path == "/" else f"{BASE}{path}?auto_signed={token}"
            t0 = time.time()
            nav_err = ""
            try:
                page.goto(nav_url, wait_until="domcontentloaded", timeout=45000)
            except PWTimeout:
                nav_err = "navigation timeout (45s)"
            except Exception as e:  # noqa
                nav_err = scrub(str(e), token)[:300]
            load_ms = int((time.time() - t0) * 1000)
            try:
                page.wait_for_timeout(int(args.settle * 1000))
            except Exception:
                pass
            probe = {}
            try:
                probe = page.evaluate(PROBE_JS)
            except Exception as e:
                probe = {"probeError": scrub(str(e), token)[:300]}

            slug = (args.prefix or f"{args.viewport}-{args.theme}") + "-" + re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()
            if not slug.strip("-"):
                slug += "root"
            shot = ev / f"{slug}.png"
            try:
                page.screenshot(path=str(shot), full_page=False)
            except Exception as e:
                shot = None
                probe["screenshotError"] = scrub(str(e), token)[:200]

            entry = {
                "path": path,
                "label": r.get("label", ""),
                "group": r.get("group", ""),
                "viewport": args.viewport,
                "theme": args.theme,
                "loadMs": load_ms,
                "navError": nav_err,
                "finalUrl": scrub(page.url, token),
                "screenshot": str(shot) if shot else "",
                "consoleErrors": [m for m in console_msgs if m["type"] in ("error", "warning")],
                "pageErrors": list(page_errors),
                "failedRequests": list(failed_reqs),
                "httpErrors": list(http_errors),
                "probe": probe,
            }
            results.append(entry)
            print(
                f"[{idx+1}/{len(routes)}] {path:42s} {load_ms:6d}ms "
                f"txt={probe.get('textLen','?'):>6} spin={probe.get('spinners','?')} "
                f"ovf={probe.get('docScrollW','?')}/{probe.get('docClientW','?')} "
                f"ce={len(entry['consoleErrors'])} pe={len(entry['pageErrors'])} "
                f"http4xx={len(entry['httpErrors'])} fr={len(entry['failedRequests'])}",
                flush=True,
            )
            sys.stdout.flush()

        ctx.close()
        browser.close()

    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"\nwrote {args.out} ({len(results)} routes)")


if __name__ == "__main__":
    main()
