#!/usr/bin/env python3
"""
Facebook video playback check with local-debug support.

Flow:
1. Open Facebook Example videos URL
2. Close cookie dialogs (best effort)
3. Close login popup
4. Wait for player controls/state
5. Click Play, toggle mute/unmute, enter fullscreen
6. Verify video time progression (with bounded retry on no-progress)
"""

import sys
import os
import time
import asyncio
import platform
from datetime import datetime, timezone
from typing import Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.utils.local_debug_browser_helpers import (
    append_local_debug_step_result,
    append_local_debug_browser_launch_step,
    capture_local_debug_screenshot,
    cli_local_debug_enabled,
    ensure_browser_session,
    local_debug_playwright_session,
    normalize_local_debug_flag,
    run_local_debug_with_context,
    run_local_debug_cli,
    stop_local_debug_cdp_process,
    str_to_bool,
)
from shared.src.lib.utils.local_debug_playwright_js import (
    FACEBOOK_JS_CLOSE_COOKIES as _JS_CLOSE_COOKIES,
    FACEBOOK_JS_CLOSE_LOGIN_POPUP as _JS_CLOSE_LOGIN_POPUP,
    FACEBOOK_JS_ENTER_FULLSCREEN as _JS_ENTER_FULLSCREEN,
    FACEBOOK_JS_ENSURE_UNMUTED as _JS_ENSURE_UNMUTED,
    FACEBOOK_JS_PLAY as _JS_PLAY,
    FACEBOOK_JS_PLAYER_STATE as _JS_PLAYER_STATE,
    FACEBOOK_JS_VIDEO_STATUS as _JS_VIDEO_STATUS,
    FACEBOOK_JS_INSTALL_FIRST_FRAME_PROBE as _JS_INSTALL_FIRST_FRAME_PROBE,
    FACEBOOK_JS_GET_FIRST_FRAME as _JS_GET_FIRST_FRAME,
)
from shared.src.lib.utils.report_step_formatter import format_timestamp_to_hhmmss_ms
from shared.src.lib.utils.web_video_playback import calc_playback_progress


sys.argv = normalize_local_debug_flag(sys.argv)

_script_args = [
    "--url:str:https://www.facebook.com/Example.ch/videos/?ref=page_internal&locale=en_EN",
    "--monitor_duration:int:20",
    "--browser_fullscreen:bool:true",
    "--headless:bool:false",
]
_script_description = "Check Facebook Example video playback."
_arg_descriptions = {
    'url': 'Facebook videos page URL',
    'monitor_duration': 'Playback monitoring seconds',
    'browser_fullscreen': 'Press F11 to make browser window fullscreen',
    'headless': 'Run browser in headless mode',
}


def _browser_fullscreen_key() -> str:
    return "Control+Meta+f" if platform.system() == "Darwin" else "F11"


def _summary(context, url: str, data: Dict[str, Any]) -> str:
    lines = [
        "FACEBOOK_CHECK SUMMARY",
        f"URL: {url}",
        f"Cookies Clicked: {data.get('cookie_clicks')}",
        f"Popup Closed: {data.get('popup_closed')}",
        f"Player Ready: {data.get('player_ready')}",
        f"Video Playing: {data.get('playing')}",
        f"Progress Seconds: {data.get('progress_seconds')}",
        f"Result: {'SUCCESS' if context.overall_success else 'FAILED'}",
    ]
    if context.error_message:
        lines.append(f"Error: {context.error_message}")
    return "\n".join(lines)
