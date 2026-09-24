"""
Real Android TV Remote Controller Implementation

This controller provides real Android TV remote control functionality using ADB.
Connects directly to Android TV devices via ADB.
"""

# get_installed_apps()'s return type hint below names AndroidApp, which is only
# importable when the guarded `from ...adb_utils import ADBUtils` succeeds (see
# ADB_AVAILABLE below) — deferring annotations to strings avoids a NameError at
# class-definition time when ADB isn't installed, the same bug class fixed in
# backend_host/src/lib/utils/appium_utils.py on 2026-09-07.
from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple, Union
import subprocess
import time
import json
import os
from pathlib import Path
from ..base_controller import RemoteControllerInterface

# Import ADB utilities from shared library
import sys
import os
# Get path to shared/lib/utils (go up to project root)
# Import local utilities

try:
    from  backend_host.src.lib.utils.adb_utils import ADBUtils
    ADB_AVAILABLE = True
except ImportError:
    print("Warning: ADB utilities not available. ADB functionality will be limited.")
    ADB_AVAILABLE = False


class AndroidTVRemoteController(RemoteControllerInterface):
    """Real Android TV remote controller using ADB commands."""
    
    @staticmethod
    def get_remote_config() -> Dict[str, Any]:
        """Get the remote configuration including layout, buttons, and image."""
        # Load configuration from JSON file
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            'config', 'remote', 'android_tv_remote.json'
        )
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Android TV remote config file not found at: {config_path}")
            
        try:
            print(f"Loading Android TV remote config from: {config_path}")
            with open(config_path, 'r') as config_file:
                return json.load(config_file)
        except Exception as e:
            raise RuntimeError(f"Error loading Android TV remote config from file: {e}")
    
    def __init__(self, device_ip: str = None, device_port: int = 5555, adb_serial: str = None, **kwargs):
        """
        Initialize the Android TV remote controller.

        Args:
            device_ip: Android TV device IP address (ADB over TCP, DEVICE<N>_IP)
            device_port: ADB port (default: 5555)
            adb_serial: USB ADB serial (DEVICE<N>_ADB_SERIAL). When set it is used as
                        the `adb -s` target instead of ip:port (USB hub / phone farm).
        """
        super().__init__("Android TV", "android_tv")

        # Android TV device parameters
        self.device_ip = device_ip
        self.device_port = device_port
        self.adb_serial = adb_serial

        # Validate required parameters
        if not self.device_ip and not self.adb_serial:
            raise ValueError("device_ip or adb_serial is required for AndroidTVRemoteController")

        self.android_device_id = self.adb_serial or f"{self.device_ip}:{self.device_port}"
        self.adb_utils = None
        self.device_resolution = None
        
        print(f"[@controller:AndroidTVRemote] Initialized for {self.android_device_id}")
        self.connect()
        
    def connect(self) -> bool:
        """Connect to the Android TV device via ADB."""
        try:
            print(f"Remote[{self.device_type.upper()}]: Connecting to Android device {self.android_device_id}")
            
            if not ADB_AVAILABLE:
                print(f"Remote[{self.device_type.upper()}]: ERROR - ADB utilities not available")
                return False
            
            # Step 1: Initialize ADB utilities
            self.adb_utils = ADBUtils()
            
            # Step 2: Connect to Android device via ADB
            if not self.adb_utils.connect_device(self.android_device_id):
                print(f"Remote[{self.device_type.upper()}]: Failed to connect to Android device {self.android_device_id}")
                self.disconnect()
                return False
                
            print(f"Remote[{self.device_type.upper()}]: Successfully connected to Android device {self.android_device_id}")
            
            # Step 3: Get device resolution
            self.device_resolution = self.adb_utils.get_device_resolution(self.android_device_id)
            if self.device_resolution:
                print(f"Remote[{self.device_type.upper()}]: Device resolution: {self.device_resolution['width']}x{self.device_resolution['height']}")
            
            self.is_connected = True
            return True
            
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Connection error: {e}")
            self.disconnect()
            return False
            
    def disconnect(self) -> bool:
        """Disconnect from Android device."""
        try:
            self.adb_utils = None
            self.is_connected = False
            
            print(f"Remote[{self.device_type.upper()}]: Disconnected successfully")
            return True
            
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Disconnect error: {e}")
            self.is_connected = False
            return False
            
    def press_key(self, key: str) -> bool:
        """
        Send a key press to the Android TV.
        
        Args:
            key: Key name (e.g., "UP", "DOWN", "OK", "HOME")
        """
        if not self.is_connected or not self.adb_utils:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected to device")
            return False
            
        try:
            print(f"Remote[{self.device_type.upper()}]: Pressing key '{key}'")
            
            success = self.adb_utils.execute_key_command(self.android_device_id, key)
            
            if success:
                print(f"Remote[{self.device_type.upper()}]: Successfully pressed key '{key}'")
            else:
                print(f"Remote[{self.device_type.upper()}]: Failed to press key '{key}'")
                
            return success
            
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Key press error: {e}")
            return False
            
    def input_text(self, text: str) -> bool:
        """
        Send text input to the Android TV.
        
        Args:
            text: Text to input
        """
        if not self.is_connected or not self.adb_utils:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected to device")
            return False
            
        try:
            print(f"Remote[{self.device_type.upper()}]: Inputting text: '{text}'")
            
            success = self.adb_utils.input_text(self.android_device_id, text)
            
            if success:
                print(f"Remote[{self.device_type.upper()}]: Successfully input text")
            else:
                print(f"Remote[{self.device_type.upper()}]: Failed to input text")
                
            return success
            
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Text input error: {e}")
            return False
            
    def launch_app(self, package_name: str) -> bool:
        """
        Launch an app by package name.
        
        Args:
            package_name: Android package name (e.g., "com.android.settings")
        """
        if not self.is_connected or not self.adb_utils:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected to device")
            return False
            
        try:
            print(f"Remote[{self.device_type.upper()}]: Launching app: {package_name}")
            
            success = self.adb_utils.launch_app(self.android_device_id, package_name)
            
            if success:
                print(f"Remote[{self.device_type.upper()}]: Successfully launched {package_name}")
            else:
                print(f"Remote[{self.device_type.upper()}]: Failed to launch {package_name}")
                
            return success
            
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: App launch error: {e}")
            return False
            
    def close_app(self, package_name: str) -> bool:
        """
        Close/stop an app by package name.
        
        Args:
            package_name: Android package name (e.g., "com.android.settings")
        """
        if not self.is_connected or not self.adb_utils:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected to device")
            return False
            
        try:
            print(f"Remote[{self.device_type.upper()}]: Closing app: {package_name}")
            
            success = self.adb_utils.close_app(self.android_device_id, package_name)
            
            if success:
                print(f"Remote[{self.device_type.upper()}]: Successfully closed {package_name}")
            else:
                print(f"Remote[{self.device_type.upper()}]: Failed to close {package_name}")
                
            return success
            
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: App close error: {e}")
            return False
            
    def kill_app(self, package_name: str) -> bool:
        """
        Kill an app by package name (alias for close_app).
        
        Args:
            package_name: Android package name (e.g., "com.netflix.ninja")
        """
        return self.close_app(package_name)
            
    def tap_coordinates(self, x: int, y: int) -> bool:
        """
        Tap at specific coordinates on the screen.
        
        Args:
            x: X coordinate
            y: Y coordinate
        """
        if not self.is_connected or not self.adb_utils:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected to device")
            return False
            
        try:
            print(f"Remote[{self.device_type.upper()}]: Tapping at coordinates ({x}, {y})")
            
            success = self.adb_utils.tap_coordinates(self.android_device_id, x, y)
            
            if success:
                print(f"Remote[{self.device_type.upper()}]: Successfully tapped at ({x}, {y})")
            else:
                print(f"Remote[{self.device_type.upper()}]: Failed to tap at ({x}, {y})")
                
            return success
            
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Coordinate tap error: {e}")
            return False
            
    def click_element(self, element_identifier: str) -> bool:
        """
        Click element directly by text, resource_id, or content_desc using ADB command.
        Supports pipe-separated fallback: "Settings|Preferences|Options"

        Args:
            element_identifier: Text, resource ID, or content description to click
                                Can use pipe "|" to specify multiple options (tries each until one succeeds)

        Returns:
            bool: True if click successful
        """
        if not self.is_connected or not self.adb_utils:
            self.last_error = "Not connected to device"
            print(f"Remote[{self.device_type.upper()}]: ERROR - {self.last_error}")
            return False

        try:
            print(f"Remote[{self.device_type.upper()}]: Direct click on element: '{element_identifier}'")

            # Parse pipe-separated terms for fallback support
            terms = [t.strip() for t in element_identifier.split('|')] if '|' in element_identifier else [element_identifier]

            if len(terms) > 1:
                print(f"Remote[{self.device_type.upper()}]: Using fallback strategy with {len(terms)} terms: {terms}")

            # Try each term until one succeeds
            last_error = None
            for i, term in enumerate(terms):
                if len(terms) > 1:
                    print(f"Remote[{self.device_type.upper()}]: Attempt {i+1}/{len(terms)}: Searching for '{term}'")

                # Find element using single UI dump
                exists, element, error = self.adb_utils.check_element_exists(self.android_device_id, term)

                if exists and element:
                    # Directly click the found element instead of re-searching (avoids double UI dump)
                    success = self.adb_utils.click_element(self.android_device_id, element)

                    if success:
                        if len(terms) > 1:
                            print(f"Remote[{self.device_type.upper()}]: Successfully clicked using term '{term}'")
                        else:
                            print(f"Remote[{self.device_type.upper()}]: Successfully clicked element: '{element_identifier}'")
                        self.last_error = None
                        return True
                    else:
                        last_error = f"Element found but click failed for '{term}'"
                        print(f"Remote[{self.device_type.upper()}]: {last_error}")
                        # Continue to next term
                else:
                    last_error = error or f"Element not found: '{term}'"
                    if len(terms) > 1:
                        print(f"Remote[{self.device_type.upper()}]: Term '{term}' not found, trying next...")
            
            # All terms failed
            print(f"Remote[{self.device_type.upper()}]: All terms failed. Last error: {last_error}")
            self.last_error = last_error or f"Element '{element_identifier}' not found"
            return False

        except Exception as e:
            error_msg = f"Element click error: {str(e)}"
            print(f"Remote[{self.device_type.upper()}]: {error_msg}")
            self.last_error = error_msg
            return False

    def get_installed_apps(self) -> List[AndroidApp]:
        """Get list of launcher-visible apps on the device.

        Returns AndroidApp objects, not dicts — host_remote_routes.py's
        /getApps does `app.package_name`/`app.label` on whatever this
        returns, matching android_mobile.py's and appium_remote.py's
        get_installed_apps() (both also return objects). This method used
        to pre-convert to `{'packageName': ..., 'label': ...}` dicts, which
        made every real /getApps call on an android_tv device 500 with
        "'dict' object has no attribute 'package_name'" (found 2026-09-07
        live-testing this suite's own hardware).
        """
        if not self.is_connected:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected to device")
            return []

        try:
            if self.adb_utils:
                return self.adb_utils.get_installed_apps(self.android_device_id, self.device_type)

            print(f"Remote[{self.device_type.upper()}]: ADB utils not available")
            return []

        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Error getting apps: {e}")
            return []
            
    def take_screenshot(self) -> Tuple[bool, str, str]:
        """
        Take a screenshot of the Android TV device.
        
        Returns:
            tuple: (success, base64_screenshot_data, error_message)
        """
        if not self.is_connected or not self.adb_utils:
            return False, "", "Not connected to device"
            
        try:
            print(f"Remote[{self.device_type.upper()}]: Taking screenshot")
            
            # Use ADB to take screenshot and get base64 data
            success, screenshot_data, error = self.adb_utils.take_screenshot(self.android_device_id)
            
            if success:
                print(f"Remote[{self.device_type.upper()}]: Screenshot captured successfully")
                return True, screenshot_data, ""
            else:
                print(f"Remote[{self.device_type.upper()}]: Screenshot failed: {error}")
                return False, "", error
                
        except Exception as e:
            error_msg = f"Screenshot error: {e}"
            print(f"Remote[{self.device_type.upper()}]: {error_msg}")
            return False, "", error_msg
        
    def get_status(self) -> Dict[str, Any]:
        """Get controller status information with ADB device verification."""
        try:
            # Basic status info
            base_status = {
                'success': True,
                'controller_type': self.controller_type,
                'device_type': self.device_type,
                'device_name': self.device_name,
                'device_ip': self.device_ip,
                'device_port': self.device_port,
                'adb_device': self.android_device_id,
                'connected': self.is_connected,
                'device_resolution': self.device_resolution,
                'supported_keys': list(ADBUtils.ADB_KEYS.keys()) if self.adb_utils else [],
                'capabilities': [
                    'adb_control', 'navigation', 'text_input', 
                    'app_launch', 'app_close', 'coordinate_tap', 'media_control', 'volume_control', 'channel_control', 'power_control'
                ]
            }
            
            # Check ADB device connectivity if we have device IP and are connected
            if self.android_device_id and self.is_connected:
                import subprocess
                
                # Run adb devices to check connectivity
                adb_result = subprocess.run(
                    ['adb', 'devices'], 
                    capture_output=True, 
                    text=True
                )
                
                if adb_result.returncode != 0:
                    base_status.update({
                        'adb_status': 'command_failed',
                        'adb_connected': False,
                        'message': 'ADB command failed'
                    })
                    return base_status
                
                # Parse adb devices output
                device_lines = [line.strip() for line in adb_result.stdout.split('\n') 
                              if line.strip() and not line.startswith('List of devices')]
                
                device_found = None
                device_status = None
                
                for line in device_lines:
                    if self.android_device_id in line:
                        device_found = line
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            device_status = parts[1].strip()
                        break
                
                if not device_found:
                    base_status.update({
                        'adb_status': 'device_not_found',
                        'adb_connected': False,
                        'message': f'Device {self.android_device_id} not found in ADB devices list',
                        'available_devices': device_lines
                    })
                elif device_status != 'device':
                    base_status.update({
                        'adb_status': f'device_{device_status}',
                        'adb_connected': False,
                        'message': f'Device {self.android_device_id} status is {device_status}, expected "device"',
                        'device_found': device_found
                    })
                else:
                    base_status.update({
                        'adb_status': 'device_connected',
                        'adb_connected': True,
                        'message': f'Device {self.android_device_id} is connected and ready',
                        'device_status': device_status
                    })
            else:
                base_status.update({
                    'adb_status': 'not_applicable',
                    'adb_connected': False,
                    'message': 'No device IP provided or not connected'
                })
            
            return base_status
            
        except Exception as e:
            return {
                'success': False,
                'controller_type': self.controller_type,
                'device_name': self.device_name,
                'adb_status': 'error',
                'adb_connected': False,
                'error': f'Failed to check ADB device status: {str(e)}'
            }
    
    def get_available_actions(self) -> Dict[str, Any]:
        """Get available actions for this Android TV controller."""
        return {
            'remote': [
                # Navigation actions
                {
                    'id': 'press_key_up',
                    'label': 'Up',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'UP'},
                    'description': 'Navigate up in the interface',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_down',
                    'label': 'Down',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'DOWN'},
                    'description': 'Navigate down in the interface',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_left',
                    'label': 'Left',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'LEFT'},
                    'description': 'Navigate left in the interface',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_right',
                    'label': 'Right',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'RIGHT'},
                    'description': 'Navigate right in the interface',
                    'requiresInput': False
                },
                # Control actions
                {
                    'id': 'press_key_ok',
                    'label': 'Select/OK',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'OK'},
                    'description': 'Select current item or confirm action',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_back',
                    'label': 'Back',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'BACK'},
                    'description': 'Go back to previous screen',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_home',
                    'label': 'Home',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'HOME'},
                    'description': 'Go to home screen',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_menu',
                    'label': 'Menu',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'MENU'},
                    'description': 'Open context menu',
                    'requiresInput': False
                },
                # Media control actions
                {
                    'id': 'press_key_play_pause',
                    'label': 'Play/Pause',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'MEDIA_PLAY_PAUSE'},
                    'description': 'Toggle play/pause for media',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_stop',
                    'label': 'Stop',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'MEDIA_STOP'},
                    'description': 'Stop media playback',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_fast_forward',
                    'label': 'Fast Forward',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'MEDIA_FAST_FORWARD'},
                    'description': 'Fast forward media',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_rewind',
                    'label': 'Rewind',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'MEDIA_REWIND'},
                    'description': 'Rewind media',
                    'requiresInput': False
                },
                # Channel control actions
                {
                    'id': 'press_key_channel_up',
                    'label': 'Channel Up',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'CHANNEL_UP'},
                    'description': 'Change to next channel',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_channel_down',
                    'label': 'Channel Down',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'CHANNEL_DOWN'},
                    'description': 'Change to previous channel',
                    'requiresInput': False
                },
                # Volume control actions
                {
                    'id': 'press_key_volume_up',
                    'label': 'Volume Up',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'VOLUME_UP'},
                    'description': 'Increase volume',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_volume_down',
                    'label': 'Volume Down',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'VOLUME_DOWN'},
                    'description': 'Decrease volume',
                    'requiresInput': False
                },
                {
                    'id': 'press_key_mute',
                    'label': 'Mute',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'VOLUME_MUTE'},
                    'description': 'Toggle mute',
                    'requiresInput': False
                },
                # Text input actions
                {
                    'id': 'input_text',
                    'label': 'Input Text',
                    'command': 'input_text',
                    'action_type': 'remote',
                    'params': {},
                    'description': 'Type text into current field',
                    'requiresInput': True,
                    'inputLabel': 'Text to input',
                    'inputPlaceholder': 'Enter text...'
                },
                # App management actions
                {
                    'id': 'launch_app',
                    'label': 'Launch App',
                    'command': 'launch_app',
                    'action_type': 'remote',
                    'params': {},
                    'description': 'Launch an application',
                    'requiresInput': True,
                    'inputLabel': 'Package name',
                    'inputPlaceholder': 'com.example.app'
                },
                {
                    'id': 'close_app',
                    'label': 'Close App',
                    'command': 'close_app',
                    'action_type': 'remote',
                    'params': {},
                    'description': 'Close an application',
                    'requiresInput': True,
                    'inputLabel': 'Package name',
                    'inputPlaceholder': 'com.example.app'
                },
                # Power control actions
                {
                    'id': 'press_key_power',
                    'label': 'Power',
                    'command': 'press_key',
                    'action_type': 'remote',
                    'params': {'key': 'POWER'},
                    'description': 'Toggle power on/off',
                    'requiresInput': False
                },
                # Wait/Assert actions (using existing verification controllers)
                {
                    'id': 'wait_for_text_appear',
                    'label': 'Wait for Text to Appear',
                    'command': 'waitForTextToAppear',
                    'action_type': 'verification',
                    'params': {},
                    'description': 'Wait for specific text to appear',
                    'requiresInput': True,
                    'verification_type': 'text'
                },
                {
                    'id': 'wait_for_text_disappear',
                    'label': 'Wait for Text to Disappear',
                    'command': 'waitForTextToDisappear',
                    'action_type': 'verification',
                    'params': {},
                    'description': 'Wait for specific text to disappear',
                    'requiresInput': True,
                    'verification_type': 'text'
                },
                {
                    'id': 'wait_for_image_appear',
                    'label': 'Wait for Image to Appear',
                    'command': 'waitForImageToAppear',
                    'action_type': 'verification',
                    'params': {},
                    'description': 'Wait for specific image to appear',
                    'requiresInput': True,
                    'verification_type': 'image'
                },
                {
                    'id': 'wait_for_image_disappear',
                    'label': 'Wait for Image to Disappear',
                    'command': 'waitForImageToDisappear',
                    'action_type': 'verification',
                    'params': {},
                    'description': 'Wait for specific image to disappear',
                    'requiresInput': True,
                    'verification_type': 'image'
                }
            ]
        }

    def get_device_capture_path(self) -> str:
        """Get device-specific capture path for screenshots."""
        return self.device_config['video_capture_path']

    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute Android TV specific command with proper abstraction and auto-reconnection.
        
        Args:
            command: Command to execute ('press_key', 'input_text', etc.)
            params: Command parameters (including wait_time)
            
        Returns:
            Dict[str, Any]: Dict with 'success' key indicating command execution status, and optional 'error' key
        """
        if params is None:
            params = {}
        
        # Extract wait_time from params
        wait_time = int(params.get('wait_time', 0))
        
        print(f"Remote[{self.device_type.upper()}]: Executing command '{command}' with params: {params}")
        
        def _execute_specific_command():
            """Execute the specific command - centralized logic"""
            if command == 'press_key':
                key = params.get('key')
                success = self.press_key(key) if key else False
                return {'success': success}
            
            elif command == 'input_text':
                text = params.get('text')
                success = self.input_text(text) if text else False
                return {'success': success}
            
            elif command == 'launch_app':
                package = params.get('package')
                success = self.launch_app(package) if package else False
                return {'success': success}
            
            elif command == 'close_app':
                package = params.get('package')
                success = self.close_app(package) if package else False
                return {'success': success}
            
            elif command == 'tap_coordinates':
                x, y = params.get('x'), params.get('y')
                success = self.tap_coordinates(int(x), int(y)) if x is not None and y is not None else False
                return {'success': success}
            
            elif command == 'click_element':
                # Support both 'element_id' (frontend) and 'text' (MCP/docs) for backward compatibility
                element_id = params.get('element_id') or params.get('text')
                if not element_id:
                    error_msg = "click_element requires 'element_id' or 'text' parameter"
                    print(f"Remote[{self.device_type.upper()}]: ERROR - {error_msg}")
                    return {'success': False, 'error': error_msg}
                success = self.click_element(element_id)
                if success:
                    return {'success': True}
                return {
                    'success': False,
                    'error': getattr(self, 'last_error', None) or f"click_element '{element_id}' failed"
                }
            
            elif command == 'get_installed_apps':
                # Android TV specific
                apps = self.get_installed_apps()
                return {'success': len(apps) > 0, 'apps': apps}
            
            else:
                # ❌ VALIDATION: Raise clear error for unknown commands
                valid_commands = [
                    'press_key', 'input_text', 'launch_app', 'close_app',
                    'click_element', 'tap_coordinates', 'get_installed_apps'
                ]
                error_msg = (
                    f"❌ Invalid command '{command}' for android_tv device. "
                    f"Valid commands: {', '.join(valid_commands)}. "
                    f"Did you mean 'click_element' (text-based) instead of 'click_element_by_index'? "
                    f"Use list_actions() to see all available commands."
                )
                print(f"Remote[{self.device_type.upper()}]: {error_msg}")
                # Return dict with error instead of False for better error propagation
                return {'success': False, 'error': error_msg}
        
        # First attempt
        try:
            result = _execute_specific_command()

            # Handle dict returns (for error messages and structured responses)
            if isinstance(result, dict):
                if not result.get('success', False):
                    print(f"Remote[{self.device_type.upper()}]: Command '{command}' returned error: {result.get('error', 'no error details')}")
                # Return the full dict so error details propagate to action_executor
                return result
            
            # If command failed, try reconnecting and retry once
            if not result:
                print(f"Remote[{self.device_type.upper()}]: Command '{command}' failed - attempting reconnection...")
                if self.connect():
                    print(f"Remote[{self.device_type.upper()}]: Reconnected - retrying command '{command}'")
                    result = _execute_specific_command()
                    if result:
                        print(f"Remote[{self.device_type.upper()}]: Command '{command}' succeeded after reconnection")
                    else:
                        print(f"Remote[{self.device_type.upper()}]: Command '{command}' failed even after reconnection")
                else:
                    error_msg = f"Failed to reconnect for command '{command}' retry"
                    print(f"Remote[{self.device_type.upper()}]: {error_msg}")
                    return {'success': False, 'error': error_msg}
                    
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Command '{command}' exception: {e}")
            # Try to reconnect on exception and retry once
            print(f"Remote[{self.device_type.upper()}]: Exception in '{command}' - attempting reconnection...")
            if self.connect():
                try:
                    print(f"Remote[{self.device_type.upper()}]: Reconnected - retrying command '{command}' after exception")
                    result = _execute_specific_command()
                    if result:
                        print(f"Remote[{self.device_type.upper()}]: Command '{command}' succeeded after exception recovery")
                    else:
                        print(f"Remote[{self.device_type.upper()}]: Command '{command}' failed even after exception recovery")
                except Exception as retry_e:
                    print(f"Remote[{self.device_type.upper()}]: Command '{command}' retry after exception also failed: {retry_e}")
                    return {'success': False, 'error': str(retry_e)}
            else:
                error_msg = f"Failed to reconnect after command '{command}' exception"
                print(f"Remote[{self.device_type.upper()}]: {error_msg}")
                return {'success': False, 'error': error_msg}
        
        # Apply wait_time after successful command execution
        if result and wait_time > 0:
            wait_seconds = wait_time / 1000.0
            print(f"Remote[{self.device_type.upper()}]: Waiting {wait_seconds}s after {command}")
            time.sleep(wait_seconds)
        
        return result