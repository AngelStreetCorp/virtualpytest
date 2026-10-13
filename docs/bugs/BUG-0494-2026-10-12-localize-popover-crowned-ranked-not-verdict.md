# BUG-0494 — Localize popover crowned the raw ranking instead of the verdict, and misexplained abstains

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                              |
|-----------|--------------------------------------------------------------------|
| ID        | BUG-0494                                                           |
| Reported  | 2026-10-12                                                         |
| Status    | Fixed (pending deploy)                                             |
| Severity  | Medium                                                             |
| Area      | frontend (navigation popover)                                      |
| Fixed in  | Unreleased                                                         |
| Commit    | `2289edffe`                                                        |

---

## Symptom

Checked against [FINGERPRINT.md](../agent/navigation/FINGERPRINT.md) ("The six abstain doors",
"Reading a result"), the Localize popover showed four things wrong:

- On a menu (nav path) it could crown a screen the matcher had **rejected**. The title picked
  `home_tvguide`, but the gold row read `home 73%`.
- Two candidates of different confidence (a genuine ambiguity, "a real answer, not a bug") showed
  one crowned winner.
- Every abstain read "No screen scored above the matcher's confidence floor", even when the floor
  was not the reason. The first live run on node1 abstained on a near-empty frame (door 1,
  `low-content frame`), and the popover blamed door 6.
- The per-frame classifier answers (motion, loaded, overlay, playback, error) were no longer shown
  anywhere after the Diagnostics dialog was removed (TASK-88 row 5).

## Root cause

BUG-0476 set the right rule (crown only `candidates.length === 1`) but the rows still came from
`ranked`, and the crown went to `ranked[0]`. `ranked` is `match_fingerprint_v5`'s region preview,
taken **before** the title gate, title disambiguation, dHash narrowing and the nav-path confidence
rewrite in `identify_screen`. On a nav menu the title decides and confidence is re-scored as
`0.6 + 0.4 * title_score`, so `ranked[0]` and `candidates[0]` can be different nodes. The tie test
compared the top two `ranked` confidences instead of reading `candidates.length > 1`.

## Fix

`Navigation_LocalizeButton.tsx`:

- Rows are `candidates` first, with their own confidence, then the `ranked` nodes they beat.
- The crown goes to `candidates[0]` only when there is exactly one candidate; with more than one,
  every candidate row is bold and none is crowned ("Tie between N screens" in step 2).
- An abstain opens with **No match** and the reason. Doors 1–3 are put in plain words; doors 4–6
  keep the matcher's own sentence.
- Step 2 shows a one-line **Screen state** from `classifier_diagnostics`, skipping `unknown` and
  `not_applicable`, and falls back to `unconfirmed_candidate` ("Low confidence, not confirmed")
  when the second opinion turned a single answer into unknown.

## Verification

- `tsc --noEmit` and `eslint` clean.
- The real component rendered against three canned payloads: a nav match where `ranked[0]` is
  `home` but the verdict is `home_tvguide` (gold row is `home_tvguide 98%`, screen-state line
  shows `static 0.4% · loaded · no overlay · no error`); a two-candidate tie (no crown, both bold,
  "Tie between 2 screens"); and the node1 `low-content frame` payload ("No match — The frame is
  nearly empty …").

## Not verified here

No confident STB match was run live: node1's only device with a Localize interface is
host-clone-1's desktop (`sauce-demo`), which abstained.
