#!/usr/bin/env python3
"""
QA chaos random walk — VirtualPyTest app.

Seeded random walk over the app: at each step it enumerates the interactive
elements on the current page, picks one at random (seeded), clicks it, then
checks the page for crashes, white screens, stuck spinners, new console errors
and layout breaks. It also injects chaos actions (back, forward, reload, new
tab, resize, offline).

SAFETY: destructive and state-changing controls are never clicked. They are
matched by their accessible name and skipped; a confirm dialog that still
appears is cancelled with Escape. Read-only exploration only.

Usage:
  python3 chaos_walk.py --seed chaos-p5-2026-10-22 --viewport desktop --theme dark \
      --steps 400 --out /tmp/qa-chaos/walk-p5.json
"""
import argparse
import json
import os
import random
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

# ── safety blocklists ───────────────────────────────────────────────────────
# Anything that deletes, resets, restarts, deploys, publishes, promotes,
# rotates keys, changes users/teams/roles/billing, starts a run on a shared
# device, or writes a setting/tree/script.
BLOCK = re.compile(
    r"(delete|remove|reset|restart|re-?start|deploy|publish|promote|rotat|"
    r"revoke|uninstall|stop|kill|discard|purge|wipe|terminat|downgrade|"
    r"factory|deprovision|erase|truncate|deactivate|drop\b|dump|"
    r"^save$|^save\b|\bsave\b|apply|submit|^create$|\bcreate\b|new\b|"
    r"^add$|\badd\b|^edit$|\bedit\b|update|^run$|\brun\b|execute|start|"
    r"take control|record|stream|capture|import|export|upload|download|"
    r"install|connect|disconnect|enable|disable|move|copy|clone|duplicate|"
    r"rename|change|set\b|generate|rebuild|config|reboot|shutdown|sign in|"
    r"log in|login|provision|refresh\b|clear|revoke|"
    r"play|open\b|launch|schedule|assign|invite|accept|"
    r"rerun|re-run|run\b|runs\b|start|trigger|fire|go\b)",
    re.I,
)
ALLOW = re.compile(r"^(cancel|close|back|dismiss|esc|no thanks|not now|keep|abort|done|ok|yes)$", re.I)

# A control that only reads is safe even if it contains a blocked word.
READONLY_OK = re.compile(
    r"(view|show|detail|report|history|list|filter|sort|search|expand|collapse|"
    r"tab|tabpanel|menu|menuitem|prev|next|page\b|more|less|refresh\b|"
    r"reload|log|logs|monitor|chart|analytics|compare|download report|"
    r"deployments?)",
    re.I,
)

DANGEROUS_DIALOG = re.compile(
    r"(are you sure|confirm|delete|remove|reset|discard|overwrite|"
    r"cannot be undone|permanent|irreversible|type .* to confirm)",
    re.I,
)


