# BUG-0377 — Atlas chat runs were stored 2 hours in the future

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0377                                                       |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | backend                                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | `3758f5cc7`                                                  |

---

## Symptom

Found while checking the rebuilt Agent Dashboard (TASK-54) on prod: a chat sent at 05:51 UTC was stored in
`agent_execution_history` at 07:51 UTC, while its `agent_turns` rows said 05:51. Atlas's "last activity" was in the
future and its chat rows were sorted above newer rows from other sources in the log drawer. Every chat run since the
table was first written is offset by the server's UTC offset (+2 h in summer, +1 h in winter).

## Root cause

`handle_message` in `backend_server/src/routes/server_agent_routes.py` took `started_at` / `completed_at` from
`datetime.now()`: a naive local time on a server running in Europe/Zurich. `isoformat()` of a naive datetime has no
offset, and Postgres reads it into the `timestamptz` column as UTC.

## Fix

`datetime.now(timezone.utc)` for both. Durations are unchanged (both ends were shifted equally). Old rows are left as
they are (shifted by 1–2 h); they age out of the dashboard's 30-day window.

## Verification

`py_compile`, `tests/backend_server/test_agent_activity.py` (55 passed). After deploy: a test chat's
`agent_execution_history.started_at` matches its `agent_turns.created_at`.
