# BUG-0766 — The fixnet answer step asked the answering modem for `CONNECT`, so it could never pass

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0766                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed — proven on the rack 2026-10-22 (9/9)                 |
| Severity  | Medium (the answer path of the fixnet call test could never pass, so "a call that is picked up" was untestable — TASK-71 goal 3 was left at half) |
| Area      | testing                                                      |
| Fixed in  | build 90145 |
| Commit    | `2b5d20c06`, `0af331fb7`, `b1ba73e5a`                        |

---

## Symptom

`test_scripts/gw/fixnet_call.py --answer true` reports **"Callee answers — FAIL"** on a rack
where the call is answered correctly, and the reason is a result code that never arrives on
that modem.

Ringing is proven on the rack (TASK-71 goal 3, 2026-10-19: `fx1 → fx4` and `fx3 → fx4`). Answering
has never been demonstrated, and the step was not able to demonstrate it: as written, no amount of
working hardware makes it pass.

## Root cause

Two defects, and the unit test hid both.

**1. The verdict read `CONNECT` from the wrong modem.** The step passed only if `CONNECT` appeared
in the reply to `ATA` **and** in the reply to `ATDT`:

```python
ok = bool(answered.get("ok")) and "CONNECT" in answered.get("reply", "") and connected
```

But `CONNECT` is the result code the **dialling** modem receives when the far end picks up. The
answering modem's `ATA` returns `OK` — `at_channel.py:170-181` even strips the trailing `OK`, so
the callee's reply is normally the empty string. Requiring `CONNECT` there asks for something the
protocol does not send, so a correctly answered call is reported as a failure.

**2. A `CONNECT` arriving after the dial's read loop closed was lost.** `ATDT` is read for
`dial_wait`, and if the far end answers after that window the `CONNECT` line sits unread in the
input buffer. Nobody was reading for it, and it then leaked into the next command: `ATChannel.command()`
returns immediately on a call-state line (`at_channel.py:177-181`), so a late `CONNECT` was read as
the reply to `ATH` — the report claimed a hang-up it never performed.

**3. The test could not catch either.** `tests/backend_host/test_fixnet_call_script.py` faked
`ATA` as returning `"CONNECT 33600"`. The mock encoded the assumption under test, so the one test
covering the answer path passed by construction.

## Fix

`test_scripts/gw/fixnet_call.py`:

- The answer step now asks the **dialling** modem for `CONNECT`. `ATA`'s own reply proves only that
  the pickup was accepted (`OK`), and is reported as such.
- If the dial's read loop closed before the far end answered, the caller keeps reading
  (`LATE_CONNECT_WAIT`, 10 s) instead of reporting "not connected" on a call that did connect. The
  wait appears in the report as a normal action.
- Both channels drop their pending lines before `ATH`, so a late `CONNECT` cannot pass as the
  hang-up's reply. The drop is logged as an action (`drop pending lines`).
- Honest details: `ATA` refused (`ERROR`), `ATA` never sent because the line never rang, and
  "the far end never picked up" carrying both replies. Metadata gains `connected`,
  `connect_after_s`, `answer_reply` and `callee_connect`, and the execution summary gains an
  `Answered:` line in answer mode.

`tests/backend_host/test_fixnet_call_script.py`: the fake modem now models the protocol — `ATA`
returns `OK`, the `CONNECT` goes to the caller — and `wait_for` polls until the deadline like the
real channel. Four cases cover the answer path: `CONNECT` in the dial reply, `CONNECT` arriving
after the dial read loop, `ATA` refused, and a line that never rang. A fifth asserts the hang-up is
not fooled by a stray `CONNECT` (and that both channels were drained).

Docs: `test_scripts/gw/fixnet_call.md` and `docs/agent/devices/FIXNET_FX_MODEMS.md` now state
what a green run does **not** cover, and the `CONNECT`-belongs-to-the-dialler rule is recorded as a
rack quirk.

**The pickup is sent in voice mode, armed before the call.** Two rack attempts exposed two orderings
that no test could have:

1. `ATA` sent while the line was still in plain data mode got **no reply at all** — not `ERROR` — and
   left the modem **deaf**: both modems then timed out on `ATH`, because a wedged modem answers
   nothing until it is reset.
2. Arming the mode **between `RING` and `ATA`** traded that for `ATA -> ERROR` in 0.03 s: changing the
   modem's mode mid-call makes it forget the incoming call, and `ERROR` is what "nothing is ringing"
   looks like.

So the callee's prepare step now arms voice mode after `ATZ` (`AT+FCLASS=8`, `AT+VLS=1`, and
`AT+VLS?` must read back `1`), and the pickup is a bare `ATA` during the ring. The caller is never
switched — it keeps dialling in data mode. The unit test's fake modem reproduces both faults (wedges
on a bare `ATA`, forgets the call on a mid-ring mode switch), so either regression fails in CI.

