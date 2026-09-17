# BUG-0086 — Android emulator boots with a black display, stream shows nothing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                        |
|-----------|------------------------------------------------------------------------------|
| ID        | BUG-0086                                                                     |
| Reported  | 2026-09-14 (labox-dongle streamed a black picture for ~2h)                    |
| Status    | Fixed (deployed to labox-dongle, labox-mobile, labox-tablet)                  |
| Severity  | High (the device looks alive and online, but every capture, verification and report screenshot is black) |
| Area      | backend_host/scripts/emulator_screencap.sh · backend_host/config/services/linux/emulator-fifo.service |
| Fixed in  | build 8887                                                                   |

---

## Symptom

`labox-dongle` showed a black stream in the Devices page. Everything else looked healthy:

- `vpt-stream`, `vpt-host`, `vpt-emulator` and `vpt-emulator-fifo` all `active`;
- ffmpeg writing captures at 5 fps, HLS segments rolling, `latest.png` updating every 200ms;
- `adb devices` listed `emulator-5554`, `dumpsys power` said `mWakefulness=Awake`,
  `dumpsys display` said `mState=ON`, and the TV launcher held focus.

The only tell was the frame size: every capture was byte-identical at 24683 bytes (a black
1920x1080 JPEG); a live frame is ~110 KB.

## Root cause

Not the capture pipeline. `adb shell screencap -p /sdcard/t.png` run *inside the guest* also
produced an all-zero 1920x1080 PNG, so the display itself was black.

`dumpsys SurfaceFlinger` showed an **empty composition list**, with every layer — TV launcher,
wallpaper, all of them — marked:

```
invisible reason=hidden by parent or layer flag
```

while WindowManager still believed the launcher was visible and obscuring the screen
(`mObscuringWindow=Window{… tvlauncher …}`, `ROTATION_0`, `1920x1080`). A WM↔SF desync: the app
kept rendering the whole time (logcat full of HWUI `Davey!` frames and `Choreographer: Skipped
NN frames`), the frames just never reached the display.

The bad state comes out of emulator startup — a race in display init on the Android 16 (API 36)
TV system image under headless `-gpu swiftshader_indirect`. It is **reproducible: 2 of 2**
`systemctl restart vpt-emulator` runs came up black, each booting normally
(`sys.boot_completed=1`) with nothing composed. A restart that comes up healthy is the lucky path,
not the rule.

Power-cycling the guest display forces SurfaceFlinger to re-evaluate layer visibility and the
picture returns immediately:

```bash
adb shell input keyevent KEYCODE_SLEEP; sleep 2; adb shell input keyevent KEYCODE_WAKEUP
```

## Fix

The screencap loop was an inline `bash -c 'while true; …'` in `vpt-emulator-fifo.service`, so it
happily shipped black PNGs for two hours without noticing. It is now a real script,
`backend_host/scripts/emulator_screencap.sh`, which keeps the same 5 fps
`screencap → latest.png` behaviour and adds a self-heal:

- every 30s, sample the current frame and test it for all-zero pixels;
- after two consecutive black samples, send SLEEP+WAKEUP once and log it;
- only act when `dumpsys power` reports `mWakefulness=Awake`, so a device deliberately put to
  sleep is left alone;
- rate-limit recoveries to one per 5 minutes.

`vpt-emulator-fifo.service` now calls the script. The unit also gained a repo template at
`backend_host/config/services/linux/emulator-fifo.service`, which it never had — it existed only
as a hand-written file on each emulator VM.

`vpt-emulator.service` is still *not* templated: it needs the per-host AVD name
(`android_tv` / `vpt_mobile` / `vpt_tablet`), which the template substitution does not carry.
`setup/proxmox/vm/runner/install_android_emulator.sh` writes it inline.

## Verification

Two `systemctl restart vpt-emulator` runs on labox-dongle, both reproducing the black boot:

| Run | Boot completed | Recovery fired | Stream live |
|-----|----------------|----------------|-------------|
| 1   | 19:13:44       | 19:17:15       | 19:17:33    |
| 2   | 19:20:06       | 19:20:34       | 19:20:56    |

Run 1 was late because of a bug in the first version of the script: `last_recovery=0` combined
with bash's `$SECONDS` also starting at 0 meant the 300s cooldown applied to the *first*
recovery, blocking it until the loop had been up 5 minutes. Seeding
`last_recovery=$((-RECOVERY_COOLDOWN))` fixed it — run 2 recovered one check interval after boot.

After recovery: captures at ~111 KB, HLS segments rolling, TV home screen visible with the labox
app in Favorite Apps. Deployed to all three emulator hosts (dongle, mobile, tablet), all three
producing live frames.

## Notes

- A snapshot of a known-good emulator state was considered and rejected: snapshot restore runs
  the same display-init path, restore on headless swiftshader is the flakier of the two, and
  "black screen after loading a snapshot" is a well-known emulator failure mode. The AVDs already
  ask for fast boot (`fastboot.forceFastBoot=yes`); the service's `-no-snapshot` flag overrides it
  deliberately.
- The launcher layer reports portrait bounds (`1080x1920`) on the landscape display even when
  healthy. Unexplained, harmless so far — worth a look if picture geometry ever goes wrong.
- `vpt-monitor` already runs per-frame blackscreen detection, but on this host its metadata JSON
  writes `{"error": "failed_to_save_full_data"}`, so it was not usable as the recovery trigger.
  Worth investigating separately.
