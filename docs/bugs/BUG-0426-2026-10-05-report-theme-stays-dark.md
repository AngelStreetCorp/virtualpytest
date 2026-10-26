# BUG-0426 — Test reports looked dark whichever theme was picked

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0426                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | shared / reports                                             |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On the owner's computer a script report (e.g. `game_kirby.py`, 2026-10-05) stayed dark when switched to
light or dark: light theme's blue header over a dark body. Switching the web app's theme did not change
the report either.

## Root cause

Two things. (1) The report never declared `color-scheme`, so a browser in dark mode with auto-dark for
web pages (Chrome "Auto Dark Mode for Web Contents", or an extension such as Dark Reader) darkened its
light theme — the gradient header survived, the backgrounds were inverted. The web app declares
`color-scheme: light dark` (`frontend/src/index.css`) and is left alone. (2) The report kept its own
theme key (`validation-report-theme`, default light), so it never followed the app's choice.

Headless Chromium does not apply forced dark, so (1) is inferred from the screenshot (light-theme header
on a dark body) and the missing declaration; the toggle itself worked in every headless test.

## Fix

`shared/src/lib/utils/report_template_html.py` adds `<meta name="color-scheme" content="light dark">`;
`report_template_css.py` sets `color-scheme: light dark` on `:root`; `report_template_js.py` reads and
writes the app's `theme-mode` key (default `system`, like the app) and follows a change made in another
tab (`storage` event). Reports are served from the app's origin, so app and reports now share one theme.

## Verification

Open a report generated after the host deploy: the sun / moon / monitor switch changes the page; switching
the theme in the app (another tab) switches the open report. Reports generated before the deploy keep
their old HTML.
