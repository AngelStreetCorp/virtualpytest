# BUG-0283 — Hosts logged "Added to analysis queue" for alerts that Redis had refused

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0283                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — misleading log; no alert analysis was lost (see Root cause) |
| Area      | `shared/src/lib/database/alerts_db.py`, `shared/src/lib/database/script_results_db.py`, `docs/agent/ai/agent.md` |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On vpt-pi4 every alert created by vpt-monitor logged:

```
[@redis_queue] Local Redis command failed: Error 111 connecting to localhost:6379. Connection refused.
[@redis_queue] Failed to add alert <uuid> to queue
[@db:alerts:create_alert] Added to analysis queue: <uuid>
```

The alert was in the DB, but the last line said it had been queued when it had not.

## Root cause

1. **The log.** `create_alert` (and `update_script_execution_result`) ignored the boolean returned by
   `add_alert_to_queue` / `add_script_to_queue` and always printed "Added to analysis queue".
   `RedisQueueProcessor` catches the connection error and returns `False`, so the `except` branch
   that prints the warning never ran.
2. **Where the alert should go.** The producer is every host (`alerts_db.create_alert` → `LPUSH p1_alerts`
   on whatever `REDIS_URL` the host's `.env` names). The template `.env.example` defaults to
   `redis://...@localhost:6379`, which is only right on the machine that runs `install_redis.sh`
   (the storage VM). Fleet survey 2026-10-04:

   | Host | redis-server | REDIS_URL | Result |
   |------|--------------|-----------|--------|
   | vpt-pi4 | not installed | localhost | Connection refused on every alert; storage Redis not reachable from its LAN |
   | vpt-pi1 | installed, local | localhost | Queued into its own Redis (30 items), which nothing reads |
   | vpt-pi3 | not installed | its site server | Timeout connecting |
   | vpt-nipogi | not installed | unset | "Redis configuration missing" |
   | host-clone-1/3, labox-web/backend/dongle/mobile | not installed | storage VM | Queued OK |

3. **There is no consumer.** `p1_alerts` on the storage VM held 884 items dating back to 2026-08-20.
   `vpt-discard-incidents` is installed **disabled** by `install_server.sh` (disabled on the server
   too), and its entry point `backend_server/scripts/discard_worker.py` starts the analyzer on
   `p2_scripts` only. Nightwatch's `monitor.yaml` has no `background_queues`. So the queue is a
   capped backlog (`MAX_QUEUED_PER_DEVICE = 5`), and vpt-pi4's failed enqueues lost no analysis.
   `docs/agent/ai/agent.md` claimed `vpt-discard-incidents` triaged all alerts via `p1_alerts`.

Installing Redis on vpt-pi4 was not done: a local Redis there (as on vpt-pi1) would only grow a
second unread queue.

## Fix

- `create_alert` and `update_script_execution_result` log "Added to analysis queue" only when the
  enqueue returned `True`; otherwise "Warning: NOT added to analysis queue (Redis unreachable?)".
- `docs/agent/ai/agent.md` states that nothing consumes `p1_alerts` today.

Open decision (resolved by [BUG-0299](BUG-0299-2026-10-04-alerts-queued-to-redis-with-no-consumer.md): hosts no longer queue alerts; the triage worker polls the alerts table): either wire a real `p1_alerts` consumer (enable an incidents worker
that runs the monitor agent on `p1_alerts`) and give remote-LAN hosts a reachable Redis, or stop
enqueueing alerts.

## Verification

- Stubbed `create_alert` with a queue processor returning `False` then `True`: the first logs the
  NOT-added warning, the second "Added to analysis queue".
- Fleet survey above: `journalctl -u vpt-monitor --since -2h` per host, `systemctl is-active
  redis-server`, `REDIS_URL` from `/opt/virtualpytest/.env`, `LLEN p1_alerts` on the storage VM via
  the server's `.env`.
