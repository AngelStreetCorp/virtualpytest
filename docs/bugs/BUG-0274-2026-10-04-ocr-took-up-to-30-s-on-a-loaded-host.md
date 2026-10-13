# BUG-0274 — OCR took up to 30 s on a loaded host

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0274                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — text checks timed out or ran out their window       |
| Area      | `backend_host/src/controllers/verification/text_helpers.py`, `image_helpers.py` |
| Fixed in  | Unreleased                                                   |
| Commit    | `this commit`                                                |

---

## Symptom

On vpt-pi1 (stb4) the same text check on the same screen took 0.2 s to 17 s. Over 24 h the
stb4 `home_text` check had p50 0.61 s, p90 3.8 s, p99 21.7 s and max 31 s, the 30 s subprocess
timeout, which returns no text. A slow OCR leg also closed a sibling image leg's window
(BUG-0273).

## Root cause

tesseract is linked against libgomp and starts one OpenMP thread per core (4 on a Pi). The box
runs at load 8-10 (ffmpeg per capture, the capture monitor's localize OCR, whisper in the
transcript accumulator, the archiver). The four threads spin at barriers waiting for cores, so
wall time follows scheduling latency and CPU time grows 5-18x, which loads the box further.
There is no lock, queue or retry in the text path; it is one pass on the cropped area.

## Fix

Every tesseract subprocess in the verification and screen-identification paths runs with
`OMP_THREAD_LIMIT=1` (`shared/src/lib/utils/tesseract_env.py`). Measured on the same frame
during four CPU hogs: the 380x75 crop 7.3 / 3.9 / 0.28 s before, 0.19 / 0.19 / 0.19 s after;
the full frame 0.8-7.8 s before, 0.67-0.76 s after. Same text out.

## Verification

`tests/backend_host/test_tesseract_single_thread.py` (fails before the fix). pytesseract callers
(subtitle detection) are not covered yet.