async def _run_local(
    url: str,
    monitor_duration: int,
    browser_fullscreen: bool = True,
    headless: bool = False,
    output_dir: str = "",
) -> Dict[str, Any]:
    launched_process = None
    step_results = []
    screenshot_paths = []
    started_at = time.time()

    base = os.path.join(project_root, "tmp", "local_debug", "facebook_check")
    output_dir = output_dir or os.path.join(base, f"adhoc_{int(time.time())}")
    os.makedirs(output_dir, exist_ok=True)
    shots_dir = os.path.join(output_dir, "screenshots")
    os.makedirs(shots_dir, exist_ok=True)

    def add_step(
        message: str,
        success: bool,
        actions=None,
        verifications=None,
        screenshot_path: str = "",
        step_start_time: str = "",
        step_end_time: str = "",
        step_duration_ms: int = 0,
    ):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node="facebook_check",
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
            step_start_time=step_start_time,
            step_end_time=step_end_time,
            step_duration_ms=step_duration_ms,
        )

    async def shot(page_obj, name: str) -> str:
        return await capture_local_debug_screenshot(
            page=page_obj,
            screenshots_dir=shots_dir,
            screenshot_paths=screenshot_paths,
            name=name,
        )

    async with local_debug_playwright_session(
        profile_name="facebook_check",
        headless=headless,
        debug_port=9222,
        reuse_existing_page=True,
    ) as session:
        browser_fullscreen_key = _browser_fullscreen_key()
        launched_process = session["launched_process"]
        browser = session["browser"]
        ctx = session["context"]
        page = session["page"]
        append_local_debug_browser_launch_step(
            step_results=step_results,
            from_node="facebook_check",
            session=session,
        )
        page.set_default_timeout(30000)

        open_step_started_at = time.time()
        open_step_started_iso = datetime.now(timezone.utc).isoformat()
        page_load_start = time.time()
        await page.goto(url, wait_until="domcontentloaded")
        page_load_time_ms = int((time.time() - page_load_start) * 1000)
        # Install the browser-side first-frame probe ASAP on the freshly-navigated page.
        # It measures buffering from the page's own timeOrigin to the first painted frame
        # (requestVideoFrameCallback), so the metric reflects real startup buffering rather
        # than our retry/wait loops. video_play_start stays as a coarse wall-clock fallback.
        await page.evaluate(_JS_INSTALL_FIRST_FRAME_PROBE)
        video_play_start = time.time()
        await page.wait_for_timeout(3000)
        cookie_result = await page.evaluate(_JS_CLOSE_COOKIES)
        await page.wait_for_timeout(1000)
        popup_result = await page.evaluate(_JS_CLOSE_LOGIN_POPUP)
        await page.wait_for_timeout(1000)
        open_shot = await shot(page, "after_open")
        open_step_ended_iso = datetime.now(timezone.utc).isoformat()
        open_step_duration_ms = int((time.time() - open_step_started_at) * 1000)
        add_step(
            "Open Facebook videos URL and dismiss popups",
            True,
            actions=[
                {"command": "page.goto", "params": {"url": url}},
                {"command": "page.evaluate", "params": {"script": "_JS_CLOSE_COOKIES"}},
                {"command": "page.evaluate", "params": {"script": "_JS_CLOSE_LOGIN_POPUP"}},
            ],
            verifications=[{
                "success": True,
                "label": "Page loaded",
                "command": "assert_page_loaded",
            }],
            screenshot_path=open_shot,
            step_start_time=open_step_started_iso,
            step_end_time=open_step_ended_iso,
            step_duration_ms=open_step_duration_ms,
        )

        player_ready = False
        last_state = {}
        player_step_started_at = time.time()
        player_step_started_iso = datetime.now(timezone.utc).isoformat()
        for _ in range(30):
            last_state = await page.evaluate(_JS_PLAYER_STATE)
            if last_state.get("hasVideo") and (last_state.get("playVisible") or not last_state.get("paused", True)):
                player_ready = True
                break
            await page.wait_for_timeout(1000)
        player_shot = await shot(page, "player_state")
        player_step_ended_iso = datetime.now(timezone.utc).isoformat()
        player_step_duration_ms = int((time.time() - player_step_started_at) * 1000)
        add_step(
            "Wait for Facebook player readiness",
            player_ready,
            actions=[{"command": "page.evaluate", "params": {"script": "_JS_PLAYER_STATE"}}],
            verifications=[{
                "success": player_ready,
                "label": "Player ready",
                "command": "assert_player_ready",
                "details": {"state": last_state},
            }],
            screenshot_path=player_shot,
            step_start_time=player_step_started_iso,
            step_end_time=player_step_ended_iso,
            step_duration_ms=player_step_duration_ms,
        )

        max_play_attempts = 3
        play_retry_wait_ms = 3000
        monitor_seconds = max(3, monitor_duration)

        controls_step_started_at = time.time()
        controls_step_started_iso = datetime.now(timezone.utc).isoformat()
        first_play_result = await page.evaluate(_JS_PLAY)
        await page.wait_for_timeout(1500)
        mute_result = None
        unmute_result = await page.evaluate(_JS_ENSURE_UNMUTED)
        if browser_fullscreen and not headless:
            await page.keyboard.press(browser_fullscreen_key)
            await page.wait_for_timeout(1500)
        fs_result = await page.evaluate(_JS_ENTER_FULLSCREEN)
        controls_ok = bool((first_play_result or {}).get("success")) and bool((fs_result or {}).get("success"))
        controls_shot = await shot(page, "after_controls")
        controls_step_ended_iso = datetime.now(timezone.utc).isoformat()
        controls_step_duration_ms = int((time.time() - controls_step_started_at) * 1000)
        add_step(
            "Play, unmute and enter fullscreen",
            controls_ok,
            actions=[action for action in [
                {"command": "page.evaluate", "params": {"script": "_JS_PLAY"}},
                {"command": "page.evaluate", "params": {"script": "_JS_ENSURE_UNMUTED"}},
                {"command": "page.keyboard.press", "params": {"key": browser_fullscreen_key}} if browser_fullscreen and not headless else None,
                {"command": "page.evaluate", "params": {"script": "_JS_ENTER_FULLSCREEN"}},
            ] if action],
            verifications=[{
                "success": controls_ok,
                "label": "Playback controls executed",
                "command": "assert_controls",
                "details": {
                    "play_result": first_play_result,
                    "unmute_result": unmute_result,
                    "fullscreen_result": fs_result,
                },
            }],
            screenshot_path=controls_shot,
            step_start_time=controls_step_started_iso,
            step_end_time=controls_step_ended_iso,
            step_duration_ms=controls_step_duration_ms,
        )

        samples = []
        play_attempts = [first_play_result]
        progress = 0.0
        playing = False
        video_load_time_ms = None
        for attempt in range(1, max_play_attempts + 1):
            attempt_started_at = time.time()
            attempt_started_iso = datetime.now(timezone.utc).isoformat()
            if attempt > 1:
                retry_play_result = await page.evaluate(_JS_PLAY)
                play_attempts.append(retry_play_result)
                await page.wait_for_timeout(1500)

            attempt_samples = []
            for _ in range(monitor_seconds):
                st = await page.evaluate(_JS_VIDEO_STATUS)
                attempt_samples.append(st)
                if video_load_time_ms is None and st and st.get("found") \
                        and not st.get("paused", True) and (st.get("currentTime", 0) or 0) > 0:
                    video_load_time_ms = int((time.time() - video_play_start) * 1000)
                await page.wait_for_timeout(1000)

            samples.extend(attempt_samples)
            progress, playing = calc_playback_progress(attempt_samples)
            attempt_ok = bool(playing and progress > 1)
            # Only record an attempt step when it succeeds, or when it's the final
            # (genuinely failed) attempt. Intermediate no-progress retries are just
            # the player warming up after the first Play press didn't take — recording
            # them as FAIL is misleading noise when a later attempt succeeds.
            if attempt_ok or attempt == max_play_attempts:
                attempt_shot = await shot(page, f"monitor_attempt_{attempt}")
                attempt_ended_iso = datetime.now(timezone.utc).isoformat()
                attempt_duration_ms = int((time.time() - attempt_started_at) * 1000)
                add_step(
                    f"Monitor playback attempt {attempt}",
                    attempt_ok,
                    actions=[{"command": "page.evaluate", "params": {"script": "_JS_VIDEO_STATUS"}}],
                    verifications=[{
                        "success": attempt_ok,
                        "label": "Video progressed",
                        "command": "assert_progress",
                        "details": {
                            "progress_seconds": round(progress, 2),
                            "playing": playing,
                        },
                    }],
                    screenshot_path=attempt_shot,
                    step_start_time=attempt_started_iso,
                    step_end_time=attempt_ended_iso,
                    step_duration_ms=attempt_duration_ms,
                )
            if playing and progress > 1:
                break
            if attempt < max_play_attempts:
                await page.wait_for_timeout(play_retry_wait_ms)

        # Prefer the browser-side first-frame measurement over the wall-clock fallback.
        first_frame_method = None
        try:
            ff = await page.evaluate(_JS_GET_FIRST_FRAME)
            if ff and ff.get("available") and ff.get("firstFrameMs") is not None:
                video_load_time_ms = int(ff["firstFrameMs"])
                first_frame_method = ff.get("method")
        except Exception:
            pass

        final_success = bool(playing and progress > 1)
        final_step_started_at = time.time()
        final_step_started_iso = datetime.now(timezone.utc).isoformat()
        final_status = await page.evaluate(_JS_VIDEO_STATUS)
        final_shot = await shot(page, "final_state")
        final_step_ended_iso = datetime.now(timezone.utc).isoformat()
        final_step_duration_ms = int((time.time() - final_step_started_at) * 1000)
        add_step(
            "Validate final playback state",
            final_success,
            actions=[{"command": "page.evaluate", "params": {"script": "_JS_VIDEO_STATUS"}}],
            verifications=[{
                "success": final_success,
                "label": "Playback progressed",
                "command": "assert_final_progress",
                "details": {
                    "progress_seconds": round(progress, 2),
                    "playing": playing,
                    "status": final_status,
                },
            }],
            screenshot_path=final_shot,
            step_start_time=final_step_started_iso,
            step_end_time=final_step_ended_iso,
            step_duration_ms=final_step_duration_ms,
        )

        result = {
            "success": final_success,
            "cookie_clicks": (cookie_result or {}).get("clicked", 0),
            "popup_closed": (popup_result or {}).get("closed", False),
            "player_ready": player_ready,
            "play_result": first_play_result,
            "play_attempts": play_attempts,
            "mute_result": mute_result,
            "unmute_result": unmute_result,
            "fullscreen_result": fs_result,
            "playing": playing,
            "progress_seconds": round(progress, 2),
            "page_load_time_ms": page_load_time_ms,
            "video_load_time_ms": video_load_time_ms,
            "first_frame_method": first_frame_method,
            "samples": samples[-10:],
            "step_results": step_results,
            "screenshot_paths": screenshot_paths,
            "execution_time": int((time.time() - started_at) * 1000),
            "mode": "local_debug",
            "error": "" if final_success else "Facebook playback check failed (no progress)",
        }

        await ctx.close()
        if browser is not None:
            await browser.close()
        stop_local_debug_cdp_process(launched_process)
        return result


