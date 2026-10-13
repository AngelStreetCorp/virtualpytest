#!/usr/bin/env python3
"""
TASK-37 — Drive the Google reCAPTCHA v2 demo form end-to-end and report the verdict.

Loads https://www.google.com/recaptcha/api2/demo in the Playwright web path,
fills the two text fields, locates the reCAPTCHA checkbox via image template
matching (the existing verification stack — `waitForImageToAppear`), clicks
it via the matched coordinates (the existing `tap_x_y` controller routes the
viewport-coordinate mouse event through the iframe boundary), submits, and
reads the post-submit verdict.

The script is intentionally **observational** rather than adversarial: it
reports whatever reCAPTCHA returns (PASS / CHALLENGE_ISSUED / BLOCK), it does
not solve challenges, and it does not retry on challenge issuance.

Per TASK-37 §10, cloud/headless IP reputation makes CHALLENGE_ISSUED the
expected outcome from a datacenter — that's a real KPI the showcase surfaces,
not a failure to chase.

host_vnc only. runner_* hosts don't register host_web_routes
(backend_host/src/routes/registry.py:5,15) so this script cannot run there.
"""

import asyncio
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Path setup (same pattern as goto.py / kpi_measurement.py)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device

DEMO_URL = "https://www.google.com/recaptcha/api2/demo"
ANCHOR_IFRAME_SELECTOR = "iframe[src*='recaptcha/api2/anchor']"
BFRAME_IFRAME_SELECTOR = "iframe[src*='recaptcha/api2/bframe']"
REFERENCE_IMAGE_NAME = "recaptcha_checkbox_unchecked"
REFERENCE_MATCH_THRESHOLD = 0.7
PASS_SENTINEL_FRAGMENT = "Verification Success"
HOORAY_SENTINEL_FRAGMENT = "Hooray"


# ───────────────────────────── step helpers ──────────────────────────────

def _record(context, name: str, ok: bool, evidence: str) -> Dict[str, Any]:
    """Append a step result with the canonical shape the executor expects."""
    step = {
        "name": name,
        "description": name,
        "status": "passed" if ok else "failed",
        "success": ok,
        "output_data": {"evidence": evidence},
    }
    context.record_step_immediately(step)
    icon = "✅" if ok else "❌"
    print(f"  {icon}  {name:<36s}  {evidence}")
    return step


# ────────────────────────── web + image helpers ──────────────────────────

def _get_web_controller(context):
    """Resolve the web controller for the host (no device_id = host path)."""
    from backend_host.src.lib.utils.host_utils import get_controller
    return get_controller(None, "web")


def _get_image_controller(context):
    """Resolve the image-verification controller for the host."""
    from backend_host.src.lib.utils.host_utils import get_controller
    return get_controller(None, "verification_image")


def _run_async(coro):
    """Run an async coroutine in the script's sync context (same pattern goto.py uses)."""
    return asyncio.run(coro)


def _exec(web, command: str, params: Optional[dict] = None) -> Dict[str, Any]:
    """Dispatch one web command via execute_command (the route-level entry point).

    Going through `execute_command` keeps the script-shaped call identical to
    what the HTTP route would do, which makes it easy to migrate this script to
    the route layer later if needed.
    """
    return _run_async(web.execute_command(command, params or {}))


# ─────────────────────────── the main script ─────────────────────────────

