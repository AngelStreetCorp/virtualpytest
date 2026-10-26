"""
IRToy Remote Controller Implementation (USB CDC serial transport)

Drives an STB/TV through a **USB IR Toy / Irdroid "Infrared Transceiver" dongle**
(`04d8:fd08`) over its CDC serial node, writing the waveform straight to the port.

This transport exists for **non-Pi hosts** (x86 miniservers such as the Minisforum).
On a Raspberry Pi OS the same dongle is claimed by the kernel `ir_toy` driver, which
publishes `/dev/lirc0` and the existing `IRRemoteController` works unchanged. A stock
Debian/Ubuntu x86 kernel ships neither `CONFIG_IR_TOY` nor `CONFIG_RAW_RC`, so the
dongle is never claimed for IR at all: `cdc_acm` grabs it and it appears as
`/dev/ttyACM0`. lirc's own userspace `irtoy` plugin *can* open that port, but lirc
never gives a userspace driver a character device — it is reachable only through the
lircd socket, whose protocol has no raw-pulse command (`SEND_ONCE/START/STOP` only).
So on x86 there is no node `ir-ctl` can talk to and `IRRemoteController` cannot work.

This controller removes the kernel and lirc from the equation entirely: the IrToy's
protocol is plain text/bytes over a 115200 baud serial link, and the sequence below
mirrors lirc's `plugins/irtoy.c` (`irtoy_enter_samplemode` + `irtoy_send_double_buffered`)
so the timings are encoded exactly the way the hardware expects.

Protocol summary (sampling mode, raw pulse transmit):

1. write ``s``      → read 3 bytes, expect ``S<proto>``
2. write ``0x24`` / ``0x25`` / ``0x26`` (20 ms apart)
3. write ``0x03``   → read 1 byte = how many bytes the dongle can take now
4. stream the big-endian timing buffer in chunks, re-reading that 1-byte credit after
   each chunk (a ``0`` credit means drained)
5. read 4 bytes: ``t <count_hi> <count_lo> C`` — ``t`` = transmit count, ``C`` = success

Each duration is microseconds divided by ``IRTOY_UNIT_US`` (21.3333 µs), truncated,
and terminated by ``0xFF 0xFF``.

Two behaviours copied verbatim from lirc's driver, both load-bearing:

* **Reset on close.** A single ``0x00`` returns the dongle to IRMAN mode. Without it
  the device keeps streaming in sample mode while no tty is open and the *next* open
  fails in cdc_acm — lirc flags this as "vital to return the irtoy to IRMAN mode".
* **Truncation, not rounding**, when converting microseconds to LSBs.

The keymaps are the same raw codes the lirc transport uses (`ir_conf/<ir_type>.json`),
so `IR_TYPE` still selects the frontend skin and nothing in the panel changes. This is
the third IR transport alongside `IRRemoteController` (lirc/ir-ctl) and
`IRTransRemoteController` (networked UDP box), and is selected by `DEVICE{n}_IR_SERIAL`
in the host `.env`.

See docs/agent/devices/INFRARED.md § 2c.
"""

import json
import os
import sys
import time
from typing import Dict, Any, List, Optional, Tuple

from ..base_controller import RemoteControllerInterface
from .ir_keymap import missing_keymap_message

# IrToy is a USB CDC-serial dongle driven through POSIX termios/tty/select — that
# stack is Linux-only (Pi, mini-PCs, lab rigs). On Windows, host_vnc, labox-mobile
# and any other win32 backend host still does `from controllers import *` from
# app.py, so this module has to import cleanly even though the controller is
# never instantiated there. Wrap the POSIX imports; fall back to a Windows baud
# constant (Windows DCB just wants the integer 115200 — there is no
# `termios.B115200` on win32).
if sys.platform == "win32":
    _IRTOY_SUPPORTED = False

    class _TermiosStub:
        B115200 = 115200

    termios = _TermiosStub()  # type: ignore[assignment]
    select = None  # type: ignore[assignment]
    tty = None     # type: ignore[assignment]
