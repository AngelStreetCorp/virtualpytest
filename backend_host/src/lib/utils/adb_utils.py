"""
ADB Utilities for Android Device Control

This module provides utilities for controlling Android devices via ADB commands.
Uses direct ADB commands without SSH dependencies.
"""

import os
import subprocess
import time
import re
import base64
import xml.etree.ElementTree as ET
try:
    # Hardened parser for device-supplied XML (entity expansion / XXE safe). ParseError is shared.
    from defusedxml.ElementTree import fromstring as _xml_fromstring
except ImportError:  # pragma: no cover - defusedxml is in backend_host/requirements.txt
    _xml_fromstring = ET.fromstring
from typing import Dict, Any, List, Optional, Tuple

# Import centralized HTTP config for timeouts
from shared.src.lib.config.constants import HTTP_CONFIG


class AndroidElement:
    """Represents an Android UI element from UI dump."""
    
    def __init__(self, element_id: int, tag: str, text: str, resource_id: str,
                 content_desc: str, class_name: str, bounds: str, clickable: bool = False,
                 enabled: bool = True, xpath: str = None, focusable: bool = False):
        self.id = element_id
        self.tag = tag
        self.text = text
        self.resource_id = resource_id
        self.content_desc = content_desc
        self.class_name = class_name
        self.bounds = bounds
        self.clickable = clickable
        self.enabled = enabled
        self.xpath = xpath
        self.focusable = focusable

    def to_dict(self) -> Dict[str, Any]:
        """Convert element to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'tag': self.tag,
            'text': self.text,
            'resource_id': self.resource_id,
            'content_desc': self.content_desc,
            'class_name': self.class_name,
            'bounds': self.bounds,
            'clickable': self.clickable,
            'focusable': self.focusable,
            'enabled': self.enabled,
            'xpath': self.xpath
        }


class AndroidApp:
    """Represents an Android application."""
    
    def __init__(self, package_name: str, label: str):
        self.package_name = package_name
        self.label = label
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert app to dictionary for JSON serialization."""
        return {
            'package_name': self.package_name,
            'label': self.label
        }


def _record_ui_trace(device_id: str, reason: str, elements) -> None:
    """Put one dumped tree into this execution's UI trace.

    Imported lazily and wrapped: a trace is diagnostics, and adb_utils is used by paths that
    must not take a hard dependency on the reporting layer, nor fail because of it.
    """
    try:
        from shared.src.lib.utils import ui_dump_capture

        rows = [
            {'text': e.text, 'content_desc': e.content_desc,
             'class_name': e.class_name, 'clickable': e.clickable}
            for e in elements
            if (e.text or '').strip() or (e.content_desc or '').strip()
        ]
        ui_dump_capture.record(device_id, reason, rows, len(elements))
    except Exception as e:
        print(f"[@lib:adbUtils:_record_ui_trace] skipped: {e}")


