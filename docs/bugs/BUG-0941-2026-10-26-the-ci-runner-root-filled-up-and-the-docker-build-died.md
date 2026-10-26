# BUG-0941 — The CI runner root filled up and the docker-build job died

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0941                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | CI / regression suite / runner infrastructure                |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/ci-runner-disk-dangling-images`              |

---

## Symptom

The `Docker stack builds and starts` job of the regression suite failed on `main` on 2026-10-26, twice, and
the error had nothing to do with the code under test:

```
failed to register layer: Error processing tar file(exit status 1):
write /usr/local/lib/node_modules/pnpm/dist/pnpm.mjs: no space left on device
##[error]Process completed with exit code 18.
```

Run `40274557257` (05:30, on `df42e2d3`) failed in `E2E Viewport Tests` and `Docker stack builds and starts`;
run `40279744045` (06:25, on `282afbbd5`) failed only in `Docker stack builds and starts`, while every other
job of that run — including the type check and the E2E suites — passed.

The runner that ran the job had no room left:

```
/dev/sdb1   31G   28G  1.2G   96% /       (runner VM 163)
/dev/sdb1   31G   28G  1.2G   96% /var/lib/docker
```

The 31 GB root of runner VM 163 held 11.77 GB of Docker images, of which one 5.06 GB image carried no tag
at all (`<none>:<none>`, one hour old).

## Root cause

**The prune step of the docker-build job only removes images that are older than 24 hours, and a rebuild
leaves its previous image behind untagged.**

[.github/workflows/regression.yml](../../../.github/workflows/regression.yml) ended every runner job with:

```yaml
docker image prune -af --filter "until=24h" || true
docker builder prune -f --filter "until=24h" || true
```

The job builds `virtualpytest-host:local` and tags it. The next build of the same repository rebuilds the
image and re-points the tag at the new one, so the **previous 5 GB image becomes dangling**: no tag, and no
container references it, but it is younger than 24 hours, so the `until=24h` filter skips it. Each rebuild
therefore left another 5 GB on the runner root, and the runner root is 31 GB.

The age filter itself is right — it is what keeps an image that a concurrent job on the same runner VM has
just built (three runners share VM 163, so one runner's build is another's input). The gap was the dangling
images, which no job can be using: they have no name and no container.

## Fix

The prune step removes the untagged leftovers at any age, and keeps the age filter for the tagged images:

```yaml
docker image prune -f || true
docker image prune -af --filter "until=24h" || true
docker builder prune -f --filter "until=24h" || true
```

`docker image prune` without `-a` only removes images that no container uses, so a running job keeps
whatever it started. The 24 h filter still protects the tagged images a concurrent job is about to use.

## Verification

- On the runner that failed, the dangling image was pruned by hand and the root went from **96 % (1.2 GB
  free) to 80 % (6.0 GB free)**, 4.93 GB reclaimed, while a job was running on that VM.
- The next pushes to `main` (06:48, 06:51, 06:52) built their images on the same runner with the disk at
  80 % and the `Docker stack builds and starts` job passed.
- The step itself runs on every runner job (`if: always()`), so the leftover is reclaimed after each build
  instead of accumulating until the disk is full.
