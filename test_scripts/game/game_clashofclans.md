# Clash of Clans Menu-Loop Farm Bot (`game_clashofclans`)

> **Local-only.** This bot targets a commercial Supercell game (§R1) — every
> screenshot, fixture, log, and metadata block stays inside the owner-controlled
> checkout. The pre-push hook refuses `**/clashofclans/**` paths in any staged
> tree (mirrors the TASK-33 §00000 ROM rule; TASK-81 §81.1 R4).

## Purpose

Unattended farm loop on the S21 FE over HDMI: open Clash of Clans, collect the
ready resource collectors, queue the troop training the clan is requesting,
donate to the clan chat, collect the weekly clan-capital chest, claim the daily
reward, and stop. **It does not play the 3-min attack phase, does not buy
gems / pass / offers, does not touch the Builder Base, and refuses to relaunch
if the §R5 account-warning guard ever trips.** Designed to be left alone for
hours while the owner is away (TASK-81 §81.1).

## How it is built

| Piece | Where | Role |
|---|---|---|
| Script | `test_scripts/game/game_clashofclans.py` (script id `game/game_clashofclans`) | Resolves the user interface, loads its tree, runs the loop, writes KPIs. No device code |
| Game library | `shared/src/lib/game/clashofclans/` (disjoint worker) | `vision.py`, `tactics.py`, `menus.py`, `runner.py` — perception, decision, menu driver, loop with §R5 guard and vpt-lease |
| User interfaces | `clashofclans-android-mobile`, `clashofclans-web` | Same tree, platform-specific actions. Built by `scripts/clashofclans_ui.py` |
| Controller | `android_mobile` `launch_app`, `open_url`, `click_element`, `tap_coordinates`, `dump_elements` | Drives the S21 FE over HDMI capture |

The android-mobile tree is the §81.1 target:

```
entry ─┬─ launch ──────────────→ home
       └─ install_game ─→ install ─────→ home

home ─┬─ collect (taps gold mine, elixir collector, dark elixir drill)
      ├─ train    (opens army, queues troops)
      ├─ donate   (clan chat: tap request row, donate per slot)
      ├─ clan_capital (collects the clan-capital weekly chest)
      ├─ daily    (collects the daily reward)
      ├─ settings (guard reads account state)
      ├─ clan     (clan page, used by donate)
      ├─ attack   (DISABLED: disabled_by: attack_opt_in)
      ├─ shop     (DISABLED: disabled_by: shop_enabled)
      └─ builder  (DISABLED: disabled_by: builder_enabled)
```

Every screen → home edge is `back=True` so the runner returns to the village
after each action without an explicit "back" tap.

| Action / node | `clashofclans-android-mobile` (S21 FE, 1080×2340 phone / 1280×720 capture) | `clashofclans-web` (stub, §81.2 future) |
|---|---|---|
| entry → launch | `launch_app com.supercell.clashofclans`, 4 s settle | (empty — reserved) |
| entry → install_game | `open_url(market://details?id=com.supercell.clashofclans, com.android.vending)`, 4 s settle | (empty — reserved) |
| install_game → install | `click_element "Install"` (text-based per GAME_BOTS.md rule 3) | (empty — reserved) |
| install → home | `click_element "Open"` + `launch_app`, 4 s settle | (empty — reserved) |
| home → collect | `tap_coordinates` gold mine / elixir / drill (placeholders, first-run tuned) + `click_element "Collect"` per popup | (empty — reserved) |
| home → train | `tap_coordinates` army button + `click_element "Train"` | (empty — reserved) |
| home → donate | `tap_coordinates` clan button + `click_element "Donate"` | (empty — reserved) |
| home → clan_capital | `click_element "Capital"` + `click_element "Collect"` | (empty — reserved) |
| home → daily | `click_element "Daily"` + `click_element "Claim"` | (empty — reserved) |
| home → settings | `tap_coordinates` settings gear | (empty — reserved) |
| home → clan | `tap_coordinates` clan button | (empty — reserved) |
| home → attack | DISABLED (`disabled_by: attack_opt_in`, §R1) | DISABLED |
| home → shop | DISABLED (`disabled_by: shop_enabled`, §R3) | DISABLED |
| home → builder | DISABLED (`disabled_by: builder_enabled`, §Out-of-scope) | DISABLED |
| install_game check | `waitForTextToAppear "Install"` over the centre Play-Store button | `waitForTextToAppear "Install"` |
| install check | `waitForTextToAppear "Open"` (up to 120 s for the install to finish) | `waitForTextToAppear "Open"` |
| home check | `waitForTextToAppear "Village"` over the top resource bar | `waitForTextToAppear "Village"` |
| collect check | `waitForTextToAppear "Collect"` over the popup | `waitForTextToAppear "Collect"` |
| settings check | `waitForTextToAppear "Settings"` over the top bar | `waitForTextToAppear "Settings"` |