else:
    _IRTOY_SUPPORTED = True
    import select
    import termios
    import tty

# ── IrToy wire constants (lirc plugins/irtoy.c) ───────────────────────────────
# The dongle speaks 115200 baud. Always termios.B115200, never the literal 115200 —
# on Linux the baud constants are octal-encoded (B115200 == 4098), so a raw integer
# is an invalid speed and tcsetattr() fails with EINVAL. On Windows the stub
# exposes the literal integer (DCB takes that directly).
IRTOY_BAUD = termios.B115200
IRTOY_UNIT_US = 21.3333          # one LSB of the dongle's timing encoding
IRTOY_LONG_TERM = 0xFFFF         # trailing 0xFF 0xFF ends the burst

CMD_SMODE_ENTER = b's'           # enter sampling mode; replies 'S<proto>'
CMD_RESET = b'\x00'              # back to IRMAN mode (must be sent before close)
# The full IRTOY_COMMAND_TXSTART is four bytes, written contiguously. The "$%&" part
# is NOT a separate "firmware version probe" sent during the handshake — on the
# Irdroid "Infrared Transceiver" firmware, splitting it from the trailing 0x03 and
# 20 ms-gapping the prefix leaves the device parked waiting for the next byte, so
# the next 0x03 (the actual TXSTART) fires its sample buffer and you get an IR burst
# on every health probe. Keep the four bytes glued together.
CMD_TXSTART = b'\x24\x25\x26\x03'

REPLY_SAMPLEMODEPROTO = ord('S')  # reply[0] after CMD_SMODE_ENTER
REPLY_XMITCOUNT = ord('t')        # reply[0] after the last chunk
REPLY_XMITSUCCESS = ord('C')      # reply[3] — 'C' means the burst went out

SAMPLEMODE_REPLY_LEN = 3
XMIT_RESULT_LEN = 4

# Mirrors the driver's timeouts (IRTOY_TIMEOUT_SMODE_ENTER / _READYFORDATA).
HANDSHAKE_TIMEOUT = 1.0
CREDIT_TIMEOUT = 1.0
RESULT_TIMEOUT = 1.0
SMODE_SETTLE_S = 0.1             # driver sleeps 100 ms before reading the reply

MAX_LSB = 0xFFFE                 # 0xFFFF is the terminator, never a duration


