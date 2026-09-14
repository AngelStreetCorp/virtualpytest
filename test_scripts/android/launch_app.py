#!/usr/bin/env python3
"""
Android Launch App — ADB smoke test for VirtualPyTest

Launches an Android app by name, dismisses any system dialogs, and verifies
that the app UI is visible via ADB element dump.

Usage:
    python test_scripts/android/launch_app.py
    python test_scripts/android/launch_app.py --app clock
    python test_scripts/android/launch_app.py --app settings --device device1
"""

import sys
import os
import time
from datetime import datetime, timezone

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device
from shared.src.lib.utils.device_utils import capture_screenshot_for_script

# ── App catalog ──────────────────────────────────────────────────────────
# Each entry: display_name, package, verify_texts (any match = app confirmed)
APP_CATALOG = {
    "settings": {
        "display_name": "Settings",
        "package": "com.android.settings",
        "verify_texts": ["Settings", "Search settings", "Network", "Battery"],
    },
    "clock": {
        "display_name": "Clock",
        "package": "com.google.android.deskclock",
        "verify_texts": ["Clock", "Alarm", "Timer", "Stopwatch", "Bedtime"],
    },
    "contacts": {
        "display_name": "Contacts",
        "package": "com.google.android.contacts",
        "verify_texts": ["Contacts", "contact"],
    },
    "chrome": {
        "display_name": "Chrome",
        "package": "com.android.chrome",
        "verify_texts": ["Chrome", "Search or type URL", "Search or type web address"],
    },
    "dialer": {
        "display_name": "Phone",
        "package": "com.google.android.dialer",
        "verify_texts": ["Phone", "Recents", "Contacts", "Favorites"],
    },
    "messages": {
        "display_name": "Messages",
        "package": "com.google.android.apps.messaging",
        "verify_texts": ["Messages", "Start chat", "Conversations"],
    },
}

SCRIPT_TAG = "launch_app"


def dismiss_system_dialogs(remote):
    """Dismiss ANR / crash / 'not responding' dialogs via ADB broadcast."""
    if not hasattr(remote, 'adb_utils'):
        return
    adb = remote.adb_utils
    device_id = getattr(remote, 'android_device_id', None)
    if not adb or not device_id:
        return
    adb.execute_command(
        f"adb -s {device_id} shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS"
    )
    time.sleep(1)


def verify_app_visible(elements, app_info):
    """Check if any element text matches the app's verify_texts."""
    verify_texts = app_info["verify_texts"]
    package = app_info["package"]
    for el in elements:
        text = getattr(el, 'text', '') or ''
        resource_id = getattr(el, 'resource_id', '') or ''
        if package in resource_id:
            return True
        for vt in verify_texts:
            if vt in text:
                return True
    return False


