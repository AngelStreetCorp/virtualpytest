#!/usr/bin/env python3
"""
Netflix Video Check Script for VirtualPyTest

Flow:
1. Open Netflix login page
2. Login with email/password
3. Select profile (required)
4. Open watch URL
5. Verify playback progression
"""

import os
import sys
import time
import json
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
    NETFLIX_JS_CLICK_GENERIC_PLAY as _JS_CLICK_GENERIC_PLAY,
    NETFLIX_JS_DETECT_DRM_BLOCK as _JS_DETECT_DRM_BLOCK,
    NETFLIX_JS_DISMISS_COOKIE_BANNER as _JS_DISMISS_COOKIE_BANNER,
    NETFLIX_JS_FORCE_PLAY as _JS_FORCE_PLAY,
    NETFLIX_JS_VIDEO_STATUS as _JS_VIDEO_STATUS,
    NETFLIX_JS_WAIT_FOR_LOGIN_RESULT as _JS_WAIT_FOR_LOGIN_RESULT,
)
from shared.src.lib.utils.report_step_formatter import format_timestamp_to_hhmmss_ms
from shared.src.lib.utils.web_video_playback import calc_playback_progress

sys.argv = normalize_local_debug_flag(sys.argv)
DEFAULT_LOCAL_DEBUG_PORT = 9222

# Keep near top for analyzer
_script_args = [
    '--email:str:',
    '--password:str:',
    '--profile:str:Kids',
    '--url:str:https://www.netflix.com/watch/81450642',
    '--login_url:str:https://www.netflix.com/login',
    '--post_login_wait:int:8',
    '--monitor_duration:int:30',
    '--headless:bool:false',
]
_script_description = "Log into Netflix and verify video playback."
_arg_descriptions = {
    'email': 'Netflix account email',
    'password': 'Netflix account password',
    'profile': 'Profile name to select',
    'url': 'Netflix watch URL',
    'login_url': 'Netflix login page URL',
    'post_login_wait': 'Seconds to wait after login',
    'monitor_duration': 'Playback monitoring seconds',
    'headless': 'Run browser in headless mode',
}


def _build_js_login(email: str, password: str) -> str:
    payload = json.dumps({'email': email, 'password': password})
    return f"""
(() => {{
    const creds = {payload};

    function setInput(el, val) {{
        if (!el) return false;
        el.focus();
        el.value = val;
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
    }}

    const emailEl = document.querySelector('input[name="userLoginId"], input[type="email"], #id_userLoginId');
    const passwordEl = document.querySelector('input[name="password"], input[type="password"], #id_password');

    const emailSet = setInput(emailEl, creds.email || '');
    const passwordSet = setInput(passwordEl, creds.password || '');

    let submitted = false;
    const submitBtn = document.querySelector('button[type="submit"], button.login-button');
    if (submitBtn) {{
        submitBtn.click();
        submitted = true;
    }} else {{
        const form = document.querySelector('form[action*="login"], form');
        if (form) {{
            form.requestSubmit ? form.requestSubmit() : form.submit();
            submitted = true;
        }}
    }}

    return {{ emailSet, passwordSet, submitted }};
}})()
"""


def _build_js_select_profile(profile_name: str) -> str:
    payload = json.dumps({'profile': profile_name})
    return f"""
(() => {{
    const expected = (({payload}).profile || '').trim().toLowerCase();
    if (!expected) return {{ selected: false, reason: 'No profile provided' }};

    function profileLabel(el) {{
        const nameEl = el.querySelector('.profile-name, [data-uia="profile-name"], .name');
        const raw = nameEl ? nameEl.textContent : el.textContent;
        return (raw || '').trim();
    }}

    const cards = Array.from(document.querySelectorAll('.profile, li.profile, .profile-icon, [data-uia="profile-link"], [data-profile-name]'));

    for (const card of cards) {{
        const txt = profileLabel(card).toLowerCase();
        if (!txt) continue;
        if (txt === expected || txt.includes(expected)) {{
            const clickable = card.querySelector('a, button') || card;
            clickable.click();
            return {{ selected: true, matched: txt, scanned: cards.length }};
        }}
    }}

    return {{ selected: false, scanned: cards.length, available: cards.map(c => profileLabel(c)).filter(Boolean) }};
}})()
"""


