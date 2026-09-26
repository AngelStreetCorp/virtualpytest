# Publishing container images to GHCR

Five containers are published to GitHub Container Registry at `ghcr.io/angelstreetcorp`: the three VirtualPyTest ones — `virtualpytest-server`, `virtualpytest-host`, `virtualpytest-frontend` — plus `minio` and `minio-mc`, which vendor the upstream MinIO binaries (registries that used to serve them stopped allowing anonymous pulls; see `gcp-standalone.md` § "The MinIO workaround"). A `launch.sh` install can pull all five instead of building from a local checkout, which makes first-run installs ~2 minutes instead of ~15. This page is the lifecycle for the *publishing* side: when to publish, how to publish, how to verify a published tag works, and how to roll back if it doesn't.

> If you only want to **use** the published images (i.e. you're running a fresh install), you don't need this page. See [docker.md](docker.md) § "Skip the build (prebuilt images)" for `VPT_IMAGE_TAG=…` in `setup/docker/.env`. The rest of this page is for project contributors cutting a publish.

## What's published

| Image | Source | Tag prefix | Built from | Default port inside |
|---|---|---|---|---|
| `ghcr.io/angelstreetcorp/virtualpytest-server` | `backend_server/Dockerfile` | `<tag>` + `latest` | public snapshot of `main` (or a `release-*` tag) | `5109` |
| `ghcr.io/angelstreetcorp/virtualpytest-host` | `backend_host/Dockerfile` | same | same | `6109` |
| `ghcr.io/angelstreetcorp/virtualpytest-frontend` | `frontend/Dockerfile` (context `frontend/`) | same | same | `5073` |
| `ghcr.io/angelstreetcorp/minio` | `setup/docker/images/minio/Dockerfile` | same | vendors an upstream MinIO release binary from GitHub (not our source) | `9000` (console `9001`) |
| `ghcr.io/angelstreetcorp/minio-mc` | `setup/docker/images/minio-mc/Dockerfile` | same | same, upstream `mc` binary | n/a (one-shot bucket-init container) |

- **Registry:** `ghcr.io/angelstreetcorp` (one org for all five; `angelstreetcorp/*` packages are private by default, so installs need `docker login ghcr.io` once).
- **Tag format:** `<branch>-<YYYY.MM.DD>-<build>` where `<branch>` is `main` for the `main` branch or `release-YYYY.MM.DD` for a customer release. The full tag is what's currently in `VERSION.txt` (`current:<tag>` line) at build time. Build numbers are monotonic project-wide — every push to `main` increments by one regardless of which image.
- **`latest`** is always repointed to the most recently published tag. **It is not** "the newest release of VirtualPyTest" — it is "the last image the project chose to publish", which may be weeks behind `main`. Pin a real tag (`VPT_IMAGE_TAG=main-2026.09.26-9358`) when you want reproducibility.
- **`minio` / `minio-mc` exist because quay.io/minio/\* stopped accepting anonymous pulls** (see `gcp-standalone.md` § "The MinIO workaround"). They tag and version identically to the other three for simplicity, even though their actual content only changes when the pinned upstream MinIO/mc version is bumped in their Dockerfile.

## What runs the publish

`.github/workflows/release-images.yml` has two jobs that matter:

- **`build`** — builds all five Docker images, then **only pushes to GHCR if the workflow runs on the public repo** (`AngelStreetCorp/virtualpytest`). On the internal repo (`virtualpytest-internal`), the build runs and the images are discarded — see the long comment near the top of the workflow for why (the leak gate cannot see what's inside an image, so the three VPT-source images must only be built from the public snapshot; `minio`/`minio-mc` ride the same gate for simplicity, though they embed no VPT source).
- **`verify`** — `launch.sh`-es the published images on a fresh runner, then asserts `docker inspect --format '{{.Config.Image}}' vpt-server` is literally `ghcr.io/angelstreetcorp/virtualpytest-server:<tag>` (so a passing run really pulled from the registry, not a `local` build that snuck through `launch.sh`'s fallback). It then curls `/server/health`, `/host/system/health`, the Supabase REST endpoint, and Grafana. This is the actual end-to-end test of "does the published image work".

Both jobs are **`workflow_dispatch` only**. Nothing fires on a tag push — see the comment at the top of the workflow for the reasoning (no consumer actually depends on registry images, the first install builds locally anyway, and ~3 GB × 3 images per tag would dominate CI minutes).

## When to publish

Publish when one of these is true. For everything else, don't — `launch.sh` with `VPT_IMAGE_TAG=local` already gives the user a working stack, and registry images only matter for first-run speed and reproducible installs.

- **You want a fresh first-run for users** (the current `latest` is months old). Publish.
- **You tagged a customer release** (`release-*`). Publish, then point the public docs at that tag.
- **You need a published image for a specific environment** (e.g. a Raspberry Pi image is being built off the same Dockerfile elsewhere and needs to match). Publish that tag.
- **You bumped a dependency that `local` builds don't include** (e.g. base Python from 3.11 to 3.12, base Node from 18 to 20). Publish so existing installs don't keep getting stale.
- **Otherwise:** don't. `local` builds match the user's checkout exactly, which is the more honest thing for the 99% case.

## How to publish

The repo you're working in matters. Pick the right one before you trigger anything.

### Step 1 — Decide which repo to publish from

| Repo | What happens on `workflow_dispatch` |
|---|---|
| `AngelStreetCorp/virtualpytest` (public) | Builds + pushes all five images to GHCR + runs the `verify` job. **This is the publish path.** |
| `AngelStreetCorp/virtualpytest-internal` (private) | Builds all five images and throws them away (the workflow's `push: ${{ steps.meta.outputs.push == 'true' }}` check is `false`). Useful for "did my Dockerfile change break anything?" — the build itself is the test. Not a publish. |

If you're working on the internal repo (which is normal — it's where development happens), you must mirror to the public repo before publishing. The project's `scripts/release/publish_public.sh` script does this — it takes the release tag you're publishing and pushes directly to the public repo (default target `git@github.com:AngelStreetCorp/virtualpytest.git`), no local sibling checkout needed:

```bash
# from inside the virtualpytest-internal checkout, HEAD == the tag being published
scripts/release/publish_public.sh main-2026.09.26-9361
```

See `RELEASING.md` § "Publish a snapshot to the public repo" for the full cut-a-release sequence (tag first, `--dry-run` to inspect, then run for real). After that, all pushes to `main` on the internal repo *don't* publish images, but a fresh run on the public repo's Actions will pick up the latest `main`.

### Step 2 — Decide the tag

Two options:

| Tag source | When | How to set |
|---|---|---|
| `github.ref_name` (a real Git ref) | You're publishing from a tagged commit (`main-*` or `release-*`). | The workflow reads it automatically. |
| `inputs.tag` (manual) | You're publishing from `main` HEAD or a specific commit. | Type it into the workflow_dispatch input box — e.g. `main-2026.09.26-9358` to match `VERSION.txt`. |

The tag you publish must match what's in `VERSION.txt` at the commit you publish from, otherwise `docker inspect` will show a version mismatch in the deployed container (the version is baked at build time). The `verify` job does not assert this — it only asserts the image came from the registry. Add a manual eyeball check before publishing.

### Step 3 — Trigger the workflow

On the **public** repo:

1. **GitHub → Actions → Release artifacts → Run workflow**.
2. **Branch:** `main` (or `release-*` if you're cutting one).
3. **Image tag to build (and to publish, on the public repo only):** type the tag (e.g. `main-2026.09.26-9358`).
4. Click **Run workflow**.

The build matrix pushes five images in parallel; expect ~10–15 minutes for the host image (the slowest because of `apt-get` dependencies), ~5 minutes each for the server and frontend, and well under a minute each for `minio`/`minio-mc` (alpine base + one `curl`). The `verify` job then runs on the same runner, taking another ~10 minutes.

### Step 4 — Watch the verify job

`verify` is the test. Watch its logs for these signals:

| Line | Means |
|---|---|
| `SUMMARY: Environment is healthy. cloudflared will use 'quic' as primary protocol.` | Backend started; nothing else interesting. |
| `200  http://localhost:5109/server/health` | Backend API answers. |
| `frontend 200` | Frontend answers. |
| `200  http://localhost:6109/host/system/health` | Host controller answers. |
| `supabase rest 200` | Database reachable. |
| `grafana 200` | Grafana reachable. |

If any of those are not 200, scroll up to the first non-green line — that's where the issue is (most often: a missing env var on the published image, a wrong default port, or a schema migration that didn't run).

The job also asserts:

```
vpt-server:     ghcr.io/angelstreetcorp/virtualpytest-server:<tag>
vpt-host:       ghcr.io/angelstreetcorp/virtualpytest-host:<tag>
vpt-minio:      ghcr.io/angelstreetcorp/minio:<tag>
vpt-minio-init: ghcr.io/angelstreetcorp/minio-mc:<tag>
```

If either line reports a `local` or a different image, the pull failed and `launch.sh` fell back to building — that's the silent failure mode that the assertion exists to catch. If the assertion fails, the publish is not "real" yet; investigate the pull error before announcing the publish.

## How to test a published tag locally

If you want to smoke-test a publish without going through GitHub Actions:

```bash
# 1. Login once
echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GH_USER" --password-stdin

# 2. Pull the three images for the tag you want to test
TAG="main-2026.09.26-9358"
for img in virtualpytest-server virtualpytest-host virtualpytest-frontend; do
  docker pull "ghcr.io/angelstreetcorp/$img:$TAG"
done

# 3. Sanity-check the version baked into each image
for img in virtualpytest-server virtualpytest-host virtualpytest-frontend; do
  docker run --rm "ghcr.io/angelstreetcorp/$img:$TAG" cat /app/VERSION.txt 2>/dev/null \
    || docker run --rm --entrypoint cat "ghcr.io/angelstreetcorp/$img:$TAG" VERSION.txt 2>/dev/null
done
# expect: each prints "current:main-2026.09.26-9358"
# (server uses /app/VERSION.txt; frontend's context is frontend/ so it's at the image root)

# 4. Run the same launch.sh a real user would, with VPT_IMAGE_TAG pinned to the test tag
sed "s/^VPT_IMAGE_TAG=local/VPT_IMAGE_TAG=$TAG/" setup/docker/.env.example > setup/docker/.env
./setup/docker/launch.sh

# 5. After it starts, assert each service is the published image, not a local build
for svc in vpt-server vpt-host vpt-minio vpt-minio-init; do
  docker inspect --format '{{.Config.Image}}' "$svc"
done
# expect each to show the matching ghcr.io/angelstreetcorp/<image>:$TAG
```

Step 5 is the assertion the CI `verify` job does. If it ever shows something else, the publish is broken even if the rest of the smoke test passes.

## How a user consumes a published image

Already covered in [docker.md § "Skip the build (prebuilt images)"](docker.md#skip-the-build-prebuilt-images). Quick recap so this page stands alone:

```bash
# Before ./setup/docker/launch.sh, edit setup/docker/.env:
VPT_IMAGE_TAG=main-2026.09.26-9358    # a specific tag
VPT_IMAGE_TAG=latest                  # the most recently published one
VPT_IMAGE_TAG=local                   # default — build from this checkout (skip the registry)
```

`launch.sh` reads that file, points every compose service at `ghcr.io/angelstreetcorp/<svc>:<tag>`, and falls back to a local build only if the pull fails. So `local` is always the safety net, even when `VPT_IMAGE_TAG` is set — useful when a tag was never published and you don't want the install to fail.

## Rolling back

If a publish turns out to be broken (the `verify` job fails after the fact, or a user reports a regression), two routes:

| Action | When | How |
|---|---|---|
| Point users at the previous tag | The current `latest` is broken; the previous one works. | Edit any docs that say `VPT_IMAGE_TAG=latest` to pin a known-good tag, or do a fresh publish (see below) and have users re-pin. |
| Re-publish a fixed image | You found and fixed the bug, want `latest` updated. | Same as Step 3 above, with a new tag (e.g. `main-2026.09.26-9400` after the fix commit). The `latest` pointer moves with it. |
| Pull `latest` back to the previous good tag | You don't have time to fix; you need a fast unblock. | `docker pull ghcr.io/angelstreetcorp/<img>:<old-tag>` then `docker tag ghcr.io/angelstreetcorp/<img>:<old-tag> ghcr.io/angelstreetcorp/<img>:latest` then `docker push ghcr.io/angelstreetcorp/<img>:latest`. Yes, you can overwrite `latest`; GHCR doesn't lock tags. |

`launch.sh` has a fallback to `local` build, so any user can also unblock themselves by setting `VPT_IMAGE_TAG=local` — they just wait the extra 10 minutes.

## Version conventions cheat sheet

```
VERSION.txt format:                current:<branch>-<YYYY.MM.DD>-<build>
                                   previous:<branch>-<YYYY.MM.DD>-<build>-<short-sha>

container image tag:               ghcr.io/angelstreetcorp/<image>:<branch>-<YYYY.MM.DD>-<build>

docker-compose reference:          image: ghcr.io/angelstreetcorp/<image>:<branch>-<YYYY.MM.DD>-<build>

Render deploy header (display):    <branch>-<YYYY.MM.DD>-<build>      ← Render's own label, not the image's actual content

Pi / backend_host /api/health:     "deployed_version" field — read from VERSION.txt on first boot
```

These four are easy to confuse. The Render display label and the bundle content baked at build time will match **only if** Render actually built from source — and we saw in BUG-0156-style incidents that they often don't. Always cross-check `cat /app/VERSION.txt` inside a running container before believing a label.

## When something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `verify` job: `failed to pull image: ... not found` | The tag you typed doesn't exist in GHCR | Check the published tags at `ghcr.io/angelstreetcorp/<image>:?tab=tags`; re-trigger with a real tag or `latest` |
| `verify` job: `expected ghcr.io/angelstreetcorp/*:<tag>, got <other>` | `launch.sh` fell back to building (pull failed silently) | Look at the launch.sh logs to see the actual pull error; usually network or a typo in the tag |
| Workflow_dispatch says "completed" but no new images in GHCR | You triggered from the **internal** repo | Repeat from the public repo (Step 1) |
| `docker inspect` shows the right image but `cat VERSION.txt` inside shows the wrong tag | You published from a commit whose `VERSION.txt` didn't match the tag you typed | Re-publish with the tag that matches `current:` in that commit's `VERSION.txt` |
| User's `VPT_IMAGE_TAG=latest` pulls a broken image | A bad publish moved `latest` | Re-publish (the workflow overwrites `latest` with the new tag) or hand-edit a known-good tag back onto `latest` per the Rollback table |

## See also

- [docker.md § Skip the build](docker.md) — the consumer side
- [ci_cd.md](ci_cd.md) — the regression workflow that runs on every push
- [.github/workflows/release-images.yml](../../.github/workflows/release-images.yml) — the workflow definition itself; the comments at the top are the canonical rationale
- [scripts/release/publish_public.sh](../../scripts/release/publish_public.sh) — mirror internal → public before publishing from `main`