# VirtualPyTest Testing Strategy

## Scope

Testing focuses on externally exposed product surfaces:

- `backend_server` API (`/server/*`)
- MCP endpoint checks via the same API surface (`/server/mcp*`)
- frontend component/hook behavior
- end-to-end user flows (Playwright)

`backend_host` is not part of CI test scope because it is not directly exposed in the current deployment model.

## Test Layers

| Layer | Location | Purpose |
|---|---|---|
| Backend server API | `tests/backend_server/` | Validate server routes and response contracts, including MCP endpoint health/auth/protocol checks |
| Frontend components | `tests/frontend/` | Fast feedback on React page/hook behavior |
| E2E | `tests/e2e/playwright/` | Validate critical product flows in browser |
| API smoke runner | `test_scripts/api/run_api_tests.py` | Lightweight profile-based HTTP smoke checks |

## CI Pipeline

Workflow: `.github/workflows/regression.yml`

Jobs:

1. `lint`
2. `backend-server-tests`
3. `frontend-component-tests`
4. `e2e-smoke`
5. `e2e-pages`
6. `e2e-viewport`
7. `web-script-local-debug`
8. `api-routes`

(No separate `deploy-report` job exists in the workflow — each job writes its own report and uploads it to the CI reports server.)

## Environment/Secrets

| Name | Used by |
|---|---|
| `E2E_BASE_URL` | backend-server-tests, e2e-smoke, e2e-viewport, api-routes |
| `E2E_AUTO_SIGN_TOKEN` | e2e-smoke, e2e-viewport (token-only auth bypass for browser/API E2E calls) |
| `TEAM_ID` | backend-server-tests, e2e-smoke, e2e-viewport, api-routes |
| `API_KEY` | backend-server-tests, e2e-smoke, e2e-viewport, api-routes |
| `MCP_AUTH_TOKEN` | optional authenticated MCP initialize check in backend server suite |

## Coverage Priorities

1. Keep server route checks stable in `tests/backend_server/`.
2. Keep MCP endpoint health/auth guard stable in `tests/backend_server/test_mcp_endpoint.py`.
3. Expand frontend hooks/pages for high-change areas.
4. Keep E2E focused on critical cross-page flows and viewport regressions.

## Non-Goals

- No direct `backend_host` CI suite.
- No external host-route assumptions in tests.

## What CI Does Not Run, And How That Is Expressed

**A test that can never run is not coverage — and a permanently "skipped" row is worse than no
row, because it reads like coverage in a report.** An audit on 2026-09-16 found 73 skipped of 652
in `backend-server-tests`, of which **40 were empty stubs**: a function whose whole body was
`pytest.skip("…")` or `pass`, asserting nothing, existing only to document that a surface is
deliberately untested. `test_restart.py` was 11 of those and nothing else. They were deleted; the
knowledge they carried is this section.

Surfaces deliberately not exercised on every push, and why:

| Surface | Why not |
|---|---|
| `/server/restart/*` (all of it) | every endpoint kicks off real video generation / AI audio analysis on a live host, 5–10 min timeouts |
| Device execution: `actions/executeBatch`, `control/take|release|takeover`, campaign execute, `remote` state changes, `desktop` bash/pyautogui, `power` | drives a real, shared device — takeover explicitly preempts whoever is using it |
| AI/agent happy paths: `ai/*`, `agent/*`, `agent_runtime/*`, `agent_benchmark`, `mcp_proxy` execute | spends provider credits, or spawns background agents on a shared deployment |
| `ai-queue/clear`, `ai/resetCache` | destructive against shared Redis/DB state |
| `api-testing/run` and `/quick` | a test runner that fires HTTP at other live endpoints as a side effect |
| `cicd/dispatch`, `cicd/restartRunner` | fires a real workflow_dispatch / SSHes into a runner VM |
| `settings` .env writes | mutates the live server's own config, leaves `.backup.<ts>` files with no delete endpoint |
| Third-party success paths: JIRA, Slack, Postman, `public/ask` | real external API calls (and, for Slack, a visible message in a real channel) |

One marker, registered in `tests/backend_server/conftest.py`, expresses what a permanent
`pytest.mark.skip` used to:

- **`manual`** — real external side effect (credits, Slack, a restarted service, a driven device).
  Run on purpose: `pytest tests/backend_server -m manual`.

CI deselects it (`-m "not manual"`), so those tests are **absent** from the report rather than
listed as skipped — and unlike a `skip`, they still run where they are meaningful.

**`local_only` was removed on 2026-09-16.** It covered `/api/events`, `/navigate` and `/docs/api`,
which had no nginx location block and fell through to the frontend SPA. That was never a property
of the tests: those three blueprints were mounted outside `/server/*`, the only prefix nginx
proxies, so they were dead on the public deployment — an alert POST to the events API got a 200
and a page of HTML and read it as success. The marker was hiding a platform defect. The blueprints
moved to `/server/events`, `/server/frontend` and `/server/docs/api`; their 12 tests now run
everywhere, and the routes are covered by the JWT guard for the first time.

