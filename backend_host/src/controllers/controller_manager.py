"""
Controller Manager

Handles the creation and organization of controllers for devices.
"""

import os
import platform
import threading
from typing import Dict, List, Any, Optional
from shared.src.lib.models.host import Host
from shared.src.lib.models.device import Device
from shared.src.lib.config.device_capabilities import model_spelling_note, parse_device_model
from backend_host.src.controllers.controller_config_factory import create_controller_configs_from_device_info
from backend_host.src.controllers import CONTROLLER_REGISTRY
from backend_host.src.controllers.controller_registry import (
    get_remote_implementation,
    get_verification_implementation,
)

# Import controller classes
from backend_host.src.controllers.audiovideo.hdmi_stream import HDMIStreamController
from backend_host.src.controllers.audiovideo.vnc_stream import VNCStreamController
from backend_host.src.controllers.audiovideo.camera_stream import CameraStreamController
from backend_host.src.controllers.audiovideo.rtsp_stream import RTSPStreamController
from backend_host.src.controllers.audiovideo.video_stream import VideoFileStreamController
from backend_host.src.controllers.remote.android_mobile import AndroidMobileRemoteController
from backend_host.src.controllers.remote.android_tv import AndroidTVRemoteController
from backend_host.src.controllers.remote.appium_remote import AppiumRemoteController
from backend_host.src.controllers.remote.infrared import IRRemoteController
from backend_host.src.controllers.desktop.bash import BashDesktopController
from backend_host.src.controllers.desktop.pyautogui import PyAutoGUIDesktopController
from backend_host.src.controllers.verification.image import ImageVerificationController
from backend_host.src.controllers.verification.text import TextVerificationController
from backend_host.src.controllers.verification.color import ColorVerificationController
from backend_host.src.controllers.verification.adb import ADBVerificationController
from backend_host.src.controllers.verification.appium import AppiumVerificationController
from backend_host.src.controllers.verification.video import VideoVerificationController
from backend_host.src.controllers.verification.audio import AudioVerificationController
from backend_host.src.controllers.power.tapo_power import TapoPowerController
from backend_host.src.controllers.web.playwright import PlaywrightWebController


