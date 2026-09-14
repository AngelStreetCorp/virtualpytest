# BUG-0016 — "Confirm Action" flashes when a confirm dialog closes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0016                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / dialogs                                           |
| Fixed in  | build 8713                                                   |
| Commit    | `c677f54c4`                                                  |

---

## Symptom

Confirm dialogs (e.g. **Force Takeover** on the Navigation Editor) briefly flashed a generic,
empty **"Confirm Action"** popup during their close animation — the real title/message vanished and
a placeholder appeared for the duration of the fade-out.

## Root cause

On confirm/cancel the dialog's `open` flag flips to `false`, but the component also **reset its
title/message state back to defaults synchronously** in the same handler. Because the dialog fades
out over a short transition, it remains mounted and visible for those frames — now showing the
default "Confirm Action" title and an empty message instead of the content it had a moment earlier.

## Fix

`frontend/src/` confirm dialog component (`c677f54c4`): keep the title/message intact through the
fade-out and only reset them after the dialog has fully closed (or not at all — they are overwritten
the next time the dialog opens). The visible content no longer changes mid-transition.

## Verification

Trigger any confirm dialog (e.g. Force Takeover), then confirm or cancel: the dialog fades out
showing its own title/message the whole time — no generic "Confirm Action" flash.
