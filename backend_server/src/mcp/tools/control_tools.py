"""
Control Tools - Device control and session management

Provides take_control and release_control for device locking and cache generation.
"""

from typing import Dict, Any
import uuid
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from ..utils.lock_ownership import (
    EXECUTION_OWNER_TYPES, anonymous_session, forget_anonymous_session, holder, remember_anonymous_session,
)
from shared.src.lib.config.constants import get_team_id


class ControlTools:
    """Device control and session management tools"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()

    def _get_or_create_session_id(
        self,
        *,
        host_name: str,
        device_id: str,
        explicit_session_id: str = None,
    ) -> str:
        if explicit_session_id:
            return explicit_session_id
        # Only reuse a session no caller named: a chat's session is never handed to another caller.
        return anonymous_session(host_name, device_id) or f"mcp-{uuid.uuid4()}"

    @staticmethod
    def _extract_owner_type(result: Dict[str, Any]) -> str:
        if result.get('owner_type'):
            return result.get('owner_type')
        lock_info = result.get('lock_info') or {}
        return lock_info.get('owner_type')
    
    def take_control(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Take exclusive control of a device. Locks device for exclusive use.

        ⚠️ WHEN TO USE: Required before interactive device operations (execute_device_action, navigate_to_node,
        capture_screenshot, verify_element_visible). NOT required for execute_script or execute_testcase —
        those tools acquire and release their own locks automatically.

        Example: take_control(host_name='host1', device_id='device1')
        
        Args:
            params: {
                'host_name': str (REQUIRED - host where device is connected),
                'device_id': str (REQUIRED - device identifier)
            }
            
        Returns:
            MCP-formatted response with session_id
        """
        host_name = params.get('host_name')
        device_id = params.get('device_id')
        team_id = params.get('team_id', get_team_id())
        userinterface_name = params.get('userinterface_name')
        # Never steal by default: a device another session holds is reported, not taken.
        # Takeover (which stops a running script) only on an explicit allow_takeover=True (BUG-0402).
        allow_takeover = bool(params.get('allow_takeover', False))
        if not host_name or not device_id:
            return self.formatter.format_api_response({
                'success': False,
                'error': 'host_name and device_id are required',
            })

        session_id = self._get_or_create_session_id(
            host_name=host_name,
            device_id=device_id,
            explicit_session_id=params.get('session_id'),
        )
        
        # Build request - include userinterface_name for cache population
        data = {
            'host_name': host_name,
            'device_id': device_id,
            'userinterface_name': userinterface_name,
            'session_id': session_id,
        }
        
        # STEP 1: Try normal take_control
        result = self.api.post('/server/control/takeControl', data=data, params={'team_id': team_id})
        
        # STEP 2: If device is locked by execution, optionally take over via explicit takeover API.
        if not result.get('success') and result.get('errorType') == 'device_locked' and allow_takeover:
            owner_type = self._extract_owner_type(result)
            if owner_type in EXECUTION_OWNER_TYPES:
                print(
                    f"[@mcp:take_control] Device {host_name}:{device_id} locked by {owner_type}, "
                    "attempting takeover..."
                )
                takeover_payload = {
                    'host_name': host_name,
                    'device_id': device_id,
                    'requested_by_session': session_id,
                    'stop_running_execution': True,
                    'reason': 'mcp_takeover',
                    'userinterface_name': userinterface_name,
                }
                result = self.api.post(
                    '/server/control/takeover',
                    data=takeover_payload,
                    params={'team_id': team_id},
                )

        if result.get('success'):
            if not params.get('session_id'):
                # An MCP client that gave no session: its device tools run under this lock.
                remember_anonymous_session(host_name, device_id, session_id)
            if not result.get('session_id'):
                result['session_id'] = session_id
        elif result.get('errorType') == 'device_locked':
            # Name the holder, as the device tools do (auto_lock); the formatter keeps only 'error'.
            owner_type = self._extract_owner_type(result) or 'unknown'
            text = (f"Device '{device_id}' on host '{host_name}' is in use by {holder(result)} ({owner_type}). "
                    "Not taking it over - wait until they release it or ask them to.")
            if owner_type in EXECUTION_OWNER_TYPES and not allow_takeover:
                text += " To stop their running execution, retry with allow_takeover=true."
            return {"content": [{"type": "text", "text": text}], "isError": True, "errorType": 'device_locked'}

        return self.formatter.format_api_response(result)
    
    def release_control(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Release device control when done. Unlocks the device so others can use it.
        
        Example: release_control(host_name='host1', device_id='device1')
        
        Args:
            params: {
                'host_name': str (REQUIRED - host where device is connected),
                'device_id': str (REQUIRED - device identifier)
            }
            
        Returns:
            MCP-formatted response
        """
        host_name = params.get('host_name')
        device_id = params.get('device_id')
        team_id = params.get('team_id', get_team_id())
        if not host_name or not device_id:
            return self.formatter.format_api_response({
                'success': False,
                'error': 'host_name and device_id are required',
            })

        session_id = params.get('session_id') or anonymous_session(host_name, device_id)
        if not session_id:
            return self.formatter.format_api_response({
                'success': False,
                'error': (
                    'No active control session found for this device. '
                    'Pass session_id explicitly or call take_control first.'
                ),
            })

        # Build request
        data = {
            'host_name': host_name,
            'device_id': device_id,
            'session_id': session_id,
        }
        
        # Call API and format response
        result = self.api.post('/server/control/releaseControl', data=data, params={'team_id': team_id})
        if result.get('success'):
            if session_id == anonymous_session(host_name, device_id):
                forget_anonymous_session(host_name, device_id)
        return self.formatter.format_api_response(result)
