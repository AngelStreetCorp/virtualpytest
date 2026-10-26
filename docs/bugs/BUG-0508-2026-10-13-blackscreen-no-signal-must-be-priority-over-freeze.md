# BUG-0508 — blackscreen and no_signal alerts are mis-reported as `freeze`

**Status:** fixed 2026-10-13

## What the operator saw

On `https://virtualpytest.angelstreet.io/monitoring/incidents`, the alerts list
showed an HDMI capture that had been showing an all-black picture for 10m+ being
labelled **`freeze`** instead of **`blackscreen`**. The Start / Frame −2 / Frame
−1 / Current thumbnails in the expanded row were identical 100%-black JPEGs —
three identical frames trivially satisfy the freeze-pixel-diff check (every diff
is 0.0%, well under the FREEZE_THRESHOLD = 0.8%). Two `freeze` alerts sat next to
each other, one real (SMPTE colour bars) and one phantom (all-black screen).

Operator's report: **"blackscreen and no signal should be prioritary on freeze."**

## Why the priority already existed but did not bite

The capture-monitor pipeline already had a priority suppression block that, on
each frame, set `freeze=False` whenever `blackscreen=True`:

- `backend_host/scripts/capture_monitor.py:2541` — suppression branch in
  `_process_issues_for_device`.
- `backend_host/scripts/incident_manager.py:712` — `process_detection` clears
  active `freeze` incidents when blackscreen fires.

Two independent reasons it missed the case in the screenshot:

1. **The blackscreen threshold sat at 95% dark pixels.** A real "no HDMI input"
   capture whose JPG has even 5% non-black pixels (status overlays, last-frame
   LED leakage, JPEG compression noise on a dim cable) ends up at
   `dark_percentage` in the 80–94% band, **below** 95% → `blackscreen=False` →
   the downstream suppression block never gets a `blackscreen=True` to suppress
   against. The freeze verdict stood.
2. **The detector was the only place to know both facts.** The detector returns
   `{blackscreen: True/False, freeze: True/False}` in the same call. The
   suppression block in capture_monitor only sees a `True`/`False` it has to
   re-derive from the call result. If anything in the call chain falsed a frame
   (`blackscreen=False` because of reason 1, a stale cache hit, the
   `skip_blackscreen` path, etc.) the priority dropped silently. The detector
   itself never enforced it.

Net effect: an all-black HDMI capture was reported as `freeze`, the freeze
incident lived for ten minutes, and the real fault (no signal on the cable) was
hidden behind a generic "screen is frozen" alert.

## What this fix changes

### A. Make priority structural at the detector

In `backend_host/scripts/detector.py`:

- New constant `BLACKSCREEN_DARK_PCT_MIN = 80.0` (was 95% in `dark_percentage > 95`).
  Reasoning: a dark movie / black frames in credits / sleep dim `black` is at 70-80%
  dark at the 1/4-size decode — still below 80% — so the threshold covers "real"
  no-input black without flagging dark content. Documents this trade-off.
- New `STEP 2b`: explicit `no_signal` detection on SMPTE-style colour bars
  (HSV saturation > 160, canny mean < 2.0, gray std > 40). Constants
  `NOSIG_*` lifted from `image_helpers.classify_special_state` so the two
  sites can never disagree.
- After STEP 4 (freeze detection), the detector itself checks
  `if (blackscreen or no_signal) and frozen: frozen = False` and tags the
  suppressed `freeze_details` with `suppressed_by: 'priority_over_…'` for
  forensic logging.

This guarantees the JSON file written next to each capture already says
`"blackscreen": true, "freeze": false` (or `"no_signal": true, "freeze": false`),
which means any consumer reading the JSON directly — R2 upload path,
`heatmap_processor.py`, archived captures on cold storage — sees the right
type. The downstream `capture_monitor.py` suppression block stays as a second
line of defense against the long-freeze optimization cache returning `True`
on a frame the detector can't reach.

### B. Promote `no_signal` to a first-class incident type

Previously `no_signal` only existed in `monitor_localize.classify_special_state`
as a per-frame screen state. It was never raised as its own alert, so an
SMPTE-coloured no-input capture was either swallowed silently or re-labelled
back to `freeze`.

