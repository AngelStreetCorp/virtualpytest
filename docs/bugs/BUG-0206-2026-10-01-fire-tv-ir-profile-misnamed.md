# BUG-0206 — The Fire TV IR profile was misnamed, so `IR_TYPE=fire_tv` loaded no key codes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0206                                                          |
| Reported  | 2026-10-01                                                        |
| Severity  | Low — IR on a Fire TV only worked with the misspelled type        |
| Status    | Fixed (pending deploy)                                            |
| Area      | `backend_host/src/controllers/remote/ir_conf/`                    |
| Fixed in  | Unreleased                                                        |
| Commit    | this commit                                                       |

---

## Symptom

A Fire TV with `DEVICE{n}_IR_TYPE=fire_tv` got an IR controller with no keys: the host
logged that `ir_conf/fire_tv.json` was not found. The panel did show the Fire TV skin,
because the frontend keys its layouts by `fire_tv`. The Remote Test page used
`ir_type: 'firetv'` and fell back to the Samsung skin.

## Root cause

The key-code file was committed as `ir_conf/firet_v.json`. The backend loads
`ir_conf/<IR_TYPE>.json` and the frontend skin is chosen from the same `IR_TYPE`, so
no single value worked for both: `fire_tv` found the skin but no codes, `firet_v` found the
codes but the Samsung skin. The factory's setup hint also advertised `appletv` / `firetv`,
neither of which matches a file.

## Fix

Renamed the file to `ir_conf/fire_tv.json`, matching `apple_tv.json` and the frontend.
`RemoteTestPage.tsx` and the factory hints now say `fire_tv` / `apple_tv`.

**A host that set `IR_TYPE=firet_v` must change it to `fire_tv`.**

## Verification

`ir_conf/fire_tv.json` exists and no reference to `firet_v` remains in code or agent docs.
