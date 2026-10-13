# BUG-0238 — Jira instance settings ignored the plugins.jira permissions

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0238                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — the default roles that can write (tester, developer, manager) all hold `plugins.jira:manage` anyway; the gap was for accounts whose grant was removed by an individual denial or a team ceiling. It matters more since an instance's `teamIds` decides which teams may push test-result defects (TASK-42) |
| Area      | `backend_server/src/routes/server_integrations_routes.py` (`/server/integrations/jira/instances` GET / POST / DELETE) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

The Jira integration page is gated by `plugins.jira:view` in the menu, but the three instance
routes behind it carried no permission decorator. Any authenticated tester or developer could
call them directly: list the configured instances, replace a domain / email / API token, or
delete an instance — including an account whose `plugins.jira:manage` had been denied
individually or by its team ceiling. The TestRail routes in the same file were gated; the Jira ones never were.

## Root cause

The Jira routes predate the fine-grained permission catalog and were never given a decorator
when `plugins.jira:view` / `plugins.jira:manage` were added; the global guard only checks that
the caller is signed in and not a viewer.

## Fix

`GET /server/integrations/jira/instances` requires `plugins.jira:view`; `POST` and `DELETE`
require `plugins.jira:manage` (the same split as TestRail). Found by the TASK-42 final review:
an instance's `teamIds` list now authorizes which teams' test-result defects may be pushed to
it, so editing an instance has to be a managed action.

## Verification

- TASK-42 gate: backend route tests and the auth/permission regression set
  (`test_auth_guard`, `test_permission_resolution`, `test_access_ceilings`,
  `test_permission_escalation`) pass on the candidate.
- Live check 2026-10-05 (`main-2026.10.05-9986`): a viewer JWT gets 403 on
  `POST /server/integrations/jira/instances`; a tester JWT passes the permission check (the role
  catalog grants testers `plugins.jira:manage`) and reaches validation (400 for a bad body).
