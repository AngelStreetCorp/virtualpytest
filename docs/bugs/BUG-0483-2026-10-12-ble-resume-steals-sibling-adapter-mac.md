# BUG-0483 — BLE Resume gave one adapter its sibling's address, both STBs lost their remote

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0483                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Critical                                                     |
| Area      | backend_host (BLE remote: `resume.sh`, `hid_remote.py`)       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

vpt-mf1, two Arris STBs on two Belkin dongles: stbv1 on `hci1` (`20:21:41:00:1F:41`), stbv1+ on
`hci2` (`20:21:41:00:1F:01`). After a Resume on stbv1+ (2026-10-12 17:00), **neither** remote
worked. stbv1 woke on a Cold Wake, connected, and was dropped by our side 4 s later
(`Disconnect … Connection Terminated By Local Host`, `bonding failed status 0x0e`). From then on
stbv1, though awake, never tried to connect again.

## Root cause

1. **Stale binding.** `/var/lib/vpt-ble/adapter-hci2.mac` said `1F:42` (staged on 2026-10-08 for
   a re-pair that only happened on hci1). hci2 was really running on `1F:01`, where its bond is.
2. **`resume.sh` borrowed the sibling's MAC.** The binding had no bond, so resume fell back to
   "newest adapter dir with a bond" — that was hci1's `1F:41`. It spoofed hci2 to `1F:41`: two
   adapters on one address. bluetoothd dropped `/org/bluez/hci2`.
3. **`hid_remote.py` bound to the wrong adapter.** `find_adapter()` returned the first usable
   adapter when its own was missing. The hci2 daemon (after 4 `GATT register failed` restarts)
   came up on `/org/bluez/hci1`: two daemons, two GATT apps and two wake loops on stbv1's adapter.
   The hci0 daemon (dongle wedged, never in bluetoothd) had been sitting on hci1 the same way since
   2026-10-08. The concurrent wake rewrote hci1's advertising mid-connection and the link died
   during encryption.

The overnight drops themselves (stbv1 01:40, stbv1+ 03:37, both `0x13` from the STB as it went to
deep standby) only needed a **Cold Wake** — the 16:37/16:40/16:58 attempts were plain Wake.

## Fix

- `resume.sh` address selection (§6.7.34): keep the address the adapter is already on when it
  holds a bond; then the persisted binding; then the newest bonded dir. **Every candidate is
  refused if a sibling adapter uses it or has it in its binding.** No bonded unowned address →
  exit 2 and change nothing. The chosen address is written back to `adapter-hciN.mac`. An explicit
  `ADAPTER_MAC` that a sibling owns is refused too.
- `hid_remote.py` `find_adapter()`: no fallback. Missing adapter → wait 30 s and exit; systemd
  retries.

## Verification

- Selection block dry-run on vpt-mf1 against the real adapters: hci1 keeps `1F:41`, hci2 keeps
  `1F:01`; with the 2026-10-08 stale binding (`hci2 → 1F:42`) hci2 keeps `1F:01` and the binding
  is rewritten; hci0 (factory MAC, no binding) skips `1F:41`/`1F:01` and exits 2;
  `ADAPTER_MAC=1F:01` on hci1 exits 2.
- Live recovery 2026-10-12 18:05: hci2 back on `1F:01`, stray `hid-remote@hci0` stopped,
  stbv1+ Cold Wake → `Connected=True ServicesResolved=True`.
- Open: stbv1 stays disconnected while awake and an open (no filter) advert drew no connect
  attempt in 25 s — consistent with the STB having dropped our key during the 17:00 failed
  encryption. It needs a re-pair (Start Pairing + STB in pair-remote mode).
