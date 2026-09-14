"""
Host Audio/Video Routes

This module contains the host-specific audio/video API endpoints for:
- AV controller connection management
- Video capture control
- Screenshot capture

These endpoints run on the host and use the host's own stored device object.
"""

from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id
from backend_host.src.lib.utils.route_request import get_json_payload, require_field
from backend_host.src.lib.utils.route_response import (
    controller_missing_for_device,
    controller_not_found,
    device_not_found
)
import os
import shutil
import time

# Create blueprint
host_av_bp = Blueprint('host_av', __name__, url_prefix='/host/av')

@host_av_bp.route('/connect', methods=['POST'])
@route_exception_handler()
def connect():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    connect_result = av_controller.connect()
    
    if connect_result:
        status = av_controller.get_status()
        return jsonify({
            'success': True,
            'connected': True,
            'device_id': device_id,
            'status': status
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to connect to AV controller'
        }), 500
        
@host_av_bp.route('/disconnect', methods=['POST'])
@route_exception_handler()
def disconnect():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    disconnect_result = av_controller.disconnect()
    
    return jsonify({
        'success': disconnect_result,
        'connected': False,
        'streaming': False,
        'device_id': device_id
    })
    
@host_av_bp.route('/status', methods=['GET'])
@route_exception_handler()
def get_status():
    device_id = request.args.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    status = av_controller.get_status()
    
    return jsonify({
        'success': True,
        'status': status,
        'device_id': device_id,
        'timestamp': time.time()
    })
    
@host_av_bp.route('/takeControl', methods=['POST'])
@route_exception_handler()
def take_control():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    control_result = av_controller.take_control()
    
    if isinstance(control_result, dict):
        control_result['device_id'] = device_id
        return jsonify(control_result)
    else:
        return jsonify({
            'success': control_result,
            'device_id': device_id
        })
        
@host_av_bp.route('/getStreamUrl', methods=['GET'])
@route_exception_handler()
def get_stream_url():
    device_id = request.args.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    from shared.src.lib.utils.build_url_utils import buildStreamUrl
    from  backend_host.src.lib.utils.host_utils import get_host_instance as get_host
    
    host = get_host()
    stream_url = buildStreamUrl(host.to_dict(), device_id)
    
    return jsonify({
        'success': True,
        'stream_url': stream_url,
        'device_id': device_id
    })
        
