# BUG-0511 — A Tello take-off, move or pairing link froze the whole vpt-host while it waited

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0511                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / drone                                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

While a Tello command waited for the drone, every other request on that host stopped: stream
tiles went black, playlists stalled and Cloudflare answered 524 (seen on vpt-pi4, 2026-10-13).
A take-off or land to a drone that does not answer waits 2 × 20 s (plus the forced land after it),
a move 2 × 10 s, and the pair route's `link` step up to ~4 s + 3 s + 1.5 s — the host was frozen
for all of it.

## Root cause

vpt-host serves Flask-SocketIO with `async_mode='gevent'` but **without** `gevent.monkey`
(`shared/src/lib/utils/app_utils.py`, `backend_host/src/app.py` `socketio.run`). Every request is a
greenlet on the main thread, and a plain blocking `socket.recv` inside one never yields to the hub.
[BUG-0506](BUG-0506-2026-10-13-tello-takeoff-timeout-wrong-source-port.md) moved the telemetry
reads off the request path; `TelloRemoteController._send_guarded` → `TelloClient.send` (flight
commands) and `execute_command('link')` (POST `/host/drone/tello/pair`) still waited on the request
greenlet. A read could also block: `get_telemetry` took the controller lock, so it waited behind a
command holding it.

## Fix

`backend_host/src/controllers/remote/tello.py`:
- `_off_hub(fn, *args)`: on the hub's thread (the vpt-host request path) the command runs in an OS
  thread of the hub's threadpool (`hub.threadpool.apply`) and the greenlet waits cooperatively;
  anywhere else (script process, background link thread) it runs inline. The app is not
  monkey-patched — nothing else changes behaviour.
- `execute_command` and `disconnect` (lands an airborne drone) go through `_off_hub`.
- `get_telemetry` reads without the lock, so it never waits behind a command.
- `rc` waits at most 0.5 s for the lock (another rc frame) and is otherwise dropped as `busy`
  instead of queueing stale stick values behind a take-off. The tile already drops failed frames.

## Verification

`tests/drone/test_tello_gevent_hub.py` (codebox, Linux loopback): a take-off to a drone that
stopped answering, and a pairing link to nothing, run in a greenlet while
`/host/drone/tello/status` is called — it answers in < 0.5 s while the command is still waiting.
The same tests fail against the previous controller (the command finishes before status runs).
Measured: a take-off waiting out 12 s of timeouts, 236 status calls in that window, worst 0.5 ms.
