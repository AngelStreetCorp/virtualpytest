# setup/proxmox/vm — per-VM helper scripts

Used on the VMs of a multi-VM install (`docs/get-started/proxmox.md` §Proxmox fleet). The role
installers themselves are in `setup/local/linux/<role>/`.

| Script | Run on | Purpose |
|---|---|---|
| `shared/install_prerequisites.sh` | every VM, once | packages, IPv4-first apt, `vpt_user` service account |
| `storage/create_disks_partitions.sh` | storage VM, once, as root | partition and format the data and shared disks |
| `storage/storage_setup_nfs_server.sh` | storage VM | export `/data` and `/shared` over NFS to the LAN |
| `shared/mount_nfs_shared.sh` | frontend / monitoring / database / proxy VMs | mount the shared export read-only |
| `shared/mount_nfs_data_shared.sh` | server and host VMs | mount data (read-write) and shared |
| `runner/install_runner.sh` | CI runner VMs | GitHub Actions runner setup |
| `backend-host/validate_android_host.sh` | Android host VMs | post-install check of the emulator host |

Storage layout and network conventions: `storage/vm-storage-overview.md`,
`vm-network-overview.md`, `vm-software-overview.md`, `vm-user-account-overview.md`
(reference material for this project's own fleet; addresses in them are examples).
