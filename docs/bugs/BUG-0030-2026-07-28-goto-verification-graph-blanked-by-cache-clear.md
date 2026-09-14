# BUG-0030 — Goto verification fails "no unified graph loaded" when a cache clear lands mid-navigation

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0030                                                     |
| Reported  | 2026-07-28                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (any goto with verifications can fail spuriously)     |
| Area      | backend_host / navigation — verification executor            |
| Fixed in  | build 8713                                                   |
| Commit    | `dd2207b71`                                                  |

---

## Symptom

A Go To Node run failed at its verification step with:

> Navigation failed at step 1 (poweroff → home): verification failed —
> NavigationExecutor has no unified graph loaded - call load_navigation_tree() first

even though every action executed fine. Reproduced on `example_tv` variant `base_5.28`
(`poweroff → home` via `power_on`, verify `End only`), but the bug is not variant-specific.

## Root cause

A race between an in-flight navigation and host-side cache invalidation:

1. `execute_navigation` starts healthy — it syncs `self.unified_graph` from the
   variant-aware cache at entry, finds the path, and runs `power_on`, then sits in the
   action's 10 s `wait_time` sleep.
2. Meanwhile the server posts `POST /host/navigation/cache/clear/<tree_id>` (no
   `variant` param → whole-tree scope). Only structural writes propagate this clear:
   node delete, edge delete, batch tree save, history restore, or the editor's
   edge-unlink save.
3. `_invalidate_tree_cache_on_host` (`host_navigation_routes.py`) sets
   `ne.unified_graph = None` on **every** device's NavigationExecutor — including the
   one mid-navigation.
4. The navigation wakes up and runs its end-verifications. `verify_node`
   (`verification_executor.py`) deliberately reads the already-loaded graph
   (`self.device.navigation_executor.unified_graph`, "zero cache calls") and
   hard-raised when it found `None`.

The execute path already self-heals from exactly this state (`_sync_unified_graph` at
entry re-fetches from the variant-aware cache and auto-populates from the DB on a cold
cache); the verify path had no such recovery.

It surfaced during variant work simply because variant editing generates frequent
whole-tree cache clears — any goto whose actions take a few seconds is exposed.

Diagnosed from the host journal (09:27:53 goto start + graph synced, 09:27:54 cache
clear arrives, 09:27:59 "file cache + 4 NavigationExecutor instances" cleared,
verification then fails).

## Fix

`verify_node` now mirrors the execute path: when `unified_graph` is `None`, it calls
`navigation_executor._sync_unified_graph(tree_id, team_id, userinterface_name)` to
re-fetch the variant-aware cached graph (auto-populating from the DB on miss), and only
raises the original error if that also comes back empty.

Not fixed by skipping mid-flight devices in the clear route — that would leave a stale
graph in place, which is the exact drift the whole-tree invalidation exists to prevent.

## Verification

- Root cause confirmed from the customer host journal: the goto's graph was synced and
  healthy at 09:27:53, the whole-tree clear landed at 09:27:54 ("file cache + 4
  NavigationExecutor instances"), and the verification raised right after the 10 s wait.
- Fix is the same `_sync_unified_graph` self-heal the execute path already uses on every
  call; the sync branch is only entered when the snapshot is `None`, so a normal goto
  (no concurrent clear) is unchanged. Not yet re-run against a live device — needs a
  deploy to the affected environment.
