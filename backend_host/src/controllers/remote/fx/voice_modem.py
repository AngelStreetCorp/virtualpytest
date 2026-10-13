"""
VoiceModem — one USB voice modem as a telephone line.

The modem layer. It owns the AT dialogue and the line state, and it is the only
place in the codebase that knows what `+VLS` means. Above this file, code calls
`dial`, `send_digits`, `hangup`; below it, there is a serial port.

Ported from `setup/local/linux/backend_host/fixnet_bench_test.py` (TASK-71 step
1), which had already been exercised against a simulated CX93001. The bench
script imports this class rather than keeping its own copy, so there is exactly
one implementation.

Port identity
-------------
`port` is whatever the udev rule names it: `/dev/fx1`..`/dev/fx4` on a Fixnet
rack, `/dev/fixnet/modemN` for the port-indexed view. Never `/dev/ttyACM*`:
cdc_acm assigns that in USB enumeration order, so the number silently changes
across reboots and a call can end up on the wrong line.

Connection model
----------------
The serial port is opened per operation and closed again, under a lock. The
modem keeps the call itself regardless of whether the port is open — AT is a
command channel, not the session — so a call spanning many `execute_command`
calls survives. Closing between operations is what stops a long-lived
`vpt-host` from permanently squatting on `/dev/fx1` and blocking the script
subprocess that actually places the call.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

from .at_channel import (
    ATChannel,
    ATError,
    CONNECT_TIMEOUT,
    DEFAULT_TIMEOUT,
    DIAL_TIMEOUT,
    DTMF_TIMEOUT,
    RING_TIMEOUT,
)
from .dtmf import DtmfStrategy

DEFAULT_MODEM_DIR = "/dev/fixnet"


class VoiceModem:
    """One modem in voice mode."""

    def __init__(
        self,
        port: str,
        timeout: float = DEFAULT_TIMEOUT,
        verbose: bool = False,
        name: str = "fx",
    ):
        self.port = port
        self.timeout = timeout
        self.verbose = verbose
        self.name = name
        self.dtmf = DtmfStrategy(port)
        self._lock = threading.RLock()
        self._state = "unknown"

    # -- construction ------------------------------------------------------

    @classmethod
    def from_env(cls, index: int, env=None, verbose: bool = False) -> "VoiceModem":
        """Build from `DEVICE{index}_FX_PORT`, falling back to the index name."""
        import os
        env = env or os.environ
        port = env.get(f"DEVICE{index}_FX_PORT") or os.path.join(
            DEFAULT_MODEM_DIR, f"modem{max(index - 1, 0)}"
        )
        name = env.get(f"DEVICE{index}_NAME") or f"fx{index}"
        return cls(port, verbose=verbose, name=name)

    # -- low-level ---------------------------------------------------------

    def _open(self) -> ATChannel:
        port = (self.port or "").strip()
        if not port:
            raise ATError(
                "no modem port configured — set DEVICE{i}_FX_PORT in the backend_host .env "
                "(/dev/fx1..fx4), or pass fx_port"
            )
        if not os.path.exists(port):
            # Deliberately not a `startswith("/dev/")` test: a bench port can be
            # a pty or a socat link, and pyserial opens either fine. What must be
            # caught is an unset or misspelt DEVICE{i}_FX_PORT, which would
            # otherwise surface as an opaque pyserial error much later.
            raise ATError(
                f"{port} does not exist — check setup/local/linux/backend_host/"
                "install_fixnet_prereqs.sh and the udev names (/dev/fx1..fx4)"
            )
        return ATChannel(port, self.timeout, verbose=self.verbose).open()

    @property
    def locked(self) -> bool:
        """True when something else already holds the port."""
        import os
        try:
            os.stat(self.port)
            return False
        except OSError:
            return True

    # -- session -----------------------------------------------------------

    def enter_voice_mode(self, channel: Optional[ATChannel] = None) -> bool:
        """FCLASS=8 then VLS=1. Without Class 8 the +V commands are not parsed."""
        own = channel is None
        channel = channel or self._open()
        try:
            ok, reply = channel.try_command("AT+FCLASS=8")
            if not ok:
                raise ATError(f"cannot enter voice mode: {reply}")
            ok, _ = channel.try_command("AT+VLS=1")
            if not ok:
                # Some firmware rejects VLS until the class change has taken.
                channel.try_command("AT+FCLASS=8", timeout=DTMF_TIMEOUT)
                ok, reply = channel.try_command("AT+VLS=1")
                if not ok:
                    raise ATError(f"VLS rejected after re-entering voice mode: {reply}")
            self._state = "voice"
            return True
        finally:
            if own:
                channel.close()

    def selftest(self) -> List[Tuple[str, bool, str]]:
        """The PoC battery. No line required. Returns (name, ok, detail)."""
        results: List[Tuple[str, bool, str]] = []
        with self._lock:
            ch = self._open()
            try:
                ok, detail = ch.try_command("AT")
                results.append(("AT", ok, detail.replace("\n", " ")[:70]))
                ok, detail = ch.try_command("ATI3")
                results.append(("firmware", ok, detail.replace("\n", " ")[:70]))
                ok, classes = ch.try_command("AT+FCLASS=?")
                voice = ok and "8" in [c.strip() for c in classes.split(",")]
                results.append(("FCLASS offers 8 (voice)", voice,
                                classes.replace("\n", " ")[:70]))
                ok, _ = ch.try_command("AT+FCLASS=8")
                results.append(("enter voice mode", ok, "" if ok else "rejected"))
                ok, line = ch.try_command("AT+VLS?")
                results.append(("VLS reads back", ok and line.strip() == "1",
                                f"VLS={line.strip()}"))
                ok, codecs = ch.try_command("AT+VSM=?")
                n = len([l for l in codecs.splitlines() if l.strip()])
                results.append(("VSM audio codecs", ok and n > 0, f"{n} codec line(s)"))
                ok, hang = ch.try_command("AT+VNH?")
                results.append(("VNH hang-up control", ok, f"VNH={hang.strip()}"))
            finally:
                ch.close()
        return results

    # -- line state --------------------------------------------------------

    def off_hook(self, channel: Optional[ATChannel] = None) -> bool:
        """ATA answers the line; on FXS this goes off-hook and should give tone."""
        own = channel is None
        channel = channel or self._open()
        try:
            ok, reply = channel.try_command("ATA", timeout=DIAL_TIMEOUT)
            if not ok:
                raise ATError(f"ATA (off-hook) failed: {reply}")
            self._state = "off_hook"
            return True
        finally:
            if own:
                channel.close()

    def on_hook(self, channel: Optional[ATChannel] = None) -> bool:
        """+VNH=1 is the documented hang-up; the dial command is the fallback."""
        own = channel is None
        channel = channel or self._open()
        try:
            ok, _ = channel.try_command("AT+VNH=1")
            if not ok:
                channel.try_command("ATH")
            self._state = "on_hook"
            return True
        finally:
            if own:
                channel.close()

    def dial(self, number: str, timeout: float = DIAL_TIMEOUT,
             channel: Optional[ATChannel] = None) -> bool:
        """ATDT<number>; — the semicolon returns the modem to command mode
        instead of staying in voice for the whole call."""
        if not number:
            raise ATError("refusing to dial an empty number")
        own = channel is None
        channel = channel or self._open()
        try:
            ok, reply = channel.try_command(f"ATDT{number};", timeout=timeout)
            if not ok:
                raise ATError(f"dial {number} failed: {reply}")
            self._state = "dialling"
            return True
        finally:
            if own:
                channel.close()

    def wait_connected(self, timeout: float = CONNECT_TIMEOUT) -> Dict:
        """Wait for CONNECT on an open channel."""
        ch = self._open()
        try:
            line, seen = ch.wait_for([r"^CONNECT"], timeout)
            self._state = "connected" if line else "no_answer"
            return {"connected": line is not None, "line": line, "seen": seen}
        finally:
            ch.close()

    def wait_ring(self, timeout: float = RING_TIMEOUT) -> Dict:
        ch = self._open()
        try:
            ch.drain_ring()
            line, seen = ch.wait_for([r"^RING"], timeout)
            return {"ringing": line is not None, "line": line, "seen": seen}
        finally:
            ch.close()

    def hangup(self) -> bool:
        with self._lock:
            ch = self._open()
            try:
                ok, _ = ch.try_command("AT+VNH=1")
                if not ok:
                    ch.try_command("ATH")
                time.sleep(0.3)
                ch.drain_ring()
                self._state = "on_hook"
                return True
            finally:
                ch.close()

    # -- DTMF --------------------------------------------------------------

    def send_digits(self, digits: str, in_call: bool = False) -> Dict:
        """Send DTMF. See dtmf.py: accepted != verified."""
        with self._lock:
            ch = self._open()
            try:
                self.enter_voice_mode(ch)
                return self.dtmf.send(ch, digits, in_call=in_call)
            finally:
                ch.close()

    def probe_dtmf(self, in_call: bool = False) -> List[Dict]:
        with self._lock:
            ch = self._open()
            try:
                self.enter_voice_mode(ch)
                return self.dtmf.probe(ch, in_call=in_call)
            finally:
                ch.close()

    # -- audio / status ----------------------------------------------------

    def probe_audio(self) -> Dict:
        """What the modem will do on the line, and what the host can hear.

        Two different questions. +VSM lists the ON-LINE codecs; whether that
        audio is exposed to Linux as a sound device is a separate hardware fact.
        A plain USB fax/data modem has a PC-side audio path that may terminate
        in its own analog jacks instead of reaching the host.
        """
        import os
        codecs: List[str] = []
        with self._lock:
            ch = self._open()
            try:
                self.enter_voice_mode(ch)
                ok, reply = ch.try_command("AT+VSM=?")
                if ok:
                    codecs = [l for l in reply.splitlines() if l.strip()]
            finally:
                ch.close()
        devs = sorted(os.listdir("/dev/snd")) if os.path.isdir("/dev/snd") else []
        return {"line_codecs": codecs, "host_audio_devices": devs,
                "host_audio": bool(devs)}

    def status(self) -> Dict:
        info: Dict = {
            "port": self.port,
            "name": self.name,
            "state": self._state,
            "dtmf_strategy": self.dtmf.describe(),
            "dtmf_resolved": self.dtmf.resolved,
        }
        try:
            with self._lock:
                ch = self._open()
                try:
                    ok, fw = ch.try_command("ATI3")
                    if ok:
                        info["firmware"] = fw.strip()
                    ok, line = ch.try_command("AT+VLS?")
                    if ok:
                        info["line"] = line.strip()
                finally:
                    ch.close()
            info["reachable"] = True
        except ATError as exc:
            info["reachable"] = False
            info["error"] = str(exc)
        return info

    def reset(self) -> Dict:
        """Recover a modem stuck off-hook after an aborted call.

        Bounded and idempotent: hang up, re-select the line, re-enter voice
        mode. A modem that needed a USB re-plug to recover is the failure this
        exists to prevent, and the caller counts resets as a stability metric.
        """
        steps: List[Dict] = []
        with self._lock:
            try:
                ch = self._open()
            except ATError as exc:
                return {"ok": False, "steps": [{"step": "open", "ok": False, "error": str(exc)}]}
            try:
                for step, cmd in (("hangup", "AT+VNH=1"), ("line", "AT+VLS=1"),
                                  ("voice", "AT+FCLASS=8")):
                    ok, reply = ch.try_command(cmd, timeout=DTMF_TIMEOUT)
                    steps.append({"step": step, "ok": ok, "reply": reply})
                ch.drain_ring()
                self._state = "on_hook"
            finally:
                ch.close()
        return {"ok": all(s["ok"] for s in steps), "steps": steps}

    def __repr__(self):
        return f"<VoiceModem {self.name} {self.port} state={self._state}>"