@script("facebook_check", "Facebook Example video playback check")
def main():
    args = get_args()
    context = get_context()
    url = args.url
    monitor_duration = int(args.monitor_duration)
    browser_fullscreen = bool(getattr(args, "browser_fullscreen", True))
    browser_fullscreen_key = _browser_fullscreen_key()

    if getattr(args, "local_debug", False):
        local_output_dir = (context.custom_data or {}).get("local_output_dir", "")
        return run_local_debug_with_context(
            context=context,
            run_local=lambda: asyncio.run(
                _run_local(
                    url,
                    monitor_duration,
                    bool(getattr(args, "headless", False)),
                    local_output_dir,
                )
            ),
            summary_builder=lambda ctx, result: _summary(ctx, url, result),
            metadata_builder=lambda result: {
                "mode": "local_debug",
                "target_url": url,
                "cookie_clicks": result.get("cookie_clicks", 0),
                "popup_closed": result.get("popup_closed", False),
                "player_ready": result.get("player_ready", False),
                "playing": result.get("playing", False),
                "progress_seconds": result.get("progress_seconds", 0),
                "page_load_time_ms": result.get("page_load_time_ms"),
                "video_load_time_ms": result.get("video_load_time_ms"),
                "first_frame_method": result.get("first_frame_method"),
                "screenshot_count": len(result.get("screenshot_paths", [])),
                "headless": bool(getattr(args, "headless", False)),
            },
            exception_metadata_builder=lambda exc: {
                "mode": "local_debug",
                "target_url": url,
                "error": str(exc),
            },
            default_failure_message="Facebook local-debug playback check failed",
        )

    device = get_device()
    web_controller = device._get_controller("web")
    step_results = []

    from shared.src.lib.utils.device_utils import capture_screenshot_for_script

    def capture_step_screenshot(screenshot_id: str) -> str:
        captured_id = capture_screenshot_for_script(device, context, screenshot_id)
        if captured_id and context.screenshot_paths:
            return context.screenshot_paths[-1]
        return ""

    def add_step(
        message: str,
        success: bool,
        actions=None,
        verifications=None,
        screenshot_path: str = "",
        step_start_time: str = "",
        step_end_time: str = "",
        step_duration_ms: int = 0,
    ):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node='facebook_check',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
            step_start_time=step_start_time,
            step_end_time=step_end_time,
            step_duration_ms=step_duration_ms,
        )

    if not web_controller:
        context.error_message = "No web controller available on this device"
        context.overall_success = False
        context.execution_summary = _summary(context, url, {})
        context.step_results = step_results
        return False

    browser_session = ensure_browser_session(
        web_controller,
        add_step=add_step,
        open_command="web_controller.open_browser",
    )
    if not browser_session["success"]:
        context.error_message = f"Failed to open browser: {browser_session['error']}"
        context.overall_success = False
        context.step_results = step_results
        context.metadata = {
            "mode": "device_web_controller",
            "target_url": url,
        }
        context.execution_summary = _summary(context, url, {})
        return False

    open_step_started_at = time.time()
    open_step_started_iso = datetime.now(timezone.utc).isoformat()
    page_load_start = time.time()
    nav_result = asyncio.run(web_controller.navigate_to_url(url))
    page_load_time_ms = int((time.time() - page_load_start) * 1000)
    # Install the browser-side first-frame probe ASAP on the freshly-navigated page so
    # buffering is measured from the page's own timeOrigin to the first painted frame,
    # not from our retry/wait loops. video_play_start stays as a coarse wall-clock fallback.
    if nav_result.get("success"):
        asyncio.run(web_controller.execute_javascript(_JS_INSTALL_FIRST_FRAME_PROBE))
    # video_load anchors here (page loaded) and measures time until playback is confirmed.
    video_play_start = time.time()
    if not nav_result.get("success"):
        open_step_ended_iso = datetime.now(timezone.utc).isoformat()
        open_step_duration_ms = int((time.time() - open_step_started_at) * 1000)
        add_step(
            "Open Facebook videos URL and dismiss popups",
            False,
            actions=[{"command": "web_controller.navigate_to_url", "params": {"url": url}}],
            verifications=[{
                "success": False,
                "label": "Page loaded",
                "command": "assert_page_loaded",
                "details": {"error": nav_result.get("error", "Unknown")},
            }],
            step_start_time=open_step_started_iso,
            step_end_time=open_step_ended_iso,
            step_duration_ms=open_step_duration_ms,
        )
        context.error_message = f"Failed to navigate: {nav_result.get('error', 'Unknown')}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = _summary(context, url, {})
        return False

    time.sleep(3)
    cookie_result = asyncio.run(web_controller.execute_javascript(_JS_CLOSE_COOKIES))
    time.sleep(1)
    popup_result = asyncio.run(web_controller.execute_javascript(_JS_CLOSE_LOGIN_POPUP))
    time.sleep(1)
    open_step_screenshot = capture_step_screenshot("facebook_open")
    open_step_ended_iso = datetime.now(timezone.utc).isoformat()
    open_step_duration_ms = int((time.time() - open_step_started_at) * 1000)
    add_step(
        "Open Facebook videos URL and dismiss popups",
        True,
        actions=[
            {"command": "web_controller.navigate_to_url", "params": {"url": url}},
            {"command": "web_controller.execute_javascript", "params": {"script": "_JS_CLOSE_COOKIES"}},
            {"command": "web_controller.execute_javascript", "params": {"script": "_JS_CLOSE_LOGIN_POPUP"}},
        ],
        verifications=[{
            "success": True,
            "label": "Page loaded",
            "command": "assert_page_loaded",
        }],
        screenshot_path=open_step_screenshot,
        step_start_time=open_step_started_iso,
        step_end_time=open_step_ended_iso,
        step_duration_ms=open_step_duration_ms,
    )

    player_ready = False
    last_state = {}
    player_step_started_at = time.time()
    player_step_started_iso = datetime.now(timezone.utc).isoformat()
    for _ in range(30):
        state_result = asyncio.run(web_controller.execute_javascript(_JS_PLAYER_STATE))
        st = state_result.get("result") if state_result.get("success") else {}
        last_state = st or {}
        if last_state.get("hasVideo") and (last_state.get("playVisible") or not last_state.get("paused", True)):
            player_ready = True
            break
        time.sleep(1)
    player_step_screenshot = capture_step_screenshot("facebook_player_ready")
    player_step_ended_iso = datetime.now(timezone.utc).isoformat()
    player_step_duration_ms = int((time.time() - player_step_started_at) * 1000)
    add_step(
        "Wait for Facebook player readiness",
        player_ready,
        actions=[{"command": "web_controller.execute_javascript", "params": {"script": "_JS_PLAYER_STATE"}}],
        verifications=[{
            "success": player_ready,
            "label": "Player ready",
            "command": "assert_player_ready",
            "details": {"state": last_state},
        }],
        screenshot_path=player_step_screenshot,
        step_start_time=player_step_started_iso,
        step_end_time=player_step_ended_iso,
        step_duration_ms=player_step_duration_ms,
    )

    max_play_attempts = 3
    play_retry_wait_seconds = 3
    monitor_seconds = max(3, monitor_duration)

    controls_step_started_at = time.time()
    controls_step_started_iso = datetime.now(timezone.utc).isoformat()
    first_play_result = asyncio.run(web_controller.execute_javascript(_JS_PLAY))
    time.sleep(1.5)
    mute_result = None
    unmute_result = asyncio.run(web_controller.execute_javascript(_JS_ENSURE_UNMUTED))
    if browser_fullscreen:
        browser_fullscreen_result = asyncio.run(web_controller.press_key(browser_fullscreen_key))
        print(
            f"🖥️ [facebook_check] Browser fullscreen ({browser_fullscreen_key}) result: "
            f"{browser_fullscreen_result if browser_fullscreen_result.get('success') else browser_fullscreen_result.get('error')}"
        )
        time.sleep(1.5)
    fs_result = asyncio.run(web_controller.execute_javascript(_JS_ENTER_FULLSCREEN))
    controls_ok = bool((first_play_result.get("result") or {}).get("success")) and bool(
        (fs_result.get("result") or {}).get("success")
    )
    controls_step_screenshot = capture_step_screenshot("facebook_controls")
    controls_step_ended_iso = datetime.now(timezone.utc).isoformat()
    controls_step_duration_ms = int((time.time() - controls_step_started_at) * 1000)
    add_step(
        "Play, unmute and enter fullscreen",
        controls_ok,
        actions=[action for action in [
            {"command": "web_controller.execute_javascript", "params": {"script": "_JS_PLAY"}},
            {"command": "web_controller.execute_javascript", "params": {"script": "_JS_ENSURE_UNMUTED"}},
            {"command": "web_controller.press_key", "params": {"key": browser_fullscreen_key}} if browser_fullscreen else None,
            {"command": "web_controller.execute_javascript", "params": {"script": "_JS_ENTER_FULLSCREEN"}},
        ] if action],
        verifications=[{
            "success": controls_ok,
            "label": "Playback controls executed",
            "command": "assert_controls",
            "details": {
                "play_result": first_play_result.get("result") if first_play_result else None,
                "unmute_result": unmute_result.get("result") if unmute_result else None,
                "fullscreen_result": fs_result.get("result") if fs_result else None,
            },
        }],
        screenshot_path=controls_step_screenshot,
        step_start_time=controls_step_started_iso,
        step_end_time=controls_step_ended_iso,
        step_duration_ms=controls_step_duration_ms,
    )

    samples = []
    play_attempts = [first_play_result.get("result") if first_play_result else None]
    progress = 0.0
    playing = False
    video_load_time_ms = None
    for attempt in range(1, max_play_attempts + 1):
        attempt_step_started_at = time.time()
        attempt_step_started_iso = datetime.now(timezone.utc).isoformat()
        if attempt > 1:
            retry_play_result = asyncio.run(web_controller.execute_javascript(_JS_PLAY))
            play_attempts.append(retry_play_result.get("result") if retry_play_result else None)
            time.sleep(1.5)

        attempt_samples = []
        for _ in range(monitor_seconds):
            st_result = asyncio.run(web_controller.execute_javascript(_JS_VIDEO_STATUS))
            st = st_result.get("result") if st_result.get("success") else {"found": False}
            attempt_samples.append(st)
            if video_load_time_ms is None and st and st.get("found") \
                    and not st.get("paused", True) and (st.get("currentTime", 0) or 0) > 0:
                video_load_time_ms = int((time.time() - video_play_start) * 1000)
            time.sleep(1)

        samples.extend(attempt_samples)
        progress, playing = calc_playback_progress(attempt_samples)
        attempt_ok = bool(playing and progress > 1)
        # Only record an attempt step when it succeeds, or when it's the final
        # (genuinely failed) attempt. Intermediate no-progress retries are just
        # the player warming up after the first Play press didn't take — recording
        # them as FAIL is misleading noise when a later attempt succeeds.
        if attempt_ok or attempt == max_play_attempts:
            attempt_step_screenshot = capture_step_screenshot(f"facebook_monitor_attempt_{attempt}")
            attempt_step_ended_iso = datetime.now(timezone.utc).isoformat()
            attempt_step_duration_ms = int((time.time() - attempt_step_started_at) * 1000)
            add_step(
                f"Monitor playback attempt {attempt}",
                attempt_ok,
                actions=[{"command": "web_controller.execute_javascript", "params": {"script": "_JS_VIDEO_STATUS"}}],
                verifications=[{
                    "success": attempt_ok,
                    "label": "Video progressed",
                    "command": "assert_progress",
                    "details": {
                        "progress_seconds": round(progress, 2),
                        "playing": playing,
                    },
                }],
                screenshot_path=attempt_step_screenshot,
                step_start_time=attempt_step_started_iso,
                step_end_time=attempt_step_ended_iso,
                step_duration_ms=attempt_step_duration_ms,
            )
        if playing and progress > 1:
            break
        if attempt < max_play_attempts:
            time.sleep(play_retry_wait_seconds)

    # Prefer the browser-side first-frame measurement over the wall-clock fallback.
    first_frame_method = None
    try:
        ff_result = asyncio.run(web_controller.execute_javascript(_JS_GET_FIRST_FRAME))
        ff = ff_result.get("result", {}) if ff_result.get("success") else {}
        if ff and ff.get("available") and ff.get("firstFrameMs") is not None:
            video_load_time_ms = int(ff["firstFrameMs"])
            first_frame_method = ff.get("method")
    except Exception:
        pass

    final_step_started_at = time.time()
    final_step_started_iso = datetime.now(timezone.utc).isoformat()
    final_status_result = asyncio.run(web_controller.execute_javascript(_JS_VIDEO_STATUS))
    final_status = final_status_result.get("result") if final_status_result.get("success") else {"found": False}
    final_success = bool(playing and progress > 1)
    final_step_screenshot = capture_step_screenshot("facebook_final_validation")
    final_step_ended_iso = datetime.now(timezone.utc).isoformat()
    final_step_duration_ms = int((time.time() - final_step_started_at) * 1000)
    add_step(
        "Validate final playback state",
        final_success,
        actions=[{"command": "web_controller.execute_javascript", "params": {"script": "_JS_VIDEO_STATUS"}}],
        verifications=[{
            "success": final_success,
            "label": "Playback progressed",
            "command": "assert_final_progress",
            "details": {
                "progress_seconds": round(progress, 2),
                "playing": playing,
                "status": final_status,
            },
        }],
        screenshot_path=final_step_screenshot,
        step_start_time=final_step_started_iso,
        step_end_time=final_step_ended_iso,
        step_duration_ms=final_step_duration_ms,
    )

    data = {
        "cookie_clicks": (cookie_result.get("result") or {}).get("clicked", 0) if cookie_result else 0,
        "popup_closed": (popup_result.get("result") or {}).get("closed", False) if popup_result else False,
        "player_ready": player_ready,
        "play_result": first_play_result.get("result") if first_play_result else None,
        "play_attempts": play_attempts,
        "mute_result": mute_result.get("result") if mute_result else None,
        "unmute_result": unmute_result.get("result") if unmute_result else None,
        "fullscreen_result": fs_result.get("result") if fs_result else None,
        "playing": playing,
        "progress_seconds": round(progress, 2),
        "page_load_time_ms": page_load_time_ms,
        "video_load_time_ms": video_load_time_ms,
        "first_frame_method": first_frame_method,
        "samples": samples[-10:],
        "mode": "device_web_controller",
        "target_url": url,
    }

    context.metadata = data
    context.step_results = step_results
    context.overall_success = final_success
    if not context.overall_success:
        context.error_message = "Facebook playback check failed (no progress)"
    context.execution_summary = _summary(context, url, data)
    return context.overall_success


