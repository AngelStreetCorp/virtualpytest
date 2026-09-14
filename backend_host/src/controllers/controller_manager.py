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
from backend_host.src.controllers.controller_config_factory import create_controller_configs_from_device_info

# Import controller classes
from backend_host.src.controllers.audiovideo.hdmi_stream import HDMIStreamController
from backend_host.src.controllers.audiovideo.vnc_stream import VNCStreamController
from backend_host.src.controllers.audiovideo.camera_stream import CameraStreamController
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


def create_host_from_environment(device_ids: List[str] = None) -> Host:
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
    host_ip = detect_host_ip()  # Use detection function (handles HOST_IP env var internally)
    host_port = int(os.getenv('HOST_PORT', '6109'))

    # Auto-construct host_url from HOST_NAME (or allow override)
    host_url = os.getenv('HOST_URL')
    if not host_url:
        # Auto-construct: /host/{hostname}
        host_url = f"/host/{host_name}"
        print(f"[@controller_manager:create_host_from_environment] Auto-constructed HOST_URL: {host_url}")
    
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
    # Uses nginx-proxied path: /host/{host_name}/vnc_lite.html?password={password}
    vnc_stream_path = os.getenv('HOST_VNC_STREAM_PATH')
    vnc_password = os.getenv('HOST_VNC_PASSWORD', 'admin1234')
    
    if not vnc_stream_path and video_capture_path:
        # Build nginx-proxied URL (works with any frontend domain)
        vnc_stream_path = f"/host/{host_name}/vnc_lite.html"
        if vnc_password:
            vnc_stream_path = f"{vnc_stream_path}?password={vnc_password}"
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
            'host_port': host_port  # Add host port for web controller
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
    
    print(f"[@controller_manager:create_host_from_environment] Host created with {host.get_device_count()} devices")
    return host


def _get_devices_config_from_environment() -> List[Dict[str, Any]]:
    """
    Extract device configurations from environment variables.
    
    Returns:
        List of device configurations
    """
    devices_config = []
    
    # Look for DEVICE1, DEVICE2, DEVICE3, DEVICE4
    for i in range(1, 13):
        device_name = os.getenv(f'DEVICE{i}_NAME')
        
        if device_name:

            # Extract all environment variables for this device.
            # DEVICE{i}_MODEL may be a bare model ('stb', 'android_tv') OR carry a
            # platform suffix after the first dash ('stb-example-v2'). The broad
            # model is everything before the first dash; the platform tag is the
            # rest. Bare values yield platform=None and identical pre-variant
            # behaviour. Reuses the existing .env field — no new keys.
            raw_model = os.getenv(f'DEVICE{i}_MODEL', 'unknown')
            device_model, _sep, device_platform = raw_model.partition('-')
            device_platform = device_platform or None
            video = os.getenv(f'DEVICE{i}_VIDEO')
            video_capture_path = os.getenv(f'DEVICE{i}_VIDEO_CAPTURE_PATH')
            
            # Auto-construct video_stream_path from HOST_NAME (or allow override)
            video_stream_path = os.getenv(f'DEVICE{i}_VIDEO_STREAM_PATH')
            if not video_stream_path and video_capture_path:
                # Auto-construct: /host/{hostname}/stream/device{N}
                video_stream_path = f"/host/{host_name}/stream/device{i}"
                print(f"[@controller_manager] Auto-constructed stream path for device{i}: {video_stream_path}")
            
            device_ip = os.getenv(f'DEVICE{i}_IP')
            device_port = os.getenv(f'DEVICE{i}_PORT')
            ir_path = os.getenv(f'DEVICE{i}_IR_PATH')
            ir_type = os.getenv(f'DEVICE{i}_IR_TYPE')
            # Networked IRTrans box (UDP). When IR_IP is set the device uses the
            # IRTrans transport instead of local lirc/ir-ctl (IR_PATH).
            ir_ip = os.getenv(f'DEVICE{i}_IR_IP')
            ir_port = os.getenv(f'DEVICE{i}_IR_PORT')
            ir_led = os.getenv(f'DEVICE{i}_IR_LED')
            ir_remote = os.getenv(f'DEVICE{i}_IR_REMOTE')
            ble_adapter_hci = os.getenv(f'DEVICE{i}_BLE_ADAPTER_HCI')
            ble_type = os.getenv(f'DEVICE{i}_BLE_TYPE')
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
                'video_stream_path': video_stream_path,
                'video_capture_path': video_capture_path,
                # Device IP/Port (used by both Android ADB and Appium - mutually exclusive)
                'device_ip': device_ip,
                'device_port': device_port,
                'ir_path': ir_path,
                'ir_type': ir_type,
                # IRTrans (networked) transport
                'ir_ip': ir_ip,
                'ir_port': ir_port,
                'ir_led': ir_led,
                'ir_remote': ir_remote,
                'ble_adapter_hci': ble_adapter_hci,
                'ble_type': ble_type,
                'bluetooth_device': bluetooth_device,
                'power_device': power_device,
                # Power configuration
                'power_name': power_name,
                'power_ip': power_ip,
                'power_email': power_email,
                'power_pwd': power_pwd,
                # API power (client REST API)
                'power_api_url': power_api_url,
                'power_api_key': power_api_key,
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

        # Remote Controllers
        elif controller_type == 'remote':
            if implementation == 'android_mobile':
                return AndroidMobileRemoteController(**params)
            elif implementation == 'android_tv':
                return AndroidTVRemoteController(**params)
            elif implementation == 'appium':
                return AppiumRemoteController(**params)
            elif implementation == 'ir_remote':
                return IRRemoteController(**params)
            elif implementation == 'irtrans_remote':
                from .remote.irtrans import IRTransRemoteController
                return IRTransRemoteController(**params)
            elif implementation == 'bluetooth_remote':
                from .remote.bluetooth import BluetoothRemoteController
                return BluetoothRemoteController(**params)


        # Verification Controllers - now require device_model
        elif controller_type == 'verification':
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

        # Power Controllers
        elif controller_type == 'power':
            if implementation == 'tapo':
                return TapoPowerController(**params)
            elif implementation == 'api_power':
                from .power.api_power import APIPowerController
                return APIPowerController(**params)

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

        # Add device_model for all verification controllers
        controller_params['device_model'] = device_model

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


def get_host(device_ids: List[str] = None) -> Host:
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
                _host_instance = create_host_from_environment(device_ids)
            else:
                print("[@controller_manager:get_host] Using existing host instance (race condition avoided)")
    
    return _host_instance