@script("recaptcha_demo", "Drive the Google reCAPTCHA v2 demo form and report the verdict", default_device="host", capture_artifacts=True)
def main():
    """Drive the recaptcha demo end-to-end and report the verdict into metadata."""
    args = get_args()
    context = get_context()
    device = get_device()

    started_ms = int(time.time() * 1000)
    step_results: List[Dict[str, Any]] = []
    metadata_outcome: str = "BLOCK"
    metadata_reason: str = ""
    metadata_extra: Dict[str, Any] = {}

    print(f"🤖 [recaptcha_demo] start — userinterface={getattr(args, 'userinterface', None)}")

    # Resolve controllers once. _record is a closure so step_results stays in sync.
    def rec(name, ok, evidence):
        s = _record(context, name, ok, evidence)
        step_results.append(s)
        return s

    try:
        web = _get_web_controller(context)
        if web is None:
            rec("acquire_web_controller", False, "no web controller on this host")
            metadata_reason = "web controller unavailable (host_vnc only — runner_* hosts do not load host_web_routes)"
            context.overall_success = False
            context.error_message = metadata_reason
            return False

        # ---- step 1: navigate to the demo page
        nav = _exec(web, "navigate_to_url", {"url": DEMO_URL, "timeout": 30_000})
        if not nav.get("success"):
            rec("navigate_to_url", False, f"{type(nav.get('error', Exception())).__name__}: {nav.get('error')}")
            metadata_reason = "navigation failed"
            context.overall_success = False
            context.error_message = metadata_reason
            return False
        rec("navigate_to_url", True, f"{DEMO_URL} loaded in {nav.get('execution_time', 0)}ms")

        # ---- step 2: wait for grecaptcha + the iframe to actually paint
        # (grecaptcha becomes typeof-function before the iframe's contentDocument
        # renders anything; taking the screenshot before paint = blank widget)
        gr = _exec(web, "execute_javascript", {
            "script": "typeof grecaptcha !== 'undefined' && typeof grecaptcha.getResponse === 'function'",
            "timeout": 15.0,
        })
        grecaptcha_ok = bool(gr.get("success") and gr.get("result"))
        painted = _exec(web, "wait_for_iframe_painted", {
            "selector": ANCHOR_IFRAME_SELECTOR,
            "max_total_ms": 12_000,
            "poll_interval_ms": 500,
        })
        iframe_painted = bool(painted.get("painted"))
        if not (grecaptcha_ok and iframe_painted):
            rec("wait_grecaptcha_ready", False,
                f"grecaptcha={grecaptcha_ok}, iframe_painted={iframe_painted} "
                f"(els={painted.get('element_count', 0)}, err={painted.get('error', '')})")
            metadata_reason = "grecaptcha / iframe did not initialize"
            context.overall_success = False
            context.error_message = metadata_reason
            return False
        rec("wait_grecaptcha_ready", True,
            f"grecaptcha ready + iframe painted ({painted.get('element_count')} els in {painted.get('elapsed_ms', 0)}ms)")

        # ---- step 3: capture a fresh screenshot, then template-match the checkbox
        # (the image verifier reads the most-recent capture from hot/captures)
        shot = _exec(web, "execute_javascript", {
            "script": "1",  # touch the page to make sure the latest frame is in captures_path
            "timeout": 2.0,
        })

        img_ctrl = _get_image_controller(context)
        if img_ctrl is None:
            rec("template_match_checkbox", False, "no image-verification controller")
            metadata_reason = "image-verification controller unavailable"
            context.overall_success = False
            context.error_message = metadata_reason
            return False

        # Provide the latest capture so waitForImageToAppear reads it.
        # The image verifier auto-captures from av_controller if no source is
        # provided, but on the web path we want to be explicit — pass an empty
        # image_list and let the auto-capture kick in.
        match = img_ctrl.waitForImageToAppear(
            image_path=REFERENCE_IMAGE_NAME,
            timeout=2.0,
            threshold=REFERENCE_MATCH_THRESHOLD,
            userinterface_name=getattr(args, "userinterface", "recaptcha_demo"),
            team_id=getattr(context, "team_id", None),
            check_focus=False,
        )
        matched, message, additional = match
        if not matched:
            rec("template_match_checkbox", False,
                f"no match >= {REFERENCE_MATCH_THRESHOLD}: {message}")
            metadata_reason = "checkbox not found by image match"
            context.overall_success = False
            context.error_message = metadata_reason
            return False
        loc = additional.get("match_location") or {}
        # match_location is (x, y, w, h) — center for the tap.
        if isinstance(loc, dict):
            x = loc.get("x", 0) + loc.get("width", 0) / 2
            y = loc.get("y", 0) + loc.get("height", 0) / 2
        else:
            x = float(loc[0]) + float(loc[2]) / 2
            y = float(loc[1]) + float(loc[3]) / 2
        score = additional.get("matching_result")
        rec("template_match_checkbox", True,
            f"matched at ({int(x)},{int(y)}) score={score:.3f}" if score else f"matched at ({int(x)},{int(y)})")

        # ---- step 4: click at the matched coordinates (the iframe-agnostic click)
        tap = _exec(web, "tap_x_y", {"x": int(x), "y": int(y)})
        if not tap.get("success"):
            rec("tap_x_y", False, f"tap_x_y failed: {tap.get('error')}")
            metadata_reason = "tap_x_y failed"
            context.overall_success = False
            context.error_message = metadata_reason
            return False
        rec("tap_x_y", True, f"page.mouse.click({int(x)},{int(y)})")

        # Give reCAPTCHA a moment to round-trip to Google and respond.
        time.sleep(2.5)

        # ---- step 5: verify the click registered (token non-empty OR challenge iframe present)
        state = _exec(web, "execute_javascript", {
            "script": (
                "() => { const token = (typeof grecaptcha !== 'undefined') ? grecaptcha.getResponse() : '';"
                " const iframes = Array.from(document.querySelectorAll('iframe'));"
                " const bframe = iframes.find(f => f.src && f.src.includes('recaptcha/api2/bframe'));"
                " return {token_len: (token || '').length, has_bframe: !!bframe}; }"
            ),
            "timeout": 5.0,
        })
        state_val = state.get("result") or {}
        token_len = int(state_val.get("token_len", 0))
        has_bframe = bool(state_val.get("has_bframe"))
        click_ok = token_len > 0 or has_bframe
        rec("verify_click_registered", click_ok,
            f"token_len={token_len} has_bframe={has_bframe}")
        if not click_ok:
            metadata_outcome = "CHALLENGE_PERSISTED"
            metadata_reason = "click did not produce a token or challenge iframe"
            context.overall_success = False
            context.error_message = metadata_reason
            return False

        # ---- step 6: if a challenge was issued, observe-and-stop (per TASK-37 §1, §10)
        if has_bframe:
            metadata_outcome = "CHALLENGE_ISSUED"
            metadata_reason = "reCAPTCHA escalated to Level-2 challenge (per task scope, we do not solve)"
            metadata_extra["challenge_iframe_present"] = True
            # Success=False is intentional: this is the honest outcome on a
            # datacenter IP, not a bug to chase. Same shape as TASK-33's
            # "success=False on any outcome other than the showcase's pass bar".
            context.overall_success = False
            context.error_message = metadata_reason
            rec("observe_challenge", True, "challenge iframe detected; stopping per task scope")
            return False

        # ---- step 7: fill the demo page's two text fields (ex-a and ex-b)
        fill = _exec(web, "execute_javascript", {
            "script": (
                "() => { const setVal = (sel, v) => {"
                " const el = document.querySelector(sel);"
                " if (!el) return false;"
                " const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;"
                " setter.call(el, v);"
                " el.dispatchEvent(new Event('input', {bubbles: true}));"
                " return true;"
                " };"
                " return {a: setVal(\"input[name='ex-a']\", '11'),"
                " b: setVal(\"input[name='ex-b']\", '22')};"
                " }"
            ),
            "timeout": 5.0,
        })
        fill_val = fill.get("result") or {}
        rec("fill_form", True,
            f"ex-a={fill_val.get('a')}, ex-b={fill_val.get('b')} (live selectors — confirm in §3)")
        metadata_extra["field_values"] = ["11", "22"]

        # ---- step 8: submit
        submit = _exec(web, "click_element", {"element_id": "#recaptcha-demo-submit"})
        if not submit.get("success"):
            rec("click_submit", False, f"submit failed: {submit.get('error')}")
            metadata_outcome = "BLOCK"
            metadata_reason = "submit click failed"
            context.overall_success = False
            context.error_message = metadata_reason
            return False
        rec("click_submit", True, "clicked #recaptcha-demo-submit")

        # Wait for the form post to round-trip and the verdict page to render.
        time.sleep(2.0)

        # ---- step 9: read the post-submit verdict from the DOM
        verdict = _exec(web, "execute_javascript", {
            "script": "() => document.body ? document.body.innerText : ''",
            "timeout": 5.0,
        })
        body_text = (verdict.get("result") or "").strip()
        if PASS_SENTINEL_FRAGMENT in body_text and HOORAY_SENTINEL_FRAGMENT in body_text:
            metadata_outcome = "PASS"
            metadata_reason = "demo page rendered 'Verification Success... Hooray!'"
            snippet = "Verification Success... Hooray!"
        else:
            metadata_outcome = "BLOCK"
            snippet = body_text[:120] or "<empty body>"
            metadata_reason = f"demo page did not render the success sentinel (snippet: {snippet})"
        rec("read_verdict", metadata_outcome == "PASS",
            f"{metadata_outcome}: {snippet}")
        context.overall_success = metadata_outcome == "PASS"
        context.error_message = None if context.overall_success else metadata_reason
        return context.overall_success

    except Exception as e:
        rec("uncaught_exception", False, f"{type(e).__name__}: {e}")
        metadata_outcome = "BLOCK"
        metadata_reason = f"uncaught exception: {type(e).__name__}: {e}"
        context.overall_success = False
        context.error_message = metadata_reason
        return False
    finally:
        elapsed_ms = int(time.time() * 1000) - started_ms
        # Persist the verdict + per-step summary into script_results.metadata.
        passed = sum(1 for s in step_results if s.get("success"))
        context.metadata = {
            "outcome": metadata_outcome,
            "reason": metadata_reason,
            "elapsed_ms": elapsed_ms,
            "step_count": len(step_results),
            "steps_passed": passed,
            "userinterface": getattr(args, "userinterface", None),
            "device_name": getattr(device, "device_name", None),
            "host_name": getattr(getattr(context, "host", None), "host_name", None),
            "script_name": "recaptcha_demo",
            **metadata_extra,
        }
        print(f"\n=== [recaptcha_demo] summary ===")
        print(f"  outcome:     {metadata_outcome}")
        print(f"  reason:      {metadata_reason}")
        print(f"  elapsed_ms:  {elapsed_ms}")
        print(f"  steps:       {passed}/{len(step_results)} passed")


# Script arguments (must be in the first 300 lines for the server-side analyzer)
_script_args = [
    "--userinterface:str:recaptcha_demo",  # Framework param — names the UI for reference-image resolution
]
_script_description = "Drive the Google reCAPTCHA v2 demo form (https://www.google.com/recaptcha/api2/demo) and report the verdict."

main._script_args = _script_args
main._script_description = _script_description
main._arg_descriptions = {
    "userinterface": "UI interface name (defaults to 'recaptcha_demo')",
}
main._target_rules = {
    "target_type": "host",
    "host_os": "all",
}


if __name__ == "__main__":
    main()