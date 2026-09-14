# BUG-0059 — Seven backend CI tests failing on every run (four unrelated causes)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0059                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (pending server deploy for causes 1 and 3)             |
| Severity  | Low (CI signal noise; one real route bug behind it)          |
| Area      | tests/backend_server · server_pathfinding_routes · auth guard allow-list |
| Fixed in  | build 8713                                                   |
| Commit    | `11850f82c`                                                        |

---

## Symptom

Once the backend job wrote its report again (BUG-0058), runs #291, #292 and #294 all showed
the same 7 failures out of ~435 tests.

## Causes and fixes

| Tests | Cause | Fix |
|---|---|---|
| `test_pathfinding::*_requires_team_id` (3) | Routes call `request.get_json()` on GET. With `Content-Type: application/json` and no body (what the tests and the SPA send) werkzeug raises `BadRequest`, so the client gets the generic 400 text instead of `{success:false, error:"team_id required"}`. A real bug, not just a test issue. | `get_json(silent=True)` throughout `server_pathfinding_routes.py` |
| `test_ci_reports::test_serve_report_unknown_run_returns_404` (1) | `/server/cicd/report/*` is authenticated since the closed-by-default guard (BUG-0057); the probe sent no credential and got 401. | Test sends the service key |
| `test_storage::test_storage_health` (1) | `/server/storage/health` fell under the guard although its docstring says "no authentication required" and the Status page polls it as a liveness probe. | Added to the guard's unauthenticated prefixes next to `/server/health` |
| `test_campaign_virtual_script_steps` (2) | `patch("backend_host.src.lib.utils.host_utils.get_device_by_id")` must import `backend_host.src`, whose `__init__` imports every controller and therefore OpenCV — not installed on the CI runners → `AttributeError: module 'backend_host' has no attribute 'src'`. | Test registers stub packages for that dotted path when the real import fails, and is marked `@pytest.mark.unit` (no live server needed). Verified locally with `cv2` blocked and with it present. |

## Verification

Causes 2 and 4 are test-side and go green on the next CI run. Causes 1 and 3 are server-side
and stay red until the server is deployed with `11850f82c`.
