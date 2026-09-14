import time
from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import APP_CONFIG, get_team_id


class ScriptTools:
    """Script execution and listing tools"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
    

    
    def _filter_result_for_mcp(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter script execution result to only include essential fields.
        Reduces token usage by ~99% (22k -> 200 tokens) by excluding verbose stdout/stderr.
        
        Full logs are available via logs_url if needed for debugging.
        """
        if not result:
            return {}
        
        # Essential fields only - exclude stdout/stderr (thousands of tokens)
        return {
            'script_name': result.get('script_name'),
            'device_id': result.get('device_id'),
            'exit_code': result.get('exit_code'),
            'script_success': result.get('script_success'),
            'execution_time_ms': result.get('execution_time_ms'),
            'report_url': result.get('report_url'),
            'logs_url': result.get('logs_url'),
            'parameters': result.get('parameters'),
        }
    
    def list_scripts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all available Python scripts with their target rules (device requirements).

        ⚠️ IMPORTANT: Use this tool BEFORE execute_script to understand what device type each script requires.
        Each script includes target_rules that specify:
        - target_type: 'host' (runs on host machine), 'android_mobile', 'android_tv', etc.
        - device_model: specific device model or 'all'
        - host_os: required OS or 'all'

        After listing scripts, call get_device_info() or get_compatible_hosts() to find
        a matching host_name and device_id for the script you want to run.

        Example: list_scripts()

        Args:
            params: {}

        Returns:
            MCP-formatted response with list of scripts and their target_rules
        """
        team_id = params.get('team_id', get_team_id())

        query_params = {'team_id': team_id}

        # Use /server/executable/list which includes target_rules per script
        print(f"[@MCP:list_scripts] Calling /server/executable/list (includes target_rules)")
        result = self.api.get('/server/executable/list', params=query_params)

        # Check for errors
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to list scripts')
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Extract scripts from folder structure (executable/list returns folders with items)
        folders = result.get('folders', [])
        scripts = []
        for folder in folders:
            for item in folder.get('items', []):
                if item.get('type') == 'script':
                    scripts.append({
                        'name': item['id'],  # e.g., 'gw/dns_lookuptime.py'
                        'folder': folder.get('name', 'Root'),
                        'target_rules': item.get('target_rules'),
                        'tags': item.get('tags', []),
                    })

        if not scripts:
            return {"isError": False, "scripts": []}

        return {
            "isError": False,
            "scripts": scripts,
            "count": len(scripts),
            "hint": "Use target_rules to determine the correct device_id. "
                    "Scripts with target_type='host' need device_id='host'. "
                    "Call get_device_info() or get_compatible_hosts() to find available devices before executing."
        }
    
    def execute_script(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a Python script on a device. Automatically acquires a device lock for the duration of execution.

        ⚠️ MANDATORY PREREQUISITE: You MUST call get_device_info() or get_compatible_hosts() BEFORE this tool
        to discover available host_name and device_id values. Do NOT guess device_id values.

        ⚠️ DEVICE ID: The device_id MUST match an actual device on the host. Use get_device_info(host_name='...')
        to see exactly which device_ids exist. Wrong device_id will be rejected.

        ⚠️ DEVICE LOCKING: This tool acquires an exclusive lock on the device. If the device is already
        locked by another execution, it will return a 'device_locked' error. Use force_unlock=true to preempt.

        Args:
            params: {
                'script_name': str (REQUIRED) - Script filename (e.g., 'my_script.py'),
                'host_name': str (REQUIRED) - Host where device is located (from get_device_info or get_compatible_hosts),
                'device_id': str (OPTIONAL) - Device identifier (defaults to 'host' if not provided),
                'parameters': str (OPTIONAL) - CLI parameters as string (e.g., '--param1 value1 --param2 value2'),
                'force_unlock': bool (OPTIONAL) - If true, preempt any existing lock on the device (default false),
                'environment': str (OPTIONAL) - 'dev'|'test'|'prod', capacity this run counts as (default 'prod')
            }

        Returns:
            MCP-formatted response with script execution results
        """
        script_name = params.get('script_name')
        host_name = params.get('host_name')
        device_id = params.get('device_id')
        parameters = params.get('parameters', '')
        userinterface_name = params.get('userinterface_name', '')
        team_id = params.get('team_id', get_team_id())

        # Validate required parameters
        if not script_name:
            return {"content": [{"type": "text", "text": "script_name is required"}], "isError": True}
        if not host_name:
            return {"content": [{"type": "text", "text": "host_name is required. Call get_device_info() first to discover available hosts."}], "isError": True}
        if not device_id:
            device_id = 'host'
            print(f"[@MCP:execute_script] No device_id provided, defaulting to 'host'")

        # Validate device_id exists on the host before executing
        print(f"[@MCP:execute_script] Validating device_id '{device_id}' exists on host '{host_name}'")
        hosts_result = self.api.get('/server/system/getAllHosts')
        valid_device_ids = []
        host_found = False
        if hosts_result.get('success'):
            for host in hosts_result.get('hosts', []):
                if host.get('host_name') == host_name:
                    host_found = True
                    valid_device_ids = [d.get('device_id') for d in host.get('devices', []) if d.get('device_id')]
                    break

        if not host_found:
            return {"content": [{"type": "text", "text": f"Host '{host_name}' not found. Call get_device_info() to see available hosts."}], "isError": True}

        if device_id not in valid_device_ids:
            return {"content": [{"type": "text", "text": f"device_id '{device_id}' does not exist on host '{host_name}'. Available device_ids on this host: {valid_device_ids}. Call get_device_info(host_name='{host_name}') to see available devices."}], "isError": True}
        
        # Build parameters string (SAME as RunTests.tsx lines 427-470)
        # The frontend always appends --host and --device at the end
        param_parts = []
        
        # Add user-provided parameters first
        if parameters and parameters.strip():
            param_parts.append(parameters.strip())
        
        # Add userinterface_name if provided (SAME as RunTests.tsx line 440-441)
        if userinterface_name:
            param_parts.append(f'--userinterface {userinterface_name}')
        
        # Always add --host and --device at the end (SAME as RunTests.tsx lines 461-467)
        param_parts.append(f'--host {host_name}')
        param_parts.append(f'--device {device_id}')
        
        final_parameters = ' '.join(param_parts)
        
        # Build request - SAME format as frontend (useScript.ts lines 247-255)
        force_unlock = bool(params.get('force_unlock', False))
        environment = params.get('environment')
        data = {
            'script_name': script_name,
            'host_name': host_name,
            'device_id': device_id,
            'parameters': final_parameters,  # Send the complete parameter string
            'force_unlock': force_unlock,
            'trigger': {
                'type': 'mcp',
                'caller_user': f"mcp:{team_id}" if team_id else 'mcp',
            },
        }
        if environment in ('dev', 'test', 'prod'):
            data['environment'] = environment
        
        query_params = {'team_id': team_id}
        
        # Call EXISTING endpoint - SAME as frontend (useScript.ts line 257)
        print(f"[@MCP:execute_script] Calling /server/script/execute for '{script_name}'")
        print(f"[@MCP:execute_script] Parameters: {final_parameters}")
        result = self.api.post('/server/script/execute', data=data, params=query_params)

        # Handle device locked (423) - provide actionable error
        if result.get('errorType') == 'device_locked':
            owner_type = result.get('owner_type', 'unknown')
            owner_reason = result.get('message', 'Device is currently in use')
            error_msg = f"Device '{device_id}' on host '{host_name}' is locked by {owner_type}. {owner_reason}"
            if result.get('can_force_takeover'):
                error_msg += ". You can retry with force_unlock=true to preempt the current execution."
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}

        # Check if async execution (returns task_id) - SAME as frontend (useScript.ts line 265)
        if result.get('task_id'):
            task_id = result['task_id']
            print(f"[@MCP:execute_script] Async execution started with task_id: {task_id}")
            
            # POLL for completion - SAME pattern as frontend (useScript.ts lines 269-279)
            return self._poll_script_completion(task_id, host_name, script_name)
        
        # Check for errors - use exit_code since 'success' is not returned by script executor
        exit_code = result.get('exit_code', 0)
        if exit_code != 0:
            report_url = result.get('report_url')
            logs_url = result.get('logs_url')
            script_success = result.get('script_success')
            error_msg = result.get('stderr') or result.get('error') or f'Script execution failed with exit code {exit_code}'
            
            response_text = f"❌ Script '{script_name}' failed\n"
            response_text += f"Exit code: {exit_code}\n"
            if script_success is not None:
                response_text += f"Test result: {'PASSED' if script_success else 'FAILED'}\n"
            response_text += f"Error: {error_msg}\n"
            if report_url:
                response_text += f"\n📄 Report: [View Report]({report_url})"
            if logs_url:
                response_text += f"\n📋 Logs: [View Logs]({logs_url})"
            
            filtered = self._filter_result_for_mcp(result)
            return {"content": [{"type": "text", "text": response_text}], "isError": True, "result": filtered}

        # Sync result - return directly (useScript.ts lines 283-300)
        print(f"[@MCP:execute_script] Sync execution completed")
        
        # Extract script_success marker (useScript.ts lines 288-293)
        script_success = result.get('script_success')
        if script_success is None and result.get('stdout'):
            if 'SCRIPT_SUCCESS:true' in result['stdout']:
                script_success = True
            elif 'SCRIPT_SUCCESS:false' in result['stdout']:
                script_success = False
        
        # Format response
        response_text = f"✅ Script '{script_name}' completed\n"
        response_text += f"Exit code: {exit_code}\n"
        if script_success is not None:
            response_text += f"Test result: {'PASSED' if script_success else 'FAILED'}\n"
        if result.get('report_url'):
            response_text += f"\n📄 Report: [View Report]({result['report_url']})"
        
        # Return filtered result (no stdout/stderr) to reduce token usage
        return {
            "isError": False,  # exit_code 0 = tool execution successful
            "result": self._filter_result_for_mcp(result)
        }
    
    def _poll_script_completion(self, task_id: str, host_name: str, script_name: str, max_wait: int = 7200) -> Dict[str, Any]:
        """
        Poll script execution until complete
        
        REUSES existing /server/script/status/<task_id> endpoint (same as frontend)
        Pattern from useScript.ts lines 161-220
        """
        poll_interval = 10  # 10 seconds - less frequent for long scripts (useScript.ts line 166)
        elapsed = 0
        
        print(f"[@MCP:poll_script] Polling for task {task_id} (max {max_wait}s)")
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            # Poll status endpoint - SAME as frontend (useScript.ts line 174)
            status = self.api.get(f'/server/script/status/{task_id}')
            
            # Check if we got a valid response (useScript.ts line 177)
            if status.get('success') and status.get('task'):
                task = status['task']
                current_status = task.get('status')
                
                if current_status == 'completed':
                    print(f"[@MCP:poll_script] Script completed after {elapsed}s")
                    task_result = task.get('result', {})
                    
                    # Extract results - SAME as frontend (useScript.ts lines 181-189)
                    # Determine success: exit_code 0 = process ran successfully
                    # Note: script_success indicates test pass/fail, NOT tool execution success
                    exit_code = task_result.get('exit_code', 0)
                    script_success = task_result.get('script_success')
                    report_url = task_result.get('report_url', '')
                    logs_url = task_result.get('logs_url', '')
                    execution_time_ms = task_result.get('execution_time_ms', elapsed * 1000)
                    device_id = task_result.get('device_id', '')
                    

                    
                    # Tool execution is successful if process exited cleanly (exit_code 0)
                    is_tool_error = exit_code != 0
                    
                    response_text = f"✅ Script '{script_name}' completed\n"
                    response_text += f"Exit code: {exit_code}\n"
                    if script_success is not None:
                        response_text += f"Test result: {'PASSED' if script_success else 'FAILED'}\n"
                    if report_url:
                        response_text += f"\n📄 Report: [View Report]({report_url})"
                    if logs_url:
                        response_text += f"\n📋 Logs: [View Logs]({logs_url})"
                    
                    # Return filtered result (no stdout/stderr) to reduce token usage
                    return {
                        "isError": is_tool_error,
                        "result": self._filter_result_for_mcp(task_result)
                    }
                
                elif current_status == 'failed':
                    print(f"[@MCP:poll_script] Script failed after {elapsed}s")
                    task_result = task.get('result', {})
                    exit_code = task_result.get('exit_code', 1)
                    script_success = task_result.get('script_success')
                    report_url = task_result.get('report_url', '')
                    logs_url = task_result.get('logs_url', '')
                    error = task.get('error', 'Script execution failed')
                    
                    response_text = f"❌ Script '{script_name}' failed after {elapsed}s\n"
                    response_text += f"Exit code: {exit_code}\n"
                    if script_success is not None:
                        response_text += f"Test result: {'PASSED' if script_success else 'FAILED'}\n"
                    response_text += f"Error: {error}\n"
                    if report_url:
                        response_text += f"\n📄 Report: [View Report]({report_url})"
                    if logs_url:
                        response_text += f"\n📋 Logs: [View Logs]({logs_url})"
                    
                    filtered = self._filter_result_for_mcp(task_result)
                    return {"content": [{"type": "text", "text": response_text}], "isError": True, "result": filtered}

                elif current_status in ['pending', 'running']:
                    print(f"[@MCP:poll_script] Status: {current_status} - {elapsed}s elapsed")
        
        print(f"[@MCP:poll_script] Script execution timed out after {max_wait}s")
        return {"content": [{"type": "text", "text": f"Script execution timed out after {max_wait}s"}], "isError": True}

