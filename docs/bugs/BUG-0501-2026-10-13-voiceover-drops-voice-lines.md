# BUG-0501 — Product-video voice-over silently dropped whole voice lines

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0501                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Closed                                                       |
| Severity  | Medium                                                       |
| Area      | scripts/promo (product videos)                               |
| Fixed in  | Unreleased                                                   |
| Commit    | `fccac0c78`, `6ca0ff1f3`                                     |

---

## Symptom

The owner, listening to video 25b, heard no voice for "Two Android phones, live on the Device page". `voiceover.py`
printed every line as placed, `voice_fit.py` reported zero spills and `promo_check.py` passed (voice_mismatch 0).
Video 25a's voiced file had three silent lines (scenes 2-4) and an audio track that decoded to 81.6 s for 67.6 s of
picture; it had been reported "voiced, verified" and was waiting to be uploaded.

## Root cause

`scripts/promo/voiceover.py` mixed the voice clips (`adelay` + `amix`) in the same ffmpeg filter graph that encoded
the picture (`tpad` + x264). In that graph `amix` dropped delayed inputs: whole lines went missing, a different set
on each run, while the same mix rendered alone was complete. Nothing in the harness listened to the result:
promo_check compared the SRT with the scenes and the container durations, never the decoded audio.

## Fix

- `voiceover.py` renders the voice track alone to a WAV, then muxes it with the picture in a second ffmpeg call.
- `voiceover.py` writes `<voiced>.voice.json` (every line's start, length, text) and decodes its own output: a line
  whose loudest 0.5 s stays under -45 dBFS fails the run.
- `promo_check.py` gains `voice_silent` (the same per-line check, from the voice map; a voiced take without a map
  is a hit) and measures `voice_mismatch` on the decoded audio length, not the container's.

## Verification

25b re-voiced: all 11 lines audible (per-line RMS -18 to -24 dB on the decoded track), promo_check PASS incl.
voice_silent, owner listened and approved, uploaded `Pt384v3ucDA`. 25a re-filmed and voiced with the fix: 10/10 lines,
PASS, uploaded `Sj9kyKj98s8`. The old 25a file fails the new counter.
