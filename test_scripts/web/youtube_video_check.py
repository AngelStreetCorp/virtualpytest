#!/usr/bin/env python3
"""
YouTube Video Check Script for VirtualPyTest

This script:
1. Launches browser and navigates to youtube.com
2. Validates cookie injection (checks for consent/cookie modal)
3. Navigates to a specific YouTube video
4. Skips ads if possible, otherwise waits 30s
5. Monitors video playback status for 30s

Usage:
    python test_scripts/web/youtube_video_check.py
    python test_scripts/web/youtube_video_check.py --url "https://www.youtube.com/watch?v=y9n6HkftavM"
    python test_scripts/web/youtube_video_check.py --url "https://www.youtube.com/watch?v=y9n6HkftavM" --device device2
    python test_scripts/web/youtube_video_check.py --local-debug --monitor_duration 20
"""

import sys
import os
import time
import asyncio
import shutil
from datetime import datetime, timezone
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
    YOUTUBE_JS_CHECK_AD as _JS_CHECK_AD,
    YOUTUBE_JS_CHECK_BOT_WALL as _JS_CHECK_BOT_WALL,
    YOUTUBE_JS_CHECK_CONSENT_MODAL as _JS_CHECK_CONSENT_MODAL,
    YOUTUBE_JS_CHECK_COOKIES as _JS_CHECK_COOKIES,
    YOUTUBE_JS_DISMISS_CONSENT_MODAL as _JS_DISMISS_CONSENT_MODAL,
    YOUTUBE_JS_DISMISS_PREMIUM_POPUP as _JS_DISMISS_PREMIUM_POPUP,
    YOUTUBE_JS_ENTER_FULLSCREEN as _JS_ENTER_FULLSCREEN,
    YOUTUBE_JS_FORCE_PLAY as _JS_FORCE_PLAY,
    YOUTUBE_JS_FIND_SKIP_AD as _JS_FIND_SKIP_AD,
    YOUTUBE_JS_VIDEO_STATUS as _JS_VIDEO_STATUS,
    YOUTUBE_JS_INSTALL_FIRST_FRAME_PROBE as _JS_INSTALL_FIRST_FRAME_PROBE,
    YOUTUBE_JS_GET_FIRST_FRAME as _JS_GET_FIRST_FRAME,
)
from shared.src.lib.utils.report_step_formatter import format_timestamp_to_hhmmss_ms
from shared.src.lib.utils.web_video_playback import calc_playback_progress

sys.argv = normalize_local_debug_flag(sys.argv)

# Script arguments
_script_args = [
    '--url:str:https://www.youtube.com/watch?v=y9n6HkftavM',  # YouTube video URL
    '--ad_wait:int:30',                                          # Seconds to wait if ad cannot be skipped
    '--monitor_duration:int:30',                                 # Seconds to monitor video playback
    '--headless:bool:false',
]
_script_description = "Open YouTube video and verify playback progression."
_arg_descriptions = {
    'url': 'YouTube video URL',
    'ad_wait': 'Seconds to wait for unskippable ads',
    'monitor_duration': 'Playback monitoring seconds',
    'headless': 'Run browser in headless mode',
}

_AD_FALLBACK_EXTRA_WAIT_SECONDS = 40


