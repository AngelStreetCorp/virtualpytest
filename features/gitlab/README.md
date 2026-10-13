# gitlab

GitLab orchestration for a **self-hosted GitLab**. Separate from `cicd` on purpose: `cicd`
collects GitHub Actions results and carries the CI reports page, the Grafana dashboard and the
`cicd` schema — none of which a customer running its own GitLab needs. This feature is the
GitLab side only, so it is enabled (or left off) independently of `cicd`.

## Parts

| Part | What it holds |
|---|---|
| `lib/gitlab_api.py` | REST API v4 client: instance/identity, projects, repository (tree/README/file), pipelines, jobs, trigger, runners |
| `lib/instances.py` | configured instances in `state_path('gitlab_instances.json')`, outside the deploy tree |
| `backend_server/__init__.py` | `/server/gitlab/*` routes, `register(app)` |
| `frontend/routes.tsx` | nav item + `/monitoring/gitlab` |
| `frontend/GitLabPage.tsx` | health strip, project picker, file tree + README, link out to GitLab |
| `frontend/gitlabApi.ts` | typed calls to the routes above |

Enable with the deny-list: a name in `DISABLED_FEATURES` is not deployed, not registered and not
bundled. With `DISABLED_FEATURES=gitlab` the frontend identifiers do not even reach `dist/`.

## Configuration

Either environment (no UI needed):

```
GITLAB_URL=http://10.10.41.52     # no trailing slash; plain HTTP is supported
GITLAB_TOKEN=glpat-…              # PAT with the `api` scope
GITLAB_CA_BUNDLE=/path/ca.crt     # when the instance is https behind an internal CA
GITLAB_INSECURE=1                 # last resort, skips TLS verification
```

or the page's Settings form, which writes the same pair to `gitlab_instances.json` and proves it
with `GET /api/v4/version` before saving. An operator who cannot use PATs should get the CA
bundle rather than `GITLAB_INSECURE`.

## Permissions

`plugins.gitlab:view` for reads, `plugins.gitlab:manage` for configuring an instance or changing
the selected project — the same shape as `plugins.jira:view/:manage` in the core integrations
routes. Triggering a pipeline additionally needs a signed-in user: it is a side effect on the
customer's CI.

## GitLab CE 19.4 constraints (verified live on 19.4.2, 2026-10-13)

These are not guesses — each was hit while driving a real instance, and each is pinned by a test
in `tests/backend_server/test_gitlab.py`:

1. Branches live at `/projects/:id/repository/branches`. GitHub's shape answers Workhorse's bare
   `{"error": "404 Not Found"}`, which is not even a GitLab error body.
2. The trigger endpoint takes `inputs[]`, not `variables[]` — 19.4 rejects variables outright.
3. CE 19.4 cannot pass pipeline inputs at all: the linter rejects a top-level `spec:` (read as a
   job) and a job-level `spec:` (unknown key). **A bare `ref` is the only usable form** — a
   parameter has to ride in the ref, a branch, a committed file or a project-level CI/CD variable.
4. Runner liveness is `status`/`online`, never `contacted_at`, which 19.4 does not return for
   instance runners. Keying off it marks every runner offline.
5. Project names reject parentheses.

Also worth knowing before an install: the documented `script.deb.sh` helper 404s (wire the apt
repo against `https://packages.gitlab.com/gpg.key` by hand), `gitlab-runner` ships from a separate
repo, and a fresh instance has no root namespace until it is seeded.

## Tests

```bash
python3 -m pytest tests/backend_server/test_gitlab.py -q     # 60 unit tests, no server needed
```

`scripts/cicd_gitlab_e2e.py` drives a real instance end to end (tunnel it if the GitLab is not on
your network):

```bash
GITLAB_URL=http://127.0.0.1:8183 GITLAB_TOKEN=glpat-… python3 scripts/cicd_gitlab_e2e.py
```

## Not built yet: packaging and deploying from the page

Reading and triggering is what this feature does today. The two goals that make it a customer
product — package a release from the page (PIN + overlay tag -> zip -> `update_core`), and package
straight from the linked repo — are specified in `docs/tasks/TASK-91-gitlab-package-and-deploy.md`.
The shell tooling (`build_customer_bundle.sh`, `deploy_customer.sh --stage-only`) already exists and
must be called, not reimplemented.

## How to disable

`DISABLED_FEATURES=gitlab` in `customer.conf` (or `--disabled-features` on `deploy_customer.sh`).
The route is also listed in `tests/e2e/playwright/specs/ui.pages.spec.js` and in
`docs/agent/validation/TESTING.md`, so the all-pages run covers it.