# BUG-0435 — vpt-vnc silently crash-loops when `/var/lib/vpt_user` is root-owned

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0435                                                     |
| Reported  | 2026-10-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / setup / host                                       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On a host where `/var/lib/vpt_user` was not created by `useradd -m` (e.g. cloned from a
template image, snapshotted, or `mkdir`'d by an installer that didn't chown the parent),
`vpt-vnc` is in a ~30s restart loop and the VNC preview panel in the web UI is blank/gray:

- `systemctl status vpt-vnc` shows `Active: activating (start) since …` and a restart
  counter in the hundreds within hours.
- `journalctl -u vpt-vnc` shows two `xauth:  timeout in locking authority file
  /var/lib/vpt_user/.Xauthority` lines (each 20s), then `Xtigervnc` binds to :5901, then
  `xfconfd: Name org.xfce.Xfconf lost on the message dbus, exiting.`, then 3s later
  `tigervncserver: No matching VNC server running for this user!`.
- The web UI shows noVNC close code 1011 with reason `Failed to connect to downstream
  server` — emitted by `websockify` on the host because its upstream VNC display (`:5901`)
  keeps dying.

The fact that `vpt-pi1`, `vpt-pi3`, `vpt-pi4` all work and only `vpt-mf1` (the Minisforum,
provisioned from a Proxmox template clone) was broken pointed at the template-clone path.

## Root cause

`/var/lib/vpt_user` is the `HOME` of the `vpt_user` service account. TigerVNC writes
`.Xauthority` here on every start, and xfce4-session writes `~/.cache` and
`~/.local/share` (XDG defaults derived from `HOME`).

When the parent dir is `root:root 755` (as on a Proxmox template-clone where the
filesystem was pre-populated and `useradd -m` was skipped or the dir was not chowned):

1. `xauth -f /var/lib/vpt_user/.Xauthority add …` waits 20s × 2 for the dotfile lock, then
   silently fails. The `.Xauthority` is never created.
2. `Xtigervnc` starts on :5901 anyway, but xfce4-session then can't create
   `~/.cache/xfce4/…` and xfconfd drops its dbus name immediately:
   `xfconfd: Name org.xfce.Xfconf lost on the message dbus, exiting.`
3. With the session components gone, `Xtigervnc` dies a few seconds later.
4. systemd sees the forking service exit and `Restart=on-failure` brings it back; the
   cycle repeats every ~30s.

`install_host.sh` chowns `$VNC_HOME/.config` and `$VNC_HOME/.vnc` (the two dirs it
itself creates) but never `$VNC_HOME` itself — line 635, 649, 697, 718 reference the
subtrees, not the parent. The parent only gets chowned if `useradd -m` did it, which is
skipped on cloned hosts.

The `vnc.service` template had carried a one-line silent auto-repair since commit
`44c3e80a9` (2026-09-23, "ensure service user's home and XDG directories are correctly
owned before starting TigerVNC") using systemd's `+`-prefix `ExecStartPre` to run
`/usr/bin/install -d -o vpt_user -g vpt_user` as root, but no live host had the new
template installed (the three Pis had all been provisioned earlier).

## Fix

`backend_host/config/services/linux/vnc.service` — replace the silent `install -d` line
with a bash wrapper that:

1. **Auto-recovers** if `/var/lib/vpt_user`, `~/.cache`, or `~/.local/share` is missing
   or not owned by `vpt_user:vpt_user` (uses the `+`-prefix `ExecStartPre` so it runs
   as root despite `User=vpt_user`).
2. **Logs loudly** when it has to fix something — prints
   `🔧 VPT-VNC AUTO-FIX: $d was [$cur], repaired to vpt_user:vpt_user` to stderr so it
   shows up in `journalctl -u vpt-vnc` and in `systemctl status vpt-vnc`. Operators can
   greppable audit with `journalctl -u vpt-vnc | grep AUTO-FIX`.
3. **Fails loud** if the auto-repair itself cannot complete (read-only parent mount,
   full disk, broken mount): prints a 5-line `FATAL` banner with the original state and
   the `install -d` error, then `exit 1` so systemd aborts the start immediately rather
   than waiting 40s for xauth to time out and silently fail.
4. **Prints a quiet success line** when everything is already correct, so even a clean
   start leaves a one-line breadcrumb in the journal (`✅ VPT-VNC: /var/lib/vpt_user +
   XDG dirs already owned by vpt_user`).

The change deploys via the standard `install_service.sh vnc --force` path, which
re-runs the substitution and `cp`es the new unit to `/etc/systemd/system/`.

## Verification

After deploying the new unit (`sudo install_service.sh vnc --force` on each host):

1. `systemctl status vpt-vnc` shows `Active: active (running)` and
   `journalctl -u vpt-vnc -n 30` includes the `✅ VPT-VNC:` or `🔧 VPT-VNC AUTO-FIX`
   marker.
2. `ss -tlnp | grep 5901` shows `Xtigervnc` bound.
3. Through the `<pi-server-host>/host/<host>/vnc_lite.html` URL, noVNC connects
   and the desktop renders. The web UI panel for that host flips from `degraded` /
   gray box to `online` / live desktop.
4. To exercise the loud path: `sudo chown -R root:root /var/lib/vpt_user` and
   `systemctl restart vpt-vnc` — the journal must show
   `🔧 VPT-VNC AUTO-FIX: /var/lib/vpt_user was [root:root], repaired to vpt_user:vpt_user`
   before the `tigervncserver` start line, and the service must reach `active (running)`
   without going through the 40s xauth-timeout phase.
5. To exercise the fail-loud path: `sudo mount -o remount,ro /` then
   `systemctl restart vpt-vnc` — the journal must show the `FATAL` banner, and
   `systemctl status vpt-vnc` must show the service failed with the banner visible
   (`systemctl status` shows the last 10 journal lines by default).
