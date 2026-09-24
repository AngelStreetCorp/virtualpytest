#!/usr/bin/env python3
"""
Dailymotion Video Check Script for VirtualPyTest

Mirrors youtube_video_check.py:
1. Launches browser and navigates to dailymotion.com
2. Dismisses the cookie consent modal if present
3. Navigates to a specific Dailymotion video URL
4. Forces playback and waits for any pre-roll ad
5. Monitors video playback progression

Usage:
    python test_scripts/web/dailymotion_video_check.py --local-debug
    python test_scripts/web/dailymotion_video_check.py --local-debug --url "https://www.dailymotion.com/video/xa2wwo4"
    python test_scripts/web/dailymotion_video_check.py --local-debug --monitor_duration 20 --headless false
"""

import sys
import os
import time
import asyncio
import shutil
from typing import Dict, Any, Optional

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
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
    DAILYMOTION_JS_CHECK_CONSENT_MODAL as _JS_CHECK_CONSENT_MODAL,
    DAILYMOTION_JS_DISMISS_CONSENT_MODAL as _JS_DISMISS_CONSENT_MODAL,
    DAILYMOTION_JS_DISMISS_PLAYER_BANNER as _JS_DISMISS_PLAYER_BANNER,
    DAILYMOTION_JS_CLICK_PLAYER_OVERLAY as _JS_CLICK_PLAYER_OVERLAY,
    DAILYMOTION_JS_VIDEO_STATUS as _JS_VIDEO_STATUS,
    DAILYMOTION_JS_FORCE_PLAY as _JS_FORCE_PLAY,
    DAILYMOTION_JS_ENTER_FULLSCREEN as _JS_ENTER_FULLSCREEN,
    DAILYMOTION_JS_INSTALL_FIRST_FRAME_PROBE as _JS_INSTALL_FIRST_FRAME_PROBE,
    DAILYMOTION_JS_GET_FIRST_FRAME as _JS_GET_FIRST_FRAME,
)
from shared.src.lib.utils.web_video_playback import calc_playback_progress

import re

sys.argv = normalize_local_debug_flag(sys.argv)

# NOTE: /fr locale triggers a Chrome GPU crash via the CDP launcher flags.
# The bare origin loads cleanly and serves the same home content.
_HOME_URL = 'https://www.dailymotion.com'
_DEFAULT_VIDEO_URL = 'https://www.dailymotion.com/video/xa2wwo4'


def _extract_video_id(url: str) -> Optional[str]:
    """Extract the Dailymotion video id (e.g. 'xa2wwo4') from a URL."""
    if not url:
        return None
    m = re.search(r'/video/([^/?#]+)', url)
    return m.group(1) if m else None


def _resolve_video_url(url: Optional[str]) -> str:
    """Return a usable Dailymotion video URL.

    Falls back to _DEFAULT_VIDEO_URL when the input is missing, doesn't match a
    Dailymotion /video/<id> shape, or is an unfilled placeholder (e.g. a literal
    '{_DEFAULT_VIDEO_URL}' forwarded by an upstream caller). Keeps the device
    run resilient against malformed --url values that would otherwise fail with
    'Could not extract a video id from --url: ...' and leave the report's
    Execution Summary empty.
    """
    if url and _extract_video_id(url):
        return url
    return _DEFAULT_VIDEO_URL


def _embed_url_for(video_id: str) -> str:
    # The embed player at geo.dailymotion.com reliably exposes a <video> element
    # and plays content under the CDP launcher flags, unlike the /video/<id> SPA route
    # which fails to hydrate its React bundle and serves a bare-HTML fallback.
    return f'https://geo.dailymotion.com/player.html?video={video_id}&mute=1&autoplay=1'

# Script arguments
_script_args = [
    f'--url:str:{_DEFAULT_VIDEO_URL}',
    '--preroll_wait:int:15',
    '--monitor_duration:int:30',
    '--headless:bool:false',
]
_script_description = "Open Dailymotion, launch a video, and verify playback progression."
_arg_descriptions = {
    'url': 'Dailymotion video URL',
    'preroll_wait': 'Seconds to wait for pre-roll ad',
    'monitor_duration': 'Playback monitoring seconds',
    'headless': 'Run browser in headless mode',
}


