"""
Device Tools - Device information and status

Get device information, capabilities, and execution status.
"""

from typing import Dict, Any
import json
import requests
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import APP_CONFIG, get_team_id
from backend_server.src.lib.utils.lock_utils import get_device_lock_info


class DeviceTools:
    """Device information and status tools"""

    HOST_REACHABILITY_TIMEOUT = 2  # seconds

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()

    @staticmethod
    def _check_host_reachable(host_api_url: str) -> bool:
        """Quick connectivity check — returns True if host responds within timeout."""
        try:
            url = f"{host_api_url.rstrip('/')}/host/system/health"
            resp = requests.get(url, timeout=DeviceTools.HOST_REACHABILITY_TIMEOUT)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout, requests.RequestException):
            return False
    
    def list_hosts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all registered hosts
        
        Returns list of all hosts with their device counts and status.
        Use this to discover available hosts before calling other tools.
        
        Args:
            params: {} (no parameters required)
            
        Returns:
            MCP-formatted response with host list
        """
        result = self.api.get('/server/system/getAllHosts')
        
        if not result.get('success'):
            return self.formatter.format_api_response(result)
        
        hosts = result.get('hosts', [])

        # Build summary - include version and services info
        host_list = []
        for host in hosts:
            status = host.get('status')
            host_url = host.get('host_url', '')
            host_port = host.get('host_port', 6109)

            # Verify connectivity for hosts reported as "online"
            host_api_url = host.get('host_api_url', '')
            if status == 'online' and host_api_url:
                if not self._check_host_reachable(host_api_url):
                    status = 'unreachable'

            host_summary = {
                'host_name': host.get('host_name'),
                'device_count': len(host.get('devices', [])),
                'deployed_version': host.get('deployed_version'),
                'status': status
            }
            host_list.append(host_summary)

        # Format response
        if not host_list:
            return {"content": [{"type": "text", "text": "📋 No hosts registered\n\n💡 Start a host with: ./scripts/launch_virtualhost.sh"}], "isError": False}

        response_text = f"📋 Registered Hosts ({len(host_list)} total):\n\n"
        for host in host_list:
            host_status = host.get('status', 'unknown')
            if host_status == 'online':
                status_emoji = "✅"
            elif host_status == 'unreachable':
                status_emoji = "⚠️"
            else:
                status_emoji = "❌"
            version = host.get('deployed_version', 'unknown')
            response_text += f"{status_emoji} {host['host_name']}\n"
            response_text += f"   Version: {version}\n"
            response_text += f"   Status: {host_status}\n"
            response_text += f"   Devices: {host['device_count']}\n\n"
        
        response_text += "💡 Use get_device_info(host_name='...') for device details"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def get_device_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get device information and capabilities
        
        Returns device list with capabilities, controllers, and status.
        
        Args:
            params: {
                'device_id': str (OPTIONAL) - Specific device, or omit for all devices,
                'host_name': str (OPTIONAL) - Filter by host
            }
            
        Returns:
            MCP-formatted response with device information
        """
        device_id = params.get('device_id')
        host_name = params.get('host_name')
        
        # Use getAllHosts as source of truth (matches frontend behavior)
        result = self.api.get('/server/system/getAllHosts')
        
        if not result.get('success'):
            return self.formatter.format_api_response(result)
            
        hosts = result.get('hosts', [])
        
        # Filter by host_name if provided
        if host_name:
            hosts = [h for h in hosts if h.get('host_name') == host_name]
            if not hosts:
                return {"content": [{"type": "text", "text": f"❌ Error: Host '{host_name}' not found"}], "isError": True}
        
        # Collect all devices
        all_devices = []
        for host in hosts:
            host_info = {
                'host_name': host.get('host_name'),
                'status': host.get('status')
            }
            
            for device in host.get('devices', []):
                # Filter by device_id if provided
                if device_id and device.get('device_id') != device_id:
                    continue
                
                # Expose more fields including version, capabilities, lock status
                current_host = host_info.get('host_name', '')
                current_device_id = device.get('device_id', '')
                lock_info = get_device_lock_info(current_host, current_device_id)

                device_clean = {
                    'device_id': current_device_id,
                    'device_name': device.get('device_name'),
                    'device_model': device.get('device_model'),
                    'device_capabilities': device.get('device_capabilities'),
                    'host_name': current_host,
                    'host_version': host_info.get('deployed_version'),
                    'status': host_info.get('status'),
                    'has_running_deployment': device.get('has_running_deployment', False),
                    'is_locked': lock_info is not None,
                    'locked_by': lock_info.get('owner_type') if lock_info else None,
                    'lock_reason': lock_info.get('lock_reason') if lock_info else None,
                    'lock_owner_name': lock_info.get('owner_user_name') if lock_info else None,
                    # Script running under a manual_control lock (subordinate run)
                    'active_script_reason': lock_info.get('active_script_reason') if lock_info else None,
                }
                all_devices.append(device_clean)
        
        if device_id and not all_devices:
             return {"content": [{"type": "text", "text": f"❌ Error: Device '{device_id}' not found"}], "isError": True}
             
        return self.formatter.format_success({"devices": all_devices})
    
    def get_compatible_hosts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get hosts and devices compatible with a userinterface
        
        ⚠️ CRITICAL: Use this tool BEFORE execute_device_action, navigate_to_node, 
        execute_testcase, or generate_test_graph to find compatible hosts/devices.
        
        This tool automatically filters hosts based on the userinterface's device models
        and returns the first compatible host/device for immediate use.
        
        Args:
            params: {
                'userinterface_name': str (REQUIRED) - Interface name (e.g., 'sauce-demo')
            }
            
        Returns:
            MCP-formatted response with:
            - compatible_hosts: List of hosts with compatible devices
            - recommended: Auto-selected first host and device
            - models: Device models required by the interface
            
        Example:
            get_compatible_hosts(userinterface_name='sauce-demo')
            # Returns: recommended_host='your-mac', recommended_device='device1'
        """
        userinterface_name = params.get('userinterface_name')
        
        if not userinterface_name:
            return {"content": [{"type": "text", "text": "❌ Error: userinterface_name is required"}], "isError": True}
        
        # Get userinterface by name to extract models
        ui_result = self.api.get(f'/server/userinterface/getUserInterfaceByName/{userinterface_name}', params={'team_id': get_team_id()})
        
        # Check if userinterface exists
        if not ui_result or 'error' in ui_result:
            return {"content": [{"type": "text", "text": f"❌ Error: Userinterface '{userinterface_name}' not found"}], "isError": True}
        
        models = ui_result.get('models', [])
        tree_id = ui_result.get('root_tree_id')
        
        if not models:
            return {"content": [{"type": "text", "text": f"❌ Error: Userinterface '{userinterface_name}' has no device models defined"}], "isError": True}
        
        # Get all hosts
        hosts_result = self.api.get('/server/system/getAllHosts')
        
        if not hosts_result.get('success'):
            return {"content": [{"type": "text", "text": "❌ Error: Failed to get hosts"}], "isError": True}
        
        all_hosts = hosts_result.get('hosts', [])
        
        # Filter hosts to only those with compatible devices
        compatible_hosts = []
        for host in all_hosts:
            compatible_devices = []
            for device in host.get('devices', []):
                device_model = device.get('device_model')
                device_capabilities = device.get('device_capabilities', {})
                
                # Check exact model match
                if device_model in models:
                    compatible_devices.append(device)
                # Check capability match (e.g., device with 'web' capability matches 'web' model)
                elif any(device_capabilities.get(model) for model in models):
                    compatible_devices.append(device)
            
            if compatible_devices:
                compatible_hosts.append({
                    'host_name': host.get('host_name'),
                    'host_url': host.get('host_url'),
                    'status': host.get('status', 'online'),
                    'devices': compatible_devices
                })
        
        # Check if any compatible hosts found
        if not compatible_hosts:
            return {"content": [{
                "type": "text",
                "text": f"❌ No compatible hosts found for userinterface '{userinterface_name}'\n\n"
                        f"Required device models: {', '.join(models)}\n\n"
                        f"💡 Make sure at least one host is running with a compatible device:\n"
                        f"   1. Start backend_host: ./scripts/launch_virtualhost.sh\n"
                        f"   2. Verify with: get_device_info()\n"
                        f"   3. Check host has device matching one of: {models}"
            }], "isError": True}
        
        # Auto-select first compatible host and device
        first_host = compatible_hosts[0]
        first_device = first_host['devices'][0]
        
        # Build response
        response_text = f"✅ Found {len(compatible_hosts)} compatible host(s) for '{userinterface_name}'\n\n"
        response_text += f"🎯 RECOMMENDED (Auto-selected):\n"
        response_text += f"   Host: {first_host['host_name']}\n"
        response_text += f"   Device: {first_device.get('device_name', 'Unknown')} ({first_device.get('device_model')})\n"
        response_text += f"   Device ID: {first_device.get('device_id')}\n"
        if tree_id:
            response_text += f"   Tree ID: {tree_id}\n"
        response_text += f"\n📋 Use these values in your next operation:\n"
        response_text += f"   host_name='{first_host['host_name']}'\n"
        response_text += f"   device_id='{first_device.get('device_id')}'\n"
        if tree_id:
            response_text += f"   tree_id='{tree_id}'\n"
        response_text += f"\n"
        
        if len(compatible_hosts) > 1:
            response_text += f"📌 Other compatible hosts:\n"
            for host in compatible_hosts[1:]:
                response_text += f"   • {host['host_name']} ({len(host['devices'])} device(s))\n"
        
        response_text += f"\n💡 Interface requires models: {', '.join(models)}"

        # Structured payload for downstream context extraction
        payload = {
            "userinterface_name": userinterface_name,
            "tree_id": tree_id,
            "recommended": {
                "host_name": first_host.get("host_name"),
                "device_id": first_device.get("device_id"),
                "device_name": first_device.get("device_name"),
                "device_model": first_device.get("device_model"),
            },
            "compatible_hosts": [
                {
                    "host_name": h.get("host_name"),
                    "devices": [
                        {
                            "device_id": d.get("device_id"),
                            "device_name": d.get("device_name"),
                            "device_model": d.get("device_model"),
                        }
                        for d in h.get("devices", [])
                    ],
                }
                for h in compatible_hosts
            ],
        }
        
        return {
            "content": [
                {"type": "text", "text": response_text},
                {"type": "text", "text": json.dumps(payload)},
            ],
            "isError": False,
        }
    
    def get_execution_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Poll execution status for async operations
        
        Check status of actions, testcases, or other async operations.
        
        Args:
            params: {
                'execution_id': str (REQUIRED) - Execution ID from async operation,
                'operation_type': str (OPTIONAL) - 'action', 'testcase', 'ai' for specific endpoints
            }
            
        Returns:
            MCP-formatted response with execution status and results
        """
        execution_id = params.get('execution_id')
        operation_type = params.get('operation_type', 'action')
        
        # Validate required parameters
        if not execution_id:
            return {"content": [{"type": "text", "text": "Error: execution_id is required"}], "isError": True}
        
        # Call appropriate endpoint based on operation type
        if operation_type == 'action':
            endpoint = f'/host/action/getStatus/{execution_id}'
        elif operation_type == 'testcase':
            endpoint = f'/host/testcase/getStatus/{execution_id}'
        elif operation_type == 'ai':
            endpoint = f'/host/ai/getExecutionStatus/{execution_id}'
        else:
            return format_tool_result({'success': False, 'error': f'Unknown operation_type: {operation_type}'})
        
        # Call API
        result = self.api.get(endpoint)
        
        return self.formatter.format_api_response(result)