@host_av_bp.route('/getSegmentCapture', methods=['POST'])
@route_exception_handler()
def get_segment_capture():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    segment_number = data.get('segment_number')
    fps = data.get('fps', 5)
    
    print(f"[@route:host_av:getSegmentCapture] 📸 Request received: device_id={device_id}, segment={segment_number}, fps={fps}")
    
    if segment_number is None:
        print(f"[@route:host_av:getSegmentCapture] ❌ Missing segment_number")
        return jsonify({
            'success': False,
            'error': 'segment_number is required'
        }), 400
    
    # Get device to find capture path
    device = get_device_by_id(device_id)
    if not device:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} not found'
        }), 404
    
    # Get capture path from device
    av_controller = get_controller(device_id, 'av')
    if not av_controller or not hasattr(av_controller, 'video_capture_path'):
        return jsonify({
            'success': False,
            'error': f'No video capture path for device {device_id}'
        }), 404
    
    from shared.src.lib.utils.storage_path_utils import (
        get_capture_folder,
        get_captures_path,
        get_cold_storage_path,
        get_capture_number_from_segment,
        get_device_segment_duration
    )

    # Get device folder + segment duration (segment->capture mapping is duration-aware)
    device_folder = get_capture_folder(av_controller.video_capture_path)
    segment_duration = get_device_segment_duration(device_folder)

    # Calculate capture number from segment
    capture_number = get_capture_number_from_segment(segment_number, fps, segment_duration)
    filename = f'capture_{str(capture_number).zfill(9)}.jpg'
    
    # Check hot storage first
    hot_captures_path = get_captures_path(device_folder)
    hot_path = os.path.join(hot_captures_path, filename)
    
    # Build cold path
    cold_captures_path = get_cold_storage_path(device_folder, 'captures')
    cold_path = os.path.join(cold_captures_path, filename)
    
    # Copy from hot to cold if exists in hot (skip if same path, i.e. SD card mode)
    if os.path.exists(hot_path):
        if os.path.realpath(hot_path) != os.path.realpath(cold_path):
            # Directory MUST exist (pre-created by setup_ram_hot_storage.sh)
            if not os.path.exists(cold_captures_path):
                return jsonify({
                    'success': False,
                    'error': f'Cold storage directory not found: {cold_captures_path}. Run setup_ram_hot_storage.sh to create it.'
                }), 500
            # Use shutil.copy() instead of copy2() to avoid permission issues with different owners
            shutil.copy(hot_path, cold_path)
            print(f"[@route:host_av:getSegmentCapture] Copied from HOT to COLD: {filename}")
    elif not os.path.exists(cold_path):
        return jsonify({
            'success': False,
            'error': f'Capture {filename} not found in hot or cold storage',
            'debug': {
                'segment_number': segment_number,
                'fps': fps,
                'capture_number': capture_number,
                'filename': filename,
                'hot_path': hot_path,
                'cold_path': cold_path
            }
        }), 500
    
    # Build URL for cold path
    from shared.src.lib.utils.build_url_utils import buildCaptureUrlFromPath
    from  backend_host.src.lib.utils.host_utils import get_host_instance as get_host
    
    host = get_host()
    capture_url = buildCaptureUrlFromPath(host.to_dict(), cold_path, device_id)
    
    return jsonify({
        'success': True,
        'capture_url': capture_url,
        'capture_path': cold_path,
        'segment_number': segment_number,
        'capture_number': capture_number
    })
    
