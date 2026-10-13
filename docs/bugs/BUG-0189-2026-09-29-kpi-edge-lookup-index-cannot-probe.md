# BUG-0189 — BUG-0001 came back: its index could never make the per-edge KPI lookup a top-1 probe

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                    |
|-----------|------------------------------------------------------------------------------------------|
| ID        | BUG-0189                                                                                 |
| Reported  | 2026-09-29 (a customer install, `example_tv` — the same interface as BUG-0001)            |
| Status    | Fixed — migration applied on every database (customer, node1, node3)                     |
| Severity  | High — Navigation editor loads blank, no metrics, intermittent 500s                      |
| Area      | db (`get_tree_metrics_optimized`) / frontend (`useNavigationEditor`)                     |
| Fixed in  | Unreleased                                                                               |
| Commit    | this commit                                                                              |

---

## Symptom

Opening the Navigation editor for a user interface fails intermittently — sometimes twice in a
row, then succeeds on a retry:

```
GET /server/navigationTrees/getTreeByUserInterfaceId/<id>?include_metrics=true&team_id=...
→ 500 Internal Server Error
{"error": "{'message': 'canceling statement due to statement timeout', 'code': '57014', ...}"}
```

and the editor shows an empty canvas plus, in the console:

```
[@TreeCache] ⚠️ Network/server error loading tree for interface <id>: {'message': 'canceling statement due to statement timeout', ...}
[@NavigationEditor:loadTreeForUserInterface] Error loading tree: TypeError: Cannot read properties of null (reading 'success')
```

The customer's build could not be upgraded, so the fix had to be DB-only.

## Root cause

Two independent defects.

**1. The BUG-0001 index cannot do what it claims.** `get_tree_metrics_optimized()` builds the
per-edge payload with a correlated subquery for the latest `kpi_report_url`
(`setup/db/schema/005_monitoring_analytics.sql`). `20260715_kpi_report_url_edge_lookup_index.sql`
added `idx_execution_results_kpi_edge_lookup (team_id, edge_id, action_set_id, variant,
executed_at DESC) WHERE kpi_report_url IS NOT NULL` to make each lookup "a top-1 index probe".
It never was one: the subquery scopes the lookup with

```sql
AND er.variant IS NOT DISTINCT FROM em.variant
```

which is **not an indexable equality**, so `variant` drops out of the `Index Cond` and becomes a
post-scan `Filter`. Once it does, the index can no longer deliver rows in `executed_at DESC`
order for the matching subset, so `ORDER BY ... LIMIT 1` never short-circuits — Postgres reads
**every** KPI row of that edge and top-N sorts it, once per `edge_metrics` row in scope.

Measured on the customer DB (`execution_results` 2,944,915 rows, 46 edges in scope):

| | index entries per edge | buffers | edge aggregation | RPC |
|---|---|---|---|---|
| before | 13,623 (11,978 rejected by the variant filter) | 553,344 (~4.3 GB) | 1865 ms | 3018 ms avg, **7908 ms max** |
| `executed_at DESC` moved ahead of `variant` | 2,807, all rejected | 119,197 | 668 ms | — |
| + `COALESCE(variant,'')` in index **and** function | 0 (empty range) | ~200 | **1.0 ms** | **5 ms avg / 6 ms max** |

`authenticator` carries `statement_timeout=8s`, so a 7.9 s peak meant the RPC died with 57014
whenever the cache was cold — the 500 above. Note the middle row: reordering the index alone is
not enough, because the common case is *no* matching row, and an early-stop scan cannot stop
early when nothing matches.

Aggravating factor on that install: `execution_results` had `last_analyze` and
`last_autoanalyze` both NULL on a 2.9M-row table with 254,347 dead tuples, so the planner was
estimating 8 rows where 1,645 came back.

**2. A failed load crashes the editor instead of reporting.** `NavigationConfigContext`
returns `null` on a failed request ("Return null instead of throwing to make it graceful"), but
`useNavigationEditor.loadTreeByUserInterface` read `result.success` straight off it — so any
transient server error became `TypeError: Cannot read properties of null` and a blank canvas
with no message, hiding the real cause.

## Fix

`setup/db/migrations/20260929g_kpi_edge_scope_index.sql` (+ `_rollback`), DB-only so it applies
to installs that cannot take a new build:

- new `idx_execution_results_kpi_edge_scope (team_id, edge_id, action_set_id,
  (COALESCE(variant,'')), executed_at DESC) WHERE kpi_report_url IS NOT NULL` — all four
  equality columns ahead of the ordering column;
- the subquery in `get_tree_metrics_optimized()` now compares
  `COALESCE(er.variant,'') = COALESCE(em.variant,'')`, matching the index expression (an
  expression index is only usable when the query text matches it). Signature and payload are
  unchanged, so existing builds keep working;
- a guard that raises if any `variant = ''` row exists, since the sentinel would otherwise
  conflate it with base scope (0 rows on lab and on the customer DB);
- drops `idx_execution_results_kpi_edge_lookup` (superseded) and
  `idx_execution_results_kpi_report` (176 MB indexing the URL *string*; nothing looks a row up
  by URL value — the RPC only returns it).

Folded into the fresh-install schema: `setup/db/schema/003_test_execution_tables.sql` (index
set) and `setup/db/schema/005_monitoring_analytics.sql` (function body).

`frontend/src/hooks/navigation/useNavigationEditor.ts` now guards the `null` result and throws a
readable error, so the editor surfaces the failure instead of a `TypeError`.

Rejected along the way: guarding the subquery with `CASE WHEN total_kpi_measurements > 0` (~46%
fewer probes) — 21 `edge_metrics` rows on the customer DB have a report URL while their
`total_kpi_measurements` is 0, so the guard would have silently hidden those KPI chips. That
counter discrepancy is a separate bug.

## Verification

On the customer DB, after applying the migration by hand:

- `EXPLAIN (ANALYZE, BUFFERS)` on the per-edge subquery: `Index Cond` carries all four
  equalities including the `COALESCE`, `Rows Removed by Filter: 0`, no `Sort` node,
  execution 1.028 ms (was 1865 ms).
- `pg_stat_statements` after a reset, reloading the editor: the PostgREST RPC entry reads
  **5 ms avg / 6 ms max** (was 3018 / 7908).
- `SELECT length(get_tree_metrics_optimized(...)::text)` returns the same 50,294-byte payload as
  before the change, and KPI chips still appear on the same edges.
- No further 57014 in the Postgres log, and the editor loads first time.

Lab DB (`execution_results` 7,069 rows), after applying the migration — note the lab never had
BUG-0001's index at all (`20260715` was only ever run on the customer DB), so it had been on the
slow path all along, hidden by its small history:

- old vs new scope comparison over all 317 `edge_metrics` rows: **0** URLs resolve differently
  (48 of them do return a URL, so the check is not vacuous) — `COALESCE(variant,'')` equality is
  semantically identical to `IS NOT DISTINCT FROM` on real data.
- `get_tree_metrics_optimized()` returns its 54,894-byte payload in **6.6 ms**; the per-edge
  subquery plan shows `Index Scan using idx_execution_results_kpi_edge_scope` with all four
  equalities in `Index Cond`, no `Sort`, 0.55 ms for 110 edges.

QualiAI DB (node3, `execution_results` 12,543 rows), same result: index created valid, function
replaced, `Index Cond` carries all four equalities, RPC 17.8 ms for its 3,910-byte payload. Its
equivalence check is vacuous rather than passing — that install has **no** `kpi_report_url` rows
at all, so there is nothing for the scope comparison to get wrong there; the meaningful check is
the lab's 48 URLs above.

Neither node3 nor node1 had `idx_execution_results_kpi_edge_lookup`: `20260715` was only ever run
on the customer DB, so the "fix" for BUG-0001 existed on exactly one database — and did not work
there. The node1 server (`SUPABASE_URL=http://192.168.0.102:54321`) is backed by the same DB the
verification above was run on, so there is no fourth database left to apply this to.

Frontend: with the server forced to fail, the editor now shows the load error instead of
logging `TypeError: Cannot read properties of null (reading 'success')`.
