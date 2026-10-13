# BUG-0401 — Agent Chat send hung forever when the server accepts the request but never answers

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0401                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend (useAgentChat) + backend_server (send_message)      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Post-deploy suite, Pi server, fresh New Chat: prompt typed + Enter. For 240 s the text stayed in the
input, no "Reconnecting…", no error, no bubble, no `send_message` frame. The Pi's vpt-server was
mid-restart with its stop hung (`State 'stop-sigterm' timed out`), so TCP connections were accepted but
never answered. The same send 25 s later worked.

## Root cause

`sendMessage` creates the conversation's backend session with `await fetch(POST /server/agent/sessions)`
and no timeout. A refused connection rejects and feeds the BUG-0340 retry/error UI; a connection that is
accepted and never answered never settles, so the send path stopped before any visible state was set.
A second Enter started a parallel session-create. Separately, the no-ack watchdog resent silently and the
server had no idempotency key.

## Fix

`useAgentChat.ts`: each session-create try is bounded (10 s, AbortController + race); "Reconnecting…" shows
after 3 s of a slow try and between retries; tries repeat with capped backoff inside the existing 60 s
budget, then "Unable to reach the server. Your message was not sent" with the text kept; a second Enter
during the step is ignored. The 4 s no-ack watchdog now shows "Waiting for the server…" (cleared on the
first event). Every send carries `client_msg_id`, reused by the watchdog resend;
`server_agent_routes.py` processes each (session, id) once (5 min memory) and just re-acks a duplicate.

## Verification

`tests/frontend/useAgentChatSendReconnect.test.tsx` (hung fetch: notice < 3.5 s, error after budget,
single delivery after recovery, silent socket: notice + same id on resend). E2E
`E2E_ONLY=outage-hang bash scripts/atlas_analytics_e2e.sh` (check "BUG-0401 send while session create hangs
shows Reconnecting and delivers"): FAILS on bundle main-2026.10.05-9999, must PASS after deploy.
