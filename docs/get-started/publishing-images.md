# Publishing container images to GHCR

Ready-made VirtualPyTest images are stored on GitHub, so a new install can skip building from source. This page is for project contributors who publish them. Most people never need it.

<div data-technical>

Five containers are published to GitHub Container Registry at `ghcr.io/angelstreetcorp`: the three VirtualPyTest ones — `virtualpytest-server`, `virtualpytest-host`, `virtualpytest-frontend` — plus `minio` and `minio-mc`, which vendor the upstream MinIO binaries (registries that used to serve them stopped allowing anonymous pulls; see `gcp-standalone.md` § "The MinIO workaround"). A `launch.sh` install can pull all five instead of building from a local checkout, which makes first-run installs ~2 minutes instead of ~15. This page is the lifecycle for the *publishing* side: when to publish, how to publish, how to verify a published tag works, and how to roll back if it doesn't.

</div>

> Only want to **use** the images? You do not need this page. See [docker.md](docker.md) § "Skip the build (prebuilt images)".

<div data-technical>

For `VPT_IMAGE_TAG=…` in `setup/docker/.env`, see [docker.md § Skip the build](docker.md#skip-the-build-prebuilt-images). The rest of this page is for project contributors cutting a publish.

</div>

---

## What's published

Five images, all stored in one place on GitHub. Three are the VirtualPyTest server, host and web page. Two are small helpers for MinIO, the file storage the platform uses.

`latest` is the last image the project chose to publish. It can be weeks behind `main`. For the same install every time, use a fixed tag.

<div data-technical>

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

</div>

---

## What runs the publish

A GitHub workflow builds all five images, pushes them only from the public repo, then starts them on a fresh machine to check they work. Nothing starts on its own. Someone has to press the button.

<div data-technical>

`.github/workflows/release-images.yml` has two jobs that matter:

- **`build`** — builds all five Docker images, then **only pushes to GHCR if the workflow runs on the public repo** (`AngelStreetCorp/virtualpytest`). On the internal repo (`virtualpytest-internal`), the build runs and the images are discarded — see the long comment near the top of the workflow for why (the leak gate cannot see what's inside an image, so the three VPT-source images must only be built from the public snapshot; `minio`/`minio-mc` ride the same gate for simplicity, though they embed no VPT source).
- **`verify`** — `launch.sh`-es the published images on a fresh runner, then asserts `docker inspect --format '{{.Config.Image}}' vpt-server` is literally `ghcr.io/angelstreetcorp/virtualpytest-server:<tag>` (so a passing run really pulled from the registry, not a `local` build that snuck through `launch.sh`'s fallback). It then curls `/server/health`, `/host/system/health`, the Supabase REST endpoint, and Grafana. This is the actual end-to-end test of "does the published image work".

Both jobs are **`workflow_dispatch` only**. Nothing fires on a tag push — see the comment at the top of the workflow for the reasoning (no consumer actually depends on registry images, the first install builds locally anyway, and ~3 GB × 3 images per tag would dominate CI minutes).

</div>

---

## When to publish

Publish only when you have a reason. A local build already gives a working install.

- **You want a fresh first run for users**, because the current `latest` is months old. Publish.
- **You tagged a customer release.** Publish, then point the public docs at that tag.

<div data-technical>

- **Another environment needs a published image.** For example, a Raspberry Pi image built from the same Dockerfile must match. Publish that tag.
- **You upgraded a base layer that local builds do not include**, such as the Python or Node version. Publish, so existing installs do not stay on the old base.

Local builds use `VPT_IMAGE_TAG=local`. The base layer examples are Python 3.11 to 3.12 and Node 18 to 20.

</div>

- **Otherwise:** don't. A local build matches the user's own checkout exactly. That is the more honest choice for almost every case.

---

## How to publish

Pick the right repo before you start anything. Publishing from the wrong one wastes a run and publishes nothing.

### Step 1 — Decide which repo to publish from

Publish from the **public** repo. Development happens in the **internal** repo, so copy the release to the public repo first.

<div data-technical>

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

</div>

### Step 2 — Decide the tag

The tag must match the version number in the project's version file, at the commit you publish from. Check it by eye before you publish. The automatic checks do not catch a mismatch.

<div data-technical>

| Tag source | When | How to set |
|---|---|---|
| `github.ref_name` (a real Git ref) | You're publishing from a tagged commit (`main-*` or `release-*`). | The workflow reads it automatically. |
| `inputs.tag` (manual) | You're publishing from `main` HEAD or a specific commit. | Type it into the workflow_dispatch input box — e.g. `main-2026.09.26-9358` to match `VERSION.txt`. |

The tag you publish must match what's in `VERSION.txt` at the commit you publish from, otherwise `docker inspect` will show a version mismatch in the deployed container (the version is baked at build time). The `verify` job does not assert this — it only asserts the image came from the registry. Add a manual eyeball check before publishing.

</div>

### Step 3 — Start the workflow

On the **public** repo, open the Actions page, run the **Release artifacts** workflow, and enter the tag. The five images build side by side. The check job runs after that.

1. **GitHub → Actions → Release artifacts → Run workflow**.
2. **Branch:** `main` (or `release-*` if you're cutting one).
3. **Image tag to build (and to publish, on the public repo only):** type the tag (e.g. `main-2026.09.26-9358`).
4. Click **Run workflow**.

<div data-technical>

Build matrix: five images in parallel. The host image is the slowest (`apt-get` dependencies), at about 10–15 minutes. The server and the web page take about 5 minutes each. The two MinIO helpers take well under a minute. The `verify` job runs on the same runner after the build, for about 10 more minutes.

</div>

### Step 4 — Watch the verify job

The verify job is the test. Watch its log for the green lines. If one is not OK, scroll up to the first problem. Also check that each running service uses the published image, not a local build. If it does not, the publish is not real yet, so find out why the download failed before you announce it.

<div data-technical>

Signals to look for in the verify log:

| Line | Means |
|---|---|
| `SUMMARY: Environment is healthy. cloudflared will use 'quic' as primary protocol.` | Backend started; nothing else interesting. |
| `200  http://localhost:5109/server/health` | Backend API answers. |
| `frontend 200` | Frontend answers. |
| `200  http://localhost:6109/host/system/health` | Host controller answers. |
| `supabase rest 200` | Database reachable. |
| `grafana 200` | Grafana reachable. |

The job also asserts:

```
vpt-server:     ghcr.io/angelstreetcorp/virtualpytest-server:<tag>
vpt-host:       ghcr.io/angelstreetcorp/virtualpytest-host:<tag>
vpt-minio:      ghcr.io/angelstreetcorp/minio:<tag>
vpt-minio-init: ghcr.io/angelstreetcorp/minio-mc:<tag>
```

If either line reports a `local` or a different image, the pull failed and `launch.sh` fell back to building — that's the silent failure mode that the assertion exists to catch. If the assertion fails, the publish is not "real" yet; investigate the pull error before announcing the publish.

</div>

---

## How to test a published tag locally

You can test a publish without GitHub. Log in, download the images for the tag, start the platform with that tag, and check each service runs the published image.

<div data-technical>

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

</div>

---

## How a user consumes a published image

Users pick a tag in a settings file, then start the platform. If the download fails, the platform builds the image locally, so an install never fails just because a tag is missing. The full steps are in [docker.md § Skip the build (prebuilt images)](docker.md#skip-the-build-prebuilt-images).

<div data-technical>

Quick recap so this page stands alone:

```bash
# Before ./setup/docker/launch.sh, edit setup/docker/.env:
VPT_IMAGE_TAG=main-2026.09.26-9358    # a specific tag
VPT_IMAGE_TAG=latest                  # the most recently published one
VPT_IMAGE_TAG=local                   # default — build from this checkout (skip the registry)
```

`launch.sh` reads that file, points every compose service at `ghcr.io/angelstreetcorp/<svc>:<tag>`, and falls back to a local build only if the pull fails. So `local` is always the safety net, even when `VPT_IMAGE_TAG` is set — useful when a tag was never published and you don't want the install to fail.

</div>

---

## Rolling back

If a publish is broken, point users at an older tag that works, or publish a fixed image as a new tag. Users can also build locally, which is slower.

<div data-technical>

| Action | When | How |
|---|---|---|
| Point users at the previous tag | The current `latest` is broken; the previous one works. | Edit any docs that say `VPT_IMAGE_TAG=latest` to pin a known-good tag, or do a fresh publish (see below) and have users re-pin. |
| Re-publish a fixed image | You found and fixed the bug, want `latest` updated. | Same as Step 3 above, with a new tag (e.g. `main-2026.09.26-9400` after the fix commit). The `latest` pointer moves with it. |
| Pull `latest` back to the previous good tag | You don't have time to fix; you need a fast unblock. | `docker pull ghcr.io/angelstreetcorp/<img>:<old-tag>` then `docker tag ghcr.io/angelstreetcorp/<img>:<old-tag> ghcr.io/angelstreetcorp/<img>:latest` then `docker push ghcr.io/angelstreetcorp/<img>:latest`. Yes, you can overwrite `latest`; GHCR doesn't lock tags. |

`launch.sh` has a fallback to `local` build, so any user can also unblock themselves by setting `VPT_IMAGE_TAG=local` — they just wait the extra 10 minutes.

</div>

---

## Version conventions cheat sheet

Four version labels look alike, and they do not always agree. Only the version inside the running container is reliable. Check that before you trust a label.

<div data-technical>

```
VERSION.txt format:                current:<branch>-<YYYY.MM.DD>-<build>
                                   previous:<branch>-<YYYY.MM.DD>-<build>-<short-sha>

container image tag:               ghcr.io/angelstreetcorp/<image>:<branch>-<YYYY.MM.DD>-<build>

docker-compose reference:          image: ghcr.io/angelstreetcorp/<image>:<branch>-<YYYY.MM.DD>-<build>

Render deploy header (display):    <branch>-<YYYY.MM.DD>-<build>      ← Render's own label, not the image's actual content

Pi / backend_host /api/health:     "deployed_version" field — read from VERSION.txt on first boot
```

These four are easy to confuse. The Render display label and the bundle content baked at build time will match **only if** Render actually built from source — and we saw in BUG-0156-style incidents that they often don't. Always cross-check `cat /app/VERSION.txt` inside a running container before believing a label.

</div>

---

## When something goes wrong

Read the first red line in the verify job, then check the tag and the repo you published from.

<div data-technical>

| Symptom | Likely cause | Fix |
|---|---|---|
| `verify` job: `failed to pull image: ... not found` | The tag you typed doesn't exist in GHCR | Check the published tags at `ghcr.io/angelstreetcorp/<image>:?tab=tags`; re-trigger with a real tag or `latest` |
| `verify` job: `expected ghcr.io/angelstreetcorp/*:<tag>, got <other>` | `launch.sh` fell back to building (pull failed silently) | Look at the launch.sh logs to see the actual pull error; usually network or a typo in the tag |
| Workflow_dispatch says "completed" but no new images in GHCR | You triggered from the **internal** repo | Repeat from the public repo (Step 1) |
| `docker inspect` shows the right image but `cat VERSION.txt` inside shows the wrong tag | You published from a commit whose `VERSION.txt` didn't match the tag you typed | Re-publish with the tag that matches `current:` in that commit's `VERSION.txt` |
| User's `VPT_IMAGE_TAG=latest` pulls a broken image | A bad publish moved `latest` | Re-publish (the workflow overwrites `latest` with the new tag) or hand-edit a known-good tag back onto `latest` per the Rollback table |

</div>

---

## See also

- [docker.md § Skip the build](docker.md) — the consumer side
- [ci_cd.md](ci_cd.md) — the regression workflow that runs on every push
- [.github/workflows/release-images.yml](../../.github/workflows/release-images.yml) — the workflow definition itself; the comments at the top are the canonical rationale
- [scripts/release/publish_public.sh](../../scripts/release/publish_public.sh) — mirror internal → public before publishing from `main`
