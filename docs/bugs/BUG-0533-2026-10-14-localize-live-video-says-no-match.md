# BUG-0533 — Localize says "No match" on live video

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0533                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / navigation                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

> **Superseded by [TASK-104](../tasks/TASK-104-localize-v3-cascade.md) (2026-10-14).** The host now
> measures motion itself and returns `verdict.kind = 'live'`; the popover reads that instead of
> the monitor's `classifier_diagnostics.motion`. The frontend-only rule below is gone.

## Symptom

Pressing Localize while the device plays video shows "No match". Live video is never a saved screen, so the matcher abstains, but the operator expected to be told the screen is video.

## Root cause

The popover only knew the matcher verdict. The per-frame motion verdict (`classifier_diagnostics.motion`) was shown as a small "Screen state" line in step 2 and never fed the headline.

## Fix

`frontend/src/components/navigation/Navigation_LocalizeButton.tsx`: when the matcher abstains (no candidates, no `state`) and `motion.kind === 'full'` or `motion.state === 'live'` (the same two tests `monitor_localize.py` gates on), step 1 and step 2 read "Live video — The screen is playing video, which is not a saved screen." Static, box, band or minor motion keeps "No match" with the abstain reason; null diagnostics change nothing.

Frontend only on purpose: `state` is the capture-failure channel (blackscreen / no_signal) that MCP and scripts treat as a warning, and the diagnostics are read from a JSON up to ~1 s old, so the host cannot give a firmer verdict than the popover already has.

## Verification

Render the popover with an abstain payload and `motion.kind: 'full'` (headline "Live video") and `'static'` ("No match"), in dark and light.
