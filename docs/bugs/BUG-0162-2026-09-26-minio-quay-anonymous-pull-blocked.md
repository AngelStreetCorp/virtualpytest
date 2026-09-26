# BUG-0162 — Docker stack can't start: quay.io/minio/\* refuses anonymous pulls

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0162                                                     |
| Reported  | 2026-09-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | setup/docker, setup/local/linux, CI                          |
| Fixed in  | build 9364                                                   |
| Commit    | 38425c0432                                                   |

---

## Symptom

Every `Docker stack builds and starts` CI run (regression.yml) failed at the "Launch the
stack exactly like a user" step:

```
minio Error
minio-init Error
Error response from daemon: unauthorized: access to the requested resource is not authorized
##[error]Process completed with exit code 18.
```

The same failure hits any fresh Docker install (`./launch.sh`, the default `VPT_IMAGE_TAG=local`
path) and the native/VM install path (`setup/local/linux/storage/install_minio.sh`), since both
pulled the same pinned tags from quay.io.

## Root cause

`setup/docker/docker-compose.yml` pinned `quay.io/minio/minio:RELEASE.2025-07-23T15-54-02Z` and
`quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z` directly as `image:` (no `build:` fallback).
quay.io — MinIO's own registry, already the fallback after Docker Hub's `minio/*` started
returning 401 (BUG unfiled, fixed in commit `fc9a7f24a0`) — itself stopped honoring anonymous
pulls for these repositories in late 2026: the anonymous bearer token quay.io hands out for
`repository:minio/minio:pull` has `"actions":[]`, so every pull is refused regardless of tag.
`docker.io/minio/minio` doesn't exist and `bitnami/minio` returns empty tag lists, so there was
no other registry mirror to fall back to.

Separately, `setup/local/linux/storage/install_minio.sh` (the native, non-Docker install path)
extracted the same binaries via `docker create quay.io/minio/...` + `docker cp`, hitting the
identical 401 — and its pinned `MINIO_IMAGE` tag (`RELEASE.2025-04-22T22-12-26Z`) had *already*
been removed from quay.io independently (commit `9fe06a15b2`), so it was doubly broken.

What still works: the direct GitHub release download URLs
(`https://github.com/minio/minio/releases/download/<tag>/minio.linux-amd64.<tag>`) resolve fine
even for these exact pinned versions — verified by curl (302 to a real asset) and by building
and running the binary. GitHub's release-asset CDN is a different code path from the
GitHub *Releases API* returning empty `assets` for `latest`, which is a separate, unrelated gap.

## Fix

1. **`setup/docker/images/minio/Dockerfile`** and **`setup/docker/images/minio-mc/Dockerfile`**
   (new) — minimal `alpine:3.20` images that `curl` the pinned MinIO/mc binaries straight from
   their GitHub release assets. No registry dependency at build time beyond GitHub itself.
2. **`setup/docker/docker-compose.yml`** — `minio` and `minio-init` now carry a `build:` block
   pointing at those Dockerfiles, alongside `image: .../minio:${VPT_IMAGE_TAG:-local}` /
   `.../minio-mc:${VPT_IMAGE_TAG:-local}` — the same local-build-vs-registry-pull toggle the
   three app images already use. Default (`VPT_IMAGE_TAG=local`) always builds locally, so
   CI and a fresh install need nothing from any registry.
3. **`setup/docker/launch.sh`** — added `minio minio-init` to the pull-mode fallback list
   (`PULL=(...)`), so a `VPT_IMAGE_TAG=<real tag>` install that can't reach GHCR for these two
   falls back to building, same as the app images.
4. **`.github/workflows/release-images.yml`** — added `minio` and `minio-mc` to the publish
   matrix (`ghcr.io/angelstreetcorp/minio`, `ghcr.io/angelstreetcorp/minio-mc`), and to the
   `verify` job's "came from the registry" assertion.
5. **`setup/local/linux/storage/install_minio.sh`** — replaced the `docker create`/`docker cp`
   extraction with a direct `curl` from the same GitHub release URLs, and re-pinned its MinIO
   version to `RELEASE.2025-07-23T15-54-02Z` to match `docker-compose.yml` (it had drifted to a
   since-removed tag). No longer requires Docker at all for this step.
6. **Docs** — `docs/get-started/gcp-standalone.md` § "The MinIO workaround" (previously a
   ~140-line mandatory manual host-systemd-MinIO workaround) rewritten to a short resolved note;
   `docs/get-started/publishing-images.md` updated for five published images instead of three.

## Verification

- Built both new images locally (`docker build -f setup/docker/images/minio/Dockerfile .` and
  the `-mc` equivalent) — both succeed, no registry involved beyond `alpine:3.20` + GitHub.
- Ran each vendored binary directly: `minio --version` → `RELEASE.2025-07-23T15-54-02Z`;
  `mc --version` → `RELEASE.2025-04-16T18-13-26Z` — both match the pinned tags exactly.
- `bash -n` on `launch.sh` and `install_minio.sh`; `python3 -c "import yaml; yaml.safe_load(...)"`
  on `release-images.yml`.
- `scripts/docs/check_paths.sh` and `scripts/docs/check_bug_ids.sh` both pass.
- CI (`Docker stack builds and starts`) is the end-to-end confirmation for the full compose
  path (build-mode `minio`/`minio-init` under the CI-default `VPT_IMAGE_TAG=local`) — pending
  on this commit.
