# BUG-0847 — Every screen the monitor registers has `fingerprint = NULL`: named, but never fingerprinted

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0847                                                          |
| Reported  | 2026-10-23                                                        |
| Status    | Fixed (pending deploy)                                            |
| Severity  | Medium                                                            |
| Area      | backend_host (monitor) / backend (image helpers, screen registry)  |
| Fixed in  | build 90145 |
| Commit    | TBD                                                               |

---

## Symptom

The TASK-162 coverage report on the lab database (2026-10-23) splits 30 recurring screens (`seen_count > 10`) into
**5 labelled + fingerprinted** and **18 labelled with no fingerprint**. Not one of the 18 is old: they are the rows
`register_screen` creates today. In particular `vpt-pi1/device1` holds six rows labelled `Full-screen poster`, each with
`incident_type = 'screen'` (so written by the current monitor, not by the legacy freeze path) — and every one of them
has `fingerprint = NULL` while `region_center` is populated.

## Root cause

`monitor_localize._register_unknown` called the single registration function with only the *identity*:

```python
hit = register_screen(self.team_id, scope, fp, sample_image_path=_thumb_uri(img))
```

`fp` is `screen_memory.fingerprint_frame(img)` = `{dhash, region_center}` — two hashes used for matching.
`register_screen` takes a separate `fingerprint=` argument for the v6 blob and forwards it to
`register_screen_row(p_fingerprint => …)`, but the monitor never passed one, so every row it created stored
`fingerprint = NULL`.

The gap was invisible because identity still works: `screen_fingerprints_db.fp_from_blob` only reads
`regions.center` + `dhash` for matching, and those live in their own columns. What is lost is everything else the
matcher can use — the per-region dHashes (v5), the focused-tile crop dHash (v6) and the focus signature — plus the
audit trail `captured_at` and the coverage report's fingerprint age (TASK-107).

The reason it had never been noticed: the path to compute a real blob was `ImageHelpers.compute_fingerprint`, which
also runs two tesseract OCR passes (`title`, `text`). The monitor's own module docstring says it avoids the
title-translation layer because it is "too heavy for a per-second loop", so the fingerprint was skipped rather than
made cheap.

## Fix

`ImageHelpers.compute_fingerprint` takes a keyword-only `ocr: bool = True`. With `ocr=False` it returns exactly the
layers the matcher actually reads — `localize_verdicts_db.SAMPLE_KEYS` is `('v', 'dhash', 'regions', 'crop', 'focus')` —
and runs no tesseract subprocess. `monitor_localize._register_unknown` now passes that blob to `register_screen`
as `fingerprint=`, computed on the loop thread (before the daemon thread is spawned) and guarded by a try/except so a
fingerprint failure degrades to today's behaviour instead of dropping the registration.

OCR stays the default, so the capture/backfill path (`refingerprint.py`, the AV routes, `navigation_executor`) is
unchanged.

## Effect

Every screen registered from the deploy onward carries a real v6 fingerprint. Matching behaviour is unchanged (it
never read this column). The coverage report's `labelled + fingerprinted` bucket can now grow.

**Not backfillable.** The 18 existing rows have no recoverable frame — which is exactly why TASK-159 added the durable
thumbnail. Their `dhash`/`region_center` identity is intact, so nothing about their matching or naming is wrong; they
will gain a fingerprint only if that picture is registered again as a new row.

## Tests

`tests/backend_host/test_localize_settled.py` (the monitor's own fixture suite) plus
`tests/backend_server/test_screen_label_worker.py`: `compute_fingerprint(img, ocr=False)` returns every
`SAMPLE_KEYS` layer, contains no `title`/`text`, and the default still does.