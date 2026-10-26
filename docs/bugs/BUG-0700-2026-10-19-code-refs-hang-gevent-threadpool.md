# BUG-0700 — code_refs calls hang on the server when the index is built off the event loop

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0700                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | code-graph / MCP `code_refs`                                 |
| Fixed in  | — (internal)                                                 |
| Commit    | `74691b118`                                                  |

---

## Symptom

After the deploys of `4099687cd` (threadpool build) and `b2a303ad7` (child-process build), every `code_refs` call
through `/server/mcp` on node1 waited until the client gave up (Cloudflare 524 after 125 s; `localhost:5109` also hung).
The rest of the server answered normally (`/server/health` ≈ 0.1 s), the serving process sat at ~5 % CPU, and no build
was running: no busy thread in a `py-spy dump`, no child process under the server. systemd also needed its stop timeout
to restart the service once.

## Root cause

Both designs moved the build out of the request greenlet and then waited for a wake-up from outside the greenlet
world: gevent's threadpool result in `4099687cd`, a child-process exit in `b2a303ad7`. The warm-up greenlet, started
from the tool's constructor at import, took the store lock and parked on that wake-up, which never arrived inside the
app; every later call queued on the lock. The same code built the index in 17 s standalone with the server's venv. The
server is a reloader-style pair (parent monitor + serving child sharing the socket) that also starts subprocesses at
boot (speedtest); which part swallows the wake-up was not pinned down (greenlet stacks are not visible to `py-spy`).

## Fix

`features/code-graph/lib/code_index/store.py`: under gevent the build runs in the calling greenlet and
`build_index(repo, pause=...)` yields every 20 files with `gevent.sleep(0.001)` (a real timer: `sleep(0)` does not let
the loop poll sockets). Nothing waits on a thread or a process, so there is no wake-up to lose. The background warm-up
starts 30 s after boot with `gevent.spawn_later`.

## Verification

- Local, gevent-patched process: 28 s build, longest event-loop gap 0.77 s over 113 ticks of 100 ms.
- node1 after deploy: `code_refs` answers via `/server/mcp`; `/server/health` stays ≈ 0.1 s during the warm-up.
