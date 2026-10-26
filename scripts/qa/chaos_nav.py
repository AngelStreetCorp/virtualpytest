#!/usr/bin/env python3
"""
QA chaos: open every top-level navigation menu, enumerate every item, click
each item and check that it lands on a page that renders.

Read-only. Records: the menu items found (so the coverage matrix is complete),
the route each item lands on, console errors, HTTP errors, blank pages and
horizontal overflow.

Usage:
  python3 chaos_nav.py --viewport desktop --theme dark --out /tmp/qa-chaos/nav-desktop-dark.json
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "https://virtualpytest.angelstreet.io"
TOKEN_FILE = "/tmp/vpt_qa_chaos.token"
EVIDENCE = "/home/jndoye/virtualpytest-qa-chaos/docs/tasks/qa-evidence/chaos"

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "phone": {"width": 390, "height": 844},
}

# Top-level nav labels that open a dropdown.
DROPDOWNS = ["AI", "Test", "Monitoring", "Pages", "Docs", "Plugins", "Settings"]

MENU_JS = r"""
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 3 || r.height < 3) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };
  const poppers = Array.from(document.querySelectorAll('[role="menu"], .MuiPopover-root, .MuiMenu-root, ul'))
    .filter(visible);
  const out = [];
  for (const p of poppers) {
    const r = p.getBoundingClientRect();
    if (r.height < 20) continue;
    const items = Array.from(p.querySelectorAll('[role="menuitem"], a[href], li button, li a, button'))
      .filter(visible)
      .map(el => {
        const rr = el.getBoundingClientRect();
        const href = el.getAttribute('href') || '';
        return {
          name: (el.getAttribute('aria-label') || el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80),
          href, x: rr.x + rr.width / 2, y: rr.y + rr.height / 2,
        };
      })
      .filter(i => i.name && i.name.length > 0);
    if (items.length) out.push({ items });
  }
  return out;
}
"""

PROBE_JS = r"""
() => {
  const de = document.documentElement;
  const body = document.body;
  const text = (body.innerText || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => { const r = el.getBoundingClientRect(); if (r.width < 4 || r.height < 4) return false;
    const st = getComputedStyle(el); return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0'; };
  const spinners = Array.from(document.querySelectorAll('.MuiCircularProgress-root'))
    .filter(el => visible(el) && !el.classList.contains('MuiLinearProgress-root')).length;
  const media = Array.from(document.querySelectorAll('img,canvas,video,svg')).filter(visible).length;
  return {
    textLen: text.length, text: text.slice(0, 250), media, spinners,
    docScrollW: de.scrollWidth, docClientW: de.clientWidth,
    heading: (document.querySelector('h1,h2') || {}).textContent || '',
    title: document.title, url: location.pathname,
  };
}
"""


def scrub(t, token):
    if not t:
        return t
    if token:
        t = t.replace(token, "<TOKEN>")
    return re.sub(r"(auto_signed=)[A-Za-z0-9_\-]{16,}", r"\1<TOKEN>", t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewport", default="desktop", choices=list(VIEWPORTS))
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="nav")
    args = ap.parse_args()

    token = Path(TOKEN_FILE).read_text().strip()
    ev = Path(EVIDENCE)
    ev.mkdir(parents=True, exist_ok=True)

    out = {"viewport": args.viewport, "theme": args.theme, "menus": [], "items": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport=VIEWPORTS[args.viewport])
        ctx.add_init_script(
            "try { localStorage.setItem('theme-mode', %s); localStorage.setItem('vpt_auto_signed','true');"
            " sessionStorage.setItem('vpt_auto_signed','true'); } catch(e) {}" % json.dumps(args.theme)
        )
        page = ctx.new_page()
        console_msgs, page_errors, http_errors = [], [], []

        def on_console(m):
            if m.type == "error":
                console_msgs.append(scrub(m.text, token)[:400])

        def on_pageerror(e):
            page_errors.append(scrub(str(e), token)[:500])

        def on_resp(r):
            if r.status >= 400:
                http_errors.append({"status": r.status, "url": scrub(r.url, token)[:200]})

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_resp)

        page.goto(f"{BASE}/?auto_signed={token}", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4500)

        def open_menu(menu):
            """Open a top-level dropdown; return True when it opened."""
            for sel in [
                f"button:has-text('{menu}')",
                f"[role='button']:has-text('{menu}')",
                f"a:has-text('{menu}')",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count() and el.is_visible():
                        el.click(timeout=5000)
                        page.wait_for_timeout(900)
                        return True
                except Exception:
                    continue
            return False

        for menu in DROPDOWNS:
            console_msgs.clear(); page_errors.clear(); http_errors.clear()
            opened = open_menu(menu)
            if not opened:
                out["menus"].append({"menu": menu, "opened": False, "items": []})
                print(f"  ?? menu {menu}: could not open", flush=True)
                continue
            page.wait_for_timeout(600)
            menus = page.evaluate(MENU_JS)
            items = []
            seen = set()
            for m in menus:
                for it in m["items"]:
                    key = it["name"]
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(it)
            shot = ev / f"{args.prefix}-{args.viewport}-{args.theme}-menu-{menu.lower().replace(' ', '-')}.png"
            try:
                page.screenshot(path=str(shot))
            except Exception:
                shot = None
            out["menus"].append({"menu": menu, "opened": True, "items": [i["name"] for i in items],
                                  "screenshot": str(shot) if shot else ""})
            print(f"  == menu {menu}: {len(items)} items", flush=True)

            for it in items:
                console_msgs.clear(); page_errors.clear(); http_errors.clear()
                rec = {"menu": menu, "name": it["name"], "href": it.get("href", "")}
                # The menu closes as soon as one item is used, so open it again
                # for every item and click the item by its visible name.
                external = (it.get("href") or "").startswith("http") and \
                    "virtualpytest.angelstreet.io" not in (it.get("href") or "")
                if external:
                    rec["skipped"] = "external link"
                    out["items"].append(rec)
                    continue
                try:
                    if not open_menu(menu):
                        raise RuntimeError("menu did not reopen")
                    loc = page.locator('[role="menuitem"]', has_text=it["name"]).first
                    loc.click(timeout=6000)
                    page.wait_for_timeout(2800)
                except Exception as e:
                    rec["clickError"] = scrub(str(e), token)[:200]
                try:
                    probe = page.evaluate(PROBE_JS)
                except Exception:
                    probe = {}
                rec["url"] = probe.get("url", "")
                rec["heading"] = probe.get("heading", "")
                rec["textLen"] = probe.get("textLen", 0)
                rec["spinners"] = probe.get("spinners", 0)
                rec["overflow"] = (probe.get("docScrollW", 0) - probe.get("docClientW", 0))
                rec["consoleErrors"] = console_msgs[:4]
                rec["pageErrors"] = page_errors[:3]
                rec["httpErrors"] = [h for h in http_errors if h["status"] in (401, 403, 404, 500, 502, 503)][:4]
                if probe.get("textLen", 0) < 25 and probe.get("media", 0) == 0:
                    rec["blank"] = True
                out["items"].append(rec)
                flag = ""
                if rec.get("pageErrors"):
                    flag += " CRASH"
                if rec.get("blank"):
                    flag += " BLANK"
                if rec.get("overflow", 0) > 12:
                    flag += f" OVERFLOW+{rec['overflow']}"
                if rec.get("httpErrors"):
                    flag += " HTTP"
                if rec.get("consoleErrors"):
                    flag += " CONSOLE"
                print(f"     - {it['name'][:34]:36s} -> {rec['url'][:42]:44s}{flag}", flush=True)
                # go back to the home page so the next menu opens cleanly
                try:
                    page.goto(f"{BASE}/?auto_signed={token}", wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2600)
                except Exception:
                    pass

        ctx.close()
        browser.close()

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\n-> {args.out}: {sum(len(m['items']) for m in out['menus'])} menu items")


if __name__ == "__main__":
    main()
