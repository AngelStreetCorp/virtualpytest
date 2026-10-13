# BUG-0406 — Text checks passed when a short target only appeared inside a longer word

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                    |
|-----------|----------------------------------------------------------|
| ID        | BUG-0406                                                 |
| Reported  | 2026-10-05                                               |
| Status    | Fixed (pending deploy)                                   |
| Severity  | Medium                                                   |
| Area      | backend_host text verification (`text_helpers.py`)       |
| Fixed in  | Unreleased                                               |
| Commit    | TBD                                                      |

---

## Symptom

A text check for a short word such as "Home" passed on a screen that did not show it. The OCR text
contained "Aufnahmen", and "home" scores 0.857 against the letters "ahmen" inside it, above the
default 0.8 threshold. Borderline checks passed falsely: in the TASK-47 second-opinion benchmark
(81 labelled borderline text checks, truth from a blind image judge) 30 were false passes.

## Root cause

`TextHelpers.text_match_score` slid a target-length (plus or minus 2) window of CHARACTERS over the
whole OCR string and took the best difflib ratio. Words were ignored, so a short target matched
fragments inside unrelated longer words.

## Fix

The score is computed on word boundaries. The normalized target found as whole word(s) is still
exactly 1.0 (so `threshold=1.0` keeps meaning "verbatim"). Otherwise the target is compared with
every window of the same number of OCR words, plus or minus one (OCR merges and splits words),
and the best difflib ratio is returned. "Home" vs "Aufnahmen" now scores 0.46; "Anrnelden" vs
"Anmelden" scores 0.82 (passes 0.8, fails 0.95), "TVGuide" vs "TV Guide" 0.93. Text with kana, CJK
ideographs, Thai, Lao, Myanmar or Khmer has no word boundaries, so that pair keeps the old
character-window scoring. Accent folding and punctuation handling are unchanged.
Files: `backend_host/src/controllers/verification/text_helpers.py` (and the offline mirror in
`scripts/jev_review/matchers.py`); tests in `tests/backend_host/test_text_match_score.py`.

## Verification

Re-scoring the same 81 labelled borderline text checks with the new scorer: false passes 30 to 6,
false fails 3 to 3, correct 48 to 72. Unit tests cover the cases above.
