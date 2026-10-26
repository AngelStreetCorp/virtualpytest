# BUG-0621: NavTargetDetector was single-scale (cv2.matchTemplate at 1.0×) — the vpt-windows GDI capture was at a different zoom than the template

**Date:** 2026-10-18
**Originally filed as BUG-0613 in the wave 8 commit message**;
renumbered to 0621 because a parallel agent claimed 0613 for
`hosts-devices-all-servers-empty`. See "Renumber note" below.
**Discovered on:** V6 run on `vpt-windows`. The LoL icon was
plainly visible in the 1920×1200 GDI capture (yellow circle
with a stylized "L" at pixel `(260, 660)`), but the detector
returned `None` with the original 130×168 template. Best
match score at 1.0× scale: **0.464** (below the 0.80 threshold).
**Severity:** medium — chain-blocking. The detector could not
find an icon that was clearly visible in the screenshot.

## What was happening

`cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)`
is a pixel-perfect normalized cross-correlation. If the
template was captured at one DPI / zoom and the screenshot is
at another, the match score drops. A 0.85× or 1.15× scale
mismatch is enough to break the match.

The original 130×168 RGBA template was extracted from a
2026-10-15 dry-run capture. The 2026-10-18 vpt-windows GDI
capture is 1920×1200 at a different DPI scale (the OS
primary monitor is 1024×768 per `GetSystemMetrics` but the
GDI capture returns 1920×1200 — the OS is doing some
non-trivial virtual-screen composition). The template's icon
footprint in the original capture was ~50×50, vs the actual
on-screen icon in the new capture which is ~70×70. The
template was effectively at ~0.71× of the live icon's size.

Best single-scale match at 1.0×: **0.464**. The detector
returned `None`.

## What ships

- **`shared/src/lib/game/leagueoflegends/vision_nav.py`**:
  `NavTargetDetector.detect()` now iterates over 9 scale
  factors (0.4×, 0.55×, 0.7×, 0.85×, 1.0×, 1.15×, 1.3×,
  1.5×, 1.6×) and keeps the single best peak. The 9
  fractions cover the vpt-windows GDI capture's full range
  (0.5×-1.0× of native) plus a generous bracket for
  screenshots captured at a different DPI than the template.

- Each scale re-sizes the template via
  `cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)`
  and runs `cv2.matchTemplate` once. The cost is `9 × base
  cost` ≈ 50-200 ms total for a 1920×1200 screenshot with a
  90×90 template (vs 5-20 ms for a single-scale match).

- The best peak across all scales is reported as the
  `NavHit.match_score`. The `bbox` is the matched region at
  the winning scale, not the 1.0× scale — so a peak at
  scale 0.7 returns a 63×63 bbox (vs the template's 90×90).
  The `normalized` center is computed against the SCALED
  bbox, so the click point is at the icon center regardless
  of which scale won.

- A new constructor parameter `scale_factors: Optional[Tuple[
  float, ...]] = None` lets callers override the default
  sweep (e.g. a tight 3-fraction sweep for a fast unit test,
  or a wider sweep for a high-DPI capture). Default
  preserved as `DEFAULT_SCALE_FACTORS` class constant.

- **No new tests** — the existing 13 detector tests
  (`test_leagueoflegends_vision_nav.py`) cover the
  single-scale and no-match paths. The multi-scale behavior
  is exercised by the V8 / V9 runs on `vpt-windows`.

- **One followup**: a unit test that asserts the multi-scale
  detector finds a template at 0.7× scale (i.e. assert the
  new code path is reachable). TODO in `TODO-handover.md`
  §3.

## Why this matters

- The detector is the perception layer of the whole chain. A
  detector that returns `None` for a visible icon blocks the
  click, which blocks the rest of the chain. Multi-scale
  matching is the standard fix for DPI / scale mismatches in
  CV pipelines.
- The 9-fraction sweep is a tradeoff between cost and recall.
  For the phase-0 chain (one click target per step) the
  50-200 ms cost is acceptable. For a hot loop (e.g. an
  agent playing 60 decisions per second) the sweep would
  need a cached-coarse-then-fine strategy; that's a future
  optimization, not a phase-0 concern.

## Renumber note

- This bug was originally claimed as **BUG-0613** in the
  wave 8 commit message (`bebbff02d`). A parallel agent
  committed `docs/bugs/BUG-0613-2026-10-18-hosts-devices-all-servers-empty.md`
  on origin/main between the wave 8 commit and the wave 9
  push. Re-filed as BUG-0621. The wave 8 commit message
  retains the 0613 reference.
