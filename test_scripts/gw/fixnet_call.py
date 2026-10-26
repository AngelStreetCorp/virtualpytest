#!/usr/bin/env python3
"""
Fixnet call test for VirtualPyTest (TASK-71).

Places one call from one FX voice modem to another through the gateways and
proves it arrived: the called modem must see RING, pick up, and both ends must
be in the same call. Every phase is its own report step, so a failure says which
phase broke (modem, dial tone, network, far end, pickup, the call itself).

Usage:
    python test_scripts/gw/fixnet_call.py                                  # defaults from the host .env
    python test_scripts/gw/fixnet_call.py --from_fx /dev/fx4 --to_fx /dev/fx3 --number <CLI of fx3>
    python test_scripts/gw/fixnet_call.py --answer false                   # only if the far end answers itself

The called modem picks up and the call must connect both ends — that is the normal way a call goes,
so it needs no flag. Pass `--answer false` only when the far end is a device that answers on its own.

The number is the CLI of the CALLED line, not a modem name.
"""

import os
import sys
import threading
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args

# The rack's real numbers are customer data, so they are not in the repo. The number defaults to the
# sentinel "env" = FIXNET_NUMBER from the host .env (the platform reads _script_args statically, so a
# value computed from the environment would not show in the Run form).
NUMBER_FROM_ENV = "env"
COUNTRY_CODE = os.environ.get("FIXNET_GCI", "A6")   # T.35: A6 = Switzerland; the US default makes the modem refuse the FXS loop

_script_args = [
    "--from_fx:str:/dev/fx3",
    "--to_fx:str:/dev/fx4",
    "--number:str:env",
    "--hold:int:5",
    "--answer:bool:true",
]

_script_description = "Call from one Fixnet FX modem to another: it rings, the called modem picks up, the call connects"
_arg_descriptions = {
    "from_fx": "Calling modem (/dev/fx1..fx4)",
    "to_fx": "Called modem (/dev/fx1..fx4); must be the line that owns --number",
    "number": "CLI to dial: the number of the called line; 'env' = FIXNET_NUMBER from the host .env",
    "hold": "Seconds to keep ringing (or to hold the call once it is connected) before hanging up",
    "answer": "The called modem picks up (AT+VLS=1) and the call must connect both ends — on by default, because that is what a call is. Pass false only when the far end is a device that answers on its own.",
}

REFUSED = ("NO DIALTONE", "BUSY", "NO ANSWER", "NO CARRIER")
RING_WAIT = 30.0      # how long the called modem waits for RING
ANSWER_DIAL_WAIT = 12.0    # how long the dial reads when the callee picks up: BUSY / NO DIALTONE come within ~7s,
                           # and a voice pickup gives the data-mode caller no CONNECT, so reading longer only runs
                           # the caller into its own carrier timeout (NO CARRIER ~50s after the dial)
DROP_WAIT = 15.0      # how long the callee waits to hear the caller hang up
# DLE-shielded line events a modem in voice mode reports (V.253). Case matters: DLE r is ringback.
LINE_TONE = r"(?-i:^\x10[db])"     # DLE d = dial tone, DLE b = busy tone: the line is not in a call


def _open(port):
    # imported here so a host without pyserial can still list the script
    from backend_host.src.controllers.remote.fx.at_channel import ATChannel
    return ATChannel(port, 3.0).open()


