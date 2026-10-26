# BUG-0528 — BLE "Waking STB…" badge duplicates the panel-header status dot

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0528                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On the BLE remote panel, the moment the link drops the operator saw the wake state in three
places at once: a small amber "Waking STB…" (or "Reconnecting…") pill at the top-left of the
remote image, the disabled "Waking…" Power button with its own spinner, and a steady amber dot
in the panel header next to the title. The pill on the image was redundant with the dot in the
header and pulled the eye away from the button row that actually changes behaviour during a
wake (Re-pair hidden, Power disabled, Logs to a second line on narrow widths).

## Root cause

`renderRemoteImage()` in `frontend/src/components/controller/remote/BluetoothRemote.tsx` rendered
an absolutely-positioned amber pill (`<Box>` with `border: 1px solid ${P.warning}` and a 10 px
`CircularProgress`) at `top: 8, left: 8` whenever `reconnecting` was true. The same
`reconnecting`/`isWaking` signal already drives the panel-header BLE status dot
(`bleDotColor === P.warning` and the disabled "Waking…" Power button) so the pill was a
second copy of the same information.

## Fix

Removed the inline pill. Extended the existing `onStatusChange` callback from
`BluetoothRemote` to `RemotePanel` with a third `blink: boolean` argument, true while
`isWaking || reconnecting`. `RemotePanel` plays a soft opacity pulse (1.1 s ease-in-out,
1 ↔ 0.35) on the 10×10 header dot only while that flag is true; the dot keeps its steady
amber colour for non-transient amber states (e.g. `degraded` — connected but HID missing).
The heading + subtext and the disabled Power button still own the human-readable status and
the clickable progress; the dot is the motion cue.

## Verification

- `tsc --noEmit` on the two files: 0 errors. (One pre-existing error in
  `frontend/src/components/rec/RecGotoNodePanel.tsx:70` is unrelated.)
- `BluetoothRemote.tsx` no longer renders any `<Box … title="The STB dropped the BLE link…">`
  pill; a comment in its place points to the dot and the BUG-0420 history.
- `RemotePanel.tsx` `@keyframes bleDotBlink` runs only while `bleDotBlink === true`; turning
  it off is a single `animation: 'none'` and the dot still reads as a normal status pip.
- `prefers-reduced-motion` is not currently handled on this animation; a follow-up could
  add a media query guard to disable the pulse for users who set the OS preference (the
  `Cmd+K` Fab animation already respects it — this animation is small and slow enough that
  most users would not flag it, but it is a real gap to record).
