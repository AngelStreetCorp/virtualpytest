"""
Verification Tools - Device state verification

Verify UI elements, video playback, text, and other device states.
"""

import time
from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from ..utils.screenshot_capture import capture_image_block
from shared.src.lib.config.constants import APP_CONFIG, get_team_id


class VerificationTools:
    """Device state verification tools"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
    
    def list_verifications(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available verification types for a device.

        ⚠️ CRITICAL: Verification commands are DEVICE-SPECIFIC. Always call this tool first
        to discover which verifications are available for YOUR device before using verify_node.

        Common confusion:
        - Web devices (host_vnc/web): Use 'waitForElementToAppear' (DOM-based, verification_type='web')
        - Mobile/TV devices: Use 'waitForElementToAppear' (ADB-based, verification_type='adb')
        - OCR capture devices: Use 'waitForTextToAppear' (screenshot OCR, verification_type='text')
        - ❌ Do NOT use 'waitForTextToAppear' on web devices — it uses OCR, not Playwright DOM

        Example: list_verifications(host_name='host-clone-1', device_id='host')

        Args:
            params: {
                'host_name': str (REQUIRED - host name where device is connected),
                'device_id': str (REQUIRED - device identifier)
            }

        Returns:
            MCP-formatted response with categorized list of available verifications
        """
        device_id = params.get('device_id')
        host_name = params.get('host_name')
        team_id = params.get('team_id', get_team_id())
        
        # Validate required parameters
        if not host_name:
            return {"content": [{"type": "text", "text": "Error: host_name is required"}], "isError": True}
        if not device_id:
            return {"content": [{"type": "text", "text": "Error: device_id is required"}], "isError": True}
        
        query_params = {
            'host_name': host_name,
            'device_id': device_id,
            'team_id': team_id
        }
        
        # Call EXISTING endpoint (same as list_actions - returns both)
        print(f"[@MCP:list_verifications] Calling /server/system/getDeviceActions")
        result = self.api.get('/server/system/getDeviceActions', params=query_params)
        
        # Check for errors
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to list verifications')

            # Provide user-friendly error messages for common device issues
            error_lower = error_msg.lower()
            if 'adb:' in error_lower and 'not found' in error_lower:
                return {"content": [{"type": "text", "text": f"❌ Device connection failed: {error_msg}\n   Check that the device is connected and ADB is running."}], "isError": True}
            elif 'adb:' in error_lower:
                return {"content": [{"type": "text", "text": f"❌ ADB error: {error_msg}\n   Verify ADB connection and device status."}], "isError": True}

            return {"content": [{"type": "text", "text": f"❌ List failed: {error_msg}"}], "isError": True}
        
        # Format response - group verifications by type
        device_verification_types = result.get('device_verification_types', {})
        device_model = result.get('device_model', 'unknown')
        
        if not device_verification_types:
            return {"content": [{"type": "text", "text": f"No verifications available for {device_model} device"}], "isError": False}
        
        response_text = f"📋 Available verifications for {device_model} ({device_id}):\n\n"
        
        if device_model in ['host_vnc', 'web']:
            response_text += "For waitForElementToAppear search_term, use selector priority:\n"
            response_text += "1. #id > 2. //xpath > 3. [attr] or .class > 4. plain text (fallback)\n"
            response_text += "1 unique selector is enough. Only use multiple verifications if single selector is not unique.\n"
            response_text += "Prefer stable structural elements (form fields, buttons) over dynamic content.\n\n"
        
        for category, verifications in device_verification_types.items():
            if not verifications:
                continue
            response_text += f"**{category.upper()}** ({len(verifications)} verifications):\n"
            
            # Handle both dict and list structures
            if isinstance(verifications, dict):
                items = list(verifications.items())[:10]
                for method_name, method_info in items:
                    description = method_info.get('description', '')
                    params_dict = method_info.get('params', {})
                    
                    response_text += f"  • {method_name}\n"
                    if description:
                        response_text += f"    {description}\n"
                    if params_dict:
                        response_text += f"    params: {params_dict}\n"
                
                if len(verifications) > 10:
                    response_text += f"  ... and {len(verifications) - 10} more\n"
            elif isinstance(verifications, list):
                for verification in verifications[:10]:
                    label = verification.get('label', verification.get('command', 'unknown'))
                    command = verification.get('command', 'unknown')
                    params_dict = verification.get('params', {})
                    description = verification.get('description', '')
                    
                    response_text += f"  • {label} (command: {command})\n"
                    if params_dict:
                        response_text += f"    params: {params_dict}\n"
                    if description:
                        response_text += f"    {description}\n"
                
                if len(verifications) > 10:
                    response_text += f"  ... and {len(verifications) - 10} more\n"
            
            response_text += "\n"
        
        return {
            "content": [{"type": "text", "text": response_text}],
            "isError": False,
            "device_verification_types": device_verification_types  # Include full data for programmatic use
        }
    
    def dump_ui_elements(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dump UI elements from current device screen

        REUSES existing verification endpoints

        Args:
            params: {
                'device_id': str (OPTIONAL - defaults to 'device1'),
                'host_name': str (OPTIONAL - defaults to 'host1'),
                'team_id': str (OPTIONAL),
                'platform': str (OPTIONAL - 'mobile', 'web', 'tv')
            }

        Returns:
            MCP-formatted response with UI elements array
        """
        device_id = params.get('device_id')
        host_name = params.get('host_name')
        team_id = params.get('team_id', get_team_id())
        platform = params.get('platform', 'mobile')

        query_params = {
            'device_id': device_id,
            'host_name': host_name,
            'team_id': team_id,
            'platform': platform
        }

        print(f"[@MCP:dump_ui_elements] Dumping UI for {device_id} on {host_name}")

        # Use /server/remote/dumpUi endpoint (proxies to backend_host)
        result = self.api.post('/server/remote/dumpUi', data=query_params)

        # Check for errors
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to dump UI elements')

            # Provide user-friendly error messages for common ADB issues
            error_lower = error_msg.lower()
            if 'adb:' in error_lower and 'not found' in error_lower:
                return {"content": [{"type": "text", "text": f"❌ Device connection failed: {error_msg}\n   Check that the device is connected and ADB is running."}], "isError": True}
            elif 'adb:' in error_lower:
                return {"content": [{"type": "text", "text": f"❌ ADB error: {error_msg}\n   Verify ADB connection and device status."}], "isError": True}

            return {"content": [{"type": "text", "text": f"❌ UI dump failed: {error_msg}"}], "isError": True}

        elements = result.get('elements', [])

        if not elements:
            return {"content": [{"type": "text", "text": "No UI elements found"}], "isError": False}

        # Strip bloat: remove xpath, className, package - keep only essential fields
        minimal_elements = []
        for e in elements:
            minimal = {
                'id': e.get('id'),
                'text': e.get('text', ''),
                'contentDesc': e.get('contentDesc', ''),
                'clickable': e.get('clickable', False),
                'bounds': e.get('bounds', {})
            }
            minimal_elements.append(minimal)

        clickable = [e for e in elements if e.get('clickable')]
        text_summary = f"{len(elements)} elements ({len(clickable)} clickable)"

        return {
            "content": [{"type": "text", "text": text_summary}],
            "isError": False,
            "elements": minimal_elements
        }

    def get_installed_apps(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get list of installed apps on Android device

        Uses the get_installed_apps method from ADBUtils

        Args:
            params: {
                'device_id': str (OPTIONAL - defaults to 'device1'),
                'host_name': str (OPTIONAL - defaults to 'host1'),
                'team_id': str (OPTIONAL)
            }

        Returns:
            MCP-formatted response with installed apps list
        """
        device_id = params.get('device_id', 'device1')
        host_name = params.get('host_name')
        team_id = params.get('team_id', get_team_id())

        query_params = {
            'device_id': device_id,
            'host_name': host_name,
            'team_id': team_id
        }

        print(f"[@MCP:get_installed_apps] Getting installed apps for {device_id} on {host_name}")

        # Use /server/remote/getApps endpoint (proxies to backend_host)
        result = self.api.post('/server/remote/getApps', data=query_params)

        # Check for errors
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to get installed apps')

            # Provide user-friendly error messages for common ADB issues
            error_lower = error_msg.lower()
            if 'adb:' in error_lower and 'not found' in error_lower:
                return {"content": [{"type": "text", "text": f"❌ Device connection failed: {error_msg}\n   Check that the device is connected and ADB is running."}], "isError": True}
            elif 'adb:' in error_lower:
                return {"content": [{"type": "text", "text": f"❌ ADB error: {error_msg}\n   Verify ADB connection and device status."}], "isError": True}

            return {"content": [{"type": "text", "text": f"❌ Get apps failed: {error_msg}"}], "isError": True}

        apps = result.get('apps', [])

        if not apps:
            return {"content": [{"type": "text", "text": "No apps found"}], "isError": False}

        response_text = f"📱 Found {len(apps)} installed apps:\n\n"
        for app in apps[:20]:  # Show first 20 apps
            package_name = app.get('packageName', 'unknown')
            label = app.get('label', package_name)
            response_text += f"  • {label} ({package_name})\n"

        if len(apps) > 20:
            response_text += f"\n  ... and {len(apps) - 20} more apps"

        return {
            "content": [{"type": "text", "text": response_text}],
            "isError": False,
            "apps": apps
        }
    
    def _attach_screenshot(self, response: Dict[str, Any], device_id: str, host_name: str, team_id: str) -> None:
        """Append a device screenshot (base64 image block) to an MCP response, in place.

        No-op if the capture fails — never breaks the primary verification result.
        Verification especially benefits from a screenshot on failure (shows why it failed).
        """
        image_block = capture_image_block(self.api, device_id, host_name, team_id)
        if image_block:
            response.setdefault('content', []).append(image_block)

    def _poll_verification_completion(self, execution_id: str, device_id: str, host_name: str, team_id: str, max_wait: int = 30, include_screenshot: bool = False) -> Dict[str, Any]:
        """
        Poll verification execution until complete
        
        REUSES existing /server/verification/execution/<id>/status API (same as frontend)
        Pattern from useVerification.ts lines 278-306
        """
        poll_interval = 1  # 1 second (same as frontend line 283)
        elapsed = 0
        
        print(f"[@MCP:poll_verification] Polling for execution {execution_id} (max {max_wait}s)")
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            # Poll status endpoint - SAME as frontend (useVerification.ts line 273)
            status = self.api.get(
                f'/server/verification/execution/{execution_id}/status',
                params={'device_id': device_id, 'host_name': host_name, 'team_id': team_id}
            )
            
            current_status = status.get('status')
            
            if current_status == 'completed':
                print(f"[@MCP:poll_verification] Verification completed successfully after {elapsed}s")
                result = status.get('result', {})
                passed = result.get('passed_count', 0)
                total = result.get('total_count', 0)
                message = f"Verification completed: {passed}/{total} passed"
                response = {"content": [{"type": "text", "text": f"✅ {message}"}], "isError": False}
                if include_screenshot:
                    self._attach_screenshot(response, device_id, host_name, team_id)
                return response

            elif current_status == 'error':
                print(f"[@MCP:poll_verification] Verification failed after {elapsed}s")
                error = status.get('error', 'Verification failed')
                response = {"content": [{"type": "text", "text": f"❌ Verification failed: {error}"}], "isError": True}
                if include_screenshot:
                    self._attach_screenshot(response, device_id, host_name, team_id)
                return response
            
            elif current_status in ['pending', 'running']:
                print(f"[@MCP:poll_verification] Status: {current_status} - {elapsed}s elapsed")
        
        print(f"[@MCP:poll_verification] Verification timed out after {max_wait}s")
        return {"content": [{"type": "text", "text": f"⏱️ Verification timed out after {max_wait}s"}], "isError": True}
    
    def verify_node(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute verifications for a specific node. Runs embedded verifications using executeBatch endpoint.

        Uses node_label (human readable name) by default. Auto-resolves label to database node_id.

        Examples:
        - verify_node(node_label='home', userinterface_name='netflix_mobile')
        - verify_node(node_label='search', userinterface_name='netflix_mobile')

        Args:
            params: {
                'node_label': str (REQUIRED - human readable node name like 'home', 'search'),
                'userinterface_name': str (REQUIRED - user interface name for auto-resolving tree_id),
                'device_id': str (OPTIONAL - device identifier),
                'host_name': str (OPTIONAL - host name where device is connected),
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name if not provided),
                'node_id': str (OPTIONAL - exact node identifier from database, overrides node_label if provided),
                'include_screenshot': bool (OPTIONAL - include a device screenshot of the verified screen in the response, default false)
            }

        Returns:
            Verification results with pass/fail status

        Examples:
            verify_node({
                "node_label": "home",
                "userinterface_name": "netflix_mobile"
            })
        """
        try:
            # Accept either node_label (preferred) or node_id (for backward compatibility)
            node_identifier = params.get('node_label') or params.get('node_id')

            if not node_identifier:
                return {"content": [{"type": "text", "text": "Error: node_label or node_id is required"}], "isError": True}

            tree_id = params.get('tree_id')
            userinterface_name = params['userinterface_name']
            host_name = params.get('host_name')
            device_id = params.get('device_id')
            team_id = params.get('team_id', get_team_id())
            include_screenshot = params.get('include_screenshot', False)

            # Auto-resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                tree_id, _, _, error = self.api.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return {"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True}

            # Validate required parameters
            if not host_name:
                return {"content": [{"type": "text", "text": "Error: host_name is required. Use get_compatible_hosts(userinterface_name='...') to discover the correct host."}], "isError": True}

            print(f"[@MCP:verify_node] Verifying node '{node_identifier}' in tree {tree_id}")
            print(f"[@MCP:verify_node] About to call endpoint: /server/navigationTrees/{tree_id}/nodes/{node_identifier}")

            # STEP 1: Get the node to retrieve embedded verifications
            # The endpoint now handles robust resolution (tries node_id/label first, then fallback)
            try:
                print(f"[@MCP:verify_node] Making API call...")
                node_result = self.api.get(
                    f'/server/navigationTrees/{tree_id}/nodes/{node_identifier}',
                    params={'team_id': team_id}
                )
                print(f"[@MCP:verify_node] API call completed. Result type: {type(node_result)}")
                print(f"[@MCP:verify_node] Raw result: {node_result}")
                print(f"[@MCP:verify_node] Endpoint response: success={node_result.get('success')}, has_node={bool(node_result.get('node'))}")
            except Exception as e:
                print(f"[@MCP:verify_node] EXCEPTION in endpoint call: {type(e).__name__}: {e}")
                import traceback
                print(f"[@MCP:verify_node] Traceback: {traceback.format_exc()}")
                return {"content": [{"type": "text", "text": f"❌ Failed to call node endpoint: {str(e)}"}], "isError": True}

            if not node_result.get('success'):
                error_msg = node_result.get('error', 'Unknown error')
                print(f"[@MCP:verify_node] Node resolution failed: {error_msg}")
                return {"content": [{"type": "text", "text": f"❌ Failed to get node: {error_msg}"}], "isError": True}

            # Log resolution method if available
            resolution_method = node_result.get('resolution_method')
            if resolution_method and resolution_method.startswith('fallback'):
                print(f"[@MCP:verify_node] ⚠️  Fallback resolution used for '{node_identifier}'")

            node = node_result.get('node', {})
            verifications = node.get('verifications', [])
            node_display_name = node.get('label', node_identifier)
            
            if not verifications:
                return {"content": [{"type": "text", "text": f"ℹ️ Node {node_display_name} has no verifications to run"}], "isError": False}
            
            print(f"[@MCP:verify_node] Node has {len(verifications)} verifications - executing directly")
            
            # STEP 2: Execute verifications directly using /server/verification/executeBatch
            # SAME as frontend useVerification.ts line 247
            # Add userinterface_name to each verification for proper reference resolution
            verifications_with_ui = [
                {**v, 'userinterface_name': userinterface_name}
                for v in verifications
            ]
            
            # Get the resolved node_id from the response
            resolved_node_id = node.get('node_id') or node.get('id')

            result = self.api.post(
                '/server/verification/executeBatch',
                data={
                    'host_name': host_name,
                    'device_id': device_id,
                    'verifications': verifications_with_ui,
                    'node_id': resolved_node_id,
                    'tree_id': tree_id
                },
                params={'team_id': team_id}
            )
            
            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')

                # Provide user-friendly error messages for common device issues
                error_lower = error_msg.lower()
                if 'adb:' in error_lower and 'not found' in error_lower:
                    return {"content": [{"type": "text", "text": f"❌ Device connection failed: {error_msg}\n   Check that the device is connected and ADB is running."}], "isError": True}
                elif 'adb:' in error_lower:
                    return {"content": [{"type": "text", "text": f"❌ ADB error: {error_msg}\n   Verify ADB connection and device status."}], "isError": True}

                return {"content": [{"type": "text", "text": f"❌ Verification execution failed: {error_msg}"}], "isError": True}
            
            # STEP 3: Handle async execution - poll for completion
            execution_id = result.get('execution_id')
            if execution_id:
                print(f"[@MCP:verify_node] Async verification started, polling execution {execution_id}")
                return self._poll_verification_completion(execution_id, device_id, host_name, team_id, max_wait=30, include_screenshot=include_screenshot)

            # Synchronous result
            verification_results = result.get('results', [])
            passed_count = result.get('passed_count', 0)
            total_count = result.get('total_count', 0)

            if passed_count == total_count:
                response = {"content": [{"type": "text", "text": f"✅ Node verification passed: {passed_count}/{total_count} verifications succeeded\n   Node: {node_display_name}"}], "isError": False}
            else:
                failed = [vr for vr in verification_results if not vr.get('success')]
                failure_details = "\n   - ".join([f"{vr.get('command', 'unknown')}: {vr.get('message', 'no details')}" for vr in failed])
                response = {"content": [{"type": "text", "text": f"❌ Node verification failed: {passed_count}/{total_count} verifications succeeded\n   Node: {node_display_name}\n   Failed:\n   - {failure_details}"}], "isError": True}

            if include_screenshot:
                self._attach_screenshot(response, device_id, host_name, team_id)
            return response
        
        except Exception as e:
            print(f"[@MCP:verify_node] Error: {e}")
            return {"content": [{"type": "text", "text": f"❌ Error verifying node: {str(e)}"}], "isError": True}

