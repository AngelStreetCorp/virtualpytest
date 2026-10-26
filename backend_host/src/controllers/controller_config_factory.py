"""
Controller Configuration Factory

Simple hardcoded device-to-controller mapping.
Each device model has predefined controllers and verification capabilities.
"""

from shared.src.lib.utils.storage_path_utils import get_device_base_path
from shared.src.lib.config.device_capabilities import (
    DEVICE_CONTROLLER_MAP,
    CONTROLLER_VERIFICATION_MAP,
    get_device_capabilities,
    model_spelling_note,
    normalize_device_model
)

def create_controller_configs_from_device_info(device_config: dict) -> dict:
    """Create controller configurations for a device."""
    # DEVICE{i}_MODEL is typed by hand, so the model arrives spelled the way the operator
    # wrote it. Resolve it to the canonical DEVICE_CONTROLLER_MAP key before the lookup:
    # an unrecognised name misses the map and returns {} — a device registered with NO
    # controllers, so Take Control answers "Unsupported device" and no remote ever appears
    # (BUG-0749). `androidtv`, `andoridtv`, `appletv` and `firetv_vega` now build exactly
    # what `android_tv`, `apple_tv` and `fire_tv_vega` build.
    raw_model = device_config.get('model', device_config.get('device_model'))
    device_model = normalize_device_model(raw_model)

    spelling = model_spelling_note(raw_model, device_model)
    if spelling:
        print(f"[@controller_factory:create_controller_configs_from_device_info] model {spelling}")

    if device_model not in DEVICE_CONTROLLER_MAP:
        print(f"[@controller_factory:create_controller_configs_from_device_info] ERROR: Unknown device model: {device_model}")
        print(f"[@controller_factory:create_controller_configs_from_device_info] ERROR: Available models: {list(DEVICE_CONTROLLER_MAP.keys())}")
        return {}
    
    configs = {}
    device_mapping = DEVICE_CONTROLLER_MAP[device_model]
    created_controllers = []
    
    # Create AV controllers
    for av_impl in device_mapping['av']:
        configs['av'] = {
            'type': 'av',
            'implementation': av_impl,
            'params': _get_av_params(av_impl, device_config)
        }
        created_controllers.append(f"av:{av_impl}")
    
    # Create Remote controllers - support multiple remotes like desktop controllers.
    # An adb remote needs DEVICE{i}_IP or DEVICE{i}_ADB_SERIAL: without either, a Fire TV
    # driven by IRTrans alone would also get a dead adb remote (and adb verification).
    skipped_impls = set()
    for remote_impl in device_mapping['remote']:
        if remote_impl in ADB_REMOTES and not (device_config.get('device_ip') or device_config.get('adb_serial')):
            print(f"[@controller_factory:create_controller_configs_from_device_info] Skipping Remote controller {remote_impl} - no DEVICE_IP or ADB_SERIAL")
            skipped_impls.add(remote_impl)
            continue
        # Use unique keys for multiple remote controllers (like desktop controllers)
        if len(device_mapping['remote']) > 1:
            # Multiple remotes - use specific keys like remote_android_tv, remote_ir_remote
            configs[f'remote_{remote_impl}'] = {
                'type': 'remote',
                'implementation': remote_impl,
                'params': _get_remote_params(remote_impl, device_config)
            }
            created_controllers.append(f"remote:{remote_impl}")
        else:
            # Single remote - use standard 'remote' key for backward compatibility
            configs['remote'] = {
                'type': 'remote',
                'implementation': remote_impl,
                'params': _get_remote_params(remote_impl, device_config)
            }
            created_controllers.append(f"remote:{remote_impl}")
    
    # Create Desktop controllers
    for desktop_impl in device_mapping['desktop']:
        configs[f'desktop_{desktop_impl}'] = {
            'type': 'desktop',
            'implementation': desktop_impl,
            'params': _get_desktop_params(desktop_impl, device_config)
        }
        created_controllers.append(f"desktop:{desktop_impl}")
    
    # Create Web controllers
    for web_impl in device_mapping['web']:
        configs['web'] = {
            'type': 'web',
            'implementation': web_impl,
            'params': _get_web_params(web_impl, device_config)
        }
        created_controllers.append(f"web:{web_impl}")
    
    # Create Switch controllers (TASK-31 follow-up). Same single-key shape as
    # power (no array — only one switch controller per device today). The
    # `switch` slot is optional in DEVICE_CONTROLLER_MAP; .get(..., []) so
    # device models without a switch entry (android_mobile, stb, host_vnc, …)
    # get an empty list and no switch controller.
    for switch_impl in device_mapping.get('switch', []):
        configs['switch'] = {
            'type': 'switch',
            'implementation': switch_impl,
            'params': _get_av_params(switch_impl, device_config),  # same shape as AV params
        }
        created_controllers.append(f"switch:{switch_impl}")

    # Create Power controllers - only if required environment variables are present
    for power_impl in device_mapping['power']:
        # Check if required power configuration is present in environment
        power_name = device_config.get('power_name', '')
        power_ip = device_config.get('power_ip', '')
        power_email = device_config.get('power_email', '')
        power_pwd = device_config.get('power_pwd', '')
        
        if power_impl == 'tapo':
            # For Tapo controllers, require all necessary configuration
            if (power_name and 'tapo' in power_name.lower() and 
                power_ip and power_email and power_pwd):
                configs['power'] = {
                    'type': 'power',
                    'implementation': power_impl,
                    'params': _get_power_params(power_impl, device_config)
                }
                created_controllers.append(f"power:{power_impl}")
            else:
                print(f"[@controller_factory:create_controller_configs_from_device_info] Skipping Power controller {power_impl} - missing required configuration:")
                print(f"[@controller_factory:create_controller_configs_from_device_info]   power_name: {power_name}")
                print(f"[@controller_factory:create_controller_configs_from_device_info]   power_ip: {power_ip}")
                print(f"[@controller_factory:create_controller_configs_from_device_info]   power_email: {power_email}")
                print(f"[@controller_factory:create_controller_configs_from_device_info]   power_pwd: {'***' if power_pwd else 'None'}")
        elif power_impl == 'api_power':
            # API power (client REST API). Reuses power_name as the API device name;
            # requires the API URL + key. Without them this impl is skipped, so a
            # Tapo-configured device on the same model is never clobbered.
            power_api_url = device_config.get('power_api_url', '')
            power_api_key = device_config.get('power_api_key', '')
            if power_name and power_api_url and power_api_key:
                configs['power'] = {
                    'type': 'power',
                    'implementation': power_impl,
                    'params': _get_power_params(power_impl, device_config)
                }
                created_controllers.append(f"power:{power_impl}")
            else:
                print(f"[@controller_factory:create_controller_configs_from_device_info] Skipping Power controller {power_impl} - missing required configuration:")
                print(f"[@controller_factory:create_controller_configs_from_device_info]   power_name: {power_name}")
                print(f"[@controller_factory:create_controller_configs_from_device_info]   power_api_url: {power_api_url}")
                print(f"[@controller_factory:create_controller_configs_from_device_info]   power_api_key: {'***' if power_api_key else 'None'}")
        elif power_impl == 'wol':
            # Wake-on-LAN PC. POWER_MAC selects this transport; POWER_IP is the
            # SSH shutdown target and status probe. A Tapo / API device has no
            # POWER_MAC, so it is never clobbered.
            power_mac = device_config.get('power_mac', '')
            if power_mac and power_ip:
                configs['power'] = {
                    'type': 'power',
                    'implementation': power_impl,
                    'params': _get_power_params(power_impl, device_config)
                }
                created_controllers.append(f"power:{power_impl}")
            elif power_mac:
                print(f"[@controller_factory:create_controller_configs_from_device_info] Skipping Power controller {power_impl} - POWER_MAC set but POWER_IP missing")
    
    # Create Verification controllers (NEW!)
    verification_types = []
    for controller_list in device_mapping.values():
        for controller_impl in controller_list:
            if controller_impl in skipped_impls:
                continue
            verification_types.extend(CONTROLLER_VERIFICATION_MAP.get(controller_impl, []))
    
    # Remove duplicates and create verification controller configs
    for verification_impl in set(verification_types):
        configs[f'verification_{verification_impl}'] = {
            'type': 'verification',
            'implementation': verification_impl,
            'params': _get_verification_params(verification_impl, device_config)
        }
        created_controllers.append(f"verification:{verification_impl}")
    
    # Single consolidated log line
    controllers_summary = ", ".join(created_controllers)
    print(f"[@controller_factory:create_controller_configs_from_device_info] Created {len(configs)} controllers: {controllers_summary}")
    return configs