To change a tree, edit `scripts/clashofclans_ui.py`, build the bundles
(`python scripts/clashofclans_ui.py --out <dir>`), and import them with
`POST /server/userinterface/import`, replacing the old user interface.

### Install path (§81.1.1)

When CoC is not installed (runner detects via `pm list packages`), the entry
takes the install sub-tree:

1. `entry → install_game` fires `open_url(market://details?id=com.supercell.clashofclans,
   com.android.vending)` in `com.android.vending`. The Play Store detail page
   opens straight on CoC.
2. `install_game → install` waits for the "Install" button (text-based) and
   clicks it via `click_element "Install"`.
3. `install → home` waits for "Open" to flip in (up to 120 s), taps it via
   `click_element "Open"`, then `launch_app com.supercell.clashofclans` to
   recover if Play Store lingers, and the home verification waits for
   "Village" to appear.

No `install_app` / `pm install` primitive exists on the HDMI capture path —
install has to go through the Play Store UI (TASK-81 §81.1 "Current state").

When CoC is already installed, the entry takes the direct path:
`entry → launch (launch_app com.supercell.clashofclans) → home`.

## What the bot does NOT do (§R1–R3, §Out-of-scope)

- **Attack play (§R1).** The Attack button is in the tree but marked
  `disabled_by: attack_opt_in`. The runner never picks it. `--attack_opt_in`
  defaults to `false` and exists only so a human can later flip it on a
  non-farming account for ad-hoc testing.
- **Real-money surfaces (§R3).** The shop edge is
  `disabled_by: shop_enabled` (default `false`). Even when enabled, the runner
  only ever claims the explicitly free rotating item — never Buy / Purchase /
  Subscribe / Gem / Offer / Pass / Trader / Supercell Store. If a UI change
  ever surfaces a "free" tap that is actually a confirm-purchase dialog, the
  bot must fail closed rather than proceed.
- **Builder Base (§Out-of-scope).** `disabled_by: builder_enabled` (default
  `false`). Same detection story as Attack, and adds zero resources to the
  home village.
- **Account-warning bypass (§R5).** No override flag exists. If the §R5 guard
  ever flips `account_warning_seen: true`, the runner stops, releases the
  vpt-lease, and refuses to relaunch for the same `userinterface` until a
  human clears it (`--clear_warning` at launch with the owner present).
- **Synthetic screenshots, logs, or fixtures landing on the public snapshot
  (§R4).** The pre-push hook refuses `**/clashofclans/**` paths in any staged
  tree. Synthetic tests use **drawn** frames, never captures from a live run.

## Usage

