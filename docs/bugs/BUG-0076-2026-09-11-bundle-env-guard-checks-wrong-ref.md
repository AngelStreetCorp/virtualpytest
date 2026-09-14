# BUG-0076 — Customer bundle build aborts on an older `PIN`: the `.env` guard checks the working tree's branch, not the staged commit

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0076                                                     |
| Reported  | 2026-09-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | release / packaging (`setup/proxmox/node/build_customer_bundle.sh`) |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

Building a customer bundle pinned to a release tag older than `main` aborts at the last step,
after the whole tree has already been staged:

```
=== Checks ===
ERROR: stage carries .env file(s) that are neither frontend/.env.production, frontend/.env.local
nor git-tracked templates:
  backend_server/src/.env.example.bak
```

Reproduced building the first bundle for the second customer at `PIN=main-2026.09.08-<pin>`.
The named file is a harmless **git-tracked template** that existed at that tag and was deleted on `main` afterwards —
nothing was leaking. Pinning to `main` (or to a tag with no since-deleted `.env*` template) hid
the bug, which is why the previous deliveries never hit it.

## Root cause

`build_customer_bundle.sh` builds its allow-list of legitimate `.env*` files with

```bash
tracked_env="$(git -C "${REPO_DIR}" ls-files | grep -E '(^|/)\.env' || true)"
```

`git ls-files` describes **whatever `REPO_DIR` is checked out at right now** — and by the time the
guard runs, the staging step (`deploy_customer.sh --stage-only`) has already restored the checkout
to the branch it was on before it detached to the `PIN` (`restored … to branch main` in the log).
So the stage, taken from the pinned commit, is validated against `main`'s file list: every `.env*`
template that the pin carried but `main` has since deleted is reported as an unexplained `.env` and
fails the build.

## Fix

`setup/proxmox/node/build_customer_bundle.sh` — take the reference list from the commit that was
actually staged. `core_ref` (read from the staged `VERSION.txt`) already carries `<PIN> <sha>`; the
sha is now extracted as `core_sha` and the guard reads that tree:

```bash
core_sha="${core_ref#* }"
tracked_env="$(git -C "${REPO_DIR}" ls-tree -r --name-only "${core_sha}" | grep -E '(^|/)\.env' || true)"
```

with a fallback to the old `ls-files` behaviour when `core_ref` is absent (so a `--no-checkout`
build of a dev tree is still checked). The guard keeps rejecting anything that is not
`frontend/.env.production`, the generated `frontend/.env.local`, or a template tracked at the
staged commit — a real `.env` is never tracked at any commit, so the leak check is unweakened.

## Verification

```bash
REPO_DIR=<fresh platform clone> \
  bash setup/proxmox/node/build_customer_bundle.sh ~/vpt-customer-<name> --out ~/bundles
```

Before: aborts on `backend_server/src/.env.example.bak`. After:

```
env files in bundle: frontend/.env.local frontend/.env.production
(no other .env* except the 13 git-tracked templates)
```

and the archive is written. Confirmed on the bundle
`vpt-<customer>-main-2026.09.08-<pin>_prod-2026.09.11-1.tar.gz`, whose `.env*` listing is exactly those
two files plus the pin's templates.