class Logged:
    """A modem channel that logs every command and reply, with timing, to a shared transcript.

    The transcript is what makes a failed step debuggable: the exact AT command, the exact
    reply, how long the modem took, and which modem said it. It is printed to the host log as
    it happens and saved in the run metadata.
    """

    def __init__(self, channel, who, log):
        self._ch, self.who, self._log = channel, who, log

    def _add(self, **kw):
        entry = {"t": time.time(), "who": self.who, **kw}
        self._log.append(entry)
        return entry

    def try_command(self, cmd, timeout=None):
        print(f"  [{self.who}] > {cmd}")
        t0 = time.time()
        good, reply = self._ch.try_command(cmd, timeout)
        dt = time.time() - t0
        shown, logged_ok = self._readable(cmd, good, reply, timeout)
        print(f"  [{self.who}] < {shown}  ({dt:.2f}s)")
        self._add(cmd=cmd, ok=logged_ok, reply=shown, timeout=timeout, dt=round(dt, 3))
        return good, reply

    @staticmethod
    def _readable(cmd, good, reply, timeout):
        """What the report shows for an AT exchange, without changing what the caller gets back.

        The channel strips the final OK, so an empty reply is shown as OK; a stray RING line that
        arrived before the OK is noted, not shown as the reply; and a dial that produced no result
        code is the far end ringing, not a failure.
        """
        if cmd.upper().startswith("ATDT") and not good and "no reply within" in reply:
            return (f"no result code within {timeout:.0f}s: the call is in progress (far end ringing)", True)
        if not good:
            return (f"FAILED: {reply}", False)
        lines = [l for l in reply.splitlines() if l.strip()]
        rings = [l for l in lines if l.strip() == "RING"]
        rest = [l for l in lines if l.strip() != "RING"]
        text = " | ".join(rest) if rest else "OK"
        if rings:
            text += f" (RING seen while this ran: the line was still ringing)"
        return (text, True)

    def wait_for(self, patterns, timeout):
        print(f"  [{self.who}] > wait for {list(patterns)} (up to {timeout:.0f}s)")
        t0 = time.time()
        line, seen = self._ch.wait_for(patterns, timeout)
        dt = time.time() - t0
        print(f"  [{self.who}] < {line if line else 'nothing seen'}  ({dt:.2f}s) lines={seen}")
        self._add(wait=list(patterns), timeout=timeout, matched=line, seen=seen, dt=round(dt, 3))
        return line, seen

    def drain(self, why):
        """Throw away pending unsolicited lines before a command.

        A CONNECT that arrives late belongs to the call, not to the command that
        follows. Without this, `ATH` would read it and return a reply the
        hang-up never sent — so the report would claim a hang-up it never saw.
        """
        self._ch.drain_ring()
        self._add(drain=why)
        print(f"  [{self.who}] ~ drop pending lines ({why})")

    def close(self):
        self._ch.close()


def resolve_number(number):
    """'env' (the default) means FIXNET_NUMBER from the host .env."""
    if (number or "").strip().lower() in ("", NUMBER_FROM_ENV):
        return os.environ.get("FIXNET_NUMBER", "")
    return number.strip()


def _action_line(entry):
    """One report line for a logged AT exchange: who, command, reply, time."""
    if "cmd" in entry:
        what = entry["cmd"]
        got = entry.get("reply") or "OK"
    elif "wait" in entry:
        what = f"wait for {entry['wait']}"
        got = entry.get("matched") or "nothing seen"
    else:
        what = f"drop pending lines ({entry.get('drain')})"
        got = "buffer cleared"
    return f"[{entry['who']}] {what} -> {got} ({entry.get('dt', 0):.2f}s)"


def _release(ch, why):
    """Hang a modem up: drop pending lines, then +VNH=1, ATH as the fallback (voice_modem.on_hook).

    The drain matters: a late line belongs to the call, not to the hang-up, and
    read as its reply it would report a hang-up that never ran.
    """
    ch.drain(why)
    good, reply = ch.try_command("AT+VNH=1")
    how = "AT+VNH=1"
    if not good:
        good, reply = ch.try_command("ATH")
        how = f"ATH (VNH refused: {reply})"
    return how, good, reply


def _hang_up(ch, why):
    how, good, reply = _release(ch, why)
    return f"hang-up ({how} -> {reply or 'OK'})" if good else f"hang-up attempt ({how} -> {reply})"


