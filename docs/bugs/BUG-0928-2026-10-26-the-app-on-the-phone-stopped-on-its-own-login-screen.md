# BUG-0928 — The app on the phone stopped on its own login screen, with Android's dialog on top of it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0928                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | testing (content suite, mobile adapter)                      |
| Fixed in  | build 90145 |
| Commit    | see branch `feat/task168-web-session`                        |

---

## Symptom

Every mobile case of the content suite ended the same way: *"the screen does not
match the tree's reference picture"*. The tree's very first edge (ENTRY → home)
failed with *"Element 'Home … currently selected' not found after 9.4s"*, and the
radio case reported that no radio surface exists in the app at all.

The phone itself was fine: the app is installed, it launches, and it answers.
What the run never got past was the app's own front door.

## Root cause

Two things stand between the launch and the app's first surface, and the suite
answered neither of them.

1. **Android's own permission dialog.** The app asks for notifications on its
   first start and the system puts a modal dialog on top of it ("Allow … to send
   you notifications?"). The dialog belongs to the system, so it is on screen
   whatever the app draws underneath it.
2. **The app's own login screen.** The app opens on a login page with a
   *Skip login* control in the corner. Until that is used, the app shows its
   front door and not the tab bar the tree verifies.

Both are visible in the captures of the run (`~/vpt-deliverables/vod-radio-runs/2026-10-26T01-53-44Z-mobile/`):
one frame shows the login page with the notification dialog on top of it, the
next shows the app's splash with the same dialog still up.

The suite waited for the app, but it waited for the wrong thing: it asked
whether *any* of the app's own surface labels was readable and moved on when the
answer was no — without asking whether the thing in front of the app was
answered. The tree then drove an app that was still behind its front door, and
the tree's verification (which reads the tab bar) could not see it.

3. **And the names of the controls were never read.** The platform's UI dump
   fills an empty text field with the placeholder `<no text>`, and the app
   publishes its names in the **content description** ("Skip login. Button").
   The adapter read the text field first, so the placeholder won and the name
   was lost: the control was on the screen all along and the suite could not
   see it. The platform itself prints the name with the content description
   first — the adapter now reads it the same way, and a placeholder is not a
   name. The system dialog was found in every run because its buttons carry
   **real text**; the app's own buttons do not.

## Fix

All in `test_scripts/content/_mobile_adapter.py`.

- **The system dialog is answered.** The screen is read; when the dialog is
  there, *Don't allow* is tapped (the allow button is the fallback). It is a
  system choice, never a credential.
- **The app's own bypass is used.** The *Skip login* control is looked for by
  its label — in every language the app ships — and tapped. No account is
  typed anywhere: the suite tests the guest session the app actually gives.
- **The labels carry the widget's role.** The app publishes them as
  *"Skip login. Button"*, not *"Skip login"*, so an equality match misses the
  very control we are after. The match prefers an exact hit and falls back to
  the label's start, the way the platform's own search does.
- **Both are answered before the app is judged ready, and again on every poll.**
  The app may put the login screen up after the first answer, so the wait asks
  again until the app's own surface is readable.

## Verification

`scripts/agent/vod_radio_offline_check.py` — 65/65 checks pass, including the
new ones: the system dialog is answered, the app's own bypass is used without a
credential (even when the label carries the widget's role, "Skip login.
Button", and even when the name lives in the content description while the
text field holds the placeholder `<no text>`), the app is ready once both are
answered, and an app that stays behind its login screen is never read as ready
(the dialog and the bypass are tried again on every poll).

Live, on the lab phone: the run of 2026-10-26 06:53 answers the system dialog
(the log shows *"answered the permission dialog (tapped 'Don't allow' at
540,2034)"* — the dialog is gone from the next screen dump) and the login
screen behind it is in the dump (*"Skip login. Button"*, *"LOGIN. Button"*,
*"Please sign in with your account…"*) — but the bypass was never used,
because the name was read from the text field, where the dump puts the
placeholder. Two fixes came out of that run: the name is read from the content
description first (as the platform prints it), and a label is matched by its
start when it carries the widget's role.

The run of 2026-10-26 07:13 is the proof that both fixes work: the log reads
*"the app's own bypass was used (tapped 'Skip login. Button' at 927,183)"* and
*"the TV app is on the screen after 0s"*, and the suite drives the app from
there.

## Evidence

- The mobile run of 2026-10-26 01:53 on `vpt-pi1/device1`:
  `~/vpt-deliverables/vod-radio-runs/2026-10-26T01-53-44Z-mobile/` — the radio
  case reports the tree's first edge failing on the tab element, and the
  captures of the run show the login page and the system dialog.
