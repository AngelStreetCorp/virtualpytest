# BUG-0504 — The image pipeline published nothing for 16 days: a bind-mount check gated the bundle

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0504                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | CI/CD                                                        |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The workflow `Release artifacts` (`.github/workflows/release-images.yml`) had not published a
container image since tag `main-2026.09.27-9394` — 16 days of releases with no GHCR image for
`virtualpytest-server`, `virtualpytest-host`, `virtualpytest-frontend`, `minio` or `minio-mc`.

Every run of the `Standalone bundle stands alone` job failed at the step `Every mount resolves
inside the bundle`, e.g. runs
[38378186932](https://github.com/AngelStreetCorp/virtualpytest/actions/runs/38378186932) (tag
`main-2026.10.13-63726`) and `main-2026.10.13-63725`, with:

```
22 bind mounts resolved inside the bundle
##[error]frontend mounts /tmp/tmp.XXXX/vpt-docker-main-2026.10.13-63726/frontend/public/docs
##[error]grafana mounts /dev/null (outside the bundle)
```

Because `build` has `needs: bundle`-equivalent ordering through the job graph and `verify` has
`needs: build`, the failure skipped both. The run's job conclusions were exactly:

```
Standalone bundle stands alone      :: failure
Build ${{ matrix.image }}           :: skipped
Published images bring the stack up :: skipped
```

The bundle ships *after* the image jobs are gated on it in practice, so a bundle integrity check
— whose job is to catch a forgotten path — had become a total block on image publishing. The
images are published by hand (`workflow_dispatch` only, per the header comment), so nothing
noticed until someone went looking for the tag.

## Root cause

Two independent regressions, each an incomplete bookkeeping of a bind mount declared in
`setup/docker/docker-compose.yml`. Neither is in the bundle script's own copy list, and the
bundle check is what surfaced them.

1. **`frontend/public/docs` is mounted but was never bundled.** Commit `4960fb00f` (2026-09-26,
   *"fix(compose): wire backend_server test_scripts, fix MinIO endpoint, HTTPS noVNC, docs mount"*)
   added `../../frontend/public/docs:/app/dist/docs:ro` to the `frontend` service — the
   documentation tree the web app serves at `/docs`. `setup/docker/make_bundle.sh` copies
   `setup/db`, the Grafana dashboards, `backend_host/src/.env.example`, `test_scripts` and
   `test_campaign`, but never `frontend/public/docs`. In the extracted bundle the source path
   does not exist at all, so the check's `os.path.exists(src)` reported it missing.

2. **`/dev/null` is mounted and the `/dev` carve-out did not cover it.** Commit `67e47e25f`
   (2026-10-05, *"feat(atlas): dashboard variables always work (allValue sentinel), template
   hidden from docker provisioning"*) added
   `/dev/null:/var/lib/grafana/dashboards/template.json:ro` so Grafana's file provisioning skips
   the Atlas dashboard *template* (it is not a dashboard, so loading it breaks the variable
   machinery). The check exempted exactly `src == '/dev'` — written for the `/dev:/dev`
   passthrough in `docker-compose.linux.yml` — so `/dev/null` fell through to
   `src.startswith(bundle)` and was reported as outside the bundle.

## Fix

- `setup/docker/make_bundle.sh` now copies `frontend/public/docs` into the bundle, creating
  `$ROOT/frontend/public` first, and the layout comment at the top of the script lists it.
  This is the "include the path" fix: the mount stays, because a user running the bundle must
  get the docs the frontend image serves. The tree is 17 MB raw / ~4.9 MB gzipped, so the
  archive grows from 0.9 MB to 6.0 MB (487 → 768 files) — still ~50× smaller than the 330 MB
  clone the bundle exists to avoid. The `~0.5 MB` claim in the workflow header was corrected to
  `~6 MB` rather than left stale.
- `.github/workflows/release-images.yml`: the host-hardware carve-out became
  `src == '/dev' or src.startswith('/dev/')`, so `/dev/null` is exempt alongside `/dev`.

The assertion itself is otherwise untouched: the `os.path.exists(src)` and
`src.startswith(bundle)` branches, the `type: bind` filter and the exit code are byte-identical.
`/dev/null` is a character device and can never be shipped inside an archive, and it already
carried the check's own justification ("host hardware, correctly outside the bundle") — so
completing that exemption is the category the carve-out was already expressing, not a
relaxation of what the bundle must contain. The alternative, dropping the `/dev/null` mount,
would have regressed `67e47e25f`.

## Verification

Rebuilt the bundle with the patched script, extracted it outside any repo checkout, seeded
`.env` from `.env.example` (`sed 's/CHANGE_ME/citestvalue/g'`) and `backend_host/src/.env`, then
ran the step's `docker compose -f docker-compose.yml -f docker-compose.linux.yml config` plus
the Python assertion verbatim:

```
23 bind mounts resolved inside the bundle
CHECK EXIT=0
```

(22 before the fix, plus the `frontend` mount that now resolves; the `/dev/null` mount is the
carve-out.) Two negative controls confirm the assertion still bites after the change:

- deleting `frontend/public/docs` from a freshly built bundle → `22 bind mounts resolved …` and
  `::error::frontend mounts …/frontend/public/docs`, exit `1`;
- passing a bundle root that is not the extraction root → `0 bind mounts resolved …`, 23
  offenders, exit `1`.

Both branches therefore still fail the step on a genuinely absent or out-of-bundle path.

## Not verified here

The GitHub Actions run itself. Reproduced locally against the same `docker compose config`
output the runner produces; the pushed run is what confirms it end to end.