def capture_local_execution_summary(
    context,
    url: str,
    profile: str,
    login_result: Optional[Dict[str, Any]] = None,
    profile_result: Optional[Dict[str, Any]] = None,
    video_result: Optional[Dict[str, Any]] = None,
) -> str:
    lines = [
        '🎯 [NETFLIX_VIDEO_CHECK] LOCAL DEBUG SUMMARY',
        '🖥️  Mode: local-debug (host Playwright only)',
        f'🔗 URL: {url}',
        f'👤 Profile: {profile}',
        ''
    ]

    if login_result:
        lines.append(f"🔐 Logged in: {'YES' if login_result.get('logged_in') else 'NO'}")
    if profile_result:
        lines.append(f"👤 Profile selected: {'YES' if profile_result.get('selected') else 'NO'}")
    if video_result:
        lines.append(f"🎬 Playback confirmed: {'YES' if video_result.get('playing') else 'NO'}")
        lines.append(f"   Progress: {video_result.get('progress_seconds', 0):.1f}s")
        if video_result.get('drm_blocked'):
            lines.append('   DRM blocked: YES (M7701-1003/protected-content)')

    lines.append('')
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    return '\n'.join(lines)


def capture_execution_summary(
    context,
    url: str,
    profile: str,
    login_result: Optional[Dict[str, Any]] = None,
    profile_result: Optional[Dict[str, Any]] = None,
    video_result: Optional[Dict[str, Any]] = None,
) -> str:
    lines = [
        '🎯 [NETFLIX_VIDEO_CHECK] EXECUTION SUMMARY',
        f'📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})',
        f'🖥️ Host: {context.host.host_name}',
        f'🔗 URL: {url}',
        f'👤 Profile: {profile}',
        ''
    ]

    lines.append('🔐 LOGIN')
    if login_result:
        lines.append(f"   Submitted: {'YES' if login_result.get('submitted') else 'NO'}")
        lines.append(f"   Logged in: {'YES' if login_result.get('logged_in') else 'NO'}")
        if login_result.get('error'):
            lines.append(f"   Error: {login_result.get('error')}")
    else:
        lines.append('   No login data collected')

    lines.append('')
    lines.append('👤 PROFILE SELECTION')
    if profile_result:
        lines.append(f"   Selected: {'YES' if profile_result.get('selected') else 'NO'}")
        if profile_result.get('error'):
            lines.append(f"   Error: {profile_result.get('error')}")
    else:
        lines.append('   No profile data collected')

    lines.append('')
    lines.append('🎬 VIDEO PLAYBACK')
    if video_result:
        lines.append(f"   Playback confirmed: {'YES' if video_result.get('playing') else 'NO'}")
        lines.append(f"   Progress: {video_result.get('progress_seconds', 0):.1f}s")
        lines.append(f"   Samples: {len(video_result.get('samples', []))}")
        if video_result.get('drm_blocked'):
            lines.append('   DRM blocked: YES (M7701-1003/protected-content)')
        if video_result.get('error'):
            lines.append(f"   Error: {video_result.get('error')}")
    else:
        lines.append('   No video data collected')

    lines.append('')
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    return '\n'.join(lines)


