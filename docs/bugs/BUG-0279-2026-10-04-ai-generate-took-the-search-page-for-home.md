# BUG-0279 — AI Generate on Android took the search page for home, so Search's way back was one BACK short

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0279                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — a created edge did not reach home, and the next item's validation started on the wrong screen |
| Area      | `backend_host/src/services/ai_exploration/phases/validation_runner.py` (`verify_mobile_web`) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

On an Android phone with Google TV, AI Generate validated Search with `search → home = BACK ×1`,
then the next item failed: *"Element 'Shop' not found"*. The phone was still on the search page.

## Root cause

Validation decided "back home" by waiting for one label, the first proposed item (`Search`).
Google TV's search page also shows "Search". The first BACK only closes the keyboard; the search
page still matched, so one BACK was saved and the next tap ran on the search page.

## Fix

On Android, home is where **every** item being validated shows in the app's window, read from
one dump. The search page lacks the tabs, so the first BACK fails the check and the second BACK
(saved as BACK ×2) passes.

## Verification

- The phone's own dumps: search page open → `Shop, Library, Watchlist` missing; after one BACK →
  still missing; after the second BACK → none missing; Google TV home → none missing.
- Deployed and run on the phone 2026-10-04: `search → home` saved as BACK ×2, all 4 items pass
  both ways, and Validate passes it.
