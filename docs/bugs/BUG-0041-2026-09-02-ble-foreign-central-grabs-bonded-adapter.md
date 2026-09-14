# BUG-0041 — BLE adapter accepts any device while already bonded; foreign central locks the STB out ("lost pairing")

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0041                                                     |
| Reported  | 2026-09-02                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (customer STB unusable until manual bond cleanup)       |
| Area      | `backend_host/src/controllers/remote/bluetooth/hid_remote.py`, `agent.py` |
| Fixed in  | build 8713                                                   |
| Commit    | `5c1fb1518`, `1c54def87`, `bba5922de`                                 |

---

## Symptom

The customer reported STB04 (host1, hci2) "lost pairing" on 2026-08-26 after 05:00 and
again on 2026-08-31 at 18:00, while STB03 on the sibling dongle hci1 of the same host kept
working. Resume did not help; the box came back on its own hours later.

## Root cause

The pairing window was never actually closed once a bond existed:

- `hid_remote.py::main()` set the adapter `Pairable=True` and `Discoverable=True` on every
  daemon start, undoing the `bondable off` that `resume.sh` applies for bonded adapters
  (§6.7.29 fix, July 2026).
- `agent.py` accepted every pairing request unconditionally.
- Nothing dropped an unbonded peer that merely connected.

A foreign BLE central (bond `AA:BB:CC:DD:EE:03`, legacy Just-Works, `Authenticated=0`,
battery-only CCC, last re-paired 2 Sep 10:35) paired onto hci2 next to the STB's real bond
(`AA:BB:CC:DD:EE:04`, LESC authenticated, HID subscribed). While it held the connection the
peripheral stopped advertising, so STB04 could never reconnect. RSSI and USB topology of the
two dongles were equal; the only difference was which advert the intruder heard.
Full analysis: `docs/agent/devices/bluetooth/BLUETOOTH_RECOVERY_CONNECTIONS.md` §6.7.30.

## Fix

1. Adapter Pairable/Discoverable follow the bond state (`_set_pairing_window`): open only while
   no bond exists, closed on the first `Bonded=true` event.
2. An unbonded peer that connects while a bond exists is disconnected immediately
   (`_reject_unbonded_peer`).
3. The agent rejects pairing unless the adapter has no bond or the requester is the bonded
   device (`_pairing_allowed`, adapter-scoped). `HID_AGENT_ALLOW_ANY=1` restores accept-all.

4. **Radio-level lock (§6.7.31, `bba5922de`).** Reproduced on host2 on 2026-09-02 with no second
   bond: a foreign central only has to *connect* to stop our advert. Whenever a bond exists the
   controller's LE filter accept list holds the bonded address and the identity advert uses
   filter policy 0x02, so only the bonded STB can establish a link. Applied in resume.sh, at
   daemon start, after wake and cold-wake; start.sh clears the list for a fresh pair.

Operator consequence: an STB that lost its own key must be re-paired via **Pair** (start.sh),
which wipes the bond and opens the window. That is the documented flow since §6.7.29.

## Recovery on an affected host (before the fix is deployed)

```bash
printf 'select <adapter-mac>\nremove <intruder-mac>\nquit\n' | sudo timeout 15 bluetoothctl
sudo systemctl restart hid-agent@hciN hid-remote@hciN
echo WAKE | sudo tee /tmp/hid_remote-hciN.fifo >/dev/null   # STB in standby needs a directed advert
```

## Verification

- `py_compile` clean on both files.
- `_pairing_allowed` unit-checked with a mocked D-Bus tree: no bond → allow; other bond on the
  same adapter → reject (`org.bluez.Error.Rejected`); bonded device itself → allow; bond on a
  sibling adapter only → allow.
- Field: intruder bond removed on host1/hci2 on 2026-09-02 11:58 and did not return;
  end-to-end reconnect of STB04 and the gates under a live foreign central still to be observed.

## Related

- [BUG-0024](BUG-0024-2026-07-24-ble-stale-duplicate-bond.md), [BUG-0039](BUG-0039-2026-09-02-ble-daemon-journal-flood-hides-incidents.md).