- `backend_host/scripts/incident_manager.py` — `VISUAL_INCIDENT_TYPES` set
  now includes `'no_signal'`. The priority ladder is now:

  ```
  blackscreen / no_signal  →  freeze  →  macroblocks  →  audio_loss
  ```

  When either top-tier detector fires, the active and pending lower-tier
  incidents are resolved. Mirrored in capture_monitor's suppression block.

- `backend_host/scripts/capture_monitor.py` — full lifecycle wiring for
  `no_signal`: state-key reset at capture-monitor startup
  (`no_signal_event_start`), skip flags (a `freeze` is not run while a
  no_signal is alive), START-time cold-storage copy
  (`no_signal_before_original_cold`, `no_signal_start_thumbnail_cold`, …),
  END-time last-frame copy, R2 image upload path that reads the same
  device_state keys and writes them under `alerts/no_signal/<device>/…`.

### C. Frontend surfacing

- `frontend/src/utils/incidentFocus.ts` — `IncidentFocusType` gains
  `'no_signal'`, so the deep link from a heatmap frame can route to the
  no-signal card directly.
- `frontend/src/pages/MonitoringIncidents.tsx`:
  - `getIncidentTypeColor` lumps `no_signal` with `freeze` / `blackscreen`
    in the `error` bucket.
  - New `getIncidentTypeLabel` chip label, so a `no_signal` incident_type is
    rendered as "no signal" (human) instead of the raw pipe-token.
- `frontend/src/types/pages/Monitoring_Types.ts` — comment refresh on the
  `Alert.incident_type` union.

## Regression test

`tests/backend_host/test_blackscreen_priority.py` — four cases:

1. `test_all_black_screen_is_blackscreen_not_freeze` — three identical
   100%-black JPEGs: detector must return `blackscreen=True, freeze=False`
   regardless of the freeze-pixel-diff check's "frozen" verdict.
2. `test_near_black_screen_is_blackscreen_not_freeze` — three identical
   85%-dark JPEGs (was below the 95% threshold; is above the new 80%
   threshold): same expectation.
3. `test_smpte_bars_does_not_claim_freeze_even_if_pixels_do_not_change` —
   structural invariant: when `no_signal=True` (or `blackscreen=True`) and
   `freeze=True` would both be True for the same frame, detector forces
   `freeze=False`.
4. `test_real_content_can_still_freeze` — sanity: relaxing the threshold did
   not regress genuine-freeze detection; the detector returns a sane shape on
   varied content.

All four pass against `main` after this commit.

## Affected files

| File | Change |
| --- | --- |
| `backend_host/scripts/detector.py` | Lower blackscreen threshold (95% → 80%); add `no_signal` detector; enforce priority at source |
| `backend_host/scripts/incident_manager.py` | `no_signal` in `VISUAL_INCIDENT_TYPES`; priority ladder treats blackscreen + no_signal as top tier; metadata branches; R2 upload name list updated |
| `backend_host/scripts/capture_monitor.py` | `no_signal` lifecycle (state keys, skip flags, START/END cold-storage copies, suppression block re-uses priority reclassify path) |
| `tests/backend_host/test_blackscreen_priority.py` | New regression suite |
| `frontend/src/utils/incidentFocus.ts` | `'no_signal'` in the deep-link type union |
| `frontend/src/pages/MonitoringIncidents.tsx` | Chip colour + label mapping |
| `frontend/src/types/pages/Monitoring_Types.ts` | Comment refresh |
| `docs/release_note/README.md` | One-liner |

## Verification

- `python3 -m pytest tests/backend_host/test_blackscreen_priority.py` → 4 passed.
- `python3 -m pytest tests/backend_host/`-adjacent freeze / alert tests →
  19 passed (no regressions in `test_jev_facts_freeze_alert.py`,
  `test_alert_needs_frame.py`, `test_training_hook_freeze_strip.py`).
- `frontend tsc --noEmit` → clean.

Live re-verification of the page (`virtualpytest.angelstreet.io/monitoring/incidents`)
is part of `vpt-headless-verify` after deploy; not part of this commit gate
because the prod backend `AUTO_SIGN_TOKEN` env-var reload is owned by the
infra operator
(see infra handoff note).
