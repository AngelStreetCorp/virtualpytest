# BUG-0203 — Every scoped graph read re-fetched the variant map, with all its override JSON, from the database

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0203                                                          |
| Reported  | 2026-09-30                                                        |
| Severity  | Medium — 47 ms of database per navigation step on a variant run, measured on the lab; more on a remote or loaded DB |
| Status    | Fixed (pending deploy)                                            |
| Area      | `shared/src/lib/utils/navigation_cache.py` · `shared/src/lib/database/userinterface_db.py` |
| Fixed in  | build 90145 |
| Related   | [BUG-0200](BUG-0200-2026-09-30-node-verification-runs-under-a-leftover-variant.md), [BUG-0202](BUG-0202-2026-09-30-takecontrol-warmed-the-wrong-cache-scope.md) (same cache key) |
| Commit    | this commit                                                       |

---

## Cause

The unified graph cache key includes the variant *scope*, resolved from variant names to
their stable row ids — and that resolution called `list_variants` **fresh on every key
construction**, by design:

```python
# the comment this change replaces
# The variant name->id map is fetched FRESH per variant cache-key
# (the rare path) so a rename is reflected immediately — no stale memo to invalidate.
```

"The rare path" is where the reasoning broke: `get_cached_unified_graph` is called from
**28 sites** and roughly 15 times per navigation step (pathfinding, the executors, the
action layer), and every one of those reads builds a key. So a variant run paid a
database round trip *per graph read*.

Worse, `list_variants` selects `node_overrides, edge_overrides` — every variant's full
override JSON — which this resolver never looks at. It needs `id` and `name`.

Base runs were unaffected: they return `None` with no DB call, which is why this stayed
invisible until variants came into regular use.

## Fix

- `userinterface_db.variant_name_id_map(team_id, userinterface_id)` — `id, name` only.
- `navigation_cache._variant_name_to_id()` memoizes that map for
  `VPT_VARIANT_MAP_TTL_SECONDS` (default 10), lock-guarded, fetching outside the lock so
  concurrent misses don't serialise behind one round trip.
- `clear_unified_cache()` drops the memo too, so a rename or delete arriving as a cache
  invalidation cannot be served stale for the rest of the TTL.
- An **empty** result is never cached: a failed read is indistinguishable from "no
  variants", and caching it would key every run by name until it expired.

Staleness is bounded and benign by construction: keys are ids, so a rename never
invalidates a cached graph, and an unknown component already falls back to a name-based
key — correct, just an extra build until the entry expires.

## Measured

On lab host `.109` against the lab DB on the same LAN, interface `stb_tv`, **one** variant
with a 1,195-character row:

```
list_variants (with node/edge overrides) : 3.2 ms/call   <-- old cost, per scoped graph read
id+name only                             : 1.8 ms/call   <-- new cost, once per TTL
a navigation step does ~15 scoped reads:
   before : 49 ms of DB per step
   after  :  2 ms per step (1 slim call, memoized for the rest)
   saved  : 47 ms per navigation step
```

Reproduce (on a host, with the env loaded — see the note below):

```python
from shared.src.lib.utils.app_utils import load_environment_variables
load_environment_variables('host')
from shared.src.lib.database.userinterface_db import list_variants, variant_name_id_map
# time each over N calls for (team_id, userinterface_id) and multiply by ~15
```

Both scaling factors point the same way on a real install: the customer interface that
prompted this carries **15 node + 18 edge overrides** in one variant (so a much larger
payload per call) against a database where ordinary queries take 1.4 s. A 20-step
navigation there was paying this 300 times.

**A note on measuring it**, because the first two attempts produced numbers that looked
fine and meant nothing: without `load_environment_variables`, `get_supabase()` returns
`None`, `list_variants` swallows that and returns `[]`, and the timing loop measures an
early return. The reproduction above asserts a non-empty read before timing anything —
the same class of trap as the ones in
[async-execution-troubleshooting.md §4](../technical/async-execution-troubleshooting.md).

## Verification

`tests/shared/test_variant_map_memo.py` — 5 cases, no database (the query is replaced and
counted). It pins the trade rather than the implementation:

| test | pins |
|---|---|
| `test_repeated_scoped_reads_hit_the_memo` | 15 reads cost **one** lookup, and the key stays stable and id-based |
| `test_base_run_never_resolves` | the common path still makes no DB call at all |
| `test_empty_result_is_not_cached` | a failed read is retried, not memoized into name-keying |
| `test_ttl_expires` | the memo does expire |
| `test_graph_invalidation_also_drops_the_map` | a rename arriving as an invalidation resolves to the same stable id afterwards |
