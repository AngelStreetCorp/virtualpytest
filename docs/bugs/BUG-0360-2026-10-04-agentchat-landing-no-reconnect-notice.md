# BUG-0360 — New-chat landing view shows no "Reconnecting…" / error notice

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0360                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | d5450d284                                                          |

---

## Symptom

On /ai-agent, from a new empty chat (centered "AI Agent" title + input), sending a message while
the server is unreachable showed nothing. The message was delivered after the outage (BUG-0340),
but the user got no "Reconnecting to the server…" feedback. Same for "Could not start the chat
session…" and "Unable to reach the server…".

## Root cause

`error` was rendered only in the thread view (`ChatMessages.tsx`); the landing view
(`renderEmptyState` in `pages/AgentChat.tsx`) never rendered it. The mobile chat already did.

## Fix

New shared `components/agent-chat/AgentChatErrorAlert.tsx`, used by the thread view and the
landing view. Regression test in `tests/frontend/AgentChat.test.tsx`.

## Verification

vitest AgentChat / useAgentChatSendReconnect / HealthRetry / Errors pass; `tsc --noEmit` clean.
