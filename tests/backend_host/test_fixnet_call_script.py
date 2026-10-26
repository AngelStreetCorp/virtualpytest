"""Unit tests for test_scripts/gw/fixnet_call.py (TASK-71). No modem required.

Two fake channels stand in for the two serial ports. The fake network connects
them the way the real rack does: dialling the number that belongs to the other
channel makes that channel see RING. What is tested is the script's verdicts, one
per phase, because each phase is a report step.
"""

import importlib.util
import os
import re
import threading
import time

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "test_scripts", "gw", "fixnet_call.py")


@pytest.fixture(scope="module")
def mod():
    os.environ.update(FIXNET_FROM_FX="/dev/fx3", FIXNET_TO_FX="/dev/fx4", FIXNET_NUMBER="1111")
    spec = importlib.util.spec_from_file_location("fixnet_call", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.RING_WAIT = 2.0
    m.ANSWER_DIAL_WAIT = 1.0
    m.DROP_WAIT = 1.0
    return m


class Net:
    """The rack: which number rings which port, and whether the line has tone."""

    def __init__(self, numbers, dead=()):
        self.numbers = numbers          # number -> port that rings
        self.dead = set(dead)           # ports with no dial tone
        self.rings = {}                 # port -> threading.Event
        self.gci = "A6"                 # what the modem reports back for AT+GCI?
        # answer path
        self.pickup_ok = True           # AT+VLS=1 during the ring is accepted
        self.bridged = True             # the pickup joins the caller's call (else: dial tone)
        self.callee_hears_drop = True   # the caller hanging up reaches the callee as busy tone
        self.caller_drops = False       # the caller gets NO CARRIER while the call is held
        self.pending = {}               # port -> unsolicited line waiting to be read
        self.voice = {}                 # port -> is the line in voice mode (FCLASS=8)
        self.offhook = set()            # ports AT+VLS=1 connected to the line (off-hook)
        self.call = {}                  # caller/callee of the call being placed, live once picked up
        self.deaf = set()               # ports a bare ATA wedged: they answer nothing
        self.forgotten = set()          # ports whose incoming call was lost to a mid-ring mode switch


class FakeChannel:
    def __init__(self, port, net):
        self.port, self.net = port, net
        self.cmds = []
        self.drains = 0
        net.rings.setdefault(port, threading.Event())

    def try_command(self, cmd, timeout=None):
        self.cmds.append(cmd)
        net = self.net
        if self.port in net.deaf and cmd not in ("AT+VNH=1",):
            # a wedged modem answers nothing, which is what the rack showed
            return False, f"{cmd} -> no reply within {timeout or 3.0}s"
        if cmd.startswith("ATDT"):
            if self.port in net.dead:
                return True, "NO DIALTONE"
            target = net.numbers.get(cmd[4:])
            if target is None:
                return True, "NO CARRIER"
            if target in net.offhook:
                # the rack: a called line already off-hook gives the caller BUSY
                return True, "BUSY"
            net.call = {"caller": self.port, "callee": target, "live": False}
            net.rings.setdefault(target, threading.Event()).set()
            # A data-mode dial gets no result code while the far end rings, and a
            # VOICE pickup gives it no CONNECT either: it just keeps waiting.
            time.sleep(min(timeout or 1.0, 1.0))
            return False, f"{cmd} -> no reply within {timeout}s"
        if cmd == "AT+GCI?":
            return True, f"+GCI: {net.gci}"
        if cmd == "AT+FCLASS=8":
            # changing mode while a call is coming in makes the modem forget it
            if net.rings[self.port].is_set():
                net.forgotten.add(self.port)
                net.rings[self.port].clear()
            net.voice[self.port] = True
            return True, ""
        if cmd == "AT+VLS=1":
            # On the rack's Conexant VLS=1 connects the modem to the line: it goes
            # off-hook. During a ring that is the pickup; outside one the line is
            # just busy (and hears dial tone).
            if not net.voice.get(self.port):
                return False, f"{cmd} -> not in voice mode"
            ringing = net.rings[self.port].is_set() and self.port not in net.forgotten
            if ringing and not net.pickup_ok:
                return False, "AT+VLS=1 -> ERROR"
            net.offhook.add(self.port)
            net.rings[self.port].clear()
            if ringing and net.bridged:
                net.call["live"] = True
                if net.caller_drops:
                    net.pending[net.call["caller"]] = "NO CARRIER"
            else:
                net.pending[self.port] = "\x10d"
            return True, ""
        if cmd == "AT+VLS?":
            return True, "1" if self.port in net.offhook else "0"
        if cmd == "ATA":
            # in voice mode this firmware refuses ATA at once; in data mode it
            # returns nothing and wedges the modem
            if net.voice.get(self.port):
                return False, "ATA -> ERROR"
            net.deaf.add(self.port)
            return False, f"{cmd} -> no reply within {timeout or 3.0}s"
        if cmd in ("AT+VNH=1", "ATH"):
            if self.port in net.deaf:
                return False, f"{cmd} -> no reply within 3.0s"
            if net.call.get("live") and net.call["caller"] == self.port:
                net.call["live"] = False
                if net.callee_hears_drop:
                    net.pending[net.call["callee"]] = "\x10b"
            net.offhook.discard(self.port)
            return True, ""
        return True, ""

    def wait_for(self, patterns, timeout):
        # polls until the deadline, like the real channel: a line that has not
        # arrived yet is not a miss until the timeout is spent
        deadline = time.time() + timeout
        while time.time() < deadline:
            for pattern in patterns:
                if re.search(pattern, "RING") and self.net.rings[self.port].is_set():
                    return "RING", ["RING"]
                waiting = self.net.pending.get(self.port, "")
                if waiting and re.search(pattern, waiting):
                    self.net.pending.pop(self.port)
                    return waiting, [waiting]
            time.sleep(0.02)
        return None, []

    def drain_ring(self):
        self.drains += 1

    def close(self):
        pass


def run(mod, net, from_fx="/dev/fx3", to_fx="/dev/fx4", number="1111", answer=True):
    """A normal run: the called modem picks up. answer=False is the opt-out."""
    steps = []
    chans = {}

    def opener(port):
        chans[port] = FakeChannel(port, net)
        return chans[port]

    ok, meta = mod.run_call(from_fx, to_fx, number, 1, answer,
                            lambda m, s, d, t0, t1, actions, checks: steps.append((m, s, d, t0, t1, actions, checks)),
                            open_channel=opener)
    return ok, meta, steps, chans


NUMBERS = {"1111": "/dev/fx4", "2222": "/dev/fx3"}


def test_defaults_come_from_the_env(mod):
    # literals only: the platform reads _script_args statically from the source
    assert mod._script_args[:3] == ["--from_fx:str:/dev/fx3", "--to_fx:str:/dev/fx4", "--number:str:env"]
    assert mod.resolve_number("env") == "1111"            # FIXNET_NUMBER from the host .env
    assert mod.resolve_number("2222") == "2222"


def test_answer_is_on_by_default_so_a_plain_run_nine_steps(mod):
    # No parameter: a normal call rings, is picked up and connects. That is the
    # normal way a call goes, so it must not need a flag to be tested.
    assert "--answer:bool:true" in mod._script_args
    ok, meta, steps, _ = run(mod, Net(NUMBERS))
    assert [s[0] for s in steps] == [
        "Check arguments", "Open both modems", "Prepare caller modem", "Prepare callee modem",
        "Dial 1111 from /dev/fx3", "RING on /dev/fx4", "Callee answers", "Call connected end to end",
        "Release both modems"]
    assert ok and meta["answer"] is True and meta["connected"] is True


def test_call_rings_the_called_modem(mod):
    ok, meta, steps, chans = run(mod, Net(NUMBERS))
    assert ok and meta["rang"]
    # the country code is set, or the modem calls the loop a digital line
    assert f"AT+GCI={mod.COUNTRY_CODE}" in chans["/dev/fx3"].cmds
    assert "ATX4" in chans["/dev/fx3"].cmds


def test_answer_false_is_the_opt_out_for_a_far_end_that_answers_itself(mod):
    # The only way back to the ring-only path: a device under test that picks
    # up on its own, where our modem must not send ATA.
    ok, meta, steps, chans = run(mod, Net(NUMBERS), answer=False)
    assert ok and meta["answer"] is False
    assert [s[0] for s in steps][-2:] == ["RING on /dev/fx4", "Release both modems"]
    assert "ATA" not in chans["/dev/fx4"].cmds and "AT+VLS=1" not in chans["/dev/fx4"].cmds


def test_every_step_carries_actions_checks_and_real_times(mod):
    ok, meta, steps, _ = run(mod, Net(NUMBERS))
    dial = next(s for s in steps if s[0].startswith("Dial"))
    assert any("ATDT1111" in a["command"] and "[caller /dev/fx3]" in a["command"] for a in dial[5])
    assert [c[0] for c in dial[6]] == ["Dial tone on the calling line", "Network accepted the call"]
    prep = next(s for s in steps if s[0] == "Prepare caller modem")
    cmds = [a["command"] for a in prep[5]]
    assert [c.split("] ")[1].split(" ->")[0] for c in cmds] == ["ATZ", "AT+GCI=A6", "AT+GCI?", "ATX4", "ATI3"]
    assert all(" (" in c and c.endswith("s)") for c in cmds)          # every action carries its duration
    assert all(s[4] >= s[3] for s in steps)
    assert meta["transcript"] and all({"t", "who"} <= set(e) for e in meta["transcript"])
    assert [x["step"] for x in meta["steps"]] == [s[0] for s in steps]


def test_country_code_that_does_not_stick_fails_prepare(mod):
    net = Net(NUMBERS)
    net.gci = "B5"
    ok, _, steps, _ = run(mod, net)
    prep = next(s for s in steps if s[0] == "Prepare caller modem")
    assert not ok and not prep[1] and "did not stick" in prep[2]


def test_reverse_direction(mod):
    ok, _, _, _ = run(mod, Net(NUMBERS), "/dev/fx4", "/dev/fx3", "2222")
    assert ok


def test_wrong_number_for_the_called_modem_fails_on_ring(mod):
    # dialling line 4's CLI but listening on fx1: the network rings fx4, fx1 stays silent
    net = Net({"1111": "/dev/fx4"})
    net.rings["/dev/fx1"] = threading.Event()
    ok, _, steps, _ = run(mod, net, "/dev/fx3", "/dev/fx1", "1111")
    ring = next(s for s in steps if s[0].startswith("RING on"))
    assert not ok and not ring[1]


def test_dead_line_reports_no_dialtone(mod):
    ok, _, steps, _ = run(mod, Net(NUMBERS, dead=["/dev/fx3"]))
    dial = next(s for s in steps if s[0].startswith("Dial"))
    assert not ok and not dial[1] and "NO DIALTONE" in dial[2]


def test_unknown_number_reports_no_carrier(mod):
    ok, _, steps, _ = run(mod, Net(NUMBERS), number="0000000000")
    dial = next(s for s in steps if s[0].startswith("Dial"))
    assert not ok and "NO CARRIER" in dial[2]


def test_same_port_is_rejected(mod):
    ok, _, steps, _ = run(mod, Net(NUMBERS), "/dev/fx4", "/dev/fx4")
    assert not ok and steps[0][1] is False


def test_pickup_is_vls_not_ata(mod):
    # The rack, 2026-10-22: in voice mode this firmware refuses ATA at once
    # (ERROR); AT+VLS=1 during the ring is what goes off-hook.
    ok, meta, steps, chans = run(mod, Net(NUMBERS))
    answered = next(s for s in steps if s[0] == "Callee answers")
    assert ok and answered[1]
    assert [c[0] for c in answered[6]] == ["Called modem picked up (AT+VLS=1)",
                                           "Called line is off-hook (AT+VLS? reads 1)"]
    assert "ATA" not in chans["/dev/fx4"].cmds
    assert chans["/dev/fx4"].cmds[-4:-2] == ["AT+VLS=1", "AT+VLS?"]


def test_connected_end_to_end_needs_the_callee_to_hear_the_caller_leave(mod):
    ok, meta, steps, chans = run(mod, Net(NUMBERS))
    call = next(s for s in steps if s[0] == "Call connected end to end")
    assert ok and call[1] and meta["connected"] is True
    assert [c[0] for c in call[6]] == ["Called line is in the call (no dial or busy tone while held)",
                                       "Calling modem still in the call when it hangs up",
                                       "Called modem hears the caller hang up"]
    # the caller hangs up first, inside this step, and the callee is then listening
    actions = [a["command"] for a in call[5]]
    hang = next(i for i, a in enumerate(actions) if a.startswith("[caller") and "AT+VNH=1" in a)
    assert any(a.startswith("[callee") and "wait for" in a and "x10[db]" in a for a in actions[hang:])


def test_a_pickup_outside_the_call_hears_dial_tone_and_fails(mod):
    net = Net(NUMBERS)
    net.bridged = False               # off-hook, but not joined to the caller: dial tone
    ok, meta, steps, _ = run(mod, net)
    call = next(s for s in steps if s[0] == "Call connected end to end")
    assert not ok and not call[1] and meta["connected"] is False
    assert "dial/busy tone" in call[2]


def test_a_callee_that_never_hears_the_caller_leave_fails(mod):
    net = Net(NUMBERS)
    net.callee_hears_drop = False
    ok, meta, steps, _ = run(mod, net)
    call = next(s for s in steps if s[0] == "Call connected end to end")
    assert not ok and not call[1] and "were not in one call" in call[2]


def test_a_caller_that_dropped_first_fails(mod):
    net = Net(NUMBERS)
    net.caller_drops = True
    ok, meta, steps, _ = run(mod, net)
    call = next(s for s in steps if s[0] == "Call connected end to end")
    assert not ok and "dropped first" in call[2]


def test_answer_fails_honestly_when_the_pickup_is_refused(mod):
    net = Net(NUMBERS)
    net.pickup_ok = False
    ok, meta, steps, _ = run(mod, net)
    answered = next(s for s in steps if s[0] == "Callee answers")
    assert not ok and not answered[1] and meta["connected"] is False
    assert "AT+VLS=1 -> ERROR" in answered[2]


def test_answer_says_so_when_the_line_never_rang(mod):
    # dialling fx4's CLI while listening on fx1: no ring, so no pickup is sent
    net = Net({"1111": "/dev/fx4"})
    net.rings["/dev/fx1"] = threading.Event()
    ok, _, steps, chans = run(mod, net, "/dev/fx3", "/dev/fx1", "1111")
    answered = next(s for s in steps if s[0] == "Callee answers")
    assert not ok and not answered[1] and "never sent" in answered[2]
    assert "AT+VLS=1" not in chans["/dev/fx1"].cmds


def test_the_line_is_in_voice_mode_before_the_call_arrives(mod):
    # Rack failures, all 2026-10-22: a bare ATA in data mode gets no reply and
    # wedges the modem; switching mode *between* RING and the pickup makes it
    # forget the call; and AT+VLS=1 before the call takes the line off-hook so
    # the dial answers BUSY. So prepare arms AT+FCLASS=8 only, and the pickup is
    # AT+VLS=1 during the ring.
    net = Net(NUMBERS)
    ok, meta, steps, chans = run(mod, net)
    assert ok and meta["connected"] is True
    prep = next(s for s in steps if s[0] == "Prepare callee modem")
    prep_cmds = [a["command"].split("] ")[1].split(" ->")[0] for a in prep[5]]
    assert prep_cmds[-1] == "AT+FCLASS=8" and "AT+VLS=1" not in prep_cmds
    assert [c[0] for c in prep[6]][-1] == "Voice mode for the pickup (FCLASS=8)"
    assert "/dev/fx4" not in net.forgotten
    # and only the callee is ever switched: the caller must keep dialling in data mode
    assert "AT+FCLASS=8" not in chans["/dev/fx3"].cmds


def test_a_callee_off_hook_before_the_dial_makes_the_call_busy(mod):
    # The rack, 2026-10-22: with AT+VLS=1 in the callee's prepare step the dial
    # answered BUSY and the callee heard dial tone then busy tone (DLE d, DLE b)
    # instead of RING. The fake must reproduce that, or the guard above is empty.
    net = Net(NUMBERS)
    callee, caller = FakeChannel("/dev/fx4", net), FakeChannel("/dev/fx3", net)
    callee.try_command("AT+FCLASS=8")
    callee.try_command("AT+VLS=1")
    assert caller.try_command("ATDT1111", 1.0) == (True, "BUSY")


def test_release_after_a_failed_call_does_not_fail_the_run_twice(mod):
    # A wedged modem fails the release too. That is one fault, not two: the
    # release still happens (a line left off-hook is worse) but it must not be
    # what decides the verdict, or every real fault reports as a pair of reds.
    net = Net(NUMBERS)
    net.pickup_ok = False             # the line rings, the pickup is refused
    ok, meta, steps, _ = run(mod, net)
    names = [s[0] for s in steps]
    assert not ok
    release = next(s for s in steps if s[0].startswith("Release both modems"))
    assert "cleanup" in release[0] and release[6] is not None
    assert meta["steps"][-1]["counts"] is False
    assert "Callee answers" in names


def test_every_release_drops_pending_lines_first(mod):
    # A late line belongs to the call, not to the hang-up: without the drain it
    # would be read as the hang-up's reply.
    ok, _, steps, chans = run(mod, Net(NUMBERS))
    hang = next(s for s in steps if s[0] == "Release both modems")
    assert ok and hang[1] and "released (AT+VNH=1)" in hang[2]
    assert chans["/dev/fx3"].drains == 2 and chans["/dev/fx4"].drains == 1   # the caller also hung up in step 8
    assert all(any(a["command"].startswith(f"[{l}") and "drop pending lines" in a["command"]
                   for a in hang[5]) for l in ("caller", "callee"))
