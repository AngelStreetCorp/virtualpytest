# BUG-0200 — Node verification ran under whatever variant an earlier request had left on the device, so its metrics landed on the wrong scope

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                    |
|-----------|--------------------------------------------------------------------------|
| ID        | BUG-0200                                                                 |
| Reported  | 2026-09-30                                                               |
| Severity  | Medium — node_metrics attributed to the wrong variant; a wasted tree rebuild per run |
| Status    | Fixed (pending deploy)                                                   |
| Area      | `backend_host` verification route + navigation_executor · frontend verification hooks |
| Fixed in  | Unreleased                                                               |
| Commit    | this commit                                                              |

---

## Symptom

Found while investigating why an editor verification's completion event was slow to appear: the
host log showed the verification finishing in 480 ms and then, *before* it could report anything,
rebuilding the entire tree hierarchy:

```
record_node_execution  ✗ 480ms | Batch verification completed: 0/2 passed
🗺️ [TreeManager] Loading navigation tree for 'example_tv' (variant=base_5.30)
🔄 [TreeManager] Cache miss - loading from database...
⚡ Retrieved 36/36 trees in 1 query(s)
🎭 Composed variant scope 'base_5.30' from 1 variant(s)
✅ Cached to memory: unified_a1e05da1-…_7fdeb4bb-…_b0283e09-22cc-4edc-94b2-5e8d32d00c4a
```

Five seconds earlier the frontend had already populated that cache
(`POST /host/navigation/cache/populate/a1e05da1-…?team_id=… 200`), and it still missed.

## Root cause

**1. The verification never declared its run scope.** `host_verification_routes.py` builds
`device.navigation_context` and stamps only `is_test`. The *only* writers of
`navigation_context['variant']` were `/host/navigation/execute`, `/host/action` and
`/host/navigation/localize` — and nothing resets that dict on take-control or release. So a node
verification read whatever variant an unrelated earlier request had left behind, and that value is
what:

- `record_node_execution` writes as the `variant` column (`navigation_executor.py:769`), so the
  **node_metrics row can be attributed to the wrong scope entirely** — switch the canvas variant
  and run a node verification with no goto in between and the metric lands on the previous scope;
- `localize_check` resolves its unified graph under.

Edges never had this problem: `useEdge.ts:37` has always stamped the variant on every edge run
(`props?.variant ?? runVariant ?? null`). Nodes simply were not wired the same way.

**2. The cache key the frontend pre-populated could not be the one the read wanted.** The unified
graph key is four parts — `unified_<tree>_<team>_<variant_scope_id>`
(`shared/src/lib/utils/navigation_cache.py:104-111`), where the scope is the
`userinterface_variants.id`, or `__base__` for base. The take-control populate route derives the
variant from exactly two inputs — a `variant` query param or a `device_id` to read it from
(`host_navigation_routes.py:608-616`) — and take-control passes neither
(`server_control_routes.py:158`), so it wrote `…___base__` while localize read
`…_b0283e09-…`. TTL (1 h), tree/team components and per-process memory are all ruled out; the host
is a single process and a later run hit the same key at age 242.7 s.

**3. `localize_check` threw away the `tree_id` it was given.** It received `tree_id` at
`execute_single_node_verification` and called `localize_check(node_id, team_id,
userinterface_name)` without it, so `localize` took its `if not tree_id:` branch and ran the full
TreeManager load on **every** call — three extra DB round trips even on a warm cache.

## Fix

- **The scope is declared end to end.** `useVerification` takes a `variant` and puts it in the
  batch payload; `useNodeEdit` supplies `runVariant` from the navigation context, the same source
  `useEdge` uses; `host_verification_routes.py` stamps it onto `navigation_context` next to
  `is_test`. That fixes the metric attribution *and* makes localize resolve the scope the user is
  actually looking at — which is also the key the cache holds.
- **`localize_check` threads `tree_id` through** to `localize`, so a warm run skips
  `load_navigation_tree` entirely.
- **Deleted `backend_host/src/lib/utils/navigation_cache.py`** — a dead duplicate with the old
  3-part key and no variant support, its own module-level dicts, and a docstring claiming a 24 h
  TTL where the live module uses 1 h. Every import in the tree already resolved to
  `shared.src.lib.utils.navigation_cache`; the only references left were two copies of
  `docs/technical/architecture/navigation.md`, whose example now points at the real module and
  passes the scope.

Not changed, and deliberately: the completion event still waits for `localize_check`. With the
scope declared the localize is a cache hit (~1 s warm, ≈3-4 s on a cold variant, 5-6 s on a loaded
remote DB) against a frontend budget with a 20 s floor, so it delays rather than hides. Decoupling
it is worth doing on principle — a best-effort diagnostic should not gate a result that already
exists — but it needs a frontend follow-up poll, because the socket waiter resolves and disconnects
on the first terminal status and would drop a second event, silently removing the Localize footer.

Also left alone: take-control's populate still writes the base key
(`server_control_routes.py:123-168` forwards neither `device_id` nor `variant`). With the scope now
declared per run the read self-heals on first use, so that pre-populate is wasted work rather than
a correctness problem — and it could never cover a variant switch made *after* take-control anyway.

## Verification

- `grep` confirms `navigation_context['variant']` is now written by the verification route as well
  as the three navigation/action routes.
- Node verification under a variant: the payload carries `variant`, the recorder writes that scope,
  and localize reports `Memory Cache HIT` on the variant key instead of rebuilding 36 trees.
- Nothing imports the deleted module (0 references across `.py` and `.md`).
