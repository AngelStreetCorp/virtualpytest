"""Unit tests for the FX voice modem remote (TASK-71). No device required.

The modem is simulated on a pty: a background thread answers AT commands with the
responses the real CX93001-EIS firmware gives, including the part that matters —
ERROR to every documented +VTS form. That makes the DTMF assertions real rather
than mocked, because the behaviour under test IS the modem's answer.

The two claims this file exists to keep honest:

  * `send_digits` reports success when the modem ACCEPTS a command, and always
    reports `verified: False`, because "the modem took it" is not "a digit was
    heard at the far end".
  * the capability resolves for `fx_dongle` without any edit to the seven-slot
    capability builder — the whole reason fx reuses the `remote` slot.
"""

from __future__ import annotations

import os
import pty
import threading
import time

import pytest

# pyserial is a real runtime dependency of the FX controller (see
# backend_host/requirements.txt) but it is not needed by a host that has no FX
# dongle, so a CI runner without it should skip rather than fail.
serial = pytest.importorskip("serial", reason="pyserial not installed (apt: python3-serial)")

from backend_host.src.controllers.remote.fx import (
    ATChannel,
    ATError,
    CANDIDATES,
    DtmfStrategy,
    FXRemoteController,
    KEY_MAP,
    VoiceModem,
    tone_pair_for,
)
from shared.src.lib.config.device_capabilities import get_device_capabilities

CX_FIRMWARE = "CX93001-EIS_V0.2013-V92"
VSM_REPLY = (
    '0,"SIGNED PCM",8,0,8000,0,0',
    '1,"UNSIGNED PCM",8,0,8000,0,0',
    '129,"IMA ADPCM",4,0,8000,0,0',
    '131,"Mu-Law",8,0,8000,0,0',
    '132,"A-Law",8,0,8000,0,0',
)


class FakeCX93001:
    """A CX93001 on a pty. `accept_vts` is the one +VTS form it tolerates."""

    def __init__(self, accept_vts: str = "", silent: bool = False):
        self.accept_vts = accept_vts
        self.silent = silent
        self.received = []
        self.master, self.slave = pty.openpty()
        self.port = os.ttyname(self.slave)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        try:
            os.close(self.master)
        except OSError:
            pass

    @staticmethod
    def _same_form(a: str, b: str) -> bool:
        """Same AT syntax, ignoring the numbers that carry the payload."""
        import re
        return re.sub(r"\d+", "#", a) == re.sub(r"\d+", "#", b)

    def _reply(self, cmd: str) -> str:
        u = cmd.strip().upper()
        if u in ("", "AT"):
            return "\r\nOK\r\n"
        if u.startswith("ATI"):
            return f"\r\n{CX_FIRMWARE}\r\n\r\nOK\r\n"
        if u.startswith("AT+FCLASS=?"):
            return "\r\n0,1,1.0,2,8\r\n\r\nOK\r\n"
        if u.startswith("AT+FCLASS"):
            return "\r\nOK\r\n"
        if u.startswith("AT+VLS=?"):
            return "\r\n0,\" \",0000000000,0000000000,B084008000\r\n\r\nOK\r\n"
        if u == "AT+VLS?":
            return "\r\n1\r\n\r\nOK\r\n"
        if u.startswith("AT+VLS"):
            return "\r\nOK\r\n"
        if u.startswith("AT+VSM=?"):
            return "\r\n" + "\r\n".join(VSM_REPLY) + "\r\n\r\nOK\r\n"
        if u.startswith("AT+VSM"):
            return "\r\nOK\r\n"
        if u.startswith("AT+VNH=?"):
            return "\r\n0\r\n\r\nOK\r\n"
        if u == "AT+VNH?":
            return "\r\n0\r\n\r\nOK\r\n"
        if u.startswith("AT+VNH"):
            return "\r\nOK\r\n"
        # The real firmware answers ERROR to all of these. A modem that
        # tolerates one form tolerates that SYNTAX, not one frozen string: the
        # tone pair changes with every digit, so the comparison is on shape.
        if u.startswith("AT+VTS") or u.startswith("AT+VDTMF"):
            if self.accept_vts and self._same_form(cmd.strip(), self.accept_vts):
                return "\r\nOK\r\n"
            return "\r\nERROR\r\n"
        if u.startswith("ATA"):
            return "\r\nOK\r\n"
        if u.startswith("ATD"):
            return "\r\nOK\r\n"
        return "\r\nERROR\r\n"

    def _serve(self):
        buf = b""
        while not self._stop.is_set():
            try:
                import select
                r, _, _ = select.select([self.master], [], [], 0.1)
            except (OSError, ValueError):
                return
            if not r:
                continue
            try:
                data = os.read(self.master, 256)
            except OSError:
                return
            if not data:
                continue
            buf += data
            while b"\r" in buf:
                raw, buf = buf.split(b"\r", 1)
                cmd = raw.decode(errors="replace").replace("\n", "").strip()
                if not cmd:
                    continue
                self.received.append(cmd)
                if self.silent:
                    continue
                try:
                    os.write(self.master, self._reply(cmd).encode())
                except OSError:
                    return


