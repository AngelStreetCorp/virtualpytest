#!/usr/bin/env python3

"""
Device Utility Functions

Centralized utilities for common device operations to avoid code duplication.
"""

import os
import shutil
import time
from typing import Optional, Tuple

# Android device models that support ADB screenshots
_ADB_SCREENSHOT_MODELS = {'android_mobile', 'android_tablet', 'android_tv',
                          'runner_android_mobile', 'runner_android_tablet', 'runner_android_tv'}


def _run_page_screenshot_path(screenshot_id: str = None) -> str:
    """Where a run's own page screenshot is written (one directory per run)."""
    import tempfile

    run_id = (os.environ.get('VPT_RUN_ID') or '').strip() or f"pid{os.getpid()}"
    # Nanoseconds, not milliseconds: two screenshots of the same step in the same run must
    # not land on the same file.
    stem = f"{time.time_ns()}_{screenshot_id}" if screenshot_id else str(time.time_ns())
    return os.path.join(tempfile.gettempdir(), 'virtualpytest_run_shots', run_id, f"{stem}.png")


def _shared_display_capture(device) -> bool:
    """True when this device's screen capture photographs a display other runs share.

    A host's `host_vnc` capture is a live x11grab of `DISPLAY=:1` — the one screen every
    browser run on the host draws on. An HDMI capture belongs to the device alone.
    """
    try:
        av_controller = device._get_controller('av')
    except Exception:
        return False
    if av_controller is None:
        return False
    source = str(getattr(av_controller, 'capture_source', '') or '').lower()
    return 'vnc' in source or 'x11grab' in source


def _drives_its_own_browser(device) -> bool:
    """True when the run has a web controller, i.e. it is a browser run on this device."""
    try:
        return device._get_controller('web') is not None
    except Exception:
        return False


def capture_run_page_screenshot(device, screenshot_id: str = None) -> Optional[str]:
    """Screenshot the page THIS run drives, or None when it drives none.

    Every browser run on a host shares one X display (`DISPLAY=:1`) and therefore one
    screen capture: the host's capture folder holds one image of the whole screen, and
    `take_screenshot()` returns the newest of them. With two runs on the host the window
    on top is regularly the other run's browser, so the image in a report showed the
    wrong site (TASK-146). The page belongs to one run, so photograph it directly.

    Never raises. A device that is not a browser run keeps the screen capture, which is
    the right answer for it. Every miss says so on stdout, because a silent fallback is
    how the first version of this shipped while changing nothing: the report still showed
    the screen capture and nothing in the run log said why.
    """
    def _miss(reason: str) -> None:
        print(f"📸 [device_utils] No run page screenshot ({reason}) — falling back to the screen capture")

    try:
        web_controller = device._get_controller('web')
    except Exception as e:
        _miss(f"{type(e).__name__}: {e}")
        return None
    if web_controller is None:
        return None  # not a browser run: the screen capture is the right answer, not a fallback
    capture = getattr(web_controller, 'capture_page_screenshot', None)
    if not callable(capture):
        _miss(f"the web controller ({type(web_controller).__name__}) cannot photograph its page")
        return None
    path = _run_page_screenshot_path(screenshot_id)
    try:
        taken = capture(path)
        # The check has to be inside the try: an awaitable answer used to escape here as
        # `stat: path should be string ... not coroutine`, which the caller reported as a
        # capture failure instead of the miss it actually was.
        if not isinstance(taken, str):
            close = getattr(taken, 'close', None)
            if callable(close):
                close()  # do not leave a coroutine dangling for the run log to warn about
            _miss("the run has no live page to photograph")
            return None
        if not os.path.exists(taken):
            _miss(f"no image was written at {taken}")
            return None
    except Exception as e:
        _miss(f"{type(e).__name__}: {e}")
        return None
    return taken


def _try_adb_screenshot(device) -> Optional[str]:
    """
    ADB screenshot fallback for Android devices without AV controller.
    Only used for android_mobile, android_tablet, android_tv models (and runner_ variants).
    """
    try:
        device_model = getattr(device, 'device_model', '')
        if device_model not in _ADB_SCREENSHOT_MODELS:
            return None

        remote = device._get_controller('remote')
        if not remote or not hasattr(remote, 'adb_utils') or not remote.adb_utils:
            return None

        android_device_id = getattr(remote, 'android_device_id', None)
        if not android_device_id:
            return None

        success, file_path, error = remote.adb_utils.take_screenshot_to_file(android_device_id)
        if success:
            print(f"📸 [device_utils] ADB screenshot captured: {os.path.basename(file_path)}")
            return file_path
        else:
            print(f"⚠️ [device_utils] ADB screenshot failed: {error}")
            return None
    except Exception as e:
        print(f"⚠️ [device_utils] ADB screenshot error: {e}")
        return None


