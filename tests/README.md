# Test Structure

Primary strategy doc:
- `tests/docs/testing-strategy.md`

This repository uses layered non-regression tests focused on the product API and user flows.

- `tests/backend_server/`:
  Live HTTP pytest coverage for backend server routes (`/server/*`), including MCP endpoint checks (`/server/mcp*`).
- `tests/frontend/`:
  Frontend component/hook tests with Vitest + RTL.
- `tests/e2e/`:
  Cross-system product tests with Playwright.
- `test_scripts/api/run_api_tests.py`:
  Standalone API profile runner (`smoke`, `full`, etc.).

## Run backend pytest

```bash
SERVER_URL=https://<origin-ip> TEAM_ID=team_123 API_KEY=... \
  pytest tests/backend_server -v

# Optional authenticated MCP initialize check (runs from backend_server suite)
SERVER_URL=https://<origin-ip> TEAM_ID=team_123 API_KEY=... MCP_AUTH_TOKEN=<mcp_bearer_token> \
  pytest tests/backend_server/test_mcp_endpoint.py -v
```

## Run frontend component tests

```bash
cd frontend
npm ci
npm install --no-save vitest@2.1.8 @testing-library/react@16.2.0 @testing-library/jest-dom@6.7.0 jsdom@25.0.1 @vitejs/plugin-react@4.7.0
npx vitest run --config ../tests/frontend/vitest.config.ts
```

## Run Playwright suites

```bash
E2E_BASE_URL=https://<origin-ip> TEAM_ID=team_123 API_KEY=... \
  tests/e2e/playwright/run_e2e_smoke.sh

E2E_BASE_URL=https://<origin-ip> TEAM_ID=team_123 API_KEY=... \
  tests/e2e/playwright/run_e2e_viewport.sh
```

## Run Python API profiles

```bash
SERVER_URL=https://<origin-ip> TEAM_ID=team_123 API_KEY=... \
  python test_scripts/api/run_api_tests.py --profile smoke
```

## Run all layers (or one layer)

```bash
tests/run_all.sh
tests/run_all.sh backend_server
tests/run_all.sh frontend
tests/run_all.sh e2e
```
