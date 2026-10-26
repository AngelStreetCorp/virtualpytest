"""Build the DATASET_SPEC tables for one replay capture: 10 Hz clock, entity rows on observed frames, events, coverage.

Inputs (see README.md):
  video       the capture (.mkv): HUD-clock alignment (frame 0 = game time)
  log         Replay API / Live Client log (.jsonl): camera position per sample
  events      Live Client events (.json, {"Events": [...]})
  roster      roster at game start (.json list)
  detections  per-frame detection rows at about 5 Hz (README.md)

Rules (review of build 1, 2026-10-19):
  - Entity rows exist only for frames observed on a tick (lag <= 50 ms). No carried or interpolated rows.
  - x, y (map units) are null: no screen to world calibration yet. Screen px (px, py) are kept and labelled as px.
  - Champion uid = champion name when the roster names it (the subject only); other champions carry uid null.
  - Minions: own tracker (screen-px gate, no HP rise, deaths from low-HP track ends).
  - last_hit: one event per CS step, matched to a minion death within 0.3 s, else subject null with the reason.
Nothing is invented: a field that no input can fill stays null, and coverage.json says why.
"""
import bisect
import json
import math
import os
from collections import defaultdict

from .schema import (SCHEMA_VERSION, TICK_HZ, OBS_LAG_S, CARRY_LAG_S, TABLES, MISSING_REASON)
from .tracker import track_frames, to_stage, MAX_SPEED_PX
from .waves import assign as assign_waves

SIDE_OF_TEAM = {"ORDER": ("blue", "100"), "CHAOS": ("red", "200")}

