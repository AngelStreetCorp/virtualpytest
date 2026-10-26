# BUG-0434 — No IR on the Minisforum: lirc never produces a node the host can use

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0434                                                     |
| Reported  | 2026-10-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / setup                                              |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On the x86 Minisforum host (`vpt-mf1`, Debian 13, kernel `6.12.86+deb13-amd64`) the USB IR
Toy is plugged in and enumerated, but IR does nothing:

```
$ sudo ls /dev/lirc*
ls: cannot access '/dev/lirc*': No such file or directory
```

`lsusb` shows the dongle healthy (`ID 04d8:fd08 Microchip Technology, Inc. USB Infrared
Transceiver`, manufacturer `Irdroid`), and lirc is installed and running — `lircd.service`
active, the `irtoy` plugin present in `/usr/lib/x86_64-linux-gnu/lirc/plugins/`. The host
log nonetheless reported the IR remote as unusable, and the Take Control IR dot stayed red.

## Root cause

Not a Raspberry Pi, and the assumption in the lirc transport is Pi-specific.

1. **`vpt-mf1` is not a Pi.** Micro Computer (HK) "Venus Series", i9-13900H, native x86_64,
   no `/proc/device-tree`, no GPIO, no `/boot/firmware/config.txt`. Every Pi remedy
   (`dtoverlay=gpio-ir-tx`, a GPIO `ir_toy` node) is inapplicable by construction.
2. **The kernel has no IR support for this dongle.** `grep CONFIG_IR_TOY /boot/config-…`
   reports `# CONFIG_IR_TOY is not set`, and `CONFIG_RAW_RC` is absent too. `modprobe
   ir_raw` → *module not found*. So nothing publishes an rc-core node or a legacy
   `/dev/lirc*`.
3. **The dongle is claimed as a serial port, not as IR.** Its two interfaces are CDC
   (Communications/Abstract-modem + CDC Data), **not HID**, so the `ir_toy` *HID* driver
   could not bind it even if it were built — a CDC-only dongle. `cdc_acm` takes both
   interfaces, producing `/dev/ttyACM0`.
4. **lirc's userspace `irtoy` plugin works but has no character device.** Running
   `lircd --driver=irtoy --device=/dev/ttyACM0` reaches `lircd(irtoy) ready`, so the port
   is usable — but no `/dev/lircN` is ever created (checked at `notice` and `debug`
   loglevel). lirc exposes userspace drivers only through its Unix socket, whose protocol
   carries `SEND_ONCE`/`SEND_START`/`SEND_STOP` and **no raw-pulse command**.
5. **The host controller cannot use that anyway.** `IRRemoteController` talks exclusively
   to the rc-core API (`infrared.py`: `ir-ctl --device <IR_PATH> --features` / `--send`).
   With no rc-core node, every send fails.

Two installer bugs compounded it:

- `setup_permissions.sh` normalised only `/dev/lirc*`, which never exist on this host, so
  the service user had no route to the serial node.
- `install_host.sh` gated LIRC setup on `command -v lircd`, but `lircd` lives in `/usr/sbin`,
  which is not on a non-login `PATH` — so an unprivileged run silently took the "lirc not
  installed" branch.

## Fix

A third IR transport that needs neither the kernel nor lirc: `IRToyRemoteController`
(`backend_host/src/controllers/remote/irtoy.py`) writes the waveform straight to the CDC
serial port using the IrToy's own protocol, mirroring lirc's `plugins/irtoy.c`
(`s` → `S<proto>`, `0x24`/`0x25`/`0x26`, then `0x03` + credit-paced timing buffer +
`t <count> C` result). Keymaps are the same `ir_conf/<type>.json` the lirc transport uses.

- Selected by `DEVICE{n}_IR_SERIAL`, alongside the existing `IR_PATH` (lirc) and `IR_IP`
  (IRTrans). All three resolve from the single frontend `remote_type:'ir_remote'`:
  `host_utils.py`, `controller_config_factory.py`, `controller_manager.py`,
  `controllers/__init__.py`, `device_capabilities.py` (`EXTERNAL_REMOTES`), and
  `shared/src/lib/models/device.py` — the last carries an explicit branch, which its own
  comment requires for any new remote class.
- `install_host.sh` now detects Pi vs non-Pi, and on a non-Pi host with the dongle present
  installs `udev/95-vpt-irtoy.rules` (stable `/dev/irtoy`) and adds `vpt_user` to `dialout`.
- `setup_permissions.sh` adds `vpt_user` to `dialout`; the `lircd` gate is fixed to use an
  explicit `/usr/sbin/lircd` fallback.
