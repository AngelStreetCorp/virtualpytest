# BUG-0043 — CI pipeline dead: runner offline for weeks and every report upload silently skipped since July

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0043                                                     |
| Reported  | 2026-09-03                                                   |
| Status    | Fixed (workflow + runner VM); page/backend change pending deploy |
| Severity  | High (no regression signal, CI/CD Reports page frozen on a June run) |
| Area      | `.github/workflows/regression.yml`, runner VM 163, `backend_server/src/routes/server_ci_reports_routes.py`, `frontend/src/pages/CICDReports.tsx` |
| Fixed in  | build 8713                                                   |
| Commit    | `140d5794e`, `da2fff51b`                                     |

---

## Symptom

- Every `Regression Tests` run since 06:55 UTC on 2026-09-03 sat in **queued** for hours; the
  GitHub runner list showed only a dead `ci-runner-node3-v1` (offline).
- The **CI/CD Reports** page showed run **#1775 (branch `debug`, 2026-06-24)** as the newest
  virtualpytest run, and its runner card read `ci-runner-node3-v1 OFFLINE … ssh: connect to host
  192.168.x.100 port 22: No route to host`.
- No `/opt/ci-reports/<run>/` directory had been written for virtualpytest since June.

## Root cause

Four independent defects stacked:

1. **Runner VM 163 had no DNS.** Its static `/etc/network/interfaces` stanza carried no
   `dns-nameservers`, so `resolvconf` wrote an empty `/etc/resolv.conf` after the 2026-08-25
   reboot. `Runner.Listener` retried `pipelinesghubeus24.actions.githubusercontent.com` forever
   (`Could not resolve host`). After weeks without contact GitHub **deleted the registration**
   ("Runner registrations are automatically deleted for runners that have not connected to the
   service recently"), so even after DNS came back the service exited with
   "Failed to create a session… please re-configure".
2. **Every report-upload step was skipped by an invalid condition.** Since `5af5f46d5`
   (2026-07-20) each `Configure CI Reports SSH Key` / `Save …` step carried
   `if: contains(runner.labels, 'self-hosted')`. `runner.labels` is not a GitHub Actions
   context; the expression evaluates to `false` and the steps never ran (they do not even appear
   in the job log). Result directories stopped being written the moment that guard landed.
3. **The repository move dropped every workflow secret.** `AngelStreetCorp/virtualpytest`
   carried no `CI_REPORTS_SSH_KEY`, `E2E_BASE_URL`, `TEAM_ID`, `API_KEY`, … (only the runner
   registration). Even with the guard removed, the first runs after recovery (#139–#141) wrote
   an empty key file (`Load key "…/ci_reports_key": error in libcrypto`, `Permission denied
   (publickey,password)`) and uploaded nothing.
4. **The page pointed at the wrong repository.** `/server/ci-reports/runners` defaulted to
   `angelstreet/virtualpytest` (the pre-move repo, which still lists the dead
   `ci-runner-node3-v1`), and the restart button targeted `192.168.x.100`, an address no VM has.
   The repo moved to `AngelStreetCorp/virtualpytest`, which also restarted run numbering at #1.

## Fix

- VM 163: `dns-nameservers 192.168.x.1` added to `/etc/network/interfaces` and applied with
  `resolvconf -a ens18.inet`; runner re-registered as `ci-runner-v3` on
  `AngelStreetCorp/virtualpytest` (`.runner_migrated` had to be removed too — it alone makes
  `config.sh` refuse with "already configured"); service
  `actions.runner.AngelStreetCorp-virtualpytest.ci-runner-v3.service` installed and started. The
  queue drained immediately. Recipe recorded in `docs/agent/infra/CICD.md`.
- Workflow: the 18 `runner.labels` guards removed (jobs already run on self-hosted only);
  push trigger limited to `main`; `meta.json` now records `repo` and `runner`.
- Backend: `/runners` queries every project's repo (`CI_PROJECT_REPOS`, default virtualpytest →
  `AngelStreetCorp/virtualpytest`, sample-app → `example-org/sample-app`) and tags runners with their
  project; restart resolves the VM per runner name (`CI_RUNNER_HOSTS`, default `ci-runner-v3` →
  192.168.x.163) and restarts the real `actions.runner.*.service` unit.
- Frontend: one runner card per project (runner from the project's latest run, ALIVE / RUNNING /
  OFFLINE from GitHub) and a Grafana-style time range (24h / 7d / 30d / all) on the page.
- Secrets re-created on the moved repository (`TEAM_ID`, `E2E_BASE_URL`, `E2E_AUTO_SIGN_TOKEN`,
  `API_KEY`, `OPENROUTER_API_KEY`, `CI_REPORTS_SSH_KEY` + `CI_REPORTS_KEY` = the runner VM's own
  key, now authorized on the reports server, `CICD_DATABASE_URL`).

## Verification

- `gh api /repos/AngelStreetCorp/virtualpytest/actions/runners` → `ci-runner-v3 online busy=true`
  within a minute of the restart; journal shows `Listening for Jobs` then `Running job: Frontend
  Lint`.
- Run #127 (first after recovery, workflow still carrying the guard) completed lint with **no**
  `Save CI meta` step in its log — the skip confirmed empirically before the guard was removed.
- Run **#142** (dispatched 09:48 UTC with the fixed workflow and the secrets in place):
  `/opt/ci-reports/142/meta.json` = `{"run":142,"repo":"virtualpytest","runner":"ci-runner-v3",
  "branch":"main","sha":"787fffb0f…"}`, `jobs/lint.json` written, and the `cicd` schema holds the
  run row with `runner=ci-runner-v3` and `lint=success` — first stored virtualpytest run since
  #1775 (2026-06-24). sample-app run `sample-app-5` landed the same way from its own workflow.
