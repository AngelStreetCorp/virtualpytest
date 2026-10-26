"""The trackers' hot path is vectorised (BUG-0910), and it must not change what they decide.

THE TRACKER WAS THE BOTTLENECK: on the egg line it matched ~175 detections against ~250-345 live
tracks in pure Python, and the box spent about a second in it per analysis — more than the
detector itself (0.24-0.75 s). The egg line therefore refreshed at 0.47-0.48 analyses/s while the
model sat idle. The same arithmetic is now done with arrays.

These tests pin the two things that matter after such a change:
  1. the SAME pairs are matched — the shipped tracker is compared against a subclass that keeps the
     ORIGINAL pure-Python matching (the reference), on a moving-belt sequence, and
  2. it is actually FAST — a relative check against the reference, so it does not depend on how
     fast the machine running the test is.
"""
import math
import os
import random
import sys
import time

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor import tracking as T  # noqa: E402


# ---- the reference: the original pure-Python matching, kept as a subclass -------------------------

def _ref_hungarian(cost):
    """The original pure-Python solver (the shipped one may use scipy now)."""
    n_rows, n_cols = len(cost), (len(cost[0]) if cost else 0)
    if not n_rows or not n_cols:
        return []
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
            p[j0] = p[way[j0]]
            j0 = way[j0]
            if j0 == 0:
                break
    pairs = [(p[j] - 1, j - 1) for j in range(1, n_cols + 1) if p[j]]
    return [(c, r) for r, c in pairs] if transposed else pairs


class ReferenceOcSort(T.OcSortTracker):
    """The tracker as it was BEFORE the vectorisation: every pair computed in a Python loop."""

    def update(self, detections, now):
        self._expire(now)
        tids = list(self.tracks)
        assigned = {}
        if tids and detections:
            big = 1e6
            cost = []
            for label, box in detections:
                row = []
                for tid in tids:
                    tr = self.tracks[tid]
                    score = T.iou(box, self._predict(tr, now)) if self._same_kind(tr, label) else 0.0
                    row.append(big if score < self.min_iou else
                               (1.0 - score) + self.direction_weight * self._direction_penalty(tr, box))
                cost.append(row)
            for di, ti in _ref_hungarian(cost):
                if cost[di][ti] < big:
                    assigned[di] = tids[ti]
        free_t = [t for t in tids if t not in assigned.values()]
        free_d = [di for di in range(len(detections)) if di not in assigned]
        if free_t and free_d:
            pairs = sorted(((T.iou(detections[di][1], self.tracks[tid].bbox), di, tid)
                            for di in free_d for tid in free_t
                            if self._same_kind(self.tracks[tid], detections[di][0])), reverse=True)
            used_d, used_t = set(), set()
            for score, di, tid in pairs:
                if score >= self.min_iou and di not in used_d and tid not in used_t:
                    used_d.add(di)
                    used_t.add(tid)
                    assigned[di] = tid
        if self.cold_gate > 0:
            free_t = [t for t in tids if t not in assigned.values() and len(self.tracks[t].history) < 2]
            free_d = [di for di in range(len(detections)) if di not in assigned]
            cand = []
            for di in free_d:
                label, box = detections[di]
                (dx, dy), size = T.centre(box), max(box[2], box[3])
                for tid in free_t:
                    tr = self.tracks[tid]
                    if self._same_kind(tr, label):
                        d = math.hypot(dx - T.centre(tr.bbox)[0], dy - T.centre(tr.bbox)[1]) / \
                            max(1.0, size, max(tr.bbox[2], tr.bbox[3]))
                        if d <= self.cold_gate:
                            cand.append((d, di, tid))
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


# ---- helpers --------------------------------------------------------------------------------------

def _belt_frame(rng, n, t):
    """n eggs on a belt moving to the right: the hard case, the boxes move between samples."""
    return [('egg', (rng.uniform(0, 1200) + t * 4.0, rng.uniform(0, 680),
                     rng.uniform(30, 70), rng.uniform(30, 70))) for _ in range(n)]


def _replay(tracker, frames):
    out = []
    for t, dets in enumerate(frames):
        res = tracker.update(dets, t * 0.5)
        out.append([(di, tr.track_id, is_new) for di, tr, is_new in res])
    return out


# ---- tests ----------------------------------------------------------------------------------------

