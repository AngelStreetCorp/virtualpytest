"""
IRTrans Remote Controller Implementation

Drives an STB through a **networked IRTrans box** instead of a local lirc / ir-ctl
transmitter. The IRTrans box accepts UDP commands of the form

    snd <remote>,<command>[,l<led>]\\r

on a fixed IP:port (default 21000). A single box is shared across STBs — each STB is
wired to a different IR-output LED (1-16), which acts as its per-STB "port".

From the frontend's point of view this is identical to the lirc IR remote: the device
keeps `ir_type=stb` so the STB panel renders, and the frontend sends
`remote_type:'ir_remote'` + `press_key`. The only difference is the transport here.

Because the IRTrans command names do not match the STB key names
(B1, OK_BUTTON, UP_ARROW, NEXT_CHANNEL, PAUSE_PLAY, ...), a key→command map is loaded
from `irtrans_conf/<ir_type>.json` (mirrors how lirc loads `ir_conf/<ir_type>.json`).

See docs/agent/devices/INFRARED.md § IRTrans (networked) transport.
"""

from typing import Dict, Any, Optional
import socket
import time
import json
import os
from ..base_controller import RemoteControllerInterface


class IRTransRemoteController(RemoteControllerInterface):
    """IR remote controller that sends UDP commands to a networked IRTrans box."""

    def __init__(self, ir_ip: str = None, ir_remote: str = None, ir_type: str = None,
                 ir_port: int = 21000, ir_led: Optional[int] = None, **kwargs):
        """
        Initialize the IRTrans remote controller.

        Args:
            ir_ip: IP address of the IRTrans box (e.g. '192.168.1.60')
            ir_remote: Remote name registered in the IRTrans box (e.g. 'STB_remote')
            ir_type: Keymap profile name → irtrans_conf/<ir_type>.json (e.g. 'stb')
            ir_port: UDP/TCP port of the IRTrans box (default 21000)
            ir_led: IR-output LED/port 1-16 (this STB's "port"); None sends on all LEDs
        """
        super().__init__("IRTrans Remote", "infrared")

        self.ir_ip = ir_ip
        self.ir_remote = ir_remote
        self.ir_type = ir_type
        self.ir_port = int(ir_port) if ir_port else 21000
        self.ir_led = int(ir_led) if ir_led not in (None, '') else None

        # Validate required parameters
        if not self.ir_ip:
            raise ValueError("ir_ip is required for IRTransRemoteController")
        if not self.ir_remote:
            raise ValueError("ir_remote is required for IRTransRemoteController")
        if not self.ir_type:
            raise ValueError("ir_type is required for IRTransRemoteController")
        if self.ir_led is not None and not 1 <= self.ir_led <= 16:
            raise ValueError("ir_led must be between 1 and 16")

        # Keymap (STB key → IRTrans command) paths
        self.ir_config_path = os.path.join(os.path.dirname(__file__), 'irtrans_conf')
        self.ir_config_file = f"{self.ir_type}.json"

        self.keymap: Dict[str, str] = {}
        self.ir_available_keys = []

        # Health tracking (drives the Take Control status dot, mirrors infrared.py)
        self._last_send_ok: Optional[bool] = None
        self._last_send_error: Optional[str] = None
        self._last_send_ts: float = 0
        self._health_cache: Optional[Dict[str, Any]] = None
        self._health_cache_ts: float = 0

        led_str = f", led {self.ir_led}" if self.ir_led else ""
        print(f"[@controller:IRTransRemote] Initialized for {self.ir_ip}:{self.ir_port} "
              f"remote '{self.ir_remote}'{led_str} (type: {self.ir_type})")

        self.connect()

    def connect(self) -> bool:
        """Load the keymap. Like lirc, this does not test transmission."""
        try:
            ir_config_full_path = os.path.join(self.ir_config_path, self.ir_config_file)
            if not os.path.exists(ir_config_full_path):
                print(f"Remote[{self.device_type.upper()}]: IRTrans keymap not found: {ir_config_full_path}")
                return False

            with open(ir_config_full_path, 'r') as f:
                self.keymap = json.load(f)

            self.ir_available_keys = list(self.keymap.keys())
            self.is_connected = True
            print(f"Remote[{self.device_type.upper()}]: Loaded {len(self.ir_available_keys)} keys "
                  f"from {self.ir_config_file}; connected to {self.device_name}")
            return True

        except json.JSONDecodeError as e:
            print(f"Remote[{self.device_type.upper()}]: Invalid JSON in {self.ir_config_file}: {e}")
            return False
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Connection failed: {e}")
            return False

    def disconnect(self) -> bool:
        """Disconnect (no persistent socket — UDP is connectionless)."""
        self.ir_available_keys = []
        self.is_connected = False
        print(f"Remote[{self.device_type.upper()}]: Disconnected from {self.device_name}")
        return True

    def press_key(self, key: str) -> bool:
        """Send a single IR key press as a UDP `snd` command to the IRTrans box."""
        if not self.is_connected:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected")
            return False

        key_upper = key.upper()
        command = self.keymap.get(key_upper)
        if not command:
            print(f"Remote[{self.device_type.upper()}]: Key '{key_upper}' not mapped in {self.ir_config_file}")
            self._record_send(False, f"Key {key_upper} not mapped in {self.ir_config_file}")
            return False

        if self.ir_led is not None:
            payload = f"snd {self.ir_remote},{command},l{self.ir_led}\r"
        else:
            payload = f"snd {self.ir_remote},{command}\r"

        print(f"Remote[{self.device_type.upper()}]: Sending {key_upper} -> {payload!r} "
              f"to {self.ir_ip}:{self.ir_port}")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload.encode('ascii'), (self.ir_ip, self.ir_port))
            self._record_send(True)
            return True
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Failed to send IRTrans command: {e}")
            self._record_send(False, str(e))
            return False

    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute IRTrans remote command.

        Args:
            command: Command to execute ('press_key', 'get_pairing_status', 'get_status')
            params: Command parameters

        Returns:
            Dict[str, Any]: Dict with 'success' key indicating command execution status
        """
        if params is None:
            params = {}

        print(f"Remote[{self.device_type.upper()}]: Executing command '{command}' with params: {params}")

        if command == 'press_key':
            key = params.get('key')
            success = self.press_key(key) if key else False
        elif command in ('get_pairing_status', 'get_status'):
            # Same command name the Take Control status-dot pipeline polls.
            return {'success': True, 'status': self.get_health()}
        else:
            print(f"Remote[{self.device_type.upper()}]: Unknown command: {command}")
            success = False

        return {'success': success}

    def _record_send(self, ok: bool, error: str = None) -> None:
        """Record the outcome of the most recent IR send (feeds the status dot)."""
        self._last_send_ok = ok
        self._last_send_error = None if ok else (error or 'IRTrans send failed')
        self._last_send_ts = time.time()

    def get_health(self) -> Dict[str, Any]:
        """
        Health for the Take Control status dot.

        IRTrans UDP `snd` is fire-and-forget (no ACK), so the non-destructive probe is
        a short **TCP connect** to the IRTrans box (it also listens on TCP at the same
        port). Reachable + last send not failed → green; box unreachable or last key
        press failed → red. Cached briefly so polling never stacks connects.
        Mirrors IRRemoteController.get_ir_health().
        """
        now = time.time()
        if self._health_cache is not None and (now - self._health_cache_ts) < 5:
            cached = dict(self._health_cache)
            cached['last_send_ok'] = self._last_send_ok
            cached['last_send_error'] = self._last_send_error
            cached['last_send_ts'] = self._last_send_ts
            return cached

        tx_probe_ok = False
        probe_error = None
        try:
            with socket.create_connection((self.ir_ip, self.ir_port), timeout=1.5):
                tx_probe_ok = True
        except Exception as e:
            probe_error = f'IRTrans box {self.ir_ip}:{self.ir_port} unreachable: {e}'

        healthy = tx_probe_ok and self._last_send_ok is not False

        if not tx_probe_ok:
            detail = f'IRTrans box not responding: {probe_error}'
        elif self._last_send_ok is False:
            detail = f'Last IR key press failed: {self._last_send_error}'
        else:
            detail = f'IRTrans ready ({self.ir_ip}:{self.ir_port}, {self.ir_remote}, led {self.ir_led})'

        status = {
            'ir_ip': self.ir_ip,
            'ir_port': self.ir_port,
            'ir_remote': self.ir_remote,
            'ir_led': self.ir_led,
            'ir_type': self.ir_type,
            'device_present': tx_probe_ok,  # network reachability stands in for device_present
            'tx_probe_ok': tx_probe_ok,
            'probe_error': probe_error,
            'last_send_ok': self._last_send_ok,
            'last_send_error': self._last_send_error,
            'last_send_ts': self._last_send_ts,
            'healthy': healthy,
            'detail': detail,
        }
        self._health_cache = status
        self._health_cache_ts = now
        return status

    def get_status(self) -> Dict[str, Any]:
        """Get controller status information."""
        return {
            'success': True,
            'controller_type': self.controller_type,
            'device_type': self.device_type,
            'device_name': self.device_name,
            'ir_ip': self.ir_ip,
            'ir_port': self.ir_port,
            'ir_remote': self.ir_remote,
            'ir_led': self.ir_led,
            'ir_type': self.ir_type,
            'ir_config_file': self.ir_config_file,
            'connected': self.is_connected,
            'supported_keys': self.ir_available_keys,
            'capabilities': [
                'ir_control', 'navigation', 'numeric_input', 'media_control',
                'volume_control', 'channel_control', 'power_control'
            ]
        }

    def get_available_actions(self) -> Dict[str, Any]:
        """Get available actions from the loaded IRTrans keymap."""
        if not self.keymap:
            raise ValueError(f"No IRTrans keymap loaded for {self.ir_type}")

        actions = []
        for key_name in self.keymap.keys():
            if not self.keymap[key_name]:
                continue
            actions.append({
                'id': f'ir_press_key_{key_name.lower()}',
                'label': f'{key_name}',
                'command': 'press_key',
                'action_type': 'remote',
                'params': {'key': key_name},
                'description': f'Press {key_name} key via IRTrans',
                'requiresInput': False
            })

        return {'remote': actions}
