"""
Vega OS Remote Controller (Amazon Fire TV on Linux, not Android).

Vega Fire TV does NOT expose Android adb tools (``input keyevent``, ``getprop``,
``am``, ``pm``, ``screencap``). Drives the device through Vega binaries:
``inputd-cli`` (keys/text), ``vmsgr``/``vlcm``/``vpm`` (app lifecycle),
``gwsi-tool-screenshooter`` (screenshots). See ``docs/tasks/TASK-57-vega-firetv.md``.

Commands (all via ``adb shell ...`` unless noted):

    Key:        inputd-cli button_press KEY_<NAME>     # "Injecting Button Press"
    Text:       inputd-cli send_text '<text>'          # exit 0, no "Error"
    Launch:     vmsgr send orpheus://<component-id>    # "Sending:"
    Stop:       vlcm terminate-app --pkg-id <pkg> --force
    Pkg-id:     vpm info <component-id>                # ".../packages/<pkg>/..." in any path line
    Apps:       vpm list apps --category com.amazon.category.main   # tab-indented after "component ids:"
    Foreground: vlcm list                              # column 4 = state, VISIBLE row
    Screenshot: gwsi-tool-screenshooter /tmp/vpt_vega_screenshot.png + adb exec-out cat → PNG bytes

Transient: every shell call returns ``Error: No running instances of
com.amazon.dev.shell.service found`` for ~10 s; ``_shell()`` retries 3x4 s.
"""

from __future__ import annotations

import base64
import re
import shlex
import subprocess
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ..base_controller import RemoteControllerInterface

SHELL_SERVICE_ERROR = "Error: No running instances of com.amazon.dev.shell.service found"
SHELL_MAX_ATTEMPTS = 3
SHELL_RETRY_SLEEP_SECONDS = 4.0

# VPT key name → Linux key name passed to inputd-cli (case-insensitive lookup).
KEY_MAP: Dict[str, str] = {
    "UP": "KEY_UP", "DOWN": "KEY_DOWN", "LEFT": "KEY_LEFT", "RIGHT": "KEY_RIGHT",
    "OK": "KEY_ENTER", "SELECT": "KEY_ENTER", "ENTER": "KEY_ENTER",
    "BACK": "KEY_BACK", "HOME": "KEY_HOMEPAGE",  # NOT KEY_HOME (does nothing)
    "MENU": "KEY_MENU",
    "PLAY_PAUSE": "KEY_PLAYPAUSE", "PLAY": "KEY_PLAYPAUSE", "PAUSE": "KEY_PLAYPAUSE",
    "REWIND": "KEY_REWIND", "FORWARD": "KEY_FASTFORWARD", "FAST_FORWARD": "KEY_FASTFORWARD",
    "VOLUME_UP": "KEY_VOLUMEUP", "VOLUME_DOWN": "KEY_VOLUMEDOWN", "MUTE": "KEY_MUTE",
    "CHANNEL_UP": "KEY_CHANNELUP", "CHANNEL_DOWN": "KEY_CHANNELDOWN", "POWER": "KEY_POWER",
    # Android TV names, so trees and scripts written for android_tv/fire_tv_fireos keep working.
    "DPAD_UP": "KEY_UP", "DPAD_DOWN": "KEY_DOWN", "DPAD_LEFT": "KEY_LEFT", "DPAD_RIGHT": "KEY_RIGHT",
    "DPAD_CENTER": "KEY_ENTER", "MEDIA_PLAY_PAUSE": "KEY_PLAYPAUSE",
}

VALID_COMMANDS = ("press_key, input_text, launch_app, close_app, kill_app, "
                  "get_installed_apps, get_foreground_app, take_screenshot, "
                  "get_status, get_pairing_status")

def _list_valid_keys() -> List[str]:
    return sorted(KEY_MAP.keys())

def _dec(b: Optional[bytes]) -> str:
    return (b or b"").decode("utf-8", errors="replace")

def _combined(stdout: Any, stderr: Any) -> str:
    return (stdout or "") + (stderr or "")