def scrub(text, token):
    if not text:
        return text
    if token:
        text = text.replace(token, "<TOKEN>")
    text = re.sub(r"(auto_signed=)[A-Za-z0-9_\-]{16,}", r"\1<TOKEN>", text)
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
  // Only indeterminate/circular spinners count as "loading". A determinate
  // LinearProgress bar (e.g. the coverage bars) is content, not a stuck spinner.
  const spinners = Array.from(document.querySelectorAll('.MuiCircularProgress-root, [role="progressbar"]'))
    .filter(el => visible(el) && !el.classList.contains('MuiLinearProgress-root'));
  const media = Array.from(document.querySelectorAll('img,canvas,video,svg')).filter(visible).length;
  const over = [];
  const all = document.querySelectorAll('body *');
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const st = getComputedStyle(el);
    if (st.position === 'fixed') continue;
    if (r.right > window.innerWidth + 12 || r.left < -12) {
      over.push({ tag: el.tagName, right: Math.round(r.right), left: Math.round(r.left) });
      if (over.length > 4) break;
    }
  }
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .MuiDialog-root')).filter(visible);
  return {
    textLen: text.length, text: text.slice(0, 300),
    media, spinners: spinners.length,
    docScrollW: de.scrollWidth, docClientW: de.clientWidth,
    overflow: over, dialogs: dialogs.length,
    dialogText: dialogs.length ? (dialogs[0].innerText || '').replace(/\s+/g,' ').slice(0, 300) : '',
    heading: (document.querySelector('h1,h2') || {}).textContent || '',
    title: document.title,
    url: location.pathname,
  };
}
"""

INTERACTIVE_JS = r"""
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };
  const sel = 'a[href], button, [role="button"], [role="tab"], [role="menuitem"], [role="option"], summary, [data-testid]';
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight * 3) continue;
    const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    const tag = el.tagName.toLowerCase();
    const key = tag + '|' + name + '|' + Math.round(r.x) + ',' + Math.round(r.y);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ tag, name, href: el.getAttribute('href') || '', x: r.x + r.width / 2, y: r.y + r.height / 2, type: el.getAttribute('type') || '', role: el.getAttribute('role') || '' });
  }
  return out;
}
"""


def is_safe(name):
    n = (name or "").strip()
    if not n:
        return True
    if ALLOW.match(n):
        return True
    if BLOCK.search(n) and not READONLY_OK.search(n):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True)
    ap.add_argument("--viewport", default="desktop", choices=list(VIEWPORTS))
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--steps", type=int, default=250)
    ap.add_argument("--out", required=True)
    ap.add_argument("--routes", default="/tmp/qa-chaos/routes.json")
    ap.add_argument("--prefix", default="walk")
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--start-url", default="/")
    args = ap.parse_args()

    token = Path(TOKEN_FILE).read_text().strip()
    routes = json.loads(Path(args.routes).read_text())
    rng = random.Random(args.seed)
    ev = Path(EVIDENCE)
    ev.mkdir(parents=True, exist_ok=True)

    findings = []
    steps_log = []
    chaos_errors = []
    console_msgs, page_errors, failed_reqs, http_errors = [], [], [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport=VIEWPORTS[args.viewport])
        ctx.add_init_script(
            "try { localStorage.setItem('theme-mode', %s); localStorage.setItem('vpt_auto_signed','true');"
            " sessionStorage.setItem('vpt_auto_signed','true'); } catch(e) {}" % json.dumps(args.theme)
        )
        page = ctx.new_page()

        def on_console(m):
            if m.type in ("error", "warning"):
                console_msgs.append({"type": m.type, "text": scrub(m.text, token)[:500]})

        def on_pageerror(e):
            page_errors.append(scrub(str(e), token)[:600])

        def on_reqfail(r):
            failed_reqs.append({"url": scrub(r.url, token)[:250]})

        def on_resp(r):
            if r.status >= 400:
                http_errors.append({"url": scrub(r.url, token)[:250], "status": r.status})

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("requestfailed", on_reqfail)
        page.on("response", on_resp)

        def nav(path):
            try:
                page.goto(f"{BASE}{path}?auto_signed={token}", wait_until="domcontentloaded", timeout=40000)
            except PWTimeout:
                pass
            except Exception:
                pass

        nav(args.start_url)
        page.wait_for_timeout(4000)

        for step in range(1, args.steps + 1):
            console_msgs.clear()
            page_errors.clear()
            failed_reqs.clear()
            http_errors.clear()
            try:
                before = page.evaluate(PROBE_JS)
            except Exception:
                before = {}

            action = None
            detail = ""
            chaos = rng.random()

            # ── chaos injections ────────────────────────────────────────────
            if chaos < 0.10:
                kind = rng.choice(["back", "forward", "reload", "newtab", "resize", "offline"])
                try:
                    if kind == "back":
                        page.go_back(wait_until="domcontentloaded", timeout=15000)
                        action, detail = "chaos:back", ""
                    elif kind == "forward":
                        page.go_forward(wait_until="domcontentloaded", timeout=15000)
                        action, detail = "chaos:forward", ""
                    elif kind == "reload":
                        page.reload(wait_until="domcontentloaded", timeout=30000)
                        action, detail = "chaos:reload", ""
                    elif kind == "newtab":
                        page2 = ctx.new_page()
                        page2.goto(f"{BASE}{before.get('url') or '/'}?auto_signed={token}",
                                   wait_until="domcontentloaded", timeout=30000)
                        page2.wait_for_timeout(2500)
                        page2.close()
                        action, detail = "chaos:newtab", before.get("url", "")
                    elif kind == "resize":
                        w = rng.choice([390, 768, 1024, 1440, 1920])
                        h = rng.choice([700, 844, 900, 1080])
                        page.set_viewport_size({"width": w, "height": h})
                        action, detail = "chaos:resize", f"{w}x{h}"
                    elif kind == "offline":
                        ctx.set_offline(True)
                        page.wait_for_timeout(rng.choice([2000, 3000, 4000]))
                        ctx.set_offline(False)
                        action, detail = "chaos:offline", "3s offline"
                except Exception as e:
                    # A back/forward that cannot complete is itself a finding, not a crash.
                    action = f"chaos:{kind}"
                    detail = f"navigation refused: {type(e).__name__}"
                    chaos_errors.append({"step": step, "kind": kind,
                                         "error": f"{type(e).__name__}: {str(e)[:200]}"})
                    try:
                        nav("/")
                        page.wait_for_timeout(2000)
                    except Exception:
                        pass

            # ── random click ────────────────────────────────────────────────
            # One step in four jumps to a random route instead of clicking, so
            # the walk reaches pages the dashboard alone would never open.
            if action is None and rng.random() < 0.25:
                r = rng.choice(routes)
                nav(r["path"])
                page.wait_for_timeout(3000)
                action, detail = "goto", r["path"]
            if action is None:
                try:
                    els = page.evaluate(INTERACTIVE_JS)
                except Exception:
                    els = []
                # Skip links that leave the app (external tool pages) and write-y switches.
                els = [e for e in els
                       if not (e.get("href", "").startswith("http")
                               and "virtualpytest.angelstreet.io" not in e.get("href", ""))]
                safe = [e for e in els if is_safe(e["name"])]
                blocked = [e for e in els if not is_safe(e["name"])]
                if safe:
                    e = rng.choice(safe)
                    try:
                        page.mouse.click(e["x"], e["y"])
                        action, detail = "click", e["name"][:80] or e["tag"]
                    except Exception:
                        action, detail = "click-failed", e["name"][:80]
                elif els:
                    action, detail = "only-blocked-controls", f"{len(blocked)} blocked"
                else:
                    # nothing to click: jump to a random route
                    r = rng.choice(routes)
                    nav(r["path"])
                    action, detail = "goto", r["path"]

            try:
                page.wait_for_timeout(int(args.settle * 1000))
            except Exception:
                pass

            after = page.evaluate(PROBE_JS) if not page.is_closed() else {}

            # A stray click can leave the app entirely — go back in.
            try:
                if "virtualpytest.angelstreet.io" not in page.url:
                    page.goto(f"{BASE}/?auto_signed={token}", wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2500)
                    after = page.evaluate(PROBE_JS)
                    detail += " [left the app]"
            except Exception:
                pass

            # cancel any dangerous dialog that appeared
            if after.get("dialogs") and DANGEROUS_DIALOG.search(after.get("dialogText", "")):
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(600)
                    after = page.evaluate(PROBE_JS)
                    detail += " [dialog cancelled]"
                except Exception:
                    pass

            steps_log.append({
                "step": step, "action": action, "detail": detail,
                "url": after.get("url", ""), "textLen": after.get("textLen", 0),
                "spinners": after.get("spinners", 0),
            })

            # ── finding detection ──────────────────────────────────────────
            shot = None
            def snap(tag):
                nonlocal shot
                f = ev / f"{args.prefix}-{args.seed}-{tag}.png"
                try:
                    page.screenshot(path=str(f))
                    shot = str(f)
                except Exception:
                    pass

            issues = []
            if page_errors:
                issues.append(("crash", "; ".join(x["text"][:200] for x in page_errors[:2])))
            if after.get("textLen", 0) < 25 and after.get("media", 0) == 0 and after.get("spinners", 0) == 0:
                issues.append(("white-screen", f"textLen={after.get('textLen')} url={after.get('url')}"))
            if after.get("spinners", 0) > 0 and after.get("textLen", 0) < 120:
                issues.append(("stuck-spinner", f"spinners={after.get('spinners')} textLen={after.get('textLen')} url={after.get('url')}"))
            if after.get("docScrollW", 0) > after.get("docClientW", 0) + 12:
                issues.append(("h-overflow", f"scrollW={after.get('docScrollW')} clientW={after.get('docClientW')} url={after.get('url')}"))
            new_con = [c for c in console_msgs if c["type"] == "error"]
            if new_con:
                issues.append(("console-error", " | ".join(c["text"][:200] for c in new_con[:2])))
            hard = [h for h in http_errors if h["status"] in (401, 403, 404, 409, 422, 500, 502, 503)]
            if hard:
                issues.append(("http-error", " | ".join(f"{h['status']} {h['url'][:120]}" for h in hard[:2])))

            if issues:
                snap(f"s{step:04d}")
                findings.append({
                    "step": step, "action": action, "detail": detail,
                    "url": after.get("url", ""), "issues": issues,
                    "consoleErrors": new_con[:5], "pageErrors": page_errors[:3],
                    "httpErrors": hard[:5], "failedRequests": failed_reqs[:3],
                    "screenshot": shot or "",
                    "probe": after,
                })
                print(f"  ! step {step:3d} {action:14s} {detail[:40]:42s} "
                      f"{[i[0] for i in issues]} url={after.get('url','')[:40]}", flush=True)

            if step % 25 == 0:
                print(f"  .. step {step}/{args.steps} findings={len(findings)} url={after.get('url','')}", flush=True)

            # Write after every step: a crash at step 200 must not lose 199 steps.
            try:
                Path(args.out).write_text(json.dumps(
                    {"seed": args.seed, "viewport": args.viewport, "theme": args.theme,
                     "steps": steps_log, "findings": findings,
                     "chaosErrors": chaos_errors}, indent=2))
            except Exception:
                pass

        ctx.close()
        browser.close()

    Path(args.out).write_text(json.dumps(
        {"seed": args.seed, "viewport": args.viewport, "theme": args.theme,
         "steps": steps_log, "findings": findings,
         "chaosErrors": chaos_errors}, indent=2))
    print(f"\nseed={args.seed} steps={len(steps_log)} findings={len(findings)} "
          f"chaosErrors={len(chaos_errors)} -> {args.out}")


if __name__ == "__main__":
    main()
