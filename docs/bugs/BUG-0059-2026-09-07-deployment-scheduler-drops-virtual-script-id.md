# BUG-0059 — Deployment scheduler never runs the right virtual-script row

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0059                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (DB applied, code pending deploy)                      |
| Severity  | Medium                                                       |
| Area      | frontend / backend / db                                      |
| Fixed in  | build 8713                                                    |
| Commit    | `988ed4a83`                                                  |

---

## Symptom

A virtual script queued through the deployment scheduler — because its device was
locked, because it was part of a 2+-script batch "Run", or because it was scheduled
for later — either ran the wrong dev/test/prod version or failed outright. Only the
immediate single-script "Run" (which bypasses the scheduler) reliably ran the correct
row. This was called out as a known follow-up in
[BUG-0048](BUG-0048-2026-09-04-virtual-script-rerun-loses-id.md): "Queued-deployment
execution of virtual scripts remains a separate follow-up — the scheduler doesn't
persist/forward `virtual_script_id` yet."

## Root cause

`backend_host/src/services/deployment_scheduler.py`'s `_execute_deployment` already
knew how to run a virtual script — it reads `dep.get('virtual_script_id')` and, when
set, materializes that DB row's source to a temp file via the same `ScriptExecutor`
the immediate-run path uses. But nothing ever wrote a `virtual_script_id` into the
`deployments` table: the column didn't exist, `server_deployment_routes.py`'s
`create_deployment` never read it from the request body, and none of
`RunTests.tsx`'s four deployment-creating call sites
(`createOneShotScriptDeployment` / locked-device queue, the runtime "device went
locked mid-run" fallback, `createScheduledRuns`, `handleMultiScriptDeployment`) sent
it. `dep.get('virtual_script_id')` on the host side always read `None`, so a queued
virtual script either ran the fallback (wrong) row or, since its `script_name`
doesn't end in `.py` and isn't `virtual_script_id`-tagged, was misclassified as a DB
campaign deployment.

## Fix

- `setup/db/schema/011_deployments.sql` / `setup/db/migrations/20260907d_deployments_virtual_script_id.sql` —
  add `deployments.virtual_script_id` (uuid) and `deployments.environment`
  (dev/test/prod, default `prod`).
- `backend_server/src/routes/server_deployment_routes.py::create_deployment` —
  persist both optional fields.
- `backend_host/src/services/deployment_scheduler.py` — thread `environment` into
  the `execute_script(...)` call too (`virtual_script_id` was already wired, just
  starved of data).
- `frontend/src/hooks/useDeployment.ts` — widen the `Deployment` interface.
- `frontend/src/pages/RunTests.tsx` — `createOneShotScriptDeployment` and
  `queueScriptExecutionFallback` now accept and forward `virtualScriptId`/
  `environment`; every deployment-creating call site resolves its own per-item
  environment (`getItemEnvironment`/`resolveVirtualScriptId`, the same helpers
  behind the new per-script environment selector) and passes it through.

## Verification

1. Applied `20260907d_deployments_virtual_script_id.sql` directly against the DB
   (`\d deployments` confirms `virtual_script_id uuid` and
   `environment varchar(10) default 'prod'`); reloaded the PostgREST schema cache.
2. `tsc --noEmit` and `eslint` clean on every touched frontend file; `ast.parse`
   clean on every touched backend file.
3. Manual follow-up once deployed: lock a device running a virtual script, queue a
   second run of it, confirm the queued run replays the same dev/test/prod row
   (not a "script not found" / miscategorized-as-campaign failure); repeat for a
   2+-script batch run and a scheduled/planned run.