@pytest.fixture
def modem():
    m = FakeCX93001()
    yield m
    m.close()


@pytest.fixture
def permissive_modem():
    """A modem that accepts one +VTS form, so a working strategy can be seen."""
    m = FakeCX93001(accept_vts="AT+VTS=[697,1209,50]")
    yield m
    m.close()


# --------------------------------------------------------------------------
# capability resolution — the reason fx reuses `remote`
# --------------------------------------------------------------------------

def test_fx_dongle_capability_resolves_without_a_builder_edit():
    caps = get_device_capabilities("fx_dongle")
    assert caps["remote"] == "fx"
    # No av: it is a telephone line, not a screen.
    assert caps["av"] is None


def test_unknown_model_still_defaults_to_the_seven_slots():
    # Guards the reason we did NOT add an eighth slot: this default is hardcoded
    # and a new capability type would have needed an edit here.
    caps = get_device_capabilities("no_such_model_xyz")
    assert set(caps) >= {"av", "remote", "desktop", "web", "power", "switch"}


# --------------------------------------------------------------------------
# ATChannel
# --------------------------------------------------------------------------

def test_command_returns_reply_without_the_ok(modem):
    with ATChannel(modem.port, timeout=2) as ch:
        assert ch.command("AT+FCLASS=?") == "0,1,1.0,2,8"


def test_error_raises_at_error(modem):
    with ATChannel(modem.port, timeout=2) as ch:
        with pytest.raises(ATError, match="ERROR"):
            ch.command("AT+VTS=1")


def test_silence_is_a_failure_not_an_empty_success():
    """The commonest bench faults look identical to a quiet modem. Returning an
    empty string would let wrong-baud / no-dialout / port-held pass as success."""
    quiet = FakeCX93001(silent=True)
    try:
        with ATChannel(quiet.port, timeout=1) as ch:
            with pytest.raises(ATError, match="no reply"):
                ch.command("AT")
    finally:
        quiet.close()


def test_try_command_never_raises(modem):
    with ATChannel(modem.port, timeout=1) as ch:
        ok, reply = ch.try_command("AT+VTS=1")
        assert ok is False and "ERROR" in reply
        ok, reply = ch.try_command("AT")
        assert ok is True and reply == ""


def test_firmware_echo_is_dropped(modem):
    modem._reply = lambda cmd: (modem.received.append(cmd), "\r\nAT\r\n\r\nOK\r\n")[1]
    with ATChannel(modem.port, timeout=2) as ch:
        assert ch.command("AT") == ""


# --------------------------------------------------------------------------
# VoiceModem
# --------------------------------------------------------------------------

def test_selftest_passes_every_check(modem):
    rows = VoiceModem(modem.port, timeout=2).selftest()
    failed = [r for r in rows if not r[1]]
    assert not failed, f"failed: {failed}"
    assert len(rows) == 7


def test_a_missing_port_says_so_instead_of_opening_something():
    vm = VoiceModem("/dev/does-not-exist-xyz")
    with pytest.raises(ATError, match="does not exist"):
        vm.selftest()


def test_an_unset_port_names_the_env_var_that_sets_it():
    """An unset DEVICE{i}_FX_PORT must say which key fixes it."""
    vm = VoiceModem("")
    with pytest.raises(ATError, match="DEVICE"):
        vm.selftest()