- Docs: new `INFRARED.md` § 2c (transport) and § 6.4 (troubleshooting); `REQUIREMENTS.md`
  also drops `ir-keytable`, which does not exist on current Debian (`ir-ctl` replaced it).

Two implementation traps were found by testing against the real dongle, and are commented
in the code and docs:

- `termios.B115200` is **not** `115200` on Linux (octal-encoded, `== 4098`); a raw integer is
  an invalid speed and `tcsetattr()` fails with `EINVAL`. Python's `termios` has no
  `cfsetispeed`, so the speeds go into the `tcgetattr` list at indexes 4 and 5.
- The udev rule must be `SUBSYSTEM=="tty"` + `ATTRS{}`. A `SUBSYSTEM=="usb"` rule symlinks
  the raw USB device node (`/dev/bus/usb/003/010`), which is not a serial port, and `ATTR{}`
  never matches because `idVendor`/`idProduct` live on the USB parent.

## Verification

Verified on `vpt-mf1` (Micro Computer HK Venus, i9-13900H, Debian 13, kernel 6.12.86),
deploying the feature onto the real host — not a temp copy:

- udev rule installed; `readlink -f /dev/irtoy` → `/dev/ttyACM0`, a character device,
  `root:dialout 0660`.
- The host's effective env turned out to be **`backend_host/src/.env`**, not
  `/opt/virtualpytest/.env` — `app.py` runs from `backend_host/src` and both files are
  merged per key, so an edit to the top-level `.env` partly applied and looked like it
  worked. The real block configured three Apple TVs, **all three pointing at
  `IR_PATH=/dev/lirc0`** — the exact node that can never exist here, so all three IR
  panels were dead. Now: `DEVICE1_IR_SERIAL=/dev/irtoy`, and IR disabled on device2/3
  (one physical dongle cannot back three controllers on the same serial port).
  A duplicated `DEVICE3` block in that file was also collapsed.
- After `systemctl restart vpt-host`: `[@controller:IRToyRemote] Initialized for serial
  device: /dev/irtoy` / `Loaded 19 keys from apple_tv.json`, with `ir_remote` and
  `irtoy_remote` correctly skipped on device2/3.
- Through the **real authenticated route** (`POST /host/remote/executeCommand`,
  `X-API-Key`), `get_pairing_status` returned `healthy: true`,
  `detail: "IR ready (/dev/irtoy, apple_tv, irtoy)"`, `transport: irtoy` — the green dot.
- **Live transmit, full loop:** seven `press_key` calls in a row
  (`UP, LEFT, RIGHT, OK, MENU, POWER, HOME`) — every one returned `success: true`, and
  the post-loop health stayed `last_send_ok: true, healthy: true`. This is the case that
  was never clean before.
- **Restart-survival regression:** restarted `vpt-host` mid-session; health after
  restart is `healthy: true`. The per-burst close (`2c677d0bb`) prevents the
  cache-the-fd wedge that previously took down the dongle on every restart.

### Bugs the live run found (none were visible from the code alone)

1. **An extra byte was read before the transmit result.** The credit loop already
   consumes the final credit; the extra 1-byte read stole the `t` count indicator, so the
   reply decoded as `b'\x00\x8a C\x00'` — `C` one byte early, `0x8a` = 138 = the payload
   length. The burst had in fact been transmitted. Commit `2c677d0bb` was *titled* as
   the fix but the diff never actually touched `_transmit` — only `press_key` (per-burst
   close) and a comment changed. The extra read stayed, and the title was wrong. Fixed
   in `53ac55220` by deleting the extra read; verified with seven back-to-back
   `press_key` calls all returning `success:true`.
2. **Caching the serial fd between presses wedged the dongle.** Sample mode streams, so
   restarting `vpt-host` while the fd was open meant the IRMAN reset never reached the
   firmware; the dongle went deaf, and recovering it needed driver rebind, then a USB
   re-enumeration that itself dropped the device (`usb 3-9: can't set config #1,
   error -71`, no `ttyACM*`). `press_key` now opens and closes the port per burst, which
   makes a restart harmless — verified by restarting vpt-host with the dongle attached
   and confirming health stayed `healthy: true` afterwards. Recovery ladder documented
   as INFRARED.md § 6.5.

Also: **the previous commit's stale bytecode** kept the bug masked for a day. The .pyc
on the host had a newer mtime than the .py, so Python used cached bytecode that
corresponded to the pre-fix code even after `2c677d0bb`. Fixed on this deploy by
deleting `__pycache__/irtoy.cpython-313.pyc` alongside the rsync; worth knowing that a
`rsync -t` of a Python module can leave the .pyc ahead of the .py and silently keep the
old version running.

The dongle is currently in the wedge state of that ladder and **needs a physical
unplug/replug**; once it is back, re-run the two `curl` checks above.