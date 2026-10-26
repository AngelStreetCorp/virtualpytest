# BUG-0550 — Fresh Debian 13 desktop hosts auto-suspend via gdm/gsd-power, taking the VPT host offline

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0550                                                     |
| Reported  | 2026-10-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | infra / host install                                         |
| Fixed in  | build 90145 |
| Commit    | `c2061b644` (initial) — VNC follow-up still on lenovo1, see Verification |

---

## Symptom

A newly installed VPT host on a Debian 13 desktop image (Lenovo
`DESKTOP-DT1V604`, i3-4150T, 4 GB, 192.168.x.26) becomes unreachable
~10 minutes after boot on every fresh start:

- `ssh vpt-lenovo1` → `Network is unreachable` on `<gateway-ip>:2226`
  (SFR gateway port forward to `192.168.x.26:22`)
- From `vpt-nipogi` on the same LAN: `ping 192.168.x.26` → 100% loss,
  ARP entry becomes `FAILED` / `STALE`
- After some minutes, the host reappears with a fresh `last_seen` —
  uptime < the gap, so the box *was* offline, not just the link flapping
- `vpt-host` heartbeat is *outbound* — the UI keeps the host marked
  `online` throughout the gap (same hazard as
  [INFRA.md › "online" does not mean viewable](../agent/infra/INFRA.md#online-does-not-mean-viewable))

## Root cause

`install_host.sh` does not strip the desktop metapackage from a
Debian 13 desktop image. The result is a fully-booted GNOME session
under the `<operator>` account, with `gsd-power` honouring the default
"sleep on idle" policy:

- `journalctl`: `systemd-logind[…]: Operation 'suspend' finished.`
  preceded by `systemd-sleep[…]: Performing sleep operation 'suspend'…`
- Kernel ring: `ACPI: PM: Preparing to enter system sleep state S3` /
  `ata1.00: Entering standby power mode` / `OOM killer disabled` (and
  inverted on resume). The disk-standby line in the same second is
  the signature; on a server box it is unique to S3.
- Observed gap: **10 min 25 s** between
  `22:07:16 Performing sleep operation 'suspend'…` and
  `22:17:41 System returned from sleep operation 'suspend'.`
- Triggers: `gsd-power` (`GNOME needs to lock the screen` delay
  inhibitor), `gsd-media-keys` (block + delay). `vpt-pi4` and
  `vpt-nipogi` do not show the same pattern — both lost the desktop
  early and run as headless servers.

A server with a GUI installed but no user driving it is the worst
case: no keypress, no pointer activity, the idle timer elapses, the
box sleeps. `vpt-host`'s outbound heartbeat cannot keep it awake
(it is a regular socket, not a wake-source), and the UI cannot tell
the difference between "sleeping" and "dead" without the tunnel-side
diagnostic in INFRA.md.

## Fix

Two layers, applied together on `vpt-lenovo1` (2026-10-15):

1. **Remove the desktop stack so nothing can re-arm suspend.**
   - Stop & disable `gdm3`, kill the running `gnome-shell` (was
     PID 1631 under `<operator>`).
   - `apt-get remove --purge -y task-desktop task-gnome-desktop
     gdm3 gnome-shell gnome-session gnome-control-center
     gnome-software gnome-terminal gnome-tweaks nautilus
     gnome-calendar gnome-characters gnome-clocks gnome-contacts
     gnome-logs gnome-maps gnome-music gnome-connections
     gnome-disk-utility gnome-font-viewer gnome-remote-desktop
     gnome-online-accounts gnome-bluetooth evolution rhythmbox
     shotwell cheese transmission-gtk simple-scan gedit eog`
   - `apt-get autoremove --purge -y`.
   - `NetworkManager` and `ModemManager` were left in place (the
     Wi-Fi watchdog in `backend_host/scripts/wifi_watchdog.sh`
     and the `sfr` gateway logic use `nmcli`).
   - **If a VNC console is wanted later** (the case on `vpt-lenovo1`):
     install `xfce4 xfce4-goodies` (~280 MB) — the DE the noVNC tile
     needs. Xfce's own power manager is set to *never* suspend via
     `/var/lib/vpt_user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml`
     (`inactivity-sleep-mode-on-{battery,ac}=0`, `power-button-action=3`,
     `dpms-enabled=false`), so even the session-level timer cannot
     put the host to sleep. The four system-level sleep targets stay
     masked. Verified: the `Xtigervnc :1` + `xfce4-session` + `xfwm4`
     + `xfdesktop` processes are up, and `https://<server>/host/vpt-lenovo1/vnc_lite.html`
     returns `200` (5781 B noVNC HTML) through the `rpitest.conf`
     regex block (see [INFRA.md › NEW_HOST_VM.md step 6.5](../agent/infra/NEW_HOST_VM.md)).

2. **Defence in depth** (in case the desktop ever comes back):
   - `systemctl mask suspend.target hibernate.target hybrid-sleep.target
     suspend-then-hibernate.target`
   - `/etc/systemd/logind.conf`:
     `HandleLidSwitch=ignore`, `HandleLidSwitchExternalPower=ignore`,
     `HandleLidSwitchDocked=ignore`, `IdleAction=ignore`, `IdleActionSec=0`
   - Per-user `gsettings` for `<operator>` (only relevant if a `gnome-*`
     session ever returns):
     `org.gnome.settings-daemon.plugins.power
      sleep-inactive-battery-type='nothing'`,
     `sleep-inactive-ac-type='nothing'`,
     `idle-dim=false`.
   - Backup: `/etc/systemd/logind.conf.bak-20261015-nosleep`.

The mask is enough to break the loop; the gsettings + logind lines
make the same intent explicit even if the mask is later reverted
by an installer that re-pulls the desktop task.

## Verification

- `systemctl is-enabled suspend.target hibernate.target
  hybrid-sleep.target suspend-then-hibernate.target` →
  `masked` for all four.
- `journalctl --since "-5 minutes" | grep -iE "suspend|hibernate"`
  on `vpt-lenovo1` after the fix is empty across a 3-min
  load-avg / RAM / temp probe (vs the pre-fix run which lost
  contact at t=90s into the same probe).
- `vpt-lenovo1` keeps a steady `online` heartbeat on the
  RPI4-server (`/server/system/getAllHosts`) for at least the
  duration of the probe.
- Capacity probe (`MONITOR_PROFILE=tv_lite`, 6 SD HLS streams):
  load 2.10–2.99 / 4 threads (~50–75 % busy), RAM 2.5 GB used
  of 3.8 GB (~66 %), package temp 56–58 °C — no throttle,
  no sleep.
- Post-`apt autoremove` `df -h /` shows 8.7 GB used → ~6 GB used
  after the desktop stack and its `-data` / `-plugin` packages
  are gone (recorded in the same run).

## Apply to next installs

Document the desktop-strip in `docs/agent/infra/NEW_HOST_VM.md` so
the next Debian-13-desktop host does not have to be retrofitted.
Track that change under a small follow-up task; not part of this bug.
