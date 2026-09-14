# BUG-0024 — BLE remote chases a stale duplicate bond; Resume can silently re-pair

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0024                                                     |
| Reported  | 2026-07-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / bluetooth                                     |
| Fixed in  | build 8713                                                   |
| Commit    | `352c288b5`                                                 |

---

## Symptom

On host2 (2026-07-24) the STB was stuck in a **"STB disconnected" Resume loop**: pressing a
key never reconnected it. The adapter held **two bonds** for the STB with **none connected**, and
wake-on-press kept targeting the wrong one.

## Root cause

When an adapter held multiple bonds and none was connected, the wake picker chose the target by
**MAC sort order** — which frequently selected a **dead, battery-only duplicate** bond rather than
the live STB, so the wake never landed. The duplicate bond itself came from the STB **silently
self-re-pairing mid-Resume** against the always-open auto-accept pairing agent (the pairing window
was left open during Resume).

## Fix

`352c288b5` (see BLUETOOTH.md §6.7.29):

- **Bond picker prefers the usable bond** — Connected first, then the bond with the **HID Input
  Report subscribed** (HID-CCC), instead of MAC sort order.
- **`resume.sh` closes the pairing window** (`bondable off` / `discoverable off`) once a bond
  already exists, so the STB can't silently self-re-pair and mint a duplicate; it also **warns
  loudly** when it finds more than one bond.
- Ghost-connection `hciconfig reset` is **rate-limited to 1/min**.
- The fleet-wide **IRK is never used for identity** (it's shared across the fleet, so it can't
  distinguish one STB's bond from another).

## Verification

With two bonds present and none connected, a key press reconnects the **live** STB (not the
duplicate) and keys land. A Resume with a bond already present leaves the pairing window closed, so
no silent re-pair occurs; a host with >1 bond logs the warning.
