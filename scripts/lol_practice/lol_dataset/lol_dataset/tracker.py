"""Minion tracker in camera-compensated ("stage") screen coordinates.

A screen position moves when the camera moves, so every detection is first mapped to stage space:
    sx = px + KX * camera_x,   sy = py - KY * camera_z
KX and KY were measured on game 8018174981 (1920x1200, fixed zoom): a static minion's stage position stays put while
the camera moves. Units: stage px. The tracker gates on the speed limit (400 map units/s, converted with KX), predicts
each track's position from its recent velocity, and allows a gap of up to MAX_GAP_S before a track closes.

Rules: a track keeps one uid for its whole life; HP only falls within a track (a higher reading beyond HP_TOL starts a
new track); a track matches within the side (ally or enemy) only.
"""
import math

KX = 0.394           # stage px per map unit of camera x (screen x moves opposite to the camera)
KY = 0.3135          # stage px per map unit of camera z (screen y grows with z)
MAX_SPEED_UNITS = 400.0          # DATASET_SPEC gate: no minion is faster than this (map units/s)
MAX_SPEED_PX = MAX_SPEED_UNITS * KX
GATE_SLACK_PX = 20.0             # added to the speed gate for detection jitter
GATE_MIN_PX = 150.0# minimum match radius: bar centres shift as HP falls (jitter), so the gate can't be only the speed limit
MAX_GAP_S = 2.5# a track unseen longer than this closes
REACQUIRE_S = 2.0                # diagnostics: a new track this soon after a lost one counts as a reacquisition
USE_PREDICTION = True# match to the predicted position (False: to the last sample)
HP_TOL = 0.20# a reading this far above the track's HP still counts as the same minion (noise)
DEATH_HP = 0.10                  # closed with HP at or below this: a death
PROBABLE_DEATH_HP = 0.35         # closed as lost with HP at or below this: probable kill (conf 0.6)


def to_stage(px, py, cam_x, cam_z):
    """Stage coordinates of a screen point. Without a camera sample the screen point is returned unchanged."""
    if cam_x is None or cam_z is None:
        return px, py
    return px + KX * cam_x, py - KY * cam_z


class Track:
    __slots__ = ("id", "kind", "hist", "first_t", "last_t", "hp", "closed", "rows", "wave", "slot", "mtype")

    def __init__(self, tid, kind, t, sx, sy, hp, row):
        self.id = tid
        self.kind = kind
        self.hist = [(t, sx, sy)]
        self.first_t = t
        self.last_t = t
        self.hp = hp
        self.closed = None
        self.rows = [row]
        self.wave = self.slot = self.mtype = None

    def last(self):
        return self.hist[-1]

    def predict(self, t):
        """Stage position at time t from the last two samples; the velocity is capped at the speed limit."""
        t1, x1, y1 = self.hist[-1]
        if len(self.hist) < 2:
            return x1, y1
        t0, x0, y0 = self.hist[-2]
        dt = t1 - t0
        if dt <= 0:
            return x1, y1
        vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
        speed = math.hypot(vx, vy)
        if speed > MAX_SPEED_PX:
            vx, vy = vx * MAX_SPEED_PX / speed, vy * MAX_SPEED_PX / speed
        dt_now = t - t1
        return x1 + vx * dt_now, y1 + vy * dt_now


def gate(dt, gate_min=None):
    return (GATE_MIN_PX if gate_min is None else gate_min) + MAX_SPEED_PX * max(dt, 0.0) + GATE_SLACK_PX


