from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from ..utils.execution_status_constants import DONE_STATES, STATE_RUNNING
from ..utils.execution_status_formatter import (
    build_status, started_response, status_response, transient_read_response, unknown_execution_response,
)
from ..utils.execution_status_mappers import KIND_SCRIPT, map_script_status
from ..utils.execution_status_reader import clamp_wait_seconds, is_transient_read_failure, read_until_done
from shared.src.lib.config.constants import APP_CONFIG, get_team_id
from shared.src.lib.executors.cli_arg_utils import normalize_argv



# Flags every script accepts through the framework, on top of its own `_script_args`.
FRAMEWORK_FLAGS = {'--host', '--device', '--userinterface', '--variant', '--ui-mode', '--ui_mode', '--local-debug', '--local_debug'}


def find_unknown_flags(parameters: str, script_flags):
    """Flags in a CLI parameter string that neither the script nor the framework defines."""
    known = FRAMEWORK_FLAGS | {('--' + f.lstrip('-')) for f in script_flags}
    return [tok.split('=', 1)[0] for tok in parameters.split()
            if tok.startswith('--') and tok.split('=', 1)[0] not in known]


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
                    entry = {
                        'name': item['id'],  # e.g., 'gw/dns_lookuptime.py'
                        'folder': folder.get('name', 'Root'),
                        'target_rules': item.get('target_rules'),
                        'tags': item.get('tags', []),
                    }
                    # Virtual (DB-stored) script: execute_script needs this id.
                    if item.get('is_virtual'):
                        entry['virtual_script_id'] = item.get('virtual_script_id')
                    scripts.append(entry)

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
        Start a Python script on a device and return its execution_id at once. Automatically acquires a device lock for the duration of execution.

        The script goes on on the host. This tool does NOT wait for the result: call
        get_script_execution_status(execution_id) until `done` is true.

        ⚠️ MANDATORY PREREQUISITE: You MUST call get_device_info() or get_compatible_hosts() BEFORE this tool
        to discover available host_name and device_id values. Do NOT guess device_id values.

        ⚠️ DEVICE ID: The device_id MUST match an actual device on the host. Use get_device_info(host_name='...')
        to see exactly which device_ids exist. Wrong device_id will be rejected.

        ⚠️ DEVICE LOCKING: This tool acquires an exclusive lock on the device. If the device is already
        locked by another execution, it will return a 'device_locked' error. Use force_unlock=true to preempt.

        Args:
            params: {
                'script_name': str (REQUIRED) - Script filename (e.g., 'my_script.py'), or the virtual script name,
                'virtual_script_id': str (OPTIONAL) - Required for a virtual (DB-stored) script: the id from list_scripts or save_virtual_script,
                'host_name': str (REQUIRED) - Host where device is located (from get_device_info or get_compatible_hosts),
                'device_id': str (OPTIONAL) - Device identifier (defaults to 'host' if not provided),
                'parameters': str (OPTIONAL) - CLI parameters as string (e.g., '--param1 value1 --param2 value2'),
                'force_unlock': bool (OPTIONAL) - If true, preempt any existing lock on the device (default false),
                'environment': str (OPTIONAL) - 'dev'|'test'|'prod', capacity this run counts as (default 'prod')
            }

        Returns:
            MCP response with structuredContent {execution_id, host_name, device_id, status: 'running', done: false}
        """
        script_name = params.get('script_name')
        virtual_script_id = params.get('virtual_script_id')
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
        
        # Normalise aliased flags and reject unknown ones BEFORE dispatch, so the
        # model gets the valid list back in the same turn instead of a failed run.
        if parameters and parameters.strip():
            tokens, alias_warnings = normalize_argv(parameters.split())
            for warning in alias_warnings:
                print(f"[@MCP:execute_script] {warning}")
            parameters = ' '.join(tokens)
            analyze_data = {'script_name': script_name}
            if virtual_script_id:
                analyze_data['virtual_script_id'] = virtual_script_id
            analysis = self.api.post('/server/script/analyze', data=analyze_data, params={'team_id': team_id})
            if isinstance(analysis, dict) and analysis.get('success') and isinstance(analysis.get('parameters'), list):
                script_flags = [p.get('name', '') for p in analysis['parameters'] if p.get('name')]
                unknown = find_unknown_flags(parameters, script_flags)
                if unknown:
                    valid = sorted(FRAMEWORK_FLAGS | {'--' + f for f in script_flags})
                    return {"content": [{"type": "text", "text": f"Unknown flag(s) {unknown} for {script_name}. Valid flags: {valid}. Fix the parameters string and call execute_script again."}], "isError": True}

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
        if virtual_script_id:
            data['virtual_script_id'] = virtual_script_id
        
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
            
            structured = build_status(task_id, KIND_SCRIPT, STATE_RUNNING,
                                      host_name=host_name, device_id=device_id, script_name=script_name)
            return started_response(structured, script_name, 'get_script_execution_status')
        
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
    
    def get_script_execution_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read the state of a script started by execute_script

        Waits up to wait_seconds (default 20, max 50) for the script to end, then answers with its
        current state. Call again while `done` is false. A script whose test FAILED is
        `status: completed, passed: false` (not a tool error); isError is only set when the
        execution_id is unknown.

        REUSES existing /server/script/status/<task_id> endpoint (same as frontend)

        Args:
            params: {
                'execution_id': str (REQUIRED) - execution_id returned by execute_script,
                'wait_seconds': int (OPTIONAL) - Seconds to wait for the script to end before answering: default 20, max 50, 0 answers at once
            }

        Returns:
            MCP response with structuredContent {execution_id, status: running|completed|failed|aborted|unknown, done, passed, exit_code, script_success, report_url, logs_url, execution_time_ms, error}
        """
        task_id = params.get('execution_id')
        if not task_id:
            return {"content": [{"type": "text", "text": "Error: execution_id is required"}], "isError": True}

        response = read_until_done(
            lambda: self.api.get(f'/server/script/status/{task_id}'),
            lambda r: map_script_status(task_id, r)['status'] in DONE_STATES,
            clamp_wait_seconds(params.get('wait_seconds')),
        )

        if not response.get('success'):
            error = response.get('error', 'Unknown error')
            if is_transient_read_failure(response):
                return transient_read_response(task_id, KIND_SCRIPT, error)
            return unknown_execution_response(task_id, KIND_SCRIPT, error)

        return status_response(map_script_status(task_id, response))
