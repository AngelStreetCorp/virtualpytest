# BUG-0478 — Dashboard shows a Windows host as "Linux (x86_64)"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0478                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | infra / deployment · dashboard host card                    |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On the Dashboard (`https://virtualpytest.angelstreet.io/`), the host card for **`vpt-windows`**
renders its System Stats header as **"Linux (x86_64)"**, although the physical machine is a
Windows PC (`192.168.1.70`, login user `pcuser` — the WoL/LM-Studio box described in
`docs/agent/devices/WAKE_ON_LAN.md`).

Two corroborating oddities on the same card, both impossible on a native Windows host:

- **Load: 0.4** — `os.getloadavg()` does not exist on Windows; `_get_load_average()` falls
  through to `(0.0, 0.0, 0.0)` there (`shared/src/lib/utils/system_monitoring_utils.py:16-37`).
- **Disk: 2%** of a ~1 TB filesystem (`use_pct 2.0`, `size 1081101176832`) — a Windows `C:`
  drive would not sit at 2%.

Card is also `degraded`.

## Root cause

**Not a display bug — the label is truthful about what is running.** The vpt-host process
behind the name `vpt-windows` is a **Linux container**, not a native Windows service.

Evidence gathered 2026-10-12:

1. **The frontend just renders what the host reports.** `frontend/src/pages/Dashboard.tsx:1173`
   is `{host.system_stats?.platform} ({host.system_stats?.architecture})` — no mapping, no
   default, no client-side OS inference.

2. **The host fills those fields from its own runtime**, not from the host *name*:
   `backend_host/src/lib/utils/system_info_utils.py:1076` and `:1080-1082`
   ```python
   'platform': platform.system(),
   'platform_distribution': get_platform_distribution(),
   'architecture': platform.machine(),
   ```

3. **The data is live, not stale.** All 680 `system_metrics` samples for `vpt-windows`
   (window `2026-10-11T17:12Z` → `2026-10-12T05:34Z`, i.e. the present) carry
   `platform=Linux`, `architecture=x86_64`. The host has **never once** reported `Windows`.

4. **The decisive evidence — it is a Docker container.** `GET /host/system/checkStorage`
   against `http://192.168.1.70:6109` returns:
   ```json
   {"host":"8e20da5d30d8","rows":[{"filesystem":"root","mountpoint":"/",
     "size":1081101176832,"use_pct":2.0,"used":21270036480}],"success":true}
   ```
   `8e20da5d30d8` is a **Docker container ID**, and the response took the **POSIX branch** of
   `check_storage()` (`shutil.disk_usage('/')`, one `root` row) instead of the Windows branch
   that walks `C:`..`Z:` (`backend_host/src/routes/host_system_routes.py:1391-1412`).
   `platform.node()` returning the container ID is the same story.

5. The deployment is reachable only over the **container** port `6109`; SSH to
   `192.168.1.70:22` times out from both the Mac and vpt-pi4, so the Windows OpenSSH server is
   not currently serving the VPT role either.

So: the physical box is Windows, but `vpt-host` runs Linux — almost certainly the Docker
path (`setup/docker/docker-compose.host.yml`, `HOST_NAME` set to `vpt-windows`). Under Docker
Desktop on Windows the containers run in a Linux VM/WSL2 kernel, so `platform.system()`
correctly returns `Linux` and `platform.machine()` correctly returns `x86_64`. Every Linux-only
metric (load average, POSIX `/` mount, `root` filesystem) is consistent with that, and none of
them can be produced by a native Windows Python process.

The name `vpt-windows` is a *logical* label: `HOST_NAME` is an arbitrary operator-set string
(`backend_host/src/app.py:442`, `.env`), completely independent of the OS underneath. Nothing
in the stack cross-checks it against `platform.system()`, so the mismatch is silent.

## Fix

**Shipped (code).** The card now separates *what vpt-host runs on* from *the machine
underneath*, so a Windows PC running Docker reads as "Docker · Windows (x86_64)" instead
of a bare, misleading "Linux (x86_64)".