def create_host_from_environment(device_ids: List[str] = None, host_ip: str = None) -> Host:
    """
    Create a Host with devices and controllers from environment variables.

    Args:
        device_ids: List of specific device IDs to create (None = all devices)

    Returns:
        Host instance with specified devices and controllers configured
    """

    # Get host info from environment variables + detect IP if not set
    import os
    from backend_host.src.app import detect_host_ip
    
    host_name = os.getenv('HOST_NAME', 'unknown-host')
    # App startup already detects the address before route registration. Reuse it
    # when supplied instead of repeating network probes during device setup.
    if not host_ip:
        host_ip = detect_host_ip()  # Use detection function (handles HOST_IP env var internally)
    host_port = int(os.getenv('HOST_PORT', '6109'))

    # Auto-construct host_url from HOST_NAME (or allow override)
    host_url = os.getenv('HOST_URL')
    if not host_url:
        # Auto-construct: /host/{hostname}
        host_url = f"/host/{host_name}"
        print(f"[@controller_manager:create_host_from_environment] Auto-constructed HOST_URL: {host_url}")
    
    # Optional features that contribute a controller (docs/technical/FEATURES.md).
    # In vpt-host they already registered through register(app); this is the path that
    # matters for a script subprocess, which builds its controllers with no app at all
    # and would otherwise create feature-backed devices with that controller missing.
    from shared.src.lib.utils.features import register_feature_controllers
    register_feature_controllers('backend_host')

    print(f"[@controller_manager:create_host_from_environment] Creating host: {host_name}")
    print(f"[@controller_manager:create_host_from_environment]   Host URL: {host_url}")
    if host_ip == '0.0.0.0':
        print(f"[@controller_manager:create_host_from_environment]   Binding: all interfaces (0.0.0.0):{host_port}")
    else:
        print(f"[@controller_manager:create_host_from_environment]   Binding: specific interface {host_ip}:{host_port}")
    
    # Detect host OS for VNC password handling
    host_os = platform.system().lower()  # 'linux', 'darwin' (macOS), 'windows', etc.

    # Create host with host_url parameter
    host = Host(host_ip, host_port, host_name, host_url, host_os=host_os)
    
    # Check for host VNC configuration and create VNC controller if present
    # Only create host VNC device if specifically requested or no device filter specified
    video_capture_path = os.getenv('HOST_VIDEO_CAPTURE_PATH')
    
    # Auto-construct VNC stream path from HOST_NAME (or allow override)
    # Uses nginx-proxied path: /host/{host_name}/vnc_lite.html
    vnc_stream_path = os.getenv('HOST_VNC_STREAM_PATH')
    # No default: HOST_VNC_PASSWORD is generated per install by install_host.sh, and a
    # literal fallback would put the old shared password in every VNC URL.
    vnc_password = os.getenv('HOST_VNC_PASSWORD')

    if not vnc_stream_path and video_capture_path:
        # Build nginx-proxied URL (works with any frontend domain).
        # The password is deliberately NOT appended. This path is handed to the browser
        # as an iframe src, so anything in the query string ends up in the address bar,
        # in history, in the Referer of every sub-request, and in the nginx and
        # Cloudflare access logs — a VNC password read off a shoulder or a log line is
        # a live desktop. The noVNC page supplies the credential itself; the access
        # decision belongs to the gate on /host/<name>/{vnc_lite.html,websockify}.
        vnc_stream_path = f"/host/{host_name}/vnc_lite.html"
        print(f"[@controller_manager:create_host_from_environment] Auto-constructed VNC path: {vnc_stream_path}")
    
    should_create_host_vnc = (
        vnc_stream_path and video_capture_path and 
        (device_ids is None or 'host' in device_ids)
    )
    
    if should_create_host_vnc:
        print(f"[@controller_manager:create_host_from_environment] VNC configuration detected - creating host VNC controller")
        print(f"[@controller_manager:create_host_from_environment]   VNC Stream Path: {vnc_stream_path}")
        print(f"[@controller_manager:create_host_from_environment]   Video Capture Path: {video_capture_path}")
        
        final_vnc_stream_path = vnc_stream_path
        if vnc_password:
            print(f"[@controller_manager:create_host_from_environment]   VNC Password: {vnc_password}")
        
        # Get additional VNC environment variables
        web_browser_path = os.getenv('HOST_WEB_BROWSER_PATH', '/usr/bin/chromium')
        
        # Create host VNC device (special device representing the host itself)
        host_device_config = {
            'device_id': 'host',
            'device_name': f'{host_name}_Host',
            'device_model': 'host_vnc',  # Keep the model as host_vnc for controller configuration
            'video_stream_path': final_vnc_stream_path,  # VNC streaming/viewing URL
            'video_capture_path': video_capture_path,  # FFmpeg capture system path
            'vnc_password': vnc_password,  # VNC password
            'web_browser_path': web_browser_path,  # Browser path for VNC viewer
            'host_ip': host_ip,  # Add host IP for web controller
            'host_port': host_port,  # Add host port for web controller
            # Audio (host-wide). The vpt-windows-audio Scheduled Task writes its
            # HLS to /stream/host_audio/.. (Linux uses /stream/_audio/..). Mirrors
            # BUG-0596's DEVICE{N} pattern for per-device capture, scoped to the
            # whole host for now since the Win10/11 audio pipeline is one
            # per-machine capture (Linux muxed audio is per-device but noVNC on
            # Windows has no per-device video to mux with).
            'audio_stream_path': os.getenv('HOST_VNC_AUDIO_STREAM_PATH'),
            # Same optional defaults as DEVICE{N}_USERINTERFACE/VARIANT: the Device page shows the
            # Localize button only when the device has a preferred userinterface (BUG-0419).
            'preferred_userinterface': os.getenv('HOST_USERINTERFACE') or None,
            'preferred_variant': os.getenv('HOST_VARIANT') or None,
        }
        
        host_device = _create_device_with_controllers(host_device_config, host)
        host.add_device(host_device)
        print(f"[@controller_manager:create_host_from_environment] Added host VNC device: {host_device.device_id} ({host_device.device_name})")
    elif vnc_stream_path and video_capture_path and device_ids is not None:
        print(f"[@controller_manager:create_host_from_environment] VNC configuration detected but host not in requested devices: {device_ids} - skipping host VNC controller")
    
    # Create devices from environment variables
    devices_config = _get_devices_config_from_environment()
    
    # Filter devices if specific device_ids requested
    if device_ids is not None:
        print(f"[@controller_manager:create_host_from_environment] Creating ONLY devices: {device_ids}")
        devices_config = [config for config in devices_config 
                         if config['device_id'] in device_ids]
    
    for device_config in devices_config:
        device = _create_device_with_controllers(device_config, host)
        host.add_device(device)
        print(f"[@controller_manager:create_host_from_environment] Added device: {device.device_id} ({device.device_name})")
    
    device_count = host.get_device_count()
    if device_count == 0:
        print("[@controller_manager:create_host_from_environment] No devices or host VNC configured; creating an empty host")
    print(f"[@controller_manager:create_host_from_environment] Host created with {device_count} devices")
    return host