def get_controller_type_for_device(device_model: str, action_type: str) -> str:
    """
    Get the correct controller type for a device model and action type.
    
    Args:
        device_model: Device model (e.g., 'android_mobile', 'host_vnc')
        action_type: Action type ('remote', 'web', 'desktop', 'verification', etc.)
        
    Returns:
        Controller type key to use with get_controller()
    """
    # Same spelling tolerance as create_controller_configs_from_device_info, but silent:
    # this is a lookup called per action, and the correction was already logged when the
    # device was built.
    device_model = normalize_device_model(device_model)

    if device_model not in DEVICE_CONTROLLER_MAP:
        # Default routing for unknown device models
        if action_type == 'web':
            return 'web'
        elif action_type == 'desktop':
            return 'desktop_pyautogui'  # Default desktop controller
        elif action_type == 'verification':
            return 'verification_text'  # Default verification controller
        else:
            return 'remote'  # Default for unknown
    
    device_mapping = DEVICE_CONTROLLER_MAP[device_model]
    
    if action_type == 'remote':
        # Remote actions go to remote controller
        remote_implementations = device_mapping.get('remote', [])
        if remote_implementations:
            return 'remote'
        else:
            return None  # Device doesn't support remote actions
    
    elif action_type == 'web':
        # Web actions go to web controller
        web_implementations = device_mapping.get('web', [])
        if web_implementations:
            return 'web'
        else:
            return None  # Device doesn't support web actions
    
    elif action_type == 'desktop':
        # Desktop actions go to desktop controller (prefer bash, fallback to pyautogui)
        desktop_implementations = device_mapping.get('desktop', [])
        if 'bash' in desktop_implementations:
            return 'desktop_bash'
        elif 'pyautogui' in desktop_implementations:
            return 'desktop_pyautogui'
        else:
            return None  # Device doesn't support desktop actions
    
    elif action_type == 'verification':
        # Verification actions - determine based on available verification types
        verification_types = []
        for controller_list in device_mapping.values():
            for controller_impl in controller_list:
                verification_types.extend(CONTROLLER_VERIFICATION_MAP.get(controller_impl, []))
        
        # Default verification type selection based on device capabilities
        if 'adb' in verification_types:
            return 'verification_adb'
        elif 'image' in verification_types:
            return 'verification_image'
        elif 'text' in verification_types:
            return 'verification_text'
        else:
            return 'verification_text'  # Fallback
    
    elif action_type == 'av':
        # AV actions go to av controller
        av_implementations = device_mapping.get('av', [])
        if av_implementations:
            return 'av'
        else:
            return None
    
    elif action_type == 'power':
        # Power actions go to power controller
        power_implementations = device_mapping.get('power', [])
        if power_implementations:
            return 'power'
        else:
            return None
    
    elif action_type == 'ai':
        # AI actions go to ai controller
        ai_implementations = device_mapping.get('ai', [])
        if ai_implementations:
            return 'ai'
        else:
            return None
    
    # Unknown action type
    return None

