"""
ATChannel — a raw AT conversation over one serial line.

The transport for the FX voice modem (TASK-71). Deliberately thin: send a
command, read until OK/ERROR or the timeout, and say nothing about telephony.
Everything above this file works with whatever comes back.

Design points that are not obvious:

* **pyserial is imported lazily, inside open().** The host imports this module
  while it builds every device's controllers; a missing pyserial must not turn
  into an ImportError at startup that takes down unrelated devices. The error
  is raised when someone actually tries to talk to a modem, with the fix in it.

* **A command that gets no reply is a failure, not an empty success.** The
  commonest bench faults are wrong baud, no dialout membership, or another
  process holding the port, and all three look identical to "the modem is
  quiet". Returning an empty string would let those pass as success.

* **The port is opened read-write by pyserial**, which sets raw mode. That is
  what lets a command and its reply share one descriptor; `printf AT | cat
  /dev/fx1` writes nowhere, because cat reads the named file and ignores stdin.

* **A firmware echo of the command is dropped.** Some modems echo what they are
  sent before answering, and it would otherwise become the first line of every
  reply.
"""

from __future__ import annotations

import re
import time
from typing import Iterable, List, Optional, Tuple

BAUD = 115200

# Timeout policy, in one place so a test can reason about it.
DEFAULT_TIMEOUT = 3.0     # a plain query
DTMF_TIMEOUT = 4.0        # tone generation can be slow on this firmware
DIAL_TIMEOUT = 30.0       # ATA / ATDT can block while the line rings
CONNECT_TIMEOUT = 30.0    # wait for CONNECT after dialling
RING_TIMEOUT = 60.0       # waiting for someone to call us

# Final replies that end a command, and unsolicited codes worth surfacing.
_TERMINATORS = ("OK", "ERROR")
_HARD_FAILURES = ("NO CARRIER", "BUSY", "NO ANSWER", "NO DIALTONE", "CONNECT")


class ATError(Exception):
    """The modem answered ERROR, or said nothing at all."""


class ATChannel:
    """One serial line to one modem. Not thread-safe — callers serialise."""

    def __init__(
        self,
        port: str,
        timeout: float = DEFAULT_TIMEOUT,
        baud: int = BAUD,
        verbose: bool = False,
    ):
        self.port = port
        self.timeout = timeout
        self.baud = baud
        self.verbose = verbose
        self._s = None

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> "ATChannel":
        if self._s is not None:
            return self
        try:
            import serial  # pyserial, imported lazily on purpose
        except ImportError:
            raise ATError(
                "pyserial is not installed for this python.\n"
                "  Debian: sudo apt-get install -y python3-serial\n"
                f"  venv:   {self._interpreter_hint()}"
            )
        try:
            self._s = serial.Serial(self.port, self.baud, timeout=0.2, write_timeout=2)
        except Exception as exc:
            raise ATError(f"cannot open {self.port}: {exc}")
        # Give the modem a moment to settle, then drop anything it said while
        # opening (boot banner, a reply to a previous process's command).
        time.sleep(0.3)
        self.drain()
        return self

    def close(self):
        if self._s is not None:
            try:
                self._s.close()
            except Exception:
                pass
            self._s = None

    def __enter__(self) -> "ATChannel":
        return self.open()

    def __exit__(self, *exc):
        self.close()

    @property
    def is_open(self) -> bool:
        return self._s is not None

    def _log(self, direction: str, text: str):
        if self.verbose:
            print(f"    {direction} {text}")

    @staticmethod
    def _interpreter_hint() -> str:
        import sys
        return f"{sys.executable} -m pip install pyserial"

    # -- reading -----------------------------------------------------------

    def _read_lines(self, deadline: float):
        """Yield stripped lines until the deadline."""
        while time.time() < deadline:
            raw = self._s.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if line:
                self._log("<", line)
                yield line

    def drain(self, seconds: float = 0.4) -> str:
        """Throw away pending output. Returns what was dropped."""
        if self._s is None:
            return ""
        deadline = time.time() + seconds
        buf = []
        for line in self._read_lines(deadline):
            buf.append(line)
            if line in _TERMINATORS:
                break
        return "\n".join(buf)

    def drain_ring(self):
        """Flush pending unsolicited lines (a RING that arrived between calls)."""
        if self._s is not None:
            try:
                self._s.reset_input_buffer()
            except Exception:
                pass

    # -- commands ----------------------------------------------------------

    def command(self, cmd: str, timeout: Optional[float] = None) -> str:
        """Send a command; return the reply without the trailing OK/ERROR.

        Raises ATError on ERROR, on a hard call-failure code, or on silence.
        """
        if self._s is None:
            raise ATError("channel is not open")
        timeout = timeout or self.timeout
        self._s.write((cmd + "\r\n").encode())
        self._s.flush()
        self._log(">", cmd)

        deadline = time.time() + timeout
        lines: List[str] = []
        for line in self._read_lines(deadline):
            if line.upper() == cmd.upper():
                continue          # firmware echo
            if line in _TERMINATORS:
                if line == "ERROR":
                    raise ATError(f"{cmd} -> ERROR")
                return "\n".join(lines).strip()
            if line.startswith("+CME ERROR"):
                raise ATError(f"{cmd} -> {line}")
            if line in _HARD_FAILURES:
                # A call-state result is information, not an AT failure: it is
                # the answer to "did the call connect", not "did the modem
                # understand me". Let the caller read it.
                return "\n".join(lines + [line]).strip()
            lines.append(line)
        raise ATError(f"{cmd} -> no reply within {timeout}s")

    def try_command(self, cmd: str, timeout: Optional[float] = None) -> Tuple[bool, str]:
        """Like command() but returns (ok, reply_or_reason). Never raises."""
        try:
            return True, self.command(cmd, timeout)
        except ATError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    def wait_for(self, patterns: Iterable[str], timeout: float) -> Tuple[Optional[str], List[str]]:
        """Wait for an unsolicited line (RING, CONNECT, NO CARRIER...).

        These arrive between commands, never as a reply to one, so they cannot
        be read with command(). Returns (matched_line_or_None, everything seen).
        """
        if self._s is None:
            raise ATError("channel is not open")
        deadline = time.time() + timeout
        seen: List[str] = []
        compiled = [re.compile(p, re.I) for p in patterns]
        for line in self._read_lines(deadline):
            seen.append(line)
            for rx in compiled:
                if rx.search(line):
                    return line, seen
        return None, seen

    # -- convenience -------------------------------------------------------

    def fingerprint(self) -> str:
        """The firmware string, for logging which modem answered."""
        return self.command("ATI3")