async def _run_local_playwright_flow(
    email: str,
    password: str,
    profile: str,
    watch_url: str,
    login_url: str,
    post_login_wait: int,
    monitor_duration: int,
    headless: bool = False,
    output_dir: str = '',
) -> Dict[str, Any]:
    login_result = None
    profile_result = None
    video_result = None
    step_results = []
    screenshot_paths = []
    trace_path = ''
    test_video_path = ''

    base = os.path.join(project_root, 'tmp', 'local_debug', 'netflix_video_check')
    output_dir = output_dir or os.path.join(base, f'adhoc_{int(time.time())}')
    os.makedirs(output_dir, exist_ok=True)
    shots_dir = os.path.join(output_dir, 'screenshots')
    os.makedirs(shots_dir, exist_ok=True)

    def add_step(message: str, success: bool, actions=None, verifications=None, screenshot_path: str = ''):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node='netflix_video_check',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
        )

    async def shot(page_obj, name: str) -> str:
        return await capture_local_debug_screenshot(
            page=page_obj,
            screenshots_dir=shots_dir,
            screenshot_paths=screenshot_paths,
            name=name,
        )

    async with local_debug_playwright_session(
        profile_name="netflix_check",
        headless=headless,
        debug_port=DEFAULT_LOCAL_DEBUG_PORT,
        viewport={'width': 1366, 'height': 768},
        record_video_dir=output_dir,
    ) as session:
        launched_process = session["launched_process"]
        browser = session["browser"]
        context = session["context"]
        page = session["page"]
        append_local_debug_browser_launch_step(
            step_results=step_results,
            from_node='netflix_video_check',
            session=session,
        )

        trace_path = os.path.join(output_dir, 'trace.zip')
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page.set_default_timeout(45000)

        # Login
        await page.goto(login_url, wait_until='domcontentloaded')
        await page.wait_for_timeout(1500)
        await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
        await page.wait_for_timeout(500)
        await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
        login_state = await page.evaluate(_JS_WAIT_FOR_LOGIN_RESULT)
        already_logged_in = bool((login_state or {}).get('onBrowse') or (login_state or {}).get('profileGate'))

        submitted = False
        if not already_logged_in:
            email_input = page.locator('input[name="userLoginId"], input[type="email"], #id_userLoginId').first
            password_input = page.locator('input[name="password"], input[type="password"], #id_password').first
            if await email_input.count() == 0 or await password_input.count() == 0:
                login_shot = await shot(page, 'login_form_missing')
                add_step(
                    'Detect login form',
                    False,
                    actions=[{'command': 'locator.count', 'params': {'email_input': True, 'password_input': True}}],
                    screenshot_path=login_shot,
                )
                await context.tracing.stop(path=trace_path)
                await context.close()
                if browser:
                    await browser.close()
                stop_local_debug_cdp_process(launched_process)
                return {
                    'success': False,
                    'error': 'Login form not found and not already logged in',
                    'login_result': {'submitted': False, 'logged_in': False, 'state': login_state, 'error': 'Login form not found'},
                    'profile_result': profile_result,
                    'video_result': video_result,
                    'step_results': step_results,
                    'screenshot_paths': screenshot_paths,
                    'trace_path': trace_path if os.path.exists(trace_path) else '',
                    'test_video_path': test_video_path,
                }

            await email_input.fill(email)
            await password_input.fill(password)

            submit_btn = page.locator('button[type="submit"], button.login-button').first
            if await submit_btn.count() > 0:
                await submit_btn.click()
            else:
                await page.keyboard.press('Enter')
            submitted = True

            await page.wait_for_timeout(post_login_wait * 1000)
            await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
            login_state = await page.evaluate(_JS_WAIT_FOR_LOGIN_RESULT)

        logged_in = bool((login_state or {}).get('onBrowse') or (login_state or {}).get('profileGate'))
        login_result = {
            'submitted': submitted,
            'logged_in': logged_in,
            'state': login_state,
            'error': '' if logged_in else ((login_state or {}).get('errorText') or 'Login did not reach browse/profile screen')
        }
        login_shot = await shot(page, 'after_login')
        add_step('Login to Netflix', logged_in, actions=[{'command': 'login', 'params': {'email': '***', 'password': '***'}}], screenshot_path=login_shot)

        if not logged_in:
            await context.tracing.stop(path=trace_path)
            await context.close()
            if browser:
                await browser.close()
            stop_local_debug_cdp_process(launched_process)
            return {
                'success': False,
                'error': login_result['error'],
                'login_result': login_result,
                'profile_result': profile_result,
                'video_result': video_result,
                'step_results': step_results,
                'screenshot_paths': screenshot_paths,
                'trace_path': trace_path if os.path.exists(trace_path) else '',
                'test_video_path': test_video_path,
            }

        # Profile
        profile_gate = bool((login_state or {}).get('profileGate'))
        if profile_gate:
            await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
            picked = await page.evaluate(_build_js_select_profile(profile))
            selected = bool((picked or {}).get('selected'))
            await page.wait_for_timeout(2500)
            profile_result = {
                'selected': selected,
                'profile_gate_visible': True,
                'error': '' if selected else f"Profile '{profile}' not found",
                'available': (picked or {}).get('available', []),
            }
        else:
            profile_result = {
                'selected': True,
                'profile_gate_visible': False,
                'error': '',
                'available': [],
            }

        profile_shot = await shot(page, 'after_profile_select')
        add_step('Select profile', bool(profile_result['selected']), actions=[{'command': 'profile-select', 'params': {'profile': profile}}], screenshot_path=profile_shot)

        if not profile_result['selected']:
            await context.tracing.stop(path=trace_path)
            await context.close()
            if browser:
                await browser.close()
            stop_local_debug_cdp_process(launched_process)
            return {
                'success': False,
                'error': profile_result['error'],
                'login_result': login_result,
                'profile_result': profile_result,
                'video_result': video_result,
                'step_results': step_results,
                'screenshot_paths': screenshot_paths,
                'trace_path': trace_path if os.path.exists(trace_path) else '',
                'test_video_path': test_video_path,
            }

        # Open video
        await page.goto(watch_url, wait_until='domcontentloaded')
        await page.wait_for_timeout(4500)
        await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
        await page.wait_for_timeout(500)
        await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
        await page.evaluate(_JS_CLICK_GENERIC_PLAY)
        await page.evaluate(_JS_FORCE_PLAY)
        open_shot = await shot(page, 'video_opened')
        add_step('Open target video', True, actions=[{'command': 'page.goto', 'params': {'url': watch_url}}], screenshot_path=open_shot)

        drm = await page.evaluate(_JS_DETECT_DRM_BLOCK)
        if (drm or {}).get('blocked'):
            video_result = {
                'success': False,
                'playing': False,
                'samples': [],
                'progress_seconds': 0,
                'drm_blocked': True,
                'error': 'DRM/protected-content block detected (M7701-1003)',
            }
            end_shot = await shot(page, 'video_monitor_end')
            add_step('Monitor playback progression', False, verifications=[{'success': False, 'label': 'DRM block detected', 'details': drm}], screenshot_path=end_shot)

            await context.tracing.stop(path=trace_path)
            await context.close()
            if browser:
                await browser.close()
            stop_local_debug_cdp_process(launched_process)

            return {
                'success': False,
                'error': video_result['error'],
                'login_result': login_result,
                'profile_result': profile_result,
                'video_result': video_result,
                'step_results': step_results,
                'screenshot_paths': screenshot_paths,
                'trace_path': trace_path if os.path.exists(trace_path) else '',
                'test_video_path': test_video_path,
            }

        # Monitor
        samples = []
        playing = False
        elapsed = 0
        interval = 5
        while elapsed < monitor_duration:
            sample = await page.evaluate(_JS_VIDEO_STATUS)
            if (sample or {}).get('found'):
                sample['elapsed'] = elapsed
                samples.append(sample)
                if not sample.get('paused', True) and sample.get('currentTime', 0) > 0:
                    playing = True
                else:
                    await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
                    await page.evaluate(_JS_FORCE_PLAY)
            else:
                await page.evaluate(_JS_DISMISS_COOKIE_BANNER)
                await page.evaluate(_JS_CLICK_GENERIC_PLAY)
                await page.evaluate(_JS_FORCE_PLAY)

            await page.wait_for_timeout(interval * 1000)
            elapsed += interval

        progress, progressing = calc_playback_progress(samples)
        playing = bool(playing or progressing)

        video_result = {
            'success': playing,
            'playing': playing,
            'samples': samples,
            'progress_seconds': progress,
            'drm_blocked': False,
            'error': None if playing else 'Video playback not confirmed during monitoring window',
        }

        end_shot = await shot(page, 'video_monitor_end')
        add_step('Monitor playback progression', playing, actions=[{'command': 'page.evaluate', 'params': {'script': '_JS_VIDEO_STATUS'}}], screenshot_path=end_shot)

        await context.tracing.stop(path=trace_path)
        await context.close()

        if page.video:
            raw_video = await page.video.path()
            if raw_video and os.path.exists(raw_video):
                final_video = os.path.join(output_dir, 'test_execution.webm')
                shutil.move(raw_video, final_video)
                test_video_path = final_video

        if browser:
            await browser.close()
        stop_local_debug_cdp_process(launched_process)

        return {
            'success': playing,
            'error': None if playing else 'Video playback not confirmed during monitoring window',
            'login_result': login_result,
            'profile_result': profile_result,
            'video_result': video_result,
            'step_results': step_results,
            'screenshot_paths': screenshot_paths,
            'trace_path': trace_path if os.path.exists(trace_path) else '',
            'test_video_path': test_video_path,
        }


