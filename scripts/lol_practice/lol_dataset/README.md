# lol_dataset: League of Legends replay dataset tool

Builds per-tick tables from one replay capture: a 10 Hz clock, entity rows on observed frames only, events, inferred actions,
features, teams, and a coverage report that says for each field whether it is filled, constant, partial or missing, and why.

Status: schema `0.2.0`. Built and checked on one capture (1920x1200, 1x playback, 15 fps). It is not general yet: see
"Known limits".

## Player names

Default export keeps the in-game Riot IDs (public names) in `players.jsonl`. Add `--anonymize --salt-file SALT.txt` to replace
every Riot ID with a salted SHA-256 hash (`player-<12 hex>`). Real-world identities are never part of the data.

## Install and test

```bash
pip install -r requirements.txt        # numpy<2, opencv-python<5, Pillow, pytesseract
pip install pytest && pytest           # synthetic inputs: no video, no tesseract
```

`pytesseract` needs the `tesseract` binary, and only for the HUD-clock alignment (`extract` without `--frame0`).

## Inputs

| Input | Flag | What it is |
|---|---|---|
| Replay video | `--video` | the capture (`.mkv`). Used for the HUD-clock alignment and thumbnails. |
| Replay API / Live Client log | `--log` | JSON lines with `t` (game seconds) and `camera` (`x`, `z`). Used for the camera at each frame. |
| Live Client events | `--events` | JSON with an `Events` list (`ChampionKill`, `Assisters`). |
| Roster | `--roster` | JSON list at game start: `championName`, `team` (`ORDER` or `CHAOS`), `riotIdGameName`. |
| Detections | `--detections` | JSON lines at about 5 Hz, one per frame: `{"t", "state", "world": {"units"}, "events", "inputs"}`. |

Detection format:
- `state`: the subject's values (`hp`, `hp_max`, `cs`, `kda`, `ad`, `as`, `ms`, `armor`, `level`, `items`, `dead`,
  `world_pos` (detector estimate), `screen_pos` (px), `spells`).
- `world.units`: `{kind, id, hp_frac, px: [x, y], dist_px, in_attack_range}`. `kind` is `ally_minion`, `enemy_minion`,
  `ally_champion` or `enemy_champion`. Champions carry no `id`.

The producer of these rows is not part of this package.

## Usage

```bash
python3 -m lol_dataset extract --video V.mkv --log L.jsonl --events E.json --roster R.json \
    --detections D.jsonl --subject ChampionName --gid GAME_ID --out OUT_DIR [--t0 60 --t1 480] [--frame0 52.5]
python3 -m lol_dataset view --dataset OUT_DIR --video V.mkv --html OUT_DIR/dataset.html
```

## Output (`OUT_DIR`)

| File | Content |
|---|---|
| `ticks.jsonl` | the 10 Hz clock: tick, time, detection time used, lag (ms), `observed` (lag within 50 ms) |
| `minions.jsonl` | one row per observed minion frame, stable `uid` per track (see Tracking), `alive` (false on the last frame of a dead track) |
| `champions.jsonl` | the subject (`uid` = champion name, `identity` = roster) and other detected champions (`uid` null, `identity` unknown) |
| `events.jsonl` | `champion_kill`, `assist` (Live Client), `minion_death`, `last_hit` (one per CS step), `level_up` |
| `actions.jsonl` | inferred `move` / `hold` from the subject's estimated velocity (conf 0.3); real inputs when present |
| `features.jsonl` | per observed tick: subject HP, level, CS, minion counts, nearest enemy minion (screen px), 30 s time bucket |
| `teams.jsonl` | per tick and team: kills, and the other team's kills as deaths |
| `turrets.jsonl`, `attacks.jsonl` | empty: no turret detector, and attacks are not generated (see Known limits) |
| `meta.json` | schema version, subject, team, frame-0 game time, alignment note, row counts, sanity stats |
| `coverage.json` | every field: `filled`, `constant`, `partial` or `missing`, with fill share, distinct values and reason |