def _get_devices_config_from_environment() -> List[Dict[str, Any]]:
    """
    Extract device configurations from environment variables.
    
    Returns:
        List of device configurations
    """
    devices_config = []
    
    # Look for DEVICE1 .. DEVICE<MAX_DEVICES> (default 99; same knob as run_ffmpeg.sh)
    for i in range(1, int(os.getenv("MAX_DEVICES", "99")) + 1):
        device_name = os.getenv(f'DEVICE{i}_NAME')
        
        if device_name:

            # Extract all environment variables for this device.
            # DEVICE{i}_MODEL may be a bare model ('stb', 'android_tv') OR carry a
            # platform suffix after the first dash ('stb-example-v2'). parse_device_model
            # does both halves of that in one place: it splits the suffix AND resolves how
            # the model is spelled, so `androidtv`, `andoridtv` and `appletv` build the
            # same device as the canonical name instead of a device with no controllers at
            # all (BUG-0749). A bare value yields platform=None and identical pre-variant
            # behaviour. Reuses the existing .env field — no new keys.
            raw_model = os.getenv(f'DEVICE{i}_MODEL', 'unknown')
            device_model, device_platform = parse_device_model(raw_model)
            video = os.getenv(f'DEVICE{i}_VIDEO')
            video_capture_path = os.getenv(f'DEVICE{i}_VIDEO_CAPTURE_PATH')

            # Per-device audio stream path -- only meaningful for host_vnc devices
            # where the video path is the noVNC iframe (no built-in audio). When
            # set, the dashboard plays an <audio> element bound to this HLS
            # playlist next to the VNC iframe. The audio source itself is owned
            # by the run_*_audio.* + capture_* scripts (vpt-windows-audio on
            # Windows, run_ffmpeg.sh's pulse `-i default` muxing on Linux).
            audio_stream_path = os.getenv(f'DEVICE{i}_HOST_VNC_AUDIO_STREAM_PATH')

            # Explicit DEVICE{i}_HOST_VNC_STREAM_PATH for the vpt-windows class of
            # host: some devices (like DEVICE1=Host_Windows) keep the noVNC URL in
            # this key instead of the generic DEVICE{N}_VIDEO_STREAM_PATH because
            # the host_vnc controller renders the iframe directly, not an HLS
            # segment. We honour both keys so vpt-windows doesn't need a
            # dummy DEVICE{N}_VIDEO_STREAM_PATH anymore; the older key wins
            # (generic video stream) when both are present -- the dashboard sees
            # the proper HLS path and the controller is correctly typed.
            host_vnc_stream_path = os.getenv(f'DEVICE{i}_HOST_VNC_STREAM_PATH')
            
            # Explicit DEVICE{i}_VIDEO_STREAM_PATH, else derived from the capture folder the
            # way every host .env spells it (/var/www/html/stream/capture2 -> /host/stream/capture2;
            # the frontend prefixes the host URL). The old fallback referenced an undefined
            # `host_name` and crashed registration for any device without the explicit key (BUG-0096).
            video_stream_path = os.getenv(f'DEVICE{i}_VIDEO_STREAM_PATH')
            # vpt-windows devices (DEVICE1=Host_Windows) keep the noVNC URL under
            # DEVICE{N}_HOST_VNC_STREAM_PATH instead -- honour that too so the
            # dashboard tile shows the vnc_lite iframe via /host/<name>/vnc_lite.html.
            # Without this fallback device1 (a host_vnc model) hits the validation
            # in buildStreamUrl and returns "VNC device device1 has no
            # video_stream_path configured" even though DEVICE1_HOST_VNC_STREAM_PATH
            # is set in .env.
            if not video_stream_path and host_vnc_stream_path:
                video_stream_path = host_vnc_stream_path
                print(f"[@controller_manager] host_vnc stream path for device{i}: {video_stream_path}")
            if not video_stream_path and video_capture_path:
                video_stream_path = f"/host/stream/{os.path.basename(video_capture_path.rstrip('/'))}"
                print(f"[@controller_manager] Derived stream path for device{i}: {video_stream_path}")
            
            device_ip = os.getenv(f'DEVICE{i}_IP')
            device_port = os.getenv(f'DEVICE{i}_PORT')
            # USB ADB serial (phone farm / USB hub). Shared with run_ffmpeg.sh for
            # scrcpy capture; when set the Android controllers target it instead of ip:port.
            adb_serial = os.getenv(f'DEVICE{i}_ADB_SERIAL')
            if adb_serial and device_ip:
                print(f"[@controller_manager] ⚠️ device{i}: DEVICE{i}_ADB_SERIAL and DEVICE{i}_IP are both set; "
                      f"adb uses the USB serial {adb_serial}, not {device_ip}. Remove one if that is not what you want.")
            ir_path = os.getenv(f'DEVICE{i}_IR_PATH')
            ir_type = os.getenv(f'DEVICE{i}_IR_TYPE')
            # Networked IRTrans box (UDP). When IR_IP is set the device uses the
            # IRTrans transport instead of local lirc/ir-ctl (IR_PATH).
            ir_ip = os.getenv(f'DEVICE{i}_IR_IP')
            ir_port = os.getenv(f'DEVICE{i}_IR_PORT')
            ir_led = os.getenv(f'DEVICE{i}_IR_LED')
            ir_remote = os.getenv(f'DEVICE{i}_IR_REMOTE')
            # USB IR Toy / Irdroid (04d8:fd08) driven over its CDC serial node. Used on
            # non-Pi hosts, where the stock Debian kernel has no CONFIG_IR_TOY so the
            # dongle is never claimed for IR and no /dev/lirc* can exist.
            ir_serial = os.getenv(f'DEVICE{i}_IR_SERIAL')
            ble_adapter_hci = os.getenv(f'DEVICE{i}_BLE_ADAPTER_HCI')
            ble_type = os.getenv(f'DEVICE{i}_BLE_TYPE')
            ble_mac = os.getenv(f'DEVICE{i}_BLE_MAC')
            # TASK-71: FX voice modem (Conexant CX93001, 0572:1349). The port is
            # named by the udev rule as /dev/fx1..fx4, never /dev/ttyACM* —
            # cdc_acm hands those out in USB enumeration order, so the number
            # changes across reboots and a call can land on the wrong line.
            fx_port = os.getenv(f'DEVICE{i}_FX_PORT')
            # TASK-71: the number this line dials. Each dongle reaches one
            # gateway FXS port, and that port answers to one number, so the
            # pairing lives in .env beside FX_PORT instead of in every test
            # case. FXRemoteController.dial falls back to it.
            fx_number = os.getenv(f'DEVICE{i}_FX_NUMBER')
            bluetooth_device = os.getenv(f'DEVICE{i}_bluetooth_device')
            power_device = os.getenv(f'DEVICE{i}_power_device')
            power_name = os.getenv(f'DEVICE{i}_POWER_NAME')
            power_ip = os.getenv(f'DEVICE{i}_POWER_IP')
            power_email = os.getenv(f'DEVICE{i}_POWER_EMAIL')
            power_pwd = os.getenv(f'DEVICE{i}_POWER_PWD')
            # API power (custom client REST API). POWER_NAME is reused as the
            # API device name; POWER_API_URL presence selects the api_power transport.
            power_api_url = os.getenv(f'DEVICE{i}_POWER_API_URL')
            power_api_key = os.getenv(f'DEVICE{i}_POWER_API_KEY')
            # Wake-on-LAN (a LAN PC). POWER_MAC presence selects the wol transport;
            # POWER_IP is reused as the SSH shutdown target and status probe.
            power_mac = os.getenv(f'DEVICE{i}_POWER_MAC')
            power_broadcast = os.getenv(f'DEVICE{i}_POWER_BROADCAST')
            power_ssh_user = os.getenv(f'DEVICE{i}_POWER_SSH_USER')
            power_ssh_port = os.getenv(f'DEVICE{i}_POWER_SSH_PORT')
            appium_platform_name = os.getenv(f'DEVICE{i}_APPIUM_PLATFORM_NAME')
            appium_device_id = os.getenv(f'DEVICE{i}_APPIUM_DEVICE_ID')
            appium_server_url = os.getenv(f'DEVICE{i}_APPIUM_SERVER_URL')

            # Optional per-device defaults for navigation scripts. When a script
            # is launched without --userinterface / --variant, the script
            # executor falls back to these (see VARIANT.md / SCRIPTS doc). The
            # frontend Run Tests page also preselects them. Empty = unset.
            preferred_userinterface = os.getenv(f'DEVICE{i}_USERINTERFACE')
            preferred_variant = os.getenv(f'DEVICE{i}_VARIANT')
            # "base" is a UI label for "no variant" — there is no
            # `userinterface_variants` row named base. Normalize so the
            # downstream resolver (navigation_executor_tree_manager) gets
            # None and falls through to the base graph, instead of trying to
            # look up a non-existent variant and failing with
            # "unknown variant 'base' for userinterface ...".
            if isinstance(preferred_variant, str):
                _trimmed = preferred_variant.strip()
                preferred_variant = None if _trimmed.lower() in ('', 'base') else _trimmed
            
            # Show only configured devices
            # A model spelled differently from the canonical name is reported, never
            # silently corrected: a bare `fire_tv` is the one case where the operator may
            # have meant the other Fire TV platform (BUG-0749).
            spelling = model_spelling_note(raw_model, device_model)
            if spelling:
                print(f"[@controller_manager] DEVICE{i}_MODEL: {spelling}")
            print(f"[@controller_manager] Found device{i}: {device_name} ({device_model})")
            
            device_config = {
                'device_id': f'device{i}',
                'device_name': device_name,
                'device_model': device_model,
                'device_platform': device_platform,  # parsed from DEVICE{i}_MODEL suffix; None if bare
                # Per-device default userinterface/variant for navigation scripts
                'preferred_userinterface': preferred_userinterface,
                'preferred_variant': preferred_variant,
                # Video configuration
                'video': video,
                'youtube_url': os.getenv(f'DEVICE{i}_YOUTUBE_URL'),
                'video_stream_path': video_stream_path,
                'video_capture_path': video_capture_path,
                # host_vnc-only: parallel audio HLS (Mixage stereo / Stereo Mix on
                # Win10/11, pulse monitor on Linux). See BUG-0596.
                'audio_stream_path': audio_stream_path,
                # Device IP/Port (used by both Android ADB and Appium - mutually exclusive)
                'device_ip': device_ip,
                'device_port': device_port,
                'adb_serial': adb_serial,
                'ir_path': ir_path,
                'ir_type': ir_type,
                # IRTrans (networked) transport
                'ir_ip': ir_ip,
                'ir_port': ir_port,
                'ir_led': ir_led,
                'ir_remote': ir_remote,
                'ir_serial': ir_serial,
                'ble_adapter_hci': ble_adapter_hci,
                'ble_type': ble_type,
                'ble_mac': ble_mac,
                'bluetooth_device': bluetooth_device,
                # TASK-71: FX voice modem. /dev/fx1..fx4, named by udev.
                'fx_port': fx_port,
                'fx_number': fx_number,
                # Tello drone (TASK-32): its address and the host ports its state and video arrive on
                'tello_ip': os.getenv(f'DEVICE{i}_TELLO_IP'),
                'tello_state_port': os.getenv(f'DEVICE{i}_TELLO_STATE_PORT'),
                'tello_video_port': os.getenv(f'DEVICE{i}_TELLO_VIDEO_PORT'),
                # The host address the drone's own radio reaches us from, used as the source for
                # every socket to that drone. With two dongles on one host both Tello APs are
                # 192.168.10.1, so this is what tells the two links apart: set it (192.168.10.2 /
                # 192.168.10.4, see scripts/drone/tello_prio.sh) and the matching `ip rule from`
                # pins the traffic to one radio. Empty keeps the 0.0.0.0 wildcard of the
                # single-drone setup.
                'tello_local_ip': os.getenv(f'DEVICE{i}_TELLO_LOCAL_IP'),
                # The port the drone's SDK answers on, and the port the client binds
                # locally for that conversation. Both default to 8889, which is right
                # for a lab drone on its own radio. A drone reached through a phone
                # (TASK-160) lives behind the host's drone bridge on 127.0.0.1, so it
                # needs its own pair of numbers - one per bridged drone, or the
                # clients would fight over the same local port.
                'tello_cmd_port': os.getenv(f'DEVICE{i}_TELLO_CMD_PORT'),
                'tello_local_cmd_port': os.getenv(f'DEVICE{i}_TELLO_LOCAL_CMD_PORT'),
                # Which phone carries this drone (the phone_agent slot) and the label
                # the owner gave the drone in the phone app. Empty = a lab drone.
                'tello_bridge': os.getenv(f'DEVICE{i}_TELLO_BRIDGE'),
                'tello_bridge_phone': os.getenv(f'DEVICE{i}_TELLO_BRIDGE_PHONE'),
                'tello_bridge_drone': os.getenv(f'DEVICE{i}_TELLO_BRIDGE_DRONE'),
                # Samsung Tizen TV network remote (samsungtvws over ws/8002). TIZEN_IP
                # presence selects the samsung_tizen remote on a `tizen` device.
                'tizen_ip': os.getenv(f'DEVICE{i}_TIZEN_IP'),
                'tizen_port': os.getenv(f'DEVICE{i}_TIZEN_PORT'),
                'tizen_token': os.getenv(f'DEVICE{i}_TIZEN_TOKEN'),
                'tizen_token_file': os.getenv(f'DEVICE{i}_TIZEN_TOKEN_FILE'),
                'power_device': power_device,
                # Power configuration
                'power_name': power_name,
                'power_ip': power_ip,
                'power_email': power_email,
                'power_pwd': power_pwd,
                # API power (client REST API)
                'power_api_url': power_api_url,
                'power_api_key': power_api_key,
                # Wake-on-LAN
                'power_mac': power_mac,
                'power_broadcast': power_broadcast,
                'power_ssh_user': power_ssh_user,
                'power_ssh_port': power_ssh_port,
                # Nintendo Switch Bluetooth Pro Controller (vpt-procon daemon). Unset =
                # daemon on this host at 127.0.0.1:6190; set to reach it on another
                # host of the LAN (that daemon then requires the token).
                'switch_procon_url': os.getenv(f'DEVICE{i}_SWITCH_PROCON_URL'),
                'switch_procon_token': os.getenv(f'DEVICE{i}_SWITCH_PROCON_TOKEN'),
            }
            
            # Load Appium env vars directly into device_config (flat)
            if appium_platform_name:
                device_config['appium_platform_name'] = appium_platform_name
            
            if appium_device_id:
                device_config['appium_device_id'] = appium_device_id
                
            if appium_server_url:
                device_config['appium_server_url'] = appium_server_url
            
            # Remove None values
            device_config = {k: v for k, v in device_config.items() if v is not None}
            
            
            devices_config.append(device_config)
    
    return devices_config


