# CI/CD feature (`features/cicd`)

> Optional feature — see [FEATURES.md](FEATURES.md). Pipeline and runner **operations** live in
> `docs/agent/infra/CICD.md` (internal); this page is the product side.
> Plan and decisions: `docs/tasks/TASK-06-cicd-feature.md` (internal).

White-box and grey-box CI results of every project (virtualpytest, sample-app, …), plus launching CI
runs, as one self-contained feature. Black-box device runs are **not** here: those stay in the
core VirtualPyTest tables and pages.

On by default. Not deployed when `DISABLED_FEATURES` lists `cicd` — set for the customer
overlay, because the pipeline, its runners and its results are ours, not the
customer's.

## The two pages

| Page | Path | What it does |
|---|---|---|
| **Test → Report › CI/CD Reports** | `/test-results/cicd-reports` | Runs table with per-job expansion, stat tiles, time range (24h / 7d / 30d / all), project filter, runner cards. Reads the `cicd` schema, so it shows exactly what the *CI/CD Quality* Grafana dashboard shows. Columns include **Trigger** (push / dispatch / schedule) and **Suite** (white / grey / all). |
| **Test → Execute › Run CI/CD** | `/test-execution/cicd` | Pick project, branch, suite and runner, then launch. Runner rows come from GitHub, so an OFFLINE self-hosted runner is greyed with a restart button, and a suite a runner may not run disables **Run** with the reason. Shows queued/running runs live before any result row exists, plus recent dispatches and a project editor. |

The old Settings path `/configuration/cicd-reports` redirects to the new Reports page.

## Where the data lives

- **Runs and jobs**: schema `cicd` in the shared Postgres database — `ci_runs`, `ci_jobs`,
  view `ci_run_summary` ([`db/001_cicd_schema.sql`](../../features/cicd/db/001_cicd_schema.sql)).
  Read and written through the server's existing Supabase client with `.schema('cicd')`; no
  second connection string. That client authenticates with **`SUPABASE_ANON_KEY`** — the server
  has no service-role key — so the schema grants the app roles write access
  ([`db/003_app_role_writes.sql`](../../features/cicd/db/003_app_role_writes.sql)), exactly as
  `public.script_results` already does. Writes are gated at the API layer, not by the grant:
  `/dispatch` needs a signed-in user, `PUT /projects` needs admin, `/ingest` needs its token.
- **Project registry and dispatch log**: `ci_projects`, `ci_dispatches`, and `ci_runs.trigger` /
  `ci_runs.suite` ([`db/002_ci_projects.sql`](../../features/cicd/db/002_ci_projects.sql)).
  `ci_projects` replaces the old `CI_PROJECT_REPOS` environment mapping and is edited from the
  Run CI/CD page.
- **Report HTML**: still on disk on the reports server under `/opt/ci-reports/<run>/`, served by
  the feature at `/server/cicd/report/<run>/<path>`.
- **Grafana**: dashboard [`grafana/cicd-quality.json`](../../features/cicd/grafana/cicd-quality.json)
  (uid `cicd-quality`) on datasource `cicd-postgres`. Push it with the normal helper, which takes
  any path: `python3 infra/monitoring/grafana/dashboards/_push_dashboard.py features/cicd/grafana/cicd-quality.json`.

## API (`/server/cicd`)

| Route | Auth | Purpose |
|---|---|---|
| `GET /health` | — | What the feature can do: schema reachable, GITHUB_TOKEN present, ingest token set |
| `GET /projects` | — | Registry rows |
| `PUT /projects/<name>` | admin | Edit one registry row |
| `GET /runs?project&since&until&branch&suite&expand=jobs` | — | `ci_run_summary` rows, newest first |
| `GET /runs/<project>/<run>` | — | One run with its jobs |
| `GET /runners?project` | — | Self-hosted runners from GitHub plus the synthetic `github-hosted` row, each with `can_run` |
| `POST /runners/<name>/restart` | — | SSH the runner VM and restart its Actions service |
| `GET /branches?project` | — | Branch names for the picker |
| `POST /dispatch` | signed-in | `{project, branch, suite, runner}` → `workflow_dispatch`, logged in `ci_dispatches` |
| `GET /live?project` | — | Queued/running GitHub runs with job progress, plus recent dispatches |
| `POST /ingest` | bearer `CICD_INGEST_TOKEN` | Run/job upsert for workflow jobs that cannot reach the LAN database |
| `GET /report/<run>/<path>` | — | Serve report HTML from disk |

