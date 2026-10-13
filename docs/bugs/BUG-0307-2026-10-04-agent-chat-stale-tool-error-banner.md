# BUG-0307 — Agent chat kept the error banner of an earlier failed tool call after a successful answer

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0307                                                     |
| Reported  | 2026-10-04 (TASK-43 real-browser test)                       |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — cosmetic / usability                                   |
| Area      | `frontend/src/hooks/aiagent/useAgentChat.ts` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

A tool failed mid-turn, the agent retried and answered correctly, yet the red banner stayed at the bottom of the chat.

## Root cause

An agent `error` event sets `error` immediately (tool errors are recoverable) but nothing cleared it until the next send or a conversation reset.

## Fix

The hook remembers the message of the latest agent `error` event. A later successful `tool_result` or an agent `message` clears it; a new send and a conversation switch/reset also clear it. An error with no later success (turn failed) and unrelated errors (socket, send, key) stay. The failed step remains in the message history.

## Verification

- `tsc --noEmit` passes.
- `tests/frontend/useAgentChatErrors.test.tsx`.