def test_a_port_outside_dev_is_allowed(modem):
    """Regression: an earlier guard refused anything not under /dev/, which
    would break the pty-based tests and any socat-style bench port. The check
    that matters is 'the path exists', not 'the path starts with /dev/'."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alias = os.path.join(tmp, "fx1")
        os.symlink(modem.port, alias)
        vm = VoiceModem(alias, timeout=2)
        assert not [r for r in vm.selftest() if not r[1]]


def test_line_state_transitions(modem):
    vm = VoiceModem(modem.port, timeout=2)
    vm.off_hook()
    assert vm._state == "off_hook"
    vm.dial("5551234")
    assert vm._state == "dialling"
    vm.hangup()
    assert vm._state == "on_hook"


def test_dial_refuses_an_empty_number(modem):
    vm = VoiceModem(modem.port, timeout=2)
    with pytest.raises(ATError, match="empty number"):
        vm.dial("")


def test_status_reports_firmware_and_reachable(modem):
    st = VoiceModem(modem.port, timeout=2).status()
    assert st["reachable"] is True
    assert CX_FIRMWARE in st["firmware"]
    assert st["port"] == modem.port


def test_status_on_a_missing_port_is_reported_not_raised():
    st = VoiceModem("/dev/does-not-exist-xyz").status()
    assert st["reachable"] is False and "error" in st


def test_reset_is_idempotent(modem):
    vm = VoiceModem(modem.port, timeout=2)
    first, second = vm.reset(), vm.reset()
    assert first["ok"] and second["ok"]
    assert [s["step"] for s in first["steps"]] == ["hangup", "line", "voice"]


def test_audio_probe_separates_line_codecs_from_host_audio(modem):
    res = VoiceModem(modem.port, timeout=2).probe_audio()
    assert len(res["line_codecs"]) == len(VSM_REPLY)
    # The +VSM codecs say nothing about whether the host can hear them.
    assert res["host_audio"] is False


# --------------------------------------------------------------------------
# DTMF — goal 2
# --------------------------------------------------------------------------

def test_tone_pair_for_maps_the_dtmf_grid():
    assert tone_pair_for("1") == (697, 1209)
    assert tone_pair_for("5") == (770, 1336)
    assert tone_pair_for("#") == (941, 1477)
    assert tone_pair_for("z") is None


def test_probe_finds_nothing_when_the_modem_accepts_nothing(modem):
    """This is the real CX93001 behaviour: +VTS is advertised, every form errors."""
    vm = VoiceModem(modem.port, timeout=2)
    results = vm.probe_dtmf()
    assert all(r["accepted"] is not True for r in results)
    assert vm.dtmf.resolved is False


def test_probe_finds_the_form_the_modem_accepts(permissive_modem):
    vm = VoiceModem(permissive_modem.port, timeout=2)
    vm.probe_dtmf()
    assert vm.dtmf.resolved is True
    assert vm.dtmf.chosen.label == "tone pair bracketed"


def test_probe_skips_in_call_dialling_while_on_hook(modem):
    results = VoiceModem(modem.port, timeout=2).probe_dtmf(in_call=False)
    skipped = [r for r in results if r["accepted"] is None]
    assert skipped and all("in-call" in r["label"] or "dial" in r["label"] for r in skipped)


def test_send_digits_reports_failure_when_nothing_is_accepted(modem):
    res = VoiceModem(modem.port, timeout=2).send_digits("1")
    assert res["ok"] is False
    assert res["verified"] is False


def test_send_digits_never_claims_verified(permissive_modem):
    """Accepted by the modem is NOT proof a digit reached the far end."""
    res = VoiceModem(permissive_modem.port, timeout=2).send_digits("1")
    assert res["ok"] is True
    assert res["verified"] is False


def test_send_digits_reuses_the_accepted_form_verbatim(permissive_modem):
    """Regression: probing the bracketed form and then sending the bare form
    throws away a working strategy. The send must use the SAME syntax."""
    vm = VoiceModem(permissive_modem.port, timeout=2)
    res = vm.send_digits("5")
    assert res["ok"] is True
    sent = [c for c in permissive_modem.received if c.startswith("AT+VTS=[")]
    assert sent, f"bracketed form was not reused: {permissive_modem.received}"
    # '5' is row 770 / col 1336 — the digit has to reach the tone pair.
    assert any("770,1336" in c for c in sent)


def test_send_digits_sends_every_digit_of_the_string(permissive_modem):
    vm = VoiceModem(permissive_modem.port, timeout=2)
    assert vm.send_digits("15")["ok"] is True
    sent = [c for c in permissive_modem.received if c.startswith("AT+VTS=[")]
    assert any("697,1209" in c for c in sent)   # '1'
    assert any("770,1336" in c for c in sent)   # '5'


def test_a_probe_only_strategy_refuses_a_digit_it_cannot_express(modem):
    """`AT+VTS=1` was probed with '1'. It cannot send '5', and saying so beats
    silently sending the wrong thing."""
    permissive = FakeCX93001(accept_vts="AT+VTS=1")
    try:
        vm = VoiceModem(permissive.port, timeout=2)
        assert vm.send_digits("1")["ok"] is True
        res = vm.send_digits("5")
        assert res["ok"] is False
        assert "only emit" in res["reason"]
    finally:
        permissive.close()


def test_send_digits_rejects_an_empty_string(modem):
    res = VoiceModem(modem.port, timeout=2).send_digits("  ")
    assert res["ok"] is False and "no digits" in res["reason"]


def test_strategy_is_per_modem_not_global():
    a, b = DtmfStrategy("/dev/fx1"), DtmfStrategy("/dev/fx2")
    a.chosen = CANDIDATES[0]
    assert b.resolved is False
    assert a.describe() != b.describe()


# --------------------------------------------------------------------------
# FXRemoteController — the VPT surface
# --------------------------------------------------------------------------

def test_controller_takes_the_port_from_params(modem):
    ctrl = FXRemoteController(device_name="FX line 1", fx_port=modem.port)
    assert ctrl.fx_port == modem.port
    assert ctrl.is_connected is True


def test_controller_off_and_on_hook(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    assert ctrl.execute_command("off_hook")["success"] is True
    assert ctrl.execute_command("on_hook")["success"] is True
    assert "ATA" in modem.received


def test_controller_dial_requires_a_number(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    res = ctrl.execute_command("dial", {})
    assert res["success"] is False and "needs a number" in res["error"]


def test_controller_dial_falls_back_to_the_configured_number(modem):
    """DEVICE{i}_FX_NUMBER is what makes `dial` usable without a per-case number."""
    ctrl = FXRemoteController(fx_port=modem.port, fx_number="5551234")
    res = ctrl.execute_command("dial", {})
    assert res["success"] is True
    assert res["number"] == "5551234"
    assert any(c.startswith("ATDT5551234") for c in modem.received)


def test_explicit_number_overrides_the_configured_one(modem):
    ctrl = FXRemoteController(fx_port=modem.port, fx_number="5551234")
    res = ctrl.execute_command("dial", {"number": "5559999"})
    assert res["success"] is True and res["number"] == "5559999"
    assert any(c.startswith("ATDT5559999") for c in modem.received)
    assert not any(c.startswith("ATDT5551234") for c in modem.received)


def test_blank_configured_number_is_not_a_number(modem):
    """DEVICE{i}_FX_NUMBER= in .env must not dial an empty string."""
    ctrl = FXRemoteController(fx_port=modem.port, fx_number="   ")
    res = ctrl.execute_command("dial", {})
    assert res["success"] is False and "needs a number" in res["error"]
    assert not any(c.startswith("ATDT") for c in modem.received)


def test_missing_number_error_names_the_env_key(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    res = ctrl.execute_command("dial", {})
    assert "FX_NUMBER" in res["error"]


def test_controller_dial_places_a_call(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    res = ctrl.execute_command("dial", {"number": "5551234"})
    assert res["success"] is True
    assert any(c.startswith("ATDT5551234") for c in modem.received)


def test_controller_send_digits_always_carries_verified_false(permissive_modem):
    ctrl = FXRemoteController(fx_port=permissive_modem.port)
    res = ctrl.execute_command("send_digits", {"digits": "1"})
    assert res["success"] is True
    assert res["verified"] is False
    assert "not proof" in res["verified_note"]


def test_controller_selftest_reports_seven_of_seven(modem):
    res = FXRemoteController(fx_port=modem.port).execute_command("selftest")
    assert res["success"] is True and res["passed"] == res["total"] == 7


def test_controller_audio_reports_that_the_host_is_deaf(modem):
    res = FXRemoteController(fx_port=modem.port).execute_command("audio")
    assert res["success"] is False
    assert "line-side hardware" in res["note"]


def test_press_key_maps_to_the_line_verbs(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    assert ctrl.execute_command("press_key", {"key": "OFF_HOOK"})["success"] is True
    assert ctrl.execute_command("press_key", {"key": "HANGUP"})["success"] is True
    assert "ATA" in modem.received


def test_press_key_forwards_params_to_dial(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    res = ctrl.execute_command("press_key", {"key": "DIAL", "number": "55599"})
    assert res["success"] is True
    assert any("ATDT55599" in c for c in modem.received)


def test_unknown_key_is_refused_with_the_known_set(modem):
    res = FXRemoteController(fx_port=modem.port).execute_command("press_key", {"key": "NOPE"})
    assert res["success"] is False
    assert set(res["known_keys"]) == set(KEY_MAP)


def test_unknown_command_never_raises(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    for cmd in ("nonsense", "", None, "DROP TABLE"):
        res = ctrl.execute_command(cmd)
        assert res["success"] is False


def test_modem_fault_is_reported_not_raised():
    ctrl = FXRemoteController(fx_port="/dev/definitely-not-here")
    res = ctrl.execute_command("status")
    assert res["success"] is True and res["reachable"] is False
    res = ctrl.execute_command("selftest")
    assert res["success"] is False and "error" in res


def test_disconnect_is_safe_without_a_live_port(modem):
    ctrl = FXRemoteController(fx_port=modem.port)
    assert ctrl.disconnect() is True