class ADBUtils:
    """ADB utilities for Android device control using direct ADB commands."""
    
    # ADB key mappings (supporting both simple and DPAD formats)
    ADB_KEYS = {
        # Simple directional keys
        'UP': 'KEYCODE_DPAD_UP',
        'DOWN': 'KEYCODE_DPAD_DOWN',
        'LEFT': 'KEYCODE_DPAD_LEFT',
        'RIGHT': 'KEYCODE_DPAD_RIGHT',
        'SELECT': 'KEYCODE_DPAD_CENTER',
        'OK': 'KEYCODE_DPAD_CENTER',
        'ENTER': 'KEYCODE_ENTER',

        # DPAD format (for Android TV remote compatibility)
        'DPAD_UP': 'KEYCODE_DPAD_UP',
        'DPAD_DOWN': 'KEYCODE_DPAD_DOWN',
        'DPAD_LEFT': 'KEYCODE_DPAD_LEFT',
        'DPAD_RIGHT': 'KEYCODE_DPAD_RIGHT',
        'DPAD_CENTER': 'KEYCODE_DPAD_CENTER',
        
        # System keys
        'BACK': 'KEYCODE_BACK',
        'HOME': 'KEYCODE_HOME',
        'MENU': 'KEYCODE_MENU',
        'POWER': 'KEYCODE_POWER',
        'ENTER': 'KEYCODE_ENTER',
        'TAB': 'KEYCODE_TAB',
        'ESCAPE': 'KEYCODE_ESCAPE',
        'DELETE': 'KEYCODE_DEL',
        'SEARCH': 'KEYCODE_SEARCH',
        
        # Volume keys
        'VOLUME_UP': 'KEYCODE_VOLUME_UP',
        'VOLUME_DOWN': 'KEYCODE_VOLUME_DOWN',
        'VOLUME_MUTE': 'KEYCODE_VOLUME_MUTE',
        
        # Phone specific keys
        'CAMERA': 'KEYCODE_CAMERA',
        'CALL': 'KEYCODE_CALL',
        'ENDCALL': 'KEYCODE_ENDCALL',
        
        # TV/Media specific keys
        'MEDIA_PLAY_PAUSE': 'KEYCODE_MEDIA_PLAY_PAUSE',
        'MEDIA_PLAY': 'KEYCODE_MEDIA_PLAY',
        'MEDIA_PAUSE': 'KEYCODE_MEDIA_PAUSE',
        'MEDIA_STOP': 'KEYCODE_MEDIA_STOP',
        'MEDIA_REWIND': 'KEYCODE_MEDIA_REWIND',
        'MEDIA_FAST_FORWARD': 'KEYCODE_MEDIA_FAST_FORWARD',
        'MEDIA_NEXT': 'KEYCODE_MEDIA_NEXT',
        'MEDIA_PREVIOUS': 'KEYCODE_MEDIA_PREVIOUS',
        
        # Channel control keys
        'CHANNEL_UP': 'KEYCODE_CHANNEL_UP',
        'CHANNEL_DOWN': 'KEYCODE_CHANNEL_DOWN',

        # Numeric keypad (KEY_0..KEY_9 — same names IR/BLE configs use, so a
        # digit-zap script can send one key name across every remote type).
        'KEY_0': 'KEYCODE_0',
        'KEY_1': 'KEYCODE_1',
        'KEY_2': 'KEYCODE_2',
        'KEY_3': 'KEYCODE_3',
        'KEY_4': 'KEYCODE_4',
        'KEY_5': 'KEYCODE_5',
        'KEY_6': 'KEYCODE_6',
        'KEY_7': 'KEYCODE_7',
        'KEY_8': 'KEYCODE_8',
        'KEY_9': 'KEYCODE_9',
    }
    
    def __init__(self):
        """
        Initialize ADB utilities.
        """
        
    def execute_command(self, command: str, timeout: int = None) -> Tuple[bool, str, str, int]:
        """
        Execute a command using subprocess.
        
        Args:
            command: Command to execute
            timeout: Command timeout in seconds (default: ULTRA_SHORT_TIMEOUT from HTTP_CONFIG)
            
        Returns:
            Tuple of (success, stdout, stderr, exit_code)
        """
        # Use centralized ultra-short timeout if not specified (3s for quick ADB operations)
        if timeout is None:
            timeout = HTTP_CONFIG['ULTRA_SHORT_TIMEOUT']
        try:
            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            success = result.returncode == 0
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            exit_code = result.returncode
            
            # Only log failures, not every successful command
            if not success:
                print(f"[@lib:adbUtils:execute_command] FAILED: {command} (exit code {exit_code}): {stderr}")
            
            return success, stdout, stderr, exit_code
            
        except subprocess.TimeoutExpired:
            print(f"[@lib:adbUtils:execute_command] Command timed out: {command}")
            return False, "", "Command timed out", -1
        except Exception as e:
            print(f"[@lib:adbUtils:execute_command] Command error: {str(e)}")
            return False, "", str(e), -1
    
    def download_file(self, remote_path: str, local_path: str) -> Tuple[bool, str]:
        """
        Download a file from remote path to local path.
        Since we're using direct ADB, this is just a file copy.
        
        Args:
            remote_path: Source file path
            local_path: Destination file path
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            import shutil
            shutil.copy2(remote_path, local_path)
            return True, ""
        except Exception as e:
            return False, str(e)
        
    def connect_device(self, device_id: str) -> bool:
        """
        Connect to ADB device.
        
        Args:
            device_id: Android device ID (IP:port)
            
        Returns:
            bool: True if connection successful
        """
        try:
            # Connect to ADB device
            success, stdout, stderr, exit_code = self.execute_command(f"adb connect {device_id}")
            
            if not success or exit_code != 0:
                print(f"[@lib:adbUtils:connect_device] ADB connect failed: {stderr}")
                return False
            
            # Verify device is connected
            success, stdout, stderr, exit_code = self.execute_command("adb devices")
            
            if not success or exit_code != 0:
                print(f"[@lib:adbUtils:connect_device] Failed to verify device connection")
                return False
                
            # Check if device appears in devices list
            device_lines = [line.strip() for line in stdout.split('\n') 
                          if line.strip() and not line.startswith('List of devices')]
            
            device_found = None
            for line in device_lines:
                if device_id in line:
                    device_found = line
                    break
                    
            if not device_found:
                print(f"[@lib:adbUtils:connect_device] Device {device_id} not found in adb devices list")
                return False
                
            if 'offline' in device_found:
                print(f"[@lib:adbUtils:connect_device] Device {device_id} is offline")
                return False
                
            if 'device' not in device_found:
                status = device_found.split('\t')[1] if '\t' in device_found else 'unknown'
                print(f"[@lib:adbUtils:connect_device] Device {device_id} status: {status}")
                return False
                
            return True
            
        except Exception as e:
            print(f"[@lib:adbUtils:connect_device] Error: {e}")
            return False
            
    def execute_key_command(self, device_id: str, key: str) -> bool:
        """
        Execute ADB key command.
        
        Args:
            device_id: Android device ID
            key: Key name (e.g., 'UP', 'DOWN', 'HOME', 'DPAD_RIGHT', 'KEYCODE_BACK')
            
        Returns:
            bool: True if command successful
        """
        try:
            # Normalize the key - remove 'KEYCODE_' prefix if present
            normalized_key = key.upper()
            if normalized_key.startswith('KEYCODE_'):
                normalized_key = normalized_key.replace('KEYCODE_', '')
            
            print(f"[@lib:adbUtils:execute_key_command] Attempting to execute key: '{key}' (normalized: '{normalized_key}')")
            
            keycode = self.ADB_KEYS.get(normalized_key)
            if not keycode:
                available_keys = list(self.ADB_KEYS.keys())
                print(f"[@lib:adbUtils:execute_key_command] Invalid key: '{key}' (normalized: '{normalized_key}')")
                print(f"[@lib:adbUtils:execute_key_command] Available keys: {', '.join(available_keys[:10])}...")
                print(f"[@lib:adbUtils:execute_key_command] Total available keys: {len(available_keys)}")
                return False
                
            command = f"adb -s {device_id} shell input keyevent {keycode}"
            print(f"[@lib:adbUtils:execute_key_command] Executing: {command}")
            
            success, stdout, stderr, exit_code = self.execute_command(command)
            
            if success and exit_code == 0:
                print(f"[@lib:adbUtils:execute_key_command] Successfully sent keyevent {keycode} for key '{key}'")
                return True
            else:
                print(f"[@lib:adbUtils:execute_key_command] Key command failed: {stderr}")
                return False
                
        except Exception as e:
            print(f"[@lib:adbUtils:execute_key_command] Error: {e}")
            return False
            
    def get_installed_apps(self, device_id: str, device_type: str = "android_mobile") -> List[AndroidApp]:
        """
        Get list of launcher-visible apps on Android device.

        Uses the MAIN/LAUNCHER intent query to return only apps that appear
        in the device launcher, filtering out system overlays and services.
        For TV devices, also queries LEANBACK_LAUNCHER category.

        Args:
            device_id: Android device ID
            device_type: Device type (android_mobile, android_tv, android_tablet)

        Returns:
            List of AndroidApp objects
        """
        try:
            print(f"[@lib:adbUtils:get_installed_apps] Getting launcher apps for device {device_id} (type={device_type})")

            seen_packages = set()
            apps = []

            # Query launcher-visible apps using intent resolution
            categories = ["android.intent.category.LAUNCHER"]
            if device_type == "android_tv":
                categories.append("android.intent.category.LEANBACK_LAUNCHER")

            for category in categories:
                command = f"adb -s {device_id} shell cmd package query-activities --brief -a android.intent.action.MAIN -c {category}"
                success, stdout, stderr, exit_code = self.execute_command(command)

                if not success or exit_code != 0:
                    print(f"[@lib:adbUtils:get_installed_apps] Failed to query {category}: {stderr}")
                    continue

                for line in stdout.split('\n'):
                    line = line.strip()
                    # Lines with activity info contain package/activity format
                    if '/' in line and not line.startswith('Activity') and not line.endswith('found:'):
                        package_name = line.split('/')[0].strip()
                        if package_name and package_name not in seen_packages:
                            seen_packages.add(package_name)
                            apps.append(AndroidApp(package_name, package_name))

            # Fallback: if intent query returned nothing, use pm list packages -3
            if not apps:
                print(f"[@lib:adbUtils:get_installed_apps] Intent query returned no apps, falling back to pm list packages -3")
                command = f"adb -s {device_id} shell pm list packages -3 --user 0"
                success, stdout, stderr, exit_code = self.execute_command(command)

                if success and exit_code == 0:
                    for line in stdout.split('\n'):
                        if line.startswith('package:'):
                            package_name = line.replace('package:', '').strip()
                            apps.append(AndroidApp(package_name, package_name))

            print(f"[@lib:adbUtils:get_installed_apps] Found {len(apps)} launcher apps")
            return apps
            
        except Exception as e:
            print(f"[@lib:adbUtils:get_installed_apps] Error: {e}")
            return []
            
    def launch_app(self, device_id: str, package_name: str) -> bool:
        """
        Launch an app by package name using am start with auto-detected main activity.
        
        Args:
            device_id: Android device ID
            package_name: App package name
            
        Returns:
            bool: True if launch successful
        """
        try:
            print(f"[@lib:adbUtils:launch_app] Launching app {package_name} on device {device_id}")

            # Force-stop first to clear any stale activity state (e.g. Settings page)
            self.execute_command(f"adb -s {device_id} shell am force-stop {package_name}")

            # Get the LAUNCHER activity (not just any MAIN — that can match Settings)
            dump_cmd = f"adb -s {device_id} shell cmd package resolve-activity --brief {package_name}"
            success, stdout, stderr, exit_code = self.execute_command(dump_cmd)

            component = None
            if success and stdout:
                # resolve-activity returns: priority=0 preferredOrder=0 match=0x108000 ...\n package/activity
                for line in stdout.strip().split('\n'):
                    line = line.strip()
                    if '/' in line and package_name in line:
                        component = line
                        break

            # Fallback: use monkey to launch (most reliable)
            if not component:
                print(f"[@lib:adbUtils:launch_app] resolve-activity failed, using monkey fallback")
                command = f"adb -s {device_id} shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1"
                success, stdout, stderr, exit_code = self.execute_command(command)
                if success and exit_code == 0:
                    print(f"[@lib:adbUtils:launch_app] Successfully launched {package_name} via monkey")
                    return True
                return False

            print(f"[@lib:adbUtils:launch_app] Resolved launcher activity: {component}")

            # Escape $ for adb shell (Android shell interprets $Foo as variable)
            escaped_component = component.replace('$', '\\$')

            # Launch with am start
            command = f"adb -s {device_id} shell am start -n {escaped_component}"
            success, stdout, stderr, exit_code = self.execute_command(command)
            
            if success and exit_code == 0:
                print(f"[@lib:adbUtils:launch_app] Successfully launched {package_name}")
                return True
            else:
                print(f"[@lib:adbUtils:launch_app] App launch failed: {stderr}")
                return False
                
        except Exception as e:
            print(f"[@lib:adbUtils:launch_app] Error: {e}")
            return False
            
    def close_app(self, device_id: str, package_name: str) -> bool:
        """
        Close/stop an app by package name using pkill.
        
        Args:
            device_id: Android device ID
            package_name: App package name to close
            
        Returns:
            bool: True if close successful
        """
        try:
            print(f"[@lib:adbUtils:close_app] Closing app {package_name} on device {device_id}")
            
            command = f"adb -s {device_id} shell am force-stop {package_name}"
            success, stdout, stderr, exit_code = self.execute_command(command)
            
            if success and exit_code == 0:
                print(f"[@lib:adbUtils:close_app] Successfully closed {package_name}")
                return True
            else:
                print(f"[@lib:adbUtils:close_app] App close failed: {stderr}")
                return False
                
        except Exception as e:
            print(f"[@lib:adbUtils:close_app] Error: {e}")
            return False
            
    def kill_app(self, device_id: str, package_name: str) -> bool:
        """
        Kill an app by package name (alias for close_app).
        
        Args:
            device_id: Android device ID
            package_name: App package name to kill
            
        Returns:
            bool: True if kill successful
        """
        return self.close_app(device_id, package_name)
            
    def dump_elements(self, device_id: str, reason: str = 'dump') -> Tuple[bool, List[AndroidElement], str]:
        """
        Every dump is recorded into this execution's UI trace (ui_dump_capture), which the
        report uploads and links. `reason` is whatever the caller was doing — a selector, a
        verification, a bare 'dump' — so the trace says why each tree was read without
        anything here needing to know what the caller considers significant.

        Dump UI elements from Android device (similar to TypeScript version).
        
        Args:
            device_id: Android device ID
            
        Returns:
            Tuple of (success, elements_list, error_message)
        """
        try:
            # Dump UI to file then read it (more compatible)
            # Use SHORT_TIMEOUT (30s) instead of ULTRA_SHORT (3s) for uiautomator dump which can be slow
            dump_command = f"adb -s {device_id} shell uiautomator dump --compressed --windows /sdcard/ui_dump.xml"
            success, stdout, stderr, exit_code = self.execute_command(dump_command, timeout=HTTP_CONFIG['SHORT_TIMEOUT'])
            
            if not success or exit_code != 0:
                error_msg = f"Failed to dump UI: {stderr}"
                print(f"[@lib:adbUtils:dump_elements] {error_msg}")
                return False, [], error_msg
                
            # Read the dumped file (use SHORT_TIMEOUT as well)
            read_command = f"adb -s {device_id} shell cat /sdcard/ui_dump.xml"
            success, stdout, stderr, exit_code = self.execute_command(read_command, timeout=HTTP_CONFIG['SHORT_TIMEOUT'])
            
            if not success or exit_code != 0:
                error_msg = f"Failed to read UI dump: {stderr}"
                print(f"[@lib:adbUtils:dump_elements] {error_msg}")
                return False, [], error_msg
                
            if not stdout or stdout.strip() == "":
                error_msg = "No UI data received from device"
                print(f"[@lib:adbUtils:dump_elements] {error_msg}")
                return False, [], error_msg
                
            print(f"[@lib:adbUtils:dump_elements] Received XML data, length: {len(stdout)}")

            # Parse XML to extract elements
            elements = self._parse_ui_elements(stdout)

            print(f"[@lib:adbUtils:dump_elements] Processing complete: {len(elements)} useful elements")
            _record_ui_trace(device_id, reason, elements)
            return True, elements, ""
            
        except Exception as e:
            error_msg = f"Error dumping UI elements: {e}"
            print(f"[@lib:adbUtils:dump_elements] {error_msg}")
            return False, [], error_msg
            
    def _parse_ui_elements(self, xml_data: str) -> List[AndroidElement]:
        """
        Parse XML data to extract UI elements with XPath information.
        
        Args:
            xml_data: XML content from uiautomator dump
            
        Returns:
            List of AndroidElement objects with XPath
        """
        elements = []
        
        # Check if we have valid XML
        if '<node' not in xml_data or '</hierarchy>' not in xml_data:
            print(f"[@lib:adbUtils:_parse_ui_elements] Invalid XML format received")
            return elements
        
        try:
            # Parse XML using ElementTree
            root = _xml_fromstring(xml_data)
            
            element_counter = 0
            filtered_out_count = 0
            
            def get_xpath(node, parent_path="", parent_node=None):
                """Generate XPath for a node considering sibling positions."""
                class_name = node.get('class', '')
                
                if not parent_node:
                    # Root node
                    return f"/{class_name}" if class_name else "/node"
                
                # Count preceding siblings with same class name
                sibling_index = 0
                for sibling in parent_node:
                    if sibling == node:
                        break
                    if sibling.get('class', '') == class_name:
                        sibling_index += 1
                
                # Build XPath with index
                current_path = f"{parent_path}/{class_name}[{sibling_index}]" if class_name else f"{parent_path}/node[{sibling_index}]"
                return current_path
            
            def traverse_and_extract(node, parent_path="", parent_node=None):
                """Recursively traverse XML tree and extract elements with XPath."""
                nonlocal element_counter, filtered_out_count
                
                # Get node attributes
                class_name = node.get('class', '').strip()
                text = node.get('text', '').strip()
                resource_id = node.get('resource-id', '').strip()
                content_desc = node.get('content-desc', '').strip()
                bounds = node.get('bounds', '').strip()
                clickable = node.get('clickable', 'false') == 'true'
                focusable = node.get('focusable', 'false') == 'true'
                enabled = node.get('enabled', 'false') == 'true'

                # Generate XPath for this element
                xpath = get_xpath(node, parent_path, parent_node)
                
                # Early filtering - skip obviously useless elements (same logic as original regex version)
                skip_element = False
                filter_reason = None
                
                # Filter 0: Skip container/layout elements
                # Two categories:
                # 1. ALWAYS filter: Pure scrolling/list containers (never interactive)
                # 2. Conditionally filter: Layout containers (can be clickable buttons)
                
                # Pure scrolling/list containers - filter UNLESS they have content_desc (used as section headers on TV)
                scrolling_container_classes = [
                    'androidx.viewpager.widget.ViewPager',
                    'android.support.v7.widget.RecyclerView',
                    'androidx.recyclerview.widget.RecyclerView',
                    'android.widget.AbsListView',
                    'AbsListView',  # Sometimes shortened
                    'android.widget.ListView',
                    'android.widget.GridView',
                    'android.widget.ScrollView',
                    'android.widget.HorizontalScrollView',
                    'androidx.compose.ui.platform.ComposeView',
                ]
                if class_name in scrolling_container_classes:
                    has_desc = content_desc and content_desc.strip()
                    if not has_desc:
                        skip_element = True
                        filter_reason = f"Scrolling container (no desc): {class_name}"

                # Layout containers - filter ONLY if not clickable/focusable AND no useful content
                layout_container_classes = [
                    'android.widget.FrameLayout',
                    'android.widget.LinearLayout',
                    'android.widget.RelativeLayout',
                    'android.widget.ConstraintLayout',
                    'android.view.ViewGroup',
                ]
                if not skip_element and class_name in layout_container_classes:
                    has_useful_content = (text and text.strip()) or (content_desc and content_desc.strip())
                    is_interactive = clickable or focusable

                    # Keep clickable/focusable containers (e.g., video cards on TV)
                    if not has_useful_content and not is_interactive:
                        skip_element = True
                        filter_reason = f"Layout container with no content: {class_name}"
                
                
                # Filter 1: Skip completely empty/useless elements
                if not skip_element and (not text or text == '' or text == ' ' or text == '\n') and \
                   (not content_desc or content_desc == '' or content_desc == ' ') and \
                   (not resource_id or resource_id == 'null' or resource_id == '') and \
                   (not class_name or class_name == '' or class_name == 'android.view.View'):
                    skip_element = True
                    filter_reason = "Empty element (no text, desc, id)"
                
                # Filter 2: Skip elements with no useful identifiers at all
                if not skip_element and (not class_name or class_name == '') and \
                   (not text or text == '') and \
                   (not resource_id or resource_id == 'null' or resource_id == '') and \
                   (not content_desc or content_desc == ''):
                    skip_element = True
                    filter_reason = "No identifiers"
                
                # Filter 3: Skip elements with literal "null" resource-id AND no other identifiers
                if not skip_element and resource_id == 'null' and not text and not content_desc:
                    skip_element = True
                    filter_reason = "Null resource-id with no text or desc"

                # Filter 4: Skip non-interactive elements with no meaningful text
                if not skip_element and not clickable and not focusable and not enabled and (not text or text == ''):
                    skip_element = True
                    filter_reason = "Non-interactive with no text"
                
                # Add element if not filtered
                if not skip_element:
                    element_counter += 1
                    element = AndroidElement(
                        element_id=element_counter,
                        tag=class_name or 'unknown',
                        text=text or '<no text>',
                        resource_id=resource_id or '<no resource-id>',
                        content_desc=content_desc or '<no content-desc>',
                        class_name=class_name or '',
                        bounds=bounds or '',
                        clickable=clickable,
                        focusable=focusable,
                        enabled=enabled,
                        xpath=xpath
                    )
                    elements.append(element)
                else:
                    filtered_out_count += 1
                    # Log filtered element with reason
                    print(f"[@lib:adbUtils:_parse_ui_elements] 🚫 FILTERED: {filter_reason} | text='{text}' | desc='{content_desc}' | class={class_name} | clickable={clickable} | enabled={enabled}")
                
                # Recursively process children
                for child in node:
                    traverse_and_extract(child, xpath, node)
            
            # Start traversal from root
            traverse_and_extract(root, "", None)
            
            print(f"[@lib:adbUtils:_parse_ui_elements] Extracted {len(elements)} elements, filtered {filtered_out_count}")
            
        except ET.ParseError as e:
            print(f"[@lib:adbUtils:_parse_ui_elements] XML Parse Error: {e}")
            print(f"[@lib:adbUtils:_parse_ui_elements] Falling back to regex parsing...")
            # Fall back to original regex-based parsing (without XPath)
            return self._parse_ui_elements_regex(xml_data)
        except Exception as e:
            print(f"[@lib:adbUtils:_parse_ui_elements] Error: {e}")
            import traceback
            traceback.print_exc()
            # Fall back to regex parsing
            return self._parse_ui_elements_regex(xml_data)
        
        return elements
    
    def _parse_ui_elements_regex(self, xml_data: str) -> List[AndroidElement]:
        """
        Fallback regex-based parsing when XML parsing fails (without XPath).
        
        Args:
            xml_data: XML content from uiautomator dump
            
        Returns:
            List of AndroidElement objects (without XPath)
        """
        elements = []
        
        # Pattern 1: Self-closing nodes
        self_closing_pattern = r'<node[^>]*\/>'
        self_closing_matches = re.findall(self_closing_pattern, xml_data, re.DOTALL)
        
        # Pattern 2: Open/close nodes
        open_close_pattern = r'<node[^>]*>.*?<\/node>'
        open_close_matches = re.findall(open_close_pattern, xml_data, re.DOTALL)
        
        # Pattern 3: All nodes (both patterns combined)
        all_nodes_pattern = r'<node[^>]*(?:\/>|>.*?<\/node>)'
        all_matches = re.findall(all_nodes_pattern, xml_data, re.DOTALL)
        
        # Use the pattern that finds the most nodes
        matches = all_matches
        if len(self_closing_matches) > len(all_matches):
            matches = self_closing_matches
           
        element_counter = 0
        filtered_out_count = 0
        
        for i, match in enumerate(matches):
            try:
                # Early filtering - skip obviously useless elements before parsing
                if ('text=""' in match or 'text=" "' in match or 'text="\n"' in match) and \
                   ('content-desc=""' in match or 'content-desc=" "' in match) and \
                   ('resource-id="null"' in match or 'resource-id=""' in match) and \
                   ('class=""' in match or 'class="android.view.View"' in match):
                    filtered_out_count += 1
                    continue
                
                # Extract attributes using regex
                def get_attr(attr_name: str) -> str:
                    pattern = f'{attr_name}="([^"]*)"'
                    attr_match = re.search(pattern, match)
                    return attr_match.group(1) if attr_match else ''
                
                text = get_attr('text').strip()
                resource_id = get_attr('resource-id').strip()
                content_desc = get_attr('content-desc').strip()
                class_name = get_attr('class').strip()
                bounds = get_attr('bounds').strip()
                clickable = get_attr('clickable') == 'true'
                focusable = get_attr('focusable') == 'true'
                enabled = get_attr('enabled') == 'true'

                # Skip elements with no useful identifiers
                if (not class_name or class_name == '') and \
                   (not text or text == '') and \
                   (not resource_id or resource_id == 'null' or resource_id == '') and \
                   (not content_desc or content_desc == ''):
                    filtered_out_count += 1
                    continue
                
                # Skip elements with null resource-id
                if resource_id == 'null':
                    filtered_out_count += 1
                    continue
                
                # Skip elements that are not interactive and have no text
                if not clickable and not enabled and (not text or text == ''):
                    filtered_out_count += 1
                    continue
                
                element_counter += 1
                element = AndroidElement(
                    element_id=element_counter,
                    tag=class_name or 'unknown',
                    text=text or '<no text>',
                    resource_id=resource_id or '<no resource-id>',
                    content_desc=content_desc or '<no content-desc>',
                    class_name=class_name or '',
                    bounds=bounds or '',
                    clickable=clickable,
                    focusable=focusable,
                    enabled=enabled,
                    xpath=None  # No XPath in regex fallback
                )
                
                elements.append(element)
                
            except Exception as e:
                print(f"[@lib:adbUtils:_parse_ui_elements_regex] Error parsing element {i+1}: {e}")
                filtered_out_count += 1
        
        print(f"[@lib:adbUtils:_parse_ui_elements_regex] Regex fallback: {len(elements)} elements, filtered {filtered_out_count}")
        return elements
        
    def click_element(self, device_id: str, element: AndroidElement) -> bool:
        """
        Click on a UI element.
        
        Args:
            device_id: Android device ID
            element: AndroidElement to click
            
        Returns:
            bool: True if click successful
        """
        try:
            print(f"[@lib:adbUtils:click_element] Attempting to click element ID={element.id}")
            
            # Parse bounds to get coordinates if available
            coordinates = None
            if element.bounds and element.bounds != '':
                # Bounds format: [x1,y1][x2,y2]
                bounds_match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', element.bounds)
                if bounds_match:
                    x1, y1, x2, y2 = map(int, bounds_match.groups())
                    coordinates = {
                        'x': (x1 + x2) // 2,
                        'y': (y1 + y2) // 2
                    }
                    print(f"[@lib:adbUtils:click_element] Calculated tap coordinates: {coordinates['x']}, {coordinates['y']}")
            
            # If we have coordinates from bounds, use direct tap
            if coordinates:
                command = f"adb -s {device_id} shell input tap {coordinates['x']} {coordinates['y']}"
                success, stdout, stderr, exit_code = self.execute_command(command)
                
                if success and exit_code == 0:
                    print(f"[@lib:adbUtils:click_element] Successfully clicked element using coordinates")
                    return True
                else:
                    print(f"[@lib:adbUtils:click_element] Direct tap failed: {stderr}")
            
            print(f"[@lib:adbUtils:click_element] All click methods failed for element")
            return False
            
        except Exception as e:
            print(f"[@lib:adbUtils:click_element] Error: {e}")
            return False
            
    def get_device_resolution(self, device_id: str) -> Optional[Dict[str, int]]:
        """
        Get current device screen resolution (orientation-aware).
        
        Args:
            device_id: Android device ID
            
        Returns:
            Dictionary with width and height accounting for current rotation, or None if failed
        """
        try:
            command = f"adb -s {device_id} shell dumpsys display"
            success, stdout, stderr, exit_code = self.execute_command(command)
            
            if not success or exit_code != 0:
                print(f"[@lib:adbUtils:get_device_resolution] Command failed: {stderr}")
                return None
            
            # Look for current display dimensions in dumpsys output. Prefer
            # mOverrideDisplayInfo's "real WxH" - this is the live, rotation-aware size
            # DisplayManagerService is actually compositing right now. Verified on a rotated
            # S21 (Android 15-ish) where mDisplayWidth/mDisplayHeight ALSO exist elsewhere in
            # the same dumpsys output but are stale (report the base portrait size even while
            # rotated to landscape) - mBaseDisplayInfo's "real" has the same staleness problem,
            # so neither of those is a safe substitute for mOverrideDisplayInfo.
            override_match = re.search(r'mOverrideDisplayInfo=DisplayInfo\{[^\n]*?real (\d+) x (\d+)', stdout)
            if override_match:
                width = int(override_match.group(1))
                height = int(override_match.group(2))
                return {'width': width, 'height': height}

            # Fall back for older Android versions that predate mOverrideDisplayInfo, where
            # mDisplayWidth/mDisplayHeight are the live rotation-aware fields instead.
            width_match = re.search(r'mDisplayWidth=(\d+)', stdout)
            height_match = re.search(r'mDisplayHeight=(\d+)', stdout)
            if width_match and height_match:
                width = int(width_match.group(1))
                height = int(height_match.group(1))
                return {'width': width, 'height': height}

            print(f"[@lib:adbUtils:get_device_resolution] Could not parse display resolution")
            return None
            
        except Exception as e:
            print(f"[@lib:adbUtils:get_device_resolution] Error: {e}")
            return None
            
    def take_screenshot(self, device_id: str) -> Tuple[bool, str, str]:
        """
        Take a screenshot of the Android device.
        
        Args:
            device_id: Android device ID
            
        Returns:
            Tuple of (success, base64_screenshot_data, error_message)
        """
        try:
            print(f"[@lib:adbUtils:take_screenshot] Taking screenshot for device {device_id}")
            
            # Take screenshot and save to device
            screenshot_path = "/sdcard/screenshot.png"
            screenshot_command = f"adb -s {device_id} shell screencap -p {screenshot_path}"
            
            success, stdout, stderr, exit_code = self.execute_command(screenshot_command, timeout=HTTP_CONFIG['SHORT_TIMEOUT'])
            
            if not success or exit_code != 0:
                error_msg = f"Failed to take screenshot: {stderr}"
                print(f"[@lib:adbUtils:take_screenshot] {error_msg}")
                return False, "", error_msg
                
            print(f"[@lib:adbUtils:take_screenshot] Screenshot saved to device at {screenshot_path}")
            
            # Pull screenshot to SSH host
            remote_temp_path = "/tmp/android_screenshot.png"
            pull_command = f"adb -s {device_id} pull {screenshot_path} {remote_temp_path}"
            success, stdout, stderr, exit_code = self.execute_command(pull_command, timeout=HTTP_CONFIG['SHORT_TIMEOUT'])
            
            if not success or exit_code != 0:
                error_msg = f"Failed to pull screenshot: {stderr}"
                print(f"[@lib:adbUtils:take_screenshot] {error_msg}")
                return False, "", error_msg
                
            print(f"[@lib:adbUtils:take_screenshot] Screenshot pulled to SSH host at {remote_temp_path}")
            
            # Download the file from SSH host to our local server
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                local_temp_path = temp_file.name
                
            try:
                success, error_msg = self.download_file(remote_temp_path, local_temp_path)
                
                if not success:
                    print(f"[@lib:adbUtils:take_screenshot] Failed to download file: {error_msg}")
                    return False, "", error_msg
                    
                print(f"[@lib:adbUtils:take_screenshot] Screenshot downloaded to local server at {local_temp_path}")
                
                # Now do base64 encoding locally on our server (much more reliable)
                with open(local_temp_path, 'rb') as f:
                    screenshot_data = base64.b64encode(f.read()).decode('utf-8')
                    
                print(f"[@lib:adbUtils:take_screenshot] Screenshot encoded locally, data length: {len(screenshot_data)}")
                
            finally:
                # Clean up local temp file
                try:
                    os.unlink(local_temp_path)
                except:
                    pass
            
            # Clean up files on remote hosts
            cleanup_commands = [
                f"adb -s {device_id} shell rm {screenshot_path}",  # Remove from device
                f"rm -f {remote_temp_path}"  # Remove from SSH host
            ]
            
            for cleanup_cmd in cleanup_commands:
                self.execute_command(cleanup_cmd)  # Don't check result, it's cleanup
            
            return True, screenshot_data, ""
            
        except Exception as e:
            error_msg = f"Screenshot error: {e}"
            print(f"[@lib:adbUtils:take_screenshot] {error_msg}")
            return False, "", error_msg

    def take_screenshot_to_file(self, device_id: str, output_path: str = None) -> Tuple[bool, str, str]:
        """
        Take a screenshot and save directly to a local file (no base64).
        Designed for runner hosts where ADB is local.

        Args:
            device_id: Android device ID
            output_path: Local file path to save PNG. Auto-generated if None.

        Returns:
            Tuple of (success, file_path, error_message)
        """
        try:
            if output_path is None:
                screenshot_dir = "/tmp/vpt_screenshots"
                os.makedirs(screenshot_dir, exist_ok=True)
                timestamp = int(time.time() * 1000)
                safe_id = device_id.replace(":", "_").replace("/", "_")
                output_path = f"{screenshot_dir}/screenshot_{safe_id}_{timestamp}.png"

            device_path = "/sdcard/vpt_screenshot.png"

            # Capture on device
            cmd = f"adb -s {device_id} shell screencap -p {device_path}"
            success, _, stderr, exit_code = self.execute_command(cmd, timeout=HTTP_CONFIG['SHORT_TIMEOUT'])
            if not success or exit_code != 0:
                return False, "", f"screencap failed: {stderr}"

            # Pull to local filesystem
            cmd = f"adb -s {device_id} pull {device_path} {output_path}"
            success, _, stderr, exit_code = self.execute_command(cmd, timeout=HTTP_CONFIG['SHORT_TIMEOUT'])
            if not success or exit_code != 0:
                return False, "", f"pull failed: {stderr}"

            # Cleanup device file
            self.execute_command(f"adb -s {device_id} shell rm {device_path}")

            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                return False, "", "Screenshot file is empty or missing"

            print(f"[@lib:adbUtils:take_screenshot_to_file] Saved: {output_path} ({os.path.getsize(output_path)} bytes)")
            return True, output_path, ""

        except Exception as e:
            return False, "", f"Screenshot to file error: {e}"

    def _calculate_match_score(self, search_term: str, matched_value: str, element: Optional[AndroidElement] = None) -> Tuple[int, int, int, int, int]:
        """
        Calculate match quality score for prioritization.
        
        Returns tuple of (exact_match, starts_with, widget_priority, case_match_score, length) where:
        - exact_match: 1 if exact match, 0 otherwise (highest priority)
        - starts_with: 1 if matched value starts with search term (2nd priority)
        - widget_priority: 2 for Button/Tab, 1 for Clickable, 0 otherwise (3rd priority)
        - case_match_score: number of matching case characters (higher is better)
        - length: length of matched value (lower is better, so we negate for sorting)
        
        Args:
            search_term: The search term to compare
            matched_value: The value that was matched
            element: Optional AndroidElement for widget type checking
        
        Returns:
            Tuple[int, int, int, int, int]: (exact_match, starts_with, widget_priority, case_match_score, -length)
        """
        search_stripped = search_term.strip()
        value_stripped = matched_value.strip()
        search_lower = search_stripped.lower()
        value_lower = value_stripped.lower()
        
        # 1. Check for exact match (highest priority)
        exact_match = 1 if search_stripped == value_stripped else 0
        
        # 2. Check if starts with search term (2nd priority)
        starts_with = 1 if value_lower.startswith(search_lower) else 0
        
        # 3. Widget Priority (Tab/Button preference)
        widget_priority = 0
        if element:
            class_name = getattr(element, 'class_name', '').lower()
            # Check class name for button/tab/switch/input identifiers
            if any(x in class_name for x in ['button', 'tab', 'switch', 'edittext']):
                widget_priority = 2
            # Check if clickable (secondary priority if not explicitly a button class)
            elif getattr(element, 'clickable', False):
                widget_priority = 1
        
        # 4. Calculate case match score (character-by-character case matching)
        # For each character position where both have the same case, add 1 point
        case_match_score = 0
        
        # Find where the search term appears in the value (case-insensitive)
        if search_lower in value_lower:
            start_idx = value_lower.index(search_lower)
            # Compare case character by character
            for i in range(len(search_stripped)):
                if i + start_idx < len(value_stripped):
                    search_char = search_stripped[i]
                    value_char = value_stripped[i + start_idx]
                    # Check if both are same case (both upper or both lower)
                    if search_char.isupper() == value_char.isupper():
                        case_match_score += 1
        
        # 5. Get length (we'll negate it for sorting so shorter is better)
        length = len(value_stripped)
        
        return (exact_match, starts_with, widget_priority, case_match_score, -length)

    def smart_element_search(self, device_id: str, search_term: str, **options) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Smart element search that looks for search_term (case-insensitive) in ANY attribute.
        Results are prioritized by: 1) Exact match, 2) Starts with, 3) Widget Type, 4) Case match, 5) Shortest length.
        
        Args:
            device_id: Android device ID
            search_term: The term to search for (case-insensitive)
            **options: Additional options (timeout, check_interval, etc.)
        
        Returns:
            Tuple of (success, list_of_matches, error_message)
            
            Each match contains:
            {
                "element_id": int,
                "matched_attribute": str,
                "matched_value": str, 
                "match_reason": str,
                "search_term": str,
                "case_match": str,
                "all_matches": list,
                "full_element": dict,
                "match_score": tuple
            }
        """
        try:
            print(f"[@lib:adbUtils:smart_element_search] Smart searching for '{search_term}' on device {device_id}")
            
            # Get all UI elements
            dump_success, elements, dump_error = self.dump_elements(
                device_id, f'smart_element_search({search_term!r})')
            
            if not dump_success:
                # Make infrastructure failures more explicit in smart search
                if 'infrastructure failure' in dump_error.lower() or 'timeout' in dump_error.lower() or 'connection' in dump_error.lower():
                    error_msg = f"Infrastructure failure - Cannot search elements: {dump_error}"
                else:
                    error_msg = f"Failed to dump UI elements: {dump_error}"
                print(f"[@lib:adbUtils:smart_element_search] {error_msg}")
                return False, [], error_msg
            
            # Convert search term to lowercase for case-insensitive comparison and strip spaces
            search_lower = search_term.strip().lower()
            matches = []
            
            print(f"[@lib:adbUtils:smart_element_search] Searching {len(elements)} elements for '{search_term}' (case-insensitive)")
            
            for element in elements:
                # Check each attribute for matches
                element_matches = []
                
                # Check text attribute
                if element.text and search_lower in element.text.lower():
                    element_matches.append({
                        "attribute": "text",
                        "value": element.text,
                        "reason": f"Contains '{search_term}' in text"
                    })
                
                # Check content_desc attribute  
                if element.content_desc and search_lower in element.content_desc.lower():
                    element_matches.append({
                        "attribute": "content_desc", 
                        "value": element.content_desc,
                        "reason": f"Contains '{search_term}' in content description"
                    })
                
                # Check resource_id attribute
                if element.resource_id and search_lower in element.resource_id.lower():
                    element_matches.append({
                        "attribute": "resource_id",
                        "value": element.resource_id, 
                        "reason": f"Contains '{search_term}' in resource ID"
                    })
                
                # Check class_name attribute
                if element.class_name and search_lower in element.class_name.lower():
                    element_matches.append({
                        "attribute": "class_name",
                        "value": element.class_name,
                        "reason": f"Contains '{search_term}' in class name"
                    })
                
                # If any matches found for this element, add to results
                if element_matches:
                    # Use the first/best match for primary result
                    primary_match = element_matches[0]
                    
                    # Calculate match score for prioritization
                    match_score = self._calculate_match_score(search_term, primary_match["value"], element)
                    
                    # Determine case match description
                    case_match = "Exact case match" if search_term in primary_match["value"] else f"Different case: searched '{search_term}', found '{primary_match['value']}'"
                    
                    match_info = {
                        "element_id": element.id,
                        "matched_attribute": primary_match["attribute"],
                        "matched_value": primary_match["value"],
                        "match_reason": f"{primary_match['reason']} (case-insensitive)",
                        "search_term": search_term,
                        "case_match": case_match,
                        "all_matches": element_matches,  # Include all matching attributes
                        "full_element": element.to_dict(),
                        "match_score": match_score  # For sorting/debugging
                    }
                    
                    matches.append(match_info)
                    
                    print(f"[@lib:adbUtils:smart_element_search] Match found - Element {element.id}: {primary_match['reason']}")
            
            # Sort matches by priority: 1) Exact match, 2) Starts with, 3) Widget Type, 4) Case match score, 5) Shortest length
            if matches:
                matches.sort(key=lambda m: m["match_score"], reverse=True)
                print(f"[@lib:adbUtils:smart_element_search] Prioritized {len(matches)} matches:")
                for i, match in enumerate(matches[:5]):  # Show top 5
                    score = match["match_score"]
                    # Score tuple: (exact_match, starts_with, widget_priority, case_match_score, -length)
                    print(f"[@lib:adbUtils:smart_element_search]   {i+1}. '{match['matched_value']}' (exact={score[0]}, start={score[1]}, widget={score[2]}, case={score[3]}, len={-score[4]})")
            
            success = len(matches) > 0
            if success:
                print(f"[@lib:adbUtils:smart_element_search] SUCCESS: Found {len(matches)} matching elements")
            else:
                print(f"[@lib:adbUtils:smart_element_search] No elements found matching '{search_term}'")
                print(f"[@lib:adbUtils:smart_element_search] UI DUMP - Available elements ({len(elements)}):")
                for i, el in enumerate(elements):
                    print(f"[@lib:adbUtils:smart_element_search]   {i+1}. text='{el.text}' desc='{el.content_desc}' id='{el.resource_id}' class='{el.class_name}'")
            
            return success, matches, ""
            
        except Exception as e:
            error_msg = f"Smart element search failed: {e}"
            print(f"[@lib:adbUtils:smart_element_search] ERROR: {error_msg}")
            return False, [], error_msg
    
    def search_element_by_xpath(self, device_id: str, xpath: str) -> Tuple[bool, List[AndroidElement], str]:
        """
        Search for elements by XPath expression.
        
        Args:
            device_id: Android device ID
            xpath: XPath expression to match elements
        
        Returns:
            Tuple of (success, matching_elements, error_message)
        """
        try:
            print(f"[@lib:adbUtils:search_element_by_xpath] Searching for XPath: '{xpath}' on device {device_id}")
            
            # Get all UI elements
            dump_success, elements, dump_error = self.dump_elements(device_id)
            
            if not dump_success:
                error_msg = f"Failed to dump UI elements: {dump_error}"
                print(f"[@lib:adbUtils:search_element_by_xpath] {error_msg}")
                return False, [], error_msg
            
            # Filter elements by XPath
            matches = []
            for element in elements:
                if hasattr(element, 'xpath') and element.xpath:
                    # Check if element's XPath matches the search
                    # Support both exact match and contains/startswith patterns
                    if element.xpath == xpath or xpath in element.xpath or element.xpath.startswith(xpath):
                        matches.append(element)
            
            success = len(matches) > 0
            if success:
                print(f"[@lib:adbUtils:search_element_by_xpath] SUCCESS: Found {len(matches)} matching elements")
                for element in matches:
                    print(f"[@lib:adbUtils:search_element_by_xpath]   Element {element.id}: {element.xpath}")
            else:
                print(f"[@lib:adbUtils:search_element_by_xpath] No elements found matching XPath '{xpath}'")
            
            return success, matches, ""
            
        except Exception as e:
            error_msg = f"XPath search failed: {e}"
            print(f"[@lib:adbUtils:search_element_by_xpath] ERROR: {error_msg}")
            return False, [], error_msg

    def check_element_exists(self, device_id: str, search_term: str, **options) -> Tuple[bool, Optional[AndroidElement], str]:
        """
        Check if an element exists using smart search. Supports pipe-separated terms for fallback (e.g., "OK|Accept|Confirm").
        
        Args:
            device_id: Android device ID
            search_term: The term to search for (case-insensitive, searches all attributes)
                        Can use pipe-separated terms: "text1|text2|text3"
            **options: Additional options (timeout, check_interval, etc.)
        
        Returns:
            Tuple of (exists, element_data_if_found, error_message)
        """
        try:
            # Check if we have pipe-separated terms
            if '|' in search_term:
                terms = [term.strip() for term in search_term.split('|') if term.strip()]
                
                for i, term in enumerate(terms):
                    
                    success, matches, error = self.smart_element_search(device_id, term.strip())
                    
                    if success and matches:
                        # Return the first match as AndroidElement
                        first_match = matches[0]
                        element_dict = first_match["full_element"]
                        
                        element = AndroidElement(
                            element_id=element_dict['id'],
                            tag=element_dict.get('tag', ''),
                            text=element_dict['text'],
                            resource_id=element_dict['resource_id'],
                            content_desc=element_dict['content_desc'], 
                            class_name=element_dict['class_name'],
                            bounds=element_dict['bounds'],
                            clickable=element_dict['clickable'],
                            enabled=element_dict['enabled'],
                            xpath=element_dict.get('xpath')
                        )
                        
                        return True, element, ""
                
                print(f"[@lib:adbUtils:check_element_exists] No matches found for any term in: {search_term}")
                return False, None, ""
            else:
                # Single term - original logic
                
                success, matches, error = self.smart_element_search(device_id, search_term)
                
                if not success:
                    return False, None, error
                
                if matches:
                    # Return the first match as AndroidElement
                    first_match = matches[0]
                    element_dict = first_match["full_element"]
                    
                    # Create AndroidElement from dict
                    element = AndroidElement(
                        element_id=element_dict['id'],
                        tag=element_dict.get('tag', ''),
                        text=element_dict['text'],
                        resource_id=element_dict['resource_id'],
                        content_desc=element_dict['content_desc'], 
                        class_name=element_dict['class_name'],
                        bounds=element_dict['bounds'],
                        clickable=element_dict['clickable'],
                        enabled=element_dict['enabled'],
                        xpath=element_dict.get('xpath')
                    )
                    
                    print(f"[@lib:adbUtils:check_element_exists] Found element: ID={element.id}")
                    return True, element, ""
                else:
                    print(f"[@lib:adbUtils:check_element_exists] No matches found")
                    return False, None, ""
            
        except Exception as e:
            error_msg = f"Element existence check failed: {e}"
            print(f"[@lib:adbUtils:check_element_exists] ERROR: {error_msg}")
            return False, None, error_msg

    def click_element_by_search(self, device_id: str, search_term: str, **options) -> bool:
        """
        Click on an element using search term. Supports pipe-separated terms for fallback (e.g., "OK|Accept|Confirm").
        
        Args:
            device_id: Android device ID
            search_term: Search term (case-insensitive, searches all attributes)
                        Can use pipe-separated terms: "text1|text2|text3"
            **options: Additional options
            
        Returns:
            bool: True if click successful
        """
        try:
            print(f"[@lib:adbUtils:click_element_by_search] Attempting to click using search term: '{search_term}'")
            
            # Check if element exists (handles pipe-separated terms automatically)
            exists, element, error = self.check_element_exists(device_id, search_term)
            
            if exists and element:
                print(f"[@lib:adbUtils:click_element_by_search] Found element, attempting click")
                return self.click_element(device_id, element)
            else:
                print(f"[@lib:adbUtils:click_element_by_search] No element found: {error}")
                return False
                
        except Exception as e:
            print(f"[@lib:adbUtils:click_element_by_search] Error: {e}")
            return False

    def input_text(self, device_id: str, search_term: str, text_to_input: str = None, **options) -> bool:
        """
        Input text, optionally into a specific element.

        Two modes:
        - 2 args (device_id, text): blind type into currently focused field
        - 3 args (device_id, search_term, text_to_input): find element, click it, then type

        Args:
            device_id: Android device ID
            search_term: When text_to_input is None, this is the text to type blindly.
                        When text_to_input is provided, this is the element search term.
            text_to_input: Text to input into the found element (optional)
            **options: Additional options

        Returns:
            bool: True if input successful
        """
        try:
            # Mode 1: blind type (no element search) - called with 2 args
            if text_to_input is None:
                text = search_term
                print(f"[@lib:adbUtils:input_text] Blind typing: '{text}'")
                escaped_text = text.replace(' ', '%s')
                input_command = f'adb -s {device_id} shell input text "{escaped_text}"'
                success, stdout, stderr, exit_code = self.execute_command(input_command)
                if success and exit_code == 0:
                    print(f"[@lib:adbUtils:input_text] SUCCESS: Blind input completed")
                    return True
                else:
                    print(f"[@lib:adbUtils:input_text] Blind input failed: {stderr}")
                    return False

            # Mode 2: find element, click, then type
            print(f"[@lib:adbUtils:input_text] Looking for input field using search term: '{search_term}'")
            print(f"[@lib:adbUtils:input_text] Text to input: '{text_to_input}'")

            # Check if element exists (handles pipe-separated terms automatically)
            exists, element, error = self.check_element_exists(device_id, search_term)
            
            if exists and element:
                print(f"[@lib:adbUtils:input_text] Found input field, attempting to click and input text")
                
                # First click on the element to focus it
                click_success = self.click_element(device_id, element)
                
                if click_success:
                    # Small delay after click
                    time.sleep(0.5)
                    
                    # Clear existing text first
                    clear_command = f"adb -s {device_id} shell input keyevent KEYCODE_CTRL_A"
                    self.execute_command(clear_command)
                    time.sleep(0.2)
                    
                    clear_command = f"adb -s {device_id} shell input keyevent KEYCODE_DEL"
                    self.execute_command(clear_command)
                    time.sleep(0.2)
                    
                    # Input the text
                    # Escape special characters for shell
                    escaped_text = text_to_input.replace('"', '\\"').replace("'", "\\'").replace(' ', '\\ ')
                    input_command = f"adb -s {device_id} shell input text \"{escaped_text}\""
                    
                    success, stdout, stderr, exit_code = self.execute_command(input_command)
                    
                    if success and exit_code == 0:
                        print(f"[@lib:adbUtils:input_text] SUCCESS: Input text completed")
                        return True
                    else:
                        print(f"[@lib:adbUtils:input_text] Text input failed: {stderr}")
                        return False
                else:
                    print(f"[@lib:adbUtils:input_text] Element found but click failed")
                    return False
            else:
                print(f"[@lib:adbUtils:input_text] No input field found: {error}")
                return False
                
        except Exception as e:
            print(f"[@lib:adbUtils:input_text] Error: {e}")
            return False

    def tap_coordinates(self, device_id: str, x: int, y: int) -> bool:
        """
        Tap at specific coordinates on the device screen.
        
        Args:
            device_id: Android device ID
            x: X coordinate
            y: Y coordinate
            
        Returns:
            bool: True if tap successful
        """
        try:
            command = f"adb -s {device_id} shell input tap {x} {y}"
            success, stdout, stderr, exit_code = self.execute_command(command)
            
            if success and exit_code == 0:
                print(f"[@lib:adbUtils:tap_coordinates] Successfully tapped at ({x}, {y})")
                return True
            else:
                print(f"[@lib:adbUtils:tap_coordinates] Tap failed: {stderr}")
                return False
                
        except Exception as e:
            print(f"[@lib:adbUtils:tap_coordinates] Error: {e}")
            return False

    def swipe(self, device_id: str, from_x: int, from_y: int, to_x: int, to_y: int, duration: int = 300) -> bool:
        """
        Swipe from one coordinate to another on the device screen.
        
        Args:
            device_id: Android device ID
            from_x: Starting X coordinate
            from_y: Starting Y coordinate
            to_x: Ending X coordinate
            to_y: Ending Y coordinate
            duration: Swipe duration in milliseconds (default: 300)
            
        Returns:
            bool: True if swipe successful
        """
        try:
            command = f"adb -s {device_id} shell input swipe {from_x} {from_y} {to_x} {to_y} {duration}"
            success, stdout, stderr, exit_code = self.execute_command(command)
            
            if success and exit_code == 0:
                print(f"[@lib:adbUtils:swipe] Successfully swiped from ({from_x}, {from_y}) to ({to_x}, {to_y}) in {duration}ms")
                return True
            else:
                print(f"[@lib:adbUtils:swipe] Swipe failed: {stderr}")
                return False
                
        except Exception as e:
            print(f"[@lib:adbUtils:swipe] Error: {e}")
            return False 