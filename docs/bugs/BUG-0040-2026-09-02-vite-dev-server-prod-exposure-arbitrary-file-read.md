# BUG-0040 — Production frontend served by an internet-exposed Vite dev server; `fs.strict:false` gave arbitrary file read

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|------------------------------------------------------------------------|
| ID        | BUG-0040                                                              |
| Reported  | 2026-09-02                                                            |
| Status    | Fixed (deployed)                                                      |
| Severity  | Critical (unauthenticated arbitrary file read on the internet-facing frontend; auto-sign auth-bypass token lived in a readable path one guess away) |
| Area      | `frontend/vite.config.ts`, `frontend/config/services/linux/frontend*.service`, proxmox `~/update_core.sh`, `proxy` VM nginx, Proxmox VMID 105 |
| Fixed in  | build 8713                                                            |
| Commit    | `92c933fa2` `6790814c4`                                               |

---

## Symptom

A VNC session onto `host-clone-1` (a CI VM) showed a Vite HMR error overlay on
`virtualpytest.angelstreet.io` reading `/etc/services` back as if it were a JS module
(`[plugin:vite:import-analysis] Failed to parse source... File: /etc/services??inline=1.wasm?init`).
Initial assumption was a CI runner artifact; it was not — the production frontend was actually
being attacked.

## Root cause

Three compounding issues:

1. **Production frontend ran `npm run dev`, not a build.** `vpt-frontend.service` on the
   `frontend` VM (192.168.x.105) ran the raw Vite dev server as the internet-facing web server.
   The repo already had a correct build+serve unit
   (`frontend/config/services/linux/frontend_prod.service`, installed by `install_frontend.sh`
   as `vpt-frontend-prod.service`) — it just wasn't the one deployed. `update_core.sh` on
   proxmox also targeted the dev-mode unit name.
2. **`server.fs.strict: false`** in `vite.config.ts` disabled Vite's dev-server filesystem
   sandbox, letting a crafted request (`?inline=1.wasm?init`, `?raw??`, etc.) read any file on
   disk the process could read, through the module-transform pipeline.
3. **Origin reachable outside Cloudflare.** `virtualpytest.angelstreet.io` resolves to
   Cloudflare's edge, but nginx on the `proxy` VM was `listen 443 ssl default_server` with
   `server_name <origin-ip> virtualpytest.angelstreet.io` — i.e. it answered for *any* Host
   header hit on the bare Hetzner IP too, which is continuously mass-scanned regardless of DNS.
   Whatever IP protection existed at Cloudflare never saw that traffic.

`journalctl -u vpt-frontend` over the prior ~36h showed an automated scanner probing
`/proc/1/environ`, `/.env`, `.env.local`, `.env.production`, `~/.ssh/id_rsa`, `~/.aws/credentials`,
and successfully reading `/etc/services` (its content leaked back in the transform error — the
exact request the VNC session's browser rendered). None of the guessed secret paths matched the
real one — `/opt/virtualpytest/frontend/.env`, which exists, is world-readable, and contains
`VITE_AUTO_SIGN_TOKEN` with `VITE_AUTO_SIGN_ENABLED=true` (a full auth-bypass to admin per
`AUTO_SIGN_ROLE=admin`, see `docs/agent/infra/CICD.md`). It was one correct guess away —
the attacker just hadn't tried the process's own working directory yet.

## Fix

1. **`vite.config.ts`**: `fs.strict` restored to `true` (Vite's default) — commit `92c933fa2`.
2. **Switched production to the build+serve service.** Installed and enabled
   `vpt-frontend-prod.service` (`npm run build` → `serve -s dist`) on the `frontend` VM;
   stopped and disabled the dev-mode `vpt-frontend.service`.
3. **Fixed a build-time OOM** hit switching to the real build: `vite build`'s post-bundle
   gzip-size reporting on this app's ~2.5MB unsplit main chunk peaked around 1.24GB RSS and
   OOM-crashed against the VM's original 2GB. Added `NODE_OPTIONS=--max-old-space-size=1536` to
   `frontend_prod.service` — commit `6790814c4`.
4. **`update_core.sh`** on proxmox (not in git): `FRONTEND_SERVICE` now points at
   `vpt-frontend-prod.service` so future `--frontend` deploys restart the right unit.
5. **nginx origin restricted to Cloudflare + LAN.** Added
   `/etc/nginx/snippets/cloudflare-only.conf` (Cloudflare's published IPv4/IPv6 ranges +
   `127.0.0.1` + `192.168.x.0/16`, `deny all`) and `include`d it in the `443 default_server`
   and `8080` (openclaw/rival) blocks of `/etc/nginx/sites-enabled/virtualpytest`; also dropped
   the bare `<origin-ip>` from `server_name` on both (cosmetic — `default_server` is what
   actually made it a catch-all, the `allow`/`deny` is the real fix). Not tracked in git; edited
   directly on the `proxy` VM. Note: `sites-available/virtualpytest` on the same VM is a stale,
   long-abandoned copy — the live, hand-maintained file is `sites-enabled/virtualpytest`; don't
   edit the former expecting it to take effect.
6. **Proxmox VMID 105 (frontend) memory 2048 → 4096MB.** Measured build peak (1.24GB RSS,
   system free memory bottomed at 108MB) left too little margin on the original 2GB allocation.
   Required a VM stop/start (no memory hotplug configured); frontend was briefly down during the
   restart.

## Verification

- `curl https://virtualpytest.angelstreet.io/` → 200 (via Cloudflare).
- `curl https://<origin-ip>/ -H "Host: virtualpytest.angelstreet.io"` → 403 (direct-IP,
  bypassing Cloudflare, now blocked at nginx).
- Same probe path that leaked `/etc/services` now returns the SPA's `index.html` (200) — no
  dev-server transform pipeline is running in production to exploit.
- Clean rebuild (`rm -rf dist && systemctl restart vpt-frontend-prod.service`) succeeds in one
  shot post-fix (previously needed a lucky `Restart=on-failure` retry that skipped rebuilding
  because a prior `dist/` already existed).
- Post-RAM-bump: VM boots on 4096MB, `vpt-frontend-prod.service` builds and starts cleanly
  unattended, site serves 200.

## Not yet done

- `VITE_AUTO_SIGN_TOKEN` / `AUTO_SIGN_TOKEN` were not rotated — the file was world-readable for
  ~36h of active scanning, though no log evidence shows it was actually read (all guessed paths
  missed it). Worth rotating out of caution.
- The frontend bundle itself still produces one ~2.5MB unsplit `main-*.js` chunk (Vite's own
  build warning: "Some chunks are larger than 500 kB... consider dynamic import() or
  manualChunks"). Splitting it would reduce build memory pressure independent of the VM RAM bump
  and is a legitimate follow-up, not addressed here.
- `docs/agent/infra/CICD.md` / `DEPLOY.md` don't yet document the `vpt-frontend-prod.service`
  cutover or the nginx Cloudflare-only restriction — worth a follow-up doc pass.

## Related

- `docs/agent/infra/CICD.md` — `AUTO_SIGN_TOKEN` / `AUTO_SIGN_ENABLED` auth-bypass mechanism.
