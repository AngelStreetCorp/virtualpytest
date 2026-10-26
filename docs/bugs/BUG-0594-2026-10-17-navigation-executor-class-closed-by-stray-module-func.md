# BUG-0590 — `def _now_iso()` at module level closed the `NavigationExecutor` class early, hiding `load_navigation_tree` and `get_navigation_preview`

## Summary
`backend_host/src/services/navigation/navigation_executor.py` accidentally had a
top-level `def _now_iso()` at line 1222 (indent 0) inside the `NavigationExecutor` class
which STARTS at line 259. A top-level `def` inside a class body **closes the class
immediately** in Python. Every method after line 1222 — `load_navigation_tree` (line 3416),
`get_navigation_preview` (line 3294), `get_execution_status` (line 3257), the entire
verification-recording block — was therefore a **module-level function**, not a
`NavigationExecutor` method. `class.method()` calls (`device.navigation_executor.load_navigation_tree(...)`)
exploded at runtime with `AttributeError: 'NavigationExecutor' object has no attribute 'load_navigation_tree'`.
The class dict only carried the methods declared before the stray `def`.

## Effect
Every host script that goes through the navigation executor failed in 5 s with:
```
[game/game_pokemon.py] ❌ [game_pokemon] Unexpected error: 'NavigationExecutor' object has no attribute 'load_navigation_tree'
```
The `pokemon-long-play-jev` scheduler on host-clone-1 (15-min cadence, jev chooser) and
several smoke scripts (`smoke_video_stream`, `smoke_heatmap`, `smoke_network_server`) all
hit the same traceback between 2026-10-15 12:45 CEST and the fix at 2026-10-17 13:05 UTC.
Local repro: a clean Python `hasattr(NavigationExecutor, 'load_navigation_tree')` returned
`False` even though `def load_navigation_tree` was visible at line 3416 — an AST walk
confirmed the function has `parent_class=None`, not `NavigationExecutor`.

## Repro on codebox (2026-10-17 13:00 UTC)
- `wc -l backend_host/src/services/navigation/navigation_executor.py` → ~4080
- line 1222 indent 0 `def _now_iso() -> str:` ← closes the class
- `from backend_host.src.services.navigation.navigation_executor import NavigationExecutor` → `class` imported
- `hasattr(NavigationExecutor, 'load_navigation_tree')` → `False` (the bug)
- fix: change the `def` to a `@staticmethod` indented 4 spaces, indent body 8 spaces → class dict
  regains `load_navigation_tree` (and `get_navigation_preview`, `get_execution_status`)
- `hasattr(NavigationExecutor, 'load_navigation_tree')` → `True`

## Why it slipped past code review
The class was syntactically valid: the stray `def` at indent 0 is legal Python. The rest of
the file (lines 1228..end) parses cleanly, so flake8 / pyflakes / mypy / pre-commit saw
nothing wrong. The bug only manifests at RUNTIME when a `NavigationExecutor` instance is
asked for `load_navigation_tree` (which game_pokemon.py does on every script start, since
it always tries to load the navigation tree for `pokemon-blue-web` before the saffron
runner can run). 107/107 pokemon tests still pass because they exercise the Runner class,
not the NavigationExecutor.

## Cross-impact (also fixed by the same indent)
Methods on `NavigationExecutor` that were declared between lines 1228 and 3416 and were
silently module-level:
- `load_navigation_tree` (line 3416) — `device.navigation_executor.load_navigation_tree(...)` in `test_scripts/game/game_pokemon.py`
- `get_navigation_preview` (line 3294) — `/server/host/navigation_preview` route
- `get_execution_status` (line 3257) — `/server/host/execution/<id>` route
- `clear_preview_cache`, `localize_check`, `localize`, `get_available_context`, `get_for_device`
  — also affected but happen to never be called from the pokemon path. They are restored
  by the same fix.

## Fix
```diff
- def _now_iso() -> str:
-     """ISO-8601 UTC with explicit timezone; ..."""
-     from datetime import datetime, timezone
-     return datetime.now(timezone.utc).isoformat()
+     @staticmethod
+     def _now_iso() -> str:
+         """ISO-8601 UTC with explicit timezone; ..."""
+         from datetime import datetime, timezone
+         return datetime.now(timezone.utc).isoformat()
```

`NavigationExecutor._now_iso()` is now callable; all the later `def`s are class methods.
Live verification on host-clone-1: post-deploy, the `pokemon-long-play-jev` run starts up
the runner (no more `'NavigationExecutor' object has no attribute 'load_navigation_tree'`
trace), the saffron GUIDE-skip fix from BUG-0589 gets a chance to fire, and the host save
memo `guide_i` advances from `9` to `11` (recorded as `kind=guide_skip, from_=9, to=11,
map=6`).

## Why `_now_iso()` was at indent 0 to begin with
Speculative: a previous patch must have intended `_now_iso` to be a module-level utility
helper but it lives next to `def _attach_verification_to_step(self, ...)` which IS a class
method (taking `self`). Two classmates, different scopes — a textbook mistake. The static
method captures the original intent (no `self` available at module level, but a `@staticmethod`
inside the class does what the helper did before).
