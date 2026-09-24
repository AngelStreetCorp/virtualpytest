# BUG-0156 — Socket.IO accepted any client, on every namespace

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0156                                                     |
| Reported  | 2026-09-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / frontend / security                                |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

`/server/*` has been closed by default since the server lockdown, but **Socket.IO was not behind
that gate at all**. Its handshake is served at `/socket.io/`, which does not start with
`/server/`, so the global guard in `app.py` — user auth, the viewer read-only floor, team scoping
— never ran for a socket connection.

Every namespace accepted every client, with no credential of any kind:

| Namespace | What it exposed |
|-----------|-----------------|
| `/agent` | `send_message`, `approve`, `stop_generation`, `clear_session`, `join_session` |
| `/system` | live fleet state — hosts, devices, lock ownership, deployment progress |
| `/` (default) | `task_complete` from browser automation |

Worse than reading: `join_session` took a `session_id` straight off the wire and joined that
room unchecked. The room *is* the delivery channel for a conversation, so an unauthenticated
client that guessed or learned a session id received that conversation's entire event stream —
prompts, tool calls, results — and could drive it: send messages as that user, approve a pending
action the agent was waiting on, or clear the history.

The default namespace was open for a quieter reason: it has no handlers of its own, and
Socket.IO accepts every client to a namespace with no `connect` handler registered. It is not
idle, though — `server_web_routes.task_complete` emits there.

## Root cause

Two separate gaps that look like one.

**The guard is path-scoped.** `_global_frontend_auth_guard` returns early unless
`request.path.startswith('/server/')`. That is correct for what it was written to do and simply
never covered the socket handshake. The frontend has been *sending* a token on `/agent` since
TASK-18 (`io(url, { auth: { token } })`) — nothing on the server ever read it, so the credential
was present and ignored, which is the kind of gap that survives review: the client code looks
authenticated.

**Rooms were never authorization.** Session rooms were introduced to deliver events to the right
tab, and `join_session` treated the id as addressing rather than as a claim. Sessions carried no
owner, so there was nothing to check even if someone had wanted to.

## Fix

**`authorize_socket_connection(auth)`** in `auth_middleware.py` decides the handshake and mirrors
the HTTP posture axis for axis, so a deployment cannot be closed over HTTP and open over
WebSocket:

```
X-API-Key (header) → auto-sign → open mode → user JWT → SERVER_PUBLIC_KEY → refuse
```

Returning `None` makes the connect handler return `False`; the client gets a `connect_error`
rather than a half-open socket. `/agent`, `/system` and the default namespace all call it.

A browser WebSocket cannot set headers, so credentials travel in the handshake `auth` payload —
`{ token, server_key, auto_sign }` — mirroring what `installFetchAuth.ts` puts on every HTTP
request. Headers are still honoured for python-socketio and CI clients.

**`backend_server/src/lib/socket_auth.py`** keeps `sid → principal`: the flask request context
ends with the handshake, so later events need the principal remembered. Populated on connect,
released on disconnect.

**Session ownership.** `POST /server/agent/sessions` records `owner_user_id`, and
`_may_use_session()` gates `join_session`, `send_message`, `approve`, `stop_generation` and
`clear_session`. It falls back to "any authenticated caller" for a shared principal (service key,
open mode, auto-sign, public key — everyone has the same id there), for a session with no
recorded owner (sessions are in-memory and predate the field, so refusing them would break every
conversation open at deploy time), and for an unknown id (the handlers answer their own "not
found").

**`frontend/src/utils/serverSocket.ts`** — `createServerSocket(base, namespace, options)` is now
the only way the app opens a socket. `/system` had nine call sites and none sent anything;
`/agent` sent a token but not the server key or auto-sign token, which matters on deployments
without Supabase. `scripts/atlas_chat.py` sends its service key on connect for the same reason.

## Verification

```bash
python3 -m pytest tests/backend_server/test_socket_auth.py -q   # 29 passed
python3 -m pytest tests/backend_server -q -m unit                # 152 passed
cd frontend && ./node_modules/.bin/tsc --noEmit && npm run lint  # clean
```

`test_socket_auth.py` runs offline and covers the handshake decision on every posture, that
claims are read from `app_metadata` only, the connection registry, session ownership, and — with
a real `flask_socketio.test_client` — that `/system` and the default namespace actually refuse an
unauthenticated connect and admit a valid token.

**Not verified against a running deployment.** This changes how every browser tab connects, so it
needs a deploy to debug and a browser pass over agent chat, Run Tests and the dashboard before it
goes near production.

## Upgrade

Server and frontend together — the server starts refusing sockets that the old bundle does not
credential. A stale cached bundle will fail to connect (visible as `connect_error` in the
console) until it is reloaded.

Nothing to configure: the credentials are the ones the frontend already sends over HTTP.
