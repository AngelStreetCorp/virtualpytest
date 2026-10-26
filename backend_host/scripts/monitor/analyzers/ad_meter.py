"""ad_meter: commercial breaks on a live TV channel, from the picture alone (TASK-90 goal 10).

Three cheap signals, no model and nothing drawn by hand:

* the channel's on-screen mark (logo bug) is LEARNED from the device's own stream: the per-pixel median of a corner over the last
  30 minutes keeps whatever stays put while the picture changes, so the mark shows up and the content averages away. Each sample
  is scored against that median (zero-mean correlation of the high-passed corner): high = mark there, low = gone. The corner whose
  scores split cleanest into "there" and "gone" is the mark's corner. The mark is re-learned after a channel change (`reset_mark`,
  or automatically when the mark stays gone with no cutting for `relearn_after_s`);
* the cut rate: a hard cut is a jump of the 32-bin grey histogram between two samples. Ads cut about three times as often as programmes;
* a break is "mark gone AND cut rate high" for `open_s`, with hysteresis, and it has to last `min_break_s`.

A closed break is one `ad_break` event with a span (start, end). KPIs and the overlay's AD badge come from monitor/events.py.

Repetition: every sample inside a break leaves a 64-bit difference hash in a per-device library (`ad_library.json` next to the device's
folders, 20 000 hashes at most). A break whose frames are mostly already in the library from earlier breaks is `confirmed` (the same
spots again), otherwise `new`. The library also helps detection, without being able to confirm its own mistakes: a hash enters as a
candidate and only becomes an active spot when `lib_min_repeat` (3) different breaks have it. `lib_run` (6) consecutive samples on active spots
are evidence of a break on their own (they open a break even with the mark on screen or slow cutting) and the break's start snaps back
to where the recognised spot began. A second store, `ad_not_library.json`, holds content that was marked as not an ad (a programme opener
that was taken for a break): `lib_run` consecutive samples on it cancel the evidence. It is filled only by `mark_not_ad(folder, break_id)`; nothing calls it yet, an
endpoint for the timeline page (TASK-94) has to be added. Audio loudness is not used: on the SRF 1 buffer it separates ads from programmes with an AUC of 0.55.
"""
import hashlib
import json
import logging
import os
import shutil
from collections import deque

import numpy as np

from monitor.analyzers.sampled import SampledWorkerAnalyzer
from monitor.events import ProfileEvents

logger = logging.getLogger('capture_monitor')

CORNERS = ('top-left', 'top-right', 'bottom-left', 'bottom-right')
PW, PH = 64, 32                       # corner patch at a 320 px wide frame; doubled for wider frames, where the mark has more pixels
BLACK_LUMA = 20
_POP8 = np.array([bin(i).count('1') for i in range(256)], dtype=np.uint8)


# ---- picture features --------------------------------------------------------------------------

def _scale_for(width):
    return 1 if width <= 480 else 2


def corner_patches(gray, scale=None):
    """(4, PH*s, PW*s) uint8: the four corner regions (PW/320 x PH/180 of the frame each), resized to a fixed patch."""
    import cv2
    h, w = gray.shape[:2]
    s = scale or _scale_for(w)
    rw, rh = max(1, round(w * PW / 320)), max(1, round(h * PH / 180))
    regions = [gray[:rh, :rw], gray[:rh, w - rw:], gray[h - rh:, :rw], gray[h - rh:, w - rw:]]
    out = []
    for r in regions:
        if r.shape[1] != PW * s or r.shape[0] != PH * s:
            r = cv2.resize(r, (PW * s, PH * s), interpolation=cv2.INTER_AREA)
        out.append(r)
    return np.stack(out)


def highpass(patch, scale=1):
    """The patch minus its box blur: keeps the small sharp mark, drops the picture's slow content."""
    import cv2
    k = 4 * scale + 1
    f = patch.astype(np.float32)
    return f - cv2.blur(f, (k, k), borderType=cv2.BORDER_REPLICATE)


def ncc(a, b):
    """Zero-mean normalised correlation of two arrays of the same shape (-1..1)."""
    a = a.ravel() - a.mean()
    b = b.ravel() - b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b) / d if d > 1e-6 else 0.0


def grey_hist(small_gray):
    import cv2
    h = cv2.calcHist([small_gray], [0], None, [32], [0, 256]).ravel()
    return h / max(1.0, h.sum())


