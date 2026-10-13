# Super Kirby Clash fight bot (TASK-51)

`game_kirby.py` plays one or more boss fights of *Super Kirby Clash* on a Nintendo Switch
(`nintendo_switch`, HDMI capture at 1280x720, 5 JPEG/s) using a real-time loop:

- **bot**: reads the latest capture every frame, picks a Switch action (press / sequence / stick /
  hold / release) from the current tactic, fires it.
- **menu driver**: a small state machine that gets the Switch from any screen (village, results,
  reward, dialog, ...) to the start of the *Hornhead* quest fight. Runs once before fight 1 with
  `--start any` (default) and again after every fight so the bot can chain fights.
- **Jev** (`--chooser jev`, default): asks the platform's decision model on a 2 s / event cadence
  in a background thread — never blocks the bot.
- `--chooser fixed`: same bot, always with the `rush` tactic.

The script ends when the fight loop ends (Kirby's HP bar gone for 25 frames, ~5 s), the time
budget runs out, the HUD never appears for 10 s, or the menu driver fails to reach the fight.

## Args

| arg | type | default | choices | meaning |
|---|---|---|---|---|
| `--chooser` | str | `jev` | `fixed` \| `jev` | `fixed`: one tactic only (rush). `jev`: decision model. |
| `--max_duration` | int | `170` | — | Hard stop in seconds per fight. |
| `--start` | str | `any` | `any` \| `fight` | `any`: menu driver before fight 1. `fight`: fight must already be on screen. |
| `--fights` | int | `1` | — | Number of fights to play. After each fight the menu driver re-opens the quest. |

## Flow (per fight)

1. Menu driver (`--start any` or after the first one): walk from the village to the Hornhead
   fight screen by detecting banners ("Form a Team", "Select Area", "Select Quest") and
   confirmations ("Are you ready to set off on your quest?"). Records the screens seen.
2. Fight loop (`KirbyRunner.run`): until the HP bar disappears for 25 frames, the time budget
   runs out, or 10 s without a fight HUD on screen. Per-frame bot action; Jev on a 2 s / event
   cadence. Same chooser for all fights in the run.
3. After the fight, the menu driver is run again (for fight 2..N) so the next "Play the same
   quest" → Set Off → fight sequence starts.

## Reports / KPIs

`script_results.metadata` carries top-level fields and a `fights` list:

| top-level | meaning |
|---|---|
| `fights_played` | Number of fights the script actually attempted (≤ `--fights`). |
| `fights_over` | Of `fights_played`, how many ended with `end_reason == "fight_over"`. |
| `menu_s_total` | Sum of `menu_s` across every menu driver invocation in the run. |
| `chooser` | The chooser used for every fight (`fixed` or `jev`). |

Each element of `fights` holds `fight`, `menu_s`, `menu_steps` and the fight's KPIs: `fight_s`, `end_reason`, `kirby_hp_end`, `mate_hp_end`, `frames`, `loop_ms_p50`, `decisions`, `tactics`, `jev_ms_p50`, `jev_cost_usd`, `jev_input_tokens`, `jev_output_tokens`, `actions_sent`, `chooser`.

Each step carries the menu-driver run's `steps`, `menu_s`, and `screens` list (e.g. `[village,
village, village_at_board, game_mode, select_area, select_quest, form_team, confirm_setoff,
dialog, fight]`), plus an evidence screenshot.

## Threshold notes

Vision thresholds are HSV, measured on real fight frames:

- Kirby (foreground, plus his pink "Lab 1" tag): `H >= 160 or H <= 3`, `S > 150`, `V > 180`, rows
  `y < 560`. Need ≥ 150 px.
- Boss body: `105 <= H <= 150`, `S > 90`, `V > 60`, rows `250 <= y < 560`, columns `x < 1200`. Need
  ≥ 2000 px.
- HP bar (Kirby: columns 157..350; teammate: 488..640) is read in rows 668..680, a column is filled
  when any pixel there matches `H <= 40` or `50 <= H <= 85`, with `S > 120, V > 120` (the bar turns
  yellow, then red, when low).
- The fight is "live" while Kirby's HP bar is on screen. The clock icon is not used: it turns grey
  during banners.
- Safety rule, over every tactic: Kirby HP < 30 % and the boss closer than 350 px makes the bot step
  away for 300 ms and guard (`r`, 300 ms hold).

The menu driver OCR:

- **Banner** (top-left red/orange strip): crop `img[15:95, 60:480]`, mask white text
  (`V > 200 and S < 70`), invert to black-on-white, resize x2 with `INTER_NEAREST`, tesseract
  `--psm 7`. Reads "Form a Team", "Game Mode", "Select Area", "Select Quest", "Shoppe", "Weapons".
- **Small regions** (`menus.REGIONS`, grey crop x2): `confirm` (`--psm 6`, "set off" →
  confirm_setoff), `choice` (`--psm 6`, "same quest" → quest_choice), `vigor` (top-right bar,
  `--psm 7`, "igor" → village). Never full-frame OCR: on a loaded Pi 4 it took ~10 s and split
  "Vigor" into "Vig Or)"; a crop takes ~1 s.
- **Dialog box**: the beige story box at the bottom (rows 575..700, ≥ 80 % box-coloured pixels).
  A village story dialog shows the Vigor bar too; the box makes it `dialog` (A), not `village`.
- **Quest bubble**: rows 100..420, connected components of near-white pixels (`V > 225 and S < 30`)
  with width 100..220, height 40..90, area > 3000; OCR of the plain grey crop at x2 `--psm 7`
  (a threshold would invert the dark text); True when "quest" appears. The tree's "Talk" bubble reads "".

## Menu driver actions

| class | action |
|---|---|
| `fight` | stop, reached. |
| `black` | no input, wait 1 s. |
| `dialog` | `press:a`. |
| `confirm_setoff` | `press:a` (Yes is the default). |
| `quest_choice` | `press:down`, `press:a` (default highlight = "Play a different quest"). |
| `form_team` | `press:a` only when the "Set Off" button is highlighted (bright red, `menus.setoff_highlighted`); otherwise `press:down`. The cursor starts on Kirby's card (A there opens Change Role) and a down sent while the screen slides in is dropped. |
| `change_role` | `press:b`. |
| `game_mode` | `press:a` (Story Quest). |
| `select_area` | `press:left`, `press:left`, `press:a` (Seaside is leftmost). |
| `select_quest` | `press:a` when the right-hand card names Hornhead (OCR `quest_card`), else `press:up` (the list wraps, the cursor starts on the last quest played). |
| `shop` | `press:b` (never A — Gem Apples can lead to real purchases). |
| `village_at_board` | `press:up` (opens the quest board). |
| `village` | sweep: first step `stick:left,left,2000`; each further step `stick:left,right,250`; after 20 rights without a bubble restart; max 2 sweeps. |
| Same class 8× (not black, not village) | press `b` once (backs out of unexpected menus). |
| `max_steps` reached | `reached False`, `error = "menu: max steps"`. |

## Tactic list (Jev options)

| id | facts |
|---|---|
| `rush` | close in on the boss and mash attack; the safest pressure when Kirby is healthy. |
| `charged` | close in, hold attack ~0.8 s, release; trades rhythm for raw damage. |
| `jump_attack` | jump then attack; avoids ground charges from the boss. |
| `guard_counter` | guard ~0.4 s then two attacks; best right after a telegraphed hit. |
| `keep_distance` | stay ~350 px away, step in only to land a hit; a safe neutral. |
| `retreat` | move away and guard; use when both Kirbys are low on HP. |