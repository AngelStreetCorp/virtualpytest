#!/usr/bin/env python3
"""
Shared core of the content-surface test suite (radio / replay / vod / recording).

ONE harness, one case per feature, one machine-readable result line per case.

The harness owns:
  * the case list and the case lifecycle (run -> record -> continue);
  * the result line format and the cause classification;
  * the small platform helpers every adapter needs (navigate, press, capture,
    motion probe).

The platform mechanics live in `test_scripts/content/adapters/<platform>.py`.
An adapter implements the four case methods and nothing else; it must never
write the result line itself.

Result line (one per case, on stdout, and in `context.metadata['content_cases']`):

    VPT_CASE_RESULT {"case":"radio","platform":"web","host":"host-clone-2",
    "device":"host","status":"FAIL","cause":"product","duration_s":31.2,
    "reason":"playback did not start: video element paused after 8s"}

`status` is PASS / FAIL / SKIP. `cause` is the separate attribution the owner
asked for, so a coverage gap is never counted as a product defect:

    product  the surface was reached and behaved wrongly -> a defect to fix
    infra    the platform could not do the job: lease, deploy, connectivity,
             timeout, a host that is down -> not a product defect
    coverage the surface is not reachable / not mapped in this UI -> the test
             could not exercise it, which is a gap in the test, not a defect

The rule the whole suite rests on: an exception that reaches the runner is a
HARNESS bug (cause=infra). A product-facing failure must be caught by the
adapter and returned as a CaseOutcome with cause=product, because only the
adapter can tell "the app crashed" from "our click missed".

Underscore-prefixed on purpose: `is_discoverable_script_ref` hides it from the
RunTests picker. It is not a runnable script.
"""

import asyncio
import json
import os
import sys
import time

# Add project root to path so the helper imports work from anywhere.
# The virtual-script converter rewrites this block (it only ever reads
# `project_root`, never `current_dir`), so keep the canonical shape.
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# --------------------------------------------------------------------------
# contract constants
# --------------------------------------------------------------------------

CASES = ("radio", "replay", "vod", "recording")

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

CAUSE_PRODUCT = "product"
CAUSE_INFRA = "infra"
CAUSE_COVERAGE = "coverage"

RESULT_MARKER = "VPT_CASE_RESULT"
SUMMARY_MARKER = "VPT_CASE_SUMMARY"


# --------------------------------------------------------------------------
# result objects
# --------------------------------------------------------------------------

class CaseOutcome:
    """What one case concluded.

    `status` is PASS / FAIL / SKIP. `cause` is the attribution (product / infra /
    coverage) and is only meaningful for FAIL and SKIP. `evidence` is a small
    JSON-able dict for the report (what was played, what was seen).
    """

    def __init__(self, status, reason, cause=None, evidence=None):
        self.status = status
        self.reason = (reason or "").strip() or "no reason given"
        self.cause = cause or (CAUSE_PRODUCT if status == STATUS_FAIL else None)
        self.evidence = evidence or {}

    @classmethod
    def passed(cls, reason, evidence=None):
        return cls(STATUS_PASS, reason, cause=None, evidence=evidence)

    @classmethod
    def failed(cls, reason, cause=CAUSE_PRODUCT, evidence=None):
        return cls(STATUS_FAIL, reason, cause=cause, evidence=evidence)

    @classmethod
    def skipped(cls, reason, cause=CAUSE_COVERAGE, evidence=None):
        """The case could not exercise the surface.

        The default cause is `coverage`: the surface is not reachable / not
        mapped in this UI. Pass cause=infra for a platform problem that
        prevented the attempt.
        """
        return cls(STATUS_SKIP, reason, cause=cause, evidence=evidence)

    def to_dict(self, case, platform, host, device, duration_s):
        row = {
            "case": case,
            "platform": platform,
            "host": host or "",
            "device": device or "",
            "status": self.status,
            "cause": self.cause or "",
            "duration_s": round(float(duration_s or 0.0), 2),
            "reason": self.reason,
        }
        if self.evidence:
            row["evidence"] = self.evidence
        return row


