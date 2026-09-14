# BUG-0074 — Grafana variables/panels fail intermittently on a large DB: Postgres parallel workers exhaust the container's 64 MB `/dev/shm`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0074                                                                    |
| Reported  | 2026-09-10 (customer Grafana, the customer's team dashboards)     |
| Status    | Fixed (applied by hand on the customer DB; migration pending on lab / QualiAI) |
| Severity  | Medium (dashboard filters show a query error on load; values stay cached, panels sharing the DB can fail the same way) |
| Area      | Postgres in Docker (Supabase CLI stack) · Grafana `postgres` datasource role |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

On the customer Grafana, several template variables (`HGW Model`, `HGW MAC`, `HGW Firmware`)
show a red warning on dashboard load. The tooltip says the SQL query failed and shows the
query, e.g.

```sql
SELECT DISTINCT COALESCE(metadata->>'firmware_version', 'Unknown')
FROM script_results WHERE script_name = 'gw_info' AND success = true ORDER BY 1
```

The dropdown is still populated (Grafana keeps the last successfully cached options), so it
looks like a transient timeout. Reordering the variables makes a *different* variable fail —
whichever one runs at the wrong moment. Same variables on the lab dashboard: fine.

## Investigation (what it was not)

- **Query plan / index.** `EXPLAIN ANALYZE` on the customer DB (`script_results` 1.7M rows,
  93K `gw_info`): 0.7 s with 2 parallel workers, 1.4 s without. Adding
  `(script_name, success)` (migration `20260910_…`) trims ~15% of heap reads but the time is
  dominated by reading 79K rows' jsonb metadata — and a 1.4 s query cannot trip Grafana's
  30 s default timeout anyway. Kept as a minor improvement, not the fix.
- **`work_mem`.** Raising it removed the *lossy* bitmap pages but not the time, and would
  have made the real problem worse (bigger shared bitmap in `/dev/shm`). **Not applied.**
- **`statement_timeout`.** Supabase sets 3 s on `anon` and 8 s on `authenticated` /
  `authenticator`, but Grafana connects as `postgres`, which has none.
- **Memory pressure.** The customer DB VM has 15 GB, swap untouched. (The lab DB VM `.102`
  *was* swapping — 903 MB of 974 MB, Logflare alone holding 260 MB — a separate, real issue
  fixed the same day by stopping `supabase_analytics_supabase`; it does not cause this bug.)

The answer was in the Postgres log, under the Grafana VM's IP and role:

```
10.10.x.61 06:41:10 UTC postgres@postgres ERROR:  could not resize shared memory segment
    "/PostgreSQL.2061818190" to 2097152 bytes: No space left on device
```

103 occurrences in 48 h, all from the Grafana VM. Grafana does not log these (the error is
returned in the query response), which is why its log looked clean.

## Root cause

Postgres parallel workers exchange data through dynamic shared memory segments allocated in
`/dev/shm`. Docker gives every container **64 MB** of `/dev/shm` by default and the Supabase
CLI does not raise it (`docker inspect … ShmSize=67108864` on the customer DB *and* on the
lab DB). A dashboard load fires its variable queries and panel queries at once; on a table the
size of the customer's `script_results`, each gets a parallel plan, they fill the 64 MB
together, and the next segment allocation fails. The failure is intermittent because it
depends on how many parallel queries overlap, and it moves between variables because whichever
query allocates last loses. The lab never hits it because its `script_results` is 70× smaller
and the planner does not go parallel (0 occurrences in 7 days, same 64 MB).

## Fix

`setup/db/migrations/20260910b_postgres_role_no_parallel_workers.sql`:

```sql
ALTER ROLE postgres SET max_parallel_workers_per_gather = 0;
```

The `postgres` role (Grafana datasource + admin psql) no longer requests parallel workers, so
its queries never allocate in `/dev/shm`. Cost: they run single-threaded (customer variable
query ≈ 1.4 s instead of 0.7 s) — but they never fail. Application traffic through PostgREST
(`authenticator` → `anon` / `authenticated` / `service_role`) is untouched.

The setting applies to **new** sessions; Grafana pools connections for up to 4 h, so after
applying it, kick its idle backends (the pool reconnects transparently):

```sql
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
WHERE usename = 'postgres' AND client_addr = '<grafana vm ip>' AND state = 'idle';
```

### Proper fix (maintenance window)

Both need the DB container recreated / Postgres restarted, i.e. seconds of DB outage for the
customer's server and hosts — see `docs/agent/infra/DATABASE.md` → Troubleshooting:

- give the container a real `/dev/shm` (`shm_size: 1g`) — for compose-managed stacks; the
  Supabase CLI has no option for it, or
- `min_dynamic_shared_memory = 256MB` so parallel queries draw from the main shared segment.

Once either is in place: `ALTER ROLE postgres RESET max_parallel_workers_per_gather;`.

## Verification

- Customer DB (`hostdb1`), 2026-09-10: `ALTER ROLE` applied by hand + idle Grafana
  backends terminated; the customer's dashboards reload without the variable warnings.
- Customer DB, by role over 48 h: all 103 failures are `postgres@postgres` (Grafana). The
  PostgREST roles (`authenticator` → `anon`/`authenticated`/`service_role`) never hit it, so the
  role-level fix covers everything that actually failed; the `/dev/shm` fix below is optional
  (only needed to get parallel speed back for Grafana).
- Lab DB (`.102`) and QualiAI: same `ShmSize=67108864`, 0 `No space left on device` in 7 days;
  migrations `20260910` + `20260910b` applied preventively on both (2026-09-10).
- Migration `20260910_…_index` was applied on the customer DB through their migration flow
  before the root cause was known; plan confirmed the index is used (`Index Cond` on both
  columns).

## Follow-ups

- Grafana still connects as the `postgres` superuser (flagged by the 2026-09-08 pentest); a
  dedicated read-only `grafana` role is the place for this kind of tuning.
- `patch_supabase_compose.sh` (minimal mode) only patches a compose file; on Supabase-CLI
  installs (lab, customer) it is a no-op — neither Logflare removal nor a future `shm_size`
  reach them that way.
- [BUG-0075](BUG-0075-2026-09-10-gateway-info-corrected-view-statement-timeout.md) — found in
  the same log: PostgREST kills the `gateway_info_corrected` read every minute on the customer DB.