def dhash(small_gray):
    """64-bit difference hash (9x8 grey, left < right per pixel) as an unsigned integer."""
    import cv2
    t = cv2.resize(small_gray, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    bits = (t[:, 1:] > t[:, :-1]).ravel()
    return int(np.packbits(bits).view('>u8')[0])


def _without_corners(small):
    """The 160x90 grey frame with its four corner patches (where the channel mark lives) filled with the frame's mean."""
    out = small.copy()
    h, w = out.shape
    ph, pw = max(1, round(h * PH / 180)), max(1, round(w * PW / 320))
    m = int(out.mean())
    out[:ph, :pw] = m
    out[:ph, w - pw:] = m
    out[h - ph:, :pw] = m
    out[h - ph:, w - pw:] = m
    return out


def _hamming(arr, q):
    x = np.bitwise_xor(arr, np.uint64(q))
    return _POP8[x.view(np.uint8).reshape(-1, 8)].sum(axis=1)


# ---- the learned mark ---------------------------------------------------------------------------

def choose_corner(scores):
    """scores: (n, 4) correlation of every ring sample with its corner's median. The corner whose scores split best into a
    "mark there" cluster (the larger one) and a "mark gone" cluster (Otsu split) is the mark's; None when no corner splits
    cleanly (a channel that shows no mark, or too little data)."""
    best, best_ratio = None, 0.0
    for c in range(scores.shape[1]):
        v = np.sort(scores[:, c])
        n = len(v)
        if n < 20 or v[-1] - v[0] < 0.2:
            continue                                     # no spread: nothing to split (the always-there rule below may still apply)
        csum = np.cumsum(v)
        total = csum[-1]
        k = np.arange(1, n)
        w0, w1 = k / n, 1 - k / n
        m0, m1 = csum[:-1] / k, (total - csum[:-1]) / (n - k)
        between = w0 * w1 * (m1 - m0) ** 2
        i = int(np.argmax(between))
        share_upper, gap = 1 - w0[i], m1[i] - m0[i]
        var = float(np.var(v))
        ratio = float(between[i]) / var if var > 0 else 0.0
        if 0.4 <= share_upper <= 0.97 and gap >= 0.25 and ratio > best_ratio:
            best, best_ratio = c, ratio
    if best is None and scores.shape[0] >= 20:
        p5 = [float(np.percentile(scores[:, c], 5)) for c in range(scores.shape[1])]
        c = int(np.argmax(p5))
        if p5[c] >= 0.45:
            best = c
    return best


class MarkLearner:
    """Ring of corner patches (one per `every_s`), the median template per corner, and the chosen mark corner."""

    def __init__(self, window_s=1800, every_s=4.0, warmup_s=120, refresh_s=120, keep_corner_s=600):
        self.window_s, self.every_s, self.warmup_s, self.refresh_s = window_s, every_s, warmup_s, refresh_s
        self.keep_corner_s = keep_corner_s
        self.reset()

    def reset(self):
        self.ring = deque(maxlen=max(10, int(self.window_s / self.every_s)))   # (ts, (4, ph, pw) uint8)
        self.template = None          # (4, ph, pw) float32, high-passed median per corner
        self.corner = None            # index of the mark's corner, or None
        self.scale = 1
        self._last_add = -1e18
        self._last_refresh = -1e18
        self._corner_ok = -1e18       # when a refresh last found a clean corner
        self.mark_id = None           # 8 hex of the first template of this learning session: tells the channels (marks) apart

    def drop_since(self, ts):
        """Forget samples newer than ts (the head of a break that was only recognised later: ads must not teach the mark)."""
        while self.ring and self.ring[-1][0] >= ts:
            self.ring.pop()

    def add(self, ts, patches, scale):
        self.scale = scale
        if ts - self._last_add >= self.every_s:
            self.ring.append((ts, patches))
            self._last_add = ts

    def ready(self, ts):
        return len(self.ring) >= 2 and self.ring[-1][0] - self.ring[0][0] >= self.warmup_s

    def refresh_due(self, ts):
        return self.ready(ts) and ts - self._last_refresh >= self.refresh_s

    def refresh(self, ts):
        n = len(self.ring)
        template, scores = [], np.empty((n, 4))
        for c in range(4):                                               # one corner at a time: the median's temporaries stay small
            stack = np.stack([p[c] for _, p in self.ring])               # (n, ph, pw)
            template.append(highpass(np.median(stack, axis=0), self.scale))
            for i in range(n):
                scores[i, c] = ncc(highpass(stack[i], self.scale), template[c])
            del stack
        template = np.stack(template)
        corner = choose_corner(scores)
        self._last_refresh = ts
        if corner is None and self.corner is not None and ts - self._corner_ok < self.keep_corner_s:
            return                       # a stretch with no clear mark (a bright documentary): keep what was learned before it
        self.template, self.corner = template, corner
        if corner is not None:
            self._corner_ok = ts
            if self.mark_id is None:
                bits = np.packbits((template[corner] > 0).ravel()).tobytes()
                self.mark_id = hashlib.sha1(bytes([corner]) + bits).hexdigest()[:8]

    def score(self, patches):
        """Correlation of this sample's mark corner with the template, or None while there is no mark corner."""
        if self.template is None or self.corner is None:
            return None
        return ncc(highpass(patches[self.corner], self.scale), self.template[self.corner])


# ---- the repetition library ---------------------------------------------------------------------

class SpotStore:
    """Hashes of frames seen inside breaks. Per hash: how often, in how many DIFFERENT breaks, and when last. An entry seen in one break only
    is a candidate: it takes no part in detection. It becomes an active spot when `min_breaks` different breaks have it (3 in the shipped settings), so a false break
    (a programme opener) cannot confirm itself. The same class holds the "not ad" hashes (entries that are active at once)."""

    def __init__(self, path=None, max_items=20000, hamming=6):
        self.path, self.max_items, self.hamming = path, max_items, hamming
        self._empty()
        if path and os.path.isfile(path):
            try:
                with open(path) as f:
                    d = json.load(f)
                self.h = np.array([int(x, 16) for x in d['hash']], dtype=np.uint64)
                self.count = np.array(d['count'], dtype=np.int32)
                self.breaks = np.array(d['breaks'], dtype=np.int16)
                self.last = np.array(d['last'], dtype=np.float64)
                self.last_break = np.array(d['last_break'], dtype=np.int64)
            except Exception as e:                       # a damaged library is only a library: start again
                logger.warning(f"ad library {path} unreadable ({e}); starting empty")
                self._empty()

    def _empty(self):
        self.h = np.zeros(0, dtype=np.uint64)
        self.count = np.zeros(0, dtype=np.int32)
        self.breaks = np.zeros(0, dtype=np.int16)
        self.last = np.zeros(0, dtype=np.float64)
        self.last_break = np.zeros(0, dtype=np.int64)

    def __len__(self):
        return len(self.h)

    def active(self, min_breaks):
        return int((self.breaks >= min_breaks).sum())

    def match(self, q, min_breaks=1):
        """Is `q` within the Hamming distance of an entry seen in at least `min_breaks` breaks?"""
        if not len(self.h):
            return False
        return bool(((_hamming(self.h, q) <= self.hamming) & (self.breaks >= min_breaks)).any())

    def match_share(self, hashes, min_breaks=1):
        if not hashes or not len(self.h):
            return 0.0
        return sum(1 for q in hashes if self.match(q, min_breaks)) / len(hashes)

    def add_break(self, hashes, now, break_id):
        """Add the hashes of one break: an entry that already exists gains a count, and a break count when it comes from another break."""
        for q in hashes:
            if len(self.h):
                d = _hamming(self.h, q)
                i = int(np.argmin(d))
                if d[i] <= self.hamming:
                    self.count[i] += 1
                    self.last[i] = now
                    if self.last_break[i] != break_id:
                        self.breaks[i] += 1
                        self.last_break[i] = break_id
                    continue
            self.h = np.append(self.h, np.uint64(q))
            self.count = np.append(self.count, 1)
            self.breaks = np.append(self.breaks, 1)
            self.last = np.append(self.last, now)
            self.last_break = np.append(self.last_break, break_id)
        if len(self.h) > self.max_items:                 # forget what was seen least recently
            keep = np.argsort(self.last)[-self.max_items:]
            self.h, self.count, self.breaks, self.last, self.last_break = (
                self.h[keep], self.count[keep], self.breaks[keep], self.last[keep], self.last_break[keep])

    def remove_matching(self, hashes):
        """Forget every entry within the Hamming distance of one of `hashes` (a break that was not an ad)."""
        if not hashes or not len(self.h):
            return 0
        drop = np.zeros(len(self.h), dtype=bool)
        for q in hashes:
            drop |= _hamming(self.h, q) <= self.hamming
        n = int(drop.sum())
        if n:
            k = ~drop
            self.h, self.count, self.breaks, self.last, self.last_break = (
                self.h[k], self.count[k], self.breaks[k], self.last[k], self.last_break[k])
        return n

    def save(self):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump({'v': 2, 'hash': [format(int(x), '016x') for x in self.h], 'count': self.count.tolist(),
                           'breaks': self.breaks.tolist(), 'last': [round(float(x), 1) for x in self.last],
                           'last_break': self.last_break.tolist()}, f)
            os.replace(tmp, self.path)
        except OSError as e:
            logger.warning(f"ad library not saved: {e}")


# ---- the analyzer -------------------------------------------------------------------------------

def _num(x):
    """x as a float when it is a real number (not a bool, not a string), else None."""
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _zone(name):
    if not name:
        return None
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


class _Device:
    def __init__(self, profile, p, library_path, folder='', breaks_path=None):
        self.learner = MarkLearner(p['mark_window_s'], p['mark_every_s'], p['warmup_s'])
        self.events = ProfileEvents(profile.events, profile.kpis, profile.incidents, tz=_zone(p['timezone']))
        self.folder = folder
        self.breaks_path = breaks_path   # ad_breaks.jsonl: closed breaks and start markers, so a restart rebuilds today's KPIs
        self.restored = False
        self.last_alive = -1e18
        self.pending_close = None
        self.action_path = None       # <metadata>/last_action.json: the system sent a remote action (a possible zap)
        self.action_ts = None
        self.action_checked = -1e18
        self.library = SpotStore(library_path, p['library_max'], p['library_hamming']) if p['library'] else None
        self.notad = None
        self.hashes_path = None
        if p['library'] and library_path:
            base = os.path.dirname(library_path)
            self.notad = SpotStore(os.path.join(base, 'ad_not_library.json'), 2000, p['library_hamming'])
            self.hashes_path = os.path.join(base, 'ad_break_hashes.json')
        elif p['library']:
            self.notad = SpotStore(None, 2000, p['library_hamming'])
        self.lib_run = 0
        self.notad_run = 0
        self.libhist = deque()        # (ts, on a spot for lib_run samples) of the last 180 s: where a recognised spot began
        self.break_hashes = {}        # id -> hashes of the last closed breaks, for mark_not_ad
        self.prev_hist = None
        self.cuts = deque()           # timestamps of hard cuts, last 30 s
        self.marks = deque()          # (ts, score) of the last mark_smooth_s
        self.evidence = deque()       # (ts, bool) of the last max(open_s, close_s)
        self.hashes = deque()         # (ts, hash, blank) of the last hash_keep_s: the head of a break was seen before it opened
        self.brk = None               # {'id', 'start', 'last_ev'} while a break is open
        self.ads_dir = None           # <device>/ads: the thumbnails of each break (served by the host's stream route) and correction requests
        self.requests_checked = -1e18
        self.next_id = 1
        self.quiet_since = None       # since when the mark has been gone with no break evidence
        self.last_run = 0.0
        self.last_ts = 0.0
        self.last_result = None


DEFAULTS = {
    'warmup_s': 120, 'mark_window_s': 1800, 'mark_every_s': 4.0, 'mark_smooth_s': 10.0, 'mark_absent': 0.25,
    'cut_hist': 0.33, 'cuts_per_30s': 8, 'open_s': 30.0, 'open_ratio': 0.7, 'close_s': 45.0, 'close_ratio': 0.2,
    'min_break_s': 90.0, 'relearn_after_s': 240.0, 'hash_keep_s': 60.0,
    'library': True, 'library_max': 20000, 'library_hamming': 6, 'confirm_share': 0.3,
    'max_break_s': 900.0,         # a break longer than this is not believed: closed as suspect_overlong (not counted, not learned), the mark is learned again
    'max_break_hashes': 4000,     # most hashes kept for one open break (2 h at 2 Hz): bounds memory and the library update
    'zap_window_s': 10.0,         # a black sample this soon after a system-sent action (last_action.json) is a channel change
    'lib_assist': True,           # the library helps detection (False: it only labels breaks confirmed / new)
    'lib_min_repeat': 3,          # different breaks that must contain a hash before it counts as a spot
    'lib_run': 6,                 # consecutive samples (3 s at 2 Hz) on spots that are evidence of a break
    'lib_open_s': 6.0,            # seconds of such evidence that open a break without the mark and cut conditions
    'snap_s': 90.0,               # how far before the evidence-based start a recognised spot may pull the start
    'snap_gap_s': 4.0,            # a pause (black frames) allowed inside a recognised run
    'head_s': 0.0,                # frames this long before the evidence-based start also go into the library: the evidence is late by its build-up
    'blank_std': 6.0,             # frames flatter than this are not hashed (black or one colour: every such frame looks alike)
    'lib_min_confidence': 0.5,    # a break feeds the library only at this confidence
    'timezone': None,             # IANA name for "today" (Europe/Zurich); None = the host's local time
    'alive_every_s': 60.0,        # a heartbeat marker in ad_breaks.jsonl: what an outage leaves tells when the monitor was really watching
    'keep_days': 3,               # days of ad_breaks.jsonl kept (and of the break thumbnails in ads/)
    'thumb_every_s': 30.0,        # while a break runs, one thumbnail at its start and then every this many seconds, for the review
    'thumb_width': 320,           # thumbnail width in pixels (JPEG quality 70: ~15 kB each)
}


class AdMeterAnalyzer(SampledWorkerAnalyzer):
    name = 'ad_meter'

    def __init__(self, core, profile, library_dir_fn=None, action_dir_fn=None):
        spec = profile.img.analyzers[0]
        extra = {k: v for k, v in spec.model_dump().items() if k not in ('type', 'sample_hz')}
        unknown = set(extra) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"ad_meter: unknown settings {sorted(unknown)}; known: {sorted(DEFAULTS)}")
        self.p = {**DEFAULTS, **extra}
        super().__init__(core, profile, spec.sample_hz or 2.0)
        self.ui = profile.ui.model_dump(exclude_none=True) if getattr(profile, 'ui', None) else None
        self.library_dir_fn = library_dir_fn
        self.action_dir_fn = action_dir_fn
        if core is not None:
            from shared.src.lib.utils.storage_path_utils import get_device_base_path, get_metadata_path
            if library_dir_fn is None:
                self.library_dir_fn = get_device_base_path
            if action_dir_fn is None:
                self.action_dir_fn = get_metadata_path

    # ---- Analyzer interface ---------------------------------------------------------------------
    def register_device(self, capture_folder):
        path = breaks = None
        if self.library_dir_fn:
            base = self.library_dir_fn(capture_folder)
            breaks = os.path.join(base, 'ad_breaks.jsonl')
            if self.p['library']:
                path = os.path.join(base, 'ad_library.json')
        with self._lock:
            dev = self._state[capture_folder] = _Device(self.profile, self.p, path, capture_folder, breaks)
        if breaks:
            dev.ads_dir = os.path.join(os.path.dirname(breaks), 'ads')
        if self.action_dir_fn:
            dev.action_path = os.path.join(self.action_dir_fn(capture_folder), 'last_action.json')

    def chunk_fields(self, analysis_data):
        out = super().chunk_fields(analysis_data)
        out['ad'] = analysis_data.get('ad')
        return out

    def reset_mark(self, folder):
        """The channel changed (a zap): forget the learned mark; breaks are not detected until it is learned again. Called when a black sample follows
        a system-sent action (_zap_check) and after a suspect_overlong break; a zap with the physical remote has no signal to call it."""
        dev = self._state[folder]
        dev.learner.reset()
        dev.marks.clear()
        dev.evidence.clear()
        dev.quiet_since = None

    # ---- worker ---------------------------------------------------------------------------------
    def process(self, folder, frame_path, ts):
        import time
        from shared.src.lib.utils import cv2_io   # contract #30: never cv2.imread in long-running code
        dev = self._state[folder]
        dev.last_run = time.time()
        frame = cv2_io.imread(frame_path)
        if frame is None:
            return None
        return self.process_frame(folder, frame, ts)

    def process_frame(self, folder, frame, ts):
        """One sample: features, mark score, evidence, the break state machine, events and KPIs. Returns the result that is
        attached to the frames until the next sample."""
        import cv2
        p = self.p
        dev = self._state[folder]
        dev.last_ts = ts
        if not dev.restored:
            self._restore(dev, ts)
        elif ts - dev.last_alive >= p['alive_every_s']:
            dev.last_alive = ts
            self._append(dev, {'type': 'alive', 't': round(ts, 1)})
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        luma = float(small.mean())
        hist = grey_hist(small)
        if dev.prev_hist is not None and 0.5 * float(np.abs(hist - dev.prev_hist).sum()) >= p['cut_hist']:
            dev.cuts.append(ts)
        dev.prev_hist = hist
        while dev.cuts and ts - dev.cuts[0] > 30.0:
            dev.cuts.popleft()
        h = dhash(_without_corners(small))
        if self._zap_check(dev, ts, float(small.mean()) < BLACK_LUMA):
            dev.cuts.clear()                 # the mark's corners are flattened first: a spot hashes the same with or without the mark
        blank = float(small.std()) < p['blank_std']
        dev.hashes.append((ts, h, blank))
        if dev.brk is not None and not blank and len(dev.brk['hashes']) < p['max_break_hashes']:
            dev.brk['hashes'].append((ts, h))
        while dev.hashes and ts - dev.hashes[0][0] > max(p['hash_keep_s'], p['open_s'] + p['head_s'] + 5):
            dev.hashes.popleft()
        hit = notad_hit = False
        if dev.library is not None and not blank:
            hit = p['lib_assist'] and dev.library.match(h, p['lib_min_repeat'])
            notad_hit = dev.notad.match(h, 1)                  # a person's correction applies whatever lib_assist says
        dev.lib_run = dev.lib_run + 1 if hit else 0
        dev.notad_run = dev.notad_run + 1 if notad_hit else 0
        lib_ev = dev.lib_run >= p['lib_run']
        notad_ev = dev.notad_run >= p['lib_run']
        dev.libhist.append((ts, lib_ev))
        while dev.libhist and ts - dev.libhist[0][0] > 180.0:
            dev.libhist.popleft()

        scale = _scale_for(gray.shape[1])
        patches = corner_patches(gray, scale)
        learner = dev.learner
        if dev.brk is None:
            learner.add(ts, patches, scale)       # a break teaches the mark nothing
        if learner.refresh_due(ts):
            learner.refresh(ts)
        score = learner.score(patches)
        if score is not None:
            dev.marks.append((ts, score))
        while dev.marks and ts - dev.marks[0][0] > p['mark_smooth_s']:
            dev.marks.popleft()
        smooth = float(np.median([s for _, s in dev.marks])) if dev.marks else None

        cuts_30 = len(dev.cuts)
        if smooth is None:
            state, by_mark = ('learning' if not learner.ready(ts) else 'no_mark'), False
        else:
            by_mark = smooth < p['mark_absent'] and cuts_30 >= p['cuts_per_30s']
            state = 'program'
        evidence = (by_mark or lib_ev) and not notad_ev          # known programme content cancels the evidence, a known spot adds to it
        self._relearn_check(dev, ts, smooth, by_mark)
        finalized = self._step(dev, ts, evidence, lib_ev)
        if dev.brk is not None:
            state = 'ad'
            self._thumb(dev, frame, ts)
        self._take_requests(folder, dev, ts)
        obs = []
        if dev.brk is not None:
            obs.append({'label': 'ad_break', 'track_id': dev.brk['id'], 'conf': 1.0, 'start': dev.brk['start'],
                        'attrs': {'state': 'ad', 'kind': 'new'}})
        events, kpis, incidents = dev.events.update(obs, finalized, ts)
        result = {'frame_size': [int(frame.shape[1]), int(frame.shape[0])], 'observations': [], 'events': events, 'kpis': kpis,
                  'ad': {'state': state, 'mark': None if smooth is None else round(smooth, 3),
                         'corner': None if learner.corner is None else CORNERS[learner.corner],
                         'cuts_30s': cuts_30, 'luma': round(luma, 1), 'black': luma < BLACK_LUMA,
                         'on_spot': lib_ev, 'known_programme': notad_ev}}
        if incidents:
            result['incidents'] = incidents
        if self.ui:
            result['ui'] = self.ui
        with self._lock:
            self._latest[folder] = result
        dev.last_result = result
        return result

    # ---- persisted break events -----------------------------------------------------------------
    def _restore(self, dev, ts):
        """First sample after a start: read ad_breaks.jsonl, rebuild the KPIs' history from the closed breaks of the last 25 h (spans
        that end in the future of this stream are ignored: a replay must not read its own earlier run; breaks a person marked as not an ad
        are left out), drop lines older than keep_days, note this start."""
        dev.restored = True
        watched, spans = [], []
        path = dev.breaks_path
        if path and os.path.isfile(path):
            try:
                with open(path) as f:
                    records = []
                    for line in f:
                        try:
                            r = json.loads(line)
                        except ValueError:
                            continue                              # a broken line is dropped by the rewrite below
                        if isinstance(r, dict):
                            records.append(r)
                keep_from = ts - self.p['keep_days'] * 86400
                self._prune_thumbs(dev, keep_from)
                kept = [r for r in records if _num(r.get('t', r.get('end'))) is not None and _num(r.get('t', r.get('end'))) >= keep_from]
                if len(kept) != len(records) or sum(1 for _ in open(path)) != len(records):
                    with open(path, 'w') as f:
                        f.writelines(json.dumps(r, separators=(',', ':')) + '\n' for r in kept)
                corrected = {r.get('id') for r in kept if r.get('type') == 'correction' and r.get('not_ad')}
                run_start = last_seen = None                      # watched intervals: from a start marker to the last marker (heartbeat or break end) of that run
                for r in kept:                                    # one bad record is skipped, never the whole restore
                    kind = r.get('type')
                    t = _num(r.get('t'))
                    if kind == 'start' and t is not None:
                        if run_start is not None and last_seen > run_start:
                            watched.append((run_start, min(last_seen, ts)))
                        run_start = last_seen = t if t <= ts else None
                    elif kind == 'alive' and t is not None and run_start is not None and t <= ts:
                        last_seen = max(last_seen, t)
                    elif kind == 'break' and r.get('id') not in corrected and r.get('kind') != 'suspect_overlong' and r.get('id') not in corrected and r.get('kind') != 'suspect_overlong':
                        a_, b_ = _num(r.get('start')), _num(r.get('end'))
                        if a_ is not None and b_ is not None and a_ <= b_ and ts - 90000 <= b_ <= ts:
                            spans.append(('ad_break', a_, b_, {'state': 'ad', 'kind': r.get('kind') if r.get('kind') in ('new', 'confirmed') else 'new'}))
                    if kind == 'break' and run_start is not None:
                        e_ = _num(r.get('end'))
                        if e_ is not None and e_ <= ts:
                            last_seen = max(last_seen, e_)
                if run_start is not None and last_seen > run_start:
                    watched.append((run_start, min(last_seen, ts)))
            except OSError as e:
                logger.warning(f"ad_meter: could not read {path}: {e}")
        dev.events.restore(spans, [(a, b) for a, b in watched if ts - 90000 <= b])
        dev.last_alive = ts
        self._append(dev, {'type': 'start', 't': round(ts, 1), 'device': dev.folder})

    def _append(self, dev, record):
        if not dev.breaks_path:
            return
        try:
            os.makedirs(os.path.dirname(dev.breaks_path), exist_ok=True)
            with open(dev.breaks_path, 'a') as f:
                f.write(json.dumps(record, separators=(',', ':')) + '\n')
        except OSError as e:
            logger.warning(f"ad_meter: break event not saved: {e}")

    def settle(self, folder, ts):
        """End of an offline clip: close the break that is still open (as if the channel went on without evidence)."""
        dev = self._state[folder]
        finalized = []
        if dev.brk is not None:
            finalized = self._close(dev, ts)
        events, kpis, incidents = dev.events.update([], finalized, ts)
        return {'observations': [], 'events': events, 'kpis': kpis, 'incidents': incidents}

    # ---- channel change -------------------------------------------------------------------------
    def _zap_check(self, dev, ts, black):
        """A system-sent action (last_action.json, written for every remote action) followed within zap_window_s by a black sample is a channel
        change: the learned mark belongs to the old channel and an open break ended with it. A zap with the physical remote leaves no trace
        here; those are caught by max_break_s and the automatic relearn."""
        if dev.action_path and ts - dev.action_checked >= 1.0:
            dev.action_checked = ts
            try:
                with open(dev.action_path) as f:
                    stamp = json.load(f).get('timestamp')
                if isinstance(stamp, (int, float)):
                    dev.action_ts = float(stamp)
            except (OSError, ValueError):
                pass
        if not black or dev.action_ts is None or not 0 <= ts - dev.action_ts <= self.p['zap_window_s']:
            return False
        dev.action_ts = None                           # one zap per action
        logger.info(f"ad_meter [{dev.folder}]: channel change after an action, learning the mark again")
        self.reset_mark(dev.folder)
        if dev.brk is not None:
            dev.pending_close = dev.brk['last_ev']
        return True

    def _close_overlong(self, dev, ts):
        """A break that lasts max_break_s is not believed (the channel changed, or the picture just cuts fast without a mark): it is recorded as
        suspect_overlong for the timeline, counted nowhere, never taught to the library, and the mark is learned again."""
        brk, dev.brk = dev.brk, None
        dev.evidence.clear()
        end = brk['last_ev']
        logger.warning(f"ad_meter [{dev.folder}]: a break open for {ts - brk['start']:.0f}s is not believed (suspect_overlong), learning the mark again")
        self._append(dev, {'type': 'break', 'v': 1, 'id': f"{dev.folder}:{int(brk['start'])}", 'device': dev.folder, 'channel': dev.learner.mark_id,
                           'start': round(brk['start'], 1), 'end': round(end, 1), 'duration_s': round(end - brk['start'], 1), 'confidence': 0.0,
                           'confirmed': False, 'kind': 'suspect_overlong', 'opened_by': brk['opened_by'], 'start_snapped': brk['start_snapped'],
                           'thumbs': brk.get('thumbs', [])})
        dev.learner.reset()
        dev.marks.clear()
        dev.quiet_since = None
        return []

    # ---- state machine --------------------------------------------------------------------------
    def _relearn_check(self, dev, ts, smooth, evidence):
        """The mark gone for relearn_after_s without any sign of a break (no cutting) is not an ad: the channel changed."""
        if dev.brk is None and smooth is not None and smooth < self.p['mark_absent'] and not evidence:
            dev.quiet_since = dev.quiet_since if dev.quiet_since is not None else ts
            if ts - dev.quiet_since >= self.p['relearn_after_s']:
                logger.info(f"ad_meter: mark gone for {ts - dev.quiet_since:.0f}s without cuts, learning it again")
                dev.learner.reset()
                dev.marks.clear()
                dev.evidence.clear()
                dev.quiet_since = None
        else:
            dev.quiet_since = None

    def _snap_start(self, dev, start):
        """Where a recognised spot (one the library knows) that touches `start` began. The evidence needs about open_s to build up, a known
        spot is recognised after lib_run samples, so the evidence-based start is late; the start of the recognised run is the better one.
        Pauses up to snap_gap_s inside a run (black frames between spots) do not end it. Returns `start` when no run touches it."""
        p = self.p
        times = [t for t, e in dev.libhist if e and t >= start - p['snap_s']]
        if not times:
            return start
        runs, first, prev = [], times[0], times[0]
        for t in times[1:]:
            if t - prev > p['snap_gap_s']:
                runs.append((first, prev))
                first = t
            prev = t
        runs.append((first, prev))
        lag = (p['lib_run'] - 1) / self.sample_hz               # the flag only rises on the lib_run-th sample of a spot
        for a, b in runs:
            if a <= start + p['snap_gap_s'] and b >= start - p['snap_gap_s']:
                return min(start, a - lag)
        return start

    def _open(self, dev, ts, start, by):
        snapped = start
        if dev.library is not None and self.p['lib_assist']:
            snapped = self._snap_start(dev, start)
        dev.brk = {'id': dev.next_id, 'start': snapped, 'last_ev': ts, 'n': 0, 'n_ev': 0, 'opened_by': by, 'start_snapped': snapped < start - 1.0,
                   'hashes': [(t, x) for t, x, b in dev.hashes if t >= snapped - self.p['head_s'] and not b][:self.p['max_break_hashes']]}
        dev.learner.drop_since(snapped)
        dev.next_id += 1

    def _step(self, dev, ts, evidence, lib_ev=False):
        p = self.p
        dev.evidence.append((ts, evidence))
        keep = max(p['open_s'], p['close_s'])
        while dev.evidence and ts - dev.evidence[0][0] > keep:
            dev.evidence.popleft()
        if dev.brk is None:
            window = [(t, e) for t, e in dev.evidence if ts - t <= p['open_s']]
            span = window[-1][0] - window[0][0] if window else 0.0
            if span >= 0.8 * p['open_s'] and sum(e for _, e in window) / len(window) >= p['open_ratio']:
                self._open(dev, ts, next(t for t, e in window if e), 'mark+cuts' if not lib_ev else 'library')
            elif lib_ev and p['lib_assist']:
                quick = [(t, e) for t, e in dev.libhist if ts - t <= p['lib_open_s']]
                if quick and quick[-1][0] - quick[0][0] >= 0.8 * p['lib_open_s'] and all(e for _, e in quick) and evidence:
                    self._open(dev, ts, quick[0][0], 'library')
            if dev.brk is not None:
                dev.brk['n'] += 1
                dev.brk['n_ev'] += 1 if evidence else 0
            return []
        dev.brk['n'] += 1
        if evidence:
            dev.brk['last_ev'] = ts
            dev.brk['n_ev'] += 1
        if dev.pending_close is not None:               # a zap ended it: close at the last sample of evidence before the channel changed
            end, dev.pending_close = dev.pending_close, None
            return self._close(dev, end)
        if ts - dev.brk['start'] > p['max_break_s']:
            return self._close_overlong(dev, ts)
        window = [(t, e) for t, e in dev.evidence if ts - t <= p['close_s']]
        span = window[-1][0] - window[0][0]
        if span >= 0.8 * p['close_s'] and sum(e for _, e in window) / len(window) < p['close_ratio']:
            return self._close(dev, dev.brk['last_ev'])
        return []

    def _close(self, dev, end):
        brk, dev.brk = dev.brk, None
        dev.evidence.clear()
        if end - brk['start'] < self.p['min_break_s']:
            logger.info(f"ad_meter: dropped a {end - brk['start']:.0f}s candidate break (under {self.p['min_break_s']:.0f}s)")
            self._drop_thumbs(dev, brk)
            return []
        hashes = [h for t, h in brk['hashes'] if t <= end]
        if dev.notad is not None and hashes and dev.notad.match_share(hashes, 1) >= 0.5:
            logger.info(f"ad_meter: dropped a break that is mostly content marked as not an ad ({brk['start']:.0f}-{end:.0f})")
            self._drop_thumbs(dev, brk)
            return []
        kind, share = 'new', 0.0
        if dev.library is not None and hashes:
            share = dev.library.match_share(hashes, 1)             # candidates count: a first repeat is what confirms
            if share >= self.p['confirm_share']:
                kind = 'confirmed'
        duration = end - brk['start']
        ratio = brk['n_ev'] / max(1, brk['n'])
        # confidence 0..1: how steadily the evidence held (50 %), how long the break is against the shortest accepted (30 %, full at 3x),
        # and how much of it the library already knew (20 %)
        confidence = round(min(1.0, 0.5 * ratio + 0.3 * min(1.0, duration / (3 * self.p['min_break_s'])) + 0.2 * share), 2)
        if dev.library is not None and hashes and confidence >= self.p['lib_min_confidence']:
            dev.library.add_break(hashes, end, int(brk['start']))
            dev.library.save()
        rid = f"{dev.folder}:{int(brk['start'])}"
        if hashes:
            dev.break_hashes[rid] = hashes
            for old in list(dev.break_hashes)[:-10]:
                del dev.break_hashes[old]
            self._save_break_hashes(dev)
        self._append(dev, {'type': 'break', 'v': 1, 'id': rid, 'device': dev.folder,
                           'channel': dev.learner.mark_id, 'start': round(brk['start'], 1), 'end': round(end, 1),
                           'duration_s': round(duration, 1), 'confidence': confidence, 'confirmed': kind == 'confirmed', 'kind': kind,
                           'opened_by': brk['opened_by'], 'start_snapped': brk['start_snapped'], 'thumbs': brk.get('thumbs', [])})
        return [{'track_id': brk['id'], 'label': 'ad_break', 'attrs': {'state': 'ad', 'kind': kind}, 'span': (brk['start'], end)}]

    # ---- review: a picture of every break (owner, 2026-10-26) -------------------------------------
    def _thumb(self, dev, frame, ts):
        """One small JPEG at the start of an open break and then every thumb_every_s, in ads/<break folder>/, so a person can see what
        the meter called an ad. The names go into the break's record in ad_breaks.jsonl when it closes."""
        import cv2
        brk = dev.brk
        if not dev.ads_dir or ts - brk.get('thumb_t', -1e18) < self.p['thumb_every_s']:
            return
        brk['thumb_t'] = ts
        sub = brk.setdefault('thumb_dir', f"b{int(ts)}")
        try:
            folder = os.path.join(dev.ads_dir, sub)
            os.makedirs(folder, exist_ok=True)
            w = int(self.p['thumb_width'])
            small = cv2.resize(frame, (w, max(1, int(frame.shape[0] * w / frame.shape[1]))), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                name = f"{int(ts)}.jpg"
                with open(os.path.join(folder, name), 'wb') as f:
                    f.write(buf.tobytes())
                brk.setdefault('thumbs', []).append(f"{sub}/{name}")
        except OSError as e:
            logger.warning(f"ad_meter [{dev.folder}]: break thumbnail not saved: {e}")

    @staticmethod
    def _drop_thumbs(dev, brk):
        if dev.ads_dir and brk.get('thumb_dir'):
            shutil.rmtree(os.path.join(dev.ads_dir, brk['thumb_dir']), ignore_errors=True)

    @staticmethod
    def _prune_thumbs(dev, keep_from):
        """Thumbnail folders older than the kept records go with them."""
        if not dev.ads_dir or not os.path.isdir(dev.ads_dir):
            return
        for name in os.listdir(dev.ads_dir):
            path = os.path.join(dev.ads_dir, name)
            try:
                if name.startswith('b') and os.path.isdir(path) and os.path.getmtime(path) < keep_from:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass

    def _take_requests(self, folder, dev, ts):
        """A person's "not an ad" from the review page: the host writes one file per request into ads/requests/ (the host process cannot
        reach this one's state), this process applies it with mark_not_ad and removes the file. Checked every 5 s."""
        if not dev.ads_dir or ts - dev.requests_checked < 5.0:
            return
        dev.requests_checked = ts
        req_dir = os.path.join(dev.ads_dir, 'requests')
        if not os.path.isdir(req_dir):
            return
        for name in sorted(os.listdir(req_dir)):
            path = os.path.join(req_dir, name)
            try:
                with open(path) as f:
                    break_id = json.load(f).get('break_id')
                found = bool(break_id) and self.mark_not_ad(folder, break_id)
                if break_id and not found:
                    # older than the last 10 breaks: nothing to unlearn, but the person's word still takes it out of the record
                    self._append(dev, {'type': 'correction', 'id': break_id, 'not_ad': True, 't': round(ts, 1), 'learned': False})
                logger.info(f"ad_meter [{folder}]: not-an-ad request for {break_id}: {'applied' if found else 'break not found (only the last 10 can be corrected)'}")
            except (OSError, ValueError) as e:
                logger.warning(f"ad_meter [{folder}]: bad not-an-ad request {name}: {e}")
            try:
                os.remove(path)
            except OSError:
                pass

    # ---- correction: this was not an ad ---------------------------------------------------------
    def _save_break_hashes(self, dev):
        if not dev.hashes_path:
            return
        try:
            os.makedirs(os.path.dirname(dev.hashes_path), exist_ok=True)
            with open(dev.hashes_path, 'w') as f:
                json.dump({k: [format(int(x), '016x') for x in v] for k, v in dev.break_hashes.items()}, f)
        except OSError as e:
            logger.warning(f"ad_meter: break hashes not saved: {e}")

    def mark_not_ad(self, folder, break_id):
        """A person says break `break_id` (the id in ad_breaks.jsonl) was not an ad: its frames become known programme, the library forgets
        them, and the break is marked in ad_breaks.jsonl so a restart does not count it. Only the last 10 breaks can be corrected
        (their hashes are kept). Returns True when it was found."""
        dev = self._state[folder]
        hashes = dev.break_hashes.get(break_id)
        if hashes is None and dev.hashes_path and os.path.isfile(dev.hashes_path):
            try:
                with open(dev.hashes_path) as f:
                    stored = json.load(f)
                dev.break_hashes = {k: [int(x, 16) for x in v] for k, v in stored.items()}
                hashes = dev.break_hashes.get(break_id)
            except (OSError, ValueError):
                hashes = None
        if not hashes:
            return False
        if dev.notad is not None:
            dev.notad.add_break(hashes, dev.last_ts, int(dev.last_ts))
            dev.notad.save()
        if dev.library is not None:
            dev.library.remove_matching(hashes)
            dev.library.save()
        self._append(dev, {'type': 'correction', 'id': break_id, 'not_ad': True, 't': round(dev.last_ts, 1)})
        return True