```bash
python test_scripts/game/game_clashofclans.py                                  # one 30-min cycle, auto UI
python test_scripts/game/game_clashofclans.py --max_runtime 3600               # one hour unattended
python test_scripts/game/game_clashofclans.py --userinterface clashofclans-android-mobile
python test_scripts/game/game_clashofclans.py --install_only                   # just the install sub-tree
python test_scripts/game/game_clashofclans.py --dry_run                        # walk the tree, no real actions
```

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--userinterface` | string | `auto` | `auto` picks the `clashofclans-*` userinterface whose models match the device. It also overrides a device's own default user interface |
| `--max_runtime` | int | `1800` | Hard stop in seconds; reaching it ends the run with `stop_reason=time_cap` |
| `--max_cycles` | int | `0` | Max number of full home → collect / train / donate → home cycles. `0` means unlimited (capped by `--max_runtime`) |
| `--idle_minutes` | int | `5` | Minutes to idle between cycles when nothing is ready (collectors, training queue, donations). The bulk of a real run is here |
| `--donate_policy` | `always` \| `on_requested` \| `never` | `always` | When to donate. `always` covers every cycle; `on_requested` only when the clan chat has open requests; `never` skips the step entirely |
| `--collect_policy` | `ready` \| `aggressive` \| `never` | `ready` | What to collect. `ready` taps the ready collectors only; `aggressive` also kicks upgrade timers; `never` skips |
| `--attack_opt_in` | bool | `false` | Unlocks the Attack button in the tree (`disabled_by: attack_opt_in`). The runner never picks it unless this is `true`. Reserved for ad-hoc non-farming testing only — do **not** use on the farming account (§R1) |
| `--dry_run` | bool | `false` | Walks the tree without invoking real actions. Smoke test for the UI bundle |
| `--install_only` | bool | `false` | Runs only the install sub-tree (`entry → install_game → install → home`) and exits. Used the first time on a fresh device |

## KPIs

`script_results.metadata` holds (§81.1 KPIs):

| Field | Type | Source |
|---|---|---|
| `gold_gained` | int | home gold-bar delta over the run |
| `elixir_gained` | int | home elixir-bar delta over the run |
| `dark_elixir_gained` | int | home dark-elixir-bar delta (may be 0 if the TH level doesn't have drills yet) |
| `troops_trained` | int | each successful barracks / spell factory queue counts one |
| `troops_donated` | int | each successful donate counts one |
| `capital_chests_collected` | int | each clan-capital reward cleared |
| `dailies_collected` | int | each completed daily quest cleared |
| `cycles_completed` | int | one full home → collect / train / donate → home loop |
| `attack_attempted` | bool | always `false` in v1; runner refuses the Attack button |
| `idle_seconds` | int | time spent waiting on collector timers + training queue (the bulk of a run) |
| `account_warning_seen` | bool | the §R5 guard; `false` for a clean run. If it flips, the runner stops and refuses to relaunch |
| `stop_reason` | str | `time_cap` / `max_cycles` / `guard` / `app_crashed` / `device_offline` |
| `userinterface` | str | `clashofclans-android-mobile` |
| `device_model` | str | `s21_phone` |
| `play_duration_s` | int | wall-clock |

## Expected timing (estimate, first live run will calibrate)

| | S21 FE (vpt-pi1, HDMI) |
|---|---|
| Action → settled screen | ~1.5–2.5 s (HDMI capture lag ~0.65 s, plus OCR + tap round-trip) |
| Full home cycle (collect → train → donate) | ~10–20 s when something is ready; ~1 min worst case |
| Idle cycle (nothing to do) | `--idle_minutes` minutes (the bulk of a real run) |
| First install on a fresh device | ~30–90 s (Play Store open + Install + wait + Open + launch) |

## Outputs

- **Metadata block** in `script_results.metadata` per §81.1 KPIs.
- **Step report**: each cycle emits a `home → <action> → home` step with the
  navigation executor's own screenshot. The §R5 guard emits an extra step with
  the warning-banner capture when it trips.
- **Local-only artefacts**: screenshots, step logs, fixture frames stay inside
  the owner-controlled checkout. The pre-push hook refuses `**/clashofclans/**`
  paths in any staged tree (§R4). No Grafana dashboard in v1 (the KPI surface
  is the metadata block; a dashboard can land once 4-hour soak runs are clean).

## Operator checklist before the first run

1. **Sign in to Google Play once on the phone.** The S21 FE must have a Google
   account signed in and that account must already own Clash of Clans, or the
   Play Store "Install" button is greyed and the path falls into a "Sign in"
   sub-tree that needs the owner's password. The bot does **not** own the
   sign-in flow (TASK-81 §81.1 "Current state").
2. **Pick the farming Supercell ID.** This bot runs only against the owner's
   personal account. Supercell bans are routine (§R1).
3. **Pick `--attack_opt_in=false`.** It defaults to `false` for a reason. Do
   not flip it on the farming account.
4. **One lease per run, no concurrent runs.** The S21 FE is the same slot the
   2048 showcase uses; the runner takes the vpt-lease at start and releases on
   every exit path (success, time cap, guard, exception). Use
   `scripts/infra-status-compact` or the lease registry to confirm the slot
   is free before launching.
6. **Start short.** First live run should be `--max_runtime 1800` (30 min)
   per §81.1.5; only extend to 4-hour runs (§81.1.6) after that one is clean
   and `account_warning_seen: false`.