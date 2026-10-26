"""
Samsung Tizen TV remote controller (network websocket).

Drives a Samsung Smart TV over its websocket remote API (tcp/8002, TLS) using the
`samsungtvws` library. No HDMI/IR hardware and no Tizen Studio needed — pairing is a
one-time "Allow" on the TV, after which the token is cached per device.

This is the network-remote counterpart to the IR/BLE remotes already bound to the
`tizen` device model (whose AV is a camera filming the panel). Control here is pure
network; the camera_stream AV controller provides the pixels.

Mirrors android_tv.py for structure: connect/disconnect, press_key, execute_command
dispatch, and the status-dot health block (_record_send/get_health) so the Take
Control panel LED works with the shared frontend code path.
"""
import os
import time
import json
from typing import Dict, Any, Optional

try:
    from controllers.base_controller import RemoteControllerInterface
except Exception:  # pragma: no cover - import path differs by entrypoint
    from backend_host.src.controllers.base_controller import RemoteControllerInterface


# Logical VPT key -> Samsung Tizen KEY_* code. Logical names match the IR/android panels
# so navigation trees and the on-screen remote are transport-agnostic.
KEY_MAP: Dict[str, str] = {
    # D-pad + select
    "UP": "KEY_UP", "DOWN": "KEY_DOWN", "LEFT": "KEY_LEFT", "RIGHT": "KEY_RIGHT",
    "OK": "KEY_ENTER", "ENTER": "KEY_ENTER", "SELECT": "KEY_ENTER",
    "BACK": "KEY_RETURN", "RETURN": "KEY_RETURN", "EXIT": "KEY_EXIT",
    # System
    "HOME": "KEY_HOME", "MENU": "KEY_MENU", "TOOLS": "KEY_TOOLS",
    "INFO": "KEY_INFO", "GUIDE": "KEY_GUIDE", "SOURCE": "KEY_SOURCE",
    "POWER": "KEY_POWER",
    # Volume / mute
    "VOLUME_UP": "KEY_VOLUP", "VOLUME_DOWN": "KEY_VOLDOWN", "MUTE": "KEY_MUTE",
    # Channels
    "CHANNEL_UP": "KEY_CHUP", "CHANNEL_DOWN": "KEY_CHDOWN", "CHANNEL_LIST": "KEY_CH_LIST",
    # Colour buttons
    "RED": "KEY_RED", "GREEN": "KEY_GREEN", "YELLOW": "KEY_YELLOW", "BLUE": "KEY_BLUE",
    # Media transport
    "PLAY": "KEY_PLAY", "PAUSE": "KEY_PAUSE", "PLAY_PAUSE": "KEY_PLAY_BACK",
    "STOP": "KEY_STOP", "REWIND": "KEY_REWIND", "FAST_FORWARD": "KEY_FF",
    # Digits
    "0": "KEY_0", "1": "KEY_1", "2": "KEY_2", "3": "KEY_3", "4": "KEY_4",
    "5": "KEY_5", "6": "KEY_6", "7": "KEY_7", "8": "KEY_8", "9": "KEY_9",
}


