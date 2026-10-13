# BUG-0350 — Agent Chat stayed broken after a server restart until the page was refreshed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0350                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium - page unusable until a manual refresh                |
| Area      | `frontend/src/hooks/aiagent/useAgentChat.ts`                 |
| Fixed in  | Unreleased                                                   |
| Commit    | 1176421ef                                                          |

---

## Symptom

Opening `/ai-agent` while the backend server is down (restarting during a deploy, 10-60 s) left the page in status
`error` ("Backend unavailable"). It stayed that way after the server came back; only a refresh recovered it.

## Root cause

The mount-time `/server/agent/health` check ran exactly once and set `error` on any failure.

## Fix

The check now retries with bounded backoff (1, 2, 4, 8, then 15 s) for as long as the page is mounted. While retrying, status
stays `checking` and the notice reads "Reconnecting to the server…" (same wording as the BUG-0340 send wait). A success
clears the notice and goes to `ready` (or `needs_key`) without a refresh; a SocketContext reconnect triggers an immediate
retry. A 401 is still final (a credential problem, not an outage). The retry timer is cleared on unmount.
Tests: `tests/frontend/useAgentChatHealthRetry.test.tsx`.
