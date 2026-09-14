#!/usr/bin/env python3
"""Shared local-debug browser helpers for web test scripts."""

import argparse
import asyncio
from contextlib import asynccontextmanager
import glob
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from shared.src.lib.utils.browser_window_utils import build_window_flags, detect_primary_display_bounds
from shared.src.lib.utils.dom_capture import capture_page_dom, get_dom_captures
from shared.src.lib.utils.report_step_formatter import format_timestamp_to_hhmmss_ms


def _record_browser_step(
    add_step: Optional[Callable[..., Any]],
    *,
    message: str,
    success: bool,
    actions: Optional[List[Dict[str, Any]]] = None,
    verifications: Optional[List[Dict[str, Any]]] = None,
    step_start_time: str = "",
    step_end_time: str = "",
    step_duration_ms: int = 0,
) -> None:
    if not add_step:
        return
    try:
        add_step(
            message,
            success,
            actions=actions,
            verifications=verifications,
            step_start_time=step_start_time,
            step_end_time=step_end_time,
            step_duration_ms=step_duration_ms,
        )
    except TypeError:
        add_step(
            message,
            success,
            actions=actions,
            verifications=verifications,
        )


def ensure_browser_session(
    web_controller: Any,
    *,
    add_step: Optional[Callable[..., Any]] = None,
    open_command: str = "web_controller.open_browser",
    final_verification_command: str = "assert_browser_connected",
) -> Dict[str, Any]:
    launch_step_started_at = time.time()
    launch_step_started_iso = datetime.now(timezone.utc).isoformat()
    launch_success = True
    launch_error = ""
    opened_now = False

    if not web_controller.is_connected:
        open_result = asyncio.run(web_controller.open_browser())
        if open_result.get("success"):
            opened_now = True
        else:
            launch_success = False
            launch_error = open_result.get("error", "Unknown")

    launch_step_ended_iso = datetime.now(timezone.utc).isoformat()
    launch_step_duration_ms = int((time.time() - launch_step_started_at) * 1000)
    _record_browser_step(
        add_step,
        message="Launch browser session",
        success=launch_success,
        actions=[{
            "command": open_command,
            "params": {"only_if_disconnected": True},
        }],
        verifications=[{
            "success": launch_success,
            "label": "Browser available",
            "command": final_verification_command,
            "details": {"error": launch_error} if launch_error else {},
        }],
        step_start_time=launch_step_started_iso,
        step_end_time=launch_step_ended_iso,
        step_duration_ms=launch_step_duration_ms,
    )

    return {
        "success": launch_success,
        "error": launch_error,
        "opened_now": opened_now,
    }


