# BUG-0751 — A misspelled IR_TYPE gave only "Failed to connect to remote controller"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0751                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host                                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On a customer host, two Apple TVs on a networked IRTrans box had `DEVICEn_IR_TYPE=appletv`.
Take Control showed the toast "Failed to connect to remote controller" and no remote. The
only clue was a journal line naming a path:
`IRTrans keymap not found: .../remote/ir_conf/appletv.json`.

## Root cause

`IR_TYPE` is used as a file name (`<ir_type>.json`) and the keymap is `apple_tv.json`.
`connect()` of the IR controllers (`irtrans.py`, `irtoy.py`, `infrared.py`) printed the path
and returned False with no reason the route could use, so `take_control` in
`backend_host/src/routes/host_control_routes.py` fell back to the generic message.

## Fix

- `backend_host/src/controllers/remote/ir_keymap.py`: `missing_keymap_message()` names the
  variable, the folder, the keymaps that exist and the closest match.
- The three IR controllers store it in `connect_error` (new field on `BaseController`) and log it.
- `take_control` puts `connect_error` in the toast when the controller has one.

The toast now reads: `IR keymap 'appletv.json' not found in ir_conf/ (check
DEVICE<n>_IR_TYPE=appletv). Available: apple_tv, fire_tv, samsung, stb. Did you mean 'apple_tv'?`

## Verification

Set `DEVICE1_IR_TYPE=appletv` on a host with an IR remote, restart `vpt-host`, Take Control:
the toast shows the message above. Set `apple_tv` and the remote appears.