def run_call(from_fx, to_fx, number, hold, answer, record, open_channel=_open):
    """Run the whole call; `record(message, success, details, start, end, actions, checks)` once per phase.

    `actions`: one {"command": "<modem> <AT command> -> <reply> (<seconds>)"} per AT exchange in the phase.
    `checks`: [(label, ok, details)], the verifications of the phase. The full transcript is returned
    in the metadata. Returns (overall_success, metadata). Never raises: a phase that cannot run is a
    failed step, not a crash.
    """
    number = resolve_number(number)
    log = []
    meta = {"from_fx": from_fx, "to_fx": to_fx, "number": number, "answer": answer, "hold": hold,
            "country_code": COUNTRY_CODE, "transcript": log, "steps": []}
    caller = callee = None
    state = {"t": time.time(), "i": 0, "n": 0}

    def step(message, checks, counts=True):
        """Record one phase. `checks` = [(label, ok, details)]; the phase passes if all do.

        `counts=False` marks a step that does not decide the verdict — the release
        after a failed call. Its real result is still reported; it just cannot be
        the reason a run fails twice for the same thing.
        """
        now = time.time()
        ok = all(c[1] for c in checks)
        state["n"] += 1
        actions = [{"command": _action_line(e)} for e in log[state["i"]:]]
        details = "; ".join(f"{label}: {det}" for label, good, det in checks)
        verdict = ("PASS" if ok else "FAIL") if counts else ("cleanup ok" if ok else "cleanup FAILED")
        print(f"[Step {state['n']}] {verdict} {message} ({now - state['t']:.1f}s)")
        for label, good, det in checks:
            print(f"    {'ok  ' if good else 'FAIL'} {label}: {det}")
        record(message, ok, details, state["t"], now, actions, checks)
        meta["steps"].append({"step": message, "ok": ok, "seconds": round(now - state["t"], 2), "counts": counts})
        state["t"], state["i"] = now, len(log)
        return ok

    try:
        # 1. arguments
        checks = [("Calling and called modem differ", from_fx != to_fx, f"{from_fx} -> {to_fx}"),
                  ("Number to dial given", bool(number),
                   number if number else "none: pass --number or set FIXNET_NUMBER in the host .env"),
                  ("Settings", True, f"hold={hold}s, answer={answer}, country code={COUNTRY_CODE}")]
        if not step("Check arguments", checks):
            return False, meta

        # 2. open both modems
        try:
            caller = Logged(open_channel(from_fx), f"caller {from_fx}", log)
            callee = Logged(open_channel(to_fx), f"callee {to_fx}", log)
        except Exception as exc:
            step("Open both modems", [("Serial ports opened", False, str(exc))])
            return False, meta
        step("Open both modems", [("Calling modem port opened", True, from_fx),
                                  ("Called modem port opened", True, to_fx)])

        # 3. prepare both: reset, country code (read back), dial-tone check, firmware
        for label, ch in (("caller", caller), ("callee", callee)):
            checks = []
            cmds = ["ATZ", f"AT+GCI={COUNTRY_CODE}", "AT+GCI?", "ATX4", "ATI3"]
            if label == "callee" and answer:
                # The line that will be picked up goes into voice mode BEFORE the
                # call arrives, not between RING and ATA. Doing it in between
                # changes the modem's mode mid-call, it forgets the incoming call,
                # and ATA then answers ERROR (rack, 2026-10-22). ATZ clears the
                # mode, so this has to come after the reset. FCLASS=8 only: on
                # this Conexant AT+VLS=1 connects the modem to the line, i.e.
                # takes it off-hook, so the caller gets BUSY and the callee
                # hears dial tone then busy tone (DLE d / DLE b) instead of RING.
                # The same AT+VLS=1, sent during the ring, is the pickup.
                cmds += ["AT+FCLASS=8"]
            for cmd in cmds:
                good, reply = ch.try_command(cmd)
                if cmd == "ATZ":
                    checks.append(("Modem reset (ATZ)", good, reply or "OK"))
                elif cmd.startswith("AT+GCI="):
                    checks.append((f"Country code set ({COUNTRY_CODE})", good, reply or "OK"))
                elif cmd == "AT+GCI?":
                    stuck = good and COUNTRY_CODE in reply
                    checks.append(("Country code reads back", stuck,
                                   reply if stuck else f"{reply or 'no answer'} (wanted {COUNTRY_CODE}: the country code did not stick)"))
                elif cmd == "ATX4":
                    checks.append(("Dial-tone detection on (ATX4)", good, reply or "OK"))
                elif cmd == "AT+FCLASS=8":
                    checks.append(("Voice mode for the pickup (FCLASS=8)", good, reply or "OK"))
                else:
                    meta[f"{label}_firmware"] = reply.strip() if good else None
                    checks.append(("Firmware", True, reply.strip() if good else "no answer (not required)"))
            if not step(f"Prepare {label} modem", checks):
                return False, meta

        # 4. dial; the callee listens for RING at the same time
        seen = {}

        def listen():
            # in voice mode the ring can also come as DLE R (0x10 'R'); case
            # matters there, DLE r is ringback
            line, lines = callee.wait_for([r"^RING", r"(?-i:^\x10R)"], RING_WAIT)
            seen["ring"], seen["lines"] = line, lines

        listener = threading.Thread(target=listen, daemon=True)
        listener.start()
        time.sleep(0.5)                       # the listener must be reading before the dial

        dial_wait = ANSWER_DIAL_WAIT if answer else float(hold) + 5.0
        answered = {}

        def answer_call():
            listener.join(RING_WAIT + 1)
            if seen.get("ring"):
                # In voice mode (armed in prepare) AT+VLS=1 IS the pickup: it
                # connects the modem to the line, i.e. goes off-hook. ATA is not
                # accepted in class 8 on this firmware: it answers ERROR at once
                # (rack, 2026-10-22, three runs: VLS=1 after RING -> OK and a
                # following ATA -> ERROR; VLS=1 before the call -> BUSY; ATA
                # alone after RING -> ERROR).
                good, reply = callee.try_command("AT+VLS=1")
                answered["ok"], answered["reply"] = good, reply
                if good:
                    good, line = callee.try_command("AT+VLS?")
                    answered["vls"] = line.strip() if good else f"no answer ({line})"

        if answer:
            threading.Thread(target=answer_call, daemon=True).start()

        t0 = time.time()
        good, reply = caller.try_command(f"ATDT{number}", dial_wait)
        # no result within the wait = the far end is ringing and nothing refused the call
        ringing = not good and "no reply within" in reply
        refused = next((r for r in REFUSED if r in reply), None)
        connected = good and "CONNECT" in reply
        dial_ok = (ringing or connected) and not refused
        meta["dial_reply"] = ("no result code: the far end is ringing" if ringing else reply)
        tone = refused != "NO DIALTONE"
        checks = [("Dial tone on the calling line", tone,
                   "heard" if tone else "NO DIALTONE: the line behind the calling modem is dead (cable, patch or gateway)"),
                  ("Network accepted the call", dial_ok,
                   (f"{refused}: the network refused or dropped the call" if refused
                    else f"CONNECT after {time.time() - t0:.1f}s" if connected
                    else f"dialled {number}, far end ringing after {time.time() - t0:.1f}s" if ringing
                    else reply))]
        step(f"Dial {number} from {from_fx}", checks)

        # 5. the called modem must have seen RING
        listener.join(RING_WAIT + 1)
        rang = bool(seen.get("ring"))
        ring_entry = next((e for e in reversed(log) if e.get("who", "").startswith("callee") and "wait" in e), None)
        meta["rang"] = rang
        meta["ring_after_s"] = round(ring_entry["t"] - t0, 1) if rang and ring_entry else None
        step(f"RING on {to_fx}", [("Called modem saw RING", rang,
             f"RING {meta['ring_after_s']}s after the dial" if rang else
             f"nothing in {RING_WAIT:.0f}s: wrong number for {to_fx}, or its line is down. Lines seen: {seen.get('lines')}")])

        # 6. the called modem picks up — the normal way a call goes
        if answer:
            # the pickup runs in its own thread during the dial; it is done by now
            # unless the line never rang
            deadline = time.time() + 3.0
            while "ok" not in answered and seen.get("ring") and time.time() < deadline:
                time.sleep(0.05)
            pickup = (answered.get("reply") or "OK") if "ok" in answered else "never sent: the line never rang"
            picked = bool(answered.get("ok"))
            meta["answer_reply"], meta["picked_up"] = answered.get("reply"), picked
            step("Callee answers", [
                ("Called modem picked up (AT+VLS=1)", picked, pickup),
                ("Called line is off-hook (AT+VLS? reads 1)", answered.get("vls") == "1",
                 answered.get("vls") or "not read: no pickup")])

            # 7. both ends are in the same call. A voice pickup gives the data-mode
            # caller no CONNECT, so the proof is on the line itself:
            #  - callee: off-hook but NOT hearing dial or busy tone for the hold
            #    time. A line that went off-hook outside a call hears dial tone
            #    (DLE d) — that is what the rack showed when VLS=1 came too early.
            #  - caller: still in the dial when it hangs up (no BUSY / NO CARRIER).
            #  - end to end: the caller hangs up and the CALLEE hears it (busy or
            #    dial tone on its line). Only a real call carries that across.
            bridged = caller_up = drop_seen = False
            hold_lines = caller_lines = drop_lines = []
            hang_reply = "not hung up: no pickup"
            if picked:
                tone, hold_lines = callee.wait_for([LINE_TONE], float(hold))
                bridged = tone is None
                dropped, caller_lines = caller.wait_for([r"^(BUSY|NO CARRIER|NO ANSWER|NO DIALTONE)"], 0.5)
                caller_up = dropped is None
                hang_reply = _hang_up(caller, "the caller ends the call")
                drop_seen, drop_lines = callee.wait_for([LINE_TONE], DROP_WAIT)
            meta.update({"connected": bool(picked and bridged and caller_up and drop_seen),
                         "callee_hold_lines": hold_lines, "callee_drop_lines": drop_lines})
            step("Call connected end to end", [
                ("Called line is in the call (no dial or busy tone while held)", picked and bridged,
                 f"quiet for {hold}s off-hook" + (f", lines: {hold_lines}" if hold_lines else "")
                 if picked and bridged else
                 f"{hold_lines[-1]!r} = dial/busy tone: the pickup did not reach the caller's call. Lines: {hold_lines}"
                 if picked else "no pickup"),
                ("Calling modem still in the call when it hangs up", picked and caller_up,
                 "no BUSY / NO CARRIER" if picked and caller_up else
                 f"dropped first: {caller_lines}" if picked else "no pickup"),
                ("Called modem hears the caller hang up", bool(drop_seen),
                 f"{drop_seen!r} on the called line after the caller's {hang_reply}" if drop_seen else
                 f"nothing within {DROP_WAIT:.0f}s after the caller's {hang_reply}: the two lines were not in "
                 f"one call. Lines: {drop_lines}" if picked else "no pickup")])
        else:
            remaining = float(hold) - (time.time() - t0)
            if rang and remaining > 0:
                time.sleep(remaining)

        # 8. release both modems (the caller again: harmless if it already hung up)
        checks = []
        for label, ch in (("caller", caller), ("callee", callee)):
            how, good, reply = _release(ch, f"before the {label}'s hang-up")
            checks.append((f"{label.capitalize()} released ({how})", good, reply or "OK"))
        # A line that already failed has nothing left to verify, and a wedged modem
        # will fail this too — that is the same fault twice, not two faults. The
        # release still runs, because leaving a line off-hook is worse than a noisy
        # report, but it stops deciding the verdict.
        already_failed = any(not s["ok"] for s in meta["steps"])
        step("Release both modems" if not already_failed
             else "Release both modems (cleanup — the call already failed above)",
             checks, counts=not already_failed)

        counted = [s for s in meta["steps"] if s.get("counts", True)]
        return all(s["ok"] for s in counted), meta
    finally:
        for ch in (caller, callee):
            if ch is not None:
                try:
                    ch._ch.try_command("ATH")
                    ch.close()
                except Exception:
                    pass


