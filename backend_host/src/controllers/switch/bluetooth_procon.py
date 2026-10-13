"""
Bluetooth Pro Controller switch controller (TASK-31).

Drives a stock Nintendo Switch (no custom firmware) by emulating a Pro
Controller over Bluetooth. The emulation itself runs in the root daemon
`vpt-procon.service` (backend_host/src/controllers/switch/procon/procon_daemon.py,
nxbt). This controller only calls that daemon's HTTP API, so vpt-host needs
no Bluetooth privileges and a vpt-host restart never drops the link. The
daemon can sit on another host of the LAN (the one whose adapter is in range
of the Switch): DEVICE{i}_SWITCH_PROCON_URL + DEVICE{i}_SWITCH_PROCON_TOKEN.

Setup, requirements and revert: docs/agent/devices/NINTENDO_SWITCH.md.

send_command() accepts:
  press:<button>             a b x y l r zl zr minus plus home capture l3 r3
                             up down left right (D-pad)
  sequence:[a,down,a]        presses in order
  stick:<left|right>,<up|down|left|right>[,<duration_ms>]
  hold:<button>[,<button>]   held until release
  release
  pair                       open the pairing window (Controllers -> Change Grip/Order)
  status
"""

from typing import Any, Dict, Optional

import requests

from .base_switch import BaseSwitchController

DAEMON_DOWN = ("Pro Controller daemon (vpt-procon) not reachable: is vpt-procon.service "
               "running on the host that owns the Bluetooth adapter?")


class BluetoothProconSwitchController(BaseSwitchController):
    """Nintendo Switch via the vpt-procon Bluetooth Pro Controller daemon."""

    def __init__(self, controller_name: str = "Bluetooth Pro Controller",
                 daemon_url: str = "http://127.0.0.1:6190", token: Optional[str] = None,
                 default_hold_ms: int = 100, **kwargs):
        self.controller_name = controller_name
        self.device_id = kwargs.get("device_id", "unknown")
        self.daemon_url = daemon_url.rstrip("/")
        self._headers = {"X-Procon-Token": token} if token else {}
        self.default_hold_ms = int(default_hold_ms)
        print(f"SWITCH[{self.device_id}]: Bluetooth Pro Controller via {self.daemon_url}")

    # -- daemon calls --------------------------------------------------------
    def _call(self, method: str, path: str, body: Optional[Dict] = None,
              timeout: float = 30) -> Dict[str, Any]:
        try:
            resp = requests.request(method, f"{self.daemon_url}{path}", json=body,
                                    headers=self._headers, timeout=timeout)
        except requests.ConnectionError:
            return {"success": False, "error": f"{DAEMON_DOWN} ({self.daemon_url})", "state": "daemon_down"}
        except requests.Timeout:
            return {"success": False, "error": f"vpt-procon did not answer {path} in {timeout:.0f}s"}
        try:
            return resp.json()
        except ValueError:
            return {"success": False, "error": f"vpt-procon {path}: HTTP {resp.status_code}"}

    def press_button(self, name: str, hold_ms: Optional[int] = None) -> Dict[str, Any]:
        return self._call("POST", "/press", {"button": name, "hold_ms": hold_ms or self.default_hold_ms})

    def get_status(self) -> Dict[str, Any]:
        status = self._call("GET", "/status", timeout=5)
        status.update({
            "controller_type": "switch",
            "implementation": "bluetooth_procon",
            "is_implemented": True,
            "controller_name": self.controller_name,
            "device_id": self.device_id,
        })
        status.setdefault("state", "unknown")
        status["success"] = status.get("state") not in ("daemon_down", "unknown")
        return status

    # -- BaseSwitchController interface ----------------------------------------
    def list_inputs(self) -> Dict[str, Any]:
        return {
            "success": True,
            "inputs": [],
            "buttons": ["a", "b", "x", "y", "l", "r", "zl", "zr", "minus", "plus",
                        "home", "capture", "l3", "r3", "up", "down", "left", "right"],
            "sticks": ["left", "right"],
            "status": self.get_status(),
        }

    def send_command(self, command: str, **kwargs) -> Dict[str, Any]:
        command = (command or "").strip()
        verb, _, arg = command.partition(":")
        verb = verb.lower()
        args = [a.strip().strip("'\"") for a in arg.strip("[] ").split(",") if a.strip()]
        if verb == "press" and args:
            return self.press_button(args[0], kwargs.get("hold_ms"))
        if verb == "sequence" and args:
            return self._call("POST", "/sequence", {"buttons": args,
                                                    "hold_ms": kwargs.get("hold_ms", self.default_hold_ms),
                                                    "gap_ms": kwargs.get("gap_ms", 150)}, timeout=60)
        if verb == "stick" and len(args) >= 2:
            body = {"stick": args[0], "direction": args[1].lower(),
                    "duration_ms": int(args[2]) if len(args) > 2 else kwargs.get("duration_ms", 200)}
            return self._call("POST", "/stick", body)
        if verb == "hold" and args:
            return self._call("POST", "/hold", {"buttons": args})
        if verb == "release":
            return self._call("POST", "/release", {})
        if verb == "pair":
            return self._call("POST", "/pair", {})
        if verb == "status":
            return self.get_status()
        return {"success": False,
                "error": f"unknown switch command {command!r}: use press:<button>, sequence:[...], "
                         f"stick:<left|right>,<direction>, hold:<button>, release, pair or status"}
