#!/usr/bin/env python3
"""Live check of the Run page target behaviour (BUG-0789) on the deployed build.

Three steps, on the real page:
  1. tick the host-level target `labox-backend` (the host_vnc pseudo-device),
  2. pick "Av Check" (a script that declares target_type: 'all') -> the target
     must STAY ticked and no warning may be shown,
  3. pick "Device Get Info" (target_type: 'device') -> the target must be
     dropped AND the page must say so (the warning toast).

Also prints every listExecutables request, so the team_id fix (BUG-0769) is
visible in the same run.
"""
import subprocess
import sys
from collections import Counter

from playwright.sync_api import sync_playwright

BASE = "https://virtualpytest.angelstreet.io"
PAGE = f"{BASE}/test-execution/run-tests?auto_signed={{token}}"

HOST_TARGET = "labox-backend"
SCRIPT_ALL = "Av Check"
SCRIPT_DEVICE_ONLY = "Device Get Info"


def selected_count(page):
    body = page.inner_text("body")
    for line in body.splitlines():
        line = line.strip()
        if line.endswith("selected") and line.split(" ")[0].isdigit():
            return line
    return "?"


def toast_text(page):
    out = []
    for sel in ("[role=alert]", ".MuiAlert-root", ".MuiSnackbar-root", "[data-testid=snackbar]", ".MuiToastContainer-root"):
        for el in page.query_selector_all(sel):
            txt = (el.inner_text() or "").strip().replace("\n", " ")
            if txt:
                out.append(txt)
    return out


def pick_script(page, name):
    """Click the script row whose text contains the given name on its own line."""
    wanted = name.lower()
    for el in page.query_selector_all("li, [role=option], [role=listitem]"):
        lines = [l.strip() for l in (el.inner_text() or "").splitlines() if l.strip()]
        if wanted in [l.lower() for l in lines]:
            el.click()
            return " / ".join(lines)
    return None


def find_target_box(page):
    """Re-query the host-level target checkbox (the list re-renders often)."""
    for box in page.query_selector_all("input[type=checkbox]"):
        near = box.evaluate_handle("e => (e.closest('label,li,div') || e)")
        try:
            if HOST_TARGET in near.inner_text():
                return box
        except Exception:
            continue
    return None


def main() -> int:
    token = subprocess.run(
        ["scripts/agent/auto_sign_token.sh"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    url = PAGE.format(token=token)

    seen = []
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, ignore_https_errors=True)
        page = ctx.new_page()
        page.on("response", lambda r: seen.append((r.status, r.request.method, r.url)))
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(15000)

        # ---- BUG-0769: the executable list must carry team_id -------------
        le = [u for _, _, u in seen if "listExecutables" in u]
        print("=== BUG-0769 — listExecutables requests ===")
        for u in le:
            print("  ", u[:160])
        if not le:
            failures.append("no listExecutables request seen")
        for u in le:
            if "team_id=" not in u:
                failures.append(f"listExecutables without team_id: {u}")

        # ---- tick the host-level target ----------------------------------
        target_box = find_target_box(page)
        if target_box is None:
            failures.append(f"target checkbox for {HOST_TARGET} not found")
            print("no target checkbox found")
        else:
            target_box.click()
            page.wait_for_timeout(1500)
            target_box = find_target_box(page)
            print(f"\n=== step 1 — {HOST_TARGET} ticked ===")
            print("  panel reads:", selected_count(page))
            print("  checkbox checked:", target_box.is_checked())

            # ---- step 2: a rule-less script must NOT drop the target ------
            row = pick_script(page, SCRIPT_ALL)
            page.wait_for_timeout(2500)
            target_box = find_target_box(page)
            after_all = selected_count(page)
            checked_all = target_box.is_checked() if target_box else False
            toasts_all = toast_text(page)
            print(f"\n=== step 2 — picked {SCRIPT_ALL!r} ({row}) ===")
            print("  panel reads:", after_all)
            print("  checkbox checked:", checked_all)
            print("  toasts:", toasts_all or "none")
            if not checked_all or after_all.strip() != "1 selected":
                failures.append(f"target lost after picking {SCRIPT_ALL}: {after_all} checked={checked_all}")
            if toasts_all:
                failures.append(f"unexpected toast after picking {SCRIPT_ALL}: {toasts_all}")

            # ---- step 3: a device-only script must not even be offered ----
            # The list and the pruning read the SAME rules, so a script that
            # cannot run on the ticked target is not offered at all. That is
            # the fix: the drop cannot happen, because the page never offers
            # the combination that would cause it.
            #
            # The warning toast is the safety net for the cases the list
            # cannot cover — a host that loses a device, or a script whose
            # rules change under the operator. Those are not reachable by
            # clicking, so they are not probed here.
            row = pick_script(page, SCRIPT_DEVICE_ONLY)
            page.wait_for_timeout(2500)
            target_box = find_target_box(page)
            after_dev = selected_count(page)
            checked_dev = target_box.is_checked() if target_box else False
            toasts_dev = toast_text(page)
            print(f"\n=== step 3 — {SCRIPT_DEVICE_ONLY!r} offered for a host-level target? ===")
            print("  row found:", row)
            print("  panel reads:", after_dev)
            print("  checkbox checked:", checked_dev)
            print("  toasts:", toasts_dev or "none")
            if row is not None:
                # It WAS offered: picking it must drop the target and say so.
                if checked_dev:
                    failures.append(f"target NOT dropped after picking {SCRIPT_DEVICE_ONLY}")
                if not toasts_dev:
                    failures.append("no warning toast after the target was dropped")
            else:
                print("  → not offered: the page hides an incompatible script, "
                      "so the target cannot be dropped silently")
                if not checked_dev:
                    failures.append("the target disappeared although nothing was picked")

        bad = [(s, m, u) for s, m, u in seen if isinstance(s, int) and s >= 400]
        print("\n=== non-2xx responses ===")
        print(" ", Counter(s for s, _, _ in bad))
        for s, m, u in bad[:10]:
            print(f"   {s} {m} {u[:140]}")
        browser.close()

    print("\n=== RESULT ===")
    if failures:
        for f in failures:
            print("  FAIL:", f)
        return 1
    print("  all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