def prepare_persistent_profile(user_data_dir: str) -> None:
    os.makedirs(user_data_dir, exist_ok=True)
    for pattern in ("Crash Reports", "chrome_debug.log", "Singleton*", "Singelton*"):
        for path in glob.glob(os.path.join(user_data_dir, pattern)):
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except Exception:
                pass

    for pref_path in (
        os.path.join(user_data_dir, "Default", "Preferences"),
        os.path.join(user_data_dir, "Preferences"),
    ):
        if not os.path.exists(pref_path):
            continue
        try:
            with open(pref_path, "r", encoding="utf-8") as f:
                content = f.read()
            if '"exit_type":"Crashed"' in content:
                content = content.replace('"exit_type":"Crashed"', '"exit_type":"Normal"')
                with open(pref_path, "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception:
            pass


def resolve_chrome_executable(custom_path: str = "") -> str:
    if custom_path and os.path.exists(custom_path):
        return custom_path
    if platform.system() == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if platform.system() == "Windows":
        return "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    for path in ("/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"):
        if os.path.exists(path):
            return path
    return ""


def wait_for_cdp_port(host: str, port: int, timeout_s: int = 30) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.connect((host, port))
                return True
            except Exception:
                time.sleep(0.5)
    return False


def launch_chrome_for_cdp(
    debug_port: int,
    user_data_dir: str = "",
    chrome_executable: str = "",
    profile_name: str = "cdp_profile",
    headless: bool = False,
    ignore_certificate_errors: bool = False,
):
    executable_path = resolve_chrome_executable(chrome_executable)
    if not executable_path:
        raise RuntimeError("Chrome executable not found")

    if not user_data_dir:
        user_data_dir = os.path.join(tempfile.gettempdir(), f"virtualpytest_{profile_name}")

    prepare_persistent_profile(user_data_dir)

    # The CDP port is exclusive — one test browser at a time. If something
    # already listens here, name it EXPLICITLY before killing it: the elapsed
    # time tells whether it's a CONCURRENT test's browser (seconds/minutes,
    # that run will now fail with "browser has been closed") or a browser
    # LEFT BEHIND by a previous test that did not close cleanly (older).
    try:
        if platform.system() != "Windows":
            out = subprocess.run(
                ["lsof", "-ti", f":{debug_port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0 and out.stdout.strip():
                pids = [p.strip() for p in out.stdout.splitlines() if p.strip()]
                details = []
                for pid in pids:
                    try:
                        ps = subprocess.run(
                            ["ps", "-p", pid, "-o", "pid=,etime=,comm="],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        details.append(" ".join((ps.stdout.strip() or pid).split()))
                    except Exception:
                        details.append(pid)
                print(
                    f"[local_debug_browser_helpers] ⚠️ ANOTHER BROWSER IS ALREADY RUNNING on CDP "
                    f"port {debug_port} — killing it to keep a single test browser. "
                    f"Owner (pid elapsed cmd): {'; '.join(details)}. "
                    "If elapsed is small, a concurrent test owned it and that run will fail with "
                    "'browser has been closed'; if elapsed is large, the previous test did not "
                    "close its browser cleanly."
                )
                for pid in pids:
                    try:
                        os.kill(int(pid), 9)
                    except Exception:
                        pass
                time.sleep(1)
    except Exception:
        pass

    window_bounds = detect_primary_display_bounds()

    chrome_flags = [
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-component-update",
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--disable-features=DialMediaRouteProvider,MediaRouter",
        "--disable-dev-shm-usage",
        "--disable-features=Translate",
        "--disable-extensions",
        "--disable-component-extensions-with-background-pages",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-domain-reliability",
        "--metrics-recording-only",
        "--no-pings",
        "--log-level=3",
        "--disable-gpu",
        "--enable-unsafe-swiftshader",
        "--hide-crash-restore-bubble",
        "--disable-webgpu",
        "--use-gl=swiftshader",
    ] + build_window_flags() + [
        "--start-maximized",
    ]
    if ignore_certificate_errors:
        chrome_flags.append("--ignore-certificate-errors")
    if headless:
        chrome_flags.append("--headless=new")
    print(
        "[local_debug_browser_helpers] Launching Chrome with bounds "
        f'{window_bounds["width"]}x{window_bounds["height"]}+{window_bounds["x"]}+{window_bounds["y"]}'
    )
    process = subprocess.Popen([executable_path] + chrome_flags)
    if not wait_for_cdp_port("127.0.0.1", debug_port, timeout_s=30):
        try:
            process.terminate()
        except Exception:
            pass
        raise RuntimeError(f"Chrome CDP port {debug_port} did not open")
    return process


async def open_local_debug_playwright_session(
    playwright_instance: Any,
    *,
    profile_name: str,
    headless: bool = False,
    debug_port: int = 9222,
    chrome_executable: str = "",
    user_data_dir: str = "",
    viewport: Optional[Dict[str, int]] = None,
    record_video_dir: str = "",
    reuse_existing_page: bool = False,
    ignore_https_errors: bool = False,
) -> Dict[str, Any]:
    """Open a local Playwright CDP session with consistent bootstrap metadata."""
    launch_started_at = time.time()
    launch_started_iso = datetime.now(timezone.utc).isoformat()

    launched_process = launch_chrome_for_cdp(
        debug_port=debug_port,
        user_data_dir=user_data_dir,
        chrome_executable=chrome_executable,
        profile_name=profile_name,
        headless=headless,
        ignore_certificate_errors=ignore_https_errors,
    )
    browser = await playwright_instance.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
    print(
        f"[local_debug_browser_helpers] ✅ Connected to Chrome via CDP on port {debug_port} "
        f"({len(browser.contexts)} context(s))",
        flush=True,
    )

    if browser.contexts:
        context = browser.contexts[0]
    else:
        new_context_kwargs: Dict[str, Any] = {}
        if record_video_dir:
            new_context_kwargs["record_video_dir"] = record_video_dir
        if viewport:
            new_context_kwargs["viewport"] = viewport
        if ignore_https_errors:
            new_context_kwargs["ignore_https_errors"] = True
        context = await browser.new_context(**new_context_kwargs)

    if reuse_existing_page and context.pages:
        page = context.pages[0]
    else:
        page = await context.new_page()

    launch_ended_iso = datetime.now(timezone.utc).isoformat()
    launch_duration_ms = int((time.time() - launch_started_at) * 1000)

    return {
        "launched_process": launched_process,
        "browser": browser,
        "context": context,
        "page": page,
        "launch_started_iso": launch_started_iso,
        "launch_ended_iso": launch_ended_iso,
        "launch_duration_ms": launch_duration_ms,
        "debug_port": debug_port,
    }


@asynccontextmanager
async def local_debug_playwright_session(
    *,
    profile_name: str,
    headless: bool = False,
    debug_port: int = 9222,
    chrome_executable: str = "",
    user_data_dir: str = "",
    viewport: Optional[Dict[str, int]] = None,
    record_video_dir: str = "",
    reuse_existing_page: bool = False,
    ignore_https_errors: bool = False,
) -> AsyncIterator[Dict[str, Any]]:
    """Open a local-debug Playwright session with a shared async_playwright lifecycle."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright_instance:
        session = await open_local_debug_playwright_session(
            playwright_instance,
            profile_name=profile_name,
            headless=headless,
            debug_port=debug_port,
            chrome_executable=chrome_executable,
            user_data_dir=user_data_dir,
            viewport=viewport,
            record_video_dir=record_video_dir,
            reuse_existing_page=reuse_existing_page,
            ignore_https_errors=ignore_https_errors,
        )
        yield session


async def diagnose_browser_death(
    exc: Exception,
    *,
    page: Any = None,
    browser: Any = None,
    launched_process: Any = None,
    debug_port: int = 9222,
) -> str:
    """On a 'browser has been closed' style failure, report WHAT died and WHY.

    Distinguishes the three causes we keep confusing:
      - our PAGE (tab) was closed but the browser lives  → gateway/SPA closed the tab
      - the whole BROWSER is gone and OUR chrome pid exited → it crashed on its own
      - the browser is gone but a FOREIGN chrome now owns the CDP port → an external
        process (a concurrent run's launch) killed ours

    Best-effort and never raises. Returns the verdict string (also printed).
    """
    bits = [f"{type(exc).__name__}: {exc}"]
    try:
        if page is not None:
            bits.append(f"page.is_closed={page.is_closed()}")
    except Exception as e:
        bits.append(f"page.is_closed=?({e})")
    browser_connected = None
    try:
        if browser is not None:
            browser_connected = browser.is_connected()
            bits.append(f"browser.is_connected={browser_connected}")
    except Exception as e:
        bits.append(f"browser.is_connected=?({e})")

    our_pid = None
    try:
        if launched_process is not None:
            our_pid = launched_process.pid
            rc = launched_process.poll()
            bits.append(f"our_chrome_pid={our_pid} {'ALIVE' if rc is None else f'exited({rc})'}")
    except Exception as e:
        bits.append(f"our_chrome_pid=?({e})")

    # Who owns the CDP port now?
    foreign_owner = None
    try:
        if platform.system() != "Windows":
            out = subprocess.run(["lsof", "-ti", f":{debug_port}"], capture_output=True, text=True, timeout=5)
            pids = [p.strip() for p in out.stdout.splitlines() if p.strip()]
            bits.append(f"port_{debug_port}_owners={pids or 'none'}")
            foreign = [p for p in pids if str(p) != str(our_pid)]
            if foreign:
                foreign_owner = foreign
    except Exception as e:
        bits.append(f"port_owner=?({e})")

    # Verdict
    if page is not None and browser_connected and _safe_is_closed(page):
        verdict = "PAGE was closed while the browser stayed alive → gateway/SPA closed our tab"
    elif foreign_owner:
        verdict = (f"browser gone AND a FOREIGN process {foreign_owner} now owns port {debug_port} "
                   f"→ an external run killed our Chrome (concurrency)")
    elif browser_connected is False:
        verdict = "whole browser is gone (our chrome pid state above) → crash or external kill"
    else:
        verdict = "inconclusive — see fields above"

    line = f"[browser-death] {verdict} | {' | '.join(bits)}"
    print(line, flush=True)
    return line


def _safe_is_closed(page: Any) -> bool:
    try:
        return bool(page.is_closed())
    except Exception:
        return False


def append_local_debug_browser_launch_step(
    *,
    step_results: List[Dict[str, Any]],
    from_node: str,
    session: Dict[str, Any],
    command_name: str = "chromium.connect_over_cdp",
) -> None:
    """Append a standardized Playwright bootstrap step for local-debug scripts."""
    append_local_debug_step_result(
        step_results=step_results,
        message="Launch browser via CDP",
        success=True,
        from_node=from_node,
        actions=[{
            "command": command_name,
            "params": {"debug_port": session.get("debug_port", 9222)},
        }],
        step_start_time=session.get("launch_started_iso", ""),
        step_end_time=session.get("launch_ended_iso", ""),
        step_duration_ms=session.get("launch_duration_ms", 0),
    )


def stop_local_debug_cdp_process(process: Any) -> None:
    """Terminate the launched local-debug browser and CONFIRM it actually died.

    A browser that survives here squats the CDP port: the next test's launch
    finds it and kills it, logging a "port already in use" warning. Escalate to
    SIGKILL and make any unclean shutdown loud so "we didn't close properly"
    is visible in the logs instead of a mystery on the next run.
    """
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=3)
            print(
                "[local_debug_browser_helpers] ⚠️ Browser ignored SIGTERM and needed "
                "SIGKILL — this test's browser did not close cleanly."
            )
        except Exception:
            print(
                "[local_debug_browser_helpers] ❌ Browser did NOT shut down — it will "
                "squat the CDP port and get killed by the next test's launch."
            )


def append_local_debug_step_result(
    *,
    step_results: List[Dict[str, Any]],
    message: str,
    success: bool,
    from_node: str,
    to_node: Optional[str] = None,
    actions: Optional[List[Dict[str, Any]]] = None,
    verifications: Optional[List[Dict[str, Any]]] = None,
    screenshot_path: str = "",
    step_start_time: str = "",
    step_end_time: str = "",
    step_duration_ms: int = 1,
) -> None:
    """Append a standardized local-debug step result."""
    action_screenshots = [screenshot_path] if screenshot_path else []
    now_iso = datetime.now(timezone.utc).isoformat()
    start_display = format_timestamp_to_hhmmss_ms(step_start_time or now_iso)
    end_display = format_timestamp_to_hhmmss_ms(step_end_time or now_iso)
    step_results.append({
        "step_number": len(step_results) + 1,
        "success": success,
        "message": message,
        "execution_time_ms": int(step_duration_ms or 0),
        "start_time": start_display,
        "end_time": end_display,
        "from_node": from_node,
        "to_node": to_node or from_node,
        "actions": actions or [],
        "verifications": verifications or [],
        "verification_results": [],
        "screenshot_path": screenshot_path or None,
        "step_end_screenshot_path": screenshot_path or None,
        "action_screenshots": action_screenshots,
    })


async def capture_local_debug_screenshot(
    *,
    page: Any,
    screenshots_dir: str,
    screenshot_paths: List[str],
    name: str,
    full_page: bool = True,
) -> str:
    """Capture a numbered Playwright screenshot and track it in screenshot_paths."""
    idx = len(screenshot_paths) + 1
    path = os.path.join(screenshots_dir, f"{idx:02d}_{name}.png")
    await page.screenshot(path=path, full_page=full_page)
    screenshot_paths.append(path)
    # DOM snapshot of the same moment; deduped per page inside dom_capture
    await capture_page_dom(page=page, name=name, output_dir=screenshots_dir)
    return path


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in ("1", "true", "t", "yes", "y", "on"):
        return True
    if lowered in ("0", "false", "f", "no", "n", "off"):
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def normalize_local_debug_flag(argv: List[str]) -> List[str]:
    normalized = []
    i = 0
    while i < len(argv):
        token = argv[i]
        # Normalize --local_debug to --local-debug
        if token == "--local_debug":
            token = "--local-debug"
        normalized.append(token)
        if token in ("--local-debug", "--local_debug"):
            next_token = argv[i + 1] if i + 1 < len(argv) else None
            if next_token is None or next_token.startswith("-"):
                normalized.append("true")
        i += 1
    return normalized


def cli_local_debug_enabled(argv: List[str]) -> bool:
    for i, token in enumerate(argv):
        if token not in ("--local-debug", "--local_debug"):
            continue
        if i + 1 >= len(argv) or argv[i + 1].startswith("-"):
            return True
        try:
            return bool(str_to_bool(argv[i + 1]))
        except ValueError:
            return False
    return False


def run_local_debug_with_context(
    context: Any,
    run_local: Callable[[], Dict[str, Any]],
    summary_builder: Callable[[Any, Dict[str, Any]], str],
    metadata_builder: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    exception_metadata_builder: Optional[Callable[[Exception], Dict[str, Any]]] = None,
    default_failure_message: str = "",
) -> bool:
    """
    Execute local-debug flow and apply result fields consistently to context.

    This keeps scripts on the decorated execution path while sharing repeated
    local-debug plumbing (success/error/metadata/summary assignment).
    """
    try:
        result = run_local()
    except Exception as exc:
        context.overall_success = False
        context.error_message = str(exc)
        if exception_metadata_builder:
            context.metadata = exception_metadata_builder(exc)
        else:
            context.metadata = {"mode": "local_debug", "error": str(exc)}
        context.execution_summary = summary_builder(context, {})
        return False

    success = bool(result.get("success"))
    context.overall_success = success
    context.error_message = result.get("error") or (default_failure_message if not success else "")

    if "step_results" in result:
        context.step_results = result.get("step_results", []) or []
    if "screenshot_paths" in result:
        context.screenshot_paths = result.get("screenshot_paths", []) or []

    test_video_path = result.get("test_video_path")
    if isinstance(test_video_path, str):
        context.test_video_url = test_video_path

    if metadata_builder:
        context.metadata = metadata_builder(result)
    else:
        context.metadata = {"mode": "local_debug"}

    context.execution_summary = summary_builder(context, result)
    return success


def _write_local_debug_report_pack(
    script_name: str,
    output_dir: str,
    summary_text: str,
    result_payload: Dict[str, Any],
    success: bool,
    error: str,
) -> Dict[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "result.json")
    log_path = os.path.join(output_dir, "execution.log")
    report_path = os.path.join(output_dir, "report.html")

    payload = dict(result_payload or {})
    payload["success"] = success
    payload["error"] = error
    payload["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(summary_text + "\n")
        f.write(f"SCRIPT_SUCCESS:{str(success).lower()}\n")

    from .report_generation_utils import generate_validation_report
    from datetime import datetime, timedelta

    step_results = payload.get("step_results", []) or []
    screenshot_paths = payload.get("screenshot_paths", []) or []

    now = datetime.now()
    end_ts = now.strftime("%Y%m%d%H%M%S")
    execution_time_ms = int(payload.get("execution_time", 0) or 0)
    start_ts = (now - timedelta(milliseconds=execution_time_ms)).strftime("%Y%m%d%H%M%S")

    local_report_data = {
        "script_name": script_name,
        "device_info": payload.get("device_info", {}) or {"device_name": "local_debug", "device_model": "local_debug"},
        "host_info": payload.get("host_info", {}) or {"host_name": "local_debug"},
        "execution_time": execution_time_ms,
        "success": success,
        "step_results": step_results,
        "screenshots": {
            "initial": screenshot_paths[0] if len(screenshot_paths) > 0 else None,
            "steps": screenshot_paths[1:-1] if len(screenshot_paths) > 2 else [],
            "final": screenshot_paths[-1] if len(screenshot_paths) > 1 else None,
        },
        "error_msg": error or "",
        "timestamp": end_ts,
        "start_time": start_ts,
        "end_time": end_ts,
        "execution_summary": summary_text,
        "test_video_url": payload.get("test_video_path", "") or "",
        "logs_url": log_path,
        # Local paths here; R2 runs get signed URLs from generate_and_upload_script_report
        "dom_captures": [
            {"name": c["name"], "title": c.get("title", ""), "url": c["path"], "page_url": c["url"]}
            for c in get_dom_captures()
        ],
    }
    html_content = generate_validation_report(local_report_data)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return {
        "output_dir": output_dir,
        "report_url": report_path,
        "logs_url": log_path,
        "result_json": json_path,
    }


def run_local_debug_cli(
    argv: List[str],
    script_name: str,
    project_root: str,
    arg_specs: List[Dict[str, Any]],
    run_local: Callable[[argparse.Namespace, str], Dict[str, Any]],
    summary_builder: Callable[[argparse.Namespace, Dict[str, Any], bool, str], str],
    default_failure_message: str = "",
) -> None:
    """
    Execute local-debug in CLI mode without entering decorated executor setup.

    This is the shared path used by web scripts to bypass device setup while still
    producing local report/log artifacts and standardized output keys.
    """
    parser = argparse.ArgumentParser(description=f"{script_name} local-debug mode")
    for spec in arg_specs:
        parser.add_argument(spec["name"], **spec.get("kwargs", {}))
    parser.add_argument("--local-debug", dest="local_debug", default=True)
    args, _ = parser.parse_known_args(argv[1:])

    output_dir = os.path.join(
        project_root,
        "tmp",
        "local_debug",
        script_name,
        f"adhoc_{int(time.time())}",
    )
    os.makedirs(output_dir, exist_ok=True)

    try:
        result = run_local(args, output_dir) or {}
        success = bool(result.get("success"))
        error = result.get("error") or (default_failure_message if not success else "")
    except Exception as exc:
        result = {"error": str(exc), "mode": "local_debug"}
        success = False
        error = str(exc)

    summary_text = summary_builder(args, result, success, error)
    pack = _write_local_debug_report_pack(
        script_name=script_name,
        output_dir=output_dir,
        summary_text=summary_text,
        result_payload=result,
        success=success,
        error=error,
    )

    print(summary_text)
    print(f"report_url: {pack['report_url']}")
    print(f"logs_url: {pack['logs_url']}")
    print(f"SCRIPT_SUCCESS:{str(success).lower()}")
    sys.exit(0)