class VegaApp(NamedTuple):
    """One launchable app; same attribute names /host/remote/getApps reads from AndroidApp."""
    package_name: str
    label: str

class VegaRemoteController(RemoteControllerInterface):
    """Vega OS (Amazon Fire TV on Linux) remote controller driven via adb."""

    def __init__(self, device_ip=None, device_port=5555, adb_serial=None, **kwargs):
        super().__init__("Vega TV", "vega")
        self.device_ip, self.device_port, self.adb_serial = device_ip, device_port, adb_serial
        if not self.adb_serial and not self.device_ip:
            raise ValueError("device_ip or adb_serial is required for VegaRemoteController")
        self.target = self.adb_serial or f"{self.device_ip}:{self.device_port}"
        self.last_error = self._last_send_error = None
        self._last_send_ok = None
        self._last_send_ts = self._health_cache_ts = 0.0
        self._health_cache = None
        print(f"[@controller:VegaRemote] Initialized for {self.target}")
        self.connect()

    def _adb(self, args, timeout=20, binary=False):
        """All subprocess calls go through here; tests mock this single seam."""
        try:
            proc = subprocess.run(["adb", "-s", self.target, *args], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, b"" if binary else "", "timeout"
        except Exception as exc:  # pragma: no cover
            return 1, b"" if binary else "", str(exc)
        if binary:
            return proc.returncode, proc.stdout or b"", _dec(proc.stderr)
        return proc.returncode, _dec(proc.stdout), _dec(proc.stderr)

    def _run_adb_connect(self):
        try:
            proc = subprocess.run(["adb", "connect", self.target], capture_output=True, timeout=20)
            return proc.returncode, _dec(proc.stdout), _dec(proc.stderr)
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except Exception as exc:  # pragma: no cover
            return 1, "", str(exc)

    def _retry_sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _shell(self, cmd: str, timeout: int = 20) -> Tuple[int, Any, str]:
        """``adb shell <cmd>`` with retry on the dev-shell-service flake."""
        last = (1, "", "no attempt")
        for attempt in range(SHELL_MAX_ATTEMPTS):
            rc, stdout, stderr = self._adb(["shell", cmd], timeout=timeout)
            last = (rc, stdout, stderr)
            if SHELL_SERVICE_ERROR not in _combined(stdout, stderr):
                return last
            if attempt < SHELL_MAX_ATTEMPTS - 1:
                self._retry_sleep(SHELL_RETRY_SLEEP_SECONDS)
        return last

    def _record_send(self, ok: bool, error: Optional[str] = None) -> None:
        self._last_send_ok = ok
        self._last_send_error = None if ok else (error or "send failed")
        self._last_send_ts = time.time()

    def connect(self) -> bool:
        """TCP targets need ``adb connect <target>``, then echo to confirm."""
        try:
            if ":" in self.target:
                self._run_adb_connect()
            rc, stdout, stderr = self._shell("echo vega-ok")
            if rc == 0 and "vega-ok" in stdout:
                self.is_connected = True
                print(f"Remote[VEGA]: Connected to {self.target}")
                return True
            self.last_error = (stderr or stdout or "echo vega-ok failed").strip()
            print(f"Remote[VEGA]: Connect failed: {self.last_error}")
            self.is_connected = False
            return False
        except Exception as exc:  # pragma: no cover
            self.last_error = str(exc); self.is_connected = False; return False

    def disconnect(self) -> bool:
        self.is_connected = False
        print("Remote[VEGA]: Disconnected")
        return True
    def _resolve_key(self, key: str) -> Optional[str]:
        if not key:
            return None
        if key.upper().startswith("KEY_"):
            return key.upper()
        return KEY_MAP.get(key.upper())

    def press_key(self, key: str) -> bool:
        if not self.is_connected:
            self.last_error = "Not connected to device"
            print(f"Remote[VEGA]: ERROR - {self.last_error}"); return False
        linux_key = self._resolve_key(key)
        if not linux_key:
            valid = ", ".join(_list_valid_keys())
            self.last_error = f"Invalid key '{key}'. Valid keys: {valid}"
            print(f"Remote[VEGA]: {self.last_error}")
            self._record_send(False, self.last_error); return False
        print(f"Remote[VEGA]: Pressing key '{key}' -> {linux_key}")
        rc, stdout, stderr = self._shell(f"inputd-cli button_press {linux_key}")
        output = _combined(stdout, stderr)
        if rc != 0:
            self.last_error = output.strip() or f"inputd-cli exit {rc}"
            self._record_send(False, self.last_error); return False
        # Success is only the injection line: an unknown key still exits 0 ("invalid
        # button value"), and so can a dev-shell-service error that outlived the retries.
        if "Injecting Button Press" not in output:
            self.last_error = output.strip() or f"inputd-cli: no injection for '{linux_key}'"
            self._record_send(False, self.last_error); return False
        self._record_send(True); return True

    def input_text(self, text: str) -> bool:
        if not self.is_connected:
            self.last_error = "Not connected to device"; return False
        if not text:
            self.last_error = "input_text requires non-empty text"
            self._record_send(False, self.last_error); return False
        print(f"Remote[VEGA]: input_text ({len(text)} chars)")
        rc, stdout, stderr = self._shell(f"inputd-cli send_text {shlex.quote(text)}")
        if rc == 0 and "Error" not in _combined(stdout, stderr):
            self._record_send(True); return True
        self.last_error = _combined(stdout, stderr).strip() or f"inputd-cli send_text exit {rc}"
        self._record_send(False, self.last_error); return False

    def _resolve_package_id(self, component_id: str) -> Optional[str]:
        rc, stdout, stderr = self._shell(f"vpm info {shlex.quote(component_id)}")
        output = _combined(stdout, stderr)
        if rc != 0 and not output:
            self.last_error = f"vpm info exit {rc}"; return None
        # Any of lib / assets / data / cache path names the package folder; a JS app
        # (ARTE) has an empty lib path, so do not rely on that one line.
        match = re.search(r"/packages/([^/\s]+)/", output)
        return match.group(1) if match else None

    def launch_app(self, component_id: str) -> bool:
        if not self.is_connected:
            self.last_error = "Not connected to device"; return False
        if not component_id:
            self.last_error = "launch_app requires a component id"
            self._record_send(False, self.last_error); return False
        cmd = f"vmsgr send {shlex.quote('orpheus://' + component_id)}"
        print(f"Remote[VEGA]: Launching {component_id}")
        rc, stdout, stderr = self._shell(cmd)
        if rc == 0 and "Sending:" in _combined(stdout, stderr):
            self._record_send(True); return True
        self.last_error = _combined(stdout, stderr).strip() or f"vmsgr exit {rc}"
        self._record_send(False, self.last_error); return False

    def close_app(self, component_id: str) -> bool:
        if not self.is_connected:
            self.last_error = "Not connected to device"; return False
        if not component_id:
            self.last_error = "close_app requires a component id"
            self._record_send(False, self.last_error); return False
        # Map component id → package id; if `vpm info` gives no `packages/` path
        # the arg IS the package id (e.g. caller already passed one).
        pkg_id = self._resolve_package_id(component_id) or component_id
        cmd = f"vlcm terminate-app --pkg-id {shlex.quote(pkg_id)} --force"
        print(f"Remote[VEGA]: Closing {component_id} (pkg {pkg_id})")
        rc, stdout, stderr = self._shell(cmd)
        if rc == 0:
            self._record_send(True); return True
        self.last_error = _combined(stdout, stderr).strip() or f"vlcm terminate-app exit {rc}"
        self._record_send(False, self.last_error); return False

    def kill_app(self, component_id: str) -> bool:
        return self.close_app(component_id)

    def get_installed_apps(self) -> List[VegaApp]:
        if not self.is_connected:
            self.last_error = "Not connected to device"; return []
        rc, stdout, stderr = self._shell("vpm list apps --category com.amazon.category.main")
        output = _combined(stdout, stderr)
        if rc != 0 and not output:
            self.last_error = f"vpm list apps exit {rc}"
            self._record_send(False, self.last_error); return []
        apps: List[VegaApp] = []
        seen = False
        for line in output.splitlines():
            if not seen:
                if line.strip() == "component ids:":
                    seen = True
                continue
            if line.startswith("\t"):
                cid = line.strip()
                if cid:
                    apps.append(VegaApp(package_name=cid, label=cid))
        self._record_send(True)
        return apps

    def get_foreground_app(self) -> Optional[str]:
        if not self.is_connected:
            self.last_error = "Not connected to device"; return None
        rc, stdout, stderr = self._shell("vlcm list")
        output = _combined(stdout, stderr)
        if rc != 0 and not output:
            self.last_error = f"vlcm list exit {rc}"
            self._record_send(False, self.last_error); return None
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[4] == "VISIBLE":
                self._record_send(True); return parts[0]
        self._record_send(True); return None

    def take_screenshot(self) -> Tuple[bool, str, str]:
        if not self.is_connected:
            return False, "", "Not connected to device"
        print("Remote[VEGA]: Taking screenshot")
        rc, stdout, stderr = self._shell("gwsi-tool-screenshooter /tmp/vpt_vega_screenshot.png")
        if rc != 0:
            self.last_error = _combined(stdout, stderr).strip() or "gwsi-tool-screenshooter failed"
            self._record_send(False, self.last_error); return False, "", self.last_error
        rc, png, err = self._adb(["exec-out", "cat", "/tmp/vpt_vega_screenshot.png"],
                                 timeout=20, binary=True)
        if rc != 0 or not png or not png.startswith(b"\x89PNG"):
            self.last_error = err or "screenshot bytes missing or not PNG"
            self._record_send(False, self.last_error); return False, "", self.last_error
        self._record_send(True)
        return True, base64.b64encode(png).decode("ascii"), ""

    def get_status(self) -> Dict[str, Any]:
        return {"success": True, "controller_type": self.controller_type, "device_type": self.device_type,
                "device_name": self.device_name, "device_ip": self.device_ip, "device_port": self.device_port,
                "adb_device": self.target, "connected": self.is_connected, "supported_keys": _list_valid_keys(),
                "capabilities": ["adb_control", "navigation", "text_input", "app_launch", "app_close",
                                 "media_control", "volume_control", "channel_control", "power_control", "screenshot"]}

    def get_health(self) -> Dict[str, Any]:
        """Cached ADB-presence + shell-echo probe (like infrared.get_ir_health)."""
        now = time.time()
        if self._health_cache is not None and (now - self._health_cache_ts) < 5:
            cached = dict(self._health_cache)
            cached["last_send_ok"], cached["last_send_error"], cached["last_send_ts"] = (self._last_send_ok, self._last_send_error, self._last_send_ts)
            return cached
        device_present, tx_probe_ok = False, False
        rc, stdout, _ = self._adb(["devices"])
        if rc == 0:
            for line in (stdout or "").splitlines():
                line = line.strip()
                if not line or line.startswith("List of devices"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] == self.target and parts[1] == "device":
                    device_present = True; break
        if device_present:
            rc, stdout, _ = self._shell("echo vega-ok")
            tx_probe_ok = rc == 0 and "vega-ok" in (stdout or "")
        healthy = bool(device_present and tx_probe_ok and self._last_send_ok is not False)
        detail = (f"Vega device {self.target} not in adb devices list" if not device_present
                  else f"Vega device {self.target} unreachable (probe failed)" if not tx_probe_ok
                  else f"Last Vega send failed: {self._last_send_error}" if self._last_send_ok is False
                  else f"Vega ready ({self.target})")
        status = {"adb_device": self.target, "device_present": device_present,
                  "tx_probe_ok": tx_probe_ok, "last_send_ok": self._last_send_ok,
                  "last_send_error": self._last_send_error,
                  "last_send_ts": self._last_send_ts, "healthy": healthy, "detail": detail}
        self._health_cache = status
        self._health_cache_ts = now
        return status

    def get_available_actions(self) -> Dict[str, Any]:
        keys = [("up", "Up", "UP"), ("down", "Down", "DOWN"), ("left", "Left", "LEFT"), ("right", "Right", "RIGHT"),
                ("ok", "Select/OK", "OK"), ("back", "Back", "BACK"), ("home", "Home", "HOME"),
                ("menu", "Menu", "MENU"), ("play_pause", "Play/Pause", "PLAY_PAUSE"), ("rewind", "Rewind", "REWIND"),
                ("forward", "Fast Forward", "FORWARD"), ("volume_up", "Volume Up", "VOLUME_UP"),
                ("volume_down", "Volume Down", "VOLUME_DOWN"), ("mute", "Mute", "MUTE")]
        comp_desc = "Vega component id, e.g. com.netflix.kepler.main"
        comp_ph = "com.example.app.main"
        actions: List[Dict[str, Any]] = [
            {"id": f"press_key_{s}", "label": l, "command": "press_key",
             "action_type": "remote", "params": {"key": k},
             "description": f"Press {l}", "requiresInput": False}
            for s, l, k in keys
        ] + [
            {"id": "input_text", "label": "Input Text", "command": "input_text",
             "action_type": "remote", "params": {"text": ""},
             "description": "Type text into the current field", "requiresInput": True,
             "inputLabel": "Text to input", "inputPlaceholder": "Enter text..."},
            {"id": "launch_app", "label": "Launch App", "command": "launch_app",
             "action_type": "remote", "params": {"package": ""}, "description": comp_desc,
             "requiresInput": True, "inputLabel": "Vega component id", "inputPlaceholder": comp_ph},
            {"id": "close_app", "label": "Close App", "command": "close_app",
             "action_type": "remote", "params": {"package": ""}, "description": comp_desc,
             "requiresInput": True, "inputLabel": "Vega component id", "inputPlaceholder": comp_ph},
        ]
        return {"remote": actions}

    def execute_command(self, command: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if params is None:
            params = {}
        wait_time = int(params.get("wait_time", 0))
        print(f"Remote[VEGA]: Executing command '{command}' with params: {params}")
        actions = {
            "press_key": ("key", self.press_key), "input_text": ("text", self.input_text),
            "launch_app": ("package", self.launch_app), "close_app": ("package", self.close_app),
            "kill_app": ("package", self.kill_app),
        }
        retryable = command in actions or command in ("get_installed_apps", "get_foreground_app", "take_screenshot")

        def _run() -> Dict[str, Any]:
            if command in actions:
                pkey, method = actions[command]
                value = params.get(pkey)
                if not value:
                    return {"success": False, "error": f"{command} requires '{pkey}'"}
                ok = method(value)
                return {"success": ok, "error": None if ok else self.last_error}
            if command == "get_installed_apps":
                apps = self.get_installed_apps()
                return {"success": True, "apps": [{"packageName": a.package_name, "label": a.label} for a in apps]}
            if command == "get_foreground_app":
                return {"success": True, "app": self.get_foreground_app()}
            if command == "take_screenshot":
                ok, data, err = self.take_screenshot()
                return {"success": ok, "screenshot": data, "error": err}
            if command in ("get_pairing_status", "get_status"):
                return {"success": True, "status": self.get_health()}
            return {"success": False,
                    "error": f"Invalid command '{command}' for vega device. Valid commands: {VALID_COMMANDS}"}

        try:
            result = _run()
        except Exception as exc:
            result = {"success": False, "error": str(exc)}
        if not result.get("success") and retryable and not self.is_connected:
            print(f"Remote[VEGA]: '{command}' failed — attempting reconnect...")
            if self.connect():
                try:
                    result = _run()
                except Exception as exc:
                    result = {"success": False, "error": str(exc)}
        if result.get("success") and wait_time > 0:
            time.sleep(wait_time / 1000.0)
        return result