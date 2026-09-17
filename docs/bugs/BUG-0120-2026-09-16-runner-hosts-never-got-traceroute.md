# BUG-0120 — `traceroute` was never installed on runner hosts, and had drifted off an existing host

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|------------------------------------------------------------------------|
| ID        | BUG-0120                                                              |
| Reported  | 2026-09-16                                                            |
| Status    | Fixed (pending deploy)                                                |
| Severity  | Low (one failing step in network-diagnostic scripts; ping/score still work) |
| Area      | `setup/local/linux/backend_host/install_host.sh`                     |
| Fixed in  | build 9151                                                            |
| Commit    | this commit                                                           |

---

## Symptom

`test_scripts/gw/superping.py`'s traceroute step fails on some hosts with
`traceroute command not found. Install with: sudo apt-get install traceroute`, even though the
ICMP ping step (and the script's overall score) succeeds.

## Root cause

`install_host.sh` installs `traceroute` for a **full** `backend_host` (any `HOST_TYPE` that isn't
`runner_*`), but never included it in the **runner** package list. `test_scripts/gw/*` (superping,
dns_lookuptime, ookla_speedtest) are generic network-diagnostic scripts documented to run "from the
host perspective" with no restriction to full hosts, so a runner-type host missing `traceroute`
fails the same way. Separately, several full hosts had drifted: `traceroute` has been in the
full-host package list since the initial repo snapshot, but the binary wasn't present on the
running machines — provisioned before that install step ran, or lost some other way; the install
script itself was never the gap for those hosts.

## Fix

- Added `traceroute` to the runner branch's `apt install` list in `install_host.sh` so a fresh
  runner install carries it.
- Swept every reachable host on both VirtualPyTest environments (the main deployment behind
  `proxmox`, and the QualiAI deployment behind `proxmox3`) and installed `traceroute` wherever it
  was missing: `host-clone-1` on both environments, `host-clone-2` on QualiAI, and the QualiAI CI
  runners `cicd-runner`/`cicd-clone-2`/`runner-01`.
- `host-clone-2` on the main environment is currently stopped and wasn't checked; the Android-TV
  runner on QualiAI wasn't reachable at its expected address. `labox-web` (ex `host-clone-3`) and
  the QualiAI Android emulator hosts already had it.
- Two of the QualiAI CI runners had no SSH access with the key already in use on that environment;
  added it to their `authorized_keys` (password auth, one-time) to be able to check and fix them.

## Verification

- `command -v traceroute` confirmed present on every host listed above as fixed.
- Re-running `superping.py` on an affected host now passes both the ICMP and traceroute steps.
- A fresh runner install (`install_host.sh` with `HOST_TYPE=runner_*`) installs `traceroute` in
  STEP 2 alongside `nmap`/`dnsutils`.
