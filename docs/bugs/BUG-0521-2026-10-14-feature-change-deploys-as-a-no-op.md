# BUG-0521 — A frontend change to a feature deploys as a no-op: the site keeps serving the previous bundle

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0521                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | deploy / frontend build pipeline                             |
| Fixed in  | build 90145 |
| Commit    | `main`                                                       |

---

## Symptom

A change confined to `features/<name>/frontend/` deploys cleanly and changes nothing on the site.
`update_core.sh main --frontend` prints the normal ending —

```
==> dist is current (caacd34bc7e3) — skipping vite build
…
========== DEPLOY SUMMARY ==========
  OK (1):     192.168.x.105
====================================
Done.
```

— and every check says it worked. The bundle served to users is the **previous** one. Measured on
the GitLab tanuki change (`8d79162d0`): the rsync landed `features/gitlab/frontend/gitlab-tanuki.svg`
on the frontend VM, the file was there at 1348 bytes, `grep` for the logo geometry in
`dist/assets/*.js` found nothing, and the GitLab menu row still rendered the old icon.

## Root cause

`frontend/scripts/ensure_dist.sh` rebuilds only when `bundle_inputs_hash()` differs from the stamp
in `dist/.build-stamp`, and its own header calls that guard airtight: *"Serving a stale bundle is
never a possible outcome."*

It is airtight for `frontend/` and leaky for `features/`. `bundle_inputs_hash()`
(`frontend/scripts/lib/build_hashes.sh`) hashed `frontend/src`, `frontend/public`, `index.html`,
the vite/tsconfig/postcss configs, `package*.json`, `.env.production` and `VERSION.txt` — and
nothing from `$REPO_ROOT/features`.

But an optional feature **is** part of `dist/` whenever it is enabled: `frontend/vite.config.ts`
emits one static import per `features/<name>/frontend/routes.tsx`, and its dev watcher covers
`features/*/frontend/**/*.{ts,tsx}` — the same files, seen from the build side. So every feature
(gitlab, zammad, tuya, cicd, avq, drone, quicktest, mods, …) shipped changes that could never
reach a user's browser through a normal deploy, while the deploy reported success.

Three things hid it, and each one is a trap for the next person:

- **rsync lands the sources.** The tree on the VM is correct, so inspecting it says nothing about
  what is being served. Only `dist/` is stale.
- **The deployed `git rev-parse HEAD` is not evidence either.** rsync copies files; it does not
  move that repository's history. The frontend VM still reported `a6dea7d67` long after the
  checkout had been updated many times over.
- **`Done.` and `OK (1)` are printed on the skip path.** The exit code is 0 and the build was
  never attempted.

`VITE_DISABLED_FEATURES` is a second hole of the same shape, which the change fixed at the same
time: `vite.config.ts` reads it to decide which `routes.tsx` are imported, the deploy passes it as
a build-time **environment variable**, and it is not a file — so switching a feature on or off
changes the bundle while nothing on disk moves.

## Fix

`bundle_inputs_hash()` now covers both:

- `"$REPO_ROOT"/features/*/frontend` — the frontend half of each feature, which is exactly what
  vite reads. A feature's `lib/` and `db/` stay out: they are backend inputs, and hashing them
  would buy a 1m45s rebuild for a python edit that cannot alter `dist/`. A feature's own
  `*.test.*` files are in, so editing one costs a rebuild — the safe direction to be wrong in
  (a needless rebuild is visible; a stale bundle is not).
- `VITE_DISABLED_FEATURES` is mixed into the stamp. When it comes from `.env.production` instead,
  that file is already hashed and the mixed-in empty value is harmless.

Cost: **+0.2 s** measured on the real tree (0.22 s → 0.42 s for the whole hash), against a
1m45s build it decides whether to run. `features/device-farm` has no `frontend/` dir and
`features/node_modules` has none either; an unmatched glob is passed through and skipped by
`find`, so neither breaks the hash.

Tests: `tests/rollout/test_build_stamp.py` — behavioural, the real shell function sourced against
a synthetic tree, 6 tests: stable when nothing changes, moves for a frontend source change, for a
feature frontend edit, for a newly added feature file, and for a feature being disabled; does
**not** move for a feature `lib/*.py` edit (that is what keeps the fix precise). Verified in the
failing direction too: reverting `build_hashes.sh` fails exactly the 3 coverage tests and leaves
the other 3 green.

## Until the deploy lands

`VPT_FORCE_BUILD=1` forces the build, but it must reach the script on the machine:

```bash
ssh proxmox "ssh frontend 'sudo -n -H -u vpt_user env VPT_FORCE_BUILD=1 \
  bash /opt/virtualpytest/frontend/scripts/ensure_dist.sh'"
ssh proxmox "ssh frontend 'sudo systemctl restart vpt-frontend-prod.service'"
```

Passing `VPT_FORCE_BUILD` to `update_core.sh` does **not** work — it shells out over `ssh` with a
fixed command string, so the variable is not forwarded, and the run fails silently if you also get
the path wrong: `update_core.sh` is `/home/<operator>/update_core.sh` on proxmox, not
`~/virtualpytest/update_core.sh`.

## After any deploy, decide with content, not with the exit code

```bash
ssh proxmox "ssh frontend 'cd /opt/virtualpytest/frontend && grep -l <distinctive-substring> dist/assets/*.js'"
```

One trap when the change is an asset: **Vite inlines a small SVG as a `data:image/svg+xml` URI**.
There is no separate file in `dist/assets/`, and `tanuki` appears in no filename and no `src`
attribute — grep the bundle for the path data, and in the DOM look for an `img` of the expected
size whose `src` starts with `data:image/svg+xml`.