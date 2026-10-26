# BUG-0649 — vpt-pi1's onboard BLE adapter goes DOWN: stb4 keys are lost or take 15-20 s

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0649 |
| Reported  | 2026-10-19 |
| Status    | Fixed (mitigated by hand: adapter up + daemon restart; detection not built) |
| Severity  | Medium |
| Area      | backend_host / BLE remote (vpt-pi1, stb4) |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

> **Rule (owner, 2026-10-19): no BLE key loss has been found** (94 of 94 keys, 0 link drops, also under saturated Wi-Fi; see the last section). The failures below coincided with the `hci0` hang. Do not blame BLE for a later stb4 failure without a journal drop at that time.

## Symptom

TASK-133: stb4 validation runs failed at `home_tvguide → home_apps` (`apps_red` score 0.000), with `no BLE peer connected after wake`
(37 s), `press_key` answered 504, `get_pairing_status` showed `connected: false`, `resume_state: idle`, bond present.

## Root cause

The Pi's onboard Bluetooth controller (`hci0`, UART) stopped answering: `dmesg` showed `Bluetooth: hci0: Opcode 0x0c03 failed: -110`
(HCI reset timeout) after many `Opcode 0x0c2d failed: -22`, and `hciconfig hci0` read **DOWN**. Every HCI command of `hid-remote@hci0`
then failed with `Invalid device: Network is down`, so neither the directed wake advert nor `cold_wake` could go out. Even after the adapter
was up again, the link dropped between presses and each key waited 14-20 s ("peer connected after wake"); that is longer than the 3 s
verification window, so the focus had not moved when the check ran (frame shows the focus still on TV Guide).

Nothing in `get_pairing_status` says the adapter is down.

## Fix / workaround

`ssh vpt-pi1 'sudo -n hciconfig hci0 up'`, then `sudo -n systemctl restart hid-remote@hci0 hid-agent@hci0` (not `bluetoothd`; never pair).
After that `apps_red` passed 5 of 8 tries (about 1 of 6 before). Also in the tree: the `home_apps` node and the Apps-grid tile nodes
waited 0 ms; `home_apps` now waits 3 s.

## Not done

`get_pairing_status` should report the adapter state (`hciconfig`-level), and the host should bring a DOWN adapter up itself.

## Verification

`dmesg | grep hci0`, `hciconfig hci0` UP RUNNING, ten `home → home_tvguide → home_apps` navigations on stb4 and a `validation` run.

## Wi-Fi coexistence test (2026-10-19, TASK-133; "is Wi-Fi the cause?")

The owner suspected Wi-Fi: `hci0` is the onboard BCM4345C0, one chip and one antenna with `wlan0`, and vpt-pi1 has no Ethernet (`eth0` DOWN).
**Verdict: not proven, and not reproducible on the current setup. Wi-Fi load did not cost a single key.**

State of the radio (vpt-pi1, 09:00-09:40): `wlan0` is already on **5 GHz** (`AKSunrise_0358314_5GHz`, channel 60, -61 dBm, tx 351 / rx 263 Mbit/s,
481 tx failed of 1.88 M packets = 0.03 %). So a move to 5 GHz is not an available fix; it is already the case. Normal traffic is about 4 Mbit/s out, 2 in.
vpt-mf1, for comparison, uses two USB Broadcom dongles (`hci1`, `hci2`, a separate radio from its Wi-Fi card) on a 2.4 GHz channel 11 network; its journal is not readable by the ssh user, so no drop count.

Controlled bursts on stb4 (Apps grid, LEFT/RIGHT alternating, screen change on the capture thumbnail = key arrived; latency floor 1.0 s is the thumbnail refresh):

| Burst | Setup | Keys | Lost | Link drops | Latency median / max |
|---|---|---|---|---|---|
| A | current, 3 s between keys | 50 | 0 | 0 | 1.0 s / 1.4 s |
| C | `wlan0` saturated by a 77 Mbit/s download, 3 s between keys | 30 | 0 | 0 | 1.0 s / **10.3 s** (one key) |
| D | 30 s between keys (idle link) | 14 | not measured (script output lost) | 0 (journal: 14 injections 31 s apart, no `Connected=False`, no `dev_disconnected`) | n/a |

Since the 07:53 reboot (1 h 50 min) `journalctl -u bluetooth -u hid-remote@hci0` shows **one** `Connected=True` and **no** drop.
Not tested: moving the remote to `hci1` (the Realtek dongle cannot take the STB's bonded address; a re-pair at the STB is needed, an owner physical action), a cable on `eth0` (physical), a Take Control live stream running at the same time (the 2026-10-14 drops, §6.7.35, were all during streams).

What the data does say:
- The hang of `hci0` (this bug) was the cause of the lost keys in the TASK-133 runs; after the adapter was up and the host rebooted, 94 of 94 keys arrived.
- One key took 10.3 s while Wi-Fi was saturated: a single sample, and the Pi was at the same time CPU-bound (load 12 on 4 cores: three ffmpeg captures, `tesseract`, the monitor `python`). CPU starvation of `hid-remote` is as plausible as radio contention; this test cannot tell them apart.
- `bluetoothd` logs about 650 `Endpoint registered` lines in 30 min from short-lived D-Bus clients (the login user's pipewire/wireplumber session): noise, not tied to any drop. It was the WirePlumber Bluetooth monitor retrying and later cost bluetoothd 40-90 % CPU: see BUG-0939.

Options, recommended first:
1. Run stb4 as it is and watch for drops with the §6.7.35 journal check; the adapter hang was the real defect. A drop that shows up again during a Take Control stream points at coexistence.
2. Give `hid-remote@hci0` CPU priority (systemd drop-in `Nice=-5`) so a loaded Pi cannot delay keys. Reversible; untested.
3. Cable on `eth0` (owner, physical): the clean fix if drops return under streaming.
4. Dongle with a settable address (Broadcom, as vpt-mf1) or a re-pair onto `hci1` (owner at the STB).