# get_device_capabilities is now imported from shared.src.lib.config.device_capabilities

def _get_av_params(implementation: str, device_config: dict) -> dict:
    """Get parameters for AV controllers."""
    # Add the real device name and device_id to all AV controllers
    base_params = {
        'real_device_name': device_config.get('device_name', 'Unknown Device'),
        'device_id': device_config.get('device_id', 'unknown'),
        'video_device': device_config.get('video', '/dev/video0')  # Add video device for audio capture
    }
    
    if implementation == 'hdmi_stream':
        return {
            **base_params,
            'video_stream_path': device_config.get('video_stream_path', '/host/stream/capture1'),
            'video_capture_path': device_config.get('video_capture_path', get_device_base_path('capture1'))
        }
    elif implementation == 'camera_stream':
        return {
            **base_params,
            'video_stream_path': device_config.get('video_stream_path', '/host/camera/stream'),
            'video_capture_path': device_config.get('video_capture_path', get_device_base_path('camera'))
        }
    elif implementation == 'vnc_stream':
        return {
            **base_params,
            'video_stream_path': device_config.get('video_stream_path', '/host/vnc/stream'),
            'video_capture_path': device_config.get('video_capture_path', get_device_base_path('capture3')),
            'vnc_password': device_config.get('vnc_password'),
            'web_browser_path': device_config.get('web_browser_path', '/usr/bin/chromium')
        }
    elif implementation == 'rtsp_stream':
        # RTSP / HLS / MJPEG network stream controller (TASK-31).
        # The URL is taken from the standard DEVICE{i}_VIDEO so the vpt-stream
        # watcher can resolve it; rtsp_url/hls_url/mjpeg_url/youtube_url are
        # honoured when set explicitly (e.g. by a feature plugin).
        return {
            **base_params,
            'video_stream_path': device_config.get('video_stream_path', '/host/stream/rtsp_video'),
            'video_capture_path': device_config.get('video_capture_path', get_device_base_path('rtsp_video')),
            'rtsp_url': device_config.get('rtsp_url') or device_config.get('video'),
            'hls_url': device_config.get('hls_url'),
            'mjpeg_url': device_config.get('mjpeg_url'),
            'youtube_url': device_config.get('youtube_url'),
            'loop': device_config.get('stream_loop', True),
        }
    elif implementation == 'video_stream':
        # Local / HTTP(S) video file controller (TASK-31).
        # video_file_path falls back to device_config['video'] (DEVICE{i}_VIDEO) so
        # the same env var that tells run_ffmpeg.sh the source also reaches the
        # controller for status reporting.
        return {
            **base_params,
            'video_stream_path': device_config.get('video_stream_path', '/host/stream/local_video'),
            'video_capture_path': device_config.get('video_capture_path', get_device_base_path('local_video')),
            'video_file_path': device_config.get('video_file_path') or device_config.get('video'),
            'loop': device_config.get('stream_loop', True),
        }
    # TASK-31: switch controller params. 'hdmi_switch' is the placeholder;
    # 'bluetooth_procon' takes the vpt-procon daemon URL + token
    # (DEVICE{i}_SWITCH_PROCON_URL / _TOKEN; default: local daemon, no token).
    elif implementation == 'hdmi_switch':
        return {
            **base_params,
            'switch_type': device_config.get('switch_type', 'unknown'),
            'switch_host': device_config.get('switch_host'),
            'switch_port': device_config.get('switch_port'),
            'switch_inputs': device_config.get('switch_inputs', []),
            'usb_device': device_config.get('usb_device'),
        }
    elif implementation == 'bluetooth_procon':
        return {
            **base_params,
            'daemon_url': device_config.get('switch_procon_url') or 'http://127.0.0.1:6190',
            'token': device_config.get('switch_procon_token'),
        }
    return base_params

