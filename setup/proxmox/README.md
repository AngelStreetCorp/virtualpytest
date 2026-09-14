# setup/proxmox — multi-VM layout and fleet operations

The user guide for installing on one VM or a fleet of VMs is
**`docs/get-started/proxmox.md`**. This folder holds what that guide does not: the
storage-VM scripts and the operator tooling for a fleet that already runs.

| Folder | What |
|---|---|
| `vm/storage/` | storage VM: partition the data / shared disks, export them over NFS (`create_disks_partitions.sh`, `storage_setup_nfs_server.sh`) |
| `vm/shared/` | any VM: prerequisites, NFS client mounts (`install_prerequisites.sh`, `mount_nfs_shared.sh`, `mount_nfs_data_shared.sh`) |
| `vm/runner/`, `vm/backend-host/` | CI runner VMs and host-VM validation helpers |
| `node/` | fleet operations from a jump host: `update_core.sh` (sync code + restart services on every VM), `deploy_customer.sh` / `build_customer_bundle.sh` (pinned platform + overlay deliveries, see `node/DEPLOY_CUSTOMER.md`), `reconcile_feature_units.sh` |
| `datacenter/scripts/` | Proxmox host prerequisites (`install_prerequisites_host.sh`: packages + SSH key) |

Every role installer lives in `setup/local/linux/<role>/` and is the same script whether the
role runs alone on a VM or all roles share one machine (`setup/local/linux/install_all.sh`).

There is **no VM-provisioning script yet**: VMs are created in the Proxmox UI and the
cross-VM values are copied by hand, exactly as `docs/get-started/proxmox.md` §Proxmox fleet
describes. Rebuilding this project's own node from backups is an internal runbook kept
outside the repository.
