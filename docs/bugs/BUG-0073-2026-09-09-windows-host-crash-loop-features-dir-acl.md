# BUG-0073 — Windows hosts crash-looped after the deploy: `features/` created by rsync with an unreadable ACL

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0073                                                                    |
| Reported  | 2026-09-09 (customer site, first packaged delivery, Windows hosts)          |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (every Windows host offline after the deploy, restart loop)            |
| Area      | shared/src/lib/utils/features.py · Windows rsync push in update_core.sh / deploy_customer.sh / customer update_core.local.sh |
| Fixed in  | Unreleased                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

After `update_core.local.sh --host-windows` pushed build 8713, the `vpt-host` scheduled task on
every Windows host entered the wrapper's restart loop ("backend host app exited with code 1
after 4s … restarting in 5s/10s/20s/40s/60s"). `C:\virtualpytest\logs\host_error.log`:

```
  File "...\shared\src\lib\utils\features.py", line 34, in enabled_features
    for name in sorted(os.listdir(features_dir)):
PermissionError: [WinError 5] Access is denied: 'C:\\virtualpytest\\virtualpytest\\features'
```

raised from the new `register_feature_blueprints(app, 'backend_host')` call in
`register_host_routes()`, which is outside that function's try/except → `main()` exits 1.

## Root cause

Two things met:

1. **The deploy created a brand-new directory on Windows.** `features/` did not exist in the
   customer's previous tree. The push goes through a Cygwin-based rsync (Chocolatey package) over
   Win32-OpenSSH; a directory rsync *creates* gets a Cygwin POSIX-mapped ACL (owner-only, no
   inheritance from the parent), which the account running the `vpt-host` task cannot read.
   Pre-existing directories kept their inherited Windows ACLs, so nothing else broke.
   `--no-perms` alone does not prevent this: without `--chmod`, rsync still applies its own
   mode to *new* entries.
2. **The feature scan could take the host down.** `enabled_features()` guarded a *missing*
   directory but not an *unreadable* one, and the optional-feature registration was added
   after the route try/except, so an `OSError` from a directory listing became a fatal
   startup error — for a mechanism whose whole point is being optional.

## Fix

- `shared/src/lib/utils/features.py`: `os.listdir` wrapped; an unreadable `features/`
  logs `[@features] ⚠️ cannot list … - no optional feature loaded` and returns `[]`.
  The core app starts; the optional features are simply absent. Same helper serves the
  server, so both apps get it.
- Windows rsync push, all three scripts: `--no-perms --chmod=ugo=rwX --omit-dir-times`
  (rsync's documented recipe for "new files get the destination-default permissions"),
  so directories rsync creates inherit the parent's Windows ACL instead of a Cygwin one.
  `deploy_customer.sh` moved from `-a` (which implied `-p`) to `-rlz` like the other two.
- Overlay `infra/deploy/WINDOWS_HOST_SSH.md`: symptom + one-time repair recorded.

## Repair on an affected host (elevated PowerShell)

```powershell
icacls C:\virtualpytest\virtualpytest /reset /T /C /Q     # ACLs back to inherited-from-parent
# the wrapper restarts vpt-host on its own within 60 s; or: Restart-ScheduledTask vpt-host
```

## Verification

- Loader: `enabled_features()` on a `chmod 000` directory → warning line, `[]`, no exception.
- Scripts: `bash -n` on all three. The permission recipe is the one from the rsync man page
  (`--perms` section); the on-site `icacls /reset` is the equivalent one-off.
- Not yet re-deployed on a Windows host with the new flags (next release).