The general rule: before marking a test unrunnable, establish that the thing it cannot reach is
*meant* to be unreachable. If the platform should expose it, the marker is the wrong fix.

A skip that remains is expected to be *conditional on something that is true in CI*: a missing
role JWT, an unregistered host. If a skip fires on every run forever, it is one of three things —
delete the stub, mark it `manual`, or fix what makes it unrunnable. Two of the 2026-09-16
skips turned out to be the third case: `test_permissions` read its host list from
`/server/server-manager/hosts`, which is not a route (it falls into the auto_proxy catch-all and
answers 400), so every host-dependent permission test skipped itself on a server with five hosts
registered; and `test_get_all_campaign_results_returns_expected_shape` was still marked `xfail` for
a bug that had since been fixed, so it reported XPassed and asserted nothing.

## Delivery Policy: Ship Tests With The Feature

**A feature or route is not "done" until it has non-regression coverage.** This is a hard rule, not a suggestion, effective 2026-09-06.

Rationale: an audit on 2026-09-06 found ~55 of 69 `backend_server` route modules (including the entire navigation/pathfinding engine — the product's core value proposition) and ~46 of 51 frontend pages had zero test coverage. Sampling 8 recent feature commits showed none touched `tests/`. The gap was systemic, not incidental — it happened because nothing enforced the connection between shipping code and shipping tests.

Rule of thumb, applied at PR/review time:

| Change | Minimum required test |
|---|---|
| New or changed `backend_server` route (`routes/*.py`) | A `tests/backend_server/test_<domain>.py` case per new endpoint (happy path + one failure mode: auth, validation, or not-found) |
| New or changed frontend page (`pages/*.tsx`) | A `tests/frontend/<Page>.test.tsx` render test, or an assertion added to `ui.smoke.spec.js` if the page is user-critical |
| New navigation/pathfinding behavior | Both a `tests/backend_server` API-contract test AND an e2e/manual check — this is the highest-risk area in the product |
| Bugfix | A regression test that fails before the fix and passes after |

A PR that adds product surface (a route, a page, a user-facing flow) without a corresponding test change should be treated the same as a PR that fails lint — send it back, don't wave it through, unless there is a documented reason skipping tests is fine (e.g. pure refactor with unchanged behavior and existing coverage).

## Duration Policy: Unit Fast, Integration Bounded, Black-Box Capped

**Unit and integration tests must stay fast. Only true black-box (E2E / real-hardware) tests are allowed to run long — and even those need a hard ceiling.** A slow "unit" test is a bug in the test, not a fact of life (it usually means a network call or real timer slipped in where a mock belongs).

An audit on 2026-09-06 found none of this was actually enforced: `regression.yml` had **zero `timeout-minutes` on any job** (falls back to GitHub Actions' 6-hour platform default), the backend pytest suite had no per-test timeout beyond a single HTTP call's 20s, and `continue-on-error: true` on every test step meant a hang wouldn't even fail loudly. `timeout-minutes` and `pytest-timeout` were added to close the CI half of this gap; `continue-on-error` was left as a separate, deliberate decision (see CI Pipeline notes) — a timeout stops a hang, it does not change pass/fail semantics.

| Test type | Per-test cap | Suite/job cap | Enforcement |
|---|---|---|---|
| Unit (Vitest, `tests/frontend/`) | 10s (`testTimeout` in `vitest.config.ts`) | 15 min (`frontend-component-tests` job) | `timeout-minutes` + Vitest `testTimeout` |
| Integration (pytest, `tests/backend_server/`, live HTTP) | 30s (`--timeout=30`) | 20 min (`backend-server-tests` job) | `pytest-timeout` + `timeout-minutes` |
| Black-box/E2E (Playwright, `tests/e2e/playwright/`) | 45s/test, 12s/assertion (`playwright.config.js`) | 30 min (`e2e-smoke`, `e2e-pages`, `e2e-viewport` jobs) | Playwright's own `timeout`/`expect.timeout` + `timeout-minutes` |
| Real-hardware Campaign (device execution, not CI) | not set | not set | **open gap — no ceiling exists today.** Needs a number derived from real `campaign_results`/Grafana data (see `docs/agent/infra/GRAFANA.md`), not a guess. Until then, treat any campaign running past a few hours as something to investigate, not something normal. |

Rule of thumb when writing a new test: if it's calling `vi.mock`-everything and rendering a component, it's a unit test — it should finish in well under a second. If it's making a real HTTP call to a live server, it's integration — bounded by `request_timeout` (20s/call), budget ~1s typical. If it's driving a real browser or real hardware end-to-end, it's black-box — that's the only category where seconds-to-minutes per test is expected, and it's exactly the category that needs an explicit cap so a stuck device or hung page doesn't silently eat a CI runner (or a lab device) for hours.
