# BUG-0026 — Device tags wiped on every service restart

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0026                                                     |
| Reported  | 2026-07-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_server / device tags / grafana                      |
| Fixed in  | build 8713                                                   |
| Commit    | `16a7ae5a5`                                                 |

---

## Symptom

User-set device tags disappeared after any service restart — most visibly after a **code deploy**.
Tags set on the Device page / Rec edit / run-tests target panel were gone the next time the host
came up, taking the Grafana **Flag/Tag** dashboard filters that depend on them with them.

## Root cause

Every **host registration** blindly upserted each of its devices into `device_flags` with
`flags = []`, **overwriting** any existing row. Registration happens on every service start, so each
restart reset all tags to empty. The `flags` column is the source of truth for the device tags, so
wiping it wiped the tags everywhere they're read (UI + `device_flags`-joined Grafana panels).

## Fix

`backend_server/src/routes/server_device_flags_routes.py` (`16a7ae5a5`):

- Registration now **inserts only when the row is missing**, and otherwise touches nothing but a
  changed `device_name` — it never overwrites `flags`.
- **Terminology:** the UI calls these **"Tags"** everywhere, so the Grafana template-variable
  **label** is renamed **Flag → Tag** across all 8 dashboards. The internal variable name (`flag`)
  is unchanged, so every panel query keeps working.

## Verification

1. Tag a device, restart `vpt-server` (or redeploy) → the tag is still set on the device and the
   `device_flags` row is intact.
2. Register a brand-new device → it gets an empty tag row created once, and is not re-emptied on
   subsequent restarts.
3. Grafana dashboards show the filter labelled **Tag** and still filter correctly.
