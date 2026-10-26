# BUG-0422 — Start Pairing wiped four BLE remotes and nothing recorded who ran it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0422                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / ble-remote / frontend                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On 2026-10-05 all four BLE remotes on two customer hosts (2 adapters each) stopped landing keys.
The STB screens still showed the remotes as paired and connected. On the hosts:

- `/tmp/ble-start-hci{1,2}.log` on both hosts had mtime 07:53–07:54: `start.sh` (the destructive
  fresh pair) had run on all four adapters within the same minute, two of them reporting
  `Concurrent start.sh detected`. Every run ended with `Paired: 0`.
- Afterwards one adapter had no bond at all; the three others had a bond with legacy keys
  (`Authenticated=0`) and **no `2a4d` in `[Cccs]`**. Sending `OK` produced `Injecting …` in the
  daemon journal and zero `Handle Value Notification` in btmon: every key was dropped.
- Nothing recorded who triggered the runs. The host journal only keeps a few hours, and
  `start_pairing` carried no caller identity.

## Root cause

`start_pairing` (`backend_host/src/controllers/remote/bluetooth.py`) runs `start.sh`, which removes
every bond on the adapter. The request carried no caller identity, the server logged only
`Proxying execute command request`, and the host journal rotates within hours. The only remaining
trace was the server's nginx access log: the four calls (138-byte responses at 07:53:12, :21, :35,
:51, matching the four `start.sh` start times) came from one browser on the Device Control page.

## Fix

Logging only; pairing behaves as before.

- The server's `/server/remote/executeCommand` stamps `params.caller` for `start_pairing` from its
  own auth state (user, role, client IP, user agent), never from the request body, and logs it.
  A direct call to the host API is stamped `via=host-api` with the source IP.
- `start_pairing` passes the caller to `start.sh` (`VPT_PAIRING_CALLER`). `start.sh` appends one line
  per run to `/var/log/vpt-ble-pairing.log`: time, adapter, MAC, the link state at the click (`healthy` / `no_keys` / `no_link`),
  the live peer and the caller. A manual run records
  the sudo user, tty and parent command line.
- `diagnose_ble.sh` prints the last 30 audit lines in section 04.

Details: [BLUETOOTH_RECOVERY_CONNECTIONS.md §6.7.32](../agent/devices/bluetooth/BLUETOOTH_RECOVERY_CONNECTIONS.md).

## Verification

- Re-pair from the panel → `sudo tail /var/log/vpt-ble-pairing.log` on the host shows
  `… caller=user=<email> role=<role> ip=<ip> … via=server`.
- `sudo ADAPTER_HCI=hciN …/start.sh` by hand → a `caller=manual sudo_user=…` line.