def capture_screenshot_for_script(device, context, screenshot_id: str = None) -> Optional[str]:
    """
    Capture screenshot, copy to COLD storage, add to context for batch upload.
    
    Simple flow:
    1. Take screenshot (HOT storage)
    2. Copy to COLD root (safe from archiver for 1 hour)
    3. Add to context with ID
    4. Return screenshot ID for report mapping
    
    Upload happens in batch at script end via context.upload_screenshots_to_r2()
    
    Args:
        device: Device instance with controllers
        context: ScriptExecutionContext (required for script screenshots)
        screenshot_id: Optional ID for report mapping (e.g., "step_1_start", "zap_iteration_2")
        
    Returns:
        screenshot_id if successful, None otherwise
        
    Example:
        # Navigation screenshot
        capture_screenshot_for_script(device, context, "step_1_start")
        
        # Zap iteration screenshot  
        capture_screenshot_for_script(device, context, "zap_iter_1_motion")
        
        # Later, after batch upload:
        # context.screenshot_paths contains R2 URLs
        # Map using screenshot_id to populate report
    """
    try:
        screenshot_path = None

        # The run's own page first: a host shares one display between its runs, so the
        # screen capture below can be the other run's window (TASK-146).
        screenshot_path = capture_run_page_screenshot(device, screenshot_id)

        if not screenshot_path and _drives_its_own_browser(device) and _shared_display_capture(device):
            print("📸 [device_utils] No image for this step — this device's screen is shared between "
                  "runs and a screen shot here would show another run's window")
            return None

        if not screenshot_path:
            av_controller = device._get_controller('av')
            if av_controller:
                screenshot_path = av_controller.take_screenshot()
                if screenshot_path:
                    # Copy from HOT to COLD if needed
                    from shared.src.lib.utils.build_url_utils import convert_hot_to_cold_path, is_hot_storage_path
                    if is_hot_storage_path(screenshot_path):
                        cold_path = convert_hot_to_cold_path(screenshot_path)
                        os.makedirs(os.path.dirname(cold_path), exist_ok=True)
                        if os.path.exists(screenshot_path):
                            shutil.copy2(screenshot_path, cold_path)
                        screenshot_path = cold_path

        # ADB fallback for Android devices without AV controller
        if not screenshot_path:
            screenshot_path = _try_adb_screenshot(device)

        if not screenshot_path:
            return None

        # Add to context for batch upload
        context.add_screenshot(screenshot_path)

        # Store mapping for report generation (if ID provided)
        if screenshot_id:
            if not hasattr(context, 'screenshot_ids'):
                context.screenshot_ids = {}
            context.screenshot_ids[screenshot_id] = len(context.screenshot_paths) - 1  # Index in list

        return screenshot_id

    except Exception as e:
        print(f"⚠️ Screenshot capture failed: {e}")
        return None


def capture_screenshot(device, context=None, log_prefix: str = "") -> Optional[str]:
    """
    LEGACY: Capture screenshot with logging.
    Use capture_screenshot_for_script() for script executions!
    
    Args:
        device: Device instance with controllers
        context: Optional ScriptExecutionContext to add screenshot to
        log_prefix: Optional prefix for log messages (e.g., "[script_name]")
        
    Returns:
        Screenshot path if successful, None otherwise
    """
    try:
        screenshot_path = None

        # The run's own page first, on BOTH paths: a host shares one display between its
        # runs, so the screen capture can be the other run's window (TASK-146, BUG-0757).
        # The executor's initial and final report artifacts come through THIS legacy
        # function, not through capture_screenshot_for_script — fixing only the latter left
        # every report header still showing the shared screen, which is what the first
        # deploy proved (2026-10-21: the run fell back to capture_000388253.jpg).
        screenshot_path = capture_run_page_screenshot(device)

        if not screenshot_path and _drives_its_own_browser(device) and _shared_display_capture(device):
            # The executor asks for the run's "before" and "after" shots, and at both of
            # those moments this run has no page: the first before it launches a browser,
            # the last after it closes one. On a host whose screen is shared, the newest
            # capture at those moments is the OTHER run's window -- so there is no honest
            # image to take. Say so and take none (BUG-0757).
            print("📸 [device_utils] No device shot for this browser run — this host's screen is "
                  "shared between runs and the newest capture belongs to whichever run is on top")
            if log_prefix:
                print(f"ℹ️ {log_prefix} Device shot skipped (shared screen, no image of this run)")
            return None

        if not screenshot_path:
            av_controller = device._get_controller('av')
            if av_controller:
                screenshot_path = av_controller.take_screenshot()

        # ADB fallback for Android devices without AV controller
        if not screenshot_path:
            screenshot_path = _try_adb_screenshot(device)

        if screenshot_path:
            if context:
                context.add_screenshot(screenshot_path)
            if log_prefix:
                print(f"✅ {log_prefix} Screenshot captured: {os.path.basename(screenshot_path)}")
            return screenshot_path
        else:
            if log_prefix:
                print(f"⚠️ {log_prefix} No screenshot available (no AV controller, no ADB)")
            return None

    except Exception as e:
        if log_prefix:
            print(f"⚠️ {log_prefix} Screenshot failed: {e}")
        return None


