# BUG-0539 — Agent Chat assistant text uses the full panel width and is hard to read

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0539                                                     |
| Reported  | 2026-10-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / agent-chat / typography                           |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `/ai-agent` (AI Agent chat), the assistant's answer text spans the **full
panel width**, not a reading-friendly column. On a normal desktop window the
chat column is well over 1200 px wide, so each paragraph wraps into one or two
very long lines (roughly 150–200 characters each). That makes the text
noticeably harder to scan than ChatGPT or Claude, both of which cap their
answer column around 768 px. The same problem affects the streamed reasoning
text (`View Reasoning` accordion body) and the user-message bubble, which
currently fills the whole row.

Two screenshots attached to the report:

- A Tello drone answer that runs edge-to-edge, with lines like
  *"VirtualPytest treats a Tello drone as a normal `tello` device model — same
  tile, same Control panel, same lock as any other device."* wrapping at
  ~170 chars.
- A stream of agent reasoning lines
  (`Ran grep…`, `Now the matcher (identify_screen) and where confidence 0.6 /
  candidates come from.`, `Setting up a copy of my worktree on vpt-pi1 …`)
  each one long line.

## Root cause

`frontend/src/components/agent-chat/ChatMessages.tsx`:

1. The content wrapper inside the scroll container is a bare
   `<Box sx={{ width: '100%' }}>`, so every message row inherits the full panel
   width.
2. The assistant message `Paper` uses `flex: 1`, so the bubble fills the row.
3. `assistantMarkdownSx` set the body to `0.82rem` / `lineHeight 1.55` —
   readable in isolation, but compounded by the very long lines above it the
   paragraph becomes a wall of text.
4. The user-message `Paper` also uses `flex: 1`, so even a short question
   stretches to the full chat width.

## Fix

`frontend/src/components/agent-chat/ChatMessages.tsx`:

- Wrap the messages column in a centered 820 px cap:
  `<Box sx={{ width: '100%', maxWidth: 820, mx: 'auto' }}>`. Narrow screens
  collapse to `100%` because the parent has no fixed width — nothing is
  clipped.
- Keep the assistant bubble at `flex: 1` so it uses the full reading width,
  but let the **user** bubble size to content with a `maxWidth: '70%'` cap, so
  short questions do not look like a full-width banner. This matches the
  ChatGPT / Claude layout.
- Bump `assistantMarkdownSx` body to `0.95rem` / `lineHeight 1.65` (≈15.2 px /
  1.65) and the heading sizes proportionally (h1 1.05rem, h2 1rem, h3-h6
  0.95rem) so the visual hierarchy still reads correctly at the new body size.
- Bump the reasoning accordion body (`View Reasoning`) from 0.85rem /
  lineHeight 1.5 to 0.9rem / lineHeight 1.6, so the streamed thinking text is
  easier on the eye too.

820 px was picked over Claude's 768 px to keep room for the avatar column
(28 px) and bubble padding (24 px total) without losing the body font's
natural line length.

## Verification

- `tsc --noEmit` and `eslint src/components/agent-chat/ChatMessages.tsx`
  pass on the changed file. The pre-existing
  `LiveRunDialog.tsx` `hideLabel` type error is on `main` and is unrelated.
- Deployed to `node1-vpt`. The shipped bundle's `assistantMarkdownSx` carries
  the new sizes (`font-size:.95rem;line-height:1.65`) and the content wrapper
  carries `max-width:820px;margin:0 auto`. Both greps land in
  `frontend/public/assets/*.js`.
- On `/ai-agent`, send any message that returns a multi-paragraph answer
  (e.g. the Tello drone prompt in the report). The answer now wraps at roughly
  80 chars per line, lines are noticeably shorter, and the user bubble
  shrinks to fit short messages.