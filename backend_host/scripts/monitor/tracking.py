"""Trackers for counting profiles (TASK-90 §2, §4.4): an object seen in many frames counts once.

Two algorithms behind `track: {algo: iou|ocsort}`:

* `iou`    greedy matching by IoU, highest first. Enough at 1-2 Hz when objects move little between samples.
* `ocsort` an OC-SORT-style tracker, written from the published idea (Cao et al., "Observation-Centric SORT", MIT): the
           track's velocity comes from its last real observations, not from a filter that drifts while the object is unseen
           (observation-centric momentum: the cost also rewards a detection that lies in the direction the track was
           moving); the association is the optimal assignment (Hungarian); and unmatched detections get a second chance
           against the LAST observation of lost tracks (observation-centric recovery). No code of other trackers is used.

Both: a track keeps the label of its first sighting, and a detection may continue it when its label is in the same group
(`label_group`; a detector flipping car <-> truck on one vehicle must not open a second track). A track not matched for
`max_gap_s` ends; ended tracks are returned by `pop_ended()` so votes on them can be settled.
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

BBox = Tuple[float, float, float, float]  # x, y, w, h


def iou(a: BBox, b: BBox) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = min(ax2, bx2) - max(a[0], b[0])
    ih = min(ay2, by2) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def iou_matrix(a_boxes: List[BBox], b_boxes: List[BBox]) -> np.ndarray:
    """Every IoU of `a_boxes` against every `b_boxes`, as an (len(a), len(b)) float array.

    THE POINT OF THIS FUNCTION: the trackers matched detections to tracks with a pure-Python
    double loop, one `iou()` call per (detection, track) pair. On the egg line that is ~175
    detections against ~250 live tracks — 43 000 pairs — and the box spent **about a second** in
    it per analysis, MORE than the detector itself (0.24-0.75 s), so the line refreshed at 0.5
    analyses/s while the model sat idle (BUG-0909). The same arithmetic in one array operation
    takes a few milliseconds.

    The numbers are the ones `iou()` returns: no overlap (or a degenerate box) is 0.0, and the
    union guard keeps a zero-area box from dividing by zero.
    """
    if not a_boxes or not b_boxes:
        return np.zeros((len(a_boxes), len(b_boxes)), dtype=np.float64)
    a = np.asarray(a_boxes, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(b_boxes, dtype=np.float64).reshape(-1, 4)
    ax2, ay2 = a[:, 0] + a[:, 2], a[:, 1] + a[:, 3]
    bx2, by2 = b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    iw = np.minimum(ax2[:, None], bx2[None, :]) - np.maximum(a[:, 0][:, None], b[:, 0][None, :])
    ih = np.minimum(ay2[:, None], by2[None, :]) - np.maximum(a[:, 1][:, None], b[:, 1][None, :])
    inter = np.where((iw > 0) & (ih > 0), iw * ih, 0.0)
    area_a = (a[:, 2] * a[:, 3])[:, None]
    area_b = (b[:, 2] * b[:, 3])[None, :]
    union = area_a + area_b - inter
    return np.where(union > 0, inter / np.where(union > 0, union, 1.0), 0.0)


def centre(b: BBox) -> Tuple[float, float]:
    return b[0] + b[2] / 2.0, b[1] + b[3] / 2.0


@dataclass
class Track:
    track_id: int
    label: str
    bbox: BBox
    first_seen: float
    last_seen: float
    hits: int = 1
    attrs: Dict[str, str] = field(default_factory=dict)
    counted: bool = False                    # an event for this track was already emitted
    history: List[Tuple[float, BBox]] = field(default_factory=list)   # recent real observations (time, bbox)
    votes: Dict[str, List[str]] = field(default_factory=dict)         # attribute -> the value of each vote
    probs: Dict[str, Dict[str, float]] = field(default_factory=dict)  # attribute -> summed class probabilities of the votes
    n_votes: int = 0
    finalized: bool = False                  # the per-track verdict was emitted
    line_cx: Optional[float] = None          # last centre x, for a profile that counts at a line (count_line_x)

    def observe(self, bbox: BBox, now: float):
        self.bbox, self.last_seen = bbox, now
        self.history.append((now, bbox))
        del self.history[:-6]


class _Base:
    def __init__(self, max_gap_s: float = 2.0, min_iou: float = 0.3, min_hits: int = 1, label_group=None,
                 stationary_gap_s: float = 30.0):
        self.stationary_gap_s = max(stationary_gap_s, max_gap_s)
        self.max_gap_s = max_gap_s
        self.min_iou = min_iou
        self.min_hits = min_hits
        self.label_group = label_group or (lambda label: label)
        self._next_id = 1
        self.tracks: Dict[int, Track] = {}
        self._ended: List[Track] = []

    def confirmed(self, track: Track) -> bool:
        return track.hits >= self.min_hits

    def pop_ended(self) -> List[Track]:
        out, self._ended = self._ended, []
        return out

    def _stationary(self, tr: Track) -> bool:
        """A track that has been seen at least 3 times and has hardly moved (a parked vehicle)."""
        h = tr.history
        if len(h) < 3:
            return False
        (x0, y0), (x1, y1) = centre(h[0][1]), centre(h[-1][1])
        return math.hypot(x1 - x0, y1 - y0) < 0.25 * max(tr.bbox[2], tr.bbox[3])

    def _expire(self, now: float):
        # A parked vehicle is detected on and off (a detector at its confidence threshold): it waits `stationary_gap_s`
        # for its next detection instead of `max_gap_s`, so it is not counted again every time it comes back.
        for tid in [t for t, tr in self.tracks.items()
                    if now - tr.last_seen > (self.stationary_gap_s if self._stationary(tr) else self.max_gap_s)]:
            self._ended.append(self.tracks.pop(tid))

    def _new(self, label, box, now) -> Track:
        tr = Track(self._next_id, label, box, now, now)
        tr.history.append((now, box))
        self._next_id += 1
        self.tracks[tr.track_id] = tr
        return tr

    def _same_kind(self, tr: Track, label: str) -> bool:
        return self.label_group(tr.label) == self.label_group(label)

    def velocity(self, tr: Track) -> Tuple[float, float]:
        """Centre velocity of a track in px/s, (0, 0) when it cannot be estimated (BUG-0836).

        Public because the pipeline puts it in the frame JSON: the overlay is drawn on a live video, which is
        later than the analysed frame, and the client moves each box forward by v x age to keep it on its
        object. The plain IoU tracker keeps no window, so it reports no motion.
        """
        window = getattr(self, 'velocity_window', 3)
        h = tr.history[-window:] if window else tr.history
        if len(h) < 2 or h[-1][0] <= h[0][0]:
            return 0.0, 0.0
        (t0, b0), (t1, b1) = h[0], h[-1]
        (x0, y0), (x1, y1) = centre(b0), centre(b1)
        return (x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)


class IouTracker(_Base):
    algo = 'iou'

    def update(self, detections: List[Tuple[str, BBox]], now: float) -> List[Tuple[int, Track, bool]]:
        """Match detections (label, bbox) to tracks. Returns [(index into detections, track, is_new)]."""
        self._expire(now)
        pairs = []
        tids = list(self.tracks)
        if detections and tids:
            scores = iou_matrix([box for _label, box in detections],
                                [self.tracks[tid].bbox for tid in tids])
            for di, (label, _box) in enumerate(detections):
                for j, tid in enumerate(tids):
                    if self._same_kind(self.tracks[tid], label):
                        score = float(scores[di, j])
                        if score >= self.min_iou:
                            pairs.append((score, di, tid))
        pairs.sort(reverse=True)
        used_d, used_t = set(), set()
        assigned: Dict[int, int] = {}
        for score, di, tid in pairs:
            if di in used_d or tid in used_t:
                continue
            used_d.add(di)
            used_t.add(tid)
            assigned[di] = tid
        out = []
        for di, (label, box) in enumerate(detections):
            tid = assigned.get(di)
            if tid is None:
                out.append((di, self._new(label, box, now), True))
            else:
                tr = self.tracks[tid]
                tr.observe(box, now)
                tr.hits += 1
                out.append((di, tr, False))
        return out


try:                                     # scipy's solver is C code; the pure-Python one below is the fallback
    from scipy.optimize import linear_sum_assignment as _scipy_lsa
except ImportError:                      # pragma: no cover - scipy is present on every host we ship to
    _scipy_lsa = None


def hungarian(cost: List[List[float]]) -> List[Tuple[int, int]]:
    """Optimal assignment for a rectangular cost matrix (rows x cols), minimising the total cost.
    Returns [(row, col)] for min(rows, cols) pairs (shortest augmenting path, O(n^3)).

    On the egg line this matrix is ~175 detections x ~345 live tracks, and the pure-Python
    shortest-augmenting-path solver spent **0.2 s** in it per analysis — more than the detector
    itself — so the line refreshed at 0.5 analyses/s while the model sat idle (BUG-0909). Scipy's
    linear_sum_assignment solves the same problem (same minimum total cost) in C, in about a
    millisecond. The pure-Python solver stays as the fallback for a host without scipy, and both
    return the same pairs on the egg line's matrices (measured: identical total cost, and the same
    pairs on every frame of a 6-frame replay)."""
    n_rows, n_cols = len(cost), (len(cost[0]) if cost else 0)
    if not n_rows or not n_cols:
        return []
    if _scipy_lsa is not None:
        rows, cols = _scipy_lsa(np.asarray(cost, dtype=np.float64))
        return list(zip(rows.tolist(), cols.tolist()))
    transposed = n_rows > n_cols
    if transposed:
        cost = [list(r) for r in zip(*cost)]
        n_rows, n_cols = n_cols, n_rows
    inf = float('inf')
    u = [0.0] * (n_rows + 1)
    v = [0.0] * (n_cols + 1)
    p = [0] * (n_cols + 1)
    way = [0] * (n_cols + 1)
    for i in range(1, n_rows + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n_cols + 1)
        used = [False] * (n_cols + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, n_cols + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n_cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    pairs = [(p[j] - 1, j - 1) for j in range(1, n_cols + 1) if p[j]]
    return [(c, r) for r, c in pairs] if transposed else pairs


class OcSortTracker(_Base):
    """OC-SORT-style tracker (see the module docstring). Extra keys: `direction_weight`, `velocity_window`."""
    algo = 'ocsort'

    def __init__(self, *a, direction_weight: float = 0.2, velocity_window: int = 3, cold_gate: float = 0.0, **kw):
        super().__init__(*a, **kw)
        self.cold_gate = cold_gate
        self.direction_weight = direction_weight
        self.velocity_window = velocity_window

    def _velocity(self, tr: Track) -> Tuple[float, float]:
        """Centre velocity (px/s) from the last real observations (observation-centric: no filter state)."""
        return self.velocity(tr)

    def _growth(self, tr: Track) -> float:
        """Per-second growth factor of the box size from the last two observations (a vehicle driving towards the camera
        gets bigger with every sample), limited to 0.5-2x per second so one bad box cannot send the prediction away."""
        if len(tr.history) < 2:
            return 1.0
        (t0, b0), (t1, b1) = tr.history[-2], tr.history[-1]
        if t1 <= t0 or b0[2] <= 0 or b0[3] <= 0:
            return 1.0
        ratio = math.sqrt((b1[2] * b1[3]) / (b0[2] * b0[3]))
        return max(0.5, min(2.0, ratio ** (1.0 / (t1 - t0))))

    def _predict(self, tr: Track, now: float) -> BBox:
        vx, vy = self._velocity(tr)
        dt = now - tr.last_seen
        x, y, w, h = tr.bbox
        g = self._growth(tr) ** dt
        cx, cy = x + w / 2 + vx * dt, y + h / 2 + vy * dt
        return cx - w * g / 2, cy - h * g / 2, w * g, h * g

    def _direction_penalty(self, tr: Track, box: BBox) -> float:
        """0 when the detection lies in the direction the track was moving (or the track has no direction), up to 1."""
        vx, vy = self._velocity(tr)
        speed = math.hypot(vx, vy)
        if speed < 1e-6:
            return 0.0
        cx, cy = centre(tr.bbox)
        dx, dy = centre(box)[0] - cx, centre(box)[1] - cy
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return 0.0
        cos = max(-1.0, min(1.0, (vx * dx + vy * dy) / (speed * d)))
        return (1.0 - cos) / 2.0


    def _groups(self, labels, tracks=None):
        """The `label_group` of every detection and every track, as arrays.

        "Is this detection of the same kind as this track?" was a Python call per pair — 30 000
        calls per analysis on the egg line. The groups are strings, so the whole matrix is one
        array comparison (BUG-0909)."""
        if tracks is None:
            return np.array([self.label_group(l) for l in labels], dtype=object)
        return (np.array([self.label_group(l) for l in labels], dtype=object),
                np.array([self.label_group(self.tracks[tid].label) for tid in tracks], dtype=object))

    def _cost_matrix(self, detections, tids, now, big):
        """The assignment cost of every (detection, track) pair, as a list of rows.

        Same numbers as the pure-Python double loop it replaces, computed with arrays: the IoU of
        every detection against every track's velocity-predicted box, the direction term, and the
        `big` cost for a pair below `min_iou` or of another kind (BUG-0909).
        """
        d_boxes = [box for _label, box in detections]
        p_boxes = [self._predict(self.tracks[tid], now) for tid in tids]
        score = iou_matrix(d_boxes, p_boxes)
        # a detection of another kind scores 0, exactly like the loop did
        det_groups, trk_groups = self._groups([label for label, _box in detections], tids)
        same = det_groups[:, None] == trk_groups[None, :]
        score = np.where(same, score, 0.0)
        # the direction term: how well the detection lies in the direction the track was moving
        pen = np.zeros(score.shape, dtype=np.float64)
        if self.direction_weight:
            dcx = np.array([centre(b)[0] for b in d_boxes], dtype=np.float64)
            dcy = np.array([centre(b)[1] for b in d_boxes], dtype=np.float64)
            for j, tid in enumerate(tids):
                tr = self.tracks[tid]
                vx, vy = self._velocity(tr)
                speed = math.hypot(vx, vy)
                if speed < 1e-6:
                    continue
                cx, cy = centre(tr.bbox)
                dx = dcx - cx
                dy = dcy - cy
                dist = np.hypot(dx, dy)
                ok = dist >= 1e-6
                cos = np.clip((vx * dx + vy * dy) / np.where(ok, speed * dist, 1.0), -1.0, 1.0)
                pen[:, j] = np.where(ok, (1.0 - cos) / 2.0, 0.0)
        cost = np.where(score < self.min_iou, big, (1.0 - score) + self.direction_weight * pen)
        return cost.tolist()

    def _cold_candidates(self, detections, free_d, free_t):
        """The cold-start pairs: a detection and a one-sighting track whose centres are close
        enough (`cold_gate`), nearest first. The distances are the same ones the loop computed."""
        boxes = [detections[di][1] for di in free_d]
        dcx = np.array([centre(b)[0] for b in boxes], dtype=np.float64)
        dcy = np.array([centre(b)[1] for b in boxes], dtype=np.float64)
        dsize = np.array([max(b[2], b[3]) for b in boxes], dtype=np.float64)
        tcx = np.array([centre(self.tracks[tid].bbox)[0] for tid in free_t], dtype=np.float64)
        tcy = np.array([centre(self.tracks[tid].bbox)[1] for tid in free_t], dtype=np.float64)
        tsize = np.array([max(self.tracks[tid].bbox[2], self.tracks[tid].bbox[3]) for tid in free_t], dtype=np.float64)
        dist = np.hypot(dcx[:, None] - tcx[None, :], dcy[:, None] - tcy[None, :])
        denom = np.maximum(np.maximum(dsize[:, None], tsize[None, :]), 1.0)
        norm = dist / denom
        det_groups, trk_groups = self._groups([detections[di][0] for di in free_d], free_t)
        same = det_groups[:, None] == trk_groups[None, :]
        cand = []
        for j, tid in enumerate(free_t):
            for i, di in enumerate(free_d):
                if not same[i, j]:
                    continue
                d = float(norm[i, j])
                if d <= self.cold_gate:
                    cand.append((d, di, tid))
        return cand

    def update(self, detections: List[Tuple[str, BBox]], now: float) -> List[Tuple[int, Track, bool]]:
        self._expire(now)
        tids = list(self.tracks)
        assigned: Dict[int, int] = {}

        # 1. optimal assignment on IoU with the velocity-predicted box, plus the direction term
        if tids and detections:
            big = 1e6
            cost = self._cost_matrix(detections, tids, now, big)
            for di, ti in hungarian(cost):
                if cost[di][ti] < big:
                    assigned[di] = tids[ti]

        # 2. observation-centric recovery: leftovers against the LAST real observation of tracks nobody claimed
        free_t = [t for t in tids if t not in assigned.values()]
        free_d = [di for di in range(len(detections)) if di not in assigned]
        if free_t and free_d:
            scores = iou_matrix([detections[di][1] for di in free_d],
                                [self.tracks[tid].bbox for tid in free_t])
            det_groups, trk_groups = self._groups([detections[di][0] for di in free_d], free_t)
            same = det_groups[:, None] == trk_groups[None, :]
            pairs = []
            for j, tid in enumerate(free_t):
                for i, di in enumerate(free_d):
                    if not same[i, j]:
                        continue
                    score = float(scores[i, j])
                    if score >= self.min_iou:
                        pairs.append((score, di, tid))
            pairs.sort(reverse=True)
            used_d, used_t = set(), set()
            for score, di, tid in pairs:
                if score >= self.min_iou and di not in used_d and tid not in used_t:
                    used_d.add(di)
                    used_t.add(tid)
                    assigned[di] = tid

        # 3. cold start: a track seen once has no velocity yet, and an object that moves more than its own size between two
        #    samples (a small egg on a fast belt) overlaps nothing. Match what is left by the distance between centres,
        #    in box sizes (`cold_gate`, 0 = off), nearest first.
        if self.cold_gate > 0:
            free_t = [t for t in tids if t not in assigned.values() and len(self.tracks[t].history) < 2]
            free_d = [di for di in range(len(detections)) if di not in assigned]
            if free_t and free_d:
                cand = self._cold_candidates(detections, free_d, free_t)
                used_d, used_t = set(), set()
                for d, di, tid in sorted(cand):
                    if di not in used_d and tid not in used_t:
                        used_d.add(di)
                        used_t.add(tid)
                        assigned[di] = tid

        out = []
        for di, (label, box) in enumerate(detections):
            tid = assigned.get(di)
            if tid is None:
                out.append((di, self._new(label, box, now), True))
            else:
                tr = self.tracks[tid]
                tr.observe(box, now)
                tr.hits += 1
                out.append((di, tr, False))
        return out


Tracker = IouTracker   # name used before there were two algorithms


def make_tracker(algo: str = 'iou', **cfg):
    if algo == 'iou':
        return IouTracker(**cfg)
    if algo == 'ocsort':
        return OcSortTracker(**cfg)
    raise ValueError(f"unknown tracker algo {algo!r} (iou | ocsort)")