def capture_execution_summary(
    context,
    url: str,
    cookie_result: Optional[Dict[str, Any]] = None,
    ad_result: Optional[Dict[str, Any]] = None,
    video_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Capture execution summary as text for report"""
    lines = []
    lines.append("🎯 [YOUTUBE_VIDEO_CHECK] EXECUTION SUMMARY")
    lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    lines.append(f"🖥️ Host: {context.host.host_name}")
    lines.append(f"🔗 URL: {url}")
    lines.append("")

    # Cookie validation section
    lines.append("🍪 COOKIE VALIDATION")
    if cookie_result:
        injected = cookie_result.get('injected', False)
        modal_found = cookie_result.get('modal_found', False)
        js_cookies = cookie_result.get('js_cookies', {})
        lines.append(f"   Injection triggered: {'✅ YES' if injected else '❌ NO'}")
        lines.append(f"   Consent modal visible: {'❌ YES (injection may have failed)' if modal_found else '✅ NO'}")
        if js_cookies:
            has_consent = js_cookies.get('hasConsent', False)
            cookie_list = js_cookies.get('cookieList', [])
            lines.append(f"   Cookies in page: {'✅' if has_consent else '⚠️'} hasConsent={has_consent}")
            for c in cookie_list[:5]:
                lines.append(f"      {c[:80]}")
        lines.append(f"   Status: {'✅ OK' if not modal_found else '❌ FAILED'}")
    else:
        lines.append("   No cookie data collected")
    lines.append("")

    # Ad handling section
    lines.append("📺 AD HANDLING")
    if ad_result:
        ad_detected = ad_result.get('ad_detected', False)
        skip_clicked = ad_result.get('skip_clicked', False)
        waited = ad_result.get('waited_seconds', 0)
        lines.append(f"   Ad detected: {'YES' if ad_detected else 'NO'}")
        if ad_detected:
            lines.append(f"   Skip clicked: {'✅ YES' if skip_clicked else '⏳ NO - waited'}")
            if waited:
                lines.append(f"   Wait time: {waited}s")
    else:
        lines.append("   No ad data collected")
    lines.append("")

    # Video status section
    lines.append("🎬 VIDEO PLAYBACK STATUS")
    if video_result:
        success = video_result.get('success', False)
        samples = video_result.get('samples', [])
        playing = video_result.get('playing', False)
        progress = video_result.get('progress_seconds', 0)
        lines.append(f"   Playback confirmed: {'✅ YES' if playing else '❌ NO'}")
        lines.append(f"   Time progression: {progress:.1f}s over {len(samples)} samples")
        if samples:
            first = samples[0]
            last = samples[-1]
            lines.append(f"   First sample: t={first.get('currentTime', 0):.1f}s paused={first.get('paused', True)}")
            lines.append(f"   Last sample:  t={last.get('currentTime', 0):.1f}s paused={last.get('paused', True)}")
        error = video_result.get('error')
        if error:
            lines.append(f"   Error: {error}")
    else:
        lines.append("   No video status data collected")
    lines.append("")

    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")

    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")

    return "\n".join(lines)


def capture_local_execution_summary(
    context,
    url: str,
    cookie_result: Optional[Dict[str, Any]] = None,
    ad_result: Optional[Dict[str, Any]] = None,
    video_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Capture execution summary text for local-debug mode (no host/device objects)."""
    lines = []
    lines.append("🎯 [YOUTUBE_VIDEO_CHECK] LOCAL DEBUG SUMMARY")
    lines.append(f"🖥️  Mode: local-debug (host Playwright only)")
    lines.append(f"🔗 URL: {url}")
    lines.append("")

    lines.append("🍪 COOKIE VALIDATION")
    if cookie_result:
        lines.append(f"   Consent modal visible: {'YES' if cookie_result.get('modal_found') else 'NO'}")
        js_cookies = cookie_result.get('js_cookies', {}) or {}
        if js_cookies:
            lines.append(f"   hasConsent={js_cookies.get('hasConsent')}")
    else:
        lines.append("   No cookie data collected")
    lines.append("")

    lines.append("📺 AD HANDLING")
    if ad_result:
        lines.append(f"   Ad detected: {'YES' if ad_result.get('ad_detected') else 'NO'}")
        lines.append(f"   Skip clicked: {'YES' if ad_result.get('skip_clicked') else 'NO'}")
    else:
        lines.append("   No ad data collected")
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


async def _run_local_playwright_flow(
    video_url: str,
    ad_wait: int,
    monitor_duration: int,
    headless: bool = False,
    output_dir: str = "",
) -> Dict[str, Any]:
    """Run YouTube checks directly with Playwright on host, no VPT controllers."""
    cookie_result = None
    ad_result = None
    video_result = None
    step_results = []
    screenshot_paths = []
    trace_path = ""
    test_video_path = ""
    project_tmp = os.path.join(project_root, 'tmp', 'local_debug', 'youtube_video_check')
    output_dir = output_dir or os.path.join(project_tmp, f"adhoc_{int(time.time())}")
    os.makedirs(output_dir, exist_ok=True)
    screenshots_dir = os.path.join(output_dir, 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)

    def add_step(message: str, success: bool, actions=None, verifications=None, screenshot_path: str = ""):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node='youtube_video_check',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
        )

    async def capture_pw_screenshot(page_obj, name: str) -> str:
        idx = len(screenshot_paths) + 1
        path = os.path.join(screenshots_dir, f"{idx:02d}_{name}.png")
        print(f"[PW] page.screenshot(path='{path}', full_page=True)")
        return await capture_local_debug_screenshot(
            page=page_obj,
            screenshots_dir=screenshots_dir,
            screenshot_paths=screenshot_paths,
            name=name,
        )

    async with local_debug_playwright_session(
        profile_name="youtube_check",
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
            from_node='youtube_video_check',
            session=session,
        )
        trace_path = os.path.join(output_dir, 'trace.zip')
        print(f"[PW] context.tracing.start(screenshots=True, snapshots=True, sources=True)")
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        print("[PW] page.set_default_timeout(30000)")
        page.set_default_timeout(30000)

        # Step 1: Open YouTube and inspect cookie/consent status
        print("[PW] page.goto('https://www.youtube.com', wait_until='domcontentloaded')")
        await page.goto('https://www.youtube.com', wait_until='domcontentloaded')
        print("[PW] page.wait_for_timeout(3000)")
        await page.wait_for_timeout(3000)
        youtube_home_shot = await capture_pw_screenshot(page, 'youtube_home')
        # Use first meaningful page state as the "initial state" screenshot in report.
        step_results[0]['screenshot_path'] = youtube_home_shot
        step_results[0]['step_end_screenshot_path'] = youtube_home_shot
        step_results[0]['action_screenshots'] = [youtube_home_shot]

        print("[PW] page.evaluate(_JS_CHECK_CONSENT_MODAL)")
        modal_selector = await page.evaluate(_JS_CHECK_CONSENT_MODAL)
        modal_found = bool(modal_selector)
        print(f"[PW] consent modal detected={modal_found} selector={modal_selector}")
        print("[PW] page.evaluate(_JS_CHECK_COOKIES)")
        js_cookies = await page.evaluate(_JS_CHECK_COOKIES)

        if modal_found:
            # Best-effort local consent handling for direct Playwright debug.
            print("[PW] page.evaluate(_JS_DISMISS_CONSENT_MODAL)")
            await page.evaluate(_JS_DISMISS_CONSENT_MODAL)
            await page.wait_for_timeout(2000)
            if await page.evaluate(_JS_CHECK_CONSENT_MODAL):
                await page.evaluate(_JS_DISMISS_CONSENT_MODAL)
                await page.wait_for_timeout(1500)
            consent_shot = await capture_pw_screenshot(page, 'consent_after_dismiss')

            modal_selector = await page.evaluate(_JS_CHECK_CONSENT_MODAL)
            modal_found = bool(modal_selector)
            js_cookies = await page.evaluate(_JS_CHECK_COOKIES)
        else:
            consent_shot = youtube_home_shot

        cookie_result = {
            'injected': False,
            'modal_found': modal_found,
            'modal_selector': modal_selector,
            'js_cookies': js_cookies,
        }
        add_step(
            "Open YouTube and validate consent/cookies",
            not modal_found,
            actions=[
                {'command': 'page.goto', 'params': {'url': 'https://www.youtube.com', 'wait_until': 'domcontentloaded'}, 'label': 'Open YouTube'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_CHECK_CONSENT_MODAL'}, 'label': 'Check consent modal'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_CHECK_COOKIES'}, 'label': 'Check cookies'},
            ],
            verifications=[{
                'success': not modal_found,
                'label': 'Consent modal closed',
                'details': {'modal_selector': modal_selector, 'hasConsent': (js_cookies or {}).get('hasConsent', False)}
            }],
            screenshot_path=consent_shot,
        )

        if modal_found:
            try:
                print(f"[PW] context.tracing.stop(path='{trace_path}')")
                await context.tracing.stop(path=trace_path)
            except Exception:
                pass
            await context.close()
            if page.video:
                raw_video_path = await page.video.path()
                if raw_video_path and os.path.exists(raw_video_path):
                    final_video_path = os.path.join(output_dir, 'test_execution.webm')
                    shutil.move(raw_video_path, final_video_path)
                    test_video_path = final_video_path
            if browser is not None:
                print("[PW] browser.close()")
                await browser.close()
            stop_local_debug_cdp_process(launched_process)
            return {
                'success': False,
                'error': f'Cookie consent modal visible: {modal_selector}',
                'cookie_result': cookie_result,
                'ad_result': ad_result,
                'video_result': video_result,
                'step_results': step_results,
                'screenshot_paths': screenshot_paths,
                'trace_path': trace_path if os.path.exists(trace_path) else "",
                'test_video_path': test_video_path,
            }

        # Step 2: Open target video
        print(f"[PW] page.goto('{video_url}', wait_until='domcontentloaded')")
        page_load_start = time.time()
        await page.goto(video_url, wait_until='domcontentloaded')
        page_load_time_ms = int((time.time() - page_load_start) * 1000)
        # Install the browser-side first-frame probe ASAP on the freshly-navigated
        # video document. It measures buffering from the page's own timeOrigin to the
        # first painted frame (requestVideoFrameCallback), so the number reflects real
        # startup buffering instead of our ad-handling sleeps. video_play_start is kept
        # only as a coarse wall-clock fallback if the probe never fires.
        print("[PW] page.evaluate(_JS_INSTALL_FIRST_FRAME_PROBE)")
        await page.evaluate(_JS_INSTALL_FIRST_FRAME_PROBE)
        video_play_start = time.time()
        print("[PW] page.wait_for_timeout(5000)")
        await page.wait_for_timeout(5000)
        print("[PW] page.evaluate(_JS_CHECK_BOT_WALL)")
        bot_wall = await page.evaluate(_JS_CHECK_BOT_WALL)
        print(f"[PW] bot_wall={bot_wall!r}")
        if not bot_wall:
            print("[PW] page.evaluate(_JS_FORCE_PLAY)")
            await page.evaluate(_JS_FORCE_PLAY)
            print("[PW] page.evaluate(_JS_ENTER_FULLSCREEN)")
            fs_result = await page.evaluate(_JS_ENTER_FULLSCREEN)
            print(f"[PW] fullscreen_result={fs_result}")
        video_opened_shot = await capture_pw_screenshot(page, 'video_opened')
        add_step(
            "Open target YouTube video",
            not bot_wall,
            actions=[action for action in [
                {'command': 'page.goto', 'params': {'url': video_url, 'wait_until': 'domcontentloaded'}, 'label': 'Open video URL'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_CHECK_BOT_WALL'}, 'label': 'Check anti-bot interstitial'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_FORCE_PLAY'}, 'label': 'Force play'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_ENTER_FULLSCREEN'}, 'label': 'Enter fullscreen'},
            ] if action],
            verifications=[{
                'success': not bot_wall,
                'label': 'Watch page served (no anti-bot interstitial)',
                'details': {'bot_wall': bot_wall},
            }],
            screenshot_path=video_opened_shot,
        )

        if bot_wall:
            # Fail fast with the real reason instead of "playback not confirmed" after the
            # whole monitoring window: YouTube refused to serve the watch page to this
            # IP/profile. Typical for datacenter egress (CI runners); fix is on the network
            # side (residential egress, logged-in profile), not in the player logic.
            error = f"YouTube anti-bot interstitial: '{bot_wall}' — watch page not served to this IP/profile"
            print(f"[PW] {error}")
            try:
                print(f"[PW] context.tracing.stop(path='{trace_path}')")
                await context.tracing.stop(path=trace_path)
            except Exception:
                pass
            await context.close()
            if page.video:
                raw_video_path = await page.video.path()
                if raw_video_path and os.path.exists(raw_video_path):
                    final_video_path = os.path.join(output_dir, 'test_execution.webm')
                    shutil.move(raw_video_path, final_video_path)
                    test_video_path = final_video_path
            if browser is not None:
                print("[PW] browser.close()")
                await browser.close()
            stop_local_debug_cdp_process(launched_process)
            return {
                'success': False,
                'error': error,
                'cookie_result': cookie_result,
                'ad_result': ad_result,
                'video_result': {'success': False, 'playing': False, 'samples': [], 'error': error},
                'step_results': step_results,
                'screenshot_paths': screenshot_paths,
                'trace_path': trace_path if os.path.exists(trace_path) else "",
                'test_video_path': test_video_path,
            }

        # Step 3: Ad handling — use native Playwright locators (no JS evaluate)
        ad_detected = False
        skip_clicked = False
        waited_seconds = 0

        # Detect ad via .ad-showing class on the player element
        ad_player = page.locator('.html5-video-player.ad-showing')
        ad_detected = await ad_player.count() > 0
        print(f"[PW] ad_detected={ad_detected}")

        if ad_detected:
            # Try to click skip button using native Playwright locators
            skip_btn = page.locator(
                '.ytp-skip-ad-button, .ytp-ad-skip-button, '
                '.ytp-ad-skip-button-modern, .ytp-skip-ad-button__button, '
                'button.ytp-skip-ad-button'
            ).first
            # Also try text-based: "Skip" button anywhere in the ad overlay
            skip_btn_text = page.get_by_text('Skip', exact=False).locator(
                'visible=true'
            ).first

            async def try_click_skip():
                """Try each skip locator, return True if one was clicked."""
                for label, loc in [('selector', skip_btn), ('text', skip_btn_text)]:
                    try:
                        if await loc.count() > 0 and await loc.is_visible():
                            await loc.click(timeout=2000)
                            print(f"[PW] skip_clicked via {label}")
                            return True
                    except Exception as e:
                        print(f"[PW] skip click failed ({label}): {e}")
                return False

            skip_clicked = await try_click_skip()
            if skip_clicked:
                await page.wait_for_timeout(2000)
                # Verify ad actually cleared
                if await ad_player.count() > 0:
                    skip_clicked = False
                    print("[PW] ad still showing after skip click")

            if not skip_clicked:
                poll_interval = 2
                elapsed = 0
                while elapsed < ad_wait:
                    await page.wait_for_timeout(poll_interval * 1000)
                    elapsed += poll_interval

                    # Try skip again (button may appear after countdown)
                    if await try_click_skip():
                        await page.wait_for_timeout(2000)
                        if await ad_player.count() == 0:
                            skip_clicked = True
                            waited_seconds = elapsed
                            print(f"[PW] skip_clicked_after={elapsed}s")
                            break

                    # Check if ad finished on its own
                    if await ad_player.count() == 0:
                        waited_seconds = elapsed
                        print(f"[PW] ad_finished_after={elapsed}s")
                        break
                else:
                    waited_seconds = ad_wait

                if not skip_clicked:
                    print(f"[PW] extra ad fallback wait={_AD_FALLBACK_EXTRA_WAIT_SECONDS}s")
                    await page.wait_for_timeout(_AD_FALLBACK_EXTRA_WAIT_SECONDS * 1000)
                    waited_seconds += _AD_FALLBACK_EXTRA_WAIT_SECONDS

        ad_result = {
            'ad_detected': ad_detected,
            'skip_clicked': skip_clicked,
            'waited_seconds': waited_seconds,
        }
        # Ensure fullscreen after ad transitions.
        print("[PW] page.evaluate(_JS_ENTER_FULLSCREEN)")
        fs_after_ad = await page.evaluate(_JS_ENTER_FULLSCREEN)
        print(f"[PW] fullscreen_after_ad={fs_after_ad}")
        ad_state_shot = await capture_pw_screenshot(page, 'ad_handling_end')
        add_step(
            "Handle YouTube ad",
            True,
            actions=[
                {'command': 'page.locator.click', 'params': {}, 'label': 'Check ad via .ad-showing class'},
                {'command': 'page.locator.click', 'params': {}, 'label': 'Click skip button (native locator)'},
                {'command': 'page.evaluate', 'params': {'script': '_JS_ENTER_FULLSCREEN'}, 'label': 'Re-enter fullscreen'},
            ],
            verifications=[{
                'success': True,
                'label': 'Ad handling completed',
                'details': {**ad_result, 'fullscreen': fs_after_ad}
            }],
            screenshot_path=ad_state_shot,
        )

        # Step 4: Playback monitoring
        samples = []
        poll_interval = 5
        elapsed = 0
        playing = False
        monitor_error = None
        premium_dismissed = False
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
                        # Dismiss premium popup once after 30s of video playback
                        if not premium_dismissed and sample.get('currentTime', 0) >= 30:
                            premium_patterns = ['No thanks', 'Not now', 'Maybe later', 'Continue without']
                            for text in premium_patterns:
                                btn = page.get_by_text(text, exact=False).locator('visible=true').first
                                try:
                                    if await btn.count() > 0 and await btn.is_visible():
                                        await btn.click(timeout=2000)
                                        print(f"[PW] premium_popup dismissed via text='{text}'")
                                        premium_dismissed = True
                                        await page.wait_for_timeout(1500)
                                        await page.evaluate(_JS_FORCE_PLAY)
                                        break
                                except Exception:
                                    pass
                            premium_dismissed = True
                    elif sample.get('paused', True):
                        print("[PW] page.evaluate(_JS_FORCE_PLAY)")
                        await page.evaluate(_JS_FORCE_PLAY)
                else:
                    print(f"[PW] video element not found at elapsed={elapsed}s")
                print(f"[PW] page.wait_for_timeout({poll_interval * 1000})")
                await page.wait_for_timeout(poll_interval * 1000)
                elapsed += poll_interval
            except Exception as monitor_exc:
                monitor_error = str(monitor_exc)
                print(f"[PW] monitor loop interrupted: {monitor_error}")
                break

        progress_seconds, progressing = calc_playback_progress(samples)
        playback_confirmed = bool(playing or progressing or progress_seconds > 1.0)

        # Prefer the browser-side first-frame measurement; the wall-clock value above
        # is only a fallback for browsers without a first-frame signal.
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
                'details': {'progress_seconds': progress_seconds, 'sample_count': len(samples), 'monitor_error': monitor_error}
            }],
            screenshot_path=video_end_shot,
        )

        try:
            print(f"[PW] context.tracing.stop(path='{trace_path}')")
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
                print("[PW] browser.close()")
                await browser.close()
            except Exception as browser_close_exc:
                print(f"[PW] browser close failed: {browser_close_exc}")
        stop_local_debug_cdp_process(launched_process)
        return {
            'success': playback_confirmed,
            'error': None if playback_confirmed else (monitor_error or 'Video playback not confirmed during monitoring window'),
            'cookie_result': cookie_result,
            'ad_result': ad_result,
            'video_result': video_result,
            'page_load_time_ms': page_load_time_ms,
            'video_load_time_ms': video_load_time_ms,
            'step_results': step_results,
            'screenshot_paths': screenshot_paths,
            'trace_path': trace_path if os.path.exists(trace_path) else "",
            'test_video_path': test_video_path,
        }


