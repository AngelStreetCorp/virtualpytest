# BUG-0529 — Go to node: running shown as success

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                  |
|-----------|------------------------|
| ID        | BUG-0529               |
| Reported  | 2026-10-14             |
| Status    | Fixed (pending deploy) |
| Severity  | Low                    |
| Area      | frontend               |
| Fixed in  | build 90145 |
| Commit    | see git log            |

---

## Symptom

In the Go to node panel, the progress message ("Navigating to home...") was shown in a green success
Alert with a check icon while the navigation was still running.

## Root cause

`Navigation_NodeGotoPanel.tsx` rendered `nodeHook.executionMessage` with severity `success` whenever a
message existed. The message is also set by `onProgress` while `isExecuting` is true.

## Fix

While `isExecuting` the Alert is `info` with the running icon; success only after completion, warning for
a sibling arrival, error unchanged. `ThemeContext` now themes MUI Alert info (neutral surface, textSecondary
icon) and success / error / warning (palette status colours) for standard and outlined variants.
`scripts/status_check.mjs` flags `severity={... running-ish ? 'success'`.