def track_frames(frames, gid, gate_min=None):
    """frames: observed frames in time order, each {tick, t, row, cam_x, cam_z}. Returns (minion rows, tracks, causes).

    Rows carry the screen px, the stage position, the track uid and the clamped HP. A closed track is listed in tracks with
    closed in {"death", "probable_kill", "lost"}. causes counts the reasons a track ended, for the report."""
    tracks, active = [], []
    rows = []
    next_id = 0
    causes = {"death": 0, "probable_kill": 0, "lost": 0, "reacquired_within_1s": 0}

    def close(tr):
        active.remove(tr)
        if tr.hp <= DEATH_HP:
            tr.closed = "death"
        elif tr.hp <= PROBABLE_DEATH_HP:
            tr.closed = "probable_kill"
        else:
            tr.closed = "lost"
        causes[tr.closed] += 1
        if tr.closed in ("death", "probable_kill"):
            tr.rows[-1]["alive"] = False
        tracks.append(tr)

    for f in frames:
        t = f["t"]
        for tr in list(active):
            if t - tr.last_t > MAX_GAP_S:
                close(tr)
        for kind in ("ally_minion", "enemy_minion"):
            dets = []
            for u in f["row"].get("world", {}).get("units", []):
                if u.get("kind") != kind or not u.get("px") or u.get("hp_frac") is None:
                    continue
                sx, sy = to_stage(u["px"][0], u["px"][1], f["cam_x"], f["cam_z"])
                dets.append((u, sx, sy))
            trs = [tr for tr in active if tr.kind == kind]
            pairs = []
            for ti, tr in enumerate(trs):
                dt = t - tr.last_t
                lx, ly = tr.last()[1], tr.last()[2]
                px_, py_ = tr.predict(t) if USE_PREDICTION else (lx, ly)
                for di, (u, sx, sy) in enumerate(dets):
                    if math.hypot(sx - lx, sy - ly) > gate(dt, gate_min):
                        continue                       # speed gate from the last sample
                    if u["hp_frac"] > tr.hp + HP_TOL:
                        continue                       # HP only falls within a track
                    pairs.append((math.hypot(sx - px_, sy - py_), ti, di))
            pairs.sort()
            used_t, used_d = set(), set()
            for _, ti, di in pairs:
                if ti in used_t or di in used_d:
                    continue
                used_t.add(ti)
                used_d.add(di)
                tr = trs[ti]
                u, sx, sy = dets[di]
                tr.hp = min(tr.hp, u["hp_frac"])
                tr.last_t = t
                tr.hist.append((t, sx, sy))
                row = _row(gid, f, tr, u, sx, sy)
                tr.rows.append(row)
                rows.append(row)
            for di, (u, sx, sy) in enumerate(dets):
                if di in used_d:
                    continue
                tr = Track(next_id, kind, t, sx, sy, u["hp_frac"], None)
                next_id += 1
                row = _row(gid, f, tr, u, sx, sy)
                tr.rows = [row]
                rows.append(row)
                # a new track started near a recently closed track of the same kind: a reacquired minion
                if any(old.kind == kind and old.closed == "lost" and 0 < t - old.last_t <= REACQUIRE_S
                       and math.hypot(sx - old.last()[1], sy - old.last()[2]) <= gate(t - old.last_t, gate_min) for old in tracks):
                    causes["reacquired_within_1s"] += 1
                active.append(tr)
    for tr in list(active):                      # still open when the capture ends: not a death
        active.remove(tr)
        tr.closed = "open"
        causes["open"] = causes.get("open", 0) + 1
        tracks.append(tr)
    return rows, tracks, causes


def _row(gid, f, tr, u, sx, sy):
    rel = "ally" if tr.kind == "ally_minion" else "enemy"
    return {"game_id": gid, "tick": f["tick"], "t_s": round(f["t"], 2), "uid": f"{gid}-{rel[0]}m{tr.id}",
            "observed": True, "alive": True, "src": "vision", "side": None, "rel": rel,
            "hp_frac": round(min(tr.hp, u["hp_frac"]), 4), "px": u["px"][0], "py": u["px"][1],
            "stage_x": round(sx, 1), "stage_y": round(sy, 1), "x": None, "y": None, "pos_kind": "screen_px",
            "dist_to_subject_px": u.get("dist_px"), "in_attack_range": u.get("in_attack_range"),
            "hp_drop_rate": None, "mtype": None, "wave": None, "slot": None, "hp": None, "hp_max": None,
            "vx": None, "vy": None, "target_uid": None, "_track": tr.id}
