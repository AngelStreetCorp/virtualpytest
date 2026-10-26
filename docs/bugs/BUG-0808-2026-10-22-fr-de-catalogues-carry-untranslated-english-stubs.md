# BUG-0808 — The French and German catalogues carry about 100 untranslated stubs (the value is the English key) and the i18n check does not catch them

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0808                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Low                                                       |
| Area      | frontend / i18n                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-11, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** any page using an affected key (for example /status)
- **Viewport / theme:** 1440 px, dark, French and German

Steps to reproduce:

1. Switch to French and open `/status`.
2. Read "VM summary" and "Hide details".

**Expected:** "Resume des VM", "Masquer les details".

**Actual:** Both stay English although the keys exist, because the catalogue value is the English key. `fr.json` has 123 of 2167 keys whose value equals the key and `de.json` 107; some are legitimate (proper nouns), the rest silently fall back to English.

Evidence:

- [ops-10-status-untranslated-fr.png](../tasks/qa-evidence/ops/ops-10-status-untranslated-fr.png)

## Root cause

`frontend/scripts/i18n-check.mjs` fails on missing keys and English literals in listed files, not on a value identical to the source string.

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