**A failed call no longer fails twice.** The release ran as a scored step even when the call had
already failed, so one fault reported as two red rows and six wasted seconds on a modem that had
nothing left to say. The release still always runs — a line left off-hook is worse than a noisy
report — but it is recorded as *cleanup* and no longer decides the verdict. It also uses the
documented `AT+VNH=1` with `ATH` as the fallback, per `voice_modem.on_hook`.

**The answer step is now the default** (`--answer:bool:true`). It was behind a flag because the
criterion could never pass; with the criterion fixed there is nothing left for the flag to protect,
and a call that is never picked up was never really proven. A plain run is eight steps: arguments,
open, prepare, dial, ring, **pick up and connect**, hang up. `--answer false` is kept as the opt-out
for the one case where the far end is a device under test that answers on its own.

## Out of scope

**DTMF (TASK-71 goal 2) and voice audio (goal 5) are untouched and stay open.** This fix covers line
state only — dial tone, the call leaving, the ring arriving, the pickup. A green run says nothing
about digits or sound:

- **DTMF:** no form is known to work on this firmware. `+VTS` is not the DTMF command and
  `send_digits` always returns `verified: False` (`fx/dtmf.py`) — a digit reaching the far end has
  never been measured.
- **Voice audio:** capture and playback through a call are not implemented, and the modem is a
  fax/data modem whose `+VSM` audio may terminate in its analog jacks and never surface as ALSA, in
  which case goal 5 needs line-side hardware rather than more software.

The TASK-71 status header was corrected in the same change: it read *"DTMF generation closed
2026-10-07"* while goal 2, §5, §13 and `fx/dtmf.py` all state that no form is proven.

## Third rack run: the callee was off-hook (BUSY)

Arming `AT+FCLASS=8`, `AT+VLS=1` in the callee's prepare step made every dial answer `BUSY`.
The callee printed `\x10d` (DLE d, dial tone) three times then `\x10b` (DLE b, busy tone) and
never `RING`: on this Conexant `AT+VLS=1` connects the modem to the line, so the called line was
off-hook before the call. Prepare now arms `AT+FCLASS=8` only (on-hook); `ATA` in class 8 goes
off-hook by itself. The ring listener also accepts `DLE R`, the voice-mode ring report. The fake
modem now treats `VLS=1` as off-hook and returns `BUSY` to a call to that line, so arming it
again fails in CI.

## Fourth rack run: ATA is refused in voice mode, and no CONNECT can come

With only `AT+FCLASS=8` in prepare the call rang (`DLE R` 5.2 s after the dial), then `ATA`
answered `ERROR` at once and the caller ended on `NO CARRIER`. Read together with the second run
(`RING` → `FCLASS=8` → `VLS=1` **OK in 0.31 s** → `ATA` `ERROR`): `AT+VLS=1` during the ring is the
pickup, and `ATA` is not accepted in class 8 on this firmware. The pickup is now `AT+VLS=1` (+ `AT+VLS?`
must read `1`). A voice pickup also gives the data-mode caller no `CONNECT` — there is no carrier —
so "CONNECT on the dialling modem" could never pass. A new step, *Call connected end to end*, proves
the call on the line: the called line hears no dial or busy tone for the hold time (it joined the
call rather than going off-hook alone), the caller has not dropped, and when the caller hangs up the
called modem hears it (`DLE b`/`DLE d`). The dial reads 12 s instead of 45 s when answering, so the
caller hangs up long before its own carrier timeout. 22 unit tests.

## Verification

- `pytest tests/backend_host/test_fixnet_call_script.py` — 20 passed after the off-hook fix (19 before it) (was 10, with the answer case
  proving nothing). Tests assert the default is eight steps, that `--answer false` sends no `ATA`,
  that the callee's prepare step arms voice mode before the dial while the caller is never switched,
  that a mid-ring mode switch loses the call (so moving it back fails), and that the release after a
  failed call cannot decide the verdict.
- `pytest tests/backend_host/test_fixnet_call_script.py tests/backend_host/test_fixnet_profile.py tests/backend_host/test_fx_remote.py` — 74 passed.
- `scripts/docs/check_bug_ids.sh`, `scripts/docs/check_bug_meta.py`,
  `scripts/release/check_release_notes.py` clean; the pre-push leak gate and review gate pass.
- **Proven on the rack, 2026-10-22 (fifth run): 9/9 steps PASS**, `/dev/fx3 → /dev/fx4`, hold 5 s.
  `DLE R` 4.7 s after the dial → `AT+VLS=1` `OK` (0.31 s) → `AT+VLS?` `1`. While held, the called
  line reported only `DLE e` (the caller's 1300 Hz data calling tone — the caller's audio reaching
  the callee) and no dial or busy tone. The caller had not dropped; its hang-up (`AT+VNH=1`, which
  answered `NO CARRIER` because it aborted the dial in progress) reached the callee as `DLE b` 1.9 s
  later. Both modems released with `AT+VNH=1` `OK`. TASK-71 goal 3 is done.