@host_av_bp.route('/takeScreenshot', methods=['POST'])
@route_exception_handler()
def take_screenshot():
    import platform
    import sys
    from shared.src.lib.utils.storage_path_utils import get_stream_base_path, sanitize_folder_name
    
    data = get_json_payload()
    # device_id comes from JSON body or query params (server proxy sends it as query param)
    device_id = data.get('device_id') or request.args.get('device_id', 'device1')
    # device_id names on-disk folders further down (cold storage copy) — keep it a plain name
    try:
        device_id = secure_filename(sanitize_folder_name(str(device_id)))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    # fast=true: a caller that computes its OWN fingerprint (the auto-builder) does NOT need the
    # host-side fingerprint (a full cv2+tesseract pass, ~1-3s) or the 0.5s settle sleep. Skipping
    # them turns a 6-14s capture into ~sub-second (2026-07-17 profiling).
    fast = bool(data.get('fast') or request.args.get('fast'))

    print(f"[@route:host_av:takeScreenshot] === START (device_id={device_id}, os={platform.system()}, fast={fast}) ===", flush=True)
    print(f"[@route:host_av:takeScreenshot] HOST_VIDEO_CAPTURE_PATH env: '{os.getenv('HOST_VIDEO_CAPTURE_PATH', 'NOT SET')}'", flush=True)
    print(f"[@route:host_av:takeScreenshot] resolved STREAM_BASE_PATH: {get_stream_base_path()}", flush=True)
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        device = get_device_by_id(device_id)
        print(f"[@route:host_av:takeScreenshot] ❌ No AV controller for device_id={device_id}, device found={device is not None}", flush=True)
        if not device:
            return device_not_found(device_id)

        return controller_not_found(
            'AV',
            f'device {device_id}',
            capabilities=device.get_capabilities()
        )
    
    print(f"[@route:host_av:takeScreenshot] video_capture_path: {av_controller.video_capture_path}", flush=True)
    
    screenshot_path = av_controller.take_screenshot()
    
    if not screenshot_path:
        print(f"[@route:host_av:takeScreenshot] ❌ take_screenshot() returned None")
        return jsonify({
            'success': False,
            'error': 'Failed to take temporary screenshot - controller returned None'
        }), 500
    
    # ALWAYS copy to cold storage with FIXED filename (for verification persistence)
    from shared.src.lib.utils.storage_path_utils import get_capture_folder, get_cold_storage_path
    
    print(f"[@route:host_av:takeScreenshot] 1. screenshot_path: {screenshot_path}")
    print(f"[@route:host_av:takeScreenshot]    file exists: {os.path.exists(screenshot_path)}")
    
    device_folder = get_capture_folder(screenshot_path)
    print(f"[@route:host_av:takeScreenshot] 2. device_folder: {device_folder}")
    
    cold_captures_path = get_cold_storage_path(device_folder, 'captures')
    print(f"[@route:host_av:takeScreenshot] 3. cold_captures_path: {cold_captures_path}")
    print(f"[@route:host_av:takeScreenshot]    dir exists: {os.path.exists(cold_captures_path)}")
    
    # Use FIXED filename that overwrites each time (ensures verification source is always available)
    cold_path = os.path.join(cold_captures_path, 'verification_source.jpg')
    print(f"[@route:host_av:takeScreenshot] 4. cold_path: {cold_path}")
    
    # Directory MUST exist (pre-created by setup or capture scripts)
    if not os.path.exists(cold_captures_path):
        os.makedirs(cold_captures_path, exist_ok=True)
        print(f"[@route:host_av:takeScreenshot] 📁 Created captures directory: {cold_captures_path}")
    
    if os.path.exists(screenshot_path):
        try:
            shutil.copy(screenshot_path, cold_path)
            screenshot_path = cold_path
            print(f"[@route:host_av:takeScreenshot] ✅ Copied to: {cold_path}")
        except PermissionError as e:
            return jsonify({
                'success': False,
                'error': f'Permission denied writing to {cold_path}. Check folder permissions.'
            }), 500
    else:
        print(f"[@route:host_av:takeScreenshot] ⚠️ Source not found: {screenshot_path}")
    
    # List files in cold captures to confirm
    if os.path.exists(cold_captures_path):
        files_in_dir = [f for f in os.listdir(cold_captures_path) if f.endswith('.jpg')][:5]
        print(f"[@route:host_av:takeScreenshot] 5. files in cold dir: {files_in_dir}")
    
    if not fast:
        time.sleep(0.5)

    from shared.src.lib.utils.build_url_utils import buildCaptureUrlFromPath
    from  backend_host.src.lib.utils.host_utils import get_host_instance as get_host
    
    try:
        host = get_host()
        screenshot_url = buildCaptureUrlFromPath(host.to_dict(), screenshot_path, device_id)
        client_screenshot_url = screenshot_url
        
        print(f"[@route:host_av:takeScreenshot] 6. Final URL: {client_screenshot_url}")

        # Compute the Localize fingerprint DIRECTLY from the captured frame — the
        # host already has the image on disk, so no re-download is ever needed.
        # fast callers compute their own fingerprint, so skip this ~1-3s cv2+OCR pass.
        fingerprint = None
        if not fast:
            try:
                import cv2
                from backend_host.src.controllers.verification.image_helpers import ImageHelpers
                img_bgr = cv2.imread(screenshot_path)
                fingerprint = ImageHelpers(None, av_controller).compute_fingerprint(img_bgr)
            except Exception as fp_err:
                print(f"[@route:host_av:takeScreenshot] fingerprint failed (non-fatal): {fp_err}")

        print(f"[@route:host_av:takeScreenshot] === SUCCESS ===")

        return jsonify({
            'success': True,
            'screenshot_url': client_screenshot_url,
            'fingerprint': fingerprint,
            'device_id': device_id
        })
    except ValueError as e:
        print(f"[@route:host_av:takeScreenshot] ❌ URL build error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
@host_av_bp.route('/takeVideoForReport', methods=['POST'])
@route_exception_handler()
def take_video_for_report():
    """Capture a test-execution MP4 via the AV controller and upload to R2.

    Mirrors the in-process path used by `script_executor.finalize_execution_context`
    so callers that cannot import the controller directly (backend_server running the
    AI test-prompt loop) still get the same video artifact attached to their report.
    """
    data = get_json_payload()
    device_id = data.get('device_id') or request.args.get('device_id', 'device1')
    try:
        duration = float(data.get('duration') or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        start_time = float(data.get('start_time') or 0)
    except (TypeError, ValueError):
        start_time = 0.0
    device_model = data.get('device_model') or 'unknown'
    script_name = (data.get('script_name') or 'test_prompt').replace('.py', '')
    script_result_id = data.get('script_result_id')

    if duration <= 0 or start_time <= 0:
        return jsonify({'success': False, 'error': 'duration and start_time are required'}), 400

    av_controller = get_controller(device_id, 'av')
    if not av_controller:
        device = get_device_by_id(device_id)
        if not device:
            return device_not_found(device_id)
        return controller_not_found('AV', f'device {device_id}', capabilities=device.get_capabilities())

    if not hasattr(av_controller, 'take_video_for_report'):
        return jsonify({'success': False, 'error': 'AV controller does not support video capture'}), 501

    local_video_path = av_controller.take_video_for_report(duration, start_time)
    if not local_video_path or not os.path.exists(local_video_path):
        return jsonify({'success': False, 'error': 'Video extraction failed', 'video_url': ''}), 500

    from datetime import datetime
    from shared.src.lib.utils.cloudflare_utils import upload_test_video

    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    upload_result = upload_test_video(
        local_video_path=local_video_path,
        device_model=device_model,
        script_name=script_name,
        timestamp=timestamp,
        script_result_id=script_result_id,
    )
    if not upload_result.get('success'):
        return jsonify({
            'success': False,
            'error': upload_result.get('error', 'R2 upload failed'),
            'video_url': '',
        }), 500

    return jsonify({
        'success': True,
        'video_url': upload_result.get('video_url', ''),
        'remote_path': upload_result.get('video_path', ''),
        'local_path': local_video_path,
    })


@host_av_bp.route('/saveScreenshot', methods=['POST'])
@route_exception_handler()
def save_screenshot():
    request_data = get_json_payload()
    device_id = request_data.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    filename, filename_error = require_field(
        request_data,
        'filename',
        message='Filename is required for saving screenshot'
    )
    if filename_error:
        return filename_error

    userinterface_name, ui_error = require_field(
        request_data,
        'userinterface_name',
        message='userinterface_name is required for saving screenshot'
    )
    if ui_error:
        return ui_error
    
    local_screenshot_path = av_controller.save_screenshot(filename)
    
    if not local_screenshot_path:
        return jsonify({
            'success': False,
            'error': 'Failed to take screenshot'
        }), 500
    
    if not os.path.exists(local_screenshot_path):
        return jsonify({
            'success': False,
            'error': f'Screenshot file not found: {local_screenshot_path}'
        }), 500
    
    try:
        from shared.src.lib.utils.cloudflare_utils import upload_navigation_screenshot
        
        r2_filename = f"{filename}.jpg"
        upload_result = upload_navigation_screenshot(local_screenshot_path, userinterface_name, r2_filename)
        
        if not upload_result.get('success'):
            return jsonify({
                'success': False,
                'error': f'Failed to upload to R2: {upload_result.get("error")}'
            }), 500
        
        r2_url = upload_result.get('url')

        client_r2_url = r2_url
        client_local_path = local_screenshot_path

        # Compute the screen fingerprint (dHash + focus) for Localize. Best-effort:
        # fingerprinting must never fail the screenshot save.
        fingerprint = None
        try:
            import cv2
            from backend_host.src.controllers.verification.image_helpers import ImageHelpers
            img_bgr = cv2.imread(local_screenshot_path)
            fingerprint = ImageHelpers(None, av_controller).compute_fingerprint(img_bgr)
        except Exception as fp_err:
            print(f"[@route:host_av:saveScreenshot] fingerprint failed (non-fatal): {fp_err}")

        return jsonify({
            'success': True,
            'screenshot_url': client_r2_url,
            'screenshot_path': client_local_path,
            'fingerprint': fingerprint,
            'device_id': device_id
        })
        
    except Exception as upload_error:
        return jsonify({
            'success': False,
            'error': f'Upload to R2 failed: {str(upload_error)}'
        }), 500


@host_av_bp.route('/regionFingerprint', methods=['POST'])
@route_exception_handler()
def region_fingerprint():
    """Recompute a node's Localize fingerprint from its STORED screenshot.
    Body: {screenshot_url}. screenshot_url may be a full signed URL OR a relative
    storage key (navigation/<ui>/<node>.jpg) — handle both."""
    import cv2, os, tempfile
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    data = get_json_payload()
    url = data.get('screenshot_url')
    if not url:
        return jsonify({'success': False, 'error': 'screenshot_url is required'}), 400
    try:
        ih = ImageHelpers(None, None)
        img = None
        if str(url).startswith('http'):
            local_path = ih.download_image(url)
            img = cv2.imread(local_path) if local_path else None
        else:
            # relative storage key → download via the storage client
            from shared.src.lib.utils.cloudflare_utils import CloudflareUtils
            cf = CloudflareUtils()
            tmp = os.path.join(tempfile.gettempdir(), 'regfp.jpg')
            dl = cf.download_file(url, tmp)
            img = cv2.imread(tmp) if dl.get('success') else None
            if img is None:
                return jsonify({'success': False,
                                'error': f"Could not fetch stored screenshot '{url}' from storage "
                                         f"({dl.get('error', 'unknown')})"}), 500
        if img is None:
            return jsonify({'success': False, 'error': 'Failed to download/read screenshot'}), 500
        fp = ih.compute_fingerprint(img)
        return jsonify({'success': True, 'fingerprint': fp})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Region fingerprint failed: {str(e)}'}), 500


@host_av_bp.route('/generateDom', methods=['POST'])
@route_exception_handler()
def generate_dom_route():
    """Generate the LLM DOM (GPT-5.5, no hints) for a node's STORED screenshot.

    Body: {screenshot_url}. Downloads the screenshot, runs dom_generator.generate_dom(),
    renders the `<stem>_dom.jpg` overlay and uploads it next to the screenshot (so the
    Edit-node "Open DOM" tab resolves it from the screenshot key), and returns {dom}.
    Slow (~45-60s) — called synchronously by the Reset-DOM button and in the background
    after a screenshot save.
    """
    import os, re, tempfile
    from backend_host.src.controllers.verification.image_helpers import ImageHelpers
    from shared.src.lib.utils.cloudflare_utils import CloudflareUtils
    from backend_host.src.services.ai_exploration.dom_generator import generate_dom, render_dom_overlay

    data = get_json_payload()
    url = data.get('screenshot_url')
    if not url:
        return jsonify({'success': False, 'error': 'screenshot_url is required'}), 400

    cf = CloudflareUtils()
    # Normalize the stored screenshot (signed URL or relative key) to a storage key.
    key = re.sub(r'^https?://[^/]+/', '', str(url)).split('?', 1)[0]
    if cf.bucket_name and key.startswith(f'{cf.bucket_name}/'):
        key = key[len(cf.bucket_name) + 1:]

    tmp_shot = os.path.join(tempfile.gettempdir(), 'gendom_src.jpg')
    tmp_overlay = os.path.join(tempfile.gettempdir(), 'gendom_overlay.jpg')
    try:
        if str(url).startswith('http'):
            local_path = ImageHelpers(None, None).download_image(url)
        else:
            dl = cf.download_file(key, tmp_shot)
            local_path = tmp_shot if dl.get('success') else None
        if not local_path or not os.path.exists(local_path):
            return jsonify({'success': False, 'error': f"Could not fetch screenshot '{key}'"}), 500

        dom = generate_dom(local_path)

        # Render + upload the overlay to the <stem>_dom.jpg sibling key.
        render_dom_overlay(local_path, dom, tmp_overlay)
        dom_key = re.sub(r'\.(jpe?g|png)$', r'_dom.\1', key, flags=re.IGNORECASE)
        up = cf.upload_files([{'local_path': tmp_overlay, 'remote_path': dom_key}])
        dom_image_ok = bool(up.get('uploaded_files'))

        return jsonify({
            'success': True,
            'dom': dom,
            'dom_image_key': dom_key if dom_image_ok else None,
            'focused_element_id': dom.get('focused_element_id'),
            'element_count': len(dom.get('focusable_elements', [])),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'DOM generation failed: {str(e)}'}), 500
    finally:
        for p in (tmp_overlay,):
            if os.path.exists(p):
                os.unlink(p)


@host_av_bp.route('/startCapture', methods=['POST'])
@route_exception_handler()
def start_video_capture():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    duration = data.get('duration', 60.0)
    filename = data.get('filename')
    resolution = data.get('resolution')
    fps = data.get('fps')
    
    capture_result = av_controller.start_video_capture(
        duration=duration,
        filename=filename,
        resolution=resolution,
        fps=fps
    )
    
    if capture_result:
        session_id = getattr(av_controller, 'capture_session_id', None)
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'duration': duration,
            'device_id': device_id,
            'message': 'Video capture started successfully'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to start video capture'
        }), 500
        
@host_av_bp.route('/stopCapture', methods=['POST'])
@route_exception_handler()
def stop_video_capture():
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    av_controller = get_controller(device_id, 'av')
    
    if not av_controller:
        return controller_missing_for_device('AV', device_id)
    
    stop_result = av_controller.stop_video_capture()
    
    if stop_result:
        return jsonify({
            'success': True,
            'device_id': device_id,
            'message': 'Video capture stopped successfully'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to stop video capture or no active capture session'
        }), 500
        
@host_av_bp.route('/promoteCapturedFrames', methods=['POST'])
@route_exception_handler()
def promote_captured_frames():
    """Persist the video-capture playback frames by copying them from HOT (RAM,
    rotating) to COLD (persistent) storage and return their served URLs.

    This is the same hot->cold promotion takeScreenshot does, applied to the
    recording window: the nginx `/captures/<file>` URL always resolves to COLD,
    but the live frames only exist in HOT and rotate out of RAM — so without
    promotion the player's frames vanish after a few seconds.

    Selection is by `duration_ms` measured back from the NEWEST capture (host
    clock only) rather than absolute start/end, so a browser/host clock skew
    can't drop frames. Returns captures oldest-first: [{filename, timestamp, url}].
    """
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    duration_ms = data.get('duration_ms')

    av_controller = get_controller(device_id, 'av')
    if not av_controller or not getattr(av_controller, 'video_capture_path', None):
        return controller_missing_for_device('AV', device_id)

    from shared.src.lib.utils.storage_path_utils import get_capture_storage_path, get_cold_storage_path
    from shared.src.lib.utils.build_url_utils import buildCaptureUrlFromPath
    from backend_host.src.lib.utils.host_utils import get_host_instance as get_host

    base = av_controller.video_capture_path
    hot_captures = get_capture_storage_path(base, 'captures')  # HOT (RAM) in RAM mode
    cold_captures = get_cold_storage_path(base, 'captures')    # COLD (persistent, nginx-served)
    os.makedirs(cold_captures, exist_ok=True)

    # Collect candidate capture frames with host-clock mtimes.
    candidates = []
    try:
        for filename in os.listdir(hot_captures):
            if not filename.startswith('capture_') or not filename.endswith('.jpg') or 'thumbnail' in filename:
                continue
            hot_path = os.path.join(hot_captures, filename)
            if not os.path.isfile(hot_path):
                continue
            candidates.append((int(os.path.getmtime(hot_path) * 1000), filename, hot_path))
    except FileNotFoundError:
        candidates = []

    if not candidates:
        return jsonify({'success': True, 'device_id': device_id, 'captures': [], 'total': 0})

    # Window = [newest - duration, newest], +1.5s pre-roll padding so the first
    # post-action frame isn't clipped. No duration => take everything available.
    newest = max(c[0] for c in candidates)
    try:
        window_start = newest - int(duration_ms) - 1500 if duration_ms else 0
    except (TypeError, ValueError):
        window_start = 0

    host_dict = get_host().to_dict()
    frames = []
    for ts, filename, hot_path in candidates:
        if ts < window_start:
            continue
        cold_path = os.path.join(cold_captures, filename)
        try:
            if not os.path.exists(cold_path):
                shutil.copy(hot_path, cold_path)  # no-op-equivalent in SD mode (hot==cold)
        except Exception as copy_err:
            print(f"[@route:host_av:promoteCapturedFrames] copy failed for {filename}: {copy_err}")
            continue
        try:
            url = buildCaptureUrlFromPath(host_dict, cold_path, device_id)
        except ValueError:
            continue
        frames.append({'filename': filename, 'timestamp': ts, 'url': url})

    frames.sort(key=lambda f: f['timestamp'])  # oldest-first for playback
    print(f"[@route:host_av:promoteCapturedFrames] Promoted {len(frames)} frame(s) hot->cold for {device_id}")
    return jsonify({'success': True, 'device_id': device_id, 'captures': frames, 'total': len(frames)})


@host_av_bp.route('/images/screenshot/<filename>', methods=['GET', 'OPTIONS'])
def serve_screenshot(filename):
    """Serve a screenshot image by filename from host"""
    if request.method == 'OPTIONS':
        response = current_app.response_class()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
        
    try:
        from shared.src.lib.utils.build_url_utils import resolveCaptureFilePath
        
        try:
            capture_path = resolveCaptureFilePath(secure_filename(filename))
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        
        if not os.path.exists(capture_path):
            return jsonify({'success': False, 'error': 'Capture not found'}), 404
        
        file_size = os.path.getsize(capture_path)
        if file_size == 0:
            return jsonify({'success': False, 'error': 'Capture file is empty'}), 500
        
        response = send_file(capture_path, mimetype='image/jpeg')
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate')
        response.headers.add('Pragma', 'no-cache')
        response.headers.add('Expires', '0')
        return response
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@host_av_bp.route('/images', methods=['GET', 'OPTIONS'])
def serve_image_by_path():
    """Serve an image or JSON file from a specified path on host"""
    if request.method == 'OPTIONS':
        response = current_app.response_class()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
        
    try:
        file_path = request.args.get('path')
        
        is_json = file_path and file_path.lower().endswith('.json')
        
        from shared.src.lib.utils.build_url_utils import resolveImageFilePath
        
        try:
            if is_json:
                temp_image_path = file_path.replace('.json', '.jpg')
                validated_image_path = resolveImageFilePath(temp_image_path)
                validated_path = validated_image_path.replace('.jpg', '.json')
            else:
                validated_path = resolveImageFilePath(file_path)
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        
        if not os.path.exists(validated_path):
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        file_size = os.path.getsize(validated_path)
        if file_size == 0:
            return jsonify({'success': False, 'error': 'File is empty'}), 500
        
        if is_json:
            mimetype = 'application/json'
        elif validated_path.lower().endswith('.png'):
            mimetype = 'image/png'
        else:
            mimetype = 'image/jpeg'
        
        response = send_file(validated_path, mimetype=mimetype)
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate')
        response.headers.add('Pragma', 'no-cache')
        response.headers.add('Expires', '0')
        return response
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
