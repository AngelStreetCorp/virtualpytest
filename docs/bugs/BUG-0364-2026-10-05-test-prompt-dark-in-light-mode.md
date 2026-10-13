# BUG-0364 — Test Prompt stayed dark in light mode

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0364                                                     |
| Reported  | 2026-10-05 (user screenshot, RPI1-server)                    |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — cosmetic, inconsistent with every other page           |
| Area      | `features/ai-test/frontend/TestPrompt.tsx`, `frontend/src/constants/agentChatTheme.ts` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

With the app in light mode, AI → Test Prompt kept a near-black sidebar, header and form, with only the result cards white.

## Root cause

The page and its form read the fixed dark `AGENT_CHAT_PALETTE` regardless of the MUI theme mode.

## Fix

`agentChatTheme.ts` gains `AGENT_CHAT_PALETTE_LIGHT` (same keys, matched to the light theme's `#fafafa` / `#fff`, darker gold for contrast) and a `useAgentChatPalette()` hook that picks by `theme.palette.mode`. `TestPrompt.tsx` and `TestPromptForm.tsx` use the hook; dark mode is unchanged.

## Verification

- `tsc --noEmit` passes.
- After the deploy: Test Prompt in light mode shows a light sidebar, header and form.
