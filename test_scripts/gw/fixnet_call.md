# Fixnet call (`fixnet_call`)

## Purpose

Places one call from one Fixnet FX voice modem to another through the gateways and proves the call arrived: the called modem has to see `RING`. Each phase is its own report step, so a failure says which part broke (modem, dial tone, network, far end).

Part of [TASK-71](../../docs/tasks/TASK-71-fixnet.md) goals 3 and 4 (outgoing call, line state).

## Target Environment

- Host-targeted; runs on the Linux host that has the FX modems (the client's PFR).
- Needs `pyserial` and `/dev/fx1`..`/dev/fx4` from `install_fixnet_prereqs.sh` (udev names by USB port).
- Nothing else may hold the two ports (stop any `picocom`, `fixnet_call_test.py`, or bench script on them).

## Usage

```bash
# defaults come from the host .env (see "Defaults" below)
python test_scripts/gw/fixnet_call.py

# the other direction (dial the CLI of the CALLED line)
python test_scripts/gw/fixnet_call.py --from_fx /dev/fx4 --to_fx /dev/fx3 --number <CLI of fx3>

# ring, pickup and connect are the default — nothing to pass
python test_scripts/gw/fixnet_call.py

# only if the far end is a device that picks up on its own: ring only, no ATA
python test_scripts/gw/fixnet_call.py --answer false
```

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--from_fx` | string | `/dev/fx3` | Calling modem |
| `--to_fx` | string | `/dev/fx4` | Called modem |
| `--number` | string | `env` | CLI to dial: the number of the **called** line, not a modem name. `env` = `FIXNET_NUMBER` from the host `.env` |
| `--hold` | int | `5` | Seconds to keep ringing (or to hold the call once it is connected) before hanging up |
| `--answer` | bool | `true` | The called modem picks up (`ATA`) and the dialling modem must report `CONNECT` — that is the normal way a call goes, so it needs no flag. Pass `false` only when the far end is a device under test that answers on its own; the run then stops at `RING` and sends no `ATA` |

## Defaults

The rack's real numbers are customer data, so they are not in this repo. `--number env` (the default) reads `FIXNET_NUMBER`
from the host's environment. Put it in the host `.env` (`backend_host/src/.env`) and **restart `vpt-host`** once: a host
process only reads its `.env` at start. Or pass the number in the Run form and skip the `.env`.

```
FIXNET_NUMBER=<CLI of the called line>
```

The lab's own table (which modem has which CLI) belongs in the customer overlay, not here.

## What the script needs on the host

- **Just the script**, plus code the host already has: `shared/.../script_decorators` and
  `backend_host/src/controllers/remote/fx/at_channel.py` (the FX controller, TASK-71), both imported from the repo root, and `pyserial`.
  As a virtual script no `_script_libs` is needed.
- `/dev/fx1`..`/dev/fx4` from `install_fixnet_prereqs.sh`, and nothing else holding the two ports.

## Steps (one report step each)

Each step lists its **actions** (every AT command, which modem sent it, the reply, how long it took) and its **verifications** (the checks below, each pass/fail with a detail).

| # | Step | Verifications |
|---|---|---|
| 1 | Check arguments | calling and called modem differ; a number is given; settings (hold, answer, country code) |
| 2 | Open both modems | each serial port opens |
| 3 | Prepare caller modem | reset (`ATZ`); country code set and read back (`AT+GCI?` must equal the code); dial-tone detection on (`ATX4`); firmware (`ATI3`). Stays in data mode — it dials |
| 4 | Prepare callee modem | the same, then **voice mode armed for the pickup**: `AT+FCLASS=8` only (the line stays on-hook). Done here, before the call, not between `RING` and the pickup. Never `AT+VLS=1` here: it takes the line off-hook and the dial answers `BUSY` |
| 5 | Dial `<number>` from `<from_fx>` | dial tone on the calling line (no `NO DIALTONE`); the network accepted the call (no `BUSY`, `NO ANSWER`, `NO CARRIER`; still ringing counts as accepted) |
| 6 | RING on `<to_fx>` | the called modem saw `RING` or `DLE R` (with how many seconds after the dial) |
| 7 | Callee answers | the pickup `AT+VLS=1` sent during the ring is accepted, and `AT+VLS?` reads back `1` (off-hook). Skipped only with `--answer false` |
| 8 | Call connected end to end | the called line hears **no** dial or busy tone (`DLE d` / `DLE b`) for `--hold` seconds, so it joined the call instead of going off-hook on its own; the calling modem has not dropped (`BUSY` / `NO CARRIER`); then the caller hangs up and the **called** modem must hear it (`DLE b` or `DLE d` within 15 s). Skipped with `--answer false` |
| 9 | Release both modems | `AT+VNH=1` on both, falling back to `ATH`. After a failed call this is **cleanup**: it still runs, but it does not decide the verdict, so one fault is one red row |

The overall result is pass only if every step passes.

## What this script does not do

A pass covers **line state**: dial tone, the call left, the ring at the far end, the pickup, and the
connection. Two things a phone test would normally do are not attempted, so a green run says nothing
about them:

- **No digits.** It never sends DTMF. `+VTS` is not the DTMF command on this firmware and no form is
  known to reach the far end, so how a device handles dialling an extension or entering a PIN is
  untested ([TASK-71](../../docs/tasks/TASK-71-fixnet.md) §5, goal 2).
- **No audio.** It captures no sound, so a device that answers with silence is a pass here. Voice
  capture and playback are not started (goal 5), and may be blocked in hardware rather than in
  software.

## Reading a failure

| Failed step | Meaning |
|---|---|
| Dial: `NO DIALTONE` | the line behind the calling modem is dead: cable, patch, or gateway FXS port not registered. Test with `ATX4` + `ATDT` in `picocom` |
| Dial: `NO CARRIER` or `BUSY` | the network refused the call: wrong number, or the called gateway line is unregistered (a mobile calling it hears the mailbox) |
| RING missing but dial OK | the number belongs to another line than `--to_fx`; check the CLI-to-modem table above |
| Prepare: `AT+GCI` fails | firmware without `+GCI`; the modem may report `DIGITAL LINE DETECTED` and refuse the FXS loop (it boots on the US profile, `B5`) |
| Answer: `AT+VLS=1` refused | the called line rang but did not pick up — check step 4 armed voice mode (`FCLASS=8` OK), and that nothing reset the line mid-ring |
| Connected: dial or busy tone while held | the callee went off-hook but not into the caller's call (the pickup came after the ring ended, or the gateway did not bridge it) |
| Connected: the callee never hears the caller leave | the two lines were not in one call; the detail lists every line the callee saw |
| Connected: the caller dropped first | the call ended (`NO CARRIER` / `BUSY` on the caller) before the caller hung up: the gateway dropped it |

## Notes

- `AT+GCI=A6` (Switzerland) is sent on every run; `ATZ` returns the modem to the US profile `B5`. Override with the env var `FIXNET_GCI`.
- The call is dialled in plain data mode with `ATX4` (dial-tone check). The voice-mode dial (`+FCLASS=8`, `ATDT…;`) answers `OK` without saying whether anything happened and prints stray `f` characters on this firmware.
- **Answering:** the called line is armed in voice mode during prepare (`AT+FCLASS=8`, after `ATZ` which clears it; not `AT+VLS=1`, which takes the line off-hook so the dial gets `BUSY` and the callee hears `DLE d` then `DLE b`), and the pickup is `AT+VLS=1` sent during the ring. Every other ordering was proven wrong on the rack (2026-10-22): an `ATA` in data mode gets **no reply at all** and leaves the modem deaf; switching mode *between* `RING` and the pickup makes the modem forget the call; and `ATA` in voice mode answers `ERROR` at once — this firmware does not accept it in class 8. A voice pickup gives the data-mode caller **no `CONNECT`** (there is no modem carrier), so the dial reads only 12 s (refusals come within ~7 s) and the connection is proven on the line instead (step 8): the called line hears no dial tone while held, and hears the caller hang up. Both channels drop their pending lines before every hang-up, or a late line would be read as the hang-up's reply. First full pass on the rack 2026-10-22 (`fx3 → fx4`, 9/9): while held the callee saw only `DLE e` (the caller's calling tone), and the caller's hang-up reached it as `DLE b` 1.9 s later.
- The older bench tool `setup/local/linux/backend_host/fixnet_call_test.py` (`call`, `ring`) does the same by hand, outside VirtualPyTest.

## Test report and debug data

The run report has three layers, like `superping` and `dns_lookuptime`:

- **Execution summary**: the important facts only: host, call (from, to, number), modem firmware and country code, whether the called modem rang and after how long, the dial result in words, steps passed, and the first failed step.
- **Test steps**: one block per step above with its **actions** (`[caller /dev/fx3] ATDT… -> …(0.31s)`) and **verifications**, with real start, end and duration.
- **Execution logs** (host stdout): every AT exchange as it happens (`[caller /dev/fx3] > ATZ`, `< OK (0.31s)`), the step results, and the RING listening. This is where to look when a step fails.

A dial with no result code is the far end ringing, and is reported as such. A stray `RING` that arrives while a command runs is noted, not shown as the command's reply.

`script_results.metadata` holds `from_fx`, `to_fx`, `number`, `answer`, `hold`, `country_code`, `caller_firmware`, `callee_firmware`, `dial_reply`, `rang`, `ring_after_s`, and with the default answer step also `answer_reply`, `connected` (the dialling modem saw `CONNECT`), `connect_after_s` and `callee_connect`, plus `steps` (name, ok, seconds), `host_name`, and `transcript`: the full time-ordered list of every AT exchange `{t, who, cmd, ok, reply, dt}` (plus `wait/matched/seen` for RING listening, and `drain` before each hang-up).

Unit tests: `tests/backend_host/test_fixnet_call_script.py` (two simulated modems and a simulated network; no hardware).
