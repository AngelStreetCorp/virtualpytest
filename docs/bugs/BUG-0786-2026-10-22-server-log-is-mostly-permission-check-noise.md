# BUG-0786 — The server log is mostly permission-check noise

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0786                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend                                                      |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-09, in `docs/tasks/QA-OPS-findings.md`); measured on the live server.

- **Page / route:** the operator's log (`journalctl -u vpt-server` on the backend server)
- **Viewport / theme:** —

Steps to reproduce:

1. Tail the backend server's log.
2. Count the lines.

**Expected:** The log shows what happened.

**Actual:** About two lines in three are `[@auth_middleware] Permission check passed: <permission>`: in a 23-second window, 23 lines of which 15 were permission checks and 8 real events. The Activity audit trail already records this in the database.

Evidence:

- [ops-09-server-log-permission-noise.png](../tasks/qa-evidence/ops/ops-09-server-log-permission-noise.png)

## Root cause

`backend_server/src/lib/auth_middleware.py:1213` printed a line for **every allowed request**:

```python
print(f"[@auth_middleware] ✅ Permission check passed: {permission}")
```

`require_permission` sits on most of the `/server/*` routes, and each decorated route also runs the role check, which printed its own line (`auth_middleware.py:1009`, `✅ Role check passed: <role> in <roles>`). Both are the *normal* outcome, so the log grew with the traffic while saying nothing.

Measured on the live server (2026-10-22, `journalctl -u vpt-server --since "1 hour ago"`):

| | lines |
|---|---|
| everything the server logged in an hour | 6031 |
| of which "Permission check passed" | **369** — the most repeated line of the hour |

The most repeated single permissions: `device_control:pair` (91), `pages.custom:view` (81), `plugins.gitlab:view` (49), `campaigns:execute` (30), `plugins.testrail:view` (22).

What stays in the log: the refusals (`⛔ team scope: …`, `⛔ tenant scope: …`, `⛔ viewer blocked from …`) — those are events, and they are what an operator reads during an incident.

## Fix

The two "check passed" lines are now behind `AUTH_TRACE`, off by default:

- `backend_server/src/lib/auth_middleware.py` — new helper `_auth_trace_enabled()` (reads `AUTH_TRACE` the same way `AUTO_SIGN_ENABLED` / `SERVER_OPEN_MODE` are read: `1`, `true`, `yes`, `on`, `enabled`). Both prints are wrapped in it.
- `AUTH_TRACE=1` brings them back for somebody chasing an auth problem. It is read **per request**, so the Settings page can switch it on and off without restarting the server.

Nothing else changed: the checks still run, they still refuse what they refused, and the refusals are still logged.

## Verification

Tests: `tests/backend_server/test_auth_trace_logging.py` — 3 cases in a Flask request context:

- a successful permission check prints nothing (no "Permission check passed", no "Role check passed");
- a successful role check prints nothing;
- with `AUTH_TRACE=1` both lines come back, with the permission and the role in them.

Against the pre-fix sources the first two cases fail (the lines were printed).

**After the deploy** (build main-2026.10.22-89636, the server restarted at 19:22 on 2026-10-22) the live log tells the story: the 20 minutes *before* the restart hold **52** "Permission check passed" lines and 10 "Role check passed" lines; the minutes *after* it hold **zero** of either, while the log keeps its real events (host pings, metrics, redis).

Re-checked over the whole evening, with the server restarted again at 19:37 on 2026-10-22 (a build that carries other work): **406** "Permission check passed" lines in the 42 minutes before the fix, **0** in the 19:22 → 19:37 window, and **0** again after the 19:37 restart — the fix survives a later deploy. "Role check passed" reads 0 since 19:22 as well. The log is not silent: it holds 1405 lines of real events over the same period.

Checks: `pytest tests/backend_server/test_auth_trace_logging.py` 3/3 · the gate's ruff selection (`E9,F63,F7,F82`) clean on the changed files.
