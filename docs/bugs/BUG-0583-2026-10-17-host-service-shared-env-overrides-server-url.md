# BUG-0583 — `vpt-host` could not register when `/opt/virtualpytest/.env` had a backend-only `SERVER_URL`

## Summary
On a host box, the systemd unit `vpt-host.service` declared
`EnvironmentFile=-/opt/virtualpytest/.env`, which is the **backend's** env file
(it carries `SERVER_NAME`, `SERVER_URL`, `SERVER_PORT`, `SERVER_PUBLIC_URL`,
`FLASK_SECRET_KEY`, `MCP_SECRET_KEY`, …). systemd loaded that file first and
the values landed in the process environment; python-dotenv then loaded the
host's own `backend_host/src/.env` with `override=False`, so the systemd value
won. On `vpt-nipogi` the shared `.env` carried `SERVER_URL=http://127.0.0.1:5109`
(the backend host's address), so the host tried to register with itself,
got `Connection refused`, exhausted 8/8 retries, and silently dropped off the
dashboard. The 24 stream ffmpegs kept running locally, so the only symptom on
the dashboard was "vpt-nipogi missing from the host list".

## Repro
1. Provision a host (vpt-nipogi shape — Debian 13 on a home LAN).
2. Either rsync from vpt-pi4 or otherwise drop `/opt/virtualpytest/.env` on the
   host box (it carries vpt-pi4's `SERVER_URL=http://127.0.0.1:5109`).
3. Put the right value in `backend_host/src/.env`:
   `SERVER_URL=http://<host-server>:5109` (RPI4-server).
4. `sudo systemctl restart vpt-host` and tail the journal:
   ```
   ❌ [HOST:vpt-nipogi] Connection error: HTTPConnectionPool(host='127.0.0.1', port=5109): Max retries exceeded ... [Errno 111] Connection refused
   ❌ [HOST:vpt-nipogi] Registration failed after 8 attempts, will retry next ping cycle
   ```
5. `curl -H "X-API-Key: …" https://<host-server>/server/system/getAllHosts`
   shows no `vpt-nipogi` in the host list, even though
   `vpt-host.service` is `active (running)` and `ps` shows 23 capture ffmpegs.

## Root cause
`backend_host/config/services/linux/host.service` template had
`EnvironmentFile=-%PROJECT_ROOT%/.env`. That file is meaningful on the
backend host (vpt-pi4, where the backend actually runs and `127.0.0.1:5109` is
correct), but on a host box the same file (when present) carries backend-only
values that should not apply to the host. `python-dotenv` runs with
`override=False`, so once systemd has populated `os.environ` from the wrong
file, the host's own `backend_host/src/.env` cannot overwrite it.

`install_host.sh` does not create `/opt/virtualpytest/.env` — only
`backend_host/src/.env`. The stray file on `vpt-nipogi` arrived by rsync from
`vpt-pi4`; a fresh host install would not have triggered the bug, but any
host that ever received the shared `.env` from the backend (manually, via
sync, or by running an old `install_server.sh` that wrote to that path) would.

## Fix
- `backend_host/config/services/linux/host.service`: `EnvironmentFile=` now
  points at the host-specific file
  (`%PROJECT_ROOT%/backend_host/src/.env`), not the project-root shared
  `.env`. systemd populates the process env from the same file
  python-dotenv reads; `override=False` is still respected; the env is
  still inspectable via `systemctl show vpt-host`. The comment block
  now explains why this can't be `%PROJECT_ROOT%/.env` on a host.
- The shared `/opt/virtualpytest/.env` on `vpt-nipogi` was patched in
  place: `SERVER_NAME`, `SERVER_URL`, `SERVER_PORT`, `SERVER_PUBLIC_URL`
  are commented out so they cannot leak back via the legacy
  `EnvironmentFile=` line before the template is rolled out
  (`/opt/virtualpytest/.env.bak.<ts>.pre-hostfix` left on disk).
- `vpt-host` re-registered at 10:25 CEST (PID 59686, replacing the stale
  PID 3546171 that had been retrying against `127.0.0.1`).
  `getAllHosts` now lists `vpt-nipogi` (25 devices, `online`).

## How to roll out to other hosts
After the template ships, every host's `vpt-host.service` will be regenerated
the next time `setup/local/linux/backend_host/install_host.sh` runs (or
`install_service.sh host` runs on the host). On hosts that already have a
stale `/opt/virtualpytest/.env` left over from a sync, no further action is
needed — the systemd unit no longer reads it. Hosts that depend on
`/opt/virtualpytest/.env` for OTHER reasons (ad-hoc scripts, the vpt-stream /
vpt-monitor units that share the same pattern) still read it via their own
units; those are not affected by this change.

## Verify
- `curl -sS -H "X-API-Key: <key>" https://<host-server>/server/system/getAllHosts`
  lists `vpt-nipogi` with `device_count=25`, `status=online`.
- `ssh vpt-nipogi sudo journalctl -u vpt-host --since '5 minutes ago'` shows
  `✅ [HOST] Registration successful!` and the periodic
  `📡 [HOST] Ping sent successfully at HH:MM:SS`.
- `ssh vpt-nipogi sudo grep -E '^SERVER_URL' /proc/$(pgrep -f 'python app.py')/environ`
  shows `SERVER_URL=http://<host-server>:5109` (RPI4-server), not
  `127.0.0.1:5109`.