@script("fixnet_call", "Call from one Fixnet FX modem to another", capture_artifacts=False)
def main():
    args = get_args()
    context = get_context()

    def record(message, success, details, start, end, actions, checks):
        context.record_step_immediately({
            "message": message,
            "success": success,
            "actions": actions,
            "verifications": [{"success": good, "label": label, "details": det} for label, good, det in checks],
            "start_time": start,
            "end_time": end,
        })

    print(f"\n[fixnet_call] {args.from_fx} -> {args.to_fx}, number={args.number}, hold={args.hold}s, answer={bool(args.answer)}")
    ok, meta = run_call(args.from_fx, args.to_fx, args.number, args.hold, bool(args.answer), record)
    steps = meta["steps"]
    counted = [s for s in steps if s.get("counts", True)]
    cleanup = [s for s in steps if not s.get("counts", True)]
    context.metadata = {**meta, "host_name": context.host.host_name}
    failed = next((s["step"] for s in counted if not s["ok"]), None)
    refused = next((r for r in REFUSED if r in (meta.get("dial_reply") or "")), None)
    lines = [
        "FIXNET CALL SUMMARY",
        f"Host: {context.host.host_name}",
        f"Call: {meta['from_fx']} -> {meta['to_fx']} (number {meta['number'] or 'not set'})",
        f"Modems: caller {meta.get('caller_firmware') or 'not reached'}, callee {meta.get('callee_firmware') or 'not reached'}; "
        f"country code {meta['country_code']}",
        f"Called modem rang: {'yes, ' + str(meta['ring_after_s']) + 's after the dial' if meta.get('rang') else 'no'}",
    ]
    if refused:
        lines.append(f"Dial refused: {refused}")
    if meta.get("answer"):
        lines.append(f"Answered: {'yes' if meta.get('picked_up') else 'no'}; "
                     f"connected end to end: {'yes' if meta.get('connected') else 'no'}")
    lines += [
        f"Steps: {sum(1 for s in counted if s['ok'])}/{len(counted)} passed" + (f", first failure: {failed}" if failed else ""),
    ]
    if cleanup:
        # the release still has to happen, so report it — but say plainly that it
        # is not what failed the run
        lines.append("Cleanup: " + "; ".join(f"{s['step']} — {'ok' if s['ok'] else 'FAILED'}" for s in cleanup))
    lines.append(f"Result: {'SUCCESS' if ok else 'FAILED'}")
    context.execution_summary = "\n".join(lines)
    if not ok:
        context.error_message = f"Fixnet call failed at: {failed}"
    context.overall_success = ok
    return ok


main._script_args = _script_args
main._target_rules = {
    "target_type": "host",
    "host_os": "linux",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