def _create_controller_instance(controller_type: str, implementation: str, params: Dict[str, Any]):
    """
    Create a controller instance based on type and implementation.

    Args:
        controller_type: Abstract type ('av', 'remote', 'verification', 'ai', etc.)
        implementation: Specific implementation ('hdmi_stream', 'android_mobile', 'ai_agent', etc.)
        params: Constructor parameters

    Returns:
        Controller instance or None if not found or failed to create
    """
    try:
        # AV Controllers
        if controller_type == 'av':
            if implementation == 'hdmi_stream':
                return HDMIStreamController(**params)
            elif implementation == 'vnc_stream':
                return VNCStreamController(**params)
            elif implementation == 'camera_stream':
                return CameraStreamController(**params)
            elif implementation == 'rtsp_stream':
                return RTSPStreamController(**params)
            elif implementation == 'video_stream':
                return VideoFileStreamController(**params)

        # Remote Controllers
        elif controller_type == 'remote':
            # Feature-registered implementations first (controller_registry.py) —
            # an optional feature can add a remote type without editing this file.
            registered = get_remote_implementation(implementation)
            if registered is not None:
                return registered['factory'](**params)
            if implementation == 'android_mobile':
                return AndroidMobileRemoteController(**params)
            elif implementation == 'android_tv':
                return AndroidTVRemoteController(**params)
            elif implementation == 'samsung_tizen':
                from .remote.samsung_tizen import SamsungTizenRemoteController
                return SamsungTizenRemoteController(**params)
            elif implementation == 'appium':
                return AppiumRemoteController(**params)
            elif implementation == 'ir_remote':
                return IRRemoteController(**params)
            elif implementation == 'irtrans_remote':
                from .remote.irtrans import IRTransRemoteController
                return IRTransRemoteController(**params)
            elif implementation == 'irtoy_remote':
                from .remote.irtoy import IRToyRemoteController
                return IRToyRemoteController(**params)
            elif implementation == 'bluetooth_remote':
                from .remote.bluetooth import BluetoothRemoteController
                return BluetoothRemoteController(**params)
            elif implementation == 'tello':
                from .remote.tello import TelloRemoteController
                return TelloRemoteController(**params)
            elif implementation == 'vega':
                from .remote.vega import VegaRemoteController
                return VegaRemoteController(**params)
            elif implementation == 'fx':
                # TASK-71: FX voice modem as a remote (pick up / hang up / dial /
                # DTMF). Model `fx_dongle`; port from DEVICE{i}_FX_PORT.
                from .remote.fx import FXRemoteController
                return FXRemoteController(**params)


        # Verification Controllers - now require device_model
        elif controller_type == 'verification':
            # Feature-registered implementations first, per device model (controller_registry.py):
            # a paired phone backs 'adb' with its own accessibility tree instead of adb itself.
            registered = get_verification_implementation(params.get('device_model'), implementation)
            if registered is not None:
                return registered['factory'](**params)
            if implementation == 'image':
                return ImageVerificationController(**params)
            elif implementation == 'text':
                return TextVerificationController(**params)
            elif implementation == 'color':
                return ColorVerificationController(**params)
            elif implementation == 'video':
                return VideoVerificationController(**params)
            elif implementation == 'audio':
                return AudioVerificationController(**params)
            elif implementation == 'adb':
                return ADBVerificationController(**params)
            elif implementation == 'appium':
                return AppiumVerificationController(**params)
            elif implementation == 'web':
                # Web verification reuses the existing web controller (Playwright has verification methods)
                return None  # Will be handled specially in device creation

        # Desktop Controllers
        elif controller_type == 'desktop':
            if implementation == 'bash':
                return BashDesktopController(**params)
            elif implementation == 'pyautogui':
                return PyAutoGUIDesktopController(**params)

        # Web Controllers
        elif controller_type == 'web':
            if implementation == 'playwright':
                from backend_host.src.controllers.web.playwright import PlaywrightWebController
                return PlaywrightWebController(**params)

        # Switch Controllers
        elif controller_type == 'switch':
            # TASK-31: switch controller. 'hdmi_switch' is a placeholder;
            # 'bluetooth_procon' drives a Nintendo Switch as a Bluetooth Pro
            # Controller (vpt-procon daemon). Both are registered in
            # CONTROLLER_REGISTRY['switch']; this block just routes.
            impl_class = CONTROLLER_REGISTRY.get('switch', {}).get(implementation)
            if impl_class is None:
                from backend_host.src.controllers.switch.base_switch import BaseSwitchController
                return BaseSwitchController(controller_name=f"{implementation} (placeholder)", **params)
            print(f"[@controller_manager] Loaded switch controller: {impl_class.__name__}")
            return impl_class(**params)
        elif controller_type == 'power':
            if implementation == 'tapo':
                return TapoPowerController(**params)
            elif implementation == 'api_power':
                from .power.api_power import APIPowerController
                return APIPowerController(**params)
            elif implementation == 'wol':
                from .power.wol_power import WOLPowerController
                return WOLPowerController(**params)

        print(f"[@controller_manager:_create_controller_instance] WARNING: Unknown controller {controller_type}_{implementation}")
        return None

    except PermissionError as e:
        print(f"[@controller_manager:_create_controller_instance] ❌ Permission denied creating {controller_type}_{implementation} controller: {e}")
        print(f"[@controller_manager:_create_controller_instance]   Continuing without this controller...")
        return None
    except Exception as e:
        print(f"[@controller_manager:_create_controller_instance] ❌ Failed to create {controller_type}_{implementation} controller: {e}")
        print(f"[@controller_manager:_create_controller_instance]   Continuing without this controller...")
        return None


