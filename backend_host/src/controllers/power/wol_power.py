"""
Wake-on-LAN Power Controller Implementation

Powers a LAN machine (typically a Windows PC) without a smart plug:

    power_on   → magic packet (6×FF + 16×MAC) broadcast over UDP to <broadcast>:9.
                 The host must sit on the same L2 network as the machine — WoL is a
                 broadcast and does not cross routers or Tailscale.
    power_off  → `ssh <user>@<ip> shutdown /s /t 0 /f` (key auth, BatchMode).
    reboot     → `ssh <user>@<ip> shutdown /r /t 0 /f`.
    status     → TCP connect to <ip>:<ssh_port>. ICMP is blocked by the Windows
                 firewall by default, sshd answers whenever the OS is up.

Same public interface as TapoPowerController, so the power routes and power
button use it unchanged. Machine-side prep (BIOS WoL, Fast Startup off,
OpenSSH Server, auto sign-in): docs/agent/devices/WAKE_ON_LAN.md.
"""

from typing import Dict, Any, List, Optional, Union
import re
import socket
import subprocess
from ..base_controller import PowerControllerInterface


def build_magic_packet(mac: str) -> bytes:
    """Return the WoL magic packet for a MAC written with ':' or '-' separators (or none)."""
    hex_mac = re.sub(r'[^0-9A-Fa-f]', '', mac or '')
    if len(hex_mac) != 12:
        raise ValueError(f"Invalid MAC address for Wake-on-LAN: '{mac}'")
    return b'\xff' * 6 + bytes.fromhex(hex_mac) * 16


class WOLPowerController(PowerControllerInterface):
    """Power controller: Wake-on-LAN to switch on, SSH shutdown to switch off."""

    WOL_PORT = 9
    SSH_TIMEOUT = 15  # seconds
    PROBE_TIMEOUT = 2  # seconds

    def __init__(self, mac: str, device_ip: str, ssh_user: Optional[str] = None,
                 ssh_port: Union[int, str] = 22, broadcast: str = '255.255.255.255', **kwargs):
        """
        Initialize the Wake-on-LAN power controller.

        Args:
            mac: MAC address of the machine's wired NIC (required)
            device_ip: LAN IP of the machine — SSH target and status probe (required)
            ssh_user: Account for the SSH shutdown. Unset = power_off/reboot unavailable.
            ssh_port: sshd port, also used as the status probe port
            broadcast: Broadcast address the magic packet is sent to
        """
        super().__init__("WOL Power")

        self.power_type = "wol"
        self.mac = mac
        self.device_ip = device_ip
        self.ssh_user = ssh_user
        self.ssh_port = int(ssh_port or 22)
        self.broadcast = broadcast or '255.255.255.255'
        self.current_power_state = "unknown"

        if not self.device_ip:
            raise ValueError("device_ip is required for WOLPowerController")
        self.magic_packet = build_magic_packet(mac)  # validates the MAC

        print(f"[@controller:WOLPower] Initialized for {self.mac} at {self.device_ip} "
              f"(broadcast {self.broadcast}, ssh user {self.ssh_user or 'none — power off disabled'})")

    def connect(self) -> bool:
        """No persistent connection — WoL and SSH are per call."""
        self.is_connected = True
        print(f"Power[{self.power_type.upper()}]: WoL power ready for {self.device_ip}")
        return True

    def disconnect(self) -> bool:
        self.is_connected = False
        print(f"Power[{self.power_type.upper()}]: WoL power disconnected for {self.device_ip}")
        return True

    def _send_magic_packet(self) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(self.magic_packet, (self.broadcast, self.WOL_PORT))
            print(f"Power[{self.power_type.upper()}]: Magic packet sent to {self.mac} via {self.broadcast}:{self.WOL_PORT}")
            return True
        except OSError as e:
            print(f"Power[{self.power_type.upper()}]: Magic packet error: {e}")
            return False

    def _ssh_command(self, remote_command: List[str]) -> List[str]:
        return [
            'ssh',
            '-o', 'BatchMode=yes',
            '-o', f'ConnectTimeout={self.SSH_TIMEOUT}',
            '-o', 'StrictHostKeyChecking=accept-new',
            '-p', str(self.ssh_port),
            f'{self.ssh_user}@{self.device_ip}',
            *remote_command,
        ]

    def _run_ssh(self, remote_command: List[str]) -> bool:
        if not self.ssh_user:
            print(f"Power[{self.power_type.upper()}]: POWER_SSH_USER not set — cannot run {remote_command}")
            return False
        argv = self._ssh_command(remote_command)
        try:
            print(f"Power[{self.power_type.upper()}]: {' '.join(argv)}")
            result = subprocess.run(argv, capture_output=True, text=True, timeout=self.SSH_TIMEOUT + 5)
            if result.returncode != 0:
                print(f"Power[{self.power_type.upper()}]: SSH exit {result.returncode}: "
                      f"{(result.stderr or result.stdout).strip()[:200]}")
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"Power[{self.power_type.upper()}]: SSH error: {e}")
            return False

    def _is_reachable(self) -> bool:
        try:
            with socket.create_connection((self.device_ip, self.ssh_port), timeout=self.PROBE_TIMEOUT):
                return True
        except OSError:
            return False

    def power_on(self, timeout: float = 10.0) -> bool:
        """Wake the machine with a magic packet. Booting takes longer than this call."""
        success = self._send_magic_packet()
        if success:
            self.current_power_state = "on"
        return success

    def power_off(self, force: bool = False, timeout: float = 5.0) -> bool:
        """Shut the machine down over SSH."""
        success = self._run_ssh(['shutdown', '/s', '/t', '0', '/f'])
        if success:
            self.current_power_state = "off"
            print(f"Power[{self.power_type.upper()}]: Shutdown sent to {self.device_ip}")
        return success

    def reboot(self, timeout: float = 40.0) -> bool:
        """Restart the machine over SSH (no WoL needed, the OS restarts itself)."""
        success = self._run_ssh(['shutdown', '/r', '/t', '0', '/f'])
        if success:
            print(f"Power[{self.power_type.upper()}]: Restart sent to {self.device_ip}")
        return success

    def get_power_status(self) -> Dict[str, Any]:
        """'on' when sshd answers, 'off' otherwise."""
        power_state = 'on' if self._is_reachable() else 'off'
        self.current_power_state = power_state
        print(f"Power[{self.power_type.upper()}]: Status for {self.device_ip}: {power_state}")
        return {
            'power_state': power_state,
            'device_ip': self.device_ip,
            'connected': True,
            'device_info': {'mac': self.mac, 'probe_port': self.ssh_port},
        }

    def isPowerOn(self) -> bool:
        """Check if device is powered on."""
        return self.get_power_status().get('power_state') == 'on'

    def isPowerOff(self) -> bool:
        """Check if device is powered off."""
        return self.get_power_status().get('power_state') == 'off'

    def get_available_actions(self) -> Dict[str, Any]:
        """Get available actions for this Wake-on-LAN power controller."""
        return {
            'power': [
                {
                    'id': 'power_on',
                    'label': 'Power On',
                    'command': 'power_on',
                    'action_type': 'power',
                    'params': {},
                    'description': 'Wake the machine with a Wake-on-LAN magic packet',
                    'requiresInput': False
                },
                {
                    'id': 'power_off',
                    'label': 'Power Off',
                    'command': 'power_off',
                    'action_type': 'power',
                    'params': {},
                    'description': 'Shut the machine down over SSH',
                    'requiresInput': False
                },
                {
                    'id': 'reboot',
                    'label': 'Reboot',
                    'command': 'reboot',
                    'action_type': 'power',
                    'params': {},
                    'description': 'Restart the machine over SSH',
                    'requiresInput': False
                }
            ]
        }

    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute WoL power command.

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
            'mac': self.mac,
            'device_ip': self.device_ip,
            'connected': self.is_connected,
            'current_power_state': self.current_power_state,
            'capabilities': ['wol_power_control', 'power_on', 'power_off', 'reboot', 'get_power_status']
        }