Every table is JSONL, one file per table. Parquet is not written (the environment's pyarrow would not load against its NumPy).

## Rules

- **Clock.** Ticks are 100 ms of game time, `tick = round(t_s * 10)`. Frame 0 is the first HUD-clock step (one anchor, no
  per-segment fit yet).
- **Observed only.** Entity rows exist only on ticks that have a detection row within 50 ms. Nothing is carried or
  interpolated, so no row mixes one frame's px with another frame's camera.
- **Positions.** `x`, `y` (map units) are always null: there is no screen to world calibration. Screen px are in `px`, `py`
  with `pos_kind = screen_px`. `est_x`, `est_z` on the subject are the detector's own estimate, labelled
  `est_kind = detector_estimate_not_calibrated`. The camera is in `cam_x`, `cam_z`, read from the log at the frame's time.
- **Champion identity.** The subject's uid is its champion name. Other champions have `uid` null and `identity` unknown:
  no portrait or level-box matching yet, so no fake ids. Within a tick no uid repeats.
- **Team.** Each row's `team` is its real side (the subject's roster team for allies, the other team for enemies).
- **Events.** Live Client names are mapped to champion names through the roster. Riot IDs are not written.
- **Last hit.** One `last_hit` event per CS step (a +3 jump is three events at the same time). Matched to a `minion_death`
  within 0.3 s: `subject_uid` is that minion, conf 0.9 (one step) or 0.6 (split step). Unmatched: `subject_uid` null,
  method `cs_step_no_minion_death_within_0.3s`, conf 0.5.
- **Coverage.** A field is `constant` when it has at most one distinct value; never `filled` for a constant. Fill share is
  the non-null share of the rows.

## Tracking (minions)

Screen-px tracker over observed frames, separate per kind (ally, enemy):
- A detection joins a track when it lies within `MAX_STEP_PX` (150 px per 0.2 s, scaled by the time gap) and its HP is at most
  the track's HP plus `HP_RISE_TOL` (0.20). The track keeps the lower HP, so `hp_frac` never rises within a track.
- A track unseen for more than `TRACK_LOST_S` (2.5 s) is closed. Closed with HP at or below 10 %: `minion_death` (conf 0.8) and
  `alive = false` on its last row. Otherwise closed as lost.

Measured on game 8018174981: 374 tracks, median track life 4.2 s, 67 deaths, 307 lost tracks. A real minion lives far longer,
so the tracks still break at detector gaps. Gate and HP settings were picked by sweeping (see `build.py` constants); the
break-up is the detector's, not the tracker's, and is not fixed here.

## Known limits

- **Resolution.** Only 1920x1200 (screen centre, HUD crops and digit templates in `_vendor/`). Other resolutions need their own
  HUD crops and the centre constant.
- **Detector outside the package.** The subject state and every unit come from the detection rows. The producer is
  Garen-specific today: the subject locator and the bar detector are tied to one champion's level box and this capture
  format. `--subject` only selects the roster team.
- **False minions near the subject.** The detector sometimes reads the subject's own bar or outline as minions (for example
  two ally minions 70 px from Garen with no minion on screen at 1:00). Their rate is not measured here; they are not removed.
- **Minion track life.** Median 4.2 s against a much longer real lane life (see Tracking). Tracks are fragmented, not wrong.
- **Track speed.** The sanity number is screen px per second (p99 about 600 px/s, max about 750 px/s). It is not map units,
  so it can't be checked against the spec's 400 units/s bound until positions are calibrated.
- **HP clamp.** Track HP is clamped, so the raw rises are not visible in the output (`hp_rises_within_track` is 0 by construction).
- **Not built:** turrets and plates, attack attribution (attacks are not generated: HP drops have no attacker and are
  jittery), wave and slot estimates, minion type and max HP, decision points, minimap positions, buffs, auto timers, resources,
  team gold and towers.
- **Naming.** Two fields keep a px suffix on purpose (`dist_to_subject_px`, `nearest_enemy_minion_px`): the spec names
  (`dist_to_subject`) mean map units, and these are screen pixels. Events use `actor_uid` and `subject_uid` as in the spec.
- **Clock.** One anchor for the whole capture. A per-segment fit with the HUD-second check (spec §2) is not implemented.

## Versioning

`schema.py` holds `SCHEMA_VERSION` and the column lists. Bump it when a column changes meaning; `meta.json` records the version
each build used.

## Licence

Not chosen yet; the owner sets it before publishing.
