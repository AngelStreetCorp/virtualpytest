# BUG-0002 — BLE remote keys silently dropped when two `hid_remote.py` daemons share one adapter

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0002                                                     |
| Reported  | 2026-07-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / bluetooth                                     |
| Fixed in  | build 8713                                                   |
| Commit    | `bed7e2e07`                                                  |

---

## Symptom

Navigation keys on **stb4** (Arris BLE, vpt-pi1 / hci0) landed only intermittently.
RIGHT pressed 6× from the customer home menu advanced the top-nav focus only ~2–3 tabs.
Controlled tests: 10 presses @5s → 3 landed; 5 presses @15s → 1 landed. The drop rate was
**independent of press spacing**, which ruled out timing/debounce.

Nothing reported an error. The controller (`vpt-host`) logged
`Remote[BLUETOOTH]: Sent RIGHT` + `press_key: SUCCESS (~12ms)` for **every** press — all FIFO
writes succeeded — while the daemon journal showed `Injecting 0x00XX` for only ~30% of them.

## Root cause

**Two `hid_remote.py` daemons were serving the same adapter**, both reading
`/tmp/hid_remote-hci0.fifo`:

| Unit | Type | PID | Started |
|---|---|---|---|
| `hid-remote@hci0.service` | enabled template | 3973803 | Jun 26 08:40 |
| `hid-remote-hci0.service` | **transient** (`systemd-run`) | 81839 | Jun 26 20:23 |

`fifo_reader_thread` sits in a blocking `open(FIFO, 'r')`. Every controller write unblocks
**both** readers, and the kernel delivers the line to exactly **one** of them. Only the daemon
holding the STB's GATT subscription actually emits a report, so every line won by the other was
swallowed — with no error on either side.

The transient units were legacy stragglers from before the unit rename that introduced the
`hid-remote@.service` template. Both `start.sh` and `resume.sh` already stop the old
`hid-remote-<hci>.service` names, but that self-heal only fires when those scripts run — neither
had run on these hosts since the upgrade, so the pre-rename daemons simply kept living
alongside the new ones for ~3 weeks.

The same duplication existed for `agent.py` (`hid-agent-hci0` transient vs `hid-agent@hci0`
enabled), and on **both** Pis — vpt-pi1 and vpt-pi3.

### Two traps this bug sets for the next debugger

1. **`fuser` / `lsof` on the FIFO shows ZERO openers even with two daemons attached.** A reader
   parked inside a blocking `open()` holds no fd yet. Absence of openers is *not* evidence of
   absence of readers. `ps` for `hid_remote.py` is the only reliable check.
2. **Tailing one unit's journal makes it look like keys vanish.** Watching only
   `hid-remote@hci0` shows ~30% `Injecting` and implies 70% were lost in transport. Summing
   *both* units accounts for 100% — nothing is lost at the FIFO layer; it is split.

The stray is **not** identifiable by age: on vpt-pi1 the transient was newer than the enabled
unit (Jun 26 20:23 vs 08:40), on vpt-pi3 it was older (Jun 24 vs Jun 25). Only
`systemctl list-unit-files` (`transient` vs `enabled`) distinguishes them.

## Fix

`backend_host/src/controllers/remote/bluetooth/hid_remote.py` — added an exclusive per-adapter
run lock (`acquire_run_lock()`, called as the first statement of `main()`):

- `flock(LOCK_EX | LOCK_NB)` on `/run/vpt-ble/hid-remote-<adapter>.lock`; a second daemon for the
  same adapter exits 1 with a message naming the holder PID, instead of silently halving the key rate.
- Runs before any D-Bus/GATT/FIFO work — a duplicate that reached GATT registration or the FIFO
  would already be stealing keys.
- `/run` is root-owned and tmpfs-backed, so the lock can't be squatted and never survives a reboot.
  `flock` is released automatically on process death, including SIGKILL — no stale-lock recovery needed.
- The lock file is opened `O_RDWR|O_CREAT`, never mode `'w'`: `'w'` truncates on open, so a second
  daemon would erase the holder's PID before it could read it and the collision message would name
  no culprit.

No change was needed in `start.sh` / `resume.sh` — both already stop the legacy transient units.

Runtime cleanup applied to both Pis (`systemctl stop hid-remote-hci0.service hid-agent-hci0.service`).

## Verification

6 × RIGHT, 15s apart, counting `Injecting` per unit on vpt-pi1:

| | `hid-remote@hci0` (enabled) | `hid-remote-hci0` (stray) |
|---|---|---|
| Before stopping stray | 4 / 6 | **2 / 6** |
| After stopping stray  | **6 / 6** | 0 |

Total was 6/6 in both runs — confirming the keys were split, never lost. The BLE link
(`AA:BB:CC:DD:EE:02`) stayed up throughout; the remote never went down.

Lock behaviour verified standalone: holder acquires and prints its PID; a second instance is
refused with exit 1 and correctly names the holder PID; once the holder exits, the next instance
acquires cleanly.

To confirm on any host:

```bash
ps -eo pid,lstart,cmd | grep [h]id_remote.py     # must print exactly ONE line per adapter
sudo systemctl list-unit-files 'hid-*' | grep transient   # must print nothing
```
