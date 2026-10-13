# BUG-0301 — Stream preview could show another device's stream after a device switch

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0301                                                     |
| Reported  | 2026-10-04 (TASK-28 promo session)                           |
| Status    | Fixed (pending deploy) — most likely cause, not reproduced   |
| Severity  | Medium — the page shows one device while a run drives another |
| Area      | `frontend/src/hooks/controller/useStream.ts` (every stream preview) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

Test Prompt on rpitest, target S21x (vpt-pi1 device1, `google-tv-mobile-ai`), Explore run
`50738e1a` at 12:44 UTC: the run drove the phone (the row says device1), but the page's
stream panel played **stb4's** stream (device4, `capture4`) for the whole run.

## Root cause (most likely)

The server, the host registry and the HLS playlists were all correct when checked: device1 →
`capture1`, device4 → `capture4`, and different segments. No frontend commit between the good
13:02 CEST run and the bad one touches stream URLs. In `useStream`, though, the stream-URL
request for a device is awaited and its answer is always applied, even if the selected device
changed while it was in flight. A page that selected stb4 and then the phone, with stb4's answer
arriving last, keeps stb4's stream. Not reproduced: the phone was in use for filming.

## Fix

`useStream` remembers the device of its latest request. An answer for any other device is
cached (it is valid for its device) but not applied, and neither are its errors.

## Verification

- `tsc --noEmit` passes.
- After the frontend deploy: the TASK-28 session retakes the S21x run and the panel shows the phone.
