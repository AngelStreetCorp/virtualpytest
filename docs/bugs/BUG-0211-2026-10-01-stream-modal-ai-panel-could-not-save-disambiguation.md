# BUG-0211 — Stream-modal AI panel: "remember my choice" for an ambiguous prompt failed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0211                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — the choice was not saved and the panel showed *Failed to apply disambiguation*; generating again asked the same question |
| Area      | `frontend/src/hooks/useAIExecutionPanel.ts` (AI panel in the stream modal) |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

In the stream modal's AI panel, a prompt with an ambiguous screen name (for example "live" when
the tree has `live` and `live_fullscreen`) asks the user to pick one. With the choice saved, the
panel shows *Failed to apply disambiguation* and does not regenerate. Found while reading the
panel for TASK-36 phase 2; listed as an open item in the TASK-36 task doc.

## Root cause

The panel posted `/server/ai/saveDisambiguationAndRegenerate`. No server or host route has that
name, so the auto-proxy forwarded it to `/host/ai/saveDisambiguationAndRegenerate`, which
answered 404. The route that saves the choice is `/host/ai-disambiguation/saveDisambiguation`,
reached through the auto-proxy as `/server/ai-disambiguation/saveDisambiguation`. It takes
`selections` as a list of `{phrase, resolved}`. The Test Builder already calls it that way
(`useTestCaseAI`); the panel sent a `{phrase: resolved}` map.

## Fix

The panel posts `/server/ai-disambiguation/saveDisambiguation` with the selections converted to
`{phrase, resolved}`, then regenerates as before.

## Verification

- `tsc --noEmit`, ESLint on the file and `vite build` pass.
- Still to do after a frontend deploy: in the stream modal, enter an ambiguous prompt, pick a
  screen with "remember" checked, and confirm the plan regenerates. The next run of the same
  prompt must not ask again.
