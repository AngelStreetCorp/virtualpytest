"""
Action Tools - Device action execution

Execute remote commands, ADB commands, web actions, and desktop actions.
"""

import json
import time
import uuid
from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from ..utils.screenshot_capture import capture_image_block
from shared.src.lib.config.constants import APP_CONFIG, get_team_id


class ActionTools:
    """Device action execution tools"""

    # Commands blocked for mobile devices (android_mobile, android_tv)
    # These are filtered from list_actions() and blocked in execute_device_action()
    MOBILE_BLOCKED_COMMANDS = {'click_element_by_id', 'swipe'}

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
        # Track active control sessions per device for auto-lock
        self._control_sessions: Dict[str, str] = {}
    
    def list_actions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available actions for a device.
        
        Example: list_actions(host_name='host1', device_id='device1')
        
        Args:
            params: {
                'host_name': str (REQUIRED - host name where device is connected),
                'device_id': str (REQUIRED - device identifier)
            }
            
        Returns:
            MCP-formatted response with categorized list of available actions
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
        
        # Call EXISTING endpoint
        print(f"[@MCP:list_actions] Calling /server/system/getDeviceActions")
        result = self.api.get('/server/system/getDeviceActions', params=query_params)
        print(f"[@MCP:list_actions] ✅ Fetched actions from backend")
        
        # Check for errors
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to list actions')
            return {"content": [{"type": "text", "text": f"❌ List failed: {error_msg}"}], "isError": True}
        
        # Format response - group actions by category
        device_action_types = result.get('device_action_types', {})
        device_model = result.get('device_model', 'unknown')
        
        # Filter out blocked commands for mobile devices
        if device_model in ['android_mobile', 'android_tv']:
            device_action_types = self._filter_mobile_actions(device_action_types)
        
        if not device_action_types:
            return {"content": [{"type": "text", "text": f"No actions available for {device_model} device"}], "isError": False}
        
        response_text = f"Available actions for {device_model} ({device_id}):\n\n"
        
        if device_model in ['host_vnc', 'web']:
            response_text += "💡 WEB DEVICE - See execute_device_action tool description for detailed usage\n\n"
        
        for category, actions in device_action_types.items():
            if not actions:
                continue
            response_text += f"**{category.upper()}** ({len(actions)} actions):\n"
            for action in actions[:10]:  # Limit to first 10 per category
                label = action.get('label', action.get('command', 'unknown'))
                command = action.get('command', 'unknown')
                params_dict = action.get('params', {})
                description = action.get('description', '')
                
                response_text += f"  {label} (command: {command})\n"

                # Enhanced parameter information based on device model and command
                if command == 'click_element':
                    if device_model in ['android_mobile', 'android_tv']:
                        response_text += f"    params: {{'text': 'element_text', 'wait_time': 1000, 'iteration': 1}}  # text REQUIRED, wait_time optional\n"
                        response_text += f"    note: For mobile devices, use text-based clicking\n"
                    else:  # web devices
                        response_text += f"    params: {{'text': 'element_text', 'xpath': 'xpath_selector', 'wait_time': 1000}}\n"
                        response_text += f"    note: For web devices, text or xpath can be used\n"
                elif command == 'click_element_by_id':
                    if device_model in ['android_mobile', 'android_tv']:
                        response_text += f"    BLOCKED: Not reliable on mobile ADB\n"
                    else:
                        response_text += f"    params: {{'element_id': 'html_id', 'wait_time': 1000}}  # element_id REQUIRED\n"
                elif params_dict:
                    response_text += f"    params: {params_dict}\n"

                if description:
                    response_text += f"    {description}\n"
            
            if len(actions) > 10:
                response_text += f"  ... and {len(actions) - 10} more\n"
            response_text += "\n"
        
        return {
            "content": [{"type": "text", "text": response_text}],
            "isError": False,
            "device_action_types": device_action_types  # Include full data for programmatic use
        }
    
    def _filter_mobile_actions(self, device_action_types: Dict[str, Any]) -> Dict[str, Any]:
        """Filter out blocked commands for mobile devices"""
        filtered = {}
        for category, actions in device_action_types.items():
            filtered_actions = [
                action for action in actions
                if action.get('command') not in self.MOBILE_BLOCKED_COMMANDS
            ]
            if filtered_actions:
                filtered[category] = filtered_actions
        return filtered
    
    def _auto_lock(self, host_name: str, device_id: str, team_id: str, force_unlock: bool = False) -> Dict[str, Any]:
        """Auto-acquire device lock. Returns error dict on failure, None on success."""
        device_key = f"{host_name}:{device_id}"

        # Reuse existing session if we already hold the lock
        if device_key in self._control_sessions:
            return None

        session_id = f"mcp-action-{uuid.uuid4()}"

        data = {
            'host_name': host_name,
            'device_id': device_id,
            'session_id': session_id,
        }

        result = self.api.post('/server/control/takeControl', data=data, params={'team_id': team_id})

        # If locked and force requested, preempt the existing lock
        if not result.get('success') and result.get('errorType') == 'device_locked' and force_unlock:
            owner_type = result.get('owner_type') or (result.get('lock_info') or {}).get('owner_type')
            # Graceful takeover for execution locks: aborts the running script/deployment first.
            if owner_type in ('script_execution', 'deployment_execution', 'mcp'):
                takeover_data = {
                    'host_name': host_name,
                    'device_id': device_id,
                    'requested_by_session': session_id,
                    'stop_running_execution': True,
                    'reason': 'mcp_force_unlock',
                }
                result = self.api.post('/server/control/takeover', data=takeover_data, params={'team_id': team_id})

            # Still locked (e.g. a manual_control lock, which /takeover refuses to preempt).
            # force_unlock=true is an explicit override and a manual lock has no running
            # execution to abort, so clear it unconditionally and retake.
            if not result.get('success'):
                self.api.post('/server/control/forceUnlock',
                              data={'host_name': host_name, 'device_id': device_id},
                              params={'team_id': team_id})
                result = self.api.post('/server/control/takeControl', data=data, params={'team_id': team_id})

        if not result.get('success'):
            error_type = result.get('errorType', '')
            if error_type == 'device_locked':
                owner_type = result.get('owner_type') or (result.get('lock_info') or {}).get('owner_type', 'unknown')

                # Piggyback on existing manual_control lock (e.g. from take_control).
                # Don't store in _control_sessions so _auto_unlock becomes a no-op.
                if owner_type == 'manual_control':
                    print(f"[@MCP:_auto_lock] Device {device_key} held by manual_control — piggybacking")
                    return None

                msg = result.get('message', 'Device is currently in use')
                error_msg = f"Device '{device_id}' on host '{host_name}' is locked by {owner_type}. {msg}"
                error_msg += ". Retry with force_unlock=true to preempt."
                return {"content": [{"type": "text", "text": error_msg}], "isError": True, "errorType": "device_locked"}
            return {"content": [{"type": "text", "text": f"Failed to lock device: {result.get('error', 'Unknown error')}"}], "isError": True}

        self._control_sessions[device_key] = session_id
        return None

    def _auto_unlock(self, host_name: str, device_id: str, team_id: str) -> None:
        """Release device lock acquired by auto-lock."""
        device_key = f"{host_name}:{device_id}"
        session_id = self._control_sessions.pop(device_key, None)
        if not session_id:
            return

        data = {
            'host_name': host_name,
            'device_id': device_id,
            'session_id': session_id,
        }
        self.api.post('/server/control/releaseControl', data=data, params={'team_id': team_id})

    def execute_device_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute batch of actions on a device. Supports remote commands, ADB, web actions, desktop automation.
        Automatically acquires and releases device lock.

        COMMON ACTION FORMATS BY DEVICE TYPE:

        📱 MOBILE DEVICES (android_mobile, android_tv):
        - click_element: {"command": "click_element", "params": {"text": "Button Text", "wait_time": 1000, "iteration": 1}}
          * text: Element text to click (REQUIRED)
          * wait_time: Milliseconds to wait after click (default: 1000)
        - click_element_by_id: BLOCKED for mobile devices (unreliable on ADB)

        🌐 WEB DEVICES (host_vnc, web):
        - click_element: {"command": "click_element", "params": {"text": "Button Text", "wait_time": 1000}}
          * text: Visible text of element to click (REQUIRED)
          * xpath: XPath selector (alternative to text)
          * wait_time: Milliseconds to wait after click (default: 1000)
        - click_element_by_id: {"command": "click_element_by_id", "params": {"element_id": "btn-submit", "wait_time": 1000}}
          * element_id: HTML element ID attribute (REQUIRED)
          * wait_time: Milliseconds to wait after click (default: 1000)
        - navigate: {"command": "navigate", "params": {"url": "https://example.com"}}
          * url: URL to navigate to (REQUIRED)

        ⚠ NEVER include `capture_screenshot` inside the `actions[]` array.
           `capture_screenshot` is a SEPARATE TOP-LEVEL MCP tool. Call it
           directly as `capture_screenshot(host_name=…, device_id=…)`. The
           IR/BLE/ADB controllers do not implement a `capture_screenshot`
           action and will fail silently with "no error details".

        🎮 REMOTE CONTROLS (press_key format depends on controller type):
        - ADB (android_mobile / android_tv): Android KEYCODE name WITHOUT `KEYCODE_` prefix
            {"command": "press_key", "params": {"key": "HOME"}}    # HOME, BACK, DPAD_DOWN, VOLUME_UP, …
        - Infrared (IR blaster, stb devices with DEVICE*_IR_TYPE set): bare name from
          `backend_host/src/controllers/remote/ir_conf/<ir_type>.json`:
            {"command": "press_key", "params": {"action_type": "infrared", "key": "HOME"}}
                                                                 # e.g. stb.json: HOME, MENU, OK, BACK, RIGHT, …
        - Bluetooth HID (BLE-emulated remote, DEVICE*_BLE_TYPE set): bare name from
          `backend_host/src/controllers/remote/bluetooth/ble_conf/<ble_type>.json`:
            {"command": "press_key", "params": {"action_type": "bluetooth", "key": "INFO"}}
        ⚠ **Do NOT use `KEY_HOME` or `KEYCODE_HOME`** — the bare name is correct.
           The old {"command": "KEY_HOME"} shorthand is deprecated; prefer `press_key` with `params.key`.

        ⚠️ COMMON MISTAKES TO AVOID:
        - Don't use "click" command - use "click_element" instead
        - Always wrap parameters in "params": {...} object
        - For mobile: use "text" parameter, not "element_id"
        - Check device type - some commands are blocked per device model
        - Do NOT pass verification commands (waitForTextToAppear, waitForElementToAppear)
          through this tool — use verify_node() instead. This tool is for ACTIONS only.

        Example: execute_device_action(host_name='host1', device_id='device1', actions=[{'command': 'click_element', 'params': {'text': 'Replay'}}])

        Args:
            params: {
                'host_name': str (REQUIRED - host name where device is connected),
                'device_id': str (REQUIRED - device identifier),
                'actions': list (REQUIRED - list of action dicts with command and params),
                'force_unlock': bool (OPTIONAL - preempt existing lock if device is locked),
                'include_screenshot': bool (OPTIONAL - include a device screenshot of the resulting screen in the response, default false)
            }

        Returns:
            MCP-formatted response with execution results
        """
        device_id = params.get('device_id')
        host_name = params.get('host_name')
        team_id = params.get('team_id', get_team_id())
        actions = params.get('actions', [])
        retry_actions = params.get('retry_actions', [])
        failure_actions = params.get('failure_actions', [])
        force_unlock = bool(params.get('force_unlock', False))
        include_screenshot = params.get('include_screenshot', False)
        # fast_screenshot: the inline screenshot skips the host fingerprint/settle (caller
        # computes its own fingerprint — the auto-builder). ~2s off every keyed press.
        fast_screenshot = bool(params.get('fast_screenshot', False))

        # Validate required parameters
        if not host_name:
            return {"content": [{"type": "text", "text": "Error: host_name is required"}], "isError": True}
        if not device_id:
            return {"content": [{"type": "text", "text": "Error: device_id is required"}], "isError": True}
        if not actions:
            return {"content": [{"type": "text", "text": "Error: actions array is required"}], "isError": True}

        # Auto-convert wrong action format and validate
        # Correct format: {"command": "press_key", "params": {"key": "BACK"}}
        # Wrong format:   {"action_type": "adb", "action_name": "press_key", "parameters": {"key": "BACK"}}
        normalized_actions = []
        for i, action in enumerate(actions):
            if not action.get('command') and action.get('action_name'):
                # Auto-convert legacy/wrong format
                converted = {
                    'command': action['action_name'],
                    'params': action.get('parameters', action.get('params', {}))
                }
                # Preserve other fields like continue_on_fail, iterator
                for key in ('continue_on_fail', 'iterator', 'action_type'):
                    if key in action:
                        converted[key] = action[key]
                print(f"[@MCP:execute_device_action] ⚠️  Auto-converted action {i} from {{action_name/parameters}} to {{command/params}} format")
                normalized_actions.append(converted)
            elif not action.get('command'):
                return {"content": [{"type": "text", "text": f"Error: action {i} missing 'command' field. Expected format: {{\"command\": \"press_key\", \"params\": {{\"key\": \"BACK\"}}}}"}], "isError": True}
            else:
                normalized_actions.append(action)
        actions = normalized_actions

        # Auto-inject action_type if missing — detect from device model
        # This prevents "Remote controller not available" for web devices
        needs_action_type = any(not a.get('action_type') for a in actions)
        if needs_action_type:
            try:
                query = {'host_name': host_name, 'device_id': device_id, 'team_id': team_id}
                device_info = self.api.get('/server/system/getDeviceActions', params=query)
                device_model = device_info.get('device_model', '') if device_info else ''
                if device_model:
                    if device_model in ('host_vnc', 'web') or 'web' in device_model:
                        inferred_type = 'web'
                    elif 'android_tv' in device_model or 'stb' in device_model:
                        inferred_type = 'remote'
                    elif 'android' in device_model:
                        inferred_type = 'adb'
                    else:
                        inferred_type = None

                    if inferred_type:
                        for a in actions:
                            if not a.get('action_type'):
                                a['action_type'] = inferred_type
                        print(f"[@MCP:execute_device_action] Auto-injected action_type='{inferred_type}' for {device_model}")
            except Exception as e:
                print(f"[@MCP:execute_device_action] action_type auto-detect failed: {e}")

        # Auto-lock device
        lock_error = self._auto_lock(host_name, device_id, team_id, force_unlock)
        if lock_error:
            return lock_error

        try:
            # Build request - SAME format as frontend (useAction.ts line 166-172)
            data = {
                'device_id': device_id,
                'host_name': host_name,
                'actions': actions,
                'retry_actions': retry_actions,
                'failure_actions': failure_actions
            }

            query_params = {'team_id': team_id}

            # Call EXISTING endpoint - SAME as frontend (useAction.ts line 163)
            print(f"[@MCP:execute_device_action] Calling /server/action/executeBatch")
            result = self.api.post('/server/action/executeBatch', data=data, params=query_params)

            # Check for errors
            if not result.get('success'):
                error_msg = result.get('error', 'Action execution failed')

                # Provide user-friendly error messages for common ADB issues
                error_lower = error_msg.lower()
                if 'adb:' in error_lower and 'not found' in error_lower:
                    return {"content": [{"type": "text", "text": f"❌ Device connection failed: {error_msg}\n   Check that the device is connected and ADB is running."}], "isError": True}
                elif 'adb:' in error_lower:
                    return {"content": [{"type": "text", "text": f"❌ ADB error: {error_msg}\n   Verify ADB connection and device status."}], "isError": True}

                return {"content": [{"type": "text", "text": f"Action execution failed: {error_msg}"}], "isError": True}

            # Check if async (returns execution_id) - SAME as frontend (useAction.ts line 188)
            if result.get('execution_id'):
                execution_id = result['execution_id']
                print(f"[@MCP:execute_device_action] Async execution started: {execution_id}")

                # POLL for completion - SAME pattern as frontend (useAction.ts line 200-246)
                return self._poll_action_completion(execution_id, device_id, host_name, team_id, include_screenshot=include_screenshot, fast_screenshot=fast_screenshot)

            print(f"[@MCP:execute_device_action] Sync execution completed")
            passed = result.get('passed_count', 0)
            total = result.get('total_count', 0)
            failed = result.get('failed_count', 0)
            execution_time = result.get('execution_time_ms', 0)

            if passed == total:
                # An action result only proves that the command was accepted by
                # the controller. It does not prove that the device reached the
                # intended state (for example, a page script can cancel a click).
                # Keep the tool successful for callers, but do not present an
                # unverified action as a passing assertion.
                msg = f"⚠️ {passed}/{total} action commands completed; state change not verified ({execution_time}ms)"
                msg = self._append_action_output(msg, result)
            else:
                details = self._format_failure_details(result)
                msg = f"❌ {passed}/{total} failed"
                if details:
                    msg += f": {details}"
                msg = self._append_action_output(msg, result)
            response = {
                "content": [{"type": "text", "text": msg}],
                "isError": failed > 0,
                "action_state_verified": False,
            }
            if include_screenshot:
                self._attach_screenshot(response, device_id, host_name, team_id, fast=fast_screenshot)
            return response
        finally:
            # Auto-unlock device
            self._auto_unlock(host_name, device_id, team_id)
    
    @staticmethod
    def _format_failure_details(result: Dict[str, Any]) -> str:
        """Extract per-action error details from execution result."""
        details = []
        for ar in result.get('results', result.get('action_results', [])):
            if not isinstance(ar, dict):
                continue
            status = ar.get('status', '')
            if status in ('passed', 'completed', 'success'):
                continue
            command = ar.get('command', ar.get('action', 'unknown'))
            error = ar.get('error') or ar.get('error_msg') or ar.get('message') or ''
            if error:
                details.append(f"{command}: {error}")
            elif status:
                details.append(f"{command}: {status}")
        # Also check top-level error field
        top_error = result.get('error') or result.get('error_msg') or ''
        if top_error and not details:
            details.append(str(top_error))
        return '; '.join(details)

    def _append_action_output(self, msg: str, result: Dict[str, Any]) -> str:
        """Extract and append action output data (DOM dump, page info, etc.) to response message."""
        import json as _json
        outputs = []

        # Check top-level output_data
        top_output = result.get('output_data') or {}
        if top_output:
            outputs.append(top_output)

        # Check individual action results (field is 'results' not 'action_results')
        for ar in result.get('results', result.get('action_results', [])):
            if isinstance(ar, dict):
                od = ar.get('output_data') or ar.get('additional_data') or {}
                if od:
                    outputs.append(od)
                # Also capture direct fields from controller (url, title, elements, etc.)
                for key in ('url', 'title', 'elements', 'page_info', 'text', 'extracted_text'):
                    if key in ar and ar[key]:
                        outputs.append({key: ar[key]})

        if outputs:
            output_str = _json.dumps(outputs if len(outputs) > 1 else outputs[0], default=str)
            # Limit to 3000 chars to avoid token bloat
            if len(output_str) > 3000:
                output_str = output_str[:3000] + '...(truncated)'
            msg += f"\n\nOutput:\n{output_str}"

        return msg

    def _attach_screenshot(self, response: Dict[str, Any], device_id: str, host_name: str, team_id: str,
                           fast: bool = False) -> None:
        """Append a device screenshot (base64 image block) to an MCP response, in place.

        No-op if the capture fails — never breaks the primary action result.
        fast=True skips the host-side fingerprint/settle (caller does its own fingerprint).
        """
        image_block = capture_image_block(self.api, device_id, host_name, team_id, fast=fast)
        if image_block:
            response.setdefault('content', []).append(image_block)

    def _poll_action_completion(self, execution_id: str, device_id: str, host_name: str, team_id: str, max_wait: int = 180, include_screenshot: bool = False, fast_screenshot: bool = False) -> Dict[str, Any]:
        """
        Poll action execution until complete

        REUSES existing /server/action/execution/<id>/status API (same as frontend)
        Pattern from useAction.ts lines 200-246
        """
        poll_interval = 1  # 1 second (same as frontend line 206)
        elapsed = 0

        print(f"[@MCP:poll_action] Polling for execution {execution_id} (max {max_wait}s)")

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            # Check for cancellation by polling the execution status for any cancellation indicators
            # If the execution was cancelled externally, it should show as error or completed with cancellation
            status = self.api.get(
                f'/server/action/execution/{execution_id}/status',
                params={'device_id': device_id, 'host_name': host_name, 'team_id': team_id}
            )

            # Check if execution was cancelled (status might indicate cancellation)
            if status.get('status') == 'cancelled':
                print(f"[@MCP:poll_action] Action execution cancelled after {elapsed}s")
                return {"content": [{"type": "text", "text": "🛑 Action execution cancelled"}], "isError": True}
            
            current_status = status.get('status')
            
            if current_status == 'completed':
                print(f"[@MCP:poll_action] Action execution completed after {elapsed}s")
                result = status.get('result', {})
                passed = result.get('passed_count', 0)
                total = result.get('total_count', 0)
                failed = result.get('failed_count', 0)
                execution_time = result.get('execution_time_ms', 0)

                # Detect 0/0 case (all actions filtered out — wrong format or invalid)
                if total == 0 and not result.get('success', True):
                    error_msg = result.get('error', 'All actions were invalid')
                    msg = f"❌ 0 actions executed: {error_msg}. Expected format: {{\"command\": \"press_key\", \"params\": {{\"key\": \"BACK\"}}}}"
                    print(f"[@MCP:poll_action] {msg[:200]}")
                    return {"content": [{"type": "text", "text": msg}], "isError": True}

                if failed > 0 or passed < total:
                    details = self._format_failure_details(result)
                    msg = f"❌ {passed}/{total} failed"
                    if details:
                        msg += f": {details}"
                    msg = self._append_action_output(msg, result)
                    print(f"[@MCP:poll_action] {msg[:200]}")
                    response = {"content": [{"type": "text", "text": msg}], "isError": True}
                else:
                    msg = f"⚠️ {passed}/{total} action commands completed; state change not verified ({execution_time}ms)"
                    msg = self._append_action_output(msg, result)
                    print(f"[@MCP:poll_action] {msg[:100]}")
                    response = {
                        "content": [{"type": "text", "text": msg}],
                        "isError": False,
                        "action_state_verified": False,
                    }

                # Attach a screenshot on both pass and fail so the resulting screen is visible
                if include_screenshot:
                    self._attach_screenshot(response, device_id, host_name, team_id, fast=fast_screenshot)
                return response
            
            elif current_status == 'error':
                print(f"[@MCP:poll_action] Action execution failed after {elapsed}s")
                error = status.get('error', 'Action execution failed')
                return {"content": [{"type": "text", "text": f"❌ Action execution failed: {error}"}], "isError": True}
            
            elif current_status in ['pending', 'running']:
                print(f"[@MCP:poll_action] Status: {current_status} - {elapsed}s elapsed")
        
        print(f"[@MCP:poll_action] Action execution timed out after {max_wait}s")
        return {"content": [{"type": "text", "text": f"⏱️ Action execution timed out after {max_wait}s"}], "isError": True}
    
