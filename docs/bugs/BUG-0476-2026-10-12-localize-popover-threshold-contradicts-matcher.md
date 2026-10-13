# BUG-0476 — Localize popover re-thresholded confidence and could contradict the matcher's verdict

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                              |
|-----------|--------------------------------------------------------------------|
| ID        | BUG-0476                                                           |
| Reported  | 2026-10-12                                                         |
| Status    | Fixed (pending deploy)                                             |
| Severity  | Medium                                                             |
| Area      | frontend (navigation popover) / backend_host (image_helpers)        |
| Fixed in  | Unreleased                                                         |
| Commit    | TBD                                                                |

---

## Symptom

On a confident match the popover read **"Possibly one of — 2 candidates"** or **"Below the 70%
confident-match threshold"** for a screen the matcher had accepted. The monitor overlay, the
navigation `verify_destination` check and `identify_screen()` all reported the same frame as a
**match**. An operator comparing the popover with the log saw two different answers for one frame.

## Root cause

`match_fingerprint_v5` already applies a confidence floor before returning: `identify_screen`
drops every candidate below `FP_MIN_CONFIDENCE = 0.55` (door 6, `REASON_DOOR6_DROPPED`). Anything
that survives in `candidates` is therefore at or above 0.55, and a non-empty `candidates` list
*is* the matcher's verdict.

The popover added a second, stricter gate of its own:

```ts
const CONFIDENT_THRESHOLD = 0.7;   // "matches the matcher's FP_MIN_CONFIDENCE (0.55-ish)"
if (cands.length === 1 && top.confidence >= CONFIDENT_THRESHOLD) return 'match';
```

Between 0.55 and 0.70 the matcher said *matched* and the UI said *not confident*. The comment
already admitted the mismatch ("0.55-ish") but nothing reconciled the two numbers.

Two smaller consequences of the same verdict model:

- The popover re-derived a verdict instead of reading one, so any future change to
  `FP_MIN_CONFIDENCE` silently diverged again.
- `cands.length > 1` forced `partial` regardless of score, so two screens both at 0.95 were
  labelled "Possibly one of" while the gold bar claimed a single confident match above them.

## Fix

The popover no longer re-judges the verdict. It reads the matcher's answer directly:

- `candidates.length === 1` → the matcher picked one screen; that row is the winner.
- `candidates.length > 1` → a genuine tie the matcher deliberately did not resolve; **neither**
  row is crowned.
- `candidates.length === 0` → an abstain. When `ranked` carries the near-miss tail, those rows are
  shown uncrowned, so the list never claims a match the matcher refused to make.

There is no UI-side confidence constant any more, so the two numbers cannot drift apart.

## Verification

- `frontend/src/components/navigation/Navigation_LocalizeButton.tsx` — no `CONFIDENT_THRESHOLD`
  remains; `grep -c CONFIDENT_THRESHOLD` is 0.
- Rendered against canned payloads for all seven states (confident match, tie, abstain with
  near-misses, no-signal, error, loading, and a legacy host with no `ranked` key) in **dark and
  light**: `tsc --noEmit` exit 0, `eslint` exit 0, `ui-check` clean, `i18n-check` 0 errors.
- The abstain fixture (`candidates: []`, `ranked: [live_tv 41%, sports 38%]`) renders both rows
  uncrowned — verified in screenshot, not only by reading the code.

## Not verified here

`cv2` is not installed on the development machine, so `tests/backend_host/test_*localize*.py`
could not run locally. The backend `ranked` addition was instead exercised against the real
`match_fingerprint_v5` with a stubbed `cv2`: `ranked` is the top 8 of 12 sorted by distance,
`candidates` and `excluded_count` are unchanged, and `ranked[0]` agrees with `best_excluded` on
both node and confidence. The suite should be run on a host with the imaging dependencies before
the next build.