# BUG-0663 — An unnamed known screen is badged "Known screen (unknown, seen 1x)" and its seen count is wrong

> **Superseded by TASK-159 (2026-10-22):** `bump_unknown_screen` is gone; only `screen_fingerprints_db.register_screen` creates screen rows. See [TASK-159](../tasks/TASK-159-screen-registry-single-writer.md).

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0663                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | monitoring / localize                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A device-control video tile shows "Known screen (unknown, seen 1x) · 100 %" on vpt-pi1 device3/device4. The screen
has no name, so the badge is noise (owner rule 2026-10-19: unknown = show nothing). The "seen 1x" is also wrong: the
owner has seen the screen 100+ times.

## Root cause

1. `localize_verdict.known_screen_verdict` built the text `Known screen (<verdict or 'unknown'>, seen Nx)` for a
   screen-memory row with no label, and the frontend had to guess "unnamed" from that text. The first fix (same day)
   matched the text; on the live page the deployed build already hides it, so the badge the owner saw came from a tab
   still running the previous JS chunk. Matching text is fragile, so the backend now says it.
2. `screen_fingerprints.seen_count` was only bumped by the alert path (`resolve_or_create`) and by the matcher-abstain
   path (`bump_unknown_screen`); the Localize known-screen match read the row and never counted it.

## Fix

- `known_screen_verdict` marks `evidence.named` (False for a row with no label and no verdict word) and builds no fake
  label (`label` is empty). The frontend (`isUnnamedKnownScreen` in `screenVerdict.ts`) keys on `evidence.named === false`
  or an empty label; the video badge, the monitoring overlay and the Localize button popover ("Unnamed screen") use it.
- `monitor_localize._count_known_sighting` counts one Localize sighting per episode (screen changes, or the same screen
  again after 10 min) through `bump_known_screen_sighting`, in a daemon thread: no DB write per frame.
- **Counter choice:** the same `seen_count` column, but only for unclassified rows (`verdict = 'unknown'`). The alert audit
  gate (`screen_memory.should_audit`, `metadata.screen_seen` stamped by `incident_manager`) reads the count of trusted
  (`expected`) rows, so those keep counting alert sightings only and the alert logic keeps its meaning. The unclassified
  backlog (auto-classify threshold 5, analytics `screen_memory` source) now reflects real sightings.

## Verification

`tests/backend_host/test_localize_phases.py` (named / unnamed), `screenVerdict.test.ts`, `LocalizeVideoBadge.test.ts`.
Live: vpt-pi1 device3/device4 tiles show no badge; their `seen_count` grows by one per episode.