@script('netflix_video_check', 'Login Netflix, select profile, play video, verify playback')
def main():
    args = get_args()
    context = get_context()

    email = (args.email or '').strip()
    password = (args.password or '').strip()
    profile = (args.profile or '').strip()
    watch_url = args.url
    login_url = args.login_url
    post_login_wait = args.post_login_wait
    monitor_duration = args.monitor_duration

    if not email:
        context.overall_success = False
        context.error_message = 'Missing required --email'
        context.execution_summary = '❌ Missing required --email'
        return False
    if not password:
        context.overall_success = False
        context.error_message = 'Missing required --password'
        context.execution_summary = '❌ Missing required --password'
        return False
    if not profile:
        context.overall_success = False
        context.error_message = 'Missing required --profile'
        context.execution_summary = '❌ Missing required --profile'
        return False

    if getattr(args, 'local_debug', False):
        local_output_dir = (context.custom_data or {}).get('local_output_dir', '')
        return run_local_debug_with_context(
            context=context,
            run_local=lambda: asyncio.run(_run_local_playwright_flow(
                email,
                password,
                profile,
                watch_url,
                login_url,
                post_login_wait,
                monitor_duration,
                bool(getattr(args, 'headless', False)),
                local_output_dir,
            )),
            summary_builder=lambda ctx, result: capture_local_execution_summary(
                ctx,
                watch_url,
                profile,
                result.get('login_result'),
                result.get('profile_result'),
                result.get('video_result'),
            ),
            metadata_builder=lambda result: {
                'mode': 'local_debug',
                'url': watch_url,
                'profile': profile,
                'login_result': result.get('login_result'),
                'profile_result': result.get('profile_result'),
                'video_result': result.get('video_result'),
                'headless': bool(getattr(args, 'headless', False)),
                'trace_path': result.get('trace_path', ''),
                'test_video_path': result.get('test_video_path', ''),
                'screenshot_count': len(result.get('screenshot_paths', [])),
            },
            exception_metadata_builder=lambda exc: {
                'mode': 'local_debug',
                'url': watch_url,
                'profile': profile,
                'headless': bool(getattr(args, 'headless', False)),
                'error': str(exc),
            },
            default_failure_message='Video playback not confirmed during monitoring window',
        )

    # Device/web-controller mode
    device = get_device()
    step_results = []
    from shared.src.lib.utils.device_utils import capture_screenshot_for_script

    def capture_step_screenshot(screenshot_id: str) -> str:
        captured_id = capture_screenshot_for_script(device, context, screenshot_id)
        if captured_id and context.screenshot_paths:
            return context.screenshot_paths[-1]
        return ''

    def add_step(message: str, success: bool, actions=None, verifications=None, screenshot_path: str = ''):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node='netflix_video_check',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
        )

    web = device._get_controller('web')
    if not web:
        add_step(
            'Launch browser session',
            False,
            actions=[{'command': 'web.open_browser', 'params': {'only_if_disconnected': True}}],
            verifications=[{
                'success': False,
                'label': 'Browser available',
                'details': {'error': 'No web controller available on this device'},
            }],
        )
        context.overall_success = False
        context.error_message = 'No web controller available on this device'
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, watch_url, profile)
        return False

    browser_session = ensure_browser_session(
        web,
        add_step=add_step,
        open_command='web.open_browser',
    )
    if not browser_session.get('success'):
        context.overall_success = False
        context.error_message = f"Failed to open browser: {browser_session.get('error')}"
        context.step_results = step_results
        context.metadata = {
            'mode': 'device_web_controller',
            'target_url': watch_url,
            'profile': profile,
        }
        context.execution_summary = capture_execution_summary(context, watch_url, profile)
        return False

    # Login page
    nav_login = asyncio.run(web.navigate_to_url(login_url))
    if not nav_login.get('success'):
        add_step(
            'Login to Netflix',
            False,
            actions=[{'command': 'web.navigate_to_url', 'params': {'url': login_url}}],
            verifications=[{
                'success': False,
                'label': 'Logged in',
                'details': {'error': nav_login.get('error', 'Unknown')},
            }],
        )
        context.overall_success = False
        context.error_message = f"Failed to navigate to login page: {nav_login.get('error', 'Unknown')}"
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, watch_url, profile)
        return False

    time.sleep(2)
    asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))
    time.sleep(1)
    asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))

    # Submit login
    login_submit = asyncio.run(web.execute_javascript(_build_js_login(email, password)))
    submitted = bool((login_submit.get('result') or {}).get('submitted')) if login_submit.get('success') else False

    time.sleep(max(1, post_login_wait))
    asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))
    login_state_resp = asyncio.run(web.execute_javascript(_JS_WAIT_FOR_LOGIN_RESULT))
    login_state = login_state_resp.get('result', {}) if login_state_resp.get('success') else {}
    logged_in = bool(login_state.get('onBrowse') or login_state.get('profileGate'))

    login_result = {
        'submitted': submitted,
        'logged_in': logged_in,
        'state': login_state,
        'error': '' if logged_in else (login_state.get('errorText') or 'Login did not reach browse/profile screen'),
    }
    login_shot = capture_step_screenshot('netflix_after_login')
    add_step(
        'Login to Netflix',
        logged_in,
        actions=[{'command': 'web.execute_javascript', 'params': {'script': '_build_js_login(email,password)'}}],
        verifications=[{
            'success': logged_in,
            'label': 'Logged in',
            'details': {'submitted': submitted},
        }],
        screenshot_path=login_shot,
    )

    if not logged_in:
        context.overall_success = False
        context.error_message = login_result['error']
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, watch_url, profile, login_result)
        return False

    # Profile
    profile_gate = bool(login_state.get('profileGate'))
    profile_result = {'selected': True, 'profile_gate_visible': profile_gate, 'error': '', 'available': []}
    if profile_gate:
        asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))
        picked_resp = asyncio.run(web.execute_javascript(_build_js_select_profile(profile)))
        picked = picked_resp.get('result', {}) if picked_resp.get('success') else {}
        selected = bool(picked.get('selected'))
        profile_result = {
            'selected': selected,
            'profile_gate_visible': True,
            'error': '' if selected else f"Profile '{profile}' not found in profile gate",
            'available': picked.get('available', []),
        }
        if selected:
            time.sleep(3)

    profile_shot = capture_step_screenshot('netflix_after_profile')
    add_step(
        'Select profile',
        bool(profile_result['selected']),
        actions=[{'command': 'web.execute_javascript', 'params': {'script': '_build_js_select_profile(profile)'}}],
        verifications=[{
            'success': bool(profile_result['selected']),
            'label': 'Profile selected',
            'details': {'profile_gate_visible': profile_gate, 'available': profile_result.get('available', [])},
        }],
        screenshot_path=profile_shot,
    )

    if not profile_result['selected']:
        context.overall_success = False
        context.error_message = profile_result['error']
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, watch_url, profile, login_result, profile_result)
        return False

    # Open video
    nav_video = asyncio.run(web.navigate_to_url(watch_url))
    if not nav_video.get('success'):
        add_step(
            'Open target video',
            False,
            actions=[{'command': 'web.navigate_to_url', 'params': {'url': watch_url}}],
            verifications=[{
                'success': False,
                'label': 'Watch page opened',
                'details': {'error': nav_video.get('error', 'Unknown')},
            }],
        )
        context.overall_success = False
        context.error_message = f"Failed to navigate to watch URL: {nav_video.get('error', 'Unknown')}"
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, watch_url, profile, login_result, profile_result)
        return False

    time.sleep(4)
    asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))
    time.sleep(1)
    asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))
    asyncio.run(web.execute_javascript(_JS_CLICK_GENERIC_PLAY))
    asyncio.run(web.execute_javascript(_JS_FORCE_PLAY))
    open_video_shot = capture_step_screenshot('netflix_video_opened')
    add_step(
        'Open target video',
        True,
        actions=[{'command': 'web.navigate_to_url', 'params': {'url': watch_url}}],
        screenshot_path=open_video_shot,
    )

    drm_resp = asyncio.run(web.execute_javascript(_JS_DETECT_DRM_BLOCK))
    drm = drm_resp.get('result', {}) if drm_resp.get('success') else {}
    if drm.get('blocked'):
        video_result = {
            'success': False,
            'playing': False,
            'samples': [],
            'progress_seconds': 0,
            'drm_blocked': True,
            'error': 'DRM/protected-content block detected (M7701-1003)',
        }
        monitor_shot = capture_step_screenshot('netflix_monitor_end')
        add_step(
            'Monitor playback progression',
            False,
            verifications=[{'success': False, 'label': 'DRM block detected', 'details': drm}],
            screenshot_path=monitor_shot,
        )
        context.overall_success = False
        context.error_message = video_result['error']
        context.metadata = {
            'url': watch_url,
            'profile': profile,
            'login_result': login_result,
            'profile_result': profile_result,
            'video_result': video_result,
        }
        context.step_results = step_results
        context.execution_summary = capture_execution_summary(context, watch_url, profile, login_result, profile_result, video_result)
        return False

    # Monitor playback
    samples = []
    playing = False
    elapsed = 0
    interval = 5
    while elapsed < monitor_duration:
        status = asyncio.run(web.execute_javascript(_JS_VIDEO_STATUS))
        if status.get('success') and status.get('result', {}).get('found'):
            sample = status.get('result', {})
            sample['elapsed'] = elapsed
            samples.append(sample)
            cur = sample.get('currentTime', 0)
            paused = sample.get('paused', True)
            if not paused and cur > 0:
                playing = True
            else:
                asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))
                asyncio.run(web.execute_javascript(_JS_FORCE_PLAY))
        else:
            asyncio.run(web.execute_javascript(_JS_DISMISS_COOKIE_BANNER))
            asyncio.run(web.execute_javascript(_JS_CLICK_GENERIC_PLAY))
            asyncio.run(web.execute_javascript(_JS_FORCE_PLAY))

        time.sleep(interval)
        elapsed += interval

    progress, progressing = calc_playback_progress(samples)
    playing = bool(playing or progressing)

    video_result = {
        'success': playing,
        'playing': playing,
        'samples': samples,
        'progress_seconds': progress,
        'drm_blocked': False,
        'error': None if playing else 'Video playback not confirmed during monitoring window',
    }
    monitor_shot = capture_step_screenshot('netflix_monitor_end')
    add_step(
        'Monitor playback progression',
        bool(playing),
        actions=[{'command': 'web.execute_javascript', 'params': {'script': '_JS_VIDEO_STATUS'}}],
        verifications=[{
            'success': bool(playing),
            'label': 'Playback progressed',
            'details': {'progress_seconds': progress, 'sample_count': len(samples)},
        }],
        screenshot_path=monitor_shot,
    )

    context.overall_success = playing
    if not playing:
        context.error_message = video_result['error']

    context.metadata = {
        'url': watch_url,
        'profile': profile,
        'login_result': {
            'submitted': login_result.get('submitted'),
            'logged_in': login_result.get('logged_in'),
            'error': login_result.get('error', ''),
        },
        'profile_result': profile_result,
        'video_result': {
            'playing': playing,
            'progress_seconds': progress,
            'sample_count': len(samples),
            'drm_blocked': False,
        },
    }
    context.step_results = step_results
    context.execution_summary = capture_execution_summary(context, watch_url, profile, login_result, profile_result, video_result)
    return playing


