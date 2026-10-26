# BUG-0916 — The web content suite never opened a catalogue tile: the app speaks German and the suite spoke English, behind a sign-in box nobody dismissed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0916                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | testing (content suite, web adapter)                         |
| Fixed in  | build 90145 |
| Commit    | see branch `feat/task168-web-session`                        |

---

## Symptom

Every web case of the content suite ended the same way: *"the tile did not open
an item"*. The runs of 2026-10-24 (08:34, 09:48, 10:04, 10:24, 11:03, 11:19,
11:59, 12:41) all reached the catalogue page of the TV web app and none of
them ever held a programme. The whole web platform was therefore reported as
infra — *our* interaction — although the app opens its catalogue tiles without
any trouble when it is driven by hand.

The run of 2026-10-25 20:37 shows the second half of the story: the suite never
held a programme either, and it died in the radio case on *"Element not found
after 10.0s"* while the browser was showing the app's own sign-in box.

## Root cause

Three causes, all ours.

1. **The app shows itself in the language of the browser profile, and a fresh
   profile starts in German.** A script run gets a Chrome profile of its own
   (`VPT_RUN_ID` → `user_data_runs/<run id>`), so every run started in German —
   and the reference tree was built in German too (its entry edge opens
   `/de/home`). The suite, however, pressed **English** labels: the catalogue
   tile is published by the app as *"Alle Sendungen, drücke Tab oder
   Umschalt+Tab, um nach links und rechts zu navigieren, …"* and the suite
   pressed *"All Shows"*. The press matched nothing at all, so "the tile did
   not open an item" was **our** fault and not the app's: pressing the label
   the app actually publishes opens the detail page of a real programme
   (`/replaycatalog/0/details/replaytv/<programme id>/show`).
2. **The app puts its sign-in box OVER the page it opens, and nobody
   dismissed it.** The box is a full-screen overlay on the app's own page, so
   the URL is the app's own URL: "the app is open" was true, the guest route
   (the app's own *"Anmeldung überspringen"* / *"Skip login"*) was never
   pressed, and every navigation after that landed on the sign-in box instead
   of the screen that was asked for. The box is only visible in the page
   itself, so it has to be looked for there.
3. **The press could not reach what the page script cannot see.** The page
   script presses only what is *on screen*; the platform's own `click_element`
   dumps the whole semantics tree and finds more. The adapter only tried that
   click **after** a press that had changed nothing, never when the page script
   had pressed nothing at all.

## Fix

All in `test_scripts/content/_web_adapter.py`.

- **The suite speaks the app's language.** Every label it presses is listed in
  every language the app ships: the replay catalogue tile (*"all shows"* /
  *"alle sendungen"*), the VOD catalogue tile (*"popular movies to rent"* /
  *"neue filme zum mieten"*) and the play action (*"watch"* / *"schauen"* …).
  The app publishes one of them, that one matches, the other is ignored. The
  app's language is read from the page (`flutter.language`, which the app
  stores quoted: `"de"`) and written into the run's evidence — it is never
  assumed.
- **The sign-in box over the app is dismissed.** When the page shows the app's
  own sign-in, the adapter presses the app's own bypass and confirms that the
  box is gone before it drives anything.
- **The press fallback runs also when the page script pressed nothing**: the
  labels the caller asked for are tried on the platform's click, one after the
  other, and the first one that changes the page wins. A press that already
  worked is never repeated — the second press on a Record button would undo
  the first one.
- The cookie banner (OneTrust), which lies over the app, is dismissed too.

## Verification

`scripts/agent/vod_radio_offline_check.py` — 58/58 checks pass, including the
new ones for these rules: the app's language is read from the page and never
assumed, the suite speaks the language the app publishes, and the sign-in box
over the app is looked for (not only a sign-in *page*).

Live, on `labox-backend` (2026-10-25), with the suite's own press script: the
app's own sign-in box is dismissed by pressing *"Anmeldung überspringen"*, the
German catalogue tile *"Alle Sendungen"* opens the detail page of a replay
programme, and the German VOD tile *"Neue Filme zum Mieten"* opens the detail
page of a film. The detail page of the film carries the app's own sign-in
prompt ("Melde dich bitte mit deinen Zugangsdaten an, um diesen Inhalt
abzuspielen") — the session of a guest covers the catalogue, not the playback,
and the run says so.

## Evidence

- The web runs of 2026-10-24 that reported "the tile did not open an item":
  `~/vpt-deliverables/vod-radio-runs/2026-10-24T*/report.md`.
- The run of 2026-10-25 20:37 on `labox-backend`:
  `~/vpt-deliverables/vod-radio-runs/2026-10-25T20-37-22Z/` — the log shows
  *"the app shows itself in 'de'"* and the failure *"Element not found after
  10.0s"* on the tree's own route, with the browser on the sign-in box.
- The live walk of 2026-10-25 on `labox-backend`: the catalogue's semantics
  labels in German, the sign-in box before the skip and the app's own screen
  after it.
