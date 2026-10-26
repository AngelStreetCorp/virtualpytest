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

**This feature is a GitLab browser and nothing else.** It reads an instance's projects, files and
README, and links out to GitLab. It does not cut deliveries — no pins, no overlays, no zip, no
tar.gz. Packaging lives in the rollout (see below); do not re-add it here without asking.

Enable with the deny-list: a name in `DISABLED_FEATURES` is not deployed, not registered and not
bundled. With `DISABLED_FEATURES=gitlab` the frontend identifiers do not even reach `dist/`.

## Configuration

Either environment (no UI needed):

```
GITLAB_URL=http://gitlab.internal     # no trailing slash; plain HTTP is supported
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

## Packaging: not here

Building a delivery is a **rollout** concern and lives with the rest of the rollout tooling, next to
`build_customer_bundle.sh` / `deploy_customer.sh` / `delivery_note.sh`:

| Where | What |
|---|---|
| `setup/proxmox/node/lib/customer_bundle.py` | the CLI: `candidates` lists production tags, overlay branches and usable formats; `build` clones the pinned core and the overlay and runs the builder |
| `setup/proxmox/node/build_customer_bundle.sh` | the builder — owns staging, excludes, deny-list, `.env` guards, manifest, size ceiling, delivery note |

It was a panel on this page until it was moved out; `lib/bundler.py` and
`frontend/PackagePanel.tsx` were removed, along with the `/server/gitlab/package/*` routes. The
isolated-checkout behaviour, the askpass token handling and the non-shallow-clone requirement all
carried over unchanged — see the CLI docstring for why the non-shallow rule matters. Full rationale
in `docs/tasks/TASK-91-gitlab-package-and-deploy.md`.

An operator runs it:

```bash
VPT_GITLAB_TOKEN=glpat-… python3 setup/proxmox/node/lib/customer_bundle.py candidates \
    --project group/customer-overlay --gitlab-url http://gitlab.internal
VPT_GITLAB_TOKEN=glpat-… python3 setup/proxmox/node/lib/customer_bundle.py build \
    --core github:main-2026.10.13-63726 --overlay gitlab:group/customer-overlay@main \
    --gitlab-url http://gitlab.internal --format zip
```

Deploying the resulting bundle onto the customer's system stays `update_core.sh` on their side.

## Keeping a customer overlay in GitLab

The customer overlay (`vpt-customer-<codename>`, branch `prod`) lives on GitHub, which is the source of
truth. The instance keeps a read-only copy, `<namespace>/vpt-customer-<codename>` with `prod` as the
default branch, which this page browses. Rules: never commit in GitLab, and no `main` branch on either
side (a leftover test `main` was deleted 2026-10-14).

The instance is only routable from the Proxmox LAN, so sync from a host that can see it, not a laptop.
The token is the one stored by this page's Settings form (`state_path('gitlab_instances.json')`, owned by
the service user, read with `sudo -n`); hand it to git through a 0700 `GIT_ASKPASS` script, never in the
URL or argv.

```bash
git bundle create /tmp/ov.bundle prod && scp /tmp/ov.bundle <lan-host>:/tmp/     # from the overlay clone
git clone -b prod /tmp/ov.bundle /tmp/ov-sync                                    # on <lan-host>
GIT_ASKPASS=<askpass> git -C /tmp/ov-sync push http://<gitlab>/gitlab/<namespace>/vpt-customer-<codename>.git prod
```

Check: `GET /api/v4/projects/<namespace>%2Fvpt-customer-<codename>/repository/branches` lists only `prod`,
at the GitHub commit. Each overlay repo carries the same recipe in its own `GITLAB.md`.

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
python3 -m pytest tests/backend_server/test_gitlab.py -q   # 73 unit tests, no server needed
python3 -m pytest tests/rollout/test_customer_bundle.py -q  # 22 bundler tests, no server needed
```

`scripts/cicd_gitlab_e2e.py` drives a real instance end to end (tunnel it if the GitLab is not on
your network):

```bash
GITLAB_URL=http://127.0.0.1:8183 GITLAB_TOKEN=glpat-… python3 scripts/cicd_gitlab_e2e.py
```

## Still open

Recorded in `docs/tasks/TASK-91-gitlab-package-and-deploy.md`:

- **Pushing the artefact into GitLab** as a generic package or release, rather than only writing
  it to a local directory, for a customer who cannot reach the machine that ran the build.

**Goal B — serving the core from the customer's own GitLab — is answered and is not a change.** GitHub
and GitLab are deliberately separate sources: GitHub is our public repo and needs internet access,
GitLab is the customer's own and is what an air-gapped install has. `VPT_CORE_REMOTE` already takes
any git remote, so pointing the core at a GitLab mirror is configuration, not a code path. The
firewall is a rollout concern; the operator pushes the `vpt-*` files into the customer's GitLab by
hand, and VirtualPyTest never pushes a bundle back.

## How to disable

`DISABLED_FEATURES=gitlab` in `customer.conf` (or `--disabled-features` on `deploy_customer.sh`).
The route is also listed in `tests/e2e/playwright/specs/ui.pages.spec.js` and in
`docs/agent/validation/TESTING.md`, so the all-pages run covers it.