# BUG-0961 — A host deploy shipped the code but never installed the Python packages, so a fixed dependency never reached the host service

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0961                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Critical                                                     |
| Area      | platform / infrastructure                                    |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

The server deploy got a Python-dependency step in BUG-0946. The **host** deploy never did: it pulls
the code, rsyncs it to the target and restarts `vpt-host.service`, and nothing else. A host venv is
filled once, by the installer that sets the host up
(`setup/local/linux/backend_host/install_host.sh`), and no deploy path calls it again.

So when a pinned dependency changes in `backend_host/requirements.txt`, the host deploy copies the new
file, restarts the service on the **old** packages and reports success. The repository says one
version, the venv keeps another.

This is not a theory either. BUG-0954 raised Pillow to 13.0.0 on both manifests (a critical JPEG
decoder overflow, GHSA-8g5g-8vmr-9782, plus six high and two medium advisories). The server
manifest got an exact pin and the server deploy installed it on the running servers. The host
manifest carried a range, `Pillow>=13.0.0,<14.0.0`, and **a range is not installable by a deploy**
(the dependency step installs exact pins only, `name==version`). The host venvs were therefore never
touched: the fleet still ran Pillow 10.4.0 on the host clones and the lab boxes and 12.3.0 on the
Lenovo and Wise boxes, days after the critical advisory was closed in the repository.

The host service is the part of the platform that reads the captures and the screenshots coming off
the devices — the images the JPEG decoder advisory is about.

## Root cause

Two gaps in a row, and the second one hid the first:

1. **A host deploy installed no Python package at all.** The dependency step added in BUG-0946 was
   wired into `sync_and_restart` for the *server* service only, and it read
   `backend_server/requirements.txt` only. The host service had no package step, so nothing in the
   host venv could ever change through a deploy.
2. **A range is not installable.** The dependency step deliberately installs exact pins only: a range
   would need a full resolve of the whole manifest, which is a much bigger decision than a deploy
   should make on its own. So the host manifest could not be fixed by writing a range — the range is
   exactly what the deploy cannot act on.

The result was a host manifest that said `Pillow>=13.0.0,<14.0.0` — a statement of intent that no
deploy path could carry out. A green host deploy, a correct manifest and a vulnerable venv, all at
the same time.

## Fix

`setup/proxmox/node/update_core.sh` gains the host side of the dependency step, and the host
manifest's Pillow becomes an exact pin.

**The host deploy installs the host manifest's pins.** The dependency step takes the manifest as an
argument: `backend_server/requirements.txt` for a server deploy, `backend_host/requirements.txt` for
a host deploy. Each service is compared against its own manifest, so a host deploy installs the
host's pins and never the server's, and the two services on a host that shares one venv (the Pi
boxes run the server and the host service from the same `/opt/virtualpytest/venv`) converge on the
same version.

**The host manifest's Pillow is an exact pin.** `backend_host/requirements.txt` now says
`Pillow==13.0.0`, like the server manifest. A range there meant "the deploy cannot do anything about
this", which is the worst thing a pin can say. The rest of the host manifest is left as it is: only
exact pins are installed, so the other 49 entries keep behaving exactly as before.

**What is compared, what is installed and when** are unchanged from BUG-0946: the pin the repository
declares against the version the venv actually has (read from the target with
`pip list --format=freeze`), only exact pins, on every deploy and not only when the code changed,
with the venv ownership put back first and a failed install failing the deploy instead of restarting
the service on a half-installed dependency.

**A host that refuses `-u vpt_user` still gets the pin.** The install runs as the venv's user, which
is what keeps pip able to write the distribution metadata. One host in the lab has a narrower
sudoers rule: the ssh user may reach root without a password but not the venv's user, so the first
form was refused and the deploy would have failed there. The install now falls back to root and puts
the ownership back right after, instead of failing the deploy on that host.

**A leased host is left alone.** The dependency step runs on the host path only where the deploy
already syncs and restarts. A host that is leased gets its code synced and its restart deferred
(the catch-up deploy restarts it when the lease is released), and its venv is not touched in the
meantime.

The harness `setup/proxmox/node/test_update_core_python_deps.sh` (already in the CI list) gained the
host path: the host manifest's pins are its own, a host deploy installs them, a host deploy does not
install the server manifest's pins, a range in the host manifest is still never installed, and a
host that refuses `-u vpt_user` gets the pin installed as root with the ownership put back.

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

4. After the next host deploy, the host venv matches the repository:

   ```
   /opt/virtualpytest/venv/bin/pip list --format=freeze | grep -i pillow
   /opt/virtualpytest/venv/bin/python -c "import PIL; print(PIL.__version__)"
   ```