# Remotes that reach the device over adb (ip:port or USB serial).
ADB_REMOTES = ('android_mobile', 'android_tv', 'vega')


def _get_remote_params(implementation: str, device_config: dict) -> dict:
    """Get parameters for Remote controllers."""
    # Getting remote params for implementation: {implementation}

    # Feature-registered implementations (controller_registry.py) build their own
    # params from the flat device config; a registration without a builder gets {}.
    from backend_host.src.controllers.controller_registry import get_remote_implementation
    registered = get_remote_implementation(implementation)
    if registered is not None:
        builder = registered.get('params_builder')
        return dict(builder(device_config)) if builder else {}

    if implementation in ['android_mobile', 'android_tv', 'vega']:
        params = {
            'device_ip': device_config.get('device_ip', '192.168.1.100'),
            'device_port': device_config.get('device_port', 5555),
            # USB serial (DEVICE<N>_ADB_SERIAL) takes priority over ip:port when set
            'adb_serial': device_config.get('adb_serial')
        }
        # Android params configured
        return params
    elif implementation == 'appium':
        params = {
            'appium_platform_name': device_config.get('appium_platform_name'),
            'appium_device_id': device_config.get('appium_device_id'),
            'appium_server_url': device_config.get('appium_server_url', 'http://localhost:4723')
        }
        # Appium params configured
        return params
    elif implementation == 'ir_remote':
        ir_path = device_config.get('ir_path')
        ir_type = device_config.get('ir_type')
        
        # Check for missing IR configuration and provide helpful error message
        missing_vars = []
        if not ir_path:
            missing_vars.append('DEVICE1_IR_PATH')
        if not ir_type:
            missing_vars.append('DEVICE1_IR_TYPE')
            
        if missing_vars:
            device_id = device_config.get('device_id', 'DEVICE1')
            device_num = device_id.replace('device', '').upper()
            missing_env_vars = [var.replace('DEVICE1', f'DEVICE{device_num}') for var in missing_vars]
            
            print(f"[@controller_factory:_get_remote_params] WARNING: Missing IR configuration for {device_id} - skipping IR remote controller")
            print(f"[@controller_factory:_get_remote_params] WARNING: To enable IR remote, set these environment variables:")
            for var in missing_env_vars:
                if 'IR_PATH' in var:
                    print(f"[@controller_factory:_get_remote_params] WARNING:   {var}=/dev/lirc0  # Path to your IR device")
                elif 'IR_TYPE' in var:
                    print(f"[@controller_factory:_get_remote_params] WARNING:   {var}=apple_tv   # IR config type (apple_tv, samsung, fire_tv, stb)")
            print(f"[@controller_factory:_get_remote_params] WARNING: Available IR types: apple_tv, samsung, fire_tv, stb")
            
            # Return special marker to indicate this controller should be skipped
            return {'_skip_controller': True, 'reason': 'Missing IR configuration'}
        
        params = {
            'ir_path': ir_path,
            'ir_type': ir_type
        }
        # IR remote params configured
        return params
    elif implementation == 'irtrans_remote':
        ir_ip = device_config.get('ir_ip')
        ir_remote = device_config.get('ir_remote')
        ir_type = device_config.get('ir_type')

        # Check for missing IRTrans configuration and provide a helpful message
        missing_vars = []
        if not ir_ip:
            missing_vars.append('DEVICE1_IR_IP')
        if not ir_type:
            missing_vars.append('DEVICE1_IR_TYPE')

        if missing_vars:
            device_id = device_config.get('device_id', 'DEVICE1')
            device_num = device_id.replace('device', '').upper()
            missing_env_vars = [var.replace('DEVICE1', f'DEVICE{device_num}') for var in missing_vars]

            print(f"[@controller_factory:_get_remote_params] WARNING: Missing IRTrans configuration for {device_id} - skipping irtrans_remote controller")
            print(f"[@controller_factory:_get_remote_params] WARNING: To enable the IRTrans (networked) remote, set:")
            for var in missing_env_vars:
                if 'IR_IP' in var:
                    print(f"[@controller_factory:_get_remote_params] WARNING:   {var}=<irtrans-box-ip>  # IRTrans box IP")
                elif 'IR_TYPE' in var:
                    print(f"[@controller_factory:_get_remote_params] WARNING:   {var}=stb  # keymap under remote/irtrans_conf/ (with IR_REMOTE) or remote/ir_conf/")
            print(f"[@controller_factory:_get_remote_params] WARNING: Optional: DEVICE{device_num}_IR_PORT=21000 (default), DEVICE{device_num}_IR_LED=1 (IR output 1-16)")
            print(f"[@controller_factory:_get_remote_params] WARNING: Optional: DEVICE{device_num}_IR_REMOTE=STB_remote (learned remote in the box; unset sends the raw ir_conf codes)")

            return {'_skip_controller': True, 'reason': 'Missing IRTrans configuration'}

        params = {
            'ir_ip': ir_ip,
            'ir_remote': ir_remote,
            'ir_type': ir_type,
            'ir_port': device_config.get('ir_port') or 21000,
            'ir_led': device_config.get('ir_led'),
        }
        return params
    elif implementation == 'irtoy_remote':
        # USB IR Toy / Irdroid (04d8:fd08) over its CDC serial node. This is the
        # transport for non-Pi hosts: a stock Debian x86 kernel ships no
        # CONFIG_IR_TOY, so the kernel never claims the dongle for IR, cdc_acm
        # takes it as /dev/ttyACM*, and no /dev/lirc* that ir-ctl could use can
        # ever exist. We write the waveform to the serial port ourselves.
        ir_serial = device_config.get('ir_serial')
        ir_type = device_config.get('ir_type')

        missing_vars = []
        if not ir_serial:
            missing_vars.append('DEVICE1_IR_SERIAL')
        if not ir_type:
            missing_vars.append('DEVICE1_IR_TYPE')

        if missing_vars:
            device_id = device_config.get('device_id', 'DEVICE1')
            device_num = device_id.replace('device', '').upper()
            missing_env_vars = [var.replace('DEVICE1', f'DEVICE{device_num}') for var in missing_vars]

            print(f"[@controller_factory:_get_remote_params] WARNING: Missing IRToy configuration for {device_id} - skipping irtoy_remote controller")
            print(f"[@controller_factory:_get_remote_params] WARNING: To enable the USB IR Toy remote, set:")
            for var in missing_env_vars:
                if 'IR_SERIAL' in var:
                    print(f"[@controller_factory:_get_remote_params] WARNING:   {var}=/dev/irtoy  # udev symlink for the 04d8:fd08 dongle")
                elif 'IR_TYPE' in var:
                    print(f"[@controller_factory:_get_remote_params] WARNING:   {var}=stb  # keymap under remote/ir_conf/")
            print(f"[@controller_factory:_get_remote_params] WARNING: Install the udev rule first: setup/local/linux/backend_host/udev/95-vpt-irtoy.rules")

            return {'_skip_controller': True, 'reason': 'Missing IRToy configuration'}

        params = {
            'ir_serial': ir_serial,
            'ir_type': ir_type,
        }
        return params
    elif implementation == 'bluetooth_remote':
        ble_adapter_hci = device_config.get('ble_adapter_hci') or 'hci0'
        ble_type = device_config.get('ble_type')

        if not ble_type:
            device_id = device_config.get('device_id', 'DEVICE1')
            device_num = device_id.replace('device', '').upper()
            print(f"[@controller_factory:_get_remote_params] WARNING: Missing BLE configuration for {device_id} - skipping bluetooth_remote controller")
            print(f"[@controller_factory:_get_remote_params] WARNING: To enable BLE remote, set: DEVICE{device_num}_BLE_TYPE=arris  # profile under bluetooth/ble_conf/")
            print(f"[@controller_factory:_get_remote_params] WARNING: Optional: DEVICE{device_num}_BLE_ADAPTER_HCI=hci0 (default hci0)")
            return {'_skip_controller': True, 'reason': 'Missing BLE configuration'}

        params = {
            'adapter_hci': ble_adapter_hci,
            'ble_type': ble_type,
            'ble_mac': device_config.get('ble_mac'),
        }
        return params
    elif implementation == 'tello':
        tello_ip = device_config.get('tello_ip')

        if not tello_ip:
            device_id = device_config.get('device_id', 'DEVICE1')
            device_num = device_id.replace('device', '').upper()
            print(f"[@controller_factory:_get_remote_params] WARNING: Missing Tello configuration for {device_id} - skipping tello controller")
            print(f"[@controller_factory:_get_remote_params] WARNING: To enable the Tello remote, set: DEVICE{device_num}_TELLO_IP=<drone-address>  # 192.168.10.1, or 10.200.<n>.2 with scripts/drone/tello_netns.sh")
            print(f"[@controller_factory:_get_remote_params] WARNING: Optional: DEVICE{device_num}_TELLO_STATE_PORT=8890 (8889+n), DEVICE{device_num}_TELLO_VIDEO_PORT=11111 (11110+n)")
            print(f"[@controller_factory:_get_remote_params] WARNING: Two drones on one host also need DEVICE{device_num}_TELLO_LOCAL_IP=192.168.10.<n> (per-radio source address, scripts/drone/tello_prio.sh)")
            return {'_skip_controller': True, 'reason': 'Missing Tello configuration'}

        return {
            'tello_ip': tello_ip,
            'cmd_port': int(device_config.get('tello_cmd_port') or 8889),
            'state_port': int(device_config.get('tello_state_port') or 8890),
            'video_port': int(device_config.get('tello_video_port') or 11111),
            # Source address the drone's radio is reached from. Needed as soon as two dongles sit
            # on one host: both Tello APs answer to 192.168.10.1, so without a per-drone source the
            # kernel picks one radio for both. scripts/drone/tello_prio.sh pairs the address here
            # with an `ip rule from`, which is what keeps the two links apart.
            'local_ip': device_config.get('tello_local_ip') or '0.0.0.0',
            # The port the client binds locally for this drone's conversation. A drone
            # behind the host's drone bridge (TASK-160) needs its own, or two bridged
            # drones on one host would share one local port.
            'local_cmd_port': int(device_config.get('tello_local_cmd_port') or 8889),
            'name': device_config.get('device_name') or 'tello',
            'device_id': device_config.get('device_id', ''),
        }

    elif implementation == 'samsung_tizen':
        tizen_ip = device_config.get('tizen_ip')
        if not tizen_ip:
            device_id = device_config.get('device_id', 'DEVICE1')
            device_num = device_id.replace('device', '').upper()
            print(f"[@controller_factory:_get_remote_params] WARNING: Missing Tizen configuration for {device_id} - skipping samsung_tizen remote")
            print(f"[@controller_factory:_get_remote_params] WARNING: To enable the Samsung Tizen network remote, set: DEVICE{device_num}_TIZEN_IP=<tv-ip>")
            print(f"[@controller_factory:_get_remote_params] WARNING: Optional: DEVICE{device_num}_TIZEN_PORT=8002, DEVICE{device_num}_TIZEN_TOKEN=<cached>, DEVICE{device_num}_TIZEN_TOKEN_FILE=<path>")
            return {'_skip_controller': True, 'reason': 'Missing Tizen configuration'}

        params = {
            'tv_ip': tizen_ip,
            'tv_port': int(device_config.get('tizen_port') or 8002),
            'device_name': device_config.get('device_name') or 'Samsung Tizen TV',
        }
        if device_config.get('tizen_token'):
            params['token'] = device_config.get('tizen_token')
        if device_config.get('tizen_token_file'):
            params['token_file'] = device_config.get('tizen_token_file')
        return params

    # Unknown implementation, returning empty params
    return {}

