"""
API Power Controller Implementation

Drives a device's power via a custom client REST API instead of a local smart
plug. Same public interface as TapoPowerController, so the existing power button /
power routes use it unchanged — only the backend transport differs.

API (X-API-KEY header auth):

    Base:    https://<power-api-host>/api/v1/devices/{device_name}/{operation}
    Headers: Content-Type: application/json   Accept: application/json   X-API-KEY: <key>

    GET  /{device_name}/status   → { "success": true, "powerState": "ON", "state": 1, ... }
    POST /{device_name}/actions  body { "action": "POWER_ON" | "POWER_OFF" | "REBOOT" }
                                 → { "success": true, "action": "POWER_ON", "message": "..." }
"""

from typing import Dict, Any
import requests
from ..base_controller import PowerControllerInterface


class APIPowerController(PowerControllerInterface):
    """Power controller that drives a client REST API."""

    REQUEST_TIMEOUT = 15  # seconds

    def __init__(self, api_url: str, device_name: str, api_key: str, **kwargs):
        """
        Initialize the API power controller.

        Args:
            api_url: Base URL up to /devices (e.g. 'https://<power-api-host>/api/v1/devices')
            device_name: Device name in the API path (e.g. 'stb01')
            api_key: Value for the X-API-KEY header
        """
        super().__init__("API Power")

        self.power_type = "api_power"
        self.api_url = api_url.rstrip('/') if api_url else api_url
        self.api_device_name = device_name
        self.api_key = api_key
        self.current_power_state = "unknown"

        # Validate required parameters
        if not self.api_url:
            raise ValueError("api_url is required for APIPowerController")
        if not self.api_device_name:
            raise ValueError("device_name is required for APIPowerController")
        if not self.api_key:
            raise ValueError("api_key is required for APIPowerController")

        print(f"[@controller:APIPower] Initialized for device '{self.api_device_name}' "
              f"via {self.api_url}")

    def _headers(self) -> Dict[str, str]:
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-API-KEY': self.api_key,
        }

    def connect(self) -> bool:
        """No persistent connection — REST is stateless."""
        self.is_connected = True
        print(f"Power[{self.power_type.upper()}]: API power ready for {self.api_device_name}")
        return True

    def disconnect(self) -> bool:
        self.is_connected = False
        print(f"Power[{self.power_type.upper()}]: API power disconnected for {self.api_device_name}")
        return True

    def _post_action(self, action: str) -> bool:
        """POST an action to the device's /actions endpoint."""
        url = f"{self.api_url}/{self.api_device_name}/actions"
        try:
            print(f"Power[{self.power_type.upper()}]: POST {url} action={action}")
            resp = requests.post(
                url,
                json={'action': action},
                headers=self._headers(),
                timeout=self.REQUEST_TIMEOUT,
            )
            ok = resp.ok and bool(resp.json().get('success'))
            if not ok:
                print(f"Power[{self.power_type.upper()}]: Action {action} failed "
                      f"(HTTP {resp.status_code}): {resp.text[:200]}")
            return ok
        except Exception as e:
            print(f"Power[{self.power_type.upper()}]: Action {action} error: {e}")
            return False

    def power_on(self, timeout: float = 10.0) -> bool:
        """Turn the device on via the API."""
        success = self._post_action('POWER_ON')
        if success:
            self.current_power_state = "on"
            print(f"Power[{self.power_type.upper()}]: Powered on {self.api_device_name}")
        return success

    def power_off(self, force: bool = False, timeout: float = 5.0) -> bool:
        """Turn the device off via the API."""
        success = self._post_action('POWER_OFF')
        if success:
            self.current_power_state = "off"
            print(f"Power[{self.power_type.upper()}]: Powered off {self.api_device_name}")
        return success

    def reboot(self, timeout: float = 40.0) -> bool:
        """Reboot the device via the API's native REBOOT action."""
        success = self._post_action('REBOOT')
        if success:
            print(f"Power[{self.power_type.upper()}]: Rebooted {self.api_device_name}")
        return success

    def get_power_status(self) -> Dict[str, Any]:
        """Get current power status via the API."""
        url = f"{self.api_url}/{self.api_device_name}/status"
        try:
            print(f"Power[{self.power_type.upper()}]: GET {url}")
            resp = requests.get(url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            raw_state = str(data.get('powerState', '')).upper()
            power_state = 'on' if raw_state == 'ON' else 'off' if raw_state == 'OFF' else 'unknown'
            self.current_power_state = power_state

            print(f"Power[{self.power_type.upper()}]: Status for {self.api_device_name}: {power_state}")
            return {
                'power_state': power_state,
                'device_name': self.api_device_name,
                'connected': True,
                'device_info': data,
            }

        except Exception as e:
            print(f"Power[{self.power_type.upper()}]: Status check error: {e}")
            return {
                'power_state': 'unknown',
                'connected': self.is_connected,
                'error': f'Status check error: {e}',
            }

    def isPowerOn(self) -> bool:
        """Check if device is powered on."""
        return self.get_power_status().get('power_state') == 'on'

    def isPowerOff(self) -> bool:
        """Check if device is powered off."""
        return self.get_power_status().get('power_state') == 'off'

    def get_available_actions(self) -> Dict[str, Any]:
        """Get available actions for this API power controller."""
        return {
            'power': [
                {
                    'id': 'power_on',
                    'label': 'Power On',
                    'command': 'power_on',
                    'action_type': 'power',
                    'params': {},
                    'description': 'Turn the device on via the power API',
                    'requiresInput': False
                },
                {
                    'id': 'power_off',
                    'label': 'Power Off',
                    'command': 'power_off',
                    'action_type': 'power',
                    'params': {},
                    'description': 'Turn the device off via the power API',
                    'requiresInput': False
                },
                {
                    'id': 'reboot',
                    'label': 'Reboot',
                    'command': 'reboot',
                    'action_type': 'power',
                    'params': {},
                    'description': 'Reboot the device via the power API',
                    'requiresInput': False
                }
            ]
        }

    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute API power command.

        Args:
            command: Command to execute ('power_on', 'power_off', 'reboot')
            params: Command parameters (unused)

        Returns:
            Dict[str, Any]: Dict with 'success' key indicating command execution status
        """
        if params is None:
            params = {}

        print(f"Power[{self.power_type.upper()}]: Executing command '{command}' with params: {params}")

        if command == 'power_on':
            success = self.power_on()
        elif command == 'power_off':
            success = self.power_off()
        elif command == 'reboot':
            success = self.reboot()
        else:
            print(f"Power[{self.power_type.upper()}]: Unknown command: {command}")
            success = False

        return {'success': success}

    def get_status(self) -> Dict[str, Any]:
        """Get controller status information."""
        return {
            'controller_type': self.controller_type,
            'power_type': self.power_type,
            'device_name': self.device_name,
            'api_device_name': self.api_device_name,
            'api_url': self.api_url,
            'connected': self.is_connected,
            'current_power_state': self.current_power_state,
            'capabilities': [
                'api_power_control', 'power_on', 'power_off', 'reboot', 'get_power_status'
            ]
        }
