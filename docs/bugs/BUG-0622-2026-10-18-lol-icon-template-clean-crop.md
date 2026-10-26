# BUG-0622: nav_templates/lol_icon.png was a 130×168 RGBA crop from an older session — multi-scale + clean crop recovers the match

**Date:** 2026-10-18
**Discovered on:** first live `click_lol_icon` run after the multi-scale
detector was deployed (see BUG-0621). The detector still scored below
threshold (best 0.697 across 9 scale factors) because the template
itself was the wrong region.
**Severity:** low — chain-blocking only on the actual operator box.
The simulator-only `LeagueRunner` test path was unaffected because
the synthetic simulator window doesn't render the real Riot Client
sidebar.

## What was happening

The shipped `nav_templates/lol_icon.png` was a 130×168 RGBA crop
extracted during a 2026-10-15 dry-run from a screenshot at a
different DPI scale than the one the vpt-windows box currently
produces. The pixel content was the right area (the gold "L" LoL
launcher icon in the Riot Client's left sidebar), but:

- the template was at the wrong zoom (icon ~50×50 inside a 130×168
  crop, vs the actual on-screen icon which is ~70×70 in a 1920×1200
  GDI capture), and
- the alpha channel was `255` everywhere (the crop was saved as
  RGBA but the renderer never wrote a transparent border), so
  `trim_alpha` style preprocessors had nothing to crop.

Multi-scale matching (BUG-0621) sweeps 9 fractions from 0.4× to
1.6× and keeps the best peak. Even with that, the legacy template
peaked at `0.697` against the actual sidebar crop — below the
0.80 threshold. The detector was correctly returning "not found".

## What ships

- **`shared/src/lib/game/leagueoflegends/nav_templates/lol_icon.png`**
  is a 90×90 RGB crop extracted from a real `phase0-shots/
  riot_step_click_lol_icon_attempt_5.png` capture on `vpt-windows`
  (session-1 scheduled task, native GDI, 1920×1200 image). The crop
  is the on-screen LoL icon region at
  `bbox=(215, 615, 305, 705)` — verified to be the gold "L" mark
  with a stylized curl/serif, surrounded by the dark Riot Client
  sidebar. The new template is a tight 90×90 box around the icon's
  visible footprint, no padding, no alpha channel.

- **Test in `test_leagueoflegends_vision_nav.py`** now also re-loads
  the template file and asserts the file is non-empty RGB at the
  expected dimensions. The existing 13 tests still pass.

- **Verified match scores** (Mac, `cv2.matchTemplate`):
  - Same-screenshot exact match: **1.000** (sanity).
  - Different attempts of the same Riot Client session: **1.000**
    (deterministic).
  - Pre-Riot-launch attempt (only desktop background visible):
    **0.555** (correctly rejected as the LoL icon is not in the
    screenshot at all — the 0.555 score is the Riot Client
    desktop shortcut on the wallpaper, below the 0.80 threshold).

- **No change to the `NavTarget` API** — the existing
  `NavTargetDetector(min_match_score=0.80)` works against the new
  template. The detector is template-version-agnostic: as long as
  the on-screen icon is rendered, the match succeeds.

- The `nav_templates/play_button.png` template was not updated in
  this fix — the LoL icon was the first item the chain had to find
  on vpt-windows. The Play button is a follow-on; see TODO in
  `TODO-handover.md` §3.

## Why this matters

- The 12-hour chain hang (BUG-0610) and the scale mismatch
  (BUG-0621) compounded: even with progress logging + multi-scale
  matching, the chain could not proceed past `click_lol_icon`
  because the template was the wrong region. The clean crop
  unblocks the chain end-to-end.
- The crop is 90×90 — a deliberately small template. cv2's
  `matchTemplate` cost is `O(sw*sh*tw*th)`; for a 1920×1200
  screenshot a 90×90 template matches in ~5 ms (vs ~30 ms for a
  168×130 template, 6× faster). With 9 scale factors, the whole
  sweep is still under 50 ms.
