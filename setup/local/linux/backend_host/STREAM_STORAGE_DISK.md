# Stream Storage on the Wrong Disk (cold data on OS root)

**Symptom:** a capture host's stream/cold data tree (`/var/www/html/stream`) lives
on the small OS root disk while a large dedicated data disk sits empty and unused.

**Fix:** `setup/local/linux/backend_host/redirect_stream_to_data.sh` — repoints
`/var/www/html/stream` at `/data` via a symlink and rebuilds the RAM hot mounts.

---

## The issue

On some VM (and potentially other cloned hosts) the storage layout was:

| Path | Backing device | Size | State |
|------|----------------|------|-------|
| `/` (incl. `/var/www/html/stream`) | `/dev/sda1` (ext4) | 30 GB | **48% full** (14 GB used) |
| `/data` | `/dev/sdb1` (xfs) | 200 GB | **0% used — empty** |
| `sda2` | *(none — unformatted)* | — | exists, no filesystem, unmounted |
| swap | `/dev/sda5` | — | active |

`/var/www/html/stream` was a **plain directory on the 30 GB root**, not a symlink
or a separate mount. Hot storage (live frames) was correctly a tmpfs/RAM mount at
`…/<device>/hot`, but all **cold** data (captures, segments, metadata, audio,
rolling 24h hour-folders) accumulated on `sda1`.

Meanwhile the dedicated 200 GB data disk (`/dev/sdb1`, mounted `/data`) was completely empty.

> Note on naming: `/data` is backed by the **second physical disk `sdb1`**, not by
> `sda2`. `sda2` is a leftover empty/unformatted partition on the OS disk and is not
> used. The large, working data volume is `/data`.

## Root cause

The local install scripts **do not create a symlink** to relocate stream storage:

- `setup_permissions.sh` only `mkdir -p /var/www/html/stream` + chown — never symlinks.
- `setup_ram_hot_storage.sh` hardcodes `BASE_PATH=/var/www/html/stream`. It is
  **symlink-aware but not symlink-creating**: it calls `realpath` on the hot path so
  cold storage *can* live on another partition via a pre-existing symlink, then mounts
  tmpfs and writes `/etc/fstab` against the resolved real path. It assumes the symlink
  already exists.
- `install_host.sh` *does* contain symlink-creation code (keyed on a `HOST_DATA_DIR`
  env var), but it lives in the `else` fallback branch that only runs when
  `setup_ram_hot_storage.sh` is **absent** — which never happens, so it's dead code.

So redirecting stream → big disk has always been a **manual provisioning step**. On
this host it was never done: the second disk was attached and mounted at `/data` but
nothing pointed the stream tree at it.

## Why it matters

- The 30 GB root fills with disposable capture/segment data and competes with the OS,
  logs, and the venv for space → eventual disk-full, capture failures, and SD/disk wear.
- The 200 GB disk provisioned specifically for this data does nothing.
- Rolling 24h retention and longer KPI/segment history are constrained by the wrong
  (small) disk.

## The fix

Run on the host:

```bash
sudo chmod +x /opt/virtualpytest/setup/local/linux/backend_host/setup_ram_hot_storage.sh
sudo bash /opt/virtualpytest/setup/local/linux/backend_host/redirect_stream_to_data.sh
```
It:

1. Aborts unless `/data` is a mounted filesystem (never dumps onto root by accident).
2. Stops `vpt-stream`, `vpt-monitor`, `vpt-archiver`, `vpt-transcript`, `vpt-kpi`.
3. Unmounts the tmpfs hot mount(s) under `/var/www/html/stream`.
4. Deletes the old `/var/www/html/stream`, creates `/data/stream` (owned by
   `vpt_user`, mode 755), and symlinks `/var/www/html/stream → /data/stream`.
5. Re-runs `setup_ram_hot_storage.sh`, which resolves the symlink with `realpath`,
   recreates the full cold/hot directory tree on `/data`, remounts the RAM hot
   mounts at the new resolved path, and **rewrites the stale `/etc/fstab` entry**
   to the new path (so it survives reboot).
6. Restarts the services and prints verification.

The script is idempotent — re-running when the symlink already points at `/data`
just rebuilds the storage tree and mounts.

## Impact

| Aspect | Effect |
|--------|--------|
| **Data loss** | Existing `/var/www/html/stream` contents are deleted. This is disposable runtime capture data — acceptable. |
| **Downtime** | Brief: stream/monitor/archiver/transcript/kpi restart (seconds). Host API and VNC are untouched. |
| **Hot storage** | Unchanged in behaviour — still tmpfs/RAM (200 M per device), now resolving onto `/data/stream/<device>/hot`. |
| **fstab / reboot** | The tmpfs entry is rewritten to the resolved `/data` path and validated with `mount -a`; persists across reboot. |
| **App config** | No `.env` or code change. `/var/www/html/stream` path is unchanged from every service's and nginx's point of view (transparent symlink). |
| **Disk usage** | Cold data now grows on the 200 GB `/data` (`/dev/sdb1`); root (`sda1`) usage drops and stops growing. |
| **`sda2`** | Left untouched/unused. If you need data on `sda2` specifically, a different (format + mount) procedure is required. |

## Verify

```bash
ls -ld /var/www/html/stream                      # lrwxrwxrwx ... -> /data/stream
findmnt -T /var/www/html/stream                  # SOURCE = /dev/sdb1 (was /dev/sda1)
findmnt -T /var/www/html/stream/capture/hot      # FSTYPE tmpfs (RAM, unchanged)
grep stream /etc/fstab                            # tmpfs entry now under /data/stream/.../hot
df -h /data                                       # usage now grows here

symlink 
jndoye@host5:/$   ls -ld /var/www/html/stream
lrwxrwxrwx 1 root root 12 May 22 12:56 /var/www/html/stream -> /data/stream
```

## Rollback

The change is just a symlink + tmpfs remount; data is disposable. To revert to
root-disk storage: stop the services, `umount` the hot mounts, `rm /var/www/html/stream`
(removes the symlink only), `mkdir -p /var/www/html/stream`, then re-run
`setup_ram_hot_storage.sh`. The fstab entry will be rewritten back to the root path.
