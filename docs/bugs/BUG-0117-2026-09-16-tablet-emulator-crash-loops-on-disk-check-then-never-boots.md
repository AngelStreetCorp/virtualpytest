# BUG-0117 — The tablet emulator crash-looped on its own disk check, then spent 90 minutes in the boot animation

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                         |
|-----------|-----------------------------------------------------------------------------------------------|
| ID        | BUG-0117                                                                                        |
| Reported  | 2026-09-16 (Dashboard: labox-tablet stuck on the boot logo, labox-mobile showing "System UI isn't responding") |
| Status    | **Fixed on the fleet; installer change pending deploy.**                                        |
| Severity  | High (two of the three emulator devices unusable for ~2 h after a routine service restart)      |
| Area      | `setup/proxmox/vm/runner/install_android_emulator.sh`, `setup/proxmox/vm/backend-host/optimize_emulator.sh`, AVD `config.ini` on the labox hosts |
| Fixed in  | build 9151                                                                                     |

| Commit    | `dea2fca924`                                                                                   |

---

## Symptom

Right after the emulator-audio rollout (`enable_emulator_audio.sh` restarts `vpt-emulator.service`),
the Dashboard showed `labox-tablet` on a white Google boot screen and `labox-mobile` with a
"System UI isn't responding" dialog. Ninety minutes later the tablet was still on the boot screen.
`systemctl` said every unit was `active`, QEMU was registered on the PulseAudio daemon, and the
stream was writing frames — of the boot logo.

## Root cause

Three things, in sequence.

**1. The emulator's own free-space check.** The tablet VM has a 30 GB disk holding
`/opt/android-sdk` (9.2 GB), the AVD (6.1 GB) and the checkout; it had 6.1 GB free. The first five
starts after the restart died in two seconds each:

```
INFO         |   Checking: hasSufficientDiskSpace
INFO         |      Error: Your device does not have enough disk space to run avd: `vpt_tablet`
FATAL        | Your device does not have enough disk space to run avd: `vpt_tablet`.
systemd[1]: vpt-emulator.service: Main process exited, code=exited, status=1/FAILURE
systemd[1]: vpt-emulator.service: Scheduled restart job, restart counter is at 5.
```

The sixth attempt passed — a few hundred MB had been released in the meantime — which is why the
unit looked healthy afterwards. The check compares free space against what the AVD's qcow2 overlays
could still grow to, so a host that hovers around that line crash-loops on *every* restart.

**2. A one-core guest on an oversubscribed node.** `vpt_tablet` and `vpt_mobile` both had
`hw.cpu.ncore = 1` — `avdmanager`'s default for their device profiles, and already flagged in
`EMULATOR.md` as "the weakest of the three, and the one that ANR'd". The Proxmox node was at load
48 on 24 cores; the guests saw 45–70 % CPU steal. Inside the tablet, `zygote64` was verifying
bytecode at **25–44 bytecodes per second**:

```
W zygote64: Verification of void android.bluetooth.BluetoothHeadsetClient.setAudioRouteAllowed(...)
            took 3.844s (24.97 bytecodes/s)
```

while the boot animation rendered 1600×2560 through swiftshader on the same core. Not crashed —
starved. The mobile, with the same one core, booted in five minutes and then ANR'd its SystemUI
on the post-boot storm of Google services (`/data/anr/` traces at 10:59 and 11:10).

**3. Dialogs outlive the problem.** An ANR dialog belongs to `system_server` and stays on screen
until someone taps *Wait*; the capture records it in place of the device. On the tablet the
`com.android.systemui` dialog survived a *Wait* tap, `am force-stop com.android.systemui`,
`CLOSE_SYSTEM_DIALOGS` and a sleep/wake cycle.

## Fix

- **Disk:** `qm resize 173 scsi0 +20G`, then `growpart` + `resize2fs` online. The tablet has
  50 GB with 25 GB free, like the mobile.
- **Cores:** `hw.cpu.ncore = 4` in both AVDs' `config.ini` (backups `config.ini.bak-ncore1`).
  The installer now writes `hw.cpu.ncore = 4` and `vm.heapSize = 576M` — the TV host's known-good
  values — after creating an AVD, idempotently, so a fresh host is not born on one core.
- **Dialogs:** `settings put global hide_error_dialogs 1` in both guests, persisted in userdata;
  `optimize_emulator.sh` sets it too. ANRs still land in logcat and `/data/anr/`.
- The vpt-stream service on the tablet, which had never been restarted since 2026-09-03 and was
  still running the audio-less grabber, was restarted with the emulator.

## Verification

| Host | Before | After |
|---|---|---|
| labox-tablet boot | 90 min in boot animation, `sys.boot_completed` empty | **45 s**, `/sys/devices/system/cpu/online` = `0-3` |
| labox-mobile boot | ~5 min, SystemUI ANR on screen | 2 min, launcher in focus |
| Post-boot ANR storm | continued for the whole window | 15–17 ANRs in the first minute after boot, none afterwards |
| Tablet segments | `h264` only | `h264 aac` |
| QEMU on `vpt-pulse` | 1 client (mobile), 1 (tablet) | unchanged |
| Tablet disk | 30 GB, 6.1 GB free | 50 GB, 25 GB free |

Not fixed here, recorded so it is not re-investigated: the Proxmox node's load. Each emulator host's
imagefile grabber costs about 3 vCPU with or without audio (the tablet's audio-less one ran at 259 %);
audio adds ~0.5 vCPU of PulseAudio (with recurring `q overrun, queuing locally`) plus ~0.6 vCPU of
encode per host. Three hosts of that on a 24-core node is where the steal comes from.

## Not a finding

The `403 Forbidden` in the host-clone-1 and labox-web previews in the same screenshot was the
BUG-0107 VNC allowlist rejecting the operator's current egress address, not the audio work. The
address was added to the `$vnc_client_allowed` map on the proxy.