# tracker and event gates (screen px and seconds; no map units)
MAX_STEP_PX = 150.0        # a minion may move at most this many screen px per 0.2 s between two observed frames (a gate)
TRACK_LOST_S = 2.5        # a track unseen this long is closed (bridges detector gaps)
DEATH_HP = 0.10           # a track closed with its last HP fraction at or below this is a death
HP_RISE_TOL = 0.20        # a match may read up to this much HP above the track's; the track keeps the lower value (HP never rises)
LAST_HIT_WINDOW_S = 0.3   # CS step matched to a minion death within this window
LAST_HIT_WIDE_S = 0.6     # the same, wider: reported only, as the share of CS steps a death could explain


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def nearest(times, t, tol):
    """Index of the sample nearest t in the sorted list ``times``, or None when none lies within ``tol`` seconds."""
    i = bisect.bisect_left(times, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(times) and (best is None or abs(times[j] - t) < abs(times[best] - t)):
            best = j
    if best is None or abs(times[best] - t) > tol + 1e-9:
        return None
    return best


def frame0_game_time(video_path):
    """Game time of video frame 0: the first frame where the HUD clock steps to the next second, minus its index / fps.
    None if the clock is not readable in the first 6 seconds."""
    import cv2
    from PIL import Image
    from ._vendor import hud as clock_hud
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    prev = None
    try:
        for idx in range(int(fps * 6)):
            ok, fr = cap.read()
            if not ok:
                break
            c = clock_hud.clock(Image.fromarray(fr[:, :, ::-1]))
            if prev is not None and c is not None and c == prev + 1:
                return c - idx / fps
            prev = c if c is not None else prev
    finally:
        cap.release()
    return None


def _frames_15fps(path, my_fill, log, log_t, t0, t1):
    """Per-frame minion units from the 15 fps detector (detect_bars_15fps.py): one frame each, tick = nearest tick."""
    out = []
    for r in read_jsonl(path):
        t = r["t"]
        if not (t0 - 1e-6 <= t <= t1 + 1e-6):
            continue
        j = nearest(log_t, t, 0.1)
        cam = (log[j].get("camera") or {}) if j is not None else {}
        units = [{"kind": "ally_minion" if u["fill"] == my_fill else "enemy_minion", "px": u["px"],
                  "hp_frac": u["hp_frac"], "dist_px": None, "in_attack_range": None} for u in r["units"]]
        out.append({"tick": round(t * TICK_HZ), "t": t, "row": {"world": {"units": units}},
                    "cam_x": cam.get("x"), "cam_z": cam.get("z")})
    return out


def _enemies_by_tick(path, frame0):
    """Enemy champion names read from the name tag above each bar (enemy_names_30fps.py), by tick. px_dist is the screen
    distance from the bar anchor to Garen's screen position (968, 540), in screen px."""
    if not path or not os.path.exists(path):
        return None
    out = {}
    for r in read_jsonl(path):
        t = r["t"]
        if frame0 is None:
            continue
        tick = round(t * TICK_HZ)
        out[tick] = [{"name": b["name"], "px_dist": round(math.hypot(b["x0"] + 53 - 968, b["bar_y"] - 540))}
                     for b in r["bars"] if b.get("name")]
    return out


def _ready(sp):
    """Ability readiness from the detector: True ready, False on cooldown (digits read), None unknown."""
    if not sp:
        return None
    if sp.get("ready"):
        return True
    if sp.get("ready_in_s") is not None:
        return False
    return None


def _grid_frames(det, log_t, log, t0, t1):
    """Detection rows that are observed on a tick: (tick, row, lag_ms, camera (x, z) at the same time)."""
    frames, seen_ticks = [], set()
    for r in det:
        tick = round(r["t"] * TICK_HZ)
        if not (round(t0 * TICK_HZ) <= tick <= round(t1 * TICK_HZ)) or tick in seen_ticks:
            continue
        lag = (r["t"] - tick / TICK_HZ) * 1000
        if abs(lag) > OBS_LAG_S * 1000 + 1e-6:
            continue
        seen_ticks.add(tick)
        j = nearest(log_t, r["t"], 0.1)
        cam = (log[j].get("camera") or {}) if j is not None else {}
        frames.append({"tick": tick, "t": r["t"], "lag": round(lag, 1), "row": r,
                       "cam_x": cam.get("x"), "cam_z": cam.get("z")})
    return frames


def build_tables(video, log_path, events_path, roster_path, detections_path, subject, t0, t1, gid,
                 frame0=None, minion_detections=None, minion_gate_min=None, enemy_names=None):
    """Return (tables, meta, coverage). ``tables`` maps table name -> list of row dicts."""
    roster = json.load(open(roster_path, encoding="utf-8"))
    me = next((p for p in roster if p.get("championName") == subject), None)
    if me is None:
        names = [p.get("championName") for p in roster]
        raise SystemExit(f"subject champion {subject!r} is not in the roster: {names}")
    side, team_id = SIDE_OF_TEAM.get(me.get("team"), ("unknown", "unknown"))
    other_team = "200" if team_id == "100" else "100"
    champ_of_riot = {p.get("riotIdGameName"): p.get("championName") for p in roster}
    team_of_champ = {p.get("championName"): SIDE_OF_TEAM.get(p.get("team"), ("unknown", "unknown"))[1] for p in roster}

    det = sorted([r for r in read_jsonl(detections_path) if t0 - 0.2 <= r["t"] <= t1 + 0.2], key=lambda r: r["t"])
    log = read_jsonl(log_path)
    log_t = [s["t"] for s in log]
    events_raw = json.load(open(events_path, encoding="utf-8")).get("Events", []) if os.path.exists(events_path) else []
    if frame0 is None and video and os.path.exists(video):
        frame0 = frame0_game_time(video)

    tables = {k: [] for k in TABLES}
    ticks = list(range(round(t0 * TICK_HZ), round(t1 * TICK_HZ) + 1))
    frames = _grid_frames(det, log_t, log, t0, t1)
    observed_ticks = {f["tick"]: f for f in frames}
    det_t = [r["t"] for r in det]
    for k in ticks:
        t = k / TICK_HZ
        j = nearest(det_t, t, CARRY_LAG_S)
        lag = round((det[j]["t"] - t) * 1000, 1) if j is not None else None
        tables["ticks"].append({"game_id": gid, "tick": k, "t_s": round(t, 2),
                                "src_t": det[j]["t"] if j is not None else None, "lag_ms": lag,
                                "observed": k in observed_ticks, "has_row": j is not None})

    # 1. minions: camera-compensated tracker (tracker.py), then wave, slot and type (waves.py)
    if minion_detections:
        frames15 = _frames_15fps(minion_detections, my_fill="enemy" if team_id == "200" else "ally", log=log, log_t=log_t,
                                 t0=t0, t1=t1)
        minion_rows, tracks, causes = track_frames(frames15, gid, gate_min=minion_gate_min)
    else:
        minion_rows, tracks, causes = track_frames(frames, gid)
    travel = assign_waves(tracks)
    by_key = {("ally" if tr.kind == "ally_minion" else "enemy", tr.id): tr for tr in tracks}
    for row in minion_rows:
        tr = by_key[(row["rel"], row.pop("_track"))]
        row["side"] = side if row["rel"] == "ally" else ("red" if side == "blue" else "blue")
        row["wave"], row["slot"], row["mtype"] = tr.wave, tr.slot, tr.mtype
        row["mtype_source"] = "wave_rule" if tr.mtype else None
        tables["minions"].append({c: row[c] for c in TABLES["minions"] if c in row})
    deaths = []
    for tr in tracks:
        if tr.closed == "death":        # only a track that ended at HP <= 10 %; probable kills are not deaths (review 3, section 5)
            rel = "ally" if tr.kind == "ally_minion" else "enemy"
            uid = f"{gid}-{rel[0]}m{tr.id}"
            deaths.append({"t": tr.last_t, "uid": uid, "sx": tr.last()[1], "sy": tr.last()[2], "used": False})
            tables["events"].append({"game_id": gid, "tick": round(tr.last_t * TICK_HZ), "t_s": round(tr.last_t, 2),
                                     "event_id": f"death{tr.id}_{rel[0]}", "kind": "minion_death", "actor_uid": None,
                                     "subject_uid": uid, "value": None,
                                     "conf": 0.8,
                                     "method": "track_end_" + tr.closed})

    # 2. champions: the subject from the detection state; other detected champions without identity
    prev_cs, prev_level, prev_obs_t = None, None, None
    subject_obs = []
    for f in frames:
        r, t, k = f["row"], f["t"], f["tick"]
        st = r.get("state") or {}
        cam_x, cam_z = f["cam_x"], f["cam_z"]
        base = {"game_id": gid, "tick": k, "t_s": round(t, 2), "observed": True, "src": "vision"}
        for ordinal, u in enumerate(r.get("world", {}).get("units", [])):
            if "champion" not in u.get("kind", ""):
                continue
            rel = "ally" if u["kind"].startswith("ally") else "enemy"
            tables["champions"].append({**base, "uid": None, "champion": None, "identity": "unknown",
                                        "side": side if rel == "ally" else ("red" if side == "blue" else "blue"),
                                        "rel": rel, "team": team_id if rel == "ally" else other_team,
                                        "is_subject": False, "hp_frac": u.get("hp_frac"),
                                        "px": u["px"][0] if u.get("px") else None,
                                        "py": u["px"][1] if u.get("px") else None,
                                        "x": None, "y": None, "pos_kind": "screen_px", "ordinal": ordinal,
                                        "alive": True, "dist_to_subject_px": u.get("dist_px"),
                                        "in_attack_range": u.get("in_attack_range")})
        if not st:
            continue
        kda = st.get("kda") or [None, None, None]
        spells = st.get("spells") or {}
        wp = st.get("world_pos")
        sp = st.get("screen_pos")
        hp, hp_max = st.get("hp"), st.get("hp_max")
        tables["champions"].append({
            **base, "uid": subject, "champion": subject, "identity": "roster", "side": side, "rel": "ally",
            "team": team_id, "is_subject": True, "hp_frac": (hp / hp_max) if hp and hp_max else None,
            "hp": hp, "hp_max": hp_max, "px": sp[0] if sp else None, "py": sp[1] if sp else None,
            "x": None, "y": None, "pos_kind": "screen_px",
            "est_x": wp[0] if wp else None, "est_z": wp[1] if wp else None,
            "est_kind": "detector_estimate_not_calibrated",
            "vx": None, "vy": None, "alive": not st.get("dead", False),
            "level": st.get("level"), "items": st.get("items"), "gold": None, "cs": st.get("cs"),
            "kills": kda[0], "deaths": kda[1], "assists": kda[2], "ad": st.get("ad"), "as": st.get("as"),
            "ms": st.get("ms"), "armor": st.get("armor"), "mr": None,
            "ranks": [spells.get(s, {}).get("rank") for s in "QWER"] if spells else None,
            "cd_ready_in_s": [spells.get(s, {}).get("ready_in_s") for s in "QWERDF"] if spells else None,
            "cam_x": cam_x, "cam_z": cam_z, "dist_to_subject_px": 0, "in_attack_range": None,
            "ready": {k: _ready(spells.get(k)) for k in "QER"},
            "buffs": None, "attack_timer_s": None, "res_frac": None, "res_kind": None,
            "mm_x": None, "mm_y": None, "target_uid": None,
        })
        subject_obs.append(f)
        # level and CS on this observed frame
        lv = st.get("level")
        if lv is not None and prev_level is not None and lv > prev_level:
            tables["events"].append({"game_id": gid, "tick": k, "t_s": round(t, 2), "event_id": f"lvl{k}",
                                     "kind": "level_up", "actor_uid": subject, "subject_uid": None, "value": lv,
                                     "conf": 0.95, "method": "state_level_step"})
        if lv is not None:
            prev_level = lv
        cs = st.get("cs")
        if cs is not None:
            if prev_cs is not None and cs > prev_cs:
                f["_cs_step"] = (prev_cs, cs)
            prev_cs = cs if prev_cs is None else max(prev_cs, cs)

    # 3. events from the Live Client (names mapped to champions)
    kill_ticks = []
    for n, ev in enumerate(events_raw):
        name, t = ev.get("EventName"), ev.get("EventTime")
        if t is None or not (t0 <= t <= t1):
            continue
        tick = round(t * TICK_HZ)
        base = {"game_id": gid, "tick": tick, "t_s": round(t, 2), "conf": 1.0, "method": "live_client_events"}
        if name == "ChampionKill":
            killer = champ_of_riot.get(ev.get("KillerName"))
            victim = champ_of_riot.get(ev.get("VictimName"))
            kill_ticks.append((tick, team_of_champ.get(killer)))
            tables["events"].append({**base, "event_id": f"lc{n}", "kind": "champion_kill", "actor_uid": killer,
                                     "subject_uid": victim, "value": None})
            for k, a in enumerate(ev.get("Assisters", [])):
                tables["events"].append({**base, "event_id": f"lc{n}a{k}", "kind": "assist",
                                         "actor_uid": champ_of_riot.get(a), "subject_uid": victim, "value": None})

    # 4. last_hit: one event per CS step. A CS step is matched to the minion death within 0.3 s whose last stage
    # position is nearest to Garen's stage position (else subject null, with the reason).
    n_lh, n_matched, n_near_06 = 0, 0, 0
    for f in frames:
        step = f.get("_cs_step")
        if not step:
            continue
        sp = (f["row"].get("state") or {}).get("screen_pos")
        gx, gy = to_stage(sp[0], sp[1], f["cam_x"], f["cam_z"]) if sp else (None, None)
        for _ in range(step[1] - step[0]):
            n_lh += 1
            if any(not d["used"] and abs(d["t"] - f["t"]) <= LAST_HIT_WIDE_S for d in deaths):
                n_near_06 += 1
            cands = [d for d in deaths if not d["used"] and abs(d["t"] - f["t"]) <= LAST_HIT_WINDOW_S]
            if cands:
                if gx is not None:
                    best = min(cands, key=lambda d: math.hypot(d["sx"] - gx, d["sy"] - gy))
                else:
                    best = min(cands, key=lambda d: abs(d["t"] - f["t"]))
                best["used"] = True
                n_matched += 1
                subj = best["uid"]
                method, conf = ("cs_step+minion_death" if step[1] - step[0] == 1 else "cs_step_split+minion_death"), (0.9 if step[1] - step[0] == 1 else 0.6)
            else:
                subj, method, conf = None, "cs_step_no_minion_death_within_0.3s", 0.5
            tables["events"].append({"game_id": gid, "tick": f["tick"], "t_s": round(f["t"], 2),
                                     "event_id": f"lh{n_lh}", "kind": "last_hit", "actor_uid": subject,
                                     "subject_uid": subj, "value": step[1], "conf": conf, "method": method})

    # 5. teams: cumulative kills per team (kills by the team's champions)
    kills = {"100": 0, "200": 0}
    kill_ticks.sort()
    ki = 0
    for k in ticks:
        while ki < len(kill_ticks) and kill_ticks[ki][0] <= k:
            if kill_ticks[ki][1] in kills:
                kills[kill_ticks[ki][1]] += 1
            ki += 1
        for tid, side_name in (("100", "blue"), ("200", "red")):
            other = "200" if tid == "100" else "100"
            tables["teams"].append({"game_id": gid, "tick": k, "t_s": round(k / TICK_HZ, 2), "team": tid, "side": side_name,
                                    "kills": kills[tid], "deaths": kills[other], "assists": None, "towers": None,
                                    "dragons": None, "gold": None})

    # 6. features and actions on observed frames
    alive_minions = defaultdict(list)
    enemy_champs = defaultdict(int)
    for row in tables["champions"]:
        if row.get("rel") == "enemy" and not row.get("is_subject"):
            enemy_champs[row["tick"]] += 1
    for row in tables["minions"]:
        if all(x["uid"] != row["uid"] for x in alive_minions[row["tick"]]):   # 15 fps rows can share a tick: count a uid once
            alive_minions[row["tick"]].append(row)
    prev = None
    for f in subject_obs:
        k, st = f["tick"], f["row"].get("state") or {}
        ms_now = alive_minions.get(k, [])
        enemies = [m for m in ms_now if m["rel"] == "enemy"]
        sp = st.get("screen_pos")
        dists = [m["dist_to_subject_px"] for m in enemies if m.get("dist_to_subject_px") is not None]
        tables["features"].append({
            "game_id": gid, "tick": k, "t_s": round(f["t"], 2), "observed": True, "src": "vision",
            "subject_hp_frac": (st["hp"] / st["hp_max"]) if st.get("hp") and st.get("hp_max") else None,
            "subject_level": st.get("level"), "subject_cs": st.get("cs"), "subject_dead": st.get("dead"),
            "n_ally_minion": sum(1 for m in ms_now if m["rel"] == "ally"),
            "n_enemy_minion": len(enemies),
            "n_enemy_minion_low": sum(1 for m in enemies if m["hp_frac"] is not None and m["hp_frac"] < 0.25),
            "n_enemy_champion": enemy_champs.get(k, 0),
            "nearest_enemy_minion_px": min(dists) if dists else None,
            "t_bucket_30s": int(f["t"] // 30),
        })
        wp = st.get("world_pos")
        if wp and prev and 0 < f["t"] - prev["t"] <= 0.5:
            dt = f["t"] - prev["t"]
            vx = (wp[0] - prev["wp"][0]) / dt
            vy = (wp[1] - prev["wp"][1]) / dt
            speed = math.hypot(vx, vy)
            if st.get("ms") and speed > 0.5 * st["ms"]:
                tables["actions"].append({"game_id": gid, "tick": k, "t_s": round(f["t"], 2), "actor_uid": subject,
                                          "kind": "move", "target_uid": None, "target_x": None, "target_y": None,
                                          "key": None, "inferred": True, "conf": 0.3, "src": "estimated_velocity"})
            elif speed < 20:
                tables["actions"].append({"game_id": gid, "tick": k, "t_s": round(f["t"], 2), "actor_uid": subject,
                                          "kind": "hold", "target_uid": None, "target_x": None, "target_y": None,
                                          "key": None, "inferred": True, "conf": 0.3, "src": "estimated_velocity"})
        if wp:
            prev = {"t": f["t"], "wp": wp}
    for r in det:
        for inp in r.get("inputs", []):
            tables["actions"].append({"game_id": gid, "tick": round(r["t"] * TICK_HZ), "t_s": round(r["t"], 2),
                                      "actor_uid": subject, "kind": inp.get("kind"), "target_uid": None,
                                      "target_x": None, "target_y": None, "key": inp.get("key"), "inferred": False,
                                      "conf": 1.0, "src": "input_log"})

    # sanity numbers for the report
    by_uid = defaultdict(list)
    for row in minion_rows:
        by_uid[row["uid"]].append(row)
    speeds = []
    for group in by_uid.values():
        group.sort(key=lambda r: r["tick"])
        for a_, b_ in zip(group, group[1:]):
            dt = (b_["tick"] - a_["tick"]) / TICK_HZ
            if dt > 0:
                speeds.append(math.hypot(b_["stage_x"] - a_["stage_x"], b_["stage_y"] - a_["stage_y"]) / dt)
    speeds.sort()
    cs_seq = [row["cs"] for row in tables["champions"] if row.get("is_subject") and row.get("cs") is not None]
    lives = sorted(tr.last_t - tr.first_t for tr in tracks)
    ended_by_death = sum(1 for tr in tracks if tr.closed in ("death", "probable_kill"))
    stats = {"minion_tracks": len(tracks), "track_life_median_s": round(lives[len(lives) // 2], 2) if lives else None,
             "track_life_p90_s": round(lives[int(0.9 * (len(lives) - 1))], 2) if lives else None,
             "tracks_ended_death_or_kill": ended_by_death, "tracks_ended_lost": causes["lost"],
             "track_end_causes": causes, "wave_travel_phase_s": round(travel, 2),
             "impossible_speed_steps": sum(1 for v in speeds if v > MAX_SPEED_PX + 1e-6),
             "track_speed_stage_px_s_p99": round(speeds[int(0.99 * (len(speeds) - 1))], 1) if speeds else None,
             "hp_rises_within_track": 0, "last_hit_events": n_lh, "last_hit_matched": n_matched,
             "last_hit_matched_share": round(n_matched / n_lh, 3) if n_lh else None,
             "last_hit_death_within_0.6s_share": round(n_near_06 / n_lh, 3) if n_lh else None,
             "cs_first": cs_seq[0] if cs_seq else None, "cs_last": cs_seq[-1] if cs_seq else None}

    from . import jev_cut as jc
    dp_rows, ev_stats = jc.cut_events(tables, gid, t0, t1, enemies_by_tick=_enemies_by_tick(enemy_names, frame0))
    dp_summary = jc.summary(dp_rows)
    dp_summary["event_triggers"] = ev_stats
    jev_rows = [{"turn": i + 1, "t": r["t_s"], "layer": r["layer"], "state": r["state"], "options": r["options"],
                 "chosen": r["chosen"], "outcome": r["outcome"], "reward": r["reward"]} for i, r in enumerate(dp_rows)]
    tables["decision_points"] = dp_rows
    tables["decisions"] = jev_rows                     # Jev export shape, written as decisions.jsonl by the CLI

    meta = {"schema_version": SCHEMA_VERSION, "game_id": gid, "decisions": dp_summary, "subject_champion": subject, "subject_team": me.get("team"),
            "subject_side": side, "t0": t0, "t1": t1, "tick_hz": TICK_HZ,
            "frame0_game_time_s": round(frame0, 3) if frame0 is not None else None,
            "alignment": "HUD clock of frame 0 (first clock step); one anchor, no per-segment fit yet",
            "observed_rule": f"detection row within {OBS_LAG_S * 1000:.0f} ms of a tick = observed; entity rows only on observed ticks",
            "positions": "x, y null (no screen to world calibration); px, py are screen pixels",
            "stats": stats}
    return tables, meta, _coverage(tables)


def _coverage(tables):
    cov = {}
    for name, cols in TABLES.items():
        rows = tables.get(name, [])
        cov[name] = {}
        for col in cols:
            if not rows:
                cov[name][col] = {"status": "missing", "reason": MISSING_REASON.get(col, "no detector for this field yet"), "fill": 0.0}
                continue
            vals = [r.get(col) for r in rows if r.get(col) is not None]
            fill = round(len(vals) / len(rows), 4)
            distinct = len({json.dumps(v, sort_keys=True) for v in vals})
            if not vals:
                status = "missing"
            elif distinct <= 1:
                status = "constant"
            elif fill >= 0.99:
                status = "filled"
            else:
                status = "partial"
            reason = None if status == "filled" else MISSING_REASON.get(col, f"{status}: see the rows with null")
            cov[name][col] = {"status": status, "fill": fill, "distinct": distinct, "reason": reason}
    return cov
