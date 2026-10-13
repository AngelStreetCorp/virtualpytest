# BUG-0475 — /server/health takes 12-27 s when the Redis host is unreachable

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0475                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | shared (redis_queue) / backend_server (health route)         |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

`GET /server/health` answered in 12-20 s (once 60 s and a 500) while `/server/storage/health`
answered in under 0.4 s. The Cloudflare status worker probing it with an 8 s timeout reported the
origin down while the app was up.

## Root cause

The slowness was not in the route. From ~01:00 to 07:27 on 2026-10-12 the Redis/MinIO VM
(192.168.0.101) answered `Error 113 … No route to host` (vpt-server journal: 132 failed Redis
commands an hour). `health()` pings Redis through `RedisQueueProcessor.health_check()`, whose
client uses `socket_connect_timeout=5` and redis-py's default retry: since redis-py 6 a failed
connect is retried 3 times with backoff (server runs 7.4.0). Each attempt waited for ARP to give
up (~3 s) or the 5 s timeout, so one health call cost 4 attempts plus backoff: 12-27 s. Once
.101 came back the endpoint answered in 0.08 s.

## Fix

`health_check()` in local (`redis://`) mode pings through a one-shot client: same host/port/
password/db, 2 s connect and read timeout, `Retry(NoBackoff(), 0)`. Queue operations keep their
5 s timeout and default retries. The JSON returned by `/server/health` is unchanged; an
unreachable Redis now reads `"redis": "disconnected"` within ~2 s.

## Verification

- Unreachable host (`REDIS_URL=redis://10.255.255.1:6379`): `health_check()` 27.12 s before,
  2.08 s after, both returning false. Connection refused: 0.08 s.
- With Redis up: `curl -A Mozilla/5.0 https://virtualpytest.angelstreet.io/server/health`
  answers in ~0.1 s with `"redis": "connected"` (measured before the fix too, once .101 was back).

## Why Redis was unreachable

The storage VM 101 (Redis + MinIO) froze: its journal stops at 01:53:48 with no kernel, OOM or
I/O message, and the server's `No route to host` errors start at the same minute. It stayed
frozen until `qm reset 101` at 07:28:26. Cause of the freeze not found (no backup or qm command
near it; earlier freezes on this node were host RAM overcommit). Two follow-ups shipped:

- 101 crash-looped four stale units that can never start (`vpt_server`, `virtualpytest-vpt_host`
  need a local Supabase that is disabled; `virtualpytest-websockify` has no working dir;
  `virtualpytest-transcript` has no devices): ~20k restarts, ~100 MB journal per 3 h, a python
  process at 100 % CPU on a 2-core VM. Stopped and disabled 2026-10-12 (`systemctl enable --now`
  restores them).
- `infra/cloudflare/status-worker` now emails **DEGRADED** when `/server/health` answers 200 with
  `supabase` / `redis` not `connected`, without marking the origin down.