def _get_desktop_params(implementation: str, device_config: dict) -> dict:
    """Get parameters for Desktop controllers."""
    # Getting desktop params for implementation: {implementation}
    
    if implementation == 'bash':
        params = {
            'host_ip': device_config.get('host_ip', '127.0.0.1'),
            'host_port': device_config.get('host_port', 22),
            'host_user': device_config.get('host_user', 'root')
        }
        # Bash params configured
        return params
    elif implementation == 'pyautogui':
        params = {}  # PyAutoGUI works locally, no connection parameters needed
        # PyAutoGUI params configured
        return params
    elif implementation == 'powershell':
        params = {
            'host_ip': device_config.get('host_ip', '127.0.0.1'),
            'host_port': device_config.get('host_port', 22),
            'host_user': device_config.get('host_user', 'Administrator')
        }
        # PowerShell params configured
        return params
    
    # Unknown implementation, returning empty params
    return {}

def _get_web_params(implementation: str, device_config: dict) -> dict:
    """Get parameters for Web controllers."""
    # Getting web params for implementation: {implementation}
    
    if implementation == 'playwright':
        params = {}
        # Playwright params configured
        return params
    elif implementation == 'selenium':
        params = {
            'selenium_url': device_config.get('selenium_url', 'http://localhost:4444/wd/hub'),
            'selenium_browser': device_config.get('selenium_browser', 'chrome')
        }
        # Selenium params configured
        return params
    
    # Unknown implementation, returning empty params
    return {}

