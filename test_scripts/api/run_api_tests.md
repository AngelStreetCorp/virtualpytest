# run_api_tests

Standalone API test runner for CI and local use.
No VPT framework dependencies — only requires `requests` and `pyyaml`.
Reads the same `test_scripts/api/api_profiles.json` as `api_test.py`.

## Usage

```bash
python test_scripts/api/run_api_tests.py --profile smoke
python test_scripts/api/run_api_tests.py --profile full
python test_scripts/api/run_api_tests.py --endpoints "/server/system/health,/server/script/list"
python test_scripts/api/run_api_tests.py --spec server-device-management
python test_scripts/api/run_api_tests.py --discover
```

## `--discover` — every GET route the server registers

This is what CI runs. Instead of a hand-written list (the old `full` profile had 11 paths
and never grew), the runner asks the server for its own route table
(`GET /server/api-testing/config`, built from Flask's `url_map`) and hits every GET rule once:

- **static rules** as-is, always with `?team_id=` (most list routes 400 without it);
- **parametrized rules** (`/server/testcase/<testcase_id>`) with ids resolved from the matching
  list endpoint — the `RESOLVERS` table in the script maps each placeholder to a list route and
  id field, one call per placeholder, cached. A placeholder with no resolver, or whose list is
  empty on the target, is reported as **SKIP** with the reason, never as a failure;
- **extra query params** some routes require (`device_model`, `userinterface_name`, …) come from
  the `EXTRA_PARAMS` table, resolved the same way.

Verdict per route is a liveness contract — the exact status/body contracts live in
`tests/backend_server`:

| Response | Verdict |
|---|---|
| 2xx | pass |
| 401 / 403 | pass — the route exists and refused the API key (admin-only routes); role checks are asserted in pytest |
| 404 | fail, unless the rule is in `ALLOW_404` (artifact never generated on that server, e.g. the security dashboard) |
| 400 / other 4xx | fail — a required param is missing: add it to `EXTRA_PARAMS` |
| 5xx / timeout / connection error | fail |

`SKIP_ROUTES` lists rules a plain GET cannot exercise (the auto-proxy catch-all, file proxies,
routes that forward to a host and so measure host availability rather than server health).

A new GET route is covered the next CI run with no change here. If it needs an id or a param
the tables don't know, it shows up as SKIP (unresolved placeholder) or FAIL (400) in the report
with the reason — add one line to `RESOLVERS` / `EXTRA_PARAMS`.

Exit code is 1 only on failures; skips do not fail the job. The HTML report lists skipped rows
in grey with their reason.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--profile` | string | `smoke` | Predefined profile name from `api_profiles.json` |
| `--endpoints` | string | — | Custom comma-separated endpoint paths (all GET, expect 200) |
| `--spec` | string | — | OpenAPI spec filename without `.yaml` (from `docs/api/specs/`) |
| `--discover` | flag | — | Every GET route the server registers (see below). Used by CI |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_URL` | `http://localhost:5109` | Base URL of the backend server |
| `API_KEY` | _(empty)_ | Sent as `X-API-Key` and `Authorization: Bearer` when set |
| `TEAM_ID` | _(empty)_ | Appended as `?team_id=` for endpoints that require it |

## Authentication

When `API_KEY` is set, every request includes:

```
X-API-Key: <API_KEY>
Authorization: Bearer <API_KEY>
```

This is used for protected `/server/*` routes. The pattern mirrors `_helpers.js:apiHeaders()` used by the Playwright E2E suite.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All endpoints returned the expected status |
| `1` | One or more endpoints failed or no config was found |

## CI Usage (GitHub Actions)

The `api-routes` job in `.github/workflows/regression.yml` runs this script automatically on every push to `main` or `debug`:

```yaml
- name: Run API route sweep
  env:
    SERVER_URL: ${{ secrets.E2E_BASE_URL }}
    TEAM_ID: ${{ secrets.TEAM_ID }}
    API_KEY: ${{ secrets.API_KEY }}
  run: python test_scripts/api/run_api_tests.py --discover
```

Uses the same three secrets already defined for the Playwright E2E job — no new secrets required.

## Local Quick-Start

```bash
pip install requests pyyaml
API_KEY=your_key SERVER_URL=https://your-server python test_scripts/api/run_api_tests.py --profile smoke
```

## Related

- `test_scripts/api_test.py` — VPT @script version (runs via the UI script runner)
- `test_scripts/api/api_profiles.json` — shared endpoint definitions
- `tests/e2e/playwright/specs/api.smoke.spec.js` — Playwright counterpart (tests 8+9 covered by `smoke` profile)
- `.github/workflows/regression.yml` — CI workflow that calls this script