def add_existing_image_to_context(device, filename: str, context) -> Optional[str]:
    """
    Find existing capture image and add to context for upload.
    
    This is for EXISTING images (like motion analysis frames), not new screenshots.
    Handles hot→cold copy automatically, checks both locations, fails fast if missing.
    
    Args:
        device: Device instance with AV controller
        filename: Image filename (e.g., 'capture_000237967.jpg')
        context: ScriptExecutionContext
        
    Returns:
        Full path if found and added, None if missing (fail-fast)
        
    Example:
        # Motion analysis - find existing frame from FFmpeg
        path = add_existing_image_to_context(device, 'capture_000237967.jpg', context)
        if path:
            # Image found, copied to cold, added to context for upload
            motion_images.append({'path': path, 'filename': filename})
        else:
            # Image missing - fail fast, don't add broken paths
            print(f"❌ Motion image not found: {filename}")
    """
    from shared.src.lib.utils.storage_path_utils import (
        get_captures_path, 
        get_capture_folder,
        get_cold_storage_path
    )
    
    try:
        av_controller = device._get_controller('av')
        if not av_controller or not hasattr(av_controller, 'video_capture_path'):
            return None
        
        # Get device folder (e.g., 'capture4' from '/var/www/html/stream/capture4')
        device_folder = get_capture_folder(av_controller.video_capture_path)
        
        # 1. Check HOT first (where FFmpeg actively generates files)
        # get_captures_path() automatically returns HOT or COLD based on RAM mode
        hot_captures_path = get_captures_path(device_folder)
        hot_image_path = os.path.join(hot_captures_path, filename)
        
        if os.path.exists(hot_image_path):
            # Found in hot - add_screenshot will auto-copy to cold
            context.add_screenshot(hot_image_path)
            # Return cold path (same as what add_screenshot stores internally)
            from shared.src.lib.utils.build_url_utils import convert_hot_to_cold_path
            return convert_hot_to_cold_path(hot_image_path)
        
        # 2. Check COLD (may have been archived already by hot_cold_archiver)
        # Use centralized cold path resolution
        cold_captures_path = get_cold_storage_path(device_folder, 'captures')
        cold_image_path = os.path.join(cold_captures_path, filename)
        
        if os.path.exists(cold_image_path):
            # Found in cold - already persisted
            context.add_screenshot(cold_image_path)
            return cold_image_path
        
        # 3. FAIL FAST - image not found in either location
        print(f"❌ [device_utils] Motion image not found: {filename} (checked hot: {hot_captures_path}, cold: {cold_captures_path})")
        return None
        
    except Exception as e:
        print(f"❌ [device_utils] Error adding existing image {filename}: {e}")
        return None


def get_av_controller(device):
    """
    Get the AV controller from a device.
    
    Args:
        device: Device instance
        
    Returns:
        AV controller instance or None
    """
    return device._get_controller('av')


def get_device_capture_path(device) -> Optional[str]:
    """
    Get the capture base path from a device's AV controller.
    
    RENAMED from get_capture_folder() to avoid conflict with storage_path_utils.get_capture_folder()
    
    Args:
        device: Device instance
        
    Returns:
        Capture base path or None (e.g., '/var/www/html/stream/capture4')
        
    Example:
        capture_path = get_device_capture_path(device)
        if capture_path:
            # Use storage_path_utils functions to get specific paths
            from shared.src.lib.utils.storage_path_utils import get_captures_path, get_capture_folder
            device_folder = get_capture_folder(capture_path)
            captures_path = get_captures_path(device_folder)
    """
    av_controller = device._get_controller('av')
    if av_controller and hasattr(av_controller, 'video_capture_path'):
        return av_controller.video_capture_path
    return None
