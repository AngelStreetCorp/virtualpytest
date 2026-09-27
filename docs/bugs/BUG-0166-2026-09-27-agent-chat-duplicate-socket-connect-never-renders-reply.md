# BUG-0166 — The AI Agent chat never rendered its reply: the page's own duplicate CONNECTs killed the socket

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0166                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend / agent                                             |
| Fixed in  | Unreleased                                                   |
| Commit    | `bcd8e9c7d2`                                                  |

---

## Symptom

On `/ai-agent`, sending a prompt leaves the bubble on "Atlas ..." forever, while the server log
shows the agent working normally for that session — thinking, tool calls, the final message,
`session_ended`. Nothing of it reaches the page.

Socket.IO frames captured with Playwright on page load, all on ONE engine connection:

```
<- 40/agent,{"sid":...}                       handshake accepted
-> 42/agent,["join_session",...]  (several)
<- 44/agent,"Unable to connect"   (three times)
```

then, a couple of seconds later, the websocket closes and the console shows
`SocketContext: Connection error: Error` from `socket.io-client`'s `onpacket`. Reproduced both
with the auto-sign token and, on the production frontend, with a normally logged-in
(Supabase JWT) session — the mechanism is identical, only the timing decides whether a given
page load hits it.

## Root cause

Three things line up.

**The client sends more than one CONNECT.** `SocketContext.connect()` called `socket.connect()`
whenever the socket was not yet `connected`. Four consumers — `AIContext`,
`AgentActivityContext`, `useAIOrchestrator`, `useAgentChat` — call it during page load, while
the authenticated handshake (BUG-0156) is still pending on an async `auth` callback. In
`socket.io-client` 4.8.1 `connect()` is not idempotent in that window: with the engine already
open it calls `onopen()` again, which re-runs the `auth` callback and sends another CONNECT
packet on the same engine connection. Four `connect()` calls, four CONNECTs.

**The server refuses the duplicates.** python-socketio's `manager.connect(eio_sid, namespace)`
keeps a bidict from engine sid to namespace sid; a second CONNECT for a namespace the engine
connection already holds raises `ValueDuplicationError`, which `_handle_connect` answers with
`44 "Unable to connect"`. This is library behaviour, not our `connect` handler — the first
CONNECT was accepted.

**The client tears itself down on CONNECT_ERROR, half-way.** On packet `44` `socket.io-client`
calls `destroy()`: it drops every subscription the namespace socket had on its Manager (so it
will never see `close` or another packet) and closes the Manager when no other namespace is
active. `connected` stays `true` because the `disconnect` path was among the subscriptions
just removed. The app now holds a socket that reports connected, accepts `emit()` (into a closed
engine), and delivers nothing. The agent's reply is emitted to a room that socket is no longer
in.

Two smaller defects were hiding behind it:

- `socket.on('reconnect', …)` handlers in `SocketContext` and `useAgentChat` never fired —
  that event is emitted by the Manager, not the namespace socket — so per-conversation session
  rooms were never re-joined after any reconnect, and the chat stopped listening to the session
  its message was sent in.
- `initSession()` had no in-flight guard: `AIContext` and `useAgentChat` both called it before
  the first `POST /server/agent/sessions` answered, so every page load created three "shared"
  sessions.

## Fix

`frontend/src/contexts/SocketContext.tsx`, `frontend/src/utils/serverSocket.ts`,
`frontend/src/hooks/aiagent/useAgentChat.ts`:

- `connect()` is a no-op while the socket is `active` (connected **or** handshaking /
  reconnecting). Only a destroyed socket gets `socket.connect()`.
- `buildSocketAuth` delivers only the most recent auth resolution, so a reconnect during a
  slow token lookup cannot send a stale second CONNECT either.
- `connect_error` marks the socket dead and rebuilds it with backoff (1 s → 30 s), since the
  library never retries a refused namespace. The auth callback re-reads the token on each
  attempt, so a refusal caused by a not-yet-restored session heals by itself.
- `SocketContext` owns room membership (`joinSession`): the shared session, `background_tasks`
  and every per-conversation session are re-joined on each `connect`. The dead `reconnect`
  handlers are removed.
- `initSession` shares its in-flight request.

## Verification

`tests/e2e/playwright/specs/agent.socket.spec.js` captures both Engine.IO transports
(long-polling carries the first packets before the websocket upgrade) and asserts one CONNECT
per engine connection, no `44/agent` frame, and a rendered reply.

| | CONNECT sent | accepted | refused | reply |
|---|---|---|---|---|
| before | 4 | 1 | 3 | none in 2 min |
| after | 1 | 1 | 0 | rendered in 5 s |

A page load now creates one shared session. See BUG-0167 for a second, unrelated way the same
symptom appears (the server answers one conversation at a time).
