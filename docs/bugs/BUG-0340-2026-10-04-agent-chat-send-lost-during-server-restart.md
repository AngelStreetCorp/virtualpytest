# BUG-0340 — Agent Chat message sent while the server restarts is silently lost

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0340                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Seen live on the Pi server (production bundle): after "New Chat", the user typed a prompt and pressed Enter at the second the backend restarted (deploy). The text stayed in the input, no bubble, no error, no spinner; nothing happened for 4 minutes.

## Root cause

`sendMessage` in `useAgentChat.ts` had two silent drop paths during a restart:

1. Socket (or session id) not ready: it retried via `setTimeout(() => sendMessage(...))` — a callback closing over the render's stale `socket`/`isConnected`, so it could never observe the reconnect. After 3 retries (~3.5 s) it set a one-shot error that is cleared by the next state reset; the text was never delivered.
2. REST `POST /server/agent/sessions` failing was only `console.warn`ed and fell back to the shared session (unknown to the freshly restarted server), after the user bubble and pending state were already set.

Neither surfaced a durable visible state, and the input text was only cleared late, so the user saw nothing happen.

## Fix

`frontend/src/hooks/aiagent/useAgentChat.ts`: while the socket/session is down, show "Reconnecting to the server…", keep the text, and poll every 1 s through a ref to the latest `sendMessage` for up to 60 s, then show a visible "not sent" error (text kept). Session creation is retried (4 attempts, 1/2/4 s backoff) before the bubble is added; if it still fails a visible error is shown and nothing is sent or cleared.

## Verification

`tests/frontend/useAgentChatSendReconnect.test.tsx` (delivery after reconnect, 60 s timeout error, session-create failure keeps text and adds no bubble); `useAgentChatErrors`, `AgentChat`, `analyticsMerge` still pass; `tsc --noEmit` clean.
