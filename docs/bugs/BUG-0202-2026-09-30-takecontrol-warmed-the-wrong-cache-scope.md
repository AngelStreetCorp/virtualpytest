# BUG-0202 — Take-control warmed the navigation cache for base, so the first run under a variant rebuilt the hierarchy anyway

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                            |
|-----------|------------------------------------------------------------------|
| ID        | BUG-0202                                                         |
| Reported  | 2026-09-30                                                       |
| Severity  | Low — wasted work; measured 0.068s on the lab, larger on a big hierarchy or a loaded DB |
| Status    | Fixed (pending deploy)                                           |
| Area      | `backend_server/src/routes/server_control_routes.py` · device-control hooks |
| Fixed in  | Unreleased                                                       |
| Related   | [BUG-0200](BUG-0200-2026-09-30-node-verification-runs-under-a-leftover-variant.md) (same cache key, the correctness half) |
| Commit    | this commit                                                      |

---

## Cause

Taking control pre-builds the unified navigation graph on the host so the first run
doesn't pay for it. The cache is keyed per scope — `unified_<tree>_<team>_<scope>`,
where scope is the variant's row id or `__base__` — and the helper takes six
parameters:

```python
# server_control_routes.py:982
def populate_navigation_cache_for_control(tree_id, team_id, host_name,
                                         force=False, device_id=None, variant=None)
```

Take-control passed three. With no `variant` and no `device_id` the host route cannot
derive a scope — it reads the query param, then falls back to the device's
`navigation_context['variant']`, which it cannot reach without a `device_id`
(`host_navigation_routes.py:608-616`) — so it wrote `__base__`. A run under a variant
then read the variant key, missed, and rebuilt the whole hierarchy mid-run.

The helper's own docstring already warned about exactly this:

> *"Pass `variant` explicitly when the caller already knows which variant the upcoming
> read will use… otherwise callers would always (re)populate `__base__` while the read
> path queries the device's active variant."*

`/execute` and `/preview` pass it. Take-control did not — while the editor header that
triggers it already holds `viewingScope`.

## Fix

The scope travels with take-control: `Navigation_EditorHeader` passes `viewingScope`
into `useDeviceControlWithForceUnlock` → `useDeviceControl` → `takeControl` →
the request body, and `_try_populate_navigation_cache` forwards both `variant` and
`device_id` (it already had the whole request `data`, so no signature change).

## Measuring it

`scripts/measure_cache_warmup.py`, run **on a host** — it calls the same TreeManager the
run path calls, so nothing is simulated:

```bash
cd /opt/virtualpytest
sudo -u <service-user> venv/bin/python scripts/measure_cache_warmup.py \
    --userinterface stb_tv --team <team-id> --variant variant1
```

It clears the scoped cache, times the load cold (what a run pays today), times it warm
(what it pays once the right scope is warmed), and averages over `--repeat` pairs.

**Measured on a lab host** (`stb_tv`, 14-tree hierarchy, DB on the same LAN):

```
run 3: cold 0.081s   warm 0.010s
run pays today (cold, wrong scope warmed) : 0.078s
run pays after the fix (scope warmed)     : 0.010s
GAIN on the first run in this scope       : 0.068s
```

68 ms — small, and worth saying plainly: the cold path is ~10 serialized DB round trips,
so it scales with hierarchy size and DB latency, not with anything the fix changes. A
36-tree interface on a loaded remote database is where the number gets interesting, and
the script is how to get it there rather than guessing.

Caveats the script prints with the result: the gain is once per scope per host process,
not per run; take-control already fetched the hierarchy server-side either way, so what
the fix removes is the **host** redoing it for the right scope; and
`clear_unified_cache()` drops every tree's cached graph on that host, so run it idle.

## What this does not fix

A scope warmed at take-control is stale the moment the canvas variant is switched — and
switching is the point of the toggle. The warm-up is best-effort; the robust half is
[BUG-0200](BUG-0200-2026-09-30-node-verification-runs-under-a-leftover-variant.md),
which makes every run declare its own scope so the read self-heals.
