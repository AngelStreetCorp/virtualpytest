# BUG-0066 — `/server/api-testing/{categories,run,quick}` always 500: `TEST_CONFIG` was never defined

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0066                                                                    |
| Reported  | 2026-09-08                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Low — the server-side API-testing runner was unusable, nothing else affected |
| Area      | backend_server/src/routes/server_api_testing_routes.py                      |
| Fixed in  | build 8887                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

```
GET  /server/api-testing/categories -> 500 {"error":"name 'TEST_CONFIG' is not defined","success":false}
POST /server/api-testing/run        -> 500 (same)
POST /server/api-testing/quick      -> 500 (same)
```

Found by the first run of the new `api-routes` CI sweep (`run_api_tests.py --discover`), which
hits every GET route the server registers: it was the only 5xx among 101 rules.

## Root cause

The module reads `TEST_CONFIG['endpoints']` in three handlers but never assigns `TEST_CONFIG`.
`CRITICAL_ROUTES` (the static list the name was meant for) exists right above the handlers.
Python only resolves the name at call time, so import succeeded and every call raised
`NameError`, turned into a 500 by the route's `except`.

The pytest suite had noticed — `tests/backend_server/test_api_testing.py` carried a test named
`test_get_categories_current_contract` that **asserted the 500** as documented behaviour, which
is how the defect survived 545 green tests.

## Fix

`TEST_CONFIG = {"endpoints": CRITICAL_ROUTES}` right after the list. The test now asserts the
200 and that the `critical` category is present.

## Deploy

Code only, no migration. Until the server is redeployed, `backend-server-tests` fails that one
test and `api-routes` reports one failure on `/server/api-testing/categories`.
