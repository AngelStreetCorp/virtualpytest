# BUG-0626: phase-0 templates were the wrong icon/button, and Play was clicked in the wrong window

**Date:** 2026-10-18
**Discovered on:** live V10-V20 runs of the phase-0 chain on `vpt-windows`.
**Severity:** medium — the chain could not pass `click_lol_icon`.

## What was happening

1. `nav_templates/lol_icon.png` (BUG-0622) was a crop of the **Teamfight Tactics** icon plus the window edge, not the LoL icon.
   It scored 1.0 against the sidebar because it was cut from the same capture, and the click landed between the LoL and TFT icons.
2. `nav_templates/play_button.png` was an older, differently scaled crop.
3. The chain waited for the League Client window *before* clicking Play. On the real box, clicking the LoL icon only opens the
   LoL page inside the Riot Client; the gold Play button there launches the League Client (about 25 s later).
4. Both targets accepted a 0.80 match. A half-drawn Riot window produced a 0.90 false match on the Home page and a stray click.

## What ships

- `lol_icon.png`: 60×60 crop of the real LoL sidebar icon (bbox 202,568-262,628 of a 1920×1200 capture).
- `play_button.png`: 170×72 crop of the gold Play button on the Riot Client's LoL page.
- `phase0_runner.py`: step order is now `click_lol_icon` → `click_play_button` (Riot window) → `wait_for_league`.
- `vision_nav.py`: `min_match_score` 0.80 → 0.95 for both targets (true matches score 1.000).

## Verified

V20 on `vpt-windows`: `click_lol_icon` clicked (232, 598) at score 1.000, `click_play_button` clicked (409, 882) at score 1.000,
`wait_for_league` found the League Client after 25.6 s. The chain reports `ok: true`.