class SamsungTizenRemoteController(RemoteControllerInterface):
    """Samsung Tizen TV remote over the websocket API (samsungtvws)."""

    @staticmethod
    def get_remote_config() -> Dict[str, Any]:
        """On-screen remote panel layout. Falls back to a minimal inline layout when no
        JSON panel file is shipped (the frontend provides the full Samsung panel)."""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'config', 'remote', 'samsung_tizen_remote.json'
        )
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return json.load(f)
        # Minimal transport-agnostic panel: logical keys the frontend can render as buttons.
        return {
            "remote_type": "samsung_tizen",
            "image": "/samsung_remote.png",
            "keys": sorted(KEY_MAP.keys()),
        }

    def __init__(self, tv_ip: str = None, tv_port: int = 8002, token: str = None,
                 token_file: str = None, remote_name: str = "VirtualPyTest",
                 device_name: str = "Samsung Tizen TV", **kwargs):
        """
        Args:
            tv_ip:      TV IP (DEVICE<N>_TIZEN_IP). Required.
            tv_port:    websocket port (default 8002, TLS). DEVICE<N>_TIZEN_PORT.
            token:      cached pairing token string (DEVICE<N>_TIZEN_TOKEN). Optional.
            token_file: path to persist the token (DEVICE<N>_TIZEN_TOKEN_FILE). Optional;
                        default under the home dir so pairing survives restarts.
        """
        super().__init__(device_name, "samsung_tizen")

        self.tv_ip = tv_ip
        self.tv_port = int(tv_port) if tv_port else 8002
        self.remote_name = remote_name
        self.token = token
        # Persist the token so the TV's one-time "Allow" is not re-prompted each restart.
        self.token_file = token_file or os.path.join(
            os.path.expanduser("~"), ".vpt_tizen_token_%s.txt" % (tv_ip or "unknown")
        )

        if not self.tv_ip:
            raise ValueError("tv_ip is required for SamsungTizenRemoteController")

        self._tv = None  # lazy samsungtvws handle

        # Status-dot health (same field names as android_tv / vega / infrared)
        self._last_send_ok: Optional[bool] = None
        self._last_send_error: Optional[str] = None
        self._last_send_ts: float = 0.0

        print(f"[@controller:SamsungTizenRemote] Initialized for {self.tv_ip}:{self.tv_port}")
        self.connect()

    # ---------- health ----------
    def _record_send(self, ok: bool, error: Optional[str] = None) -> None:
        self._last_send_ok = ok
        self._last_send_error = None if ok else (error or "send failed")
        self._last_send_ts = time.time()

    def get_health(self) -> Dict[str, Any]:
        """Status-dot payload for the Take Control panel (InfraredStatus-shaped)."""
        present = False
        detail = "not connected"
        try:
            # REST device info is a cheap, non-destructive reachability probe.
            import urllib.request
            url = "http://%s:8001/api/v2/" % self.tv_ip
            with urllib.request.urlopen(url, timeout=3) as r:
                info = json.load(r)
            present = True
            detail = "%s (%s)" % (info.get("device", {}).get("name", "TV"),
                                  info.get("device", {}).get("PowerState", "?"))
        except Exception as e:
            detail = "unreachable: %s" % e
        return {
            "device_present": present,
            "tx_probe_ok": present,
            "last_send_ok": self._last_send_ok,
            "last_send_error": self._last_send_error,
            "last_send_ts": self._last_send_ts,
            "healthy": present and (self._last_send_ok is not False),
            "detail": detail,
        }

    # ---------- connection ----------
    def connect(self) -> bool:
        try:
            from samsungtvws import SamsungTVWS
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: ERROR - samsungtvws not installed: {e}")
            self.is_connected = False
            return False
        try:
            # timeout=30: on an unpaired host the first connect holds the socket open
            # long enough for the user to accept the TV's "Allow" prompt, so samsungtvws
            # can persist the issued token to token_file. Once paired, connects succeed
            # immediately and the 30s is only an upper bound.
            self._tv = SamsungTVWS(
                host=self.tv_ip, port=self.tv_port, name=self.remote_name,
                token=self.token, token_file=self.token_file, timeout=30
            )
            self.is_connected = True
            print(f"Remote[{self.device_type.upper()}]: Ready for {self.tv_ip}:{self.tv_port}")
            return True
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Connection error: {e}")
            self.is_connected = False
            return False

    def disconnect(self) -> bool:
        try:
            if self._tv is not None:
                try:
                    self._tv.close()
                except Exception:
                    pass
            self._tv = None
            self.is_connected = False
            return True
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Disconnect error: {e}")
            return False

    # ---------- primitives ----------
    def press_key(self, key: str) -> bool:
        if self._tv is None and not self.connect():
            self._record_send(False, "not connected")
            return False
        code = KEY_MAP.get(str(key).upper())
        if code is None:
            # Allow passing a raw KEY_* code straight through.
            raw = str(key)
            code = raw if raw.startswith("KEY_") else None
        if code is None:
            print(f"Remote[{self.device_type.upper()}]: Unknown key '{key}'")
            self._record_send(False, f"unknown key {key}")
            return False
        try:
            self._tv.send_key(code)
            print(f"Remote[{self.device_type.upper()}]: Sent {key} -> {code}")
            self._record_send(True)
            return True
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Key send error: {e}")
            self._record_send(False, str(e))
            # Force a fresh handle next time (token/socket may have dropped).
            self._tv = None
            return False

    def launch_app(self, app_id: str) -> bool:
        """Launch a built-in/store app by its websocket app id."""
        if self._tv is None and not self.connect():
            self._record_send(False, "not connected")
            return False
        try:
            self._tv.run_app(app_id)
            self._record_send(True)
            return True
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: App launch error: {e}")
            self._record_send(False, str(e))
            return False

    def open_browser(self, url: str) -> bool:
        if self._tv is None and not self.connect():
            return False
        try:
            self._tv.open_browser(url)
            self._record_send(True)
            return True
        except Exception as e:
            self._record_send(False, str(e))
            return False

    # ---------- dispatch ----------
    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        params = params or {}
        wait_time = int(params.get('wait_time', 0))
        print(f"Remote[{self.device_type.upper()}]: Executing '{command}' params={params}")

        def _run():
            if command == 'get_pairing_status':
                return {'success': True, 'status': self.get_health()}
            if command == 'press_key':
                key = params.get('key')
                return {'success': self.press_key(key) if key else False}
            if command == 'launch_app':
                app = params.get('app') or params.get('package') or params.get('app_id')
                return {'success': self.launch_app(app) if app else False}
            if command == 'open_browser':
                url = params.get('url')
                return {'success': self.open_browser(url) if url else False}
            return {'success': False, 'error': f"unsupported command '{command}'"}

        result = _run()
        if wait_time > 0:
            time.sleep(wait_time / 1000.0)
        return result