@script("youtube_video_check", "Launch browser, validate YouTube cookies, play video, check status")
def main():
    """Main function: navigate to YouTube, validate cookies, play video, monitor playback"""
    args = get_args()
    context = get_context()

    video_url = args.url
    ad_wait = args.ad_wait
    monitor_duration = args.monitor_duration

    if getattr(args, 'local_debug', False):
        print(f"🧪 [youtube_video_check] Running local Playwright-only mode")
        local_output_dir = (context.custom_data or {}).get('local_output_dir', '')
        return run_local_debug_with_context(
            context=context,
            run_local=lambda: asyncio.run(_run_local_playwright_flow(
                video_url,
                ad_wait,
                monitor_duration,
                bool(getattr(args, 'headless', False)),
                local_output_dir,
            )),
            summary_builder=lambda ctx, result: capture_local_execution_summary(
                ctx,
                video_url,
                result.get('cookie_result'),
                result.get('ad_result'),
                result.get('video_result'),
            ),
            metadata_builder=lambda result: {
                'mode': 'local_debug',
                'url': video_url,
                'cookie_result': result.get('cookie_result'),
                'ad_result': result.get('ad_result'),
                'video_result': result.get('video_result'),
                'page_load_time_ms': result.get('page_load_time_ms'),
                'video_load_time_ms': result.get('video_load_time_ms'),
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

    device = get_device()

    print(f"🎯 [youtube_video_check] URL: {video_url}")
    print(f"📱 [youtube_video_check] Device: {device.device_name} ({device.device_model})")

    cookie_result = None
    ad_result = None
    video_result = None
    step_results = []

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
            from_node='youtube_video_check',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
        )

    # ── STEP 1: Get web controller ────────────────────────────────────────────
    web_controller = device._get_controller('web')
    if not web_controller:
        add_step(
            "Launch browser session",
            False,
            actions=[{'command': 'web_controller.open_browser', 'params': {'only_if_disconnected': True}}],
            verifications=[{
                'success': False,
                'label': 'Browser available',
                'command': 'assert_browser_connected',
                'details': {'error': 'No web controller available on this device'},
            }],
        )
        context.error_message = "No web controller available on this device"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, video_url)
        return False

    # ── STEP 2: Ensure browser is open ───────────────────────────────────────
    print(f"\n📋 [youtube_video_check] ==========================================")
    print(f"📋 [youtube_video_check] CHECKING BROWSER STATUS")
    print(f"📋 [youtube_video_check] ==========================================\n")

    browser_session = ensure_browser_session(
        web_controller,
        add_step=add_step,
        open_command='web_controller.open_browser',
    )
    if not browser_session.get('success'):
        context.error_message = f"Failed to open browser: {browser_session.get('error')}"
        context.overall_success = False
        context.step_results = step_results
        context.metadata = {
            'mode': 'device_web_controller',
            'target_url': video_url,
        }
        context.execution_summary = capture_execution_summary(context, video_url)
        return False
    if browser_session.get('opened_now'):
        print(f"✅ [youtube_video_check] Browser opened successfully")
    else:
        print(f"✅ [youtube_video_check] Browser already open")

    # ── STEP 3: Navigate to youtube.com and validate cookies ─────────────────
    print(f"\n📋 [youtube_video_check] ==========================================")
    print(f"📋 [youtube_video_check] NAVIGATING TO YOUTUBE.COM + COOKIE CHECK")
    print(f"📋 [youtube_video_check] ==========================================\n")

    nav_home_result = asyncio.run(web_controller.navigate_to_url('https://www.youtube.com'))
    if not nav_home_result.get('success'):
        add_step(
            "Open YouTube and validate consent/cookies",
            False,
            actions=[{'command': 'web_controller.navigate_to_url', 'params': {'url': 'https://www.youtube.com'}}],
            verifications=[{
                'success': False,
                'label': 'Consent modal closed',
                'details': {'error': nav_home_result.get('error', 'Unknown')},
            }],
        )
        context.error_message = f"Failed to navigate to youtube.com: {nav_home_result.get('error', 'Unknown')}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, video_url)
        return False

    print(f"✅ [youtube_video_check] On youtube.com: {nav_home_result.get('title', '')}")

    # Wait briefly for page to settle
    time.sleep(3)

    # Check for consent modal
    modal_result = asyncio.run(web_controller.execute_javascript(_JS_CHECK_CONSENT_MODAL))
    modal_selector = modal_result.get('result') if modal_result.get('success') else None
    modal_found = bool(modal_selector)

    # Get cookies visible in the page
    js_cookie_result = asyncio.run(web_controller.execute_javascript(_JS_CHECK_COOKIES))
    js_cookies = js_cookie_result.get('result') if js_cookie_result.get('success') else {}

    cookie_result = {
        'injected': True,  # inject_consent_cookies_if_needed runs automatically during navigate_to_url
        'modal_found': modal_found,
        'modal_selector': modal_selector,
        'js_cookies': js_cookies,
    }

    print(f"🍪 [youtube_video_check] Consent modal present: {modal_found}")
    if modal_found:
        print(f"⚠️  [youtube_video_check] Cookie injection may have failed — modal still visible: {modal_selector}")
        open_step_shot = capture_step_screenshot("youtube_home_state")
        add_step(
            "Open YouTube and validate consent/cookies",
            False,
            actions=[
                {'command': 'web_controller.navigate_to_url', 'params': {'url': 'https://www.youtube.com'}},
                {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_CHECK_CONSENT_MODAL'}},
                {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_CHECK_COOKIES'}},
            ],
            verifications=[{
                'success': False,
                'label': 'Consent modal closed',
                'details': {'modal_selector': modal_selector, 'hasConsent': (js_cookies or {}).get('hasConsent', False)},
            }],
            screenshot_path=open_step_shot,
        )
        context.error_message = f"Cookie consent modal still visible after injection: {modal_selector}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, video_url, cookie_result)
        return False

    if js_cookies:
        print(f"🍪 [youtube_video_check] hasConsent={js_cookies.get('hasConsent')} "
              f"cookies={js_cookies.get('cookieList', [])}")
    open_step_shot = capture_step_screenshot("youtube_home_state")
    add_step(
        "Open YouTube and validate consent/cookies",
        True,
        actions=[
            {'command': 'web_controller.navigate_to_url', 'params': {'url': 'https://www.youtube.com'}},
            {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_CHECK_CONSENT_MODAL'}},
            {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_CHECK_COOKIES'}},
        ],
        verifications=[{
            'success': True,
            'label': 'Consent modal closed',
            'details': {'modal_selector': modal_selector, 'hasConsent': (js_cookies or {}).get('hasConsent', False)},
        }],
        screenshot_path=open_step_shot,
    )

    # ── STEP 4: Navigate to the specific YouTube video ────────────────────────
    print(f"\n📋 [youtube_video_check] ==========================================")
    print(f"📋 [youtube_video_check] NAVIGATING TO VIDEO")
    print(f"📋 [youtube_video_check] ==========================================\n")

    page_load_start = time.time()
    nav_video_result = asyncio.run(web_controller.navigate_to_url(video_url))
    page_load_time_ms = int((time.time() - page_load_start) * 1000)
    # video_load anchors here (video page loaded) and measures time until playback is confirmed.
    video_play_start = time.time()
    if not nav_video_result.get('success'):
        add_step(
            "Open target YouTube video",
            False,
            actions=[{'command': 'web_controller.navigate_to_url', 'params': {'url': video_url}}],
            verifications=[{
                'success': False,
                'label': 'Video page opened',
                'details': {'error': nav_video_result.get('error', 'Unknown')},
            }],
        )
        context.error_message = f"Failed to navigate to video: {nav_video_result.get('error', 'Unknown')}"
        context.overall_success = False
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, video_url, cookie_result)
        return False

    print(f"✅ [youtube_video_check] On video page: {nav_video_result.get('title', '')}")

    # Install the browser-side first-frame probe ASAP on the freshly-navigated video
    # document so buffering is measured from the page's own timeOrigin to the first
    # painted frame, not from our ad-handling sleeps. video_play_start stays as a
    # coarse wall-clock fallback only.
    asyncio.run(web_controller.execute_javascript(_JS_INSTALL_FIRST_FRAME_PROBE))

    # Wait for video player to initialize
    print(f"⏳ [youtube_video_check] Waiting 5s for player to initialize...")
    time.sleep(5)
    force_play_result = asyncio.run(web_controller.execute_javascript(_JS_FORCE_PLAY))
    print(
        f"▶️ [youtube_video_check] Force play result: "
        f"{force_play_result.get('result') if force_play_result.get('success') else force_play_result.get('error')}"
    )
    fs_result = asyncio.run(web_controller.execute_javascript(_JS_ENTER_FULLSCREEN))
    print(f"🖥️ [youtube_video_check] Fullscreen request result: {fs_result.get('result') if fs_result.get('success') else fs_result.get('error')}")
    video_open_step_shot = capture_step_screenshot("youtube_video_opened")
    add_step(
        "Open target YouTube video",
        True,
        actions=[action for action in [
            {'command': 'web_controller.navigate_to_url', 'params': {'url': video_url}},
            {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_FORCE_PLAY'}},
            {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_ENTER_FULLSCREEN'}},
        ] if action],
        screenshot_path=video_open_step_shot,
    )

    # ── STEP 5: Ad handling ───────────────────────────────────────────────────
    print(f"\n📋 [youtube_video_check] ==========================================")
    print(f"📋 [youtube_video_check] AD HANDLING")
    print(f"📋 [youtube_video_check] ==========================================\n")

    ad_detected = False
    skip_clicked = False
    waited_seconds = 0

    # Check if an ad is playing
    ad_check = asyncio.run(web_controller.execute_javascript(_JS_CHECK_AD))
    ad_info = ad_check.get('result', {}) if ad_check.get('success') else {}
    ad_detected = ad_info.get('adPlaying', False)

    print(f"📺 [youtube_video_check] Ad detected: {ad_detected}")

    def _try_skip_ad():
        """Find the skip button via JS, then click it via real Playwright (CDP).
        YouTube rejects synthesized JS clicks on .ytp-skip-ad-button — only a
        trusted CDP mouse event will dismiss the ad.
        Returns True if the ad was successfully cleared.
        """
        find_result = asyncio.run(web_controller.execute_javascript(_JS_FIND_SKIP_AD))
        find_info = find_result.get('result', {}) if find_result.get('success') else {}
        if not find_info.get('found'):
            return False
        selector = find_info.get('selector')
        print(f"📺 [youtube_video_check] Skip button visible: {selector} — clicking via Playwright")
        click_result = asyncio.run(web_controller.click_element(selector))
        if not click_result.get('success'):
            print(f"⚠️ [youtube_video_check] click_element failed: {click_result.get('error')}")
            return False
        time.sleep(2)
        ad_check_after = asyncio.run(web_controller.execute_javascript(_JS_CHECK_AD))
        ad_info_after = ad_check_after.get('result', {}) if ad_check_after.get('success') else {}
        cleared = not ad_info_after.get('adPlaying', True)
        print(f"📺 [youtube_video_check] Skip via {selector} cleared_ad={cleared} state={ad_info_after}")
        return cleared

    if ad_detected:
        # Try to skip immediately
        skip_clicked = _try_skip_ad()

        if not skip_clicked:
            # Try polling for skip button for up to ad_wait seconds
            print(f"⏳ [youtube_video_check] No skip button yet — polling for {ad_wait}s...")
            poll_interval = 2
            elapsed = 0
            while elapsed < ad_wait:
                time.sleep(poll_interval)
                elapsed += poll_interval

                # Try skip
                if _try_skip_ad():
                    skip_clicked = True
                    waited_seconds = elapsed
                    print(f"✅ [youtube_video_check] Ad skipped after {elapsed}s")
                    break

                # Check if ad finished on its own
                ad_check2 = asyncio.run(web_controller.execute_javascript(_JS_CHECK_AD))
                ad_info2 = ad_check2.get('result', {}) if ad_check2.get('success') else {}
                if not ad_info2.get('adPlaying', True):
                    print(f"✅ [youtube_video_check] Ad finished after {elapsed}s")
                    waited_seconds = elapsed
                    break

                countdown = ad_info2.get('countdownText', '')
                print(f"   [{elapsed}s] Ad still playing... {countdown}")
            else:
                waited_seconds = ad_wait
                print(f"⏳ [youtube_video_check] Ad wait complete ({ad_wait}s)")
            if not skip_clicked:
                print(
                    f"⏳ [youtube_video_check] Extra fallback wait "
                    f"({_AD_FALLBACK_EXTRA_WAIT_SECONDS}s) to let ad finish naturally"
                )
                time.sleep(_AD_FALLBACK_EXTRA_WAIT_SECONDS)
                waited_seconds += _AD_FALLBACK_EXTRA_WAIT_SECONDS
                ad_check3 = asyncio.run(web_controller.execute_javascript(_JS_CHECK_AD))
                ad_info3 = ad_check3.get('result', {}) if ad_check3.get('success') else {}
                print(f"📺 [youtube_video_check] Ad state after extra wait: {ad_info3}")
    else:
        print(f"✅ [youtube_video_check] No ad detected — video should be playing")

    ad_result = {
        'ad_detected': ad_detected,
        'skip_clicked': skip_clicked,
        'waited_seconds': waited_seconds,
    }
    fs_after_ad = asyncio.run(web_controller.execute_javascript(_JS_ENTER_FULLSCREEN))
    print(f"🖥️ [youtube_video_check] Fullscreen after ad result: {fs_after_ad.get('result') if fs_after_ad.get('success') else fs_after_ad.get('error')}")
    ad_step_shot = capture_step_screenshot("youtube_ad_state")
    add_step(
        "Handle YouTube ad",
        True,
        actions=[
            {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_CHECK_AD'}},
            {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_FIND_SKIP_AD'}},
            {'command': 'web_controller.click_element', 'params': {'element_id': '<skip selector>'}},
            {'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_ENTER_FULLSCREEN'}},
        ],
        verifications=[{
            'success': True,
            'label': 'Ad handling completed',
            'details': {**ad_result, 'fullscreen': fs_after_ad.get('result') if fs_after_ad.get('success') else fs_after_ad.get('error')},
        }],
        screenshot_path=ad_step_shot,
    )

    # ── STEP 6: Monitor video playback for monitor_duration seconds ───────────
    print(f"\n📋 [youtube_video_check] ==========================================")
    print(f"📋 [youtube_video_check] MONITORING VIDEO STATUS ({monitor_duration}s)")
    print(f"📋 [youtube_video_check] ==========================================\n")

    samples = []
    poll_interval = 5
    elapsed = 0
    playing = False
    initial_time = None
    premium_dismissed = False
    video_load_time_ms = None

    while elapsed < monitor_duration:
        status_result = asyncio.run(web_controller.execute_javascript(_JS_VIDEO_STATUS))
        if status_result.get('success') and status_result.get('result', {}).get('found'):
            sample = status_result['result']
            sample['elapsed'] = elapsed
            samples.append(sample)

            current_time = sample.get('currentTime', 0)
            paused = sample.get('paused', True)
            ready_state = sample.get('readyState', 0)
            error = sample.get('error')

            if initial_time is None:
                initial_time = current_time

            print(f"   [{elapsed}s] currentTime={current_time:.1f}s paused={paused} "
                  f"readyState={ready_state} error={error}")

            if not paused and current_time > 0:
                playing = True
                if video_load_time_ms is None:
                    video_load_time_ms = int((time.time() - video_play_start) * 1000)
                # Dismiss premium popup once after 30s of video playback
                if not premium_dismissed and current_time >= 30:
                    premium_retry = asyncio.run(web_controller.execute_javascript(_JS_DISMISS_PREMIUM_POPUP))
                    if premium_retry.get('success') and (premium_retry.get('result') or {}).get('clicked'):
                        print(
                            f"   [{elapsed}s] Premium popup dismissed: "
                            f"{premium_retry.get('result')}"
                        )
                        time.sleep(1.5)
                        asyncio.run(web_controller.execute_javascript(_JS_FORCE_PLAY))
                    premium_dismissed = True
            elif paused:
                retry_play = asyncio.run(web_controller.execute_javascript(_JS_FORCE_PLAY))
                print(
                    f"   [{elapsed}s] Retried play: "
                    f"{retry_play.get('result') if retry_play.get('success') else retry_play.get('error')}"
                )
        else:
            print(f"   [{elapsed}s] Could not get video status: "
                  f"{status_result.get('error', 'video element not found')}")

        time.sleep(poll_interval)
        elapsed += poll_interval

    # Calculate time progression
    progress_seconds, progressing = calc_playback_progress(samples)
    playing = bool(playing or progressing)

    # Prefer the browser-side first-frame measurement; the wall-clock value above is
    # only a fallback for browsers without a first-frame signal.
    first_frame_method = None
    try:
        ff_result = asyncio.run(web_controller.execute_javascript(_JS_GET_FIRST_FRAME))
        ff = ff_result.get('result', {}) if ff_result.get('success') else {}
        if ff and ff.get('available') and ff.get('firstFrameMs') is not None:
            video_load_time_ms = int(ff['firstFrameMs'])
            first_frame_method = ff.get('method')
            print(f"🎞️ [youtube_video_check] First-frame video_load_time_ms={video_load_time_ms} method={first_frame_method}")
    except Exception as ff_exc:
        print(f"⚠️ [youtube_video_check] First-frame probe read failed: {ff_exc}")

    video_result = {
        'success': playing,
        'playing': playing,
        'samples': samples,
        'progress_seconds': progress_seconds,
        'error': None if playing else 'Video did not play during monitoring window',
    }

    if not playing:
        print(f"❌ [youtube_video_check] Video was not playing during {monitor_duration}s monitoring window")
    else:
        print(f"✅ [youtube_video_check] Video playing confirmed — progressed {progress_seconds:.1f}s")
    monitor_step_shot = capture_step_screenshot("youtube_monitor_end")
    add_step(
        "Monitor playback progression",
        bool(playing),
        actions=[{'command': 'web_controller.execute_javascript', 'params': {'script': '_JS_VIDEO_STATUS'}}],
        verifications=[{
            'success': bool(playing),
            'label': 'Playback progressed',
            'details': {'progress_seconds': progress_seconds, 'sample_count': len(samples)},
        }],
        screenshot_path=monitor_step_shot,
    )

    # ── STEP 7: Set result and capture summary ────────────────────────────────
    context.overall_success = playing
    if not playing and not context.error_message:
        context.error_message = "Video playback not confirmed during monitoring window"

    context.metadata = {
        "url": video_url,
        "cookie_result": cookie_result,
        "ad_result": ad_result,
        "page_load_time_ms": page_load_time_ms,
        "video_load_time_ms": video_load_time_ms,
        "first_frame_method": first_frame_method,
        "video_result": {
            "playing": playing,
            "progress_seconds": progress_seconds,
            "sample_count": len(samples),
            "video_load_time_ms": video_load_time_ms,
            "first_frame_method": first_frame_method,
        },
    }
    context.step_results = step_results

    context.execution_summary = capture_execution_summary(
        context, video_url, cookie_result, ad_result, video_result
    )

    return playing


# Assign script arguments to main function
main._script_args = _script_args


def _run_local_debug_cli():
    run_local_debug_cli(
        argv=sys.argv,
        script_name="youtube_video_check",
        project_root=project_root,
        arg_specs=[
            {"name": "--url", "kwargs": {"type": str, "default": "https://www.youtube.com/watch?v=y9n6HkftavM"}},
            {"name": "--ad_wait", "kwargs": {"type": int, "default": 30}},
            {"name": "--monitor_duration", "kwargs": {"type": int, "default": 30}},
            {"name": "--headless", "kwargs": {"type": str_to_bool, "default": False}},
        ],
        run_local=lambda args, output_dir: asyncio.run(_run_local_playwright_flow(
            args.url,
            int(args.ad_wait),
            int(args.monitor_duration),
            bool(args.headless),
            output_dir,
        )),
        summary_builder=lambda args, result, success, error: capture_local_execution_summary(
            type("LocalContext", (), {"overall_success": success, "error_message": error, "get_execution_time_ms": lambda self: 0})(),
            args.url,
            result.get("cookie_result"),
            result.get("ad_result"),
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
