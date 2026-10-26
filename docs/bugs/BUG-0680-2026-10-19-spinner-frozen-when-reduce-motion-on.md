# BUG-0680 — Loading spinners looked frozen when "Reduce motion" (or the OS setting) was on

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0680                                                                                       |
| Reported  | 2026-10-19                                                                                     |
| Status    | Fixed (pending deploy)                                                                         |
| Severity  | Low (a working screen looked hung)                                                             |
| Area      | `frontend/src/contexts/ThemeContext.tsx`                                                       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                                                            |

---

## Symptom

During a stream quality switch the "Loading HD quality stream…" overlay showed a spinner that did not
turn, so the screen looked hung.

## Root cause

When "Reduce motion" is on (Settings → Appearance, or the operating system's reduced-motion setting,
which always applies), the theme forces `animation-duration: 0.001ms` and one iteration on every
element (`*`). That also stopped every loading spinner: computed on the live page the spinner went from
`1.4s infinite` to `1e-06s ×1`. The setting's own text promises only to turn off page transitions
and chart animations.

## Fix

`ThemeContext.tsx`: the reduced-motion rule no longer applies to `.MuiCircularProgress-root` and its
children, so spinners keep turning. Everything else stays reduced.

## Verification

Headless Chromium with `reducedMotion: 'reduce'`: before, the spinner's computed animation is
`1e-06s ×1`; after deploy it is `1.4s infinite`.
