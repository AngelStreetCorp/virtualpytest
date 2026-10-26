# BUG-0343 — Manager alerts never showed in the dashboard page

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0343                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium - escalations to the owner went unseen                |
| Area      | ghosty-sessions (codebox session dashboard): `public/app.js`, `manager-events.js` |
| Fixed in  | build 90145 |
| Commit    | ghosty-sessions `15d89f9` (bell and alerts sheet), `fe971b1` (event dedupe), merged as `3b2a620` (branch `mgr-ui-alerts`) |

---

## Symptom

The AI manager's batched escalations (`POST /api/alert`, 5 alerts between 2026-10-04 11:58 and 16:44 UTC) and every other ghosty alert were only written to the push feed (`GET /api/push/feed`). Only the service worker (`public/sw.js`) read that feed, to show a Web Push notification. No page code rendered it, so the owner looking at the dashboard saw none of them (reported 2026-10-04 ~16:55 UTC).

Related defect: the same stop was re-appended to `manager-events.jsonl` several times (same session, same question), waking the manager agent each time. Seen the same day: one worktree question 3 times and one temporary-trees question 3 times.

## Root cause

The feed had a single consumer, the service worker. The dashboard page never fetched `/api/push/feed`. Separately, the event file appended every stop it was handed, with no check for a stop it had already recorded.

## Fix

In ghosty-sessions, branch `mgr-ui-alerts`, merged into `main` as `3b2a620`:

- `15d89f9`: top-bar bell with an unread count and an alerts sheet; the page polls the feed every 30 s, lists alerts (HTML escaped) and has "mark all read".
- `fe971b1`: `manager-events.js` skips a stop with the same session, kind and text already appended in the last 6 h (the window is seeded from the file's tail, so a service restart does not forget it).

Shipped alongside, not bug fixes: `GET /api/manager/actions` (read-only tail of `manager-actions.jsonl`) and a manager cost chip in the AI manager panel.

## Verification

`npm test` passed 569/569 three times. Live check on a spare port with a fresh state dir at 412 px and 1280 px: alerts listed, mark all read worked, HTML was escaped. On the real service: `ghosty-sessions` was restarted at 16:58:08 UTC (the merge commit time) and `curl -s localhost:7777/ | grep -c alertsBtn` returns 1, so the bell is live on codebox. Not verified: the 6 h dedupe against a real re-fired stop on the live service.
