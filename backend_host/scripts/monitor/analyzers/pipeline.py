"""Detect + attribute + track pipeline for non-TV profiles (counting_cars first), TASK-90 goal 5.

The profile's `img.analyzers` are a detector (`coco_detect`) followed by attributors (`hsv_colour`). Detection
runs on its own thread at the detector's `sample_hz` (like the localize worker), never on the frame worker, and
the newest result is attached to every frame's JSON in between. Detections are tracked (`monitor/tracking.py`)
and the profile's events and KPIs are computed from the tracks (`monitor/events.py`).
"""
import math
import logging
import os
import time

from monitor.analyzers.sampled import SampledWorkerAnalyzer
from monitor.events import ProfileEvents
from collections import Counter

from monitor.tracking import make_tracker

logger = logging.getLogger('capture_monitor')

def label_groups(events):
    """label -> group id: labels that one event lists together (car, truck, bus in `car_seen`) are one kind of object for
    tracking, so a detector flipping between them on the same vehicle does not open a new track (and count it twice)."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for spec in events.values():
        labels = list(spec.in_ or [])
        for other in labels[1:]:
            parent[find(other)] = find(labels[0])
    return lambda label: find(label)


DETECTORS = {'coco_detect', 'egg_detect', 'yolo_seg_detect'}
ATTRIBUTORS = {'hsv_colour', 'egg_classify'}
FOCUS_CROPS_KEPT = 40        # crops of the "last checked" panel kept per device in the metadata folder
FOCUS_CROP_MAX_PX = 160


class SceneCut:
    """When the source starts again (a device that plays one clip in a loop), the picture jumps and the counters would
    double the same objects once per pass.

    The signal is how much the picture CHANGED, not how many tracks were lost: in a busy scene a loop leaves plenty of
    matched tracks, but the frame after the loop is no longer the frame before it. A 32x18 grey descriptor of the frame
    is correlated with the previous sample's (mean of the product of two zero-mean, unit-variance descriptors, so 1.0 is
    the same picture), which is under a millisecond and needs no model. `cut_below` is that threshold.

    Measured on the cars clip: 0.92 median and 0.868 worst inside one pass, 0.836 across the loop, so the default sits
    below the worst in-clip value. It is a heuristic, which is why `every_s` (a plain timer) is the other trigger and
    why `cooldown_s` stops a busy scene from firing over and over.
    """

    SIZE = (32, 18)

    def __init__(self, cut_below: float = 0.86, for_samples: int = 2, cooldown_s: float = 10.0):
        self.cut_below = cut_below
        self.for_samples = for_samples
        self.cooldown_s = cooldown_s
        self._run = 0
        self._prev = None
        self._last = None

    @staticmethod
    def describe(frame):
        import cv2
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        g = cv2.resize(g, SceneCut.SIZE).astype('float32')
        return (g - g.mean()) / (g.std() + 1e-6)

    def feed(self, frame, now: float) -> bool:
        """True when this sample starts a new pass of the source."""
        desc = self.describe(frame)
        prev, self._prev = self._prev, desc
        if prev is None:
            return False
        similarity = float((desc * prev).mean())
        self._run = self._run + 1 if similarity < self.cut_below else 0
        if self._run < self.for_samples:
            return False
        self._run = 0
        if self._last is not None and now - self._last < self.cooldown_s:   # a restart already counted; let the loop run
            return False
        self._last = now
        return True


def _build_stage(spec):
    extra = {k: v for k, v in spec.model_dump().items() if k not in ('type', 'sample_hz')}
    if spec.type == 'coco_detect':
        from monitor.analyzers.coco_detect import CocoDetect
        return CocoDetect(**extra)
    if spec.type == 'hsv_colour':
        from monitor.analyzers.hsv_colour import HsvColour
        return HsvColour(**extra)
    if spec.type == 'egg_detect':
        from monitor.analyzers.egg_detect import EggDetect
        return EggDetect(**extra)
    if spec.type == 'yolo_seg_detect':
        from monitor.analyzers.yolo_seg_detect import YoloSegDetect
        return YoloSegDetect(**extra)
    if spec.type == 'egg_classify':
        from monitor.analyzers.egg_classify import EggClassify
        return EggClassify(**extra)
    raise ValueError(f"pipeline cannot run analyzer type {spec.type!r}")


class PipelineAnalyzer(SampledWorkerAnalyzer):
    name = 'pipeline'
    _reset_cfg = None        # `img.reset_counters` as a dict, or None: counters run for ever unless a profile asks

    def __init__(self, core, profile):
        specs = profile.img.analyzers
        if specs[0].type not in DETECTORS or any(s.type not in ATTRIBUTORS for s in specs[1:]):
            raise ValueError(f"profile {profile.name!r}: img.analyzers must be one detector then attributors "
                             f"(detectors {sorted(DETECTORS)}, attributors {sorted(ATTRIBUTORS)})")
        self.detector = _build_stage(specs[0])
        self.attributors = [_build_stage(s) for s in specs[1:]]
        super().__init__(core, profile, specs[0].sample_hz or 2.0)
        t = profile.img.track
        self._algo = t.algo if t else 'iou'
        self._track_cfg = dict(max_gap_s=t.max_gap_s, min_iou=t.min_iou) if t else {}
        if t and t.algo == 'ocsort' and t.cold_gate:
            self._track_cfg['cold_gate'] = t.cold_gate
        self._track_cfg['label_group'] = label_groups(profile.events)
        self.votes = t.votes if t else 1
        self.count_line_x = t.count_line_x if t else None
        self.count_sign = -1.0 if t and t.count_dir == 'left' else 1.0
        self.min_votes = (t.min_votes or t.votes) if t else 1
        rc = getattr(profile.img, 'reset_counters', None)
        self._reset_cfg = rc.model_dump() if rc is not None else None
        self.primary = self.attributors[0].attr if self.attributors else None   # the attribute whose value is the verdict
        self.ui = profile.ui.model_dump(exclude_none=True) if getattr(profile, 'ui', None) else None
        # where the "last checked" crops go: the device's metadata folder (served like the other metadata files)
        self.focus_dir_fn = None
        if core is not None:
            from shared.src.lib.utils.storage_path_utils import get_metadata_path
            self.focus_dir_fn = get_metadata_path

    # ---- Analyzer interface (start/analyze/frame_record/chunk_fields/worker: SampledWorkerAnalyzer) ------------
    def register_device(self, capture_folder):
        self._drop_old_crops(capture_folder)
        with self._lock:
            self._state[capture_folder] = {
                'tracker': make_tracker(self._algo, **self._track_cfg),
                'events': ProfileEvents(self.profile.events, self.profile.kpis, self.profile.incidents),
                'cut': self._make_cut(),
                'last_run': 0.0, 'focus': None, 'crops': [], 'restarts': 0, 'counting_since': None,
                'reset_every_at': None,
            }

    def _drop_old_crops(self, folder):
        """focus_*.jpg of a previous run: the in-memory list of crops is empty after a restart, so nothing else would ever delete them from the
        (tmpfs) metadata folder, and chunk entries written before the restart point at crops that no longer matter."""
        d = self.focus_dir_fn(folder) if self.focus_dir_fn else None
        if not d or not os.path.isdir(d):
            return
        for name in os.listdir(d):
            if name.startswith('focus_') and name.endswith('.jpg'):
                try:
                    os.remove(os.path.join(d, name))
                except OSError:
                    pass

    def _make_cut(self):
        """The scene-cut trigger, only when the profile asks for one (`cut_below`); `every_s` alone needs no picture work."""
        cfg = self._reset_cfg or {}
        if cfg.get('cut_below') is None:
            return None
        return SceneCut(cut_below=cfg['cut_below'], for_samples=cfg.get('for_samples', 2),
                        cooldown_s=cfg.get('cooldown_s', 10.0))

    def _restart(self, state, frame, ts) -> bool:
        """True when this sample starts a new pass of the source, so the counters go back to 0.

        Two triggers, both optional, whichever comes first: `every_s` (the clip is that long, so one pass is that long —
        deterministic, no thresholds) and a scene cut (the picture jumped, which catches a loop of any length and a
        stream that changed under us).
        """
        if self._reset_cfg is None:
            return False
        every = state['reset_every_at']
        if every is not None and ts >= every:
            state['reset_every_at'] = ts + self._reset_cfg['every_s']
            return True
        return bool(state['cut'] and state['cut'].feed(frame, ts))

    def process(self, folder, frame_path, ts):
        """Detect, attribute, track and update events/KPIs for one frame; store the result for frame_record."""
        from shared.src.lib.utils import cv2_io   # contract #30: never cv2.imread in long-running code
        state = self._state[folder]
        state['last_run'] = time.time()
        if state['counting_since'] is None:
            state['counting_since'] = ts
            every = (self._reset_cfg or {}).get('every_s')
            if every:
                state['reset_every_at'] = ts + every
        frame = cv2_io.imread(frame_path)
        if frame is None:
            return None
        detections = self.detector.detect(frame)
        # a looping file starts again: count one pass, not the whole day
        if self._restart(state, frame, ts):
            with self._lock:
                state['tracker'] = make_tracker(self._algo, **self._track_cfg)
            state['events'].reset()
            state['focus'] = None
            state['restarts'] += 1
            state['counting_since'] = ts
        tracker = state['tracker']
        matched = tracker.update([(d.label, d.bbox) for d in detections], ts)
        observations, finalized = [], []
        voted = None
        counted = None    # the object that just crossed the count line, if the profile counts at one
        for di, track, is_new in matched:
            d = detections[di]
            if track.n_votes < self.votes:
                self._vote(track, frame, d)
                voted = (track, d)
            if self.count_line_x is not None:
                # BUG-0915: counted when the centre crosses the line in the direction of travel, once per track. The
                # previous centre is the track's own last one, so a track missed for a few samples still crosses.
                line = self.count_line_x * frame.shape[1]
                cx = d.bbox[0] + d.bbox[2] / 2.0
                prev = track.line_cx
                if (not track.finalized and prev is not None
                        and self.count_sign * (prev - line) < 0 <= self.count_sign * (cx - line)):
                    finalized.append(self._finalize(track))
                    counted = (track, d)
                track.line_cx = cx
            elif tracker.confirmed(track) and not track.finalized and track.n_votes >= self.votes:
                finalized.append(self._finalize(track))
            obs = {
                'label': track.label, 'track_id': track.track_id, 'conf': round(d.conf, 3),
                'bbox': [round(v, 1) for v in d.bbox], 'attrs': dict(track.attrs),
            }
            if getattr(d, 'shape', None):
                obs['shape'] = d.shape
            if getattr(d, 'size_mm', None) is not None:
                obs['size_mm'] = d.size_mm
            if self.votes > 1:
                obs['votes'] = f"{min(track.n_votes, self.votes)}/{self.votes}"
            if self.primary:
                obs['verdict'] = track.attrs.get(self.primary) if track.finalized else None
                obs['probs'] = self._probs(track)
            # Centre velocity in px/s, the same estimate the tracker matches on (BUG-0836). The frame JSON is
            # written up to `sample_hz` period + analysis time + one poll interval after the frame was captured,
            # and the overlay is drawn on a *live* video that is even later. A belt of eggs moves in that gap,
            # so the overlay boxes drift off the eggs. These two numbers let the client put each box back where
            # its object is now instead of where it was when the monitor looked.
            # and for the same reason. A threshold, because the detector's centre jitters by a fraction of a pixel
            # between two encodings of the same picture: an object that has not moved reports no motion at all
            # rather than a velocity of 0.3 px/s that the client would then add to nothing.
            vx, vy = tracker.velocity(track) if hasattr(tracker, 'velocity') else (0.0, 0.0)
            if math.hypot(vx, vy) >= 2.0:
                obs['v'] = [round(vx, 1), round(vy, 1)]
            observations.append(obs)
        # The "last checked" panel and the gold outline. With a count line it is the last object COUNTED: the newest
        # track to vote is mostly a fresh, low-confidence detection, and on the egg belt it was often bare belt.
        focus_on = counted if self.count_line_x is not None else voted
        if focus_on is not None:
            self._set_focus(state, folder, frame, *focus_on)
        for track in tracker.pop_ended():                # tracks that left the frame
            if self.count_line_x is None and not track.finalized and tracker.confirmed(track):
                finalized.append(self._finalize(track, left=True))
        self._finish_focus(state, finalized)
        events, kpis, incidents = state['events'].update(observations, finalized, ts)
        result = {'frame_size': [frame.shape[1], frame.shape[0]], 'observations': observations,
                  'events': events, 'kpis': kpis}
        if self._reset_cfg:
            result['counting'] = {'restarts': state['restarts'], 'since': state['counting_since']}
        if incidents:
            result['incidents'] = incidents
        if self.ui:
            result['ui'] = self.ui
        if state['focus']:
            result['focus'] = state['focus']
        with self._lock:
            self._latest[folder] = result
        return result

    def settle(self, folder, ts):
        """Advance the clock to `ts` with nothing in view: tracks past max_gap_s end and their verdicts are emitted.
        Used at the end of an offline clip; returns the result like process()."""
        state = self._state[folder]
        tracker = state['tracker']
        tracker.update([], ts)
        finalized = [self._finalize(t, left=True) for t in tracker.pop_ended()
                     if self.count_line_x is None and not t.finalized and tracker.confirmed(t)]
        events, kpis, incidents = state['events'].update([], finalized, ts)
        return {'observations': [], 'events': events, 'kpis': kpis, 'incidents': incidents}

    # ---- votes ---------------------------------------------------------------------------------
    def _vote(self, track, frame, det):
        """One vote per attribute at this sample of the track; an attributor that knows probabilities adds them up."""
        for att in self.attributors:
            if hasattr(att, 'classify_det'):
                value, probs = att.classify_det(frame, det)
            else:
                value, probs = att.classify(frame, det.bbox), None
            track.votes.setdefault(att.attr, []).append(value)
            if probs:
                acc = track.probs.setdefault(att.attr, {})
                for cls, p in probs.items():
                    acc[cls] = acc.get(cls, 0.0) + p
        track.n_votes += 1
        for attr, values in track.votes.items():       # provisional attributes: the majority so far (a tie keeps the earlier value)
            track.attrs[attr] = Counter(values).most_common(1)[0][0]

    def _probs(self, track):
        """Probability per class of the primary attribute: the mean of the classifier's probabilities over the votes, or the
        share of votes for an attributor that only names a class (colour from a histogram)."""
        attr = self.primary
        if track.n_votes == 0 or attr not in track.votes:
            return {}
        if attr in track.probs:
            return {c: round(v / track.n_votes, 3) for c, v in track.probs[attr].items()}
        counts = Counter(track.votes[attr])
        return {c: round(n / track.n_votes, 3) for c, n in counts.items()}

    def _set_focus(self, state, folder, frame, track, det):
        """The most recently checked item for the "last checked" panel: its crop, verdict so far and probabilities."""
        probs = self._probs(track)
        verdict = track.attrs.get(self.primary) if self.primary else None
        focus = {'track_id': track.track_id, 'check': min(track.n_votes, self.votes), 'checks': self.votes,
                 'verdict': verdict, 'final': False, 'probs': probs, 'crop': None}
        folder_dir = self.focus_dir_fn(folder) if self.focus_dir_fn else None
        if folder_dir:
            try:
                from shared.src.lib.utils import cv2_io
                import cv2
                x, y, w, h = det.bbox
                mx, my = w * 0.12, h * 0.12
                crop = frame[int(max(0, y - my)):int(y + h + my), int(max(0, x - mx)):int(x + w + mx)]
                if crop.size:
                    r = min(1.0, FOCUS_CROP_MAX_PX / max(crop.shape[:2]))
                    if r < 1.0:
                        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * r)), max(1, int(crop.shape[0] * r))), interpolation=cv2.INTER_AREA)
                    name = f"focus_{track.track_id}_{focus['check']}.jpg"
                    os.makedirs(folder_dir, exist_ok=True)
                    if cv2_io.imwrite(os.path.join(folder_dir, name), crop, [cv2.IMWRITE_JPEG_QUALITY, 80]):
                        focus['crop'] = name                       # relative to the device's metadata folder
                        state['crops'].append(os.path.join(folder_dir, name))
                        while len(state['crops']) > FOCUS_CROPS_KEPT:
                            try:
                                os.remove(state['crops'].pop(0))
                            except OSError:
                                pass
            except Exception as e:                                  # the panel works without a crop
                logger.warning(f"[{folder}] focus crop failed: {e}")
        state['focus'] = focus

    @staticmethod
    def _finish_focus(state, finalized):
        """When the focused item's verdict becomes final, show the final verdict."""
        f = state['focus']
        if not f:
            return
        for fin in finalized:
            if fin['track_id'] == f['track_id']:
                f['final'] = True
                f['verdict'] = fin['verdict']

    def _finalize(self, track, left=False):
        """Emit the track's verdict once. A track that left the frame with fewer than min_votes is `unverified`."""
        track.finalized = True
        track.counted = True
        if left and track.n_votes < self.min_votes:
            for attr in track.votes:
                track.attrs[attr] = 'unverified'
            if not track.votes:
                for att in self.attributors:
                    track.attrs[att.attr] = 'unverified'
        return {'track_id': track.track_id, 'label': track.label, 'attrs': dict(track.attrs),
                'verdict': track.attrs.get(self.primary) if self.primary else None}