@script("launch_app", "Launch an Android app and verify it is displayed", default_device="device1")
def main():
    context = get_context()
    args = get_args()
    device = get_device()

    # Resolve app from --app argument
    app_key = getattr(args, 'app', 'settings').lower()
    if app_key not in APP_CATALOG:
        available = ", ".join(sorted(APP_CATALOG.keys()))
        print(f"❌ [{SCRIPT_TAG}] Unknown app '{app_key}'. Available: {available}")
        context.execution_summary = f"FAIL: Unknown app '{app_key}'"
        return False

    app_info = APP_CATALOG[app_key]
    app_name = app_info["display_name"]
    package = app_info["package"]

    remote = device._get_controller('remote')
    if not remote:
        print(f"❌ [{SCRIPT_TAG}] No remote controller available")
        context.execution_summary = "FAIL: No remote controller"
        return False

    # ── Step 1: Launch app ───────────────────────────────────────────────
    step1_start = time.time()
    step1_ts = datetime.now(timezone.utc).strftime('%H:%M:%S')

    print(f"[{SCRIPT_TAG}] Step 1: Launching {app_name} ({package})...")
    launch_ok = remote.launch_app(package)
    time.sleep(2)

    # Dismiss any ANR / crash dialogs
    dismiss_system_dialogs(remote)

    # Screenshot after launch
    capture_screenshot_for_script(device, context, "step_1_launch")
    step1_screenshot = context.screenshot_paths[-1] if context.screenshot_paths else None

    step1_end_ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    step1_ms = int((time.time() - step1_start) * 1000)

    context.record_step_immediately({
        'description': f'Launch {app_name}',
        'success': launch_ok,
        'step_category': 'script',
        'screenshot_path': step1_screenshot,
        'step_end_screenshot_path': step1_screenshot,
        'execution_time_ms': step1_ms,
        'start_time': step1_ts,
        'end_time': step1_end_ts,
        'actions': [{'command': 'launch_app', 'params': {'package': package}}],
        'message': f"Launched {package}" if launch_ok else f"Failed to launch {package}",
    })

    if not launch_ok:
        print(f"❌ [{SCRIPT_TAG}] Failed to launch {app_name}")
        context.execution_summary = f"FAIL: Could not launch {app_name}"
        return False

    print(f"✅ [{SCRIPT_TAG}] Step 1 passed: {app_name} launched")

    # ── Step 2: Verify app is displayed ──────────────────────────────────
    step2_start = time.time()
    step2_ts = datetime.now(timezone.utc).strftime('%H:%M:%S')

    print(f"[{SCRIPT_TAG}] Step 2: Verifying {app_name} UI...")

    # Dismiss any lingering dialogs
    dismiss_system_dialogs(remote)

    # Dump UI elements
    verification = device._get_controller('verification')
    if verification and hasattr(verification, 'dump_elements'):
        success, elements, error = verification.dump_elements()
    elif hasattr(remote, 'dump_elements'):
        success, elements, error = remote.dump_elements()
    else:
        # TV remote — no UI dump, just verify launch succeeded
        success, elements, error = True, [], ""

    if not success:
        print(f"❌ [{SCRIPT_TAG}] Failed to dump UI elements: {error}")
        capture_screenshot_for_script(device, context, "step_2_fail")
        step2_screenshot = context.screenshot_paths[-1] if context.screenshot_paths else None

        step2_end_ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        step2_ms = int((time.time() - step2_start) * 1000)
        context.record_step_immediately({
            'description': f'Verify {app_name} UI',
            'success': False,
            'step_category': 'script',
            'screenshot_path': step2_screenshot,
            'step_end_screenshot_path': step2_screenshot,
            'execution_time_ms': step2_ms,
            'start_time': step2_ts,
            'end_time': step2_end_ts,
            'actions': [{'command': 'dump_elements'}],
            'message': f"dump_elements error: {error}",
        })
        context.execution_summary = f"FAIL: dump_elements error: {error}"
        return False

    # Verify app content
    element_count = len(elements)
    app_confirmed = verify_app_visible(elements, app_info) if elements else False

    # Screenshot of verified state
    capture_screenshot_for_script(device, context, "step_2_verify")
    step2_screenshot = context.screenshot_paths[-1] if context.screenshot_paths else None

    step2_end_ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    step2_ms = int((time.time() - step2_start) * 1000)

    if element_count == 0 and not app_confirmed:
        step2_ok = True
        step2_msg = f"{app_name} launched (no UI dump available on this device type)"
    elif element_count > 0 and app_confirmed:
        step2_ok = True
        step2_msg = f"Found {element_count} UI elements, {app_name} content confirmed"
    elif element_count > 0 and not app_confirmed:
        step2_ok = False
        step2_msg = f"Found {element_count} UI elements but {app_name} content NOT found (possible overlay)"
    else:
        step2_ok = False
        step2_msg = "No UI elements found — ADB dump returned empty"

    context.record_step_immediately({
        'description': f'Verify {app_name} UI',
        'success': step2_ok,
        'step_category': 'script',
        'screenshot_path': step2_screenshot,
        'step_end_screenshot_path': step2_screenshot,
        'execution_time_ms': step2_ms,
        'start_time': step2_ts,
        'end_time': step2_end_ts,
        'actions': [{'command': 'dump_elements', 'result': {'element_count': element_count, 'app_confirmed': app_confirmed}}],
        'message': step2_msg,
    })

    if step2_ok:
        print(f"✅ [{SCRIPT_TAG}] Step 2 passed: {step2_msg}")
        context.execution_summary = f"PASS: {step2_msg}"
        return True
    else:
        print(f"❌ [{SCRIPT_TAG}] Step 2 failed: {step2_msg}")
        context.execution_summary = f"FAIL: {step2_msg}"
        return False


main._script_args = ['--app:str:settings']
main._script_description = "Launch an Android app and verify it displays."
main._arg_descriptions = {
    'app': 'App key from catalog (e.g. settings)',
}

main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "runner_android_mobile|runner_android_tablet|runner_android_tv",
}

if __name__ == "__main__":
    main()