main._script_args = _script_args
main._target_rules = {
    "target_type": "host",
    "host_os": "all",
    "device_model": "all",
}


def _run_local_debug_cli():
    run_local_debug_cli(
        argv=sys.argv,
        script_name="facebook_check",
        project_root=project_root,
        arg_specs=[
            {"name": "--url", "kwargs": {"type": str, "default": "https://www.facebook.com/Example.ch/videos/?ref=page_internal&locale=en_EN"}},
            {"name": "--monitor_duration", "kwargs": {"type": int, "default": 20}},
            {"name": "--browser_fullscreen", "kwargs": {"type": str_to_bool, "default": True}},
            {"name": "--headless", "kwargs": {"type": str_to_bool, "default": False}},
        ],
        run_local=lambda args, _output_dir: asyncio.run(
            _run_local(
                args.url,
                int(args.monitor_duration),
                bool(args.browser_fullscreen),
                bool(args.headless),
                _output_dir,
            )
        ),
        summary_builder=lambda args, result, success, error: _summary(
            type("LocalContext", (), {"overall_success": success, "error_message": error})(),
            args.url,
            result,
        ),
        default_failure_message="Facebook local-debug playback check failed",
    )

main._target_rules = {
    "target_type": "host",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    if cli_local_debug_enabled(sys.argv):
        _run_local_debug_cli()
    main()