def _get_power_params(implementation: str, device_config: dict) -> dict:
    """Get parameters for Power controllers."""
    # Getting power params for implementation: {implementation}
    
    if implementation == 'tapo':
        params = {
            'device_ip': device_config.get('power_ip'),
            'email': device_config.get('power_email'),
            'password': device_config.get('power_pwd')
        }
        # Tapo params configured
        return params
    elif implementation == 'api_power':
        params = {
            'api_url': device_config.get('power_api_url'),
            'device_name': device_config.get('power_name'),   # reused as API device name
            'api_key': device_config.get('power_api_key'),
        }
        return params
    elif implementation == 'wol':
        params = {
            'mac': device_config.get('power_mac'),
            'device_ip': device_config.get('power_ip'),
            'ssh_user': device_config.get('power_ssh_user'),
            'ssh_port': device_config.get('power_ssh_port') or 22,
            'broadcast': device_config.get('power_broadcast') or '255.255.255.255',
        }
        return params

    # Unknown implementation, returning empty params
    return {}

def _get_verification_params(implementation: str, device_config: dict) -> dict:
    """Get parameters for Verification controllers."""
    if implementation in ['image', 'text', 'video']:
        # Image, text, and video verification controllers need av_controller dependency
        # This will be injected by the controller manager
        return {}
    elif implementation == 'adb':
        # ADB verification controller needs device connection info
        return {
            'device_ip': device_config.get('device_ip', '192.168.1.100'),
            'device_port': device_config.get('device_port', 5555),
            'adb_serial': device_config.get('adb_serial')
        }
    elif implementation == 'appium':
        # Appium verification controller needs Appium server info
        return {
            'appium_platform_name': device_config.get('appium_platform_name'),
            'appium_device_id': device_config.get('appium_device_id'),
            'appium_server_url': device_config.get('appium_server_url', 'http://localhost:4723')
        }
    return {}