class IRToyRemoteController(RemoteControllerInterface):
    """IR remote controller that writes raw pulses to a USB IR Toy over CDC serial."""

    def __init__(self, ir_serial: str = None, ir_type: str = None, **kwargs):
        """
        Initialize the IRToy (USB serial) remote controller.

        Args:
            ir_serial: Serial node of the dongle — prefer the udev symlink
                `/dev/irtoy` over `/dev/ttyACM0`, which changes on replug.
        """
        if not _IRTOY_SUPPORTED:
            raise NotImplementedError(
                "IRToyRemoteController requires POSIX termios (Linux/macOS). "
                f"Current platform is {sys.platform}; use IRRemoteController, "
                "IRTransRemoteController, or a different remote backend."
            )

        super().__init__("IRToy Remote", "infrared")

        self.ir_serial = ir_serial
        self.ir_type = ir_type

        if not self.ir_serial:
            raise ValueError("ir_serial is required for IRToyRemoteController")
        if not self.ir_type:
            raise ValueError("ir_type is required for IRToyRemoteController")

        self.ir_config_path = os.path.join(os.path.dirname(__file__), 'ir_conf')
        self.ir_config_file = f"{self.ir_type}.json"

        self.ir_available_keys: List[str] = []
        self.ir_config_data: Dict[str, str] = {}

        # Serial handle. Always None between presses: see press_key for why the
        # port is opened and closed per burst instead of being held open.
        self._fd: Optional[int] = None

        # Health tracking (drives the Take Control status dot, mirrors infrared.py)
        self._last_send_ok: Optional[bool] = None
        self._last_send_error: Optional[str] = None
        self._last_send_ts: float = 0
        self._health_cache: Optional[Dict[str, Any]] = None
        self._health_cache_ts: float = 0

        print(f"[@controller:IRToyRemote] Initialized for serial device: {self.ir_serial}")
        print(f"[@controller:IRToyRemote] Using config type: {self.ir_type}")

        self.connect()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Load the keymap. Like lirc, this does not test transmission."""
        try:
            ir_config_full_path = os.path.join(self.ir_config_path, self.ir_config_file)
            if not os.path.exists(ir_config_full_path):
                self.connect_error = missing_keymap_message(self.ir_config_path, self.ir_type)
                print(f"Remote[{self.device_type.upper()}]: {self.connect_error}")
                return False

            with open(ir_config_full_path, 'r') as f:
                self.ir_config_data = json.load(f)

            self.ir_available_keys = list(self.ir_config_data.keys())

            if not os.path.exists(self.ir_serial):
                print(f"Remote[{self.device_type.upper()}]: WARNING - IRToy serial device not found: {self.ir_serial}")
                print(f"Remote[{self.device_type.upper()}]: Continuing with config-only mode")

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
        """Close the serial port, returning the dongle to IRMAN mode first."""
        try:
            self._close_port()
            self.ir_available_keys = []
            self.is_connected = False
            print(f"Remote[{self.device_type.upper()}]: Disconnected from {self.device_name}")
            return True
        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Disconnect error: {e}")
            return False

    # ── serial plumbing ──────────────────────────────────────────────────────

    def _read_exact(self, count: int, timeout: float) -> bytes:
        """Read exactly `count` bytes or raise."""
        buf = b''
        deadline = time.monotonic() + timeout
        while len(buf) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"IRToy timed out after {len(buf)}/{count} bytes")
            readable, _, _ = select.select([self._fd], [], [], remaining)
            if not readable:
                raise TimeoutError(f"IRToy timed out after {len(buf)}/{count} bytes")
            chunk = os.read(self._fd, count - len(buf))
            if not chunk:
                raise ConnectionError("IRToy closed the serial port (device unplugged?)")
            buf += chunk
        return buf

    def _write_all(self, data: bytes) -> None:
        """Write every byte of `data`, tolerating short writes."""
        view = memoryview(data)
        while view:
            written = os.write(self._fd, view)
            if written <= 0:
                raise ConnectionError("IRToy serial write failed")
            view = view[written:]

    def _open_port(self) -> None:
        """Open the serial node and put the dongle into sampling mode."""
        if self._fd is not None:
            return

        fd = os.open(self.ir_serial, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            tty.setraw(fd)
            attrs = termios.tcgetattr(fd)
            # Python's termios has no cfsetispeed/cfsetospeed helpers; the speeds go
            # straight into the iflag/oflag slots at index 4 and 5.
            attrs[4] = IRTOY_BAUD  # ispeed
            attrs[5] = IRTOY_BAUD  # ospeed
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:
            os.close(fd)
            raise

        self._fd = fd
        self._enter_sample_mode()

    def _close_port(self) -> None:
        """Reset the dongle to IRMAN mode, then close. Best-effort, never raises."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            os.write(fd, CMD_RESET)
            time.sleep(0.02)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass

    def _drain_input(self) -> None:
        """Read and discard any bytes the firmware has already pushed.

        If the Irdroid was last driven by a *different* kernel driver (e.g. the
        Pi's ``ir_toy`` driver on a previous host) that didn't send a clean
        ``0x00`` IRMAN reset before the cable was unplugged, the firmware can
        still be in sample-mode streaming when the cdc_acm port is opened on
        the new host. Without a drain, our first ``s`` read would land in the
        middle of that stale stream and decode as a non-``'S'`` byte. Read with
        a 100 ms quiet-window so we stop as soon as the firmware is silent
        rather than waiting on the full handshake timeout.
        """
        while True:
            readable, _, _ = select.select([self._fd], [], [], 0.1)
            if not readable:
                return
            try:
                chunk = os.read(self._fd, 4096)
            except Exception:
                return
            if not chunk:
                return

    def _enter_sample_mode(self) -> None:
        """Run the IRMAN reset + 's' handshake. Emits no IR.

        The pre-handshake ``0x00`` is the load-bearing bit. On a clean power-up
        the firmware is already in IRMAN mode and the reset is a no-op; on a
        power-up where the firmware was left in some other state (sample mode,
        transmit mode, or any of the wedged substates documented in BUG-0434)
        the reset forces it back to a known-good IRMAN before we send ``s``.
        Without it, the Irdroid that worked fine on a Raspberry Pi as
        ``/dev/lirc2`` will return malformed replies (or no reply) the moment
        it lands on a non-Pi host where the ``ir_toy`` driver didn't claim it
        first. See BUG-0434.
        """
        # Clear any bytes the firmware pushed before the reset had a chance to
        # land (the Irdroid's sample-mode stream starts immediately on power-up
        # if the previous host didn't reset it).
        self._drain_input()
        self._write_all(CMD_RESET)
        time.sleep(SMODE_SETTLE_S)
        # And drain anything the firmware echoed back in response to the reset
        # before we send ``s``.
        self._drain_input()

        self._write_all(CMD_SMODE_ENTER)
        time.sleep(SMODE_SETTLE_S)

        reply = self._read_exact(SAMPLEMODE_REPLY_LEN, HANDSHAKE_TIMEOUT)
        if reply[0] != REPLY_SAMPLEMODEPROTO:
            raise ConnectionError(
                f"IRToy did not enter sample mode (reply {reply!r}) — "
                f"is {self.ir_serial} really an IR Toy?"
            )

    @staticmethod
    def _encode_durations(raw_code: str) -> bytes:
        """
        Convert a lirc raw code ('+420 -231 ...', microseconds) to the dongle's
        big-endian timing buffer, terminated with 0xFF 0xFF.

        Mirrors lirc: `(lirc_t)(((double)signal) / IRTOY_UNIT)` — a truncating cast,
        not a rounding one, because the hardware grid is 21.3333 µs.
        """
        durations = [abs(int(token)) for token in raw_code.split()]
        if not durations:
            raise ValueError("empty IR code")

        out = bytearray()
        for duration in durations:
            # Truncate toward zero, and never emit 0xFFFF — that is the terminator.
            lsb = int(duration / IRTOY_UNIT_US)
            lsb = max(0, min(lsb, MAX_LSB))
            out += bytes(((lsb >> 8) & 0xFF, lsb & 0xFF))
        out += bytes((0xFF, 0xFF))
        return bytes(out)

    def _transmit(self, payload: bytes) -> None:
        """Push one timing buffer into the dongle, honouring its flow-control credits."""
        self._write_all(CMD_TXSTART)

        # The dongle announces how much room it has; we refill as it drains.
        credit = self._read_exact(1, CREDIT_TIMEOUT)[0]
        sent = 0
        zero_credit_count = 0
        MAX_ZERO_CREDITS = 20  # ~20s of "drained" before we call it a wedge
        while sent < len(payload):
            if credit > 0:
                chunk = payload[sent:sent + credit]
                self._write_all(chunk)
                sent += len(chunk)
                zero_credit_count = 0
            else:
                # credit == 0 is the NORMAL "drained, wait" state, not an error.
                # lirc's irtoy_send_double_buffered handles it the same way: write
                # what we can (possibly 0 bytes), then poll again. Treating 0 as
                # fatal here used to surface as "IRToy reported no transmit buffer
                # space" mid-burst and block the request worker for ~CREDIT_TIMEOUT
                # per credit read, so subsequent health/press calls timed out.
                #
                # Bounded, though: if credit stays 0 across many polls the
                # firmware is genuinely wedged (the Irdroid "0/3 bytes" failure
                # mode), and we must surface that as an error rather than spin.
                # 20 consecutive zero reads at CREDIT_TIMEOUT=1s = ~20 s budget.
                zero_credit_count += 1
                if zero_credit_count > MAX_ZERO_CREDITS:
                    raise ConnectionError(
                        f"IRToy transmit buffer stayed empty for "
                        f"{MAX_ZERO_CREDITS}s ({sent}/{len(payload)} bytes sent) — "
                        f"firmware likely wedged; physical replug required")
            credit = self._read_exact(1, CREDIT_TIMEOUT)[0]

        # NOTE: no extra read here. The loop already consumes the final credit
        # (0 = drained) as its trailing read — that is exactly what lirc's
        # irtoy_send_double_buffered does. Adding a second 1-byte read steals the
        # 't' count indicator, so the 4-byte result arrives shifted and decodes as
        # b'\x00\xNN C\x00' instead of b't\xNN C'. Symptom: NN equals the payload
        # length and C sits one byte early — the burst actually went out.
        reply = self._read_exact(XMIT_RESULT_LEN, RESULT_TIMEOUT)
        if reply[0] != REPLY_XMITCOUNT:
            raise ConnectionError(f"IRToy transmit reply malformed: {reply!r}")
        transmitted = (reply[1] << 8) | reply[2]
        if transmitted != len(payload):
            raise ConnectionError(
                f"IRToy transmitted {transmitted} bytes, expected {len(payload)}")
        if reply[3] != REPLY_XMITSUCCESS:
            raise ConnectionError(f"IRToy transmit error status {reply[3]:#04x}")

    # ── commands ─────────────────────────────────────────────────────────────

    def press_key(self, key: str) -> bool:
        """Send a single IR key press as a raw waveform burst."""
        if not self.is_connected:
            print(f"Remote[{self.device_type.upper()}]: ERROR - Not connected")
            self._record_send(False, 'IRToy remote not connected')
            return False

        key_upper = key.upper()
        raw_code = self.ir_config_data.get(key_upper)
        if not raw_code:
            # Mirrors infrared.py: an empty value in ir_conf means "not mapped".
            print(f"Remote[{self.device_type.upper()}]: Key '{key_upper}' not found in {self.ir_config_file}")
            self._record_send(False, f"Key {key_upper} not in {self.ir_config_file}")
            return False

        print(f"Remote[{self.device_type.upper()}]: Sending {key_upper} via IRToy")

        try:
            payload = self._encode_durations(raw_code)
            # The port is opened and closed per press, deliberately.
            #
            # Keeping the fd open between presses looks faster and is what lirc
            # does, but it makes the dongle fragile here: sample mode streams, and
            # if the service is restarted or killed while the fd is open, the IRMAN
            # reset never reaches the device and it stays deaf — the next open then
            # times out and only a physical replug recovers it. That happened on a
            # real host. The ~160 ms handshake is cheap next to the 300 ms
            # inter-press delay VPT already imposes on IR.
            self._open_port()
            try:
                self._transmit(payload)
            finally:
                # Always return the dongle to IRMAN mode, on success and on failure.
                self._close_port()

            self._record_send(True)
            return True

        except Exception as e:
            print(f"Remote[{self.device_type.upper()}]: Failed to send IRToy code: {e}")
            self._record_send(False, str(e))
            # Never leave a half-open handle behind.
            self._close_port()
            return False

    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute IRToy remote command.

        Args:
            command: Command to execute ('press_key', 'get_pairing_status', 'get_status')
            params: Command parameters

        Returns:
            Dict[str, Any]: Dict with 'success' key indicating command execution status
        """
        if params is None:
            params = {}

        print(f"Remote[{self.device_type.upper()}]: Executing command '{command}' with params: {params}")

        key = None
        if command == 'press_key':
            key = params.get('key')
            success = self.press_key(key) if key else False
        elif command in ('get_pairing_status', 'get_status'):
            # Same command name the Take Control status-dot pipeline polls.
            return {'success': True, 'status': self.get_ir_health()}
        else:
            print(f"Remote[{self.device_type.upper()}]: Unknown command: {command}")
            success = False

        if success:
            return {'success': True}
        return {'success': False, 'error': self._last_send_error if key else 'No key given'}

    def _record_send(self, ok: bool, error: str = None) -> None:
        """Record the outcome of the most recent IR send (feeds the status dot)."""
        self._last_send_ok = ok
        self._last_send_error = None if error is None and ok else (error or 'IRToy send failed')
        self._last_send_ts = time.time()

    # ── health ───────────────────────────────────────────────────────────────

    def _probe(self) -> Tuple[bool, Optional[str]]:
        """
        Non-destructive probe: open the port and run the sample-mode handshake.

        This is the IRToy equivalent of `ir-ctl --features` — it proves the dongle is
        present and the firmware answers, and transmits nothing. The port is closed
        again (with the IRMAN reset) so the probe never leaves the device streaming.
        """
        if not os.path.exists(self.ir_serial):
            return False, f'IRToy device {self.ir_serial} missing'

        was_open = self._fd is not None
        if was_open:
            # A press was interrupted mid-flight; drop the handle and probe clean.
            self._close_port()
        try:
            self._open_port()
            return True, None
        except FileNotFoundError:
            return False, f'IRToy device {self.ir_serial} missing'
        except PermissionError:
            return False, (f'permission denied opening {self.ir_serial} '
                           f'(service user must be in the dialout group)')
        except TimeoutError as e:
            return False, f'IRToy handshake timed out: {e}'
        except Exception as e:
            return False, f'IRToy not responding: {e}'
        finally:
            # The probe always leaves no handle behind: sample mode streams, so a
            # port left open with the reset unsent is what wedges the dongle.
            self._close_port()

    def get_ir_health(self) -> Dict[str, Any]:
        """
        Health for the Take Control status dot, shaped exactly like
        IRRemoteController.get_ir_health() so the frontend cannot tell the
        transports apart.
        """
        now = time.time()
        if self._health_cache is not None and (now - self._health_cache_ts) < 5:
            cached = dict(self._health_cache)
            cached['last_send_ok'] = self._last_send_ok
            cached['last_send_error'] = self._last_send_error
            cached['last_send_ts'] = self._last_send_ts
            return cached

        device_present = bool(self.ir_serial) and os.path.exists(self.ir_serial)
        tx_probe_ok, probe_error = self._probe()

        healthy = device_present and tx_probe_ok and self._last_send_ok is not False

        if not device_present:
            detail = f'IRToy device {self.ir_serial} missing'
        elif not tx_probe_ok:
            detail = f'IR transmitter not responding: {probe_error}'
        elif self._last_send_ok is False:
            detail = f'Last IR key press failed: {self._last_send_error}'
        else:
            detail = f'IR ready ({self.ir_serial}, {self.ir_type}, irtoy)'

        status = {
            'ir_path': self.ir_serial,
            'ir_type': self.ir_type,
            'transport': 'irtoy',
            'device_present': device_present,
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

    def get_health(self) -> Dict[str, Any]:
        """Alias matching IRTransRemoteController.get_health()."""
        return self.get_ir_health()

    # ── introspection ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get controller status information."""
        return {
            'success': True,
            'controller_type': self.controller_type,
            'device_type': self.device_type,
            'device_name': self.device_name,
            'ir_path': self.ir_serial,
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
        """Get available actions from the loaded IR keymap JSON."""
        if not self.ir_config_data:
            raise ValueError(f"No IR config loaded for {self.ir_type}")

        actions = []
        for key_name in self.ir_config_data.keys():
            if not self.ir_config_data[key_name]:
                continue
            actions.append({
                'id': f'ir_press_key_{key_name.lower()}',
                'label': f'{key_name}',
                'command': 'press_key',
                'action_type': 'remote',
                'params': {'key': key_name},
                'description': f'Press {key_name} key via infrared',
                'requiresInput': False
            })

        return {'remote': actions}