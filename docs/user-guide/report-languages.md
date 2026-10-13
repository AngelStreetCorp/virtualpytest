# Test reports in English, French and German

Every run report and campaign report can be read in English, French and German. Use the `EN | FR | DE` switch at the
top right of the report, next to Light/Dark/System.

## Which language opens

1. `#lang=fr` (or `?lang=fr`) in the report link wins. On a stored report link, always use `#lang=`. Those links are
   signed URLs, so an extra `?…&lang=` parameter can make storage refuse the link (403). The fragment never reaches
   storage. The web app opens reports with `#lang=<your app language>`.
2. Otherwise, your last choice on the switch. It is kept in the browser under `virtualpytest:language`, the same
   setting the web app uses, so the app and the reports follow each other.
3. Otherwise, your browser language, if the report has it (`fr-CH` → `fr`).
4. Otherwise, English.

A [shared link](./sharing-reports.md) keeps the switch, since the translations are inside the page. A shared page
cannot remember your choice, though. Add `#lang=fr` to the link you send so it opens in French.

## What is translated

- **Translated**: the report's own words (headings, labels, PASS/FAIL, link names, step timing), the platform's
  step messages (`Navigation step: A → B`, `Recovery → home`), and the strings of scripts that ship a language
  file (below).
- **Shown as captured**: device, host, node and file names, OCR text, numbers, URLs, the JSON details of a
  verification, and any message nobody wrote a translation for (an exception text, for example).

Reports made before this feature have no switch. They are not regenerated.

## Translating your script's strings

Put a `<script>.i18n.json` next to the script: `test_scripts/goto.py` → `test_scripts/goto.i18n.json`. Each key is the
**exact English text** your script writes into the report: a step message, a verification label,
`context.error_message`, or one line of `context.execution_summary`. Write `{name}` where a value changes from run to
run. The value maps each language code to its text and keeps the same `{name}`s.

```json
{
  "Captured {saved} of {total} sample frames": {
    "fr": "{saved} images capturées sur {total}",
    "de": "{saved} von {total} Bildern erfasst"
  },
  "🎯 Result: SUCCESS": { "fr": "🎯 Résultat : RÉUSSI", "de": "🎯 Ergebnis: ERFOLGREICH" }
}
```

- Your script does not change: it keeps writing English, and the report does the rest.
- A multi-line execution summary is matched line by line, so write one key per line.
- When two keys match, the one with more fixed text wins (`📍 Navigation steps: 0 (already verified at target)`
  beats `📍 Navigation steps: {count}`).
- A missing language shows the English text.
- `python3 scripts/report_i18n_check.py` checks every file: invalid JSON, a `{name}` missing or extra in a
  translation (an error), and languages not yet covered (a warning; `--strict` turns these into errors).

`goto` and `subtitle_qa` ship one. Copy those as examples.

**Virtual scripts** (edited in the browser) have no file next to them. Put the same dict in the source instead, next
to `_script_args`: `main._i18n = { "Captured {saved} of {total} sample frames": {"fr": "…", "de": "…"} }`. A file
script may do the same. When both exist, `main._i18n` wins for the entries it has.

**Testcase reports** (from the TestCase builder) get the switcher too. The platform translates its block, navigation and
loop lines. The names you typed into the testcase stay as typed.

## Adding a language

1. Copy `shared/src/lib/i18n/report/en.json` to `<code>.json` (for example `es.json`). Set `_name` to the language's own
   name and translate the values. Keep every `{name}`.
2. Run `python3 scripts/report_i18n_check.py`. It lists what is missing for the platform and for each script.
3. That is all. The switch builds its buttons from the files present. Scripts add `"es"` to their entries when they
   are ready; until then they show English.

Use lowercase codes, the same as the web app: `en`, `fr`, `de`, then `es`, `zh-CN`, and so on.
