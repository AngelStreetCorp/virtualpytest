# BUG-0003 — bluetoothd restart silently wipes the BLE remote's GATT registration; every key dropped

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0003                                                     |
| Reported  | 2026-07-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / bluetooth                                     |
| Fixed in  | build 8414                                                   |
| Commit    | `bd620fc5c`                                                  |

---

## Symptom

**stb4** (Arris BLE, vpt-pi3 / hci0) stopped responding to **every** key, POWER included. The
frontend showed a black screen — the STB was stuck in standby and could not be woken (all captures
exactly 7 402 bytes, the black-HDMI signature). Every layer that normally proves the remote works
reported success:

- wake-on-press reconnected the STB over BLE in ~1 s (`ADV_DIRECT_IND` → `Connected=True`),
- the link encrypted AES-CCM from the on-disk bond,
- the daemon journal logged `Injecting 0x0030` (POWER) with no error,
- the controller returned `press_key: SUCCESS`.

## Root cause

`bluetooth.service` restarted at 13:06 while `hid-remote@hci0` had been running since Jun 25.
D-Bus GATT applications (`RegisterApplication`) live in the bluetoothd instance they were
registered against; a bluetoothd restart forgets them all, and the daemon never re-registered.
The new bluetoothd served an **empty GATT table**: the STB connected and encrypted, found none of
its cached handles (`Invalid Handle` on Battery `0x0017`, primary-service discovery returning ~1
entry), never re-subscribed to notifications — and BlueZ **silently drops** `notify_value` to an
unsubscribed characteristic. `agent.py`'s `RegisterAgent`/`RequestDefaultAgent` die the same way,
silently regressing pairing to reject-all.

Confirmed with `btmon`: zero `ATT: Handle Value Notification` TX packets during presses.

Full write-up: BLUETOOTH.md §6.7.28
(`docs/agent/devices/bluetooth/BLUETOOTH_RECOVERY_CONNECTIONS.md`, internal).

## Fix

Three layers:

1. `hid_remote.py` — `install_bluez_owner_watch()`: on `NameOwnerChanged` for `org.bluez` with a
   **new** owner, `os._exit(1)`; `Restart=always` relaunches the daemon through the normal startup
   path, which re-registers the GATT app. Owner *loss* is deliberately ignored (restarting while
   bluetoothd is down would crash-loop `find_adapter()`).
2. `agent.py` — same watcher for the pairing agent registration.
3. `hid-remote@.service` / `hid-agent@.service` — `PartOf=bluetooth.service` (explicit bluetoothd
   restarts propagate) and `StartLimitIntervalSec=0` (the self-heal exit must never trip the
   default 5-in-10s start limit if bluetoothd flaps).

Units self-bootstrap from the repo on the next `start.sh`/`resume.sh` run.

## Verification

On host3 (vpt-pi3), after deploying and restarting `hid-remote@hci0`:

- `sudo systemctl restart bluetooth` → daemon logs the owner change and exits; systemd relaunches
  it; journal shows `GATT application registered` within seconds — no manual step.
- `wake` + `press_key` via the host API afterwards → `btmon` shows `ATT: Handle Value
  Notification` TX and the STB reacts.

Diagnosis recipe for any host:

```bash
systemctl show bluetooth hid-remote@hci0 -p Id -p ExecMainStartTimestamp
# bluetoothd newer than the daemon (pre-fix) = this bug
```

## Recurrence — 2026-07-21, vpt-pi1 / stb4 (fix was on disk but not running)

Same failure, different host, five days after the fix shipped — because **deploying the fix does
not activate it**. Frontend reported "Bluetooth connected but no key works".

**State found on vpt-pi1:**

- `/opt/.../bluetooth/hid_remote.py` on disk **had** the BUG-0002 + BUG-0003 fixes (`acquire_run_lock`,
  `install_bluez_owner_watch`) — the deploy had happened.
- The running daemon (PID 3973803) had been alive since **Jun 26**, i.e. started three weeks
  *before* the fix existed. It was still executing the old pre-fix code from memory.
- The hardened unit file was **not installed**: `systemctl show hid-remote@hci0 -p PartOf` → empty.
  Units only self-bootstrap via `start.sh`/`resume.sh`, and neither had run on this host since
  Jul 16. Nothing else restarts `hid-remote@` — `update_core.sh` doesn't touch it.

**Diagnosis twist — the timestamp heuristic gave a false negative.** bluetoothd (Jun 25) was
*older* than the daemon (Jun 26), so the §6.7.28 recipe said "not this bug". Yet the GATT
registration was gone anyway (trigger unknown). The definitive tests are:

1. `journalctl -u hid-remote@hci0 | grep -c 'GATT application registered'` for the **current**
   process → was 0.
2. `btmon -i hci0` during an inject: **zero ATT packets** while the daemon logs `Injecting` and
   D-Bus reports `Connected=True / ServicesResolved=True`.

Also observed: the kernel held a live encrypted LL connection (`hcitool -i hci0 con` →
`handle 65 … AUTH ENCRYPT`) while D-Bus said `Connected=false` — the *inverse* of the §6.7.21
ghost. Neither layer can be trusted alone.

**Fix applied:** `sudo systemctl restart hid-remote@hci0 hid-agent@hci0`. Journal logged
`Run lock acquired` (new code active) and `GATT application registered`. Verified with btmon:
STB reconnects → encrypts → sends the CCCD `Write Request` → `ATT: Handle Value Notification`
TX for RIGHT/LEFT presses. Keys land.

**Lesson / follow-up:** a code fix for a long-running daemon is not deployed until the daemon is
restarted. After deploying BLE daemon fixes, restart `hid-remote@<hci>` + `hid-agent@<hci>` on
every BLE host (or run `resume.sh`), and confirm `PartOf=bluetooth.service` is present in the
installed unit. As of 2026-07-21 vpt-pi1 runs the fixed code but still has the old unit file
(harmless — the in-code owner watch + `Restart=always` covers the bluetoothd-restart case).
