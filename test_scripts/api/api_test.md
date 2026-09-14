# api_test

Tests API endpoints and validates responses via the VPT script runner UI.
Reads endpoint definitions from `test_scripts/api/api_profiles.json` — the same file used by `test_scripts/api/run_api_tests.py` for CI.

## Usage

```bash
python test_scripts/api/api_test.py --profile smoke     # CI-aligned smoke check (server health)
python test_scripts/api/api_test.py --profile sanity    # Quick health check
python test_scripts/api/api_test.py --profile full      # Full API validation
python test_scripts/api/api_test.py --endpoints "/server/system/health,/server/script/list"
python test_scripts/api/api_test.py --spec server-device-management
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--profile` | string | `sanity` | Predefined profile name (smoke, sanity, full, devices, campaigns, testcases, deployment) |
| `--endpoints` | string | — | Custom comma-separated endpoint paths (all GET, expect 200) |
| `--spec` | string | — | OpenAPI spec filename without `.yaml` (from `docs/openapi/specs/`) |

## Profiles

| Profile | Endpoints | Purpose |
|---------|-----------|---------|
| `smoke` | 3 | Mirrors CI `api.smoke.spec.js` tests 8+9 — the source of truth for both ad-hoc and GitHub Actions |
| `sanity` | 2 | Quick health + stats check |
| `full` | 11 | All major server endpoints |
| `devices` | 2 | Device and model management |
| `campaigns` | 1 | Campaign management |
| `testcases` | 3 | Testcases and requirements |
| `deployment` | 4 | Deployments, executions, alerts |

## Authentication

If the `API_KEY` environment variable is set, every request includes:

```
X-API-Key: <API_KEY>
Authorization: Bearer <API_KEY>
```

This is used for protected `/server/*` routes. The pattern mirrors `_helpers.js:apiHeaders()` used by the Playwright E2E suite.

## Output

- Tests each endpoint and records success/failure with response time
- Reports status codes and calculates success rate percentage
- Writes structured results to the VPT execution context for the report UI

## Related

- `test_scripts/api/run_api_tests.py` — standalone CI runner, no VPT framework needed
- `test_scripts/api/api_profiles.json` — shared endpoint definitions
- `tests/e2e/playwright/specs/api.smoke.spec.js` — Playwright counterpart (tests 8+9 covered by `smoke` profile)