def capture_local_execution_summary(
    context,
    url: str,
    cookie_result: Optional[Dict[str, Any]] = None,
    video_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Capture execution summary text for local-debug mode."""
    lines = []
    lines.append("🎯 [DAILYMOTION_VIDEO_CHECK] LOCAL DEBUG SUMMARY")
    lines.append(f"🖥️  Mode: local-debug (host Playwright only)")
    lines.append(f"🔗 URL: {url}")
    lines.append("")

    lines.append("🍪 COOKIE VALIDATION")
    if cookie_result:
        lines.append(f"   Consent modal initially visible: {'YES' if cookie_result.get('modal_found_initially') else 'NO'}")
        lines.append(f"   Dismissed: {'YES' if cookie_result.get('dismissed') else 'NO'}")
        lines.append(f"   Modal still visible after dismiss: {'YES' if cookie_result.get('modal_still_visible') else 'NO'}")
    else:
        lines.append("   No cookie data collected")
    lines.append("")

    lines.append("🎬 VIDEO PLAYBACK STATUS")
    if video_result:
        lines.append(f"   Playback confirmed: {'YES' if video_result.get('playing') else 'NO'}")
        lines.append(f"   Time progression: {video_result.get('progress_seconds', 0):.1f}s")
        lines.append(f"   Samples: {len(video_result.get('samples', []))}")
    else:
        lines.append("   No video status data collected")
    lines.append("")

    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    return "\n".join(lines)


def _summary(context, url: str, data: Optional[Dict[str, Any]] = None) -> str:
    """Build the device-controller execution summary.

    Called at every return path so the report always has an Execution Summary
    instead of the '📊 Execution summary not available' fallback. Pattern
    mirrors `facebook_check.py._summary` / `device_get_info.py`.
    """
    data = data or {}
    video_id = data.get('video_id') or _extract_video_id(url) or '-'
    page_load = data.get('page_load_time_ms')
    video_load = data.get('video_load_time_ms')
    first_frame_method = data.get('first_frame_method')
    progress = data.get('progress_seconds', 0.0)
    playback_confirmed = bool(data.get('playback_confirmed'))

    lines = [
        "DAILYMOTION_VIDEO_CHECK SUMMARY",
        f"URL: {url}",
        f"Video ID: {video_id}",
        f"Video Playing: {'YES' if playback_confirmed else 'NO'}",
        f"Progress Seconds: {float(progress):.2f}",
        f"Page Load Time: {f'{page_load}ms' if page_load is not None else '-'}",
        f"Video Load Time: {f'{video_load}ms ({first_frame_method})' if video_load is not None else '-'}",
        f"Result: {'SUCCESS' if context.overall_success else 'FAILED'}",
    ]
    if context.error_message:
        lines.append(f"Error: {context.error_message}")
    return "\n".join(lines)


async def _run_local_playwright_flow(
    video_url: str,
    preroll_wait: int,
    monitor_duration: int,
    headless: bool = False,
    output_dir: str = "",
) -> Dict[str, Any]:
    """Run Dailymotion checks directly with Playwright on host."""
    cookie_result = None
    video_result = None
    step_results = []
    screenshot_paths = []
    trace_path = ""
    test_video_path = ""
    project_tmp = os.path.join(project_root, 'tmp', 'local_debug', 'dailymotion_video_check')
    output_dir = output_dir or os.path.join(project_tmp, f"adhoc_{int(time.time())}")
    os.makedirs(output_dir, exist_ok=True)
    screenshots_dir = os.path.join(output_dir, 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)

    def add_step(message: str, success: bool, actions=None, verifications=None, screenshot_path: str = ""):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node='dailymotion_video_check',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
        )

    async def capture_pw_screenshot(page_obj, name: str) -> str:
        print(f"[PW] capture_screenshot('{name}')")
        return await capture_local_debug_screenshot(
            page=page_obj,
            screenshots_dir=screenshots_dir,
            screenshot_paths=screenshot_paths,
            name=name,
        )

    async with local_debug_playwright_session(
        profile_name="dailymotion_check",
        headless=headless,
        debug_port=9222,
        record_video_dir=output_dir,
    ) as session:
        launched_process = session["launched_process"]
        browser = session["browser"]
        context = session["context"]
        page = session["page"]
        append_local_debug_browser_launch_step(
            step_results=step_results,
            from_node='dailymotion_video_check',
            session=session,
        )
        trace_path = os.path.join(output_dir, 'trace.zip')
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page.set_default_timeout(30000)

        # Step 1: Open Dailymotion and handle cookie consent
        print(f"[PW] page.goto('{_HOME_URL}', wait_until='domcontentloaded')")
        await page.goto(_HOME_URL, wait_until='domcontentloaded')
        await page.wait_for_timeout(3000)
        home_shot = await capture_pw_screenshot(page, 'dailymotion_home')
        step_results[0]['screenshot_path'] = home_shot
        step_results[0]['step_end_screenshot_path'] = home_shot
        step_results[0]['action_screenshots'] = [home_shot]

        print("[PW] page.evaluate(_JS_CHECK_CONSENT_MODAL)")
        modal_selector = await page.evaluate(_JS_CHECK_CONSENT_MODAL)
        modal_found_initially = bool(modal_selector)
        print(f"[PW] consent modal detected={modal_found_initially} selector={modal_selector}")

        dismissed = False
        dismiss_method = None
        modal_still_visible = False
        if modal_found_initially:
            # Dailymotion uses Sourcepoint CMP, which renders its buttons inside a
            # cross-origin iframe (sp_message_iframe_*). Handle that first via
            # Playwright frame locators, since pure-JS querySelectors can't cross
            # origins. Fall back to the in-page JS dismiss for other CMPs.
            sp_frame = None
            for frame in page.frames:
                if frame.name.startswith('sp_message_iframe_') or 'consent.dailymotion.com' in (frame.url or ''):
                    sp_frame = frame
                    break
            if sp_frame is not None:
                print(f"[PW] detected Sourcepoint CMP iframe name={sp_frame.name}")
                for label in ('Accept All', 'Accept all', 'Accept', 'J\u2019accepte', 'Tout accepter', 'Accepter'):
                    try:
                        btn = sp_frame.get_by_role('button', name=label, exact=False)
                        if await btn.count() > 0:
                            await btn.first.click(timeout=3000)
                            dismissed = True
                            dismiss_method = f'sourcepoint_iframe:{label}'
                            print(f"[PW] sourcepoint accept clicked via label='{label}'")
                            break
                    except Exception as click_exc:
                        print(f"[PW] sourcepoint click '{label}' failed: {click_exc}")
                await page.wait_for_timeout(2000)
                modal_still_visible = bool(await page.evaluate(_JS_CHECK_CONSENT_MODAL))
            if modal_still_visible or not dismissed:
                # Try the in-page JS dismissal (Didomi / inline CMP fallback)
                for attempt in range(3):
                    print(f"[PW] page.evaluate(_JS_DISMISS_CONSENT_MODAL) attempt={attempt + 1}")
                    dismiss_res = await page.evaluate(_JS_DISMISS_CONSENT_MODAL) or {}
                    if dismiss_res.get('clicked'):
                        dismissed = True
                        dismiss_method = dismiss_method or dismiss_res.get('method')
                    await page.wait_for_timeout(2000)
                    modal_still_visible = bool(await page.evaluate(_JS_CHECK_CONSENT_MODAL))
                    if not modal_still_visible:
                        break
            consent_shot = await capture_pw_screenshot(page, 'after_consent_dismiss')
        else:
            consent_shot = home_shot

        cookie_result = {
            'modal_found_initially': modal_found_initially,
            'modal_selector': modal_selector,
            'dismissed': dismissed,
            'dismiss_method': dismiss_method,
            'modal_still_visible': modal_still_visible,
        }
        consent_ok = not modal_still_visible
        add_step(
            "Open Dailymotion and validate consent/cookies",
            consent_ok,
            actions=[
                {'command': 'page.goto', 'params': {'url': _HOME_URL, 'wait_until': 'domcontentloaded'}, 'label': 'Open Dailymotion'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_CHECK_CONSENT_MODAL'}, 'label': 'Check consent modal'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_DISMISS_CONSENT_MODAL'}, 'label': 'Dismiss consent modal'},
            ],
            verifications=[{
                'success': consent_ok,
                'label': 'Consent modal closed',
                'details': cookie_result,
            }],
            screenshot_path=consent_shot,
        )

        if not consent_ok:
            try:
                await context.tracing.stop(path=trace_path)
            except Exception:
                pass
            await context.close()
            if browser is not None:
                await browser.close()
            stop_local_debug_cdp_process(launched_process)
            return {
                'success': False,
                'error': f'Cookie consent modal still visible: {modal_selector}',
                'cookie_result': cookie_result,
                'video_result': video_result,
                'step_results': step_results,
                'screenshot_paths': screenshot_paths,
                'trace_path': trace_path if os.path.exists(trace_path) else "",
                'test_video_path': test_video_path,
            }

        # Step 2: Navigate to the Dailymotion embed player. The main /video/<id>
        # SPA route fails to hydrate under the CDP launcher flags and serves a
        # bare-HTML fallback with no <video> element. The embed URL
        # (geo.dailymotion.com/player.html?video=<id>) bypasses that and reliably
        # exposes a <video> element we can monitor.
        video_id = _extract_video_id(video_url)
        if not video_id:
            raise RuntimeError(f"Could not extract a video id from --url: {video_url}")
        embed_url = _embed_url_for(video_id)
        print(f"[PW] page.goto('{embed_url}', wait_until='domcontentloaded')")
        page_load_start = time.time()
        await page.goto(embed_url, wait_until='domcontentloaded')
        page_load_time_ms = int((time.time() - page_load_start) * 1000)
        # Install the browser-side first-frame probe ASAP on the freshly-navigated embed
        # page. It measures buffering from the page's own timeOrigin to the first painted
        # frame (requestVideoFrameCallback), so the metric reflects real startup buffering
        # rather than the banner-dismiss/pre-roll waits. video_play_start stays as a coarse
        # wall-clock fallback.
        print("[PW] page.evaluate(_JS_INSTALL_FIRST_FRAME_PROBE)")
        await page.evaluate(_JS_INSTALL_FIRST_FRAME_PROBE)
        video_play_start = time.time()
        await page.wait_for_timeout(3000)

        # Dismiss the player's tracker-consent banner ("Nous utilisons les traceurs...")
        print("[PW] page.evaluate(_JS_DISMISS_PLAYER_BANNER)")
        banner_res = await page.evaluate(_JS_DISMISS_PLAYER_BANNER)
        print(f"[PW] player_banner_dismiss={banner_res}")
        await page.wait_for_timeout(1000)

        # Click the .vod_click overlay to start playback, then force play via JS
        print("[PW] page.evaluate(_JS_CLICK_PLAYER_OVERLAY)")
        overlay_res = await page.evaluate(_JS_CLICK_PLAYER_OVERLAY)
        print(f"[PW] overlay_click={overlay_res}")
        print("[PW] page.evaluate(_JS_FORCE_PLAY)")
        await page.evaluate(_JS_FORCE_PLAY)
        print("[PW] page.evaluate(_JS_ENTER_FULLSCREEN)")
        fs_result = await page.evaluate(_JS_ENTER_FULLSCREEN)
        print(f"[PW] fullscreen_result={fs_result}")
        video_opened_shot = await capture_pw_screenshot(page, 'video_opened')
        add_step(
            "Open target Dailymotion video (embed player)",
            True,
            actions=[
                {'command': 'page.goto', 'params': {'url': embed_url, 'wait_until': 'domcontentloaded'}, 'label': 'Open embed player'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_DISMISS_PLAYER_BANNER'}, 'label': 'Dismiss tracker banner'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_CLICK_PLAYER_OVERLAY'}, 'label': 'Click play overlay'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_FORCE_PLAY'}, 'label': 'Force play'},
            ],
            screenshot_path=video_opened_shot,
        )

        # Step 3: Pre-roll wait (Dailymotion ads share the same <video> element,
        # so playback monitoring will still see progression during/after the ad).
        if preroll_wait > 0:
            print(f"[PW] page.wait_for_timeout({preroll_wait * 1000})  # pre-roll wait")
            await page.wait_for_timeout(preroll_wait * 1000)
            await page.evaluate(_JS_FORCE_PLAY)

        # Step 4: Playback monitoring
        samples = []
        poll_interval = 5
        elapsed = 0
        playing = False
        monitor_error = None
        video_load_time_ms = None

        while elapsed < monitor_duration:
            try:
                print("[PW] page.evaluate(_JS_VIDEO_STATUS)")
                sample = await page.evaluate(_JS_VIDEO_STATUS)
                if (sample or {}).get('found'):
                    sample['elapsed'] = elapsed
                    samples.append(sample)
                    print(f"[PW] sample elapsed={elapsed}s currentTime={sample.get('currentTime', 0):.2f} paused={sample.get('paused', True)}")
                    if not sample.get('paused', True) and sample.get('currentTime', 0) > 0:
                        playing = True
                        if video_load_time_ms is None:
                            video_load_time_ms = int((time.time() - video_play_start) * 1000)
                    elif sample.get('paused', True):
                        print("[PW] page.evaluate(_JS_FORCE_PLAY)")
                        await page.evaluate(_JS_FORCE_PLAY)
                else:
                    print(f"[PW] video element not found at elapsed={elapsed}s")
                await page.wait_for_timeout(poll_interval * 1000)
                elapsed += poll_interval
            except Exception as monitor_exc:
                monitor_error = str(monitor_exc)
                print(f"[PW] monitor loop interrupted: {monitor_error}")
                break

        progress_seconds, progressing = calc_playback_progress(samples)
        playback_confirmed = bool(playing or progressing or progress_seconds > 1.0)

        # Prefer the browser-side first-frame measurement over the wall-clock fallback.
        first_frame_method = None
        try:
            ff = await page.evaluate(_JS_GET_FIRST_FRAME)
            if ff and ff.get('available') and ff.get('firstFrameMs') is not None:
                video_load_time_ms = int(ff['firstFrameMs'])
                first_frame_method = ff.get('method')
                print(f"[PW] first_frame video_load_time_ms={video_load_time_ms} method={first_frame_method}")
        except Exception as ff_exc:
            print(f"[PW] first-frame probe read failed: {ff_exc}")

        video_result = {
            'success': playback_confirmed,
            'playing': playback_confirmed,
            'samples': samples,
            'progress_seconds': progress_seconds,
            'video_load_time_ms': video_load_time_ms,
            'first_frame_method': first_frame_method,
            'error': None if playback_confirmed else (monitor_error or 'Video did not play during monitoring window'),
        }
        video_end_shot = ""
        try:
            video_end_shot = await capture_pw_screenshot(page, 'video_monitor_end')
        except Exception as screenshot_exc:
            screenshot_error = str(screenshot_exc)
            print(f"[PW] final screenshot failed: {screenshot_error}")
            if not monitor_error:
                monitor_error = screenshot_error
        add_step(
            "Monitor playback progression",
            playback_confirmed,
            actions=[{'command': 'page.evaluate', 'params': {'script': '_JS_VIDEO_STATUS'}, 'label': 'Poll video status'}],
            verifications=[{
                'success': playback_confirmed,
                'label': 'Playback progressed',
                'details': {'progress_seconds': progress_seconds, 'sample_count': len(samples), 'monitor_error': monitor_error},
            }],
            screenshot_path=video_end_shot,
        )

        try:
            await context.tracing.stop(path=trace_path)
        except Exception as trace_exc:
            print(f"[PW] tracing stop failed: {trace_exc}")
        try:
            await context.close()
        except Exception as ctx_close_exc:
            print(f"[PW] context close failed: {ctx_close_exc}")
        try:
            if page.video:
                raw_video_path = await page.video.path()
                if raw_video_path and os.path.exists(raw_video_path):
                    final_video_path = os.path.join(output_dir, 'test_execution.webm')
                    shutil.move(raw_video_path, final_video_path)
                    test_video_path = final_video_path
        except Exception as video_exc:
            print(f"[PW] video artifact collection failed: {video_exc}")
        if browser is not None:
            try:
                await browser.close()
            except Exception as browser_close_exc:
                print(f"[PW] browser close failed: {browser_close_exc}")
        stop_local_debug_cdp_process(launched_process)

        return {
            'success': playback_confirmed,
            'error': None if playback_confirmed else (monitor_error or 'Video playback not confirmed during monitoring window'),
            'cookie_result': cookie_result,
            'video_result': video_result,
            'page_load_time_ms': page_load_time_ms,
            'video_load_time_ms': video_load_time_ms,
            'first_frame_method': first_frame_method,
            'step_results': step_results,
            'screenshot_paths': screenshot_paths,
            'trace_path': trace_path if os.path.exists(trace_path) else "",
            'test_video_path': test_video_path,
        }


@script("dailymotion_video_check", "Launch browser, open Dailymotion, play a video, check status")
def main():
    """Main function: navigate to Dailymotion, launch a video, monitor playback."""
    args = get_args()
    context = get_context()

    # Normalize --url up-front: a placeholder ('{_DEFAULT_VIDEO_URL}') or any
    # other non-Dailymotion value falls back to _DEFAULT_VIDEO_URL so a single
    # bad launch no longer fails with 'Could not extract a video id from --url'.
    video_url = _resolve_video_url(args.url)
    preroll_wait = args.preroll_wait
    monitor_duration = args.monitor_duration

    if getattr(args, 'local_debug', False):
        print(f"🧪 [dailymotion_video_check] Running local Playwright-only mode")
        local_output_dir = (context.custom_data or {}).get('local_output_dir', '')
        return run_local_debug_with_context(
            context=context,
            run_local=lambda: asyncio.run(_run_local_playwright_flow(
                video_url,
                preroll_wait,
                monitor_duration,
                bool(getattr(args, 'headless', False)),
                local_output_dir,
            )),
            summary_builder=lambda ctx, result: capture_local_execution_summary(
                ctx,
                video_url,
                result.get('cookie_result'),
                result.get('video_result'),
            ),
            metadata_builder=lambda result: {
                'mode': 'local_debug',
                'url': video_url,
                'cookie_result': result.get('cookie_result'),
                'video_result': result.get('video_result'),
                'page_load_time_ms': result.get('page_load_time_ms'),
                'video_load_time_ms': result.get('video_load_time_ms'),
                'first_frame_method': result.get('first_frame_method'),
                'headless': bool(getattr(args, 'headless', False)),
                'trace_path': result.get('trace_path', ''),
                'test_video_path': result.get('test_video_path', ''),
                'screenshot_count': len(result.get('screenshot_paths', [])),
            },
            exception_metadata_builder=lambda exc: {
                'mode': 'local_debug',
                'url': video_url,
                'headless': bool(getattr(args, 'headless', False)),
                'error': str(exc),
            },
            default_failure_message='Video playback not confirmed during monitoring window',
        )

    # Device-controller path: minimal implementation that delegates JS execution via the web controller.
    device = get_device()
    print(f"🎯 [dailymotion_video_check] URL: {video_url}")
    print(f"📱 [dailymotion_video_check] Device: {device.device_name} ({device.device_model})")

    step_results = []

    # Match the device execution path used by youtube_video_check: capture a
    # device screenshot and attach it to each completed report step.
    from shared.src.lib.utils.device_utils import capture_screenshot_for_script

    def capture_step_screenshot(screenshot_id: str) -> str:
        captured_id = capture_screenshot_for_script(device, context, screenshot_id)
        if captured_id and context.screenshot_paths:
            return context.screenshot_paths[-1]
        return ""

    def add_step(message: str, success: bool, actions=None, verifications=None, screenshot_path: str = ""):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node='dailymotion_video_check',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
        )

    web_controller = device._get_controller('web')
    if not web_controller:
        add_step(
            "Launch browser session",
            False,
            actions=[{'command': 'web_controller.open_browser', 'params': {}}],
            verifications=[{
                'success': False,
                'label': 'Browser available',
                'details': {'error': 'No web controller available on this device'},
            }],
        )
        context.error_message = "No web controller available on this device"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = _summary(context, video_url, {})
        return False

    browser_session = ensure_browser_session(
        web_controller,
        add_step=add_step,
        open_command='web_controller.open_browser',
    )
    if not browser_session.get('success'):
        context.error_message = f"Failed to open browser: {browser_session.get('error')}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = _summary(context, video_url, {})
        return False

    # ensure_browser_session creates the first step; attach the current browser
    # state to it so the browser launch row also has its own screenshot.
    browser_launch_shot = capture_step_screenshot("dailymotion_browser_ready")
    if step_results and browser_launch_shot:
        step_results[-1]["screenshot_path"] = browser_launch_shot
        step_results[-1]["step_end_screenshot_path"] = browser_launch_shot
        step_results[-1]["action_screenshots"] = [browser_launch_shot]

    # Navigate to home and dismiss cookies
    nav_home = asyncio.run(web_controller.navigate_to_url(_HOME_URL))
    if not nav_home.get('success'):
        context.error_message = f"Failed to navigate to Dailymotion: {nav_home.get('error', 'Unknown')}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = _summary(context, video_url, {})
        return False

    time.sleep(3)
    modal_check = asyncio.run(web_controller.execute_javascript(_JS_CHECK_CONSENT_MODAL))
    modal_selector = modal_check.get('result') if modal_check.get('success') else None
    if modal_selector:
        asyncio.run(web_controller.execute_javascript(_JS_DISMISS_CONSENT_MODAL))
        time.sleep(2)
    home_step_shot = capture_step_screenshot("dailymotion_home_state")
    add_step("Open Dailymotion and dismiss cookie consent", True, screenshot_path=home_step_shot)

    # Navigate to the Dailymotion embed player (see comment in _run_local_playwright_flow).
    # video_url was already normalized via _resolve_video_url() at the top of main(),
    # so _extract_video_id() is only here as a safety net for unexpected values.
    video_id = _extract_video_id(video_url)
    if not video_id:
        context.error_message = f"Could not extract a video id from --url: {video_url}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = _summary(context, video_url, {})
        return False
    embed_url = _embed_url_for(video_id)
    page_load_start = time.time()
    nav_video = asyncio.run(web_controller.navigate_to_url(embed_url))
    page_load_time_ms = int((time.time() - page_load_start) * 1000)
    # Install the browser-side first-frame probe ASAP on the freshly-navigated embed page
    # so buffering is measured from the page's own timeOrigin to the first painted frame,
    # not from the banner-dismiss/pre-roll waits. video_play_start stays as a coarse fallback.
    if nav_video.get('success'):
        asyncio.run(web_controller.execute_javascript(_JS_INSTALL_FIRST_FRAME_PROBE))
    # video_load anchors here (embed page loaded) and measures time until playback is confirmed.
    video_play_start = time.time()
    if not nav_video.get('success'):
        context.error_message = f"Failed to navigate to embed player: {nav_video.get('error', 'Unknown')}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = _summary(context, video_url, {'page_load_time_ms': page_load_time_ms, 'video_id': video_id})
        return False

    time.sleep(3)
    asyncio.run(web_controller.execute_javascript(_JS_DISMISS_PLAYER_BANNER))
    asyncio.run(web_controller.execute_javascript(_JS_CLICK_PLAYER_OVERLAY))
    asyncio.run(web_controller.execute_javascript(_JS_FORCE_PLAY))
    asyncio.run(web_controller.execute_javascript(_JS_ENTER_FULLSCREEN))
    video_open_step_shot = capture_step_screenshot("dailymotion_video_opened")
    add_step("Open target Dailymotion video (embed player)", True, screenshot_path=video_open_step_shot)

    if preroll_wait > 0:
        time.sleep(preroll_wait)
        asyncio.run(web_controller.execute_javascript(_JS_FORCE_PLAY))

    # Monitor playback
    samples = []
    elapsed = 0
    playing = False
    video_load_time_ms = None
    while elapsed < monitor_duration:
        status = asyncio.run(web_controller.execute_javascript(_JS_VIDEO_STATUS))
        if status.get('success') and (status.get('result') or {}).get('found'):
            sample = status['result']
            sample['elapsed'] = elapsed
            samples.append(sample)
            if not sample.get('paused', True) and sample.get('currentTime', 0) > 0:
                playing = True
                if video_load_time_ms is None:
                    video_load_time_ms = int((time.time() - video_play_start) * 1000)
            elif sample.get('paused', True):
                asyncio.run(web_controller.execute_javascript(_JS_FORCE_PLAY))
        time.sleep(5)
        elapsed += 5

    progress_seconds, progressing = calc_playback_progress(samples)
    playback_confirmed = bool(playing or progressing or progress_seconds > 1.0)

    # Prefer the browser-side first-frame measurement over the wall-clock fallback.
    first_frame_method = None
    try:
        ff_result = asyncio.run(web_controller.execute_javascript(_JS_GET_FIRST_FRAME))
        ff = ff_result.get('result', {}) if ff_result.get('success') else {}
        if ff and ff.get('available') and ff.get('firstFrameMs') is not None:
            video_load_time_ms = int(ff['firstFrameMs'])
            first_frame_method = ff.get('method')
            print(f"🎞️ [dailymotion_video_check] First-frame video_load_time_ms={video_load_time_ms} method={first_frame_method}")
    except Exception as ff_exc:
        print(f"⚠️ [dailymotion_video_check] First-frame probe read failed: {ff_exc}")

    monitor_step_shot = capture_step_screenshot("dailymotion_monitor_end")
    add_step("Monitor playback progression", playback_confirmed, verifications=[{
        'success': playback_confirmed,
        'label': 'Playback progressed',
        'details': {'progress_seconds': progress_seconds, 'sample_count': len(samples)},
    }], screenshot_path=monitor_step_shot)

    context.overall_success = playback_confirmed
    if not playback_confirmed and not context.error_message:
        context.error_message = "Video playback not confirmed during monitoring window"
    context.metadata = {
        'url': video_url,
        'page_load_time_ms': page_load_time_ms,
        'video_load_time_ms': video_load_time_ms,
        'first_frame_method': first_frame_method,
        'video_result': {
            'playing': playback_confirmed,
            'progress_seconds': progress_seconds,
            'sample_count': len(samples),
            'video_load_time_ms': video_load_time_ms,
            'first_frame_method': first_frame_method,
        },
    }
    context.step_results = step_results
    context.execution_summary = _summary(context, video_url, {
        'video_id': video_id,
        'playback_confirmed': playback_confirmed,
        'progress_seconds': progress_seconds,
        'page_load_time_ms': page_load_time_ms,
        'video_load_time_ms': video_load_time_ms,
        'first_frame_method': first_frame_method,
    })
    return playback_confirmed


main._script_args = _script_args


def _run_local_debug_cli():
    run_local_debug_cli(
        argv=sys.argv,
        script_name="dailymotion_video_check",
        project_root=project_root,
        arg_specs=[
            {"name": "--url", "kwargs": {"type": str, "default": _DEFAULT_VIDEO_URL}},
            {"name": "--preroll_wait", "kwargs": {"type": int, "default": 15}},
            {"name": "--monitor_duration", "kwargs": {"type": int, "default": 30}},
            {"name": "--headless", "kwargs": {"type": str_to_bool, "default": False}},
        ],
        run_local=lambda args, output_dir: asyncio.run(_run_local_playwright_flow(
            args.url,
            int(args.preroll_wait),
            int(args.monitor_duration),
            bool(args.headless),
            output_dir,
        )),
        summary_builder=lambda args, result, success, error: capture_local_execution_summary(
            type("LocalContext", (), {"overall_success": success, "error_message": error, "get_execution_time_ms": lambda self: 0})(),
            args.url,
            result.get("cookie_result"),
            result.get("video_result"),
        ),
        default_failure_message='Video playback not confirmed during monitoring window',
    )


main._script_args = _script_args
main._target_rules = {
    "target_type": "host",
    "host_os": "all",
    "device_model": "all",
}


if __name__ == "__main__":
    if cli_local_debug_enabled(sys.argv):
        _run_local_debug_cli()
    main()
