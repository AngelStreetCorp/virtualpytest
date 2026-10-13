"""
FX remote controller — the telephone as a VirtualPyTest remote (TASK-71).

A USB voice modem (Conexant CX93001, `0572:1349`) on a backend_host, presented
to VPT as a device whose remote is the handset. Device model `fx_dongle`.

    pick up the phone, hang it up, dial, send DTMF — from the remote panel,
    from a script action, or from the AI agent.

Why a *remote* and not a new capability type: a telephone handset is to VPT what
a Tello drone is — a device whose remote is a command surface rather than a TV
button pad. `remote/tello.py` established that shape, and reusing the `remote`
slot means the button panel, `/host/remote/executeCommand`, `execute_sequence`
with its retry/failure actions, and the action executor's remote branch all work
unchanged. A new `telephony` capability would have needed its own plumbing
through every one of those, plus an eighth slot in the capability builder.

execute_command surface
-----------------------
    off_hook                     pick up (ATA)
    on_hook | hangup             hang up (AT+VNH=1, falling back to ATH)
    dial        {number}         off-hook + ATDT<number>;
                                 {number} defaults to DEVICE{i}_FX_NUMBER,
                                 the number this line's gateway answers to
    wait_connected {timeout}     wait for CONNECT
    send_digits {digits, in_call} DTMF in-call — see dtmf.py for the honesty
                                 caveat: accepted is not verified
    ring        {timeout}        wait for an incoming call (RING)
    selftest                     the PoC battery, no line needed
    audio                        is voice audio reachable from the host?
    status                       line state, firmware, DTMF strategy
    reset                        recover a modem stuck off-hook
    press_key    {key}           one call, the entry point the remote UI uses

Every one of these returns a dict with `success`, the shape
`RemoteControllerInterface.execute_sequence` and the action executor expect.

Nothing above this file sees an AT command. A second USB voice modem is a new
factory in voice_modem.py and a new implementation name here, not a change to
any caller.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ...base_controller import RemoteControllerInterface
from .at_channel import ATError, CONNECT_TIMEOUT, DIAL_TIMEOUT, RING_TIMEOUT
from .voice_modem import VoiceModem

# Remote-panel keys -> the command they mean. The analogue of tello's KEY_MAP,
# and the reason the on-screen remote works with no FX-specific UI code.
KEY_MAP: Dict[str, Dict[str, Any]] = {
    "OFF_HOOK": {"command": "off_hook", "params": {}},
    "ON_HOOK": {"command": "on_hook", "params": {}},
    "HANGUP": {"command": "on_hook", "params": {}},
    "DIAL": {"command": "dial", "params": {}},
    "DIGITS": {"command": "send_digits", "params": {}},
    "RING": {"command": "ring", "params": {}},
}

# Verbs that change line state. Anything else is a read or a recovery.
_LINE_VERBS = ("off_hook", "on_hook", "hangup", "dial", "send_digits")


class FXRemoteController(RemoteControllerInterface):
    """Remote controller for an FX voice modem."""

    def __init__(self, device_name: str = "FX", fx_port: str = None,
                 fx_number: str = None, device_type: str = "fx", **kwargs):
        super().__init__(device_name, device_type)
        self.device_id = kwargs.get("device_id", "unknown")
        # DEVICE{i}_FX_PORT is the whole point of the udev naming: without it
        # this would be /dev/ttyACM0, which changes meaning across a reboot.
        self.fx_port = fx_port or os.path.join("/dev/fixnet", "modem0")
        # The number this line dials, from DEVICE{i}_FX_NUMBER. Each dongle
        # reaches one gateway FXS port, and that port answers to one number, so
        # the pairing belongs in .env beside FX_PORT rather than in every test
        # case. A test case may still pass {number} to override it.
        self.fx_number = (fx_number or "").strip()
        self._vm = VoiceModem(self.fx_port, name=device_name, verbose=bool(kwargs.get("verbose")))
        self.is_connected = True   # a serial line has no separate connect step

    # -- helpers -----------------------------------------------------------

    def _fail(self, reason: str, **extra) -> Dict[str, Any]:
        return {"success": False, "error": reason, "port": self.fx_port, **extra}

    def _ok(self, **payload) -> Dict[str, Any]:
        return {"success": True, "port": self.fx_port, **payload}

    @staticmethod
    def _as_int(params: Dict[str, Any], key: str, default: int) -> int:
        try:
            return int(params.get(key, default))
        except (TypeError, ValueError):
            return default

    # -- the surface -------------------------------------------------------

    def execute_command(self, command: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        cmd = (command or "").strip().lower()

        try:
            if cmd == "press_key":
                return self._press_key(params)

            if cmd == "off_hook":
                self._vm.off_hook()
                return self._ok(state="off_hook")

            if cmd in ("on_hook", "hangup"):
                self._vm.hangup()
                return self._ok(state="on_hook")

            if cmd == "dial":
                # DEVICE{i}_FX_NUMBER is the default for this line; an explicit
                # {number} wins, so a test case can dial anywhere.
                number = str(params.get("number") or self.fx_number).strip()
                if not number:
                    return self._fail("dial needs a number: pass {number} or set "
                                      "DEVICE{i}_FX_NUMBER for this device")
                self._vm.off_hook()
                self._vm.dial(number, timeout=self._as_int(params, "timeout", int(DIAL_TIMEOUT)))
                return self._ok(number=number, state="dialling")

            if cmd == "wait_connected":
                res = self._vm.wait_connected(self._as_int(params, "timeout", int(CONNECT_TIMEOUT)))
                return {"success": bool(res["connected"]), "port": self.fx_port,
                        "connected": res["connected"], "line": res["line"],
                        "seen": res["seen"]}

            if cmd == "send_digits":
                digits = str(params.get("digits", "")).strip()
                res = self._vm.send_digits(digits, in_call=bool(params.get("in_call", False)))
                # `success` here means the modem accepted the command. It is not
                # proof a digit was emitted, and the payload says so.
                return {"success": bool(res.get("ok")), "port": self.fx_port,
                        "digits": digits, "strategy": res.get("strategy"),
                        "command": res.get("command"),
                        "verified": False,
                        "verified_note": "accepted by the modem; not proof a digit reached the far end",
                        "reason": res.get("reason", "")}

            if cmd == "ring":
                res = self._vm.wait_ring(self._as_int(params, "timeout", int(RING_TIMEOUT)))
                return {"success": bool(res["ringing"]), "port": self.fx_port,
                        "ringing": res["ringing"], "line": res["line"], "seen": res["seen"]}

            if cmd == "selftest":
                rows = self._vm.selftest()
                passed = sum(1 for r in rows if r[1])
                return {"success": passed == len(rows), "passed": passed,
                        "total": len(rows),
                        "results": [{"name": n, "ok": o, "detail": d} for n, o, d in rows]}

            if cmd == "audio":
                res = self._vm.probe_audio()
                return {"success": bool(res["host_audio"]), "port": self.fx_port,
                        "line_codecs": res["line_codecs"],
                        "host_audio_devices": res["host_audio_devices"],
                        "note": ("voice audio is not exposed to the host; record/playback "
                                 "needs line-side hardware, not more software"
                                 if not res["host_audio"] else "ALSA device present")}

            if cmd == "status":
                return self._ok(**self._vm.status())

            if cmd == "reset":
                res = self._vm.reset()
                return {"success": bool(res["ok"]), "port": self.fx_port, "steps": res["steps"]}

            if cmd == "dtmf_probe":
                results = self._vm.probe_dtmf(in_call=bool(params.get("in_call", False)))
                accepted = [r for r in results if r.get("accepted")]
                return {"success": bool(accepted), "port": self.fx_port,
                        "results": results, "accepted": len(accepted),
                        "strategy": self._vm.dtmf.describe()}

            return self._fail(f"unknown command: {command}")

        except ATError as exc:
            return self._fail(str(exc))
        except Exception as exc:  # never let a modem fault kill a run
            return self._fail(f"{type(exc).__name__}: {exc}")

    def _press_key(self, params: Dict[str, Any]) -> Dict[str, Any]:
        key = str(params.get("key", "")).strip().upper()
        mapped = KEY_MAP.get(key)
        if mapped is None:
            return self._fail(f"unknown key: {key}", known_keys=sorted(KEY_MAP))
        merged = dict(mapped["params"])
        merged.update(params)
        merged.pop("key", None)
        return self.execute_command(mapped["command"], merged)

    # -- base-class surface ------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        try:
            return self._ok(**self._vm.status())
        except Exception as exc:
            return self._fail(str(exc))

    def disconnect(self) -> bool:
        # There is no persistent connection: the port is opened per operation,
        # precisely so a long-lived vpt-host cannot hold /dev/fx1 against the
        # script that wants to place a call.
        self.is_connected = True
        return True

    def __repr__(self):
        return f"<FXRemoteController {self.device_name} {self.fx_port}>"