# BUG-0176 — An emulator's screen turned off after 30 minutes idle and its stream stayed black

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0176                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | setup (`optimize_emulator.sh`), Android emulator hosts       |
| Fixed in  | build 90145 |
| Commit    | `cf9e5eb08`                                                  |

---

## Symptom

`labox-mobile`'s tile was black while every service reported healthy and frames were fresh.
`latest.png` was rewritten every second, but it was genuinely black: mean brightness `0`, and so
were the captures and the HLS frames. After someone woke the device the picture came back, then
went black again about 30 minutes later. `labox-dongle`'s TV emulator never did this.

```
dumpsys power                      → mWakefulness=Asleep
settings get system screen_off_timeout → 1800000      (TV emulator: 2147483647)
```

## Root cause

`setup/proxmox/vm/backend-host/optimize_emulator.sh` set `screen_off_timeout` to 30 minutes, to
"prevent the lock screen during tests". A monitored emulator is idle most of the time, so it slept
and streamed black. Nothing woke it: the screencap watchdog in `emulator_screencap.sh` only
power-cycles a black display while the device reports `Awake`. It deliberately leaves a sleeping
device alone, as that may be intended. The TV AVD had been created with the maximum timeout, which
is why only the mobile emulator was affected.

## Fix

- `optimize_emulator.sh` sets `screen_off_timeout 2147483647` (never), so new emulators never sleep.
- Existing emulators need it set once:
  `adb shell settings put system screen_off_timeout 2147483647` plus a wake key. It survives
  reboots. Applied to `labox-mobile` on 2026-09-27; `labox-tablet` still needs it when it's back
  online.
- Documented: `docs/android-emulator-troubleshooting.md` §12 plus a Quick Diagnosis row, and
  `docs/get-started/emulators.md` (setup step and a §5 Verify check).

## Verification

`labox-mobile` after the change: `screen_off_timeout=2147483647`, `mWakefulness=Awake`, and the
source image, captures and HLS frames show the device screen (mean brightness 0.10–0.11 instead
of 0). The tile plays in the app.