def _resolved_device_name(controller) -> str:
    """The name the connected hardware reports for itself, or '' when it cannot say.

    Optional on purpose: a controller for fixed hardware has nothing to add, and asking must
    never be able to break device creation.
    """
    resolver = getattr(controller, 'get_connected_device_name', None)
    if not callable(resolver):
        return ''
    try:
        return (resolver() or '').strip()
    except Exception as e:
        print(f"[@controller_manager:_resolved_device_name] skipped: {e}")
        return ''


def _create_device_with_controllers(device_config: Dict[str, Any], host: 'Host') -> Device:
    """
    Create a device with all its controllers from configuration.
    Handles controller dependencies by creating them in the right order.
    
    Args:
        device_config: Device configuration dictionary
        host: Host instance (optional, used for executor initialization)
        
    Returns:
        Device instance with controllers
    """
    host_name = host.host_name
    device_id = device_config['device_id']
    device_name = device_config['device_name']
    device_model = device_config['device_model']
    
    print(f"[@controller_manager:_create_device_with_controllers] Creating device: {device_id}")
    
    # Create device with IP/port values and video paths for URL building
    device = Device(
        device_id,
        device_name,
        device_model,
        host_name,
        device_config.get('device_ip'),
        device_config.get('device_port'),
        device_config.get('video_stream_path'),
        device_config.get('video_capture_path'),
        device_config.get('video'),
        device_config.get('ir_type'),
        device_config.get('device_platform'),  # parsed from DEVICE{i}_MODEL suffix
        device_config.get('preferred_userinterface'),
        device_config.get('preferred_variant'),
        device_config.get('audio_stream_path'),  # host_vnc-only (BUG-0596)
    )
    
    # Create controllers using the factory (returns dict now)
    controller_configs = create_controller_configs_from_device_info(device_config)
    
    # Convert dict to list for processing
    controller_list = list(controller_configs.values())
    
    # Separate controllers by type to handle dependencies
    av_controllers = [c for c in controller_list if c['type'] == 'av']
    remote_controllers = [c for c in controller_list if c['type'] == 'remote']
    verification_controllers = [c for c in controller_list if c['type'] == 'verification']
    power_controllers = [c for c in controller_list if c['type'] == 'power']
    desktop_controllers = [c for c in controller_list if c['type'] == 'desktop']
    web_controllers = [c for c in controller_list if c['type'] == 'web']
    # TASK-31: switch controllers (HDMI matrix placeholder, Bluetooth Pro
    # Controller for a Nintendo Switch). Same iteration shape as the others; instantiated after
    # AV so the switch controller can reference the av_controller if needed.
    switch_controllers = [c for c in controller_list if c['type'] == 'switch']
    
    # Step 1: Create AV controllers first (no dependencies)  
    av_controller = None
    for controller_config in av_controllers:
        controller_type = controller_config['type']
        implementation = controller_config['implementation']
        controller_params = controller_config['params']
        
        # Create controller based on implementation type
        controller = _create_controller_instance(controller_type, implementation, controller_params)
        if controller:
            device.add_controller(controller_type, controller)
            av_controller = controller  # Keep reference for verification controllers
    
    # Step 2: Create remote controllers (no dependencies)
    for controller_config in remote_controllers:
        controller_type = controller_config['type']
        implementation = controller_config['implementation']
        controller_params = controller_config['params']
        
        # Check if controller should be skipped due to missing configuration
        if controller_params.get('_skip_controller'):
            reason = controller_params.get('reason', 'Unknown reason')
            print(f"[@controller_manager:_create_device_with_controllers] ⚠️  Skipping {implementation} controller: {reason}")
            continue
        
        controller = _create_controller_instance(controller_type, implementation, controller_params)
        if controller:
            device.add_controller(controller_type, controller)
            # A slot whose hardware arrives at runtime knows its own name better than .env
            # does: DEVICE{i}_NAME is a slot label ("Phone slot 1"), while the thing paired
            # into it is a particular phone ("samsung SM-G998B"). vpt-host already renames
            # the device when a phone pairs, but a script runs in its own process and builds
            # its devices straight from .env, so every result it recorded carried the slot
            # label. Controllers that cannot know better simply don't implement this.
            resolved = _resolved_device_name(controller)
            if resolved and resolved != device.device_name:
                print(f"[@controller_manager:_create_device_with_controllers] "
                      f"{device.device_id}: '{device.device_name}' is a slot label - "
                      f"using the connected device's own name '{resolved}'")
                device.device_name = resolved
    
    # Step 3: Create web controllers (no dependencies, needed before verification controllers)
    web_controller = None
    for controller_config in web_controllers:
        controller_type = controller_config['type']
        implementation = controller_config['implementation']
        controller_params = controller_config['params']
        
        controller = _create_controller_instance(controller_type, implementation, controller_params)
        if controller:
            device.add_controller(controller_type, controller)
            web_controller = controller  # Keep reference for web verification
    
    # Step 4: Create verification controllers (depend on AV/web controllers and device model)
    for controller_config in verification_controllers:
        controller_type = controller_config['type']
        implementation = controller_config['implementation']
        controller_params = controller_config['params']
        
        # Skip 'web' verification - web controller already registered and has verification methods
        # No need to register Playwright twice (it's already registered as 'web' controller)
        if implementation == 'web':
            print(f"[@controller_manager:_create_device_with_controllers] ✓ Web verifications available via 'web' controller (Playwright)")
            continue
        
        # Add av_controller dependency for verification controllers that need it
        # ADB verification controller doesn't need av_controller (uses direct ADB communication)
        if implementation in ['image', 'text', 'video', 'color', 'audio']:
            if av_controller:
                controller_params['av_controller'] = av_controller
            else:
                print(f"[@controller_manager:_create_device_with_controllers] ⚠️  {implementation} verification needs AV controller but none available - skipping")
                continue  # Skip creating this controller

        # Add device_model + device_id for all verification controllers (every one takes
        # **kwargs). The model picks a feature-registered implementation; the id is what such
        # an implementation needs to address the device it belongs to.
        controller_params['device_model'] = device_model
        controller_params['device_id'] = device_id

        # Create the verification controller instance
        controller = _create_controller_instance(
            controller_type, implementation, controller_params
        )

        if controller:
            device.add_controller(controller_type, controller)
        else:
            print(f"[@controller_manager:_create_device_with_controllers] ⚠️  Failed to create {implementation} verification controller - continuing with other controllers")
    
    # Step 5: Create power controllers (no dependencies)
    for controller_config in power_controllers:
        controller_type = controller_config['type']
        implementation = controller_config['implementation']
        controller_params = controller_config['params']
        
        controller = _create_controller_instance(controller_type, implementation, controller_params)
        if controller:
            device.add_controller(controller_type, controller)
    
    # Step 6: Create desktop controllers (no dependencies)
    for controller_config in desktop_controllers:
        controller_type = controller_config['type']
        implementation = controller_config['implementation']
        controller_params = controller_config['params']

        controller = _create_controller_instance(controller_type, implementation, controller_params)
        if controller:
            device.add_controller(controller_type, controller)

    # Step 6b: Create switch controllers (TASK-31). Same iteration shape as
    # the others; the av_controller is passed in case a switch controller
    # needs the host's capture pipeline.
    for controller_config in switch_controllers:
        controller_type = controller_config['type']
        implementation = controller_config['implementation']
        controller_params = controller_config['params']
        if av_controller is not None:
            controller_params.setdefault('av_controller', av_controller)

        controller = _create_controller_instance(controller_type, implementation, controller_params)
        if controller:
            device.add_controller(controller_type, controller)
    
    # Step 7: Create service executors (ActionExecutor, NavigationExecutor, VerificationExecutor, ExplorationExecutor)
    try:
        from backend_host.src.services.actions.action_executor import ActionExecutor
        from backend_host.src.services.navigation.navigation_executor import NavigationExecutor
        from backend_host.src.services.verifications.verification_executor import VerificationExecutor
        from backend_host.src.services.blocks.standard_block_executor import StandardBlockExecutor
        from backend_host.src.services.ai_exploration.exploration_executor import ExplorationExecutor
        from backend_host.src.services.ai import AIGraphBuilder
        
        # Create executors - device has everything they need
        # team_id will be provided during actual execution, not during initialization
        device.action_executor = ActionExecutor(device, _from_device_init=True)
        device.navigation_executor = NavigationExecutor(device, _from_device_init=True)
        device.verification_executor = VerificationExecutor(device, _from_device_init=True)
        device.exploration_executor = ExplorationExecutor(device, _from_device_init=True)
        device.standard_block_executor = StandardBlockExecutor(device)
        device.ai_builder = AIGraphBuilder(device)
        
    except Exception as e:
        print(f"[@controller_manager:_create_device_with_controllers] ❌ Failed to create service executors for device {device_id}: {e}")
        print(f"[@controller_manager:_create_device_with_controllers] ❌ Host name: {host_name}")
        print(f"[@controller_manager:_create_device_with_controllers] ❌ Device: {device}")
        import traceback
        print(f"[@controller_manager:_create_device_with_controllers] ❌ Full traceback: {traceback.format_exc()}")
        # Continue without executors - they can be created later if needed
    
    print(f"[@controller_manager:_create_device_with_controllers] ✓ Device {device_id} created with capabilities: {device.get_capabilities()}")
    return device


# Global host instance with thread safety
_host_instance: Optional[Host] = None
_host_creation_lock = threading.Lock()


def get_host(device_ids: List[str] = None, host_ip: str = None) -> Host:
    """
    Get the global host instance, creating it if necessary.
    Thread-safe singleton pattern.
    
    Args:
        device_ids: List of specific device IDs to create (None = all devices)
    
    Returns:
        Host instance
    """
    global _host_instance
    
    if _host_instance is None:
        with _host_creation_lock:
            # Double-check pattern
            if _host_instance is None:
                print("[@controller_manager:get_host] Creating new host instance")
                _host_instance = create_host_from_environment(device_ids, host_ip=host_ip)
            else:
                print("[@controller_manager:get_host] Using existing host instance (race condition avoided)")
    
    return _host_instance
