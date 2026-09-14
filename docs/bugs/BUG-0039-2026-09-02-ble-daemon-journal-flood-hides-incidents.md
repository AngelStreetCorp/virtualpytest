# BUG-0039 — BLE daemon floods the journal on every keypress; past "lost pairing" incidents unrecoverable

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0039                                                     |
| Reported  | 2026-09-02                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (no data loss, but every BLE incident older than ~1 h is un-diagnosable) |
| Area      | `backend_host/src/controllers/remote/bluetooth/hid_remote.py`, `diagnose_ble.sh`, host journald |
| Fixed in  | build 8713                                                   |
| Commit    | `7c091bf8e`                                                |

---

## Symptom

The customer reported that STB04 lost its BLE pairing on 2026-08-26 after 05:00 and again on
2026-08-31 at 18:00, while STB03 on the sibling dongle of the same host kept working. When we
went to pull the journal for those windows on `host1`, `journalctl --list-boots` showed
the current boot's **first entry at 09:24 the same morning**, although `dmesg` put the uptime at
about 28 days. Nothing from either incident survived.

## Root cause

`hid-remote@hciN` runs as root, yet `hid_remote.py` called `sudo btmgmt … conn-info` (the
§6.7.21 ghost check) on **every keypress**, and `sudo hcitool` / `sudo hciconfig reset` on the
wake path. Each sudo invocation writes three audit lines (`COMMAND=` plus pam session
open/close). Together with the `Injecting 0x…` line and the multi-bond warning from
`_bonded_peer_mac()` (printed on every call once an adapter holds two bonds), one keypress
produced **five journal lines**, plus a kernel `Bluetooth: hciN: Opcode 0x0c2d failed: -22`
(conn-info's Read Transmit Power Level, which the Belkin/Broadcom dongle rejects).

`journald.conf` on the host is all defaults (`Storage=auto`, `RuntimeMaxUse` = 10 % of `/run`),
so the journal rotated down to roughly one hour of history under continuous zap testing.

## Fix

1. **`_priv()` helper** — `sudo` is prefixed only when the daemon is not already root. Removes
   three audit lines per keypress on the deployed root units.
2. **Multi-bond warning logged once per change** of the bond set (`_LAST_MULTI_BOND_KEY`),
   not on every press. The warning itself stays, as it is the primary §6.7.29 signal.
3. **`diagnose_ble.sh`** rewritten (commit `2dbbe97e1`) to write a folder of small per-section
   files (clipboard-copyable from a VDI), squash the remaining chatter into counters, accept a
   `SINCE`/`UNTIL` window, and print journal retention up front so an unrecoverable window is
   obvious.

The kernel `0x0c2d` line is not addressed: it comes from `btmgmt conn-info` itself and the
ghost check needs that probe.

## Operator action on the host (journal retention)

Make the journal persistent with a size cap so the next incident is captured:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/vpt.conf >/dev/null <<'CONF'
[Journal]
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=1month
CONF
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
journalctl --disk-usage          # should now report a file under /var/log/journal
```

Then restart the daemons so the quiet build is loaded:

```bash
sudo systemctl restart hid-remote@hci1 hid-remote@hci2
```

## Verification

- `python3 -m py_compile hid_remote.py` clean; `_priv()` returns the bare command under root.
- `squash()` in `diagnose_ble.sh` tested against the 2026-09-02 journal excerpt: the 5-line
  keypress groups collapse to per-key counters, sudo/pam lines are dropped, consecutive
  duplicates fold into "repeated N more times".
- Field verification (journal growth rate after deploy) pending.

## Related

- [BUG-0024](BUG-0024-2026-07-24-ble-stale-duplicate-bond.md) — the duplicate bond that makes
  the warning fire in the first place.
- `docs/agent/devices/bluetooth/BLUETOOTH_RECOVERY_CONNECTIONS.md` §6.7.21 (ghost check), §6.7.29.
