# BUG-0212 — Grafana Workspace drop-down offered only "None" to the built-in admin

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0212                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | db / grafana                                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Signed in to Grafana as its built-in `admin` account, every dashboard's **Workspace** drop-down
(TASK-31 phase D) listed only **None**. The workspace filter could not be used. The panels still
showed every device.

## Root cause

The two functions the dashboards call identified the viewer differently:

- `grafana_device_scope(email, login, workspace)` recognises the built-in admin by its **login**
  (`login = 'admin'` → `*`, see everything).
- `grafana_user_workspaces(email)` matched the viewer to a VirtualPyTest profile by **email** only.
  The built-in admin's email is `admin@localhost`, which has no profile, so it returned no rows.

So the built-in admin was treated as an admin for devices but as an unknown user for workspaces.

## Fix

`grafana_user_workspaces` now takes the login as well, `(p_email TEXT, p_login TEXT DEFAULT '')`,
and lists every workspace for login `admin`, the same rule as `grafana_device_scope`.

- Migration `setup/db/migrations/20261001d_grafana_workspaces_builtin_admin.sql` (rollback
  alongside); schema twin `setup/db/schema/056_grafana_device_scope.sql`. The login defaults to `''`,
  so dashboards not yet re-imported keep working.
- `infra/monitoring/grafana/dashboards/_apply_device_scope.py` passes `${__user.login}` in the
  Workspace query; re-run over the 21 repo dashboards, plus `features/avq/grafana/audio-video-quality.json`
  (only the Workspace query changed).
- `tests/backend_server/test_dashboard_device_scope.py` asserts the Workspace query passes the login.

## Verification

- Ran the migration on the node1 lab DB in a transaction, then rolled it back:
  `grafana_user_workspaces('admin@localhost', 'admin')` returned 3 workspaces (previously 0); a
  VirtualPyTest admin returned 3; an unknown account returned 0; the old one-argument call still
  ran; `SET ROLE postgres` (the node1 Grafana datasource login) could still execute it.
- `_check_device_scope.py`: `device scope OK (23 dashboards)`; the device-scope tests pass.
- After applying the migration and re-importing the dashboards, sign in as Grafana `admin` and open
  any dashboard: the Workspace drop-down should list every workspace.
