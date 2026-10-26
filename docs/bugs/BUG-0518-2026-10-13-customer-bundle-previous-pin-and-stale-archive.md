# BUG-0518 — Customer bundle: previous pin never fetched, and a stale archive could be delivered

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0518                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | rollout / customer bundle (TASK-91)                          |
| Fixed in  | build 90145 |
| Commit    | `fix/bundle-review`                                          |

---

## Symptom

1. `customer_bundle.py build --prev-pin main-2026.10.01-1 ...` finished green, but the delivery note had no changelog: the previous pin was never in the clone.
2. A build into an out directory that already held earlier bundles could report an older build's archive and delivery note (or a stale archive when the builder produced none) as its own.

## Root cause

1. `_clone()` fetched the previous pin with the tag refspec and the branch refspec in ONE `git fetch`. When the pin is only a tag, git fails the whole fetch (`couldn't find remote ref refs/heads/...`, exit 128), and the return code was ignored. The fallback path (fetch by name, check out `FETCH_HEAD`) also left no local ref named after the pin, so `git show <pin>:VERSION.txt` failed in the builder.
2. `_collect()` took the archive that sorted last and the first `DELIVERY-*.md` in the shared out directory instead of the files this build named.

## Fix

`setup/proxmox/node/lib/customer_bundle.py`: the previous pin is fetched as a tag or as a branch (decided with `_remote_has_tag`), and a failed fetch is a `BuildError`; the by-name fallback tags a pin locally. `_collect()` reads the `bundle: <base>` line the builder prints and takes exactly `<base>.<fmt>`, its `.sha256` and `DELIVERY-<base>.md`; if that archive is missing the build fails with "produced no archive". Also: the askpass token file is created 0700 and deleted right after the overlay clone, and the per-build overlay checkout is removed; `candidates` reports an unreachable core remote instead of an empty success; one GitLab URL (`--gitlab-url` / `$VPT_GITLAB_URL`) serves the API calls and the clone.

## Verification

`python3 -m pytest -q tests/rollout` — the new classes use a real local git repository as the remote (tag-only previous pin, missing previous pin, by-name fallback) and a shared out directory holding archives named before and after this build's.
