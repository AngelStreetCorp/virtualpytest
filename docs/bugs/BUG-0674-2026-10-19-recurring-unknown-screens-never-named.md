# BUG-0674 — Recurring unknown screens are never named

> **Superseded by TASK-159 (2026-10-22):** `bump_unknown_screen` is gone; only `screen_fingerprints_db.register_screen` creates screen rows. See [TASK-159](../tasks/TASK-159-screen-registry-single-writer.md).

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value |
|-----------|-------|
| ID        | BUG-0674 |
| Reported  | 2026-10-19 |
| Status    | Fixed (pending deploy) |
| Severity  | Medium |
| Area      | backend / localize / screen memory |
| Fixed in  | build 90145 |
| Commit    | TBD |

---

## Symptom

stb3 / stb4 on the operator Home in its full-poster state (tab bar hidden) showed no screen name for hours. Lab DB:
65 `screen_fingerprints` rows `verdict = unknown`, 0 with a `label`, three rows seen about 280 times each.

## Root cause

TASK-84 intends: Localize logs a screen it cannot name, counts sightings, past a threshold AI names it, Localize then
names it. Three links were broken (`backend_server/scripts/auto_classify_unknowns.py`):

1. **The sample is gone.** The row stored the host's rolling frame URL (`/host/<name>/stream/captureN/captures/...`);
   the host deletes that frame within minutes. Hours later the classifier could not fetch it. Verified on vpt-pi1: the
   stored frames no longer exist.
2. **Nightly, and the counter only just started.** The timer ran at 02:00; Localize sightings only count since today, so
   the rows crossed the threshold (5) after the last run. All 7 candidates still had `classification_attempts = 0`.
3. **The answer never reached the row.** The result went only into `userinterface_unknown_screens` as a pending proposal
   (678 pending) for a person to accept. `screen_fingerprints.label`, which `known_screen_verdict` reads, was never set.
   Even when it ran, the badge stayed empty.

Also: open naming of a full-poster Home gives a different name per poster (`thundermans_poster`...), so it never converges.

## Fix

- `match_runs_worker._store_thumb`: on first sighting (and on later ones while missing) the server fetches the frame
  and stores a 320 px JPEG data URI in `sample_image_path` (`bump_unknown_screen` returns `needs_thumb`).
- `auto_classify_unknowns.py`: reads data-URI samples; a missing sample no longer burns an attempt; after a name is
  found it is written to `screen_fingerprints.label` (`name_row`, only if empty; verdict stays `unknown`).
- `STATE_HINTS`: for `stb_tv` a Qwen yes/no check (menu bar visible: MENU / NOMENU) runs first; `NOMENU` stores the label
  `Home (tab bar hidden)`. (A closed choice with the description on the `home` node picked `home_recodings`: rejected.)
- `bump_known_screen_sighting` (host, Localize memory hit) stores the same thumbnail from the live frame: the recurring posters are counted on this path, not the abstain path.
- `auto-classify.timer`: hourly instead of 02:00.

## Verification

See the commit message / FINGERPRINT.md "Screen memory pipeline" for rows named before / after and the live tile check.
