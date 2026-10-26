# BUG-0840 — One screen, several rows and names: seven writers on screen_fingerprints

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0840                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | monitoring / backend / db                                    |
| Fixed in  | build 90145 |
| Commit    | branch `task159-screen-registry`                             |

---

## Symptom

On vpt-mf1 (stbv1, stbv1+) and vpt-pi1 (stb4) the same splash or trailer picture showed different names on different
tiles (`movie_poster_preview`, `Full-screen poster`) or none, and the freeze status disagreed with the tile.

## Root cause

Seven writers created or named `screen_fingerprints` rows with two different keys (freeze rows keyed by
`incident_type`, abstain rows by exact `dhash`), so one picture became several rows; the tile showed the nearest row.
The closed "menu or no menu" check never ran on freeze rows (no `userinterface`). Both prune paths ignored `label`.
Full analysis: `docs/tasks/TASK-159-screen-registry-single-writer.md` §3.

## Fix

`screen_fingerprints_db.register_screen` is the only creator (monitor Localize; freeze alert only when Localize gave no
screen id); identity is the `match_screen` tolerance; names `unknown_N` come from `register_screen_row`; a name is written
once (`name_screen_row`); both prunes skip real names; duplicates are soft-merged (`merged_into`). Migrations
`20261022e_screen_registry.sql`, `20261022f_screen_prune_guard.sql`.

## Verification

`tests/shared/test_screen_registry*.py`, `tests/backend_host/test_localize_default_ui.py`; SQL proof transcript in
`docs/tasks/TASK-159-evidence/lab-rollback-proof-2026-10-22.txt`; live before/after on stbv1/stbv1+ after the host deploy.
