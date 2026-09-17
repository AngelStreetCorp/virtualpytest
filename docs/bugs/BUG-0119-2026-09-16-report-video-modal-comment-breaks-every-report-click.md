# BUG-0119 — A code comment's backticks silently disabled every click in every script report

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                 |
|-----------|------------------------------------------------------------------------|
| ID        | BUG-0119                                                              |
| Reported  | 2026-09-16                                                            |
| Status    | Fixed (pending deploy)                                                |
| Severity  | High (every script report generated since the regression)            |
| Area      | `shared/src/lib/utils/report_template_js.py`                         |
| Fixed in  | build 9151                                                            |
| Commit    | this commit                                                           |

---

## Symptom

On a script report (`report.html`), nothing in the "Test Steps" list responds to a click — rows
that should expand to show the step's actions/verifications/error just sit there. The same report
still renders fine (summary fields, "Click here" links, badges), so at a glance the page looks
intact; only the interactive parts are dead. Section header toggles (▼ Summary / ▼ Test Steps) and
screenshot/video modals are silently broken too — every `onclick` handler defined in the report's
single inline `<script>` block stops working, not just the step rows.

## Root cause

`report_template_js.py`'s `openVideoModal()` builds the video-modal markup as a JS template
literal (backtick string). A code comment added inside that literal (`df7d936a38`, explaining why
the video element bounds both width and height) itself used backticks around `` `min-width: 800px` ``
and `` `height: auto` ``. A backtick inside a template literal isn't just text — it's the token that
*closes* the literal. The first one ends the outer string right after "...BOTH orientations. ",
leaving `min-width: 800px\` with\n \`height: auto\` blew...` as bare, invalid JavaScript.

That single unescaped backtick is a syntax error in the whole inline `<script>` block. Browsers
don't partially execute a script tag — a parse error in one function (`openVideoModal`, only
reachable when a report has a video) kills every function defined anywhere in that block, including
the completely unrelated `toggleStep()` and `toggleSection()` used by every report, video or not.
Confirmed by extracting the generated `<script>` content from a live report and running
`node --check` on it: `SyntaxError: Unexpected identifier 'min'` at the exact comment line.

## Fix

Reworded the comment to use single quotes instead of backticks
(`shared/src/lib/utils/report_template_js.py`), so the template literal is no longer terminated
early. Verified by re-running `get_report_javascript()` and `node --check`-ing the output: clean
syntax, no stray backticks left in the file (`grep '`'` now shows only the four intended
literal open/close pairs).

## Verification

1. `python3 -c "from shared.src.lib.utils.report_template_js import get_report_javascript; js=get_report_javascript().replace('{{','{').replace('}}','}'); open('/tmp/r.js','w').write(js)"` then `node --check /tmp/r.js` → passes.
2. Re-generate a report and open it in a browser: clicking a step row expands/collapses it; the
   summary/steps section headers toggle; screenshot and video modals still open.
