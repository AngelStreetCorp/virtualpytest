# BUG-0849 — The "no menu → poster" rule named two photos of a wall "Full-screen poster"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0849                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | High                                                             |
| Area      | backend_server (screen label worker) / ai                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                               |

---

## Symptom

The TASK-162 worker ran for the first time against the lab registry and named two rows `Full-screen poster`,
both on `vpt-pi4/device1`, with `seen_count` 21 and 18 and `confidence=HIGH` in its note.

Both are wrong. The stored frames are blurry photographs of a physical object — a wall or a door edge filling
the frame, out of focus. There is no menu, no artwork and no screen.

The `--verify` pass, run right after, disagreed with both (agreement **0/2**). Reading the two frames by eye
confirmed it: the verifier was right and the namer was wrong.

## Root cause

Two faults in the same place, both in how the worker treated TASK-159 G5's closed states.

**1. The rule has a precondition that was never checked.** `auto_classify_unknowns.STATE_HINTS` decides a screen
is a `Full-screen poster` by asking *"menu or no menu?"* and mapping `NOMENU` → poster. That inference is only
valid when a menu was possible — i.e. when the picture is a device UI. On a frame that is not a screen at all
the question is vacuous: a photograph of a wall has no menu, so it answers `NOMENU` and is confidently named a
poster. The state hints were written for `stb_tv` frames; the registry also holds frames from devices that
point a camera at the room (a Pi with a USB camera), and nothing said so.

**2. A closed yes/no was recorded as `HIGH` confidence.** The worker set `confidence='HIGH'` on any state-check
hit. A closed question is not a statement of confidence — it is one bit, and as above that bit can be
confidently wrong. Doing so also skipped the "low confidence → leave it for a human" rule the worker was built
to enforce: there was no low-confidence path for a state hit at all.

**Contributing:** a name written by the single writer is **permanent by design** (TASK-159 G4 — `name_screen_row`
will not replace a real name), so a wrong confident name cannot be undone by any later AI pass. Only a human can
fix it. The design is right; it makes the gate in front of it load-bearing.

## Fix

**A new closed question 0a, asked first, with unanimity:** *"is this a picture OF a device screen, or a photo of
the real world?"* — `SCREEN` or `PHOTO`. A `PHOTO` verdict is never named: the row goes to `label_state='review'`
and the human review list with the three votes in `label_note`.

**Unanimity, not a single answer.** Measured on this fleet: three *identical* calls of the free MiniMax VLM on one
stored frame answered `MOVING, STILL, STILL`. The `minimax_vlm` client posts only `prompt` + `image_url`, so no
temperature is sent and the provider samples on its own. Every two-sided gate therefore asks `--liveness-votes`
times (default 3) and requires every answer to agree; a split is not a decision and the row is left alone. The
same mechanism applies to the "moving or still" question, which is asked only for rows from the opt-in
`DEVICE<N>_LOCALIZE_SETTLED=1` path — a single still thumbnail cannot show motion, and a freeze or abstain row is
already settled by the path that made it.

**Confidence is now earned.** A state hit is only reached after two unanimous gates, and the note records both.
Open-set naming already required an explicit confidence word; its parser was also fixed (it truncated `HIGH` to
`HIG`, matched nothing and fell through to `LOW`, silently disabling every open-set name).

## Proof

- Before the fix, on the two real rows: named `Full-screen poster`, note `confidence=HIGH`, verify **0/2**.
- After the fix, on the same two rows: `not a device screen (3 vote(s): no, no, no) -> left for a human`, nothing
  named, `--verify` has nothing to disagree with.
- Both wrong labels were restored to their pre-run state (NULL) immediately; `name_screen_row` correctly refused
  to clear them, because its guard only touches NULL / `unknown_N` — so the revert was done directly and is
  recorded in TASK-162 §5. `scripts/screen_label_coverage.py --metric` is back to its baseline **7**.

## Tests

`tests/scripts/test_screen_label_worker.py`: a photo of a real thing is refused (`test_the_ui_gate_refuses_a_photo_of_a_real_thing`),
a split vote is not a decision (`test_a_split_vote_is_not_a_decision`), unanimity decides
(`test_unanimous_votes_decide`), a failed call does not count as a vote
(`test_a_failed_call_does_not_count_as_a_vote`), `NOMENU` does not match `MENU`
(`test_word_boundaries_stop_nomenu_matching_menu`), an unparsable confidence is LOW
(`test_no_parsable_confidence_means_low`), and liveness is only asked where the path cannot answer it
(`test_liveness_is_only_asked_where_the_path_cannot_answer_it`).