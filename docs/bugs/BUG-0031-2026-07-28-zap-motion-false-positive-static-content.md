# BUG-0031 — Zap runs fail on near-static live content (motion false-positive)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0031                                                     |
| Reported  | 2026-07-28                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (false-positive fail on one channel entry per run)       |
| Area      | test_scripts/tv — zap_digit / zap_chup motion check          |
| Fixed in  | build 8713                                                   |
| Commit    | `96e1afa9e`                                                  |

---

## Symptom

A `zap_digit` run against `example_tv` failed on the **first** channel entry (ch 618) with
`Enter channel 618 — motion 0.5%` · **Motion Detection: NOT DETECTED (0.5% < 1.0% threshold)**,
while the next entry (ch 619) passed at 21.5%. The destination *was* playing — it had landed
on a live tennis broadcast during a near-static moment (players between points), so the two
compared frames barely differed. One false "frozen" verdict failed the whole run.

## Root cause

The post-zap check confirms the destination is playing by capturing two fresh frames and
diffing them; a change below `motion_threshold` (default 1.0%) counts as "not playing". Two
independent weaknesses made this over-strict:

1. **Sample window too short.** `ZapExecutor.detect_real_motion` hard-coded the gap between
   the two frames to `duration: 1.0` (`video_analysis_helpers.detect_motion_between_captures`
   sleeps `min(duration, 2.0)` between captures). Over 1s, slow/near-static content (a sports
   scene between plays) can move less than 1% even though it is genuinely playing.
2. **Any single miss failed the run.** Every channel entry was a hard gate, so one unlucky
   static frame — most likely on the very first, warm-up entry — sank an otherwise-good run
   and the run reported failure even though the KPI/zap measurement had been captured.

Separately, `zap_chup` never actually enforced the motion verdict: it did
`motion_detected = bool(real_motion)`, and `detect_real_motion` returns a **dict** (truthy)
whether or not motion was found — the verdict lives in `real_motion['motion']`. So a frozen
destination was reported as playing, and the only way `zap_chup` failed on motion was if the
detector itself errored (returned `None`) — exactly backwards from intent.

## Fix

Three coordinated changes (`shared/src/lib/executors/zap_executor.py`,
`test_scripts/tv/zap_digit.py`, `test_scripts/tv/zap_chup.py`):

- **Wider compare window.** `ZapExecutor` gains a `motion_duration` constructor arg (default
  1.0, so other callers are unchanged). `zap_digit`/`zap_chup` pass **2.0s** — the helper's
  cap — giving slow content more chance to move. A genuinely frozen channel still reads ~0%
  over any window, so this reduces false misses without weakening the frozen guard. Exposed
  as `--motion-window-s` (and `--motion-threshold` is now also a `zap_chup` arg).
- **First entry non-blocking.** The very first channel entry (`zap_digit`) / first iteration
  (`zap_chup`) is a warm-up: keys-OK-but-below-threshold motion is recorded (⚠️, with its %
  and compared frames) and the KPI measurement is kept, but it does **not** fail the run.
  Key-press failures still block, and every later entry stays strict.
- **`zap_chup` enforces the real verdict.** `bool(real_motion)` → `bool(real_motion and
  real_motion.get('motion'))`, and the verdict + compared frames are surfaced on the zap step
  (parity with `zap_digit`). This is a **behaviour change**: a frozen non-first iteration now
  correctly fails where it previously passed silently.

## Verification

- Both scripts compile (`py_compile`).
- Logic diff between the two repos (main / prod) is identical — only the `example_*` vs the
  overlay's own default UI-name lines differ, as intended.
- Reasoning check on the reported run: with the 2.0s window ch 618 gets a larger sample, and
  even if it still reads below threshold, being the first entry it is non-blocking → the run
  passes and the zap KPI is retained; ch 619 (21.5%) is unaffected.

> Not yet exercised against a live STB — validate on `example_tv` after deploy (a first-entry
> static scene should warn, not fail; a genuinely frozen later channel should still fail).
