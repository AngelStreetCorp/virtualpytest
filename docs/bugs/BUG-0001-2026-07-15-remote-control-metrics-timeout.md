# BUG-0001 — /remote-control metrics timeout on large interfaces

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                    |
|-----------|----------------------------------------------------------|
| ID        | BUG-0001                                                 |
| Reported  | 2026-07-15                                               |
| Status    | Fixed (pending deploy)                                   |
| Severity  | High                                                     |
| Area      | backend / db / userinterface                             |
| Fixed in  | build 8414                                               |
| Commit    | `8a1906888`                                              |

---

## Symptom

On prod, opening `/remote-control` (NavigationEditor) for the `example_tv` userinterface fails to
load its metrics:

```
GET /server/navigationTrees/getTreeByUserInterfaceId/6b481457-5ee8-4e9a-819b-d56533e93c11?include_metrics=true&team_id=...
→ 500 Internal Server Error
{"error": "{'message': 'canceling statement due to statement timeout', 'code': '57014', ...}"}
```

Frontend then shows `[@TreeCache] ⚠️ metrics-only fetch failed` and the editor can't attach
per-node/per-edge metrics.

A **freshly duplicated** interface loads fine — which pointed straight at data volume, not the
interface itself: the duplicate has no execution history for the timing-out query to scan.

## Root cause

`include_metrics=true` runs the Postgres RPC `get_tree_metrics_optimized`
(`setup/db/migrations/20260508_e_metrics_hierarchy_expand.sql`). The node/edge aggregate reads hit
small pre-aggregated tables and are cheap. The cost is a **per-edge correlated subquery** that
fetches the latest `kpi_report_url` from the raw `execution_results` table (lines 82–93):

```sql
SELECT er.kpi_report_url FROM public.execution_results er
WHERE er.team_id = p_team_id
  AND er.tree_id = ANY(v_tree_ids)
  AND er.edge_id = em.edge_id
  AND er.action_set_id = em.action_set_id
  AND er.variant IS NOT DISTINCT FROM em.variant
  AND er.kpi_report_url IS NOT NULL
ORDER BY er.executed_at DESC
LIMIT 1
```

`execution_results` has **no index on `edge_id` / `action_set_id`**, so for every edge in the tree
Postgres scans + sorts the raw execution history. N edges × a large history = statement timeout
(57014). The `20260507_b` migration comment claimed "each edge is a fast index lookup of the most
recent row" — but that supporting index was never created, and `20260508_e` then widened the filter
from `tree_id = p_tree_id` to `tree_id = ANY(...)`, making it worse.

## Fix

Add the partial composite index the RPC already assumes — no function change needed:

`setup/db/migrations/20260715_kpi_report_url_edge_lookup_index.sql`

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_results_kpi_edge_lookup
    ON public.execution_results (team_id, edge_id, action_set_id, variant, executed_at DESC)
    WHERE kpi_report_url IS NOT NULL;
```

The leading equality columns + `executed_at DESC` turn each per-edge lookup into a top-1 index
probe; `tree_id = ANY(...)` stays a cheap residual filter over the already-narrow slice.

The same index is mirrored into the fresh-install schema
(`setup/db/schema/003_test_execution_tables.sql`, plain `CREATE INDEX`) so new DBs get it without
replaying migrations.

Deploy note: built `CONCURRENTLY` so it doesn't block writes; must run standalone (not inside a
`BEGIN/COMMIT`). Must be applied to the DB backing the affected customer prod host.

## Verification

Reload `example_tv` `/remote-control` — the `getTreeByUserInterfaceId?include_metrics=true` call
returns in milliseconds instead of timing out, and per-node/edge metrics attach normally.