Reads are open, matching the current `/server/*` baseline; see
[`../../docs/tasks`](../tasks) and the server-auth work for the plan to change that globally.

## Runner choice and why cloud is limited

A dispatch targets either the **self-hosted LAN runner** or **GitHub-hosted** capacity. Which
suites each may run comes from `ci_projects`:

- `runner_labels` — the self-hosted labels the workflow targets. The LAN runner may run
  everything, because grey suites drive a deployed target that only exists on the LAN.
- `cloud_suites` — suites allowed on GitHub-hosted runners. **Seeded to `white` only** for both
  projects.

The cloud restriction is deliberate. Grey suites would have to reach
`virtualpytest.angelstreet.io`, and that hostname sits behind Cloudflare, which blocks requests
from sources it does not like: verified 2026-09-03 that plain `curl` **and** a real headless
Chromium both get HTTP 403 from a laptop, while the same request from the Hetzner host returns
200. The block is by source address, not user agent. Until a GitHub-hosted run is observed
getting through, grey in the cloud is not trusted.

The same caveat applies to how cloud jobs record results: a GitHub-hosted runner cannot reach
the LAN (no SSH to the reports server, no `psql` to Postgres), so it posts rows to
`POST /server/cicd/ingest` over that same public URL. If Cloudflare rejects it, the workflow
emits a `::warning::` and the run simply is not recorded — the tests still ran, and their
artifacts are on the GitHub run. Self-hosted jobs keep using `psql` directly, which is the path
that has always worked.

## Workflow contract

Both repos' workflows declare two `workflow_dispatch` inputs, because the dispatch endpoint
always sends both and GitHub rejects a dispatch carrying an input the workflow does not declare:

| Input | Values | Effect |
|---|---|---|
| `suite` | `all` (default), `white`, `grey` | White jobs run for `all`/`white`, grey jobs for `all`/`grey` |
| `runner` | `self-hosted` (default), `github-hosted` | Cloud-capable jobs switch `runs-on` to `ubuntu-latest`; grey jobs are skipped |

On a push or pull request the inputs are empty, so every gate falls through to "run everything
on the LAN runner" — a push behaves exactly as it did before the feature existed.

One wrinkle worth knowing: a `grey`-only dispatch skips `lint`, and GitHub skips any job that
`needs` a skipped job. The grey jobs therefore gate on
`needs.lint.result == 'success' || needs.lint.result == 'skipped'`, which still refuses to run
after a genuinely failed lint.

## Server environment

| Variable | Needed for |
|---|---|
| `GITHUB_TOKEN` | Runner list, branch list, dispatch, live runs. Currently an `Environment=` line in `vpt-server.service` rather than the server `.env`; moving it into `.env` is safer, since a unit re-render can drop it. |
| `CICD_INGEST_TOKEN` | `POST /ingest`. Without it the endpoint answers 503 and cloud jobs cannot record results. Must match the `CICD_INGEST_TOKEN` secret in both repos. |
| `CI_REPORTS_DIR` | Where report HTML is served from (default `/opt/ci-reports`) |
| `CI_RUNNER_HOSTS`, `CI_RUNNER_USER`, `CI_RUNNER_SSH_KEY`, `CI_RUNNER_SSH_JUMP` | The runner restart button |

Missing configuration never stops the server: the pages show a single
"CI/CD not configured: …" line, built from `GET /health`.

## One core dependency

The core Status page probes `/server/cicd/runners` for its CI runner rows. With the feature
disabled that request 404s and the section stays empty — core does not require the feature. It
is the only place core reaches into it, apart from the bookmark redirect for the old Settings
path.
