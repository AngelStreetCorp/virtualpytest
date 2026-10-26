"""Versioned schema of the LoL dataset (DATASET_SPEC.md). Bump SCHEMA_VERSION when a column changes meaning.

Naming: spec names where the meaning matches. Where the spec says map units and we only have screen pixels, the column
keeps a px suffix (dist_to_subject_px, nearest_enemy_minion_px) and a `pos_kind` column says what the position is.
"""

SCHEMA_VERSION = "0.4.0"
TICK_HZ = 10                 # DATASET_SPEC 2: 100 ms of game time per tick
OBS_LAG_S = 0.05             # a detection row within 50 ms of a tick is observed; entity rows exist only on those ticks
CARRY_LAG_S = 0.10           # the clock table records the nearest row up to 100 ms away (has_row); no entity row is carried

# Every table and its columns. coverage.json reports each one as filled / partial / constant / missing.
TABLES = {
    "ticks": ["game_id", "tick", "t_s", "src_t", "lag_ms", "observed", "has_row"],
    "minions": ["game_id", "tick", "t_s", "uid", "observed", "alive", "src", "side", "rel", "hp_frac", "hp", "hp_max",
                "px", "py", "stage_x", "stage_y", "pos_kind", "mtype_source", "x", "y", "vx", "vy", "mtype", "wave", "slot", "target_uid",
                "hp_drop_rate", "dist_to_subject_px", "in_attack_range"],
    "champions": ["game_id", "tick", "t_s", "uid", "champion", "identity", "observed", "src", "side", "rel", "team",
                  "is_subject", "ordinal", "hp_frac", "hp", "hp_max", "px", "py", "pos_kind", "x", "y",
                  "est_x", "est_z", "est_kind", "alive", "dist_to_subject_px", "in_attack_range", "cam_x", "cam_z",
                  "level", "items", "gold", "cs", "kills", "deaths", "assists", "ad", "as", "ms", "armor", "mr",
                  "ranks", "cd_ready_in_s", "buffs", "attack_timer_s", "res_frac", "res_kind", "mm_x", "mm_y", "target_uid"],
    "turrets": ["game_id", "tick", "t_s", "uid", "side", "x", "y", "hp_frac", "hp", "target_uid", "alive", "plates_left"],
    "attacks": ["game_id", "attack_id", "tick", "t_s", "t_impact_s", "attacker_uid", "target_uid", "kind", "damage",
                "inferred", "conf"],
    "events": ["game_id", "tick", "t_s", "event_id", "kind", "actor_uid", "subject_uid", "value", "conf", "method"],
    "actions": ["game_id", "tick", "t_s", "actor_uid", "kind", "target_uid", "target_x", "target_y", "key", "inferred",
                "conf", "src"],
    "features": ["game_id", "tick", "t_s", "observed", "src", "subject_hp_frac", "subject_level", "subject_cs",
                 "subject_dead", "n_ally_minion", "n_enemy_minion", "n_enemy_minion_low", "n_enemy_champion",
                 "nearest_enemy_minion_px", "t_bucket_30s"],
    "teams": ["game_id", "tick", "t_s", "team", "side", "kills", "deaths", "assists", "towers", "dragons", "gold"],
    "decision_points": ["dp_id", "game_id", "tick", "t_s", "layer", "window_s", "state", "options", "chosen",
                        "chosen_inferred", "label_confidence", "label_rule", "outcome", "reward_parts", "reward"],
}

# Why a column is null or partial, shown in coverage.json and the viewer.
MISSING_REASON = {
    "x": "no screen to world calibration (DATASET_SPEC 3.1); screen px is in px, py",
    "y": "no screen to world calibration (DATASET_SPEC 3.1); screen px is in px, py",
    "vx": "no map-unit positions, so no velocity (subject velocity is estimated from the detector, see actions)",
    "vy": "no map-unit positions, so no velocity",
    "mtype": "minion type classifier not wired into the build",
    "wave": "wave-spawn estimate not built (needs first sighting and lane distance)",
    "slot": "wave order not built (depends on wave)",
    "hp": "absolute HP needs hp_max by type; only the bar fraction is observed",
    "hp_max": "hp_max by minion type and game minute not built",
    "target_uid": "attack attribution not built",
    "hp_drop_rate": "not computed in this build (tracks are observed-only)",
    "uid": "champions other than the subject have no identity (no portrait or level-box match yet)",
    "champion": "champion identity for other players not built (roster names only for the subject)",
    "identity": "roster for the subject; unknown for other champions",
    "est_x": "detector estimate for the subject, not calibrated",
    "est_z": "detector estimate for the subject, not calibrated",
    "items": "from the detection state (subject only)",
    "gold": "gold is not in the Live Client log for other players or the replay path",
    "mr": "magic resist not read",
    "ranks": "rank digits only read for the subject",
    "cd_ready_in_s": "cooldown reads only for the subject",
    "buffs": "buff icons not read",
    "attack_timer_s": "auto attack timing not built",
    "res_frac": "resource bar not read (phase 2)",
    "res_kind": "resource bar not read (phase 2)",
    "mm_x": "minimap champion positions not built",
    "mm_y": "minimap champion positions not built",
    "cam_x": "camera at the same time as the frame (log sample within 0.1 s); null when no log sample",
    "cam_z": "camera at the same time as the frame (log sample within 0.1 s); null when no log sample",
    "plates_left": "turret plates not read",
    "attacker_uid": "attacker attribution not built",
    "damage": "attacks not generated: HP drops have no attacker and are not gated (jitter)",
    "towers": "tower count not derived in this build",
    "dragons": "dragon count not derived in this build",
    "assists": "team assists not derived in this build",
    "subject_uid": "no minion death within 0.3 s of the CS step, or not a minion event",
    "actor_uid": "no actor for this event kind",
    "value": "no value for this event kind",
    "target_x": "actions with a map target not built",
    "target_y": "actions with a map target not built",
    "key": "real inputs only (bot games); replays have none",
    "nearest_enemy_minion_px": "screen px from the subject's screen position; null when the subject is not on screen",
    "dist_to_subject_px": "screen px from the detector; null when not given",
    "killable": "killable triggers need absolute minion HP per type: not built",
}
