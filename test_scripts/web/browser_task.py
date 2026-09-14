#!/usr/bin/env python3
"""
Browser Task Execution Script for VirtualPyTest

This script navigates to a URL using device.action, waits 10 seconds, 
then executes a browser-use AI task.

Usage:
    python test_scripts/web/browser_task.py --url <url> --task <task_description>
    
Examples:
    python test_scripts/web/browser_task.py --url "google.com" --task "Search for Python tutorials"
    python test_scripts/web/browser_task.py --url "https://youtube.com" --task "Find a video about cats"
    python test_scripts/web/browser_task.py --url "amazon.com" --task "Search for wireless headphones and show me the top 3 results"
"""

import sys
import os
import time
import asyncio
import shutil
import argparse
import logging
import io
import builtins
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
    stop_local_debug_cdp_process,
)
from shared.src.lib.utils.local_debug_playwright_js import (
    YOUTUBE_JS_CHECK_CONSENT_MODAL as _JS_CHECK_CONSENT_MODAL,
    YOUTUBE_JS_DISMISS_CONSENT_MODAL as _JS_DISMISS_CONSENT_MODAL,
)

sys.argv = normalize_local_debug_flag(sys.argv)

# Script arguments
# MUST be defined near top of file (within first 300 lines) for script analyzer
_script_args = [
    '--url:str:youtube.com',                    # URL to navigate to
    '--task:str:Launch funny cat video',  # Browser-use task description
    '--max_steps:int:10',                      # Maximum steps for browser-use (default: 20)
    '--wait_seconds:int:10',                   # Wait time before task execution
    '--openrouter_api_key:str:',               # Optional OpenRouter API key for --local-debug browser-use
]
_script_description = "Navigate to a URL and run an AI browser task."
_arg_descriptions = {
    'url': 'URL to navigate to',
    'task': 'AI task description to execute',
    'max_steps': 'Max steps for browser-use agent',
    'wait_seconds': 'Wait before task execution',
    'openrouter_api_key': 'OpenRouter API key for local debug',
}


def capture_execution_summary(context, url: str, task: str, max_steps: int, nav_result: Dict[str, Any] = None, 
                             task_result: Dict[str, Any] = None) -> str:
    """Capture execution summary as text for report"""
    lines = []
    lines.append(f"🎯 [BROWSER_TASK] EXECUTION SUMMARY")
    lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    lines.append(f"🖥️ Host: {context.host.host_name}")
    lines.append(f"")
    
    # Navigation section
    lines.append(f"🌐 NAVIGATION")
    lines.append(f"   URL: {url}")
    if nav_result:
        nav_success = nav_result.get('success', False)
        nav_time = nav_result.get('execution_time', 0)
        lines.append(f"   Status: {'✅ SUCCESS' if nav_success else '❌ FAILED'}")
        lines.append(f"   Time: {nav_time}ms")
        if nav_success:
            final_url = nav_result.get('url', url)
            final_title = nav_result.get('title', 'Unknown')
            lines.append(f"   Final URL: {final_url}")
            lines.append(f"   Page Title: {final_title}")
        else:
            error = nav_result.get('error', 'Unknown error')
            lines.append(f"   Error: {error}")
    
    lines.append(f"")
    lines.append(f"⏳ WAIT: 10 seconds")
    lines.append(f"")
    
    # Browser-use task section
    lines.append(f"🤖 BROWSER-USE AI TASK")
    lines.append(f"   Task: {task}")
    lines.append(f"   Max Steps: {max_steps}")
    if task_result:
        task_success = task_result.get('success', False)
        task_time = task_result.get('execution_time', 0)
        lines.append(f"   Status: {'✅ SUCCESS' if task_success else '❌ FAILED'}")
        lines.append(f"   Time: {task_time}ms ({task_time/1000:.1f}s)")
        
        if task_success:
            result_summary = task_result.get('result_summary', 'Task completed')
            lines.append(f"   Result: {result_summary}")
            
            # Add execution logs if available (truncated)
            execution_logs = task_result.get('execution_logs', '')
            if execution_logs:
                log_lines = execution_logs.split('\n')
                lines.append(f"   Logs: {len(log_lines)} lines of execution logs")
                # Show first and last few lines
                if len(log_lines) > 10:
                    lines.append(f"")
                    lines.append(f"   📋 First 5 log lines:")
                    for log_line in log_lines[:5]:
                        if log_line.strip():
                            lines.append(f"      {log_line[:100]}")
                    lines.append(f"   ...")
                    lines.append(f"   📋 Last 5 log lines:")
                    for log_line in log_lines[-5:]:
                        if log_line.strip():
                            lines.append(f"      {log_line[:100]}")
        else:
            error = task_result.get('error', 'Unknown error')
            lines.append(f"   Error: {error}")
    
    lines.append(f"")
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
    lines.append(f"")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    
    return "\n".join(lines)


def capture_local_execution_summary(
    context,
    url: str,
    task: str,
    max_steps: int,
    nav_result: Optional[Dict[str, Any]] = None,
    task_result: Optional[Dict[str, Any]] = None,
) -> str:
    """Local-debug summary without host/device references."""
    lines = []
    lines.append("🎯 [BROWSER_TASK] LOCAL DEBUG SUMMARY")
    lines.append("🖥️  Mode: local-debug (Playwright on host)")
    lines.append(f"🔗 URL: {url}")
    lines.append(f"📝 Task: {task}")
    lines.append(f"🔢 Max Steps: {max_steps}")
    lines.append("")
    if nav_result:
        lines.append(f"🌐 Navigation: {'OK' if nav_result.get('success') else 'FAILED'}")
        lines.append(f"   Final URL: {nav_result.get('url', '')}")
        lines.append(f"   Title: {nav_result.get('title', '')}")
    if task_result:
        lines.append(f"🤖 Task Result: {'OK' if task_result.get('success') else 'FAILED'}")
        lines.append(f"   Summary: {task_result.get('result_summary', '')}")
    lines.append("")
    lines.append(f"📸 Screenshots: {len(context.screenshot_paths)}")
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    return "\n".join(lines)


async def _run_local_browser_use_task(page, task: str, max_steps: int, openrouter_api_key: str = "") -> Dict[str, Any]:
    """Execute browser-use task directly on existing Playwright page."""
    start_time = time.time()
    execution_logs = []

    api_key = (openrouter_api_key or '').strip() or os.getenv('OPENROUTER_API_KEY')
    if not api_key:
        return {
            'success': False,
            'error': 'OPENROUTER_API_KEY is not set',
            'execution_time': 0,
            'result_summary': '',
            'execution_logs': '',
        }

    try:
        from browser_use import Agent
        from browser_use.llm import ChatOpenAI
        from browser_use.browser.profile import BrowserProfile
    except Exception as e:
        return {
            'success': False,
            'error': f'Browser-use not available: {e}',
            'execution_time': 0,
            'result_summary': '',
            'execution_logs': '',
        }

    log_capture_string = io.StringIO()
    log_handler = logging.StreamHandler(log_capture_string)
    log_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    browser_use_logger = logging.getLogger('browser_use')
    original_handlers = root_logger.handlers[:]
    browser_use_original_handlers = browser_use_logger.handlers[:]

    root_logger.addHandler(log_handler)
    browser_use_logger.addHandler(log_handler)

    original_print = print

    def capture_print(*args, **kwargs):
        original_print(*args, **kwargs)
        if args:
            execution_logs.append(' '.join(str(arg) for arg in args))

    builtins.print = capture_print
    try:
        current_viewport = await page.evaluate("""() => ({
            width: window.innerWidth,
            height: window.innerHeight
        })""")

        browser_profile = BrowserProfile(
            viewport=current_viewport,
            no_viewport=False
        )

        llm = ChatOpenAI(
            model='o4-mini',
            api_key=api_key,
            base_url='https://openrouter.ai/api/v1',
            temperature=1.0
        )

        agent = Agent(
            task=task,
            llm=llm,
            page=page,
            browser_profile=browser_profile,
            use_vision=True,
            max_failures=5,
            retry_delay=2
        )
        await agent.run(max_steps=max_steps)

        captured_logs = log_capture_string.getvalue()
        all_logs = execution_logs + [captured_logs] if captured_logs else execution_logs
        return {
            'success': True,
            'error': '',
            'execution_time': int((time.time() - start_time) * 1000),
            'result_summary': 'Task completed',
            'execution_logs': '\n'.join(all_logs)
        }
    except Exception as e:
        captured_logs = log_capture_string.getvalue()
        all_logs = execution_logs + [captured_logs] if captured_logs else execution_logs
        return {
            'success': False,
            'error': str(e),
            'execution_time': int((time.time() - start_time) * 1000),
            'result_summary': '',
            'execution_logs': '\n'.join(all_logs)
        }
    finally:
        builtins.print = original_print
        root_logger.handlers = original_handlers
        browser_use_logger.handlers = browser_use_original_handlers


async def _run_local_playwright_browser_task(
    url: str,
    task: str,
    max_steps: int,
    wait_seconds: int,
    openrouter_api_key: str = "",
    output_dir: str = "",
) -> Dict[str, Any]:
    """Playwright-only local debug flow for browser_task."""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"

    output_dir = output_dir or os.path.join(project_root, "tmp", "local_debug", "browser_task", f"adhoc_{int(time.time())}")
    os.makedirs(output_dir, exist_ok=True)
    screenshots_dir = os.path.join(output_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    step_results = []
    screenshot_paths = []
    trace_path = os.path.join(output_dir, "trace.zip")
    test_video_path = ""

    def add_step(message: str, success: bool, actions=None, verifications=None, screenshot_path: str = ""):
        append_local_debug_step_result(
            step_results=step_results,
            message=message,
            success=success,
            from_node='local-debug',
            actions=actions,
            verifications=verifications,
            screenshot_path=screenshot_path,
            step_duration_ms=0,
        )

    async def shot(page, name: str) -> str:
        path = os.path.join(screenshots_dir, f"{len(screenshot_paths) + 1:02d}_{name}.png")
        print(f"[PW] page.screenshot(path='{path}', full_page=True)")
        return await capture_local_debug_screenshot(
            page=page,
            screenshots_dir=screenshots_dir,
            screenshot_paths=screenshot_paths,
            name=name,
        )

    nav_result = {'success': False}
    task_result = {'success': False}
    overall_success = False
    final_error = ''

    async with local_debug_playwright_session(
        profile_name="browser_task",
        debug_port=9222,
        viewport={'width': 1366, 'height': 768},
        record_video_dir=output_dir,
    ) as session:
        launched_process = session["launched_process"]
        context = session["context"]
        page = session["page"]
        append_local_debug_browser_launch_step(
            step_results=step_results,
            from_node='local-debug',
            session=session,
        )

        print("[PW] context.tracing.start(screenshots=True, snapshots=True, sources=True)")
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page.set_default_timeout(30000)

        print(f"[PW] page.goto('{url}', wait_until='domcontentloaded')")
        await page.goto(url, wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)

        if "youtube.com" in page.url:
            print("[PW] page.evaluate(_JS_CHECK_CONSENT_MODAL)")
            modal_selector = await page.evaluate(_JS_CHECK_CONSENT_MODAL)
            modal_found = bool(modal_selector)
            print(f"[PW] consent modal detected={modal_found} selector={modal_selector}")
            if modal_found:
                print("[PW] page.evaluate(_JS_DISMISS_CONSENT_MODAL)")
                dismiss_result = await page.evaluate(_JS_DISMISS_CONSENT_MODAL)
                print(f"[PW] consent dismiss result={dismiss_result}")
                await page.wait_for_timeout(1500)
                modal_after = await page.evaluate(_JS_CHECK_CONSENT_MODAL)
                consent_shot = await shot(page, "after_consent_dismiss")
                add_step(
                    "Dismiss YouTube consent modal",
                    not bool(modal_after),
                    actions=[{'command': 'page.evaluate', 'params': {'script': '_JS_DISMISS_CONSENT_MODAL'}, 'label': 'Dismiss consent'}],
                    verifications=[{'success': not bool(modal_after), 'label': 'Consent modal closed', 'details': {'selector_after': modal_after}}],
                    screenshot_path=consent_shot,
                )

        nav_shot = await shot(page, "after_navigation")
        nav_result = {
            'success': True,
            'url': page.url,
            'title': await page.title(),
            'execution_time': 0,
        }
        add_step(
            "Navigate to target URL",
            True,
            actions=[{'command': 'page.goto', 'params': {'url': url, 'wait_until': 'domcontentloaded'}, 'label': 'Navigate URL'}],
            verifications=[{'success': True, 'label': 'Navigation succeeded', 'details': {'url': page.url}}],
            screenshot_path=nav_shot,
        )

        print(f"[PW] page.wait_for_timeout({wait_seconds * 1000})")
        await page.wait_for_timeout(wait_seconds * 1000)
        wait_shot = await shot(page, "after_wait")
        add_step(
            f"Wait {wait_seconds}s before task",
            True,
            actions=[{'command': 'page.wait_for_timeout', 'params': {'ms': wait_seconds * 1000}, 'label': 'Wait'}],
            screenshot_path=wait_shot,
        )

        # Local-debug: execute the real browser-use task to mirror controller flow.
        task_with_context = f"You are on website {page.url}\n\nExecute task: {task}"
        print(f"[PW] browser-use Agent.run(max_steps={max_steps})")
        task_result = await _run_local_browser_use_task(page, task_with_context, max_steps, openrouter_api_key=openrouter_api_key)
        task_shot = await shot(page, "after_task_execution")
        add_step(
            "Execute browser-use task",
            bool(task_result.get('success')),
            actions=[{'command': 'browser_use.Agent.run', 'params': {'task': task_with_context, 'max_steps': max_steps}, 'label': 'Browser-use task'}],
            verifications=[{
                'success': bool(task_result.get('success')),
                'label': 'Task execution succeeded',
                'details': {
                    'execution_time': task_result.get('execution_time', 0),
                    'error': task_result.get('error', '')
                }
            }],
            screenshot_path=task_shot,
        )
        if not task_result.get('success'):
            final_error = f"Browser-use task failed: {task_result.get('error', 'Unknown error')}"
            overall_success = False
        else:
            overall_success = True

        print(f"[PW] context.tracing.stop(path='{trace_path}')")
        await context.tracing.stop(path=trace_path)
        await context.close()
        if page.video:
            raw_video_path = await page.video.path()
            if raw_video_path and os.path.exists(raw_video_path):
                final_video_path = os.path.join(output_dir, 'test_execution.webm')
                shutil.move(raw_video_path, final_video_path)
                test_video_path = final_video_path
        # CDP session owns the browser process; tearing down the launched
        # process (below) is the only cleanup needed — there is no Playwright
        # `browser` object here (connection is via launched_process/context/page).
        stop_local_debug_cdp_process(launched_process)

    return {
        'success': overall_success,
        'error': final_error,
        'nav_result': nav_result,
        'task_result': task_result,
        'step_results': step_results,
        'screenshot_paths': screenshot_paths,
        'trace_path': trace_path if os.path.exists(trace_path) else "",
        'test_video_path': test_video_path,
        'normalized_url': url,
    }


def _run_local_debug_cli():
    parser = argparse.ArgumentParser(description="browser_task local-debug mode")
    parser.add_argument("--url", type=str, default="youtube.com")
    parser.add_argument("--task", type=str, default="Launch funny cat video")
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--wait_seconds", type=int, default=10)
    parser.add_argument("--openrouter_api_key", type=str, default="")
    parser.add_argument("--local-debug", "--local_debug", dest="local_debug", default=True)
    args, _ = parser.parse_known_args()

    result = asyncio.run(_run_local_playwright_browser_task(
        url=args.url,
        task=args.task,
        max_steps=int(args.max_steps),
        wait_seconds=int(args.wait_seconds),
        openrouter_api_key=(args.openrouter_api_key or "").strip(),
        output_dir="",
    ))
    success = bool(result.get("success"))
    error = result.get("error") or ""
    print("BROWSER_TASK SUMMARY")
    print(f"URL: {result.get('normalized_url', args.url)}")
    print(f"Result: {'SUCCESS' if success else 'FAILED'}")
    if error:
        print(f"Error: {error}")
    print(f"SCRIPT_SUCCESS:{str(success).lower()}")
    sys.exit(0)


@script("browser_task", "Navigate to URL and execute browser-use task")
def main():
    """Main function: navigate to URL, wait, and execute browser-use task"""
    args = get_args()
    context = get_context()
    
    url = args.url
    task = args.task
    max_steps = args.max_steps
    wait_seconds = args.wait_seconds
    openrouter_api_key = (args.openrouter_api_key or '').strip()

    if getattr(args, 'local_debug', False):
        print(f"🧪 [browser_task] Running local Playwright-only mode")
        print(f"🖥️  [browser_task] wait_seconds={wait_seconds}")
        local_output_dir = (context.custom_data or {}).get('local_output_dir', '')
        try:
            result = asyncio.run(_run_local_playwright_browser_task(
                url=url,
                task=task,
                max_steps=max_steps,
                wait_seconds=wait_seconds,
                openrouter_api_key=openrouter_api_key,
                output_dir=local_output_dir,
            ))
        except Exception as e:
            context.overall_success = False
            context.error_message = str(e)
            context.metadata = {"mode": "local_debug", "url": url, "task": task, "error": str(e)}
            context.execution_summary = capture_local_execution_summary(context, url, task, max_steps)
            return False

        context.overall_success = bool(result.get('success'))
        context.error_message = result.get('error') or ''
        context.step_results = result.get('step_results', [])
        context.screenshot_paths = result.get('screenshot_paths', [])
        context.test_video_url = result.get('test_video_path', '')
        context.metadata = {
            "mode": "local_debug",
            "url": result.get('normalized_url', url),
            "task": task,
            "max_steps": max_steps,
            "openrouter_api_key_provided": bool(openrouter_api_key),
            "navigation_result": result.get('nav_result'),
            "task_result": result.get('task_result'),
            "trace_path": result.get('trace_path', ''),
            "test_video_path": result.get('test_video_path', ''),
            "screenshot_count": len(result.get('screenshot_paths', [])),
        }
        context.execution_summary = capture_local_execution_summary(
            context,
            result.get('normalized_url', url),
            task,
            max_steps,
            result.get('nav_result'),
            result.get('task_result'),
        )
        return context.overall_success

    device = get_device()
    
    print(f"🎯 [browser_task] URL: {url}")
    print(f"🎯 [browser_task] Task: {task}")
    print(f"🎯 [browser_task] Max Steps: {max_steps}")
    print(f"📱 [browser_task] Device: {device.device_name} ({device.device_model})")
    
    # Initialize results
    nav_result = None
    task_result = None
    
    # STEP 1: Get web controller to check browser status
    web_controller = device._get_controller('web')
    
    if not web_controller:
        context.error_message = "No web controller available on this device"
        context.overall_success = False
        summary_text = capture_execution_summary(context, url, task, max_steps, nav_result, task_result)
        context.execution_summary = summary_text
        return False
    
    # STEP 2: Ensure browser is open
    print(f"\n📋 [browser_task] ==========================================")
    print(f"📋 [browser_task] CHECKING BROWSER STATUS")
    print(f"📋 [browser_task] ==========================================\n")
    
    browser_session = ensure_browser_session(
        web_controller,
        open_command='web_controller.open_browser',
    )
    if not browser_session.get('success'):
        context.error_message = f"Failed to open browser: {browser_session.get('error')}"
        context.overall_success = False
        context.metadata = {
            'mode': 'device_web_controller',
            'target_url': url,
            'task': task,
        }
        summary_text = capture_execution_summary(context, url, task, max_steps, nav_result, task_result)
        context.execution_summary = summary_text
        return False
    if browser_session.get('opened_now'):
        print(f"✅ [browser_task] Browser opened successfully")
    else:
        print(f"✅ [browser_task] Browser already open")
    
    # STEP 3: Navigate to URL using web controller directly
    print(f"\n📋 [browser_task] ==========================================")
    print(f"📋 [browser_task] NAVIGATING TO URL")
    print(f"📋 [browser_task] ==========================================\n")
    
    print(f"🌐 [browser_task] Navigating to: {url}")
    # ✅ Wrap async call with asyncio.run for script context
    nav_result = asyncio.run(web_controller.navigate_to_url(url))
    
    if not nav_result.get('success'):
        context.error_message = f"Navigation failed: {nav_result.get('error', 'Unknown error')}"
        context.overall_success = False
        summary_text = capture_execution_summary(context, url, task, max_steps, nav_result, task_result)
        context.execution_summary = summary_text
        return False
    
    final_url = nav_result.get('url', url)
    page_title = nav_result.get('title', 'Unknown')
    print(f"✅ [browser_task] Navigation successful!")
    print(f"   Final URL: {final_url}")
    print(f"   Page Title: {page_title}")
    
    # STEP 4: Wait
    print(f"\n⏳ [browser_task] Waiting {wait_seconds} seconds before executing task...")
    time.sleep(wait_seconds)
    print(f"✅ [browser_task] Wait complete")
    
    # STEP 5: Execute browser-use task
    print(f"\n📋 [browser_task] ==========================================")
    print(f"📋 [browser_task] EXECUTING BROWSER-USE TASK")
    print(f"📋 [browser_task] ==========================================\n")
    
    # Add context to task
    task_with_context = f"You are on website {final_url}\n\nExecute task: {task}"
    
    print(f"🤖 [browser_task] Task: {task}")
    print(f"🤖 [browser_task] Context: You are on website {final_url}")
    print(f"🤖 [browser_task] Max Steps: {max_steps}")
    # ✅ Wrap async call with asyncio.run for script context
    task_result = asyncio.run(web_controller.browser_use_task(task_with_context, max_steps=max_steps))
    
    if not task_result.get('success'):
        print(f"❌ [browser_task] Task execution failed: {task_result.get('error', 'Unknown error')}")
        context.error_message = f"Browser-use task failed: {task_result.get('error', 'Unknown error')}"
        context.overall_success = False
        summary_text = capture_execution_summary(context, url, task, max_steps, nav_result, task_result)
        context.execution_summary = summary_text
        return False
    
    print(f"✅ [browser_task] Task execution complete!")
    print(f"   Result: {task_result.get('result_summary', 'Task completed')}")
    print(f"   Time: {task_result.get('execution_time', 0)}ms")
    
    # STEP 6: Set overall success and capture summary
    context.overall_success = True
    
    # Store task result in metadata for later analysis
    context.metadata = {
        "url": url,
        "task": task,
        "navigation_result": nav_result,
        "task_result": task_result,
        "final_url": final_url,
        "page_title": page_title
    }
    
    # Capture summary
    summary_text = capture_execution_summary(context, url, task, max_steps, nav_result, task_result)
    context.execution_summary = summary_text
    
    return True


# Assign script arguments to main function
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
