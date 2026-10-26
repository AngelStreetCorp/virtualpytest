# BUG-0541 — Agent Chat devtools console floods with `[ChatMessages] Render check:` lines while a turn is active

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                  |
|-----------|--------------------------------------------------------|
| ID        | BUG-0541                                               |
| Reported  | 2026-10-15                                             |
| Status    | Fixed (pending deploy)                                 |
| Severity  | Low (cosmetic / devtools noise)                        |
| Area      | frontend / ai / agent-chat                             |
| Fixed in  | build 90145 |
| Commit    | see branch fix/cleanup-render-log                      |

---

## Symptom

Opening `https://virtualpytest.angelstreet.io/ai-agent` and starting a chat
turn floods the browser devtools console with hundreds of identical-looking
lines per minute:

    AgentChat-BpI5ruy_.js:19 [ChatMessages] Render check:
    {activeConversationId: '1792058906583-dimchlf', sidebarTab: 'chats',
     messagesLength: 4, isSystemConversation: false, hasNoMessages: false, …}
    AgentChat-BpI5ruy_.js:19 [ChatMessages] Render check:
    {activeConversationId: '1792058906583-dimchlf', sidebarTab: 'chats',
     messagesLength: 4, isSystemConversation: false, hasNoMessages: false, …}
    … (repeats ~4 times/sec while a turn is in flight)

The DOM is unaffected, but the console becomes unusable during long turns.

## Root cause

`frontend/src/components/agent-chat/ChatMessages.tsx` runs a 250 ms
`setInterval` (the `now` tick driving the live "answer elapsed" /
"reasoning elapsed" counters) while a turn is in flight:

    const interval = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(interval);

That timer triggers a re-render of `ChatMessages` ~4 times/sec during the
turn. Two unconditional `console.log` calls live in the render bodies of
`ChatMessages.tsx` (line 794 before the fix) and `AgentChat.tsx` (line 2707
before the fix), so every render emits one log line. The two logs survived
the initial open-source snapshot (`703263e54`) and were never gated by
`import.meta.env.DEV` / `NODE_ENV`. The expected re-render storm is
~4 renders/sec, the log just makes the storm visible.

## Fix

Remove both render-body `console.log` calls from
`frontend/src/components/agent-chat/ChatMessages.tsx` and
`frontend/src/pages/AgentChat.tsx`. The 250 ms timer that drives the live
elapsed counters is left intact — it is intentional behaviour, not the
defect. No other code or test changes required; the rendering cadence and
the counters it powers are unchanged.

## Verification

Open the Agent Chat page, send a turn, watch the browser devtools console:

- before: ~4 `[ChatMessages] Render check:` lines/sec (with
  `[AgentChat] Render check:` interleaved when the parent's IIFE re-runs).
- after: no `Render check:` lines; the live `mm:ss.t` counters on each
  card and in the header still tick four times a second, and the cards
  freeze on the same values the moment `turnStartedAt` flips to `null`.