def test_iou_matrix_matches_the_scalar_iou():
    """Every cell of the array must be the number `iou()` returns for that pair."""
    boxes = [(10.0, 20.0, 30.0, 40.0), (25.0, 25.0, 30.0, 30.0), (0.0, 0.0, 0.0, 0.0),
             (100.0, 100.0, 10.0, 10.0)]
    m = T.iou_matrix(boxes, boxes)
    for i, a in enumerate(boxes):
        for j, b in enumerate(boxes):
            assert float(m[i, j]) == pytest.approx(T.iou(a, b), abs=1e-12)


def test_iou_matrix_handles_an_empty_side():
    assert T.iou_matrix([], [(0.0, 0.0, 1.0, 1.0)]).shape == (0, 1)
    assert T.iou_matrix([(0.0, 0.0, 1.0, 1.0)], []).shape == (1, 0)


def test_the_vectorised_tracker_matches_the_reference_matcher():
    """Same pairs, same track ids, on a belt moving to the right."""
    cfg = dict(max_gap_s=30.0, min_iou=0.1, cold_gate=1.5)
    frames = [_belt_frame(random.Random(3), 120, t) for t in range(6)]
    new_out = _replay(T.make_tracker('ocsort', **cfg), frames)
    ref_out = _replay(ReferenceOcSort(**cfg), frames)
    assert new_out == ref_out


def test_the_vectorised_cost_matrix_is_the_reference_matrix():
    """The array-built cost matrix is the matrix the Python loop built, cell for cell."""
    cfg = dict(max_gap_s=30.0, min_iou=0.1, cold_gate=1.5)
    frames = [_belt_frame(random.Random(5), 175, t) for t in range(4)]
    tracker = T.make_tracker('ocsort', **cfg)
    for t, dets in enumerate(frames):
        tracker.update(dets, t * 0.5)
    live = list(tracker.tracks)
    dets, now = frames[-1], 3 * 0.5
    assert len(live) > 100, 'the workload must be big enough to matter'

    ref = []
    for label, box in dets:
        row = []
        for tid in live:
            tr = tracker.tracks[tid]
            score = T.iou(box, tracker._predict(tr, now)) if tracker._same_kind(tr, label) else 0.0
            row.append(1e6 if score < tracker.min_iou else
                       (1.0 - score) + tracker.direction_weight * tracker._direction_penalty(tr, box))
        ref.append(row)
    new = tracker._cost_matrix(dets, live, now, 1e6)
    assert len(new) == len(ref) and len(new[0]) == len(ref[0])
    for i, row in enumerate(ref):
        for j, value in enumerate(row):
            assert new[i][j] == pytest.approx(value, abs=1e-9)


def test_the_vectorised_tracker_is_much_faster_than_the_reference():
    """A RELATIVE check, so it does not depend on the speed of the machine running the test.

    The workload is the egg line's: 175 detections against the tracks they accumulate over a few
    frames. The reference is the original double loop, one `iou()` call per pair."""
    cfg = dict(max_gap_s=30.0, min_iou=0.1, cold_gate=1.5)
    frames = [_belt_frame(random.Random(5), 175, t) for t in range(4)]
    tracker = T.make_tracker('ocsort', **cfg)
    for t, dets in enumerate(frames):           # build up the live tracks
        tracker.update(dets, t * 0.5)
    live = list(tracker.tracks)
    dets, now = frames[-1], 3 * 0.5
    assert len(live) > 100, 'the workload must be big enough to matter'

    t0 = time.perf_counter()
    for label, box in dets:                      # the original loop
        for tid in live:
            tr = tracker.tracks[tid]
            T.iou(box, tracker._predict(tr, now))
    ref_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    tracker._cost_matrix(dets, live, now, 1e6)
    new_time = time.perf_counter() - t0

    assert new_time < ref_time / 3.0, f'vectorised {new_time:.4f} s vs reference {ref_time:.4f} s'


def test_the_assignment_solver_is_optimal_and_matches_the_reference_solver():
    """Scipy's solver and the pure-Python one must agree on the TOTAL cost (both are optimal) and
    the pairs must be unique, for the matrix shape the egg line produces."""
    rng = random.Random(9)
    rows, cols = 40, 25
    cost = [[rng.uniform(0, 1) for _ in range(cols)] for _ in range(rows)]
    pairs = T.hungarian(cost)
    assert len(pairs) == min(rows, cols)
    assert len({r for r, _c in pairs}) == len(pairs)
    assert len({c for _r, c in pairs}) == len(pairs)
    total = sum(cost[r][c] for r, c in pairs)
    ref = _ref_hungarian(cost)
    assert abs(sum(cost[r][c] for r, c in ref) - total) < 1e-9
