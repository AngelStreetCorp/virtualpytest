# setup/proxmox/vm — per-VM helper scripts

Used on the VMs of a multi-VM install (`docs/get-started/proxmox.md` §Proxmox fleet). The role
installers themselves are in `setup/local/linux/<role>/`.

| Script | Run on | Purpose |
|---|---|---|
| `shared/install_prerequisites.sh` | every VM, once | packages, IPv4-first apt, `vpt_user` service account, persistent journal |
| `shared/install_prerequisites.sh --journal-only` | every VM, any time | the persistent journal alone (see below) |
| `storage/create_disks_partitions.sh` | storage VM, once, as root | partition and format the data and shared disks |
| `storage/storage_setup_nfs_server.sh` | storage VM | export `/data` and `/shared` over NFS to the LAN |
| `shared/mount_nfs_shared.sh` | frontend / monitoring / database / proxy VMs | mount the shared export read-only |
| `shared/mount_nfs_data_shared.sh` | server and host VMs | mount data (read-write) and shared |
| `runner/install_runner.sh` | CI runner VMs | GitHub Actions runner setup |
| `backend-host/validate_android_host.sh` | Android host VMs | post-install check of the emulator host |

### The persistent journal (`--journal-only`)

A guest that hangs (qemu at 100 % of a core, network stack dead) is only
diagnosable if its own journal survives the reboot, so every guest image gets
one: `/var/log/journal` with `Storage=persistent`, capped by the free space of
the filesystem that holds it.

**The cap follows the host** (E61): `cap = min(512M, max(64M, 5 % of the free
space))` — 64 M is the floor, 512 M the ceiling. A fixed 512 M journal was
19 % of the free space left on a guest whose disk was 91 % full, on the very
device the capture writes to (measured 2026-10-24: 2.7 G free → 138 M; the
guests with 12–24 G free keep 512 M). `VPT_JOURNAL_MAX_USE` overrides the
computed value, and when the free space cannot be read the 512 M default is
used — the install never stops over it. The cap in the drop-in and the
`journalctl --vacuum-size=` argument are the same number.

`sudo bash shared/install_prerequisites.sh --journal-only` does that **and
repairs a guest that is already running** — it writes the setting where it
wins (`/etc/systemd/journald.conf.d/vpt.conf`; a drop-in overrides the main
`journald.conf`), creates the journal file journald adopts
(`journalctl --flush` — `mkdir` and `systemd-tmpfiles --create` leave the
directory empty), restarts journald and **fails loudly** if the journal is
still RAM-only. It is idempotent: a second run changes nothing.

The same files are written by the host installer
(`setup/local/linux/backend_host/install_host.sh`, STEP 7b), which picks
`volatile` or `persistent` from the host's root device and writes the same
`90-vpt-cap.conf`, byte for byte — see
[install_host.md](../../local/linux/backend_host/install_host.md#journald-storage-mode-step-7b).

Storage layout and network conventions: `storage/vm-storage-overview.md`,
`vm-network-overview.md`, `vm-software-overview.md`, `vm-user-account-overview.md`
(reference material for this project's own fleet; addresses in them are examples).