def emit_result(row: dict) -> None:
    """Print one machine-readable result line. Exactly one per case."""
    print(f"{RESULT_MARKER} {json.dumps(row, ensure_ascii=False, sort_keys=True)}", flush=True)


def emit_summary(rows: list) -> None:
    """Print the run summary line (one per run, after the cases)."""
    counts = {STATUS_PASS: 0, STATUS_FAIL: 0, STATUS_SKIP: 0}
    causes = {CAUSE_PRODUCT: 0, CAUSE_INFRA: 0, CAUSE_COVERAGE: 0}
    for row in rows:
        counts[row.get("status")] = counts.get(row.get("status"), 0) + 1
        cause = row.get("cause")
        if cause:
            causes[cause] = causes.get(cause, 0) + 1
    summary = {
        "cases": len(rows),
        "pass": counts[STATUS_PASS],
        "fail": counts[STATUS_FAIL],
        "skip": counts[STATUS_SKIP],
        "product": causes[CAUSE_PRODUCT],
        "infra": causes[CAUSE_INFRA],
        "coverage": causes[CAUSE_COVERAGE],
    }
    print(f"{SUMMARY_MARKER} {json.dumps(summary, sort_keys=True)}", flush=True)
    return summary


# --------------------------------------------------------------------------
# case context
# --------------------------------------------------------------------------

class CaseContext:
    """Everything one case needs: the device, the script context, the args.

    `spec` is the platform adapter's own spec for this case (node labels, key
    names, wait times). Adapters own their specs; the harness does not know
    what a "radio node" is on any given platform.
    """

    def __init__(self, device, context, args, case, platform, spec=None):
        self.device = device
        self.context = context
        self.args = args
        self.case = case
        self.platform = platform
        self.spec = spec or {}
        self.notes = []
        self._zap = None

    # -- logging ----------------------------------------------------------
    def log(self, message):
        print(f"[{self.platform}/{self.case}] {message}", flush=True)

    def note(self, message):
        """Record a fact for the report evidence (kept short)."""
        self.notes.append(str(message))
        return message

    # -- argument helpers -------------------------------------------------
    def arg(self, name, default=None):
        value = getattr(self.args, name, None)
        if value is None or value == "":
            return default
        return value

    def userinterface(self):
        return (self.arg("userinterface_name")
                or self.arg("userinterface")
                or getattr(self.context, "userinterface", None)
                or "")

    def variant(self):
        return self.arg("variant") or None

    # -- device helpers ---------------------------------------------------
    def controller(self, kind):
        """The first controller of a kind, or None.

        `remote` for the IR/BLE/appium remotes, `web` for the browser.
        """
        getter = getattr(self.device, "_get_controller", None)
        if getter is None:
            return None
        try:
            return getter(kind)
        except Exception:
            return None

    def zap_executor(self):
        """A ZapExecutor for the motion probe (cached per case)."""
        if self._zap is not None:
            return self._zap
        from shared.src.lib.executors.zap_executor import ZapExecutor
        threshold = float(self.arg("motion_threshold", 1.0) or 1.0)
        window = min(2.0, max(0.0, float(self.arg("motion_window_s", 2.0) or 2.0)))
        self._zap = ZapExecutor(self.device, self.userinterface(),
                                motion_threshold=threshold,
                                motion_duration=window)
        return self._zap


# --------------------------------------------------------------------------
# shared platform helpers (used by every adapter)
# --------------------------------------------------------------------------

def sleep(ctx: CaseContext, seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(float(seconds))


def capture(ctx: CaseContext, label: str):
    """Take a screenshot for the report. Returns the path or None."""
    try:
        from shared.src.lib.utils.device_utils import capture_screenshot_for_script
        capture_screenshot_for_script(ctx.device, ctx.context, label)
        paths = getattr(ctx.context, "screenshot_paths", None) or []
        return paths[-1] if paths else None
    except Exception as exc:                                   # noqa: BLE001
        ctx.log(f"screenshot '{label}' failed: {exc}")
        return None


def exception_cause(exc: BaseException) -> str:
    """Which cause an exception gets when an adapter catches it.

    A product-facing error (the app refused, the player did not start, the
    surface is broken) is a PRODUCT defect. A programming error — our own
    bug, a changed API, a missing attribute — is NOT the product's fault, so
    it is INFRA. Blaming the product for a typo in this file is exactly the
    confusion the cause split exists to prevent.
    """
    if isinstance(exc, (TypeError, AttributeError, NameError, KeyError,
                        ImportError, IndexError, UnboundLocalError)):
        return CAUSE_INFRA
    return CAUSE_PRODUCT


def tree_id_for(ctx: CaseContext):
    """The tree id of the run, loading it once if the executor has not."""
    tree_id = getattr(ctx.context, "tree_id", None)
    if tree_id:
        return tree_id
    executor = getattr(ctx.device, "navigation_executor", None)
    if executor is None:
        return None
    loaded = executor.load_navigation_tree(ctx.userinterface(),
                                           getattr(ctx.context, "team_id", None))
    if not loaded.get("success"):
        return None
    tree_id = loaded.get("tree_id")
    ctx.context.tree_id = tree_id
    return tree_id


def node_exists(ctx: CaseContext, node_label: str) -> bool:
    """Is this node label in the tree the device is driving?

    The distinction matters for the cause split: a node that is NOT in the
    tree is a coverage gap (this UI has no such surface), while a node that
    IS in the tree and still cannot be opened is a product failure.
    """
    if not node_label:
        return False
    executor = getattr(ctx.device, "navigation_executor", None)
    if executor is None:
        return False
    tree_id = tree_id_for(ctx)
    if not tree_id:
        return False
    try:
        node_id = executor.get_node_id(node_label, tree_id,
                                       getattr(ctx.context, "team_id", None))
    except Exception:                                           # noqa: BLE001
        # The label is not in the graph (or the graph is unavailable).
        return False
    return bool(node_id)


# The navigation executor says this when it reached the node but the screen
# does not look like the picture the tree expects. That is the TEST's
# expectation being wrong for this device (a tree built on another box, a
# changed screen), not the product misbehaving.
_VERIFICATION_MISMATCH_MARKERS = (
    "not detected in source", "match score", "required:", "verification failed",
    "reference image", "does not match", "no match",
)

# A navigation that runs out of time is a platform fact: the screen never
# answered. It says nothing about the product, so it must never be reported
# as a defect of the product -- not even when the node IS in the tree.
_NAVIGATION_TIMEOUT_MARKERS = (
    "did not finish within", "never answered", "timed out", "timeout",
)


def verification_mismatch(detail: str) -> bool:
    """Did the navigation reach the node but fail the tree's own check?"""
    text = (detail or "").lower()
    return any(marker in text for marker in _VERIFICATION_MISMATCH_MARKERS)


def navigation_timeout(detail: str) -> bool:
    """Did the navigation run out of time instead of failing?

    `navigate_to` bounds every navigation and says so in its own words. A
    platform that did not answer in time cannot tell us anything about the
    product.
    """
    text = (detail or "").lower()
    return any(marker in text for marker in _NAVIGATION_TIMEOUT_MARKERS)


def surface_failure(ctx: CaseContext, node_label: str, detail: str,
                    reason: str = "") -> CaseOutcome:
    """The right outcome for a surface that could not be opened.

    Three different things can hide behind one "it did not work":

    * the node is NOT in the tree → COVERAGE: this UI has no such surface.
      A gap in the test, not a defect.
    * the navigation reached the node but the screen does not match the tree's
      reference picture → INFRA: the tree's expectation is wrong for THIS
      device (the fleet's boxes differ, or the screen changed). The test
      cannot conclude anything about the product, so this must never be
      reported as a defect.
    * the navigation ran out of time → INFRA: the platform did not answer.
      That is a platform fact, never a defect of the product.
    * the node IS in the tree and the navigation genuinely failed → PRODUCT:
      the surface is there and it did not work.
    """
    text = reason or (f"could not open '{node_label}'"
                      + (f": {detail}" if detail else ""))
    if verification_mismatch(detail):
        return CaseOutcome.failed(
            f"infra: {text} — the screen does not match the tree's reference picture, "
            f"so this run cannot conclude anything about the product",
            cause=CAUSE_INFRA)
    if navigation_timeout(detail):
        return CaseOutcome.failed(
            f"infra: {text} — the platform did not answer in time, so this run cannot "
            f"conclude anything about the product",
            cause=CAUSE_INFRA)
    if node_exists(ctx, node_label):
        return CaseOutcome.failed(f"product: {text}", cause=CAUSE_PRODUCT)
    return CaseOutcome.skipped(f"coverage gap: {text}", cause=CAUSE_COVERAGE)


def navigate_to(ctx: CaseContext, node_label: str, tree_id=None, timeout_s: float = 90.0):
    """Navigate the device to a node of the current tree.

    Returns (ok: bool, detail: str). The detail is the executor's error text
    when it fails, so the case can say why it could not reach the surface.

    The navigation is bounded: the executor waits for an element that may
    never come, and a case that waits forever is a case that never reports.
    A navigation that runs out of time is a platform fact, so it reads as a
    failure of the route, not as a defect of the product.
    """
    if not node_label:
        return False, "no target node given"
    device = ctx.device
    executor = getattr(device, "navigation_executor", None)
    if executor is None:
        return False, "device has no navigation executor"
    if not tree_id:
        tree_id = tree_id_for(ctx)
    if not tree_id:
        return False, "navigation tree load failed"

    async def _run():
        return await executor.execute_navigation(
            tree_id=tree_id,
            userinterface_name=ctx.userinterface(),
            target_node_label=node_label,
            team_id=getattr(ctx.context, "team_id", None),
            context=ctx.context,
        )

    try:
        result = asyncio.run(asyncio.wait_for(_run(), timeout=timeout_s))
    except asyncio.TimeoutError:
        return False, (f"navigation to '{node_label}' did not finish within "
                       f"{timeout_s:.0f}s: the screen never answered")
    except Exception as exc:                                   # noqa: BLE001
        return False, f"navigation to '{node_label}' raised: {exc}"
    if not result.get("success"):
        return False, f"navigation to '{node_label}' failed: {result.get('error') or 'unknown error'}"
    return True, result.get("error") or ""


def press_key(ctx: CaseContext, key_name: str, settle: float = 0.5):
    """Press a remote key on the device. Returns (ok: bool, detail: str).

    Only the remote transports (IR / BLE / appium) have a remote controller.
    A web device has none: the caller must use the web adapter's own actions.
    """
    remote = ctx.controller("remote")
    if remote is None:
        return False, "device has no remote controller"
    try:
        ok = remote.press_key(key_name)
    except Exception as exc:                                   # noqa: BLE001
        return False, f"press {key_name} raised: {exc}"
    sleep(ctx, settle)
    return bool(ok), "" if ok else f"press {key_name} was refused by the controller"


def run_async(coro):
    """Run a coroutine from the synchronous script body."""
    return asyncio.run(coro)


def web_action(ctx: CaseContext, command: str, params=None):
    """Send one command to the browser controller.

    Returns (ok: bool, detail: str, payload: dict). The browser controller's
    execute_command is async, hence the asyncio wrapper.
    """
    web = ctx.controller("web")
    if web is None:
        return False, "device has no web controller", {}
    try:
        result = asyncio.run(web.execute_command(command, params or {}))
    except Exception as exc:                                   # noqa: BLE001
        return False, f"web action '{command}' raised: {exc}", {}
    if not isinstance(result, dict):
        result = {"result": result}
    ok = bool(result.get("success", True))
    return ok, (result.get("error") or ""), result


def audio_probe(ctx: CaseContext, window_s: float = 8.0, level_db: float = -50.0) -> dict:
    """Is there sound on the device right now?

    This is the signal that proves an AUDIO-ONLY surface played. Screen motion
    cannot: a radio station is a static logo with sound, so "the picture did
    not move" says nothing about the audio.

    It reads the capture monitor's own per-frame analysis — the same source
    the av_check script reads — where every frame carries the mean volume in
    dB and the monitor's audio verdict. Nothing is recomputed here.

    Returns {'audible': bool | None, 'level_db': float | None, 'frames': int,
    'detail': str}. `audible` is None when the capture carries no audio
    analysis at all: then the case must NOT claim the audio was silent.
    """
    result = {"audible": None, "level_db": None, "frames": 0,
              "detail": "the capture carries no audio analysis"}
    device = ctx.device
    try:
        from backend_host.src.lib.utils.analysis_utils import (
            load_recent_analysis_data_from_path,
        )
    except Exception as exc:                                   # noqa: BLE001
        result["detail"] = f"the capture analysis is not available here: {exc}"
        return result

    av_controller = ctx.controller("av")
    capture_path = getattr(av_controller, "video_capture_path", None) if av_controller else None
    if not capture_path:
        result["detail"] = "this device has no AV controller, so there is nothing to analyse"
        return result

    try:
        loaded = load_recent_analysis_data_from_path(capture_path,
                                                     timeframe_minutes=2, max_count=None)
    except Exception as exc:                                   # noqa: BLE001
        result["detail"] = f"the capture analysis could not be read: {exc}"
        return result
    if not loaded.get("success"):
        result["detail"] = loaded.get("error") or "the capture analysis could not be read"
        return result

    now_ms = int(time.time() * 1000)
    window_ms = int(max(1.0, window_s) * 1000)
    levels = []
    audible_flags = []
    for item in loaded.get("analysis_data") or []:
        mtime = item.get("file_mtime") or 0
        if not mtime or not (now_ms - window_ms <= mtime <= now_ms + 5000):
            continue
        data = item.get("analysis_json") or {}
        if not isinstance(data, dict):
            continue
        level = data.get("mean_volume_db")
        if isinstance(level, (int, float)):
            levels.append(float(level))
        if data.get("audio") is not None:
            audible_flags.append(bool(data.get("audio")))
        result["frames"] += 1

    if not levels and not audible_flags:
        result["detail"] = ("no frame of the capture carries an audio reading "
                             f"(in the last {int(window_s)}s)")
        return result
    if levels:
        result["level_db"] = max(levels)
    if audible_flags:
        result["audible"] = any(audible_flags)
    elif levels:
        result["audible"] = result["level_db"] > level_db
    result["detail"] = (f"{result['frames']} frame(s), peak {result['level_db']} dB"
                         if result["level_db"] is not None
                         else f"{result['frames']} frame(s) with an audio verdict")
    return result


def motion_probe(ctx: CaseContext, threshold=None, window=None):
    """Frame-to-frame motion check on the device's screen.

    Returns a dict {playing: bool, change: float|None, detail: str}. Used by
    the platforms that have no media element to inspect (STB, Android phone).
    """
    try:
        zap = ctx.zap_executor()
        if threshold is not None:
            zap.motion_threshold = float(threshold)
        if window is not None:
            zap.motion_duration = min(2.0, max(0.0, float(window)))
        result = zap.detect_real_motion(ctx.context)
    except Exception as exc:                                   # noqa: BLE001
        return {"playing": False, "change": None, "detail": f"motion probe raised: {exc}"}
    if not result:
        return {"playing": False, "change": None,
                "detail": "motion detector returned no result (no capture on this device?)"}
    change = result.get("change")
    return {
        "playing": bool(result.get("motion")),
        "change": change,
        "detail": f"frame change {change}% (threshold {result.get('threshold')}%)"
                  if change is not None else "motion detector returned no verdict",
    }


# --------------------------------------------------------------------------
# the adapter interface
# --------------------------------------------------------------------------

class Adapter:
    """Platform mechanics for the four content cases.

    Subclasses set `platform` and implement the four `run_*` methods. Each
    returns a CaseOutcome. They must not raise for a product-facing problem:
    catch it and return CaseOutcome.failed(..., cause=CAUSE_PRODUCT).
    """

    platform = "unknown"

    def prepare(self, ctx: CaseContext) -> None:
        """Optional per-run setup (login, wake the device, open the app)."""

    def run_radio(self, ctx: CaseContext) -> CaseOutcome:
        raise NotImplementedError

    def run_replay(self, ctx: CaseContext) -> CaseOutcome:
        raise NotImplementedError

    def run_vod(self, ctx: CaseContext) -> CaseOutcome:
        raise NotImplementedError

    def run_recording(self, ctx: CaseContext) -> CaseOutcome:
        raise NotImplementedError

    def finish(self, ctx: CaseContext) -> None:
        """Optional per-run cleanup (leave the device in a sane state)."""


def detect_platform(device) -> str:
    """Which adapter fits this device.

    'stb' | 'web' | 'mobile' | 'unknown'. The device model is the signal the
    platform itself uses to route a device to a controller set.
    """
    model = (getattr(device, "device_model", "") or "").lower()
    if "stb" in model or "set_top" in model or "set-top" in model:
        return "stb"
    if model in ("web", "host_vnc", "browser") or "web" in model:
        return "web"
    if "android" in model or "mobile" in model or "phone" in model:
        return "mobile"
    return "unknown"


def build_adapter(platform: str, device, context, args):
    """Instantiate the adapter for a platform.

    The import is local so a missing platform module cannot break the other
    platforms.
    """
    platform = (platform or "").lower()
    if platform == "auto" or not platform:
        platform = detect_platform(device)
    if platform == "stb":
        from test_scripts.content._stb_adapter import StbAdapter as AdapterCls
    elif platform == "web":
        from test_scripts.content._web_adapter import WebAdapter as AdapterCls
    elif platform == "mobile":
        from test_scripts.content._mobile_adapter import MobileAdapter as AdapterCls
    else:
        raise ValueError(f"no adapter for platform '{platform}'")
    return AdapterCls()


# --------------------------------------------------------------------------
# the suite runner
# --------------------------------------------------------------------------

def run_suite(device, context, args, adapter, cases=None):
    """Run the requested cases, one after the other, and collect the rows.

    A failing case never stops the suite: the next case still runs. The
    returned list is one dict per case, in the order the cases ran.
    """
    cases = list(cases or CASES)
    rows = []

    host_name = ""
    try:
        host_name = getattr(getattr(context, "host", None), "host_name", "") or ""
    except Exception:
        host_name = ""
    device_name = getattr(device, "device_name", "") or ""

    try:
        adapter.prepare(CaseContext(device, context, args, "prepare", adapter.platform))
    except Exception as exc:                                   # noqa: BLE001
        ctx = CaseContext(device, context, args, "prepare", adapter.platform)
        ctx.log(f"prepare failed: {exc}")

    for case in cases:
        ctx = CaseContext(device, context, args, case, adapter.platform)
        started = time.time()
        try:
            runner = getattr(adapter, f"run_{case}", None)
            if runner is None:
                outcome = CaseOutcome.skipped(f"the {adapter.platform} adapter has no '{case}' case",
                                              cause=CAUSE_COVERAGE)
            else:
                outcome = runner(ctx)
                if not isinstance(outcome, CaseOutcome):
                    outcome = CaseOutcome.failed(
                        f"the '{case}' case returned {type(outcome).__name__}, not a CaseOutcome",
                        cause=CAUSE_INFRA)
        except Exception as exc:                               # noqa: BLE001
            # An exception that reaches here is a harness bug, not a product
            # defect: the adapter is supposed to catch product-facing errors
            # and return them as a CaseOutcome.
            outcome = CaseOutcome.failed(f"harness error in the '{case}' case: {exc}",
                                         cause=CAUSE_INFRA)
        duration = time.time() - started
        row = outcome.to_dict(case, adapter.platform, host_name, device_name, duration)
        if ctx.notes:
            row["notes"] = ctx.notes[-5:]
        rows.append(row)
        emit_result(row)

    try:
        adapter.finish(CaseContext(device, context, args, "finish", adapter.platform))
    except Exception as exc:                                   # noqa: BLE001
        print(f"[{adapter.platform}] finish failed: {exc}", flush=True)

    # Keep the rows in the run metadata so the dispatcher can read them back
    # from the persisted script result, not only from stdout.
    try:
        if not isinstance(context.metadata, dict):
            context.metadata = {}
        context.metadata["content_cases"] = rows
    except Exception:
        pass

    emit_summary(rows)
    return rows


def suite_passed(rows: list) -> bool:
    """Did the run pass?

    A FAIL fails the run. A SKIP does NOT: the surface was not there to test,
    so the run neither broke nor proved anything — the report keeps the split
    (a skipped case is never counted as a pass). An empty run is not a pass.
    """
    if not rows:
        return False
    return not any(row.get("status") == STATUS_FAIL for row in rows)