- `backend_host/src/lib/utils/system_info_utils.py` — new `detect_container_runtime()`,
  `_detect_wsl()` and `get_physical_platform()`. The result is merged into both
  `get_host_system_stats()` and `get_enhanced_system_stats()`, so it rides the existing
  ping payload — **no DB migration and no schema change**: the dashboard card reads the
  live `system_stats` from the host ping (`backend_host/src/lib/utils/host_utils.py:679`),
  not from the `system_metrics` table. New keys: `in_container`, `container_runtime`,
  `is_wsl`, `physical_platform`, `os_mismatch`.
- `frontend/src/pages/Dashboard.tsx` — new `PlatformLabel` component replaces the inline
  `{platform} ({architecture})` caption. Bare-metal hosts render exactly as before; a
  containerised host gains an outlined runtime chip plus a tooltip explaining the
  mismatch.
- `frontend/src/types/pages/Dashboard_Types.ts` — the five keys typed as optional, so a
  host that has not re-registered yet falls back cleanly.
- `frontend/src/i18n/locales/{fr,de}.json` — 5 new tooltip keys each (`i18n-check` exits 0).

**Deliberately not guessed:** `physical_platform` is only ever set to `Windows` on positive
evidence of the WSL2 kernel (`platform.release()` / `/proc/sys/kernel/osrelease` /
`/proc/version` carrying `microsoft` or `wsl`). A hostname is never used to infer an OS —
`HOST_NAME` is an unconstrained operator label, which is exactly why this bug existed.

**Still worth doing operationally** (config, not code):

**A. If a containerised host is intended** (recommended if that is how the box is deployed):
rename it so the name stops contradicting the OS, e.g. `HOST_NAME=vpt-windows-docker`
in `setup/docker/.env`.

**B. If a native Windows host was intended** (needed for real Windows device control — USB
passthrough, TightVNC, NSSM services): the host must be (re)installed with
`setup/local/windows/backend_host/install_host_windows.ps1`, which registers `vpt-host` as a
Scheduled Task and services under NSSM. Then the card drops the Docker chip and shows
`Windows (AMD64)`, and the Windows-specific service logic in `system_info_utils.py`
(`_check_windows_service`, `_check_windows_scheduled_task`, `WINDOWS_SERVICE_ALIASES` for
TightVNC `tvnserver`) actually engages — today that whole code path is unreachable on this
host because the container never reports `Windows`.

## Verification

Unit tests — `tests/backend_host/test_platform_container_detection.py`, 11 cases, all
passing: bare-metal Linux unchanged; Docker-on-Windows reports `physical_platform=Windows`
+ `os_mismatch=True`; Docker-on-Linux raises **no** mismatch; native Windows is not a
container; container detection falls back to cgroup markers (`kubepods`/`docker`/
`containerd`/`lxc`) and reads `None` on a plain systemd cgroup; WSL detected from
`/proc/version` when `platform.release()` lacks the marker; and a `HOST_NAME=vpt-windows`
box with no WSL evidence is **not** claimed to be Windows.

```bash
pytest tests/backend_host/test_platform_container_detection.py -q     # 11 passed
cd frontend && ./node_modules/.bin/tsc --noEmit                       # exit 0
cd frontend && node scripts/i18n-check.mjs                            # 0 errors
```

Rendered states verified in dark mode: Docker-on-Windows shows the chip + `Windows
(x86_64)`; bare-metal Linux is byte-identical to the current UI; Docker-on-Linux shows the
chip but no mismatch claim; native Windows shows `Windows (AMD64)` with no chip.

End-to-end after deploy (the card updates on the next host ping, ≤60s):

```bash
# the host itself now reports the machine underneath
curl -s -H "X-API-Key: $API_KEY" http://192.168.1.70:6109/host/system/checkStorage
# still a POSIX "/" row + container-id hostname == still the Docker path
```