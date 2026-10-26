# BUG-0228 — Script report: a small recording played at its native size in the video modal

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0228                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed — not yet deployed                                     |
| Severity  | Low — the video plays, but a web-host recording is a small box in the middle of an empty modal |
| Area      | `shared/src/lib/utils/report_template_js.py` (`openVideoModal`) |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

In the report of `game/game_tetris` on the `tetris-web` host (2026-10-01, 18:50–18:53), the
**Test Execution** video opened as a small player in the middle of a large, empty modal.

## Root cause

The modal's `<video>` was styled `width: auto; height: auto` with only `max-width` /
`max-height` bounds. Those bounds only shrink a large recording; a small one (a web host's
capture) stays at its intrinsic pixel size and is never scaled up to the modal.

## Fix

The `<video>` now fills the modal body (`width: 100%; height: 100%; object-fit: contain`),
the same rule the screenshot `<img>` already uses. Landscape and portrait recordings both scale
to fit, and the player controls stay inside the modal (the reason the old height bound existed).

## Verification

- After a server/host deploy, open a web-host script report and click **Test Execution**: the
  video fills the modal width. Then a phone (portrait) report: the video fits the modal height
  and its controls are visible.
