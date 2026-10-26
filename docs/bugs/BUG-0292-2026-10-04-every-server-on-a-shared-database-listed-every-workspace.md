# BUG-0292 — Every server on a shared database listed every workspace

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0292                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | db / backend / frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Switching the server selector between Awesomation and vpt-pi1 (RPI1-server) on
`/workspaces` showed the same workspaces on both, and the workspace switcher offered the same
list everywhere, although a workspace is meant to belong to the server it was made on.

## Root cause

The frontend already re-fetches per selected server (query keys scoped by server since
`402524064b`). But RPI1-server's `SUPABASE_URL` is the same Supabase as Awesomation's (through
the public `/supabase` proxy), and `public.workspaces` had no column saying which server a
workspace belongs to — so both servers returned the whole table.

## Fix

- `setup/db/migrations/20261004a_workspaces_server_name.sql` (+ rollback; twin in
  `setup/db/schema/030_workspaces.sql`): `workspaces.server_name TEXT NOT NULL`. Existing rows go
  to the server named by `-v owner_server=...` (Awesomation on the lab database).
- `shared/src/lib/database/workspaces_db.py`: a server lists and reads only workspaces whose
  `server_name` is its own `SERVER_NAME`; create always writes that name, update never changes it.
- `backend_server/src/routes/server_workspaces_routes.py`: update, delete and member changes on
  another server's workspace answer 404.

- `setup/db/migrations/20261004b_workspaces_slug_per_server.sql`: the slug is unique per
  server (`UNIQUE (server_name, slug)`), not per database. Before it, creating "Streams" on
  RPI1-server failed with "A workspace with slug 'streams' already exists" because Awesomation
  had one.

- `frontend/src/pages/Workspaces.tsx`: the Devices tab offers only the selected server's devices.
  It merged every server's hosts, so a workspace made on RPI1-server listed host-clone-1 and the
  labox-* hosts, which belong to Awesomation.

No shared workspaces: one that belongs elsewhere is deleted and recreated on that server.

## Verification

Apply the migration, deploy both servers, then on `/workspaces` create a workspace on
Awesomation: it is listed there and not on RPI1-server, and the reverse. Unit tests: `tests/shared/test_workspaces_server_scope.py`.
