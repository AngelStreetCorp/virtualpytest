# CI: the regression workflow

`.github/workflows/regression.yml` runs on every push to `main` and every pull request
against `main`; it can also be started by hand (*Actions → Regression Tests → Run workflow*)
with two inputs: `suite` (`all` / `white` / `grey`) and `runner` (`self-hosted` / `github-hosted`).

| Job | Runs on | What it proves |
|---|---|---|
| **Docker stack builds and starts** (`docker-build`) | GitHub-hosted | `./setup/docker/launch.sh` exactly as a user runs it, then the server, UI, host, Supabase and Grafana answer |
| **Docs reference existing paths** (`docs-paths`) | GitHub-hosted | every repo path an onboarding doc names exists (`scripts/docs/check_paths.sh`) |
| **Frontend Lint** (`lint`) | either | ESLint on `frontend/` |
| **Frontend Typecheck** (`typecheck`) | either | `tsc` on `frontend/` |
| **Backend Server Unit Tests** (`backend-server-tests`) | self-hosted | `tests/backend_server` against a deployed server, every HTTP call logged in the report |
| **Frontend Component Tests** (`frontend-component-tests`) | either | Vitest component suite |
| **E2E Smoke Tests** | self-hosted | Playwright: login, main pages reachable |
| **E2E All Pages (Screenshot + Error Check)** | self-hosted | every page renders without console errors |
| **E2E Viewport Tests** | self-hosted | layout at phone / tablet / desktop widths |
| **Web Script Local Debug (Python Playwright)** (`web-script-local-debug`) | self-hosted | a real `web/…` test script runs end to end on the runner's own browser |
| **API Route Sweep (Python)** (`api-routes`) | self-hosted | `run_api_tests.py --discover` calls every GET route the server registers — with a real id where one exists, a synthetic one otherwise |

`white` = the first six (code checks, no devices); `grey` = the browser and script jobs, which
need the LAN runners and a running platform. Self-hosted jobs are skipped when `runner` is
`github-hosted`.

Reports are copied to the CI reports host and indexed in the `cicd` database; they appear in
the web UI under *Configuration → CI/CD Reports* (the `cicd` feature). A newer commit cancels
the in-flight run of an older one on the same branch.

Running the backend suite locally against a deployed server, and the runner fleet itself, are
described in the internal docs (`docs/agent/`).