main._script_args = _script_args


def _run_local_debug_cli():
    def _run_local_from_args(args, output_dir):
        email = (args.email or "").strip()
        password = (args.password or "").strip()
        profile = (args.profile or "").strip()
        if not email:
            return {"success": False, "error": "Missing required --email"}
        if not password:
            return {"success": False, "error": "Missing required --password"}
        if not profile:
            return {"success": False, "error": "Missing required --profile"}

        return asyncio.run(_run_local_playwright_flow(
            email,
            password,
            profile,
            args.url,
            args.login_url,
            int(args.post_login_wait),
            int(args.monitor_duration),
            bool(args.headless),
            output_dir,
        ))

    def _summary(args, result, success, error):
        context = type("LocalContext", (), {"overall_success": success, "error_message": error, "get_execution_time_ms": lambda self: 0})()
        return capture_local_execution_summary(
            context,
            args.url,
            (args.profile or "").strip(),
            result.get("login_result"),
            result.get("profile_result"),
            result.get("video_result"),
        )

    run_local_debug_cli(
        argv=sys.argv,
        script_name="netflix_video_check",
        project_root=project_root,
        arg_specs=[
            {"name": "--email", "kwargs": {"type": str, "default": ""}},
            {"name": "--password", "kwargs": {"type": str, "default": ""}},
            {"name": "--profile", "kwargs": {"type": str, "default": "Kids"}},
            {"name": "--url", "kwargs": {"type": str, "default": "https://www.netflix.com/watch/81450642"}},
            {"name": "--login_url", "kwargs": {"type": str, "default": "https://www.netflix.com/login"}},
            {"name": "--post_login_wait", "kwargs": {"type": int, "default": 8}},
            {"name": "--monitor_duration", "kwargs": {"type": int, "default": 30}},
            {"name": "--headless", "kwargs": {"type": str_to_bool, "default": False}},
        ],
        run_local=_run_local_from_args,
        summary_builder=_summary,
        default_failure_message="Video playback not confirmed during monitoring window",
    )


main._script_args = _script_args
main._target_rules = {
    "target_type": "host",
    "host_os": "all",
    "device_model": "all",
}


if __name__ == '__main__':
    if cli_local_debug_enabled(sys.argv):
        _run_local_debug_cli()
    main()
