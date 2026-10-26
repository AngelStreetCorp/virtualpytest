# BUG-0746 — A screen judged harmless kept raising freeze alerts, and Localize never named it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0746                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium (one model call and one alert per sighting of a still menu, forever) |
| Area      | monitoring                                                   |
| Fixed in  | build 90145 |
| Commit    | see `git log --grep BUG-0746`                                |

---

## Symptom

`vpt-mf1` / `capture5` (Android TV "Mi", no userinterface) raised 56 freeze alerts in 3 days on the Google TV home
screen. The triage model judged every one `expected` ("static menu content, legitimately still"), and the next one came
anyway. The screen was never remembered, and Localize showed nothing for that device.

## Root cause

1. **Screen memory only ran on the `host` VNC desktop.** `incident_manager._stamp_screen_id` returned early unless
   `device_id == 'host'` (TASK-84 review rule). No other device got a `screen_fingerprints` row, so the model's
   verdicts were thrown away and nothing could ever discard the screen.
2. **The memory never stopped an alert from opening.** Even on the host, a known `expected` screen still produced an
   alert; the server worker discarded it afterwards (`check_type = fingerprint`). Phase 4 of TASK-84 (suppress at
   source) was never built.
3. **No default userinterface.** `monitor_localize._resolve_ui` returned None for a device with no
   `DEVICEn_USERINTERFACE` (phones excepted) and for `host`, so Localize did not run there at all. DEVICE5 and up also
   arrive as their capture folder (`capture5`), which the `device(\d+)` pattern never matched.
5. **A person's Discard taught nothing.** `server_alerts_routes.updateDiscardStatus` called `_teach_screen_memory` only
   `if not discard` (regression of f832c623d7, 2026-10-18, a lookup dedupe): **Keep** marked the screen `bad`, **Discard**
   never marked it `expected`. Fixed: every manual Discard / Keep teaches its screen, one alert lookup per click; a
   route-level test now covers it (`test_a_person_s_discard_and_keep_through_the_route_teach_the_screen`).
4. **Candidates expired before promotion.** A new fingerprint must be seen 5 times before it becomes a row, but the
   candidate was forgotten after 1 h of not being seen; a menu that freezes every hour or two never got there.

## Fix

- `incident_manager._freeze_screen` looks up the freeze frame in screen memory for **every** device, once per freeze
  episode, before the frame upload. On a screen judged `expected` (2 model votes or one person) with
  `ALERT_SCREEN_MEMORY=on`, the freeze is **not reported** at all; the episode is remembered until the freeze ends. Any
  other freeze is opened with `screen_id` stamped, so the triage verdict lands on the row.
- `monitor_localize._resolve_ui` gives a device with no userinterface the default tree-less one (`NO_TREE`): Localize
  answers signal / live and names a still frame from screen memory (`known_screen #id`, its verdict) or `unknown`.
  `host` reads `HOST_USERINTERFACE`; `captureN` is mapped to its `DEVICEn`.
- **Usage decides what a screen memory keeps** (owner follow-up): the in-memory candidates (5 sightings within a window,
  wiped by every host restart) are gone. A screen is a row from its first sighting; one seen 5+ times
  (`ALERT_SCREEN_KEEP_MIN_SEEN`) is kept for good, one seen fewer times, never judged and unseen for 7 days
  (`ALERT_SCREEN_PRUNE_DAYS`) is deleted as random by `screen_fingerprints_db.prune_rare` (triage worker, daily). The
  worker's "teach" bypass of the `short` / `repeat` rules applies only to a recurring screen, so random screens cost no
  extra model calls.

- **Usage counted on flips** (found live on vpt-mf1): one frozen screen made two near-identical rows (07:52, 07:54), and
  Localize alternated between them every tick; `_count_known_sighting` counted each flip as a new sighting (214 in 2 h).
  It now counts each screen at most once per `KNOWN_RECOUNT_S` (10 min) per device.
- Deploy note: `update_core.sh` restarts `vpt-monitor-img` only with `--restart vpt-monitor-img`; without it a host keeps
  running the old monitor code.

A person's **Keep** on an alert still marks the screen `bad` (human wins), and a `bad` screen is always reported.

Tests: `tests/backend_host/test_freeze_known_screen.py`, `tests/backend_host/test_localize_default_ui.py`.
