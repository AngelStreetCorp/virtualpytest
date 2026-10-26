# BUG-0498 — AI chat key popup stayed up after one "no key" answer

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0498                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

`/ai-agent` showed "AI Provider Configuration Required" for endpoint `minimax` although the key
was stored on the server. The key field looked already filled (dots), yet the agent did not
connect. A reload brought the chat back.

## Root cause

`useAgentChat` asks `GET /server/agent/health` once on mount. When that one answer says
`api_key_configured: false`, the status is set to `needs_key` and never asked again, so a
single wrong or stale answer kept the popup up until a reload. The server's key
(`ai_secrets.json`) and the `minimax` endpoint row had not changed since 2026-09-29, and both
`/server/agent/health` and a chat turn answered fine when checked; the one-off answer could
not be traced further.

The dots in the field were the browser's saved-password autofill on a `type=password` input,
not the server key.

## Fix

- `frontend/src/hooks/aiagent/useAgentChat.ts`: while the status is `needs_key`, the health
  check runs again every 15 s; when the server has the key the chat connects on its own.
  Saving a key cancels the pending check.
- `frontend/src/components/agent-chat/ChatMessages.tsx`: the field sets
  `autoComplete="new-password"` so the browser no longer fills it. The popup is shorter:
  title "API key needed", one line `<endpoint> · <model> has no key.`, a settings icon at the
  top right (Settings → AI → Endpoints), button "Save".

## Verification

Open `/ai-agent` with a configured endpoint: the chat connects. With the popup showing, add
the key in Settings → AI → Endpoints in another tab: within 15 s the popup goes away and the
chat connects without a reload.
