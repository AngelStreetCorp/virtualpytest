# BUG-0946 — A server deploy shipped the code but never installed the Python packages, so a fixed dependency never reached the running service

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0946                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | platform / infrastructure                                    |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A server deploy does three things: it pulls the code, it rsyncs it to the target, and it restarts
`vpt-server.service`. It never reinstalls the Python packages.

So when a pinned dependency changes in `backend_server/requirements.txt`, the deploy copies the new
file to the target, restarts the service on the **old** packages, and reports success. The
repository says one version, the venv keeps another, and nothing anywhere says so.

This is not a theory. The `certifi` bump that closed the critical advisory
[GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2) (BUG-0944) went in as
`certifi==2026.10.19` and was deployed as `main-2026.10.26-90121`. The deploy was green. The
running servers on all three hosts still had `certifi 2025.08.03` in their venv — the bundle that
still trusts the revoked eMudhra chain — and the only way to find that out was to look at the live
venv with `python -c "import certifi"`.

Two things made it worse than an ordinary missing step:

- **The deploy looked green.** The restart succeeded, the health check succeeded, and the summary
  said `OK`. A green deploy is exactly what a person relies on to decide that a fix shipped.
- **The file on the target always says the new version.** The rsync replaces
  `backend_server/requirements.txt` before anybody compares anything, so a file-to-file diff says
  "nothing changed" precisely when the venv is the thing that is out of date.

## Root cause

`update_core.sh` treats the code and the packages as one thing. The code is versioned, compared and
synced; the packages are not versioned, not compared and not synced. The venv is explicitly outside
the rsync (`--exclude='venv'`) and nothing else puts anything in it.

The venv is created and filled by `setup/local/linux/backend_server/install_server.sh`
(`python3 -m venv` as `vpt_user`, then `pip install -r backend_server/requirements.txt`) — an
installer that runs when a host is set up. Nothing in the deploy path ever calls it again.

A second, smaller problem showed up while fixing this by hand: on `vpt-pi4` the venv had **136
root-owned entries** in `site-packages`, so a `pip install` run as `vpt_user` could not write the
distribution metadata. It failed with `Permission denied: 'top_level.txt'`, left an invalid
distribution (`~ertifi`) behind, and the result was a venv where `import certifi` worked but
`pip show certifi` said the package was not installed and `pip check` reported
`requests 2.33.0 requires certifi, which is not installed`. A deploy that installed dependencies
without fixing the ownership would have shipped exactly that.

## Fix

`setup/proxmox/node/update_core.sh` gains a Python-dependency step for the server deploy.

**What is compared.** The pin the repository declares against the version the venv actually has —
read from the target with `pip list --format=freeze`, not from the file the target had before the
rsync. The file is replaced by the rsync before anybody looks at it, so only the venv can say
whether the packages are current.

**What is installed.** Only exact pins (`name==version`), one package at a time. A range (`>=`)
would need a full resolve of the whole file, which is a much bigger decision than a deploy should
make on its own, so ranges are left alone.

**When it runs.** On every server deploy, not only when the code changed: a venv that drifted (a
package installed by hand, a failed install, a venv copied from elsewhere) has to be able to catch
up even when the code on disk is the same.

**The ownership is put back first.** `chown -R vpt_user:vpt_user` on the venv before installing
anything, so pip can write the distribution metadata as the user the installer created the venv
for. Without it, a root-owned file in the venv turns the install into a half-install.

**A failed install fails the deploy.** The service is not restarted on a half-installed dependency;
the host is reported as failed and the old code keeps running.

**The ssh call closes stdin.** `ssh` forwards the loop's input to the remote command, so a command
inside a `while read` loop that reads it swallows the rest of the list. The first version of this
step installed **one pin out of seven** and reported success: the loop stopped after the first
package because the ssh had eaten the rest of the input. `</dev/null` on the call closes it. The
harness's ssh stub eats stdin the same way, so the harness catches this rather than the deploy.

New harness `setup/proxmox/node/test_update_core_python_deps.sh` (added to the CI list in
`.github/workflows/deploy-harness.yml`, which is a hardcoded list — a harness that is not in it
never runs) covers: a pin the venv is behind on is installed, a pin it already has is left alone,
a range is never installed, the ownership is restored first, an up-to-date venv installs nothing at
all, a venv with nothing in it gets every exact pin, **every** pin behind is installed and not only
the first, the package name is compared case-insensitively, and a distribution pip spells with an
underscore matches the normalised pin.

**The name is normalised on both sides.** pip reports a distribution the way the wheel spells it
(`pydantic_core`) while the repository pins it the way PyPI normalises it (`pydantic-core`). Without
the normalisation every underscored package looks missing, and the deploy reinstalls four packages
that are already at the right version on every run. That is not a harmless noise: the comparison is
what decides whether a package is installed, so a comparison that cannot see an installed package
would also not see one that is genuinely out of date.

## Verification

1. The harness, locally and in CI:

   ```
   bash setup/proxmox/node/test_update_core_python_deps.sh
   # all python-dependency checks passed
   ```

2. The other four update_core harnesses still pass — the deploy script is shared by every session
   on the platform, so a change to it is only acceptable if nothing else moves:

   ```
   for h in setup/proxmox/node/test_update_core_*.sh; do bash "${h}" || fail=1; done
   ```

3. `bash -n setup/proxmox/node/update_core.sh` is green, and CI runs it on every push.

4. On the live servers, after the next server deploy, the venv matches the repository:

   ```
   /opt/virtualpytest/venv/bin/pip list --format=freeze | grep -i certifi
   /opt/virtualpytest/venv/bin/python -c "import certifi; print(certifi.__version__)"
   ```

## Left open on purpose

The OS-level Python on the server hosts keeps the Debian package `python3-certifi 2022.9.24-1`,
which is inside the advisory's range. It is not the platform's trust store: every Python service
on those hosts runs `/opt/virtualpytest/venv/bin/python`, and that is the one that was fixed.
Upgrading a distribution package is an OS update, not a deploy, and Debian bookworm currently has
no newer candidate — so it stays as it is until the distribution ships one.
