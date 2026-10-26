"""Generic event bookkeeping keyed by event names a profile declares.

Each declared event `<name>` has device_state keys `<name>_event_start` / `<name>_start_sequence`
and per-frame JSON keys `<name>_event_start` / `<name>_event_duration_ms`.
"""


def start_key(name):
    return f'{name}_event_start'


def start_sequence_key(name):
    return f'{name}_start_sequence'


def duration_key(name):
    return f'{name}_event_duration_ms'


def clear_event_state(device_state, names):
    """Forget any open event (used when the frame counter rewinds after an ffmpeg restart)."""
    for name in names:
        device_state[start_key(name)] = None
        device_state[start_sequence_key(name)] = None


def ordered_union(name_lists):
    """Union of event name lists, first occurrence order kept."""
    seen = []
    for names in name_lists:
        for n in names:
            if n not in seen:
                seen.append(n)
    return seen


# ---- profile events and KPIs (counting-style profiles) -------------------------------------------

from collections import deque  # noqa: E402
from datetime import datetime  # noqa: E402


def _value(observation, attr):
    """Observation attribute named by a manifest: label, track_id, conf, or an analyzer attribute."""
    if attr in ('label', 'track_id', 'conf'):
        return observation.get(attr)
    return (observation.get('attrs') or {}).get(attr)


def matches(spec, observation):
    value = _value(observation, spec.attr)
    if spec.in_ is not None:
        return value in spec.in_
    return value == spec.equals


class ProfileEvents:
    """Events, KPIs and KPI/event incidents of one device for a profile (TASK-90 §4.4).

    An event fires once per track, when the track's verdict is final (`finalized`: it has its votes, or it left the frame):
    the verdict's label and attributes (colour, egg condition, or `unverified`) are tested against the event's
    `{attr, equals|in}`. While a matching track is still in the frame the event is reported as in progress with its start
    and duration. A KPI counts firings of its event in the last `window_s` seconds, optionally grouped by an attribute
    (`group_by`) or as the percentage of verified firings that pass a test (`pct_where`). An event that lasts (an ad
    break) is finalized with a `span` (start, end); `pct_time` is the share of the time actually WATCHED in the window (not the whole window: a restart or an outage is not "watched without ads") that spans cover, `first_in_hour`
    the minutes from the start of the current clock hour to the first span that started in it.
    """

    def __init__(self, events, kpis, incidents=None, tz=None):
        self.events = events
        self.kpis = [k for k in kpis if k.stat is None]    # telemetry statistics are the analyzer's own (analyzers/telemetry.py)
        self.incidents = incidents or {}
        self.tz = tz                                         # tzinfo for "since midnight" and the clock hour; None = the host's local time
        self._fired = {name: deque() for name in events}   # name -> deque[(ts, attrs)]
        self._active = {name: {} for name in events}        # name -> {track_id: start_ts}
        self._samples = {}                                   # kpi name -> items its percentage rests on (pct_where): a first bad egg is 100 %
        self._watched = []                                   # (start, end) intervals this device was watched in earlier runs (restore)
        self._run_start = None                               # when this run first saw the device

    def restore(self, spans, watched):
        """Rebuild after a restart from persisted events: `spans` = [(event name, start, end, attrs)] of closed events, `watched` = [(start, end)]
        intervals earlier runs were watching (from their start and heartbeat markers), so a gap between runs is not counted as watched time."""
        for name, start, end, attrs in spans:
            if name in self._fired:
                self._fired[name].append((end, dict(attrs or {}, span=(start, end))))
        for name in self._fired:
            self._fired[name] = deque(sorted(self._fired[name], key=lambda x: x[0]))
        self._watched = sorted((a, b) for a, b in watched if b > a)

    def observed(self, lo, now):
        """Seconds of [lo, now] this device was watched: the persisted intervals of earlier runs plus this run."""
        total = sum(max(0.0, min(b, now) - max(a, lo)) for a, b in self._watched)
        if self._run_start is not None:
            total += max(0.0, now - max(self._run_start, lo))
        return total

    def midnight(self, now):
        """Start of the local day `now` is in (the host's timezone, or `tz`): DST days are 23 or 25 hours long, that is fine."""
        d = datetime.fromtimestamp(now, self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        return d.timestamp()

    def reset(self):
        """Drop every firing and every track in progress, so the KPIs count from 0 again.

        For a device that plays the SAME clip in a loop the counters would otherwise grow forever and no longer describe
        one pass of the video (a car counted in pass 3 is counted again in pass 4). The pipeline calls this when it sees
        the source jump back to the start. Watched time (`_watched`, `_run_start`) is left alone: the device really was
        watched, and `pct_time` KPIs should still see it.
        """
        for dq in self._fired.values():
            dq.clear()
        for active in self._active.values():
            active.clear()
        self._samples.clear()

    def update(self, observations, finalized, now):
        """observations: dicts (label, track_id, conf, attrs, ...) of the frame; finalized: dicts (track_id, label, attrs)
        of tracks whose verdict was emitted now. Returns (events in progress, kpis, incidents)."""
        if self._run_start is None:
            self._run_start = now
        for name, spec in self.events.items():
            live = {}
            for o in observations:
                if matches(spec, o):
                    tid = o.get('track_id')
                    live[tid] = self._active[name].get(tid, o.get('start', now))   # an observation may carry its own (earlier) start
            self._active[name] = live
            for fin in finalized:
                if matches(spec, fin):
                    self._fired[name].append((now, dict(fin.get('attrs') or {}, label=fin.get('label'), span=fin.get('span'))))
        longest = {}
        for name, tracks in self._active.items():
            if tracks:
                start = min(tracks.values())
                longest[name] = {'start': start, 'duration_ms': int((now - start) * 1000)}
        kpis = {}
        for k in self.kpis:
            # filter, never pop: several KPIs with different windows share one event's firings
            inside = [(ts, attrs) for ts, attrs in self._fired[k.of] if now - ts <= k.window_s]
            if k.pct_time:
                lo = self.midnight(now) if k.since_midnight else now - k.window_s
                observed = self.observed(lo, now)
                covered = sum(max(0.0, min(a['span'][1], now) - max(a['span'][0], lo))
                              for _ts, a in self._fired[k.of] if a.get('span'))
                covered += sum(max(0.0, now - max(start, lo)) for start in self._active[k.of].values())
                kpis[k.name] = round(100.0 * covered / observed, 1) if observed >= 1 else 0.0
            elif k.first_in_hour:
                hour = datetime.fromtimestamp(now, self.tz).replace(minute=0, second=0, microsecond=0).timestamp()
                starts = [a['span'][0] for _ts, a in self._fired[k.of] if a.get('span') and a['span'][0] >= hour]
                starts += [st for st in self._active[k.of].values() if st >= hour]
                kpis[k.name] = round((min(starts) - hour) / 60.0, 1) if starts else None
            elif k.pct_where is not None:
                verified = [a for _ts, a in inside if a.get(k.pct_where.attr) not in (None, 'unverified')]
                self._samples[k.name] = len(verified)
                hit = [a for a in verified if matches(k.pct_where, {'attrs': a, **a})]
                kpis[k.name] = round(100.0 * len(hit) / len(verified), 1) if verified else 0.0
            elif k.group_by is None:
                kpis[k.name] = len(inside)
            else:
                groups = {}
                for _ts, attrs in inside:
                    g = attrs.get(k.group_by)
                    if g is not None:
                        groups[g] = groups.get(g, 0) + 1
                kpis[k.name] = groups
        # old firings no KPI looks at never pile up
        keep_s = max([k.window_s for k in self.kpis] or [0])
        for dq in self._fired.values():
            while dq and now - dq[0][0] > keep_s:
                dq.popleft()
        return longest, kpis, self._incident_state(longest, kpis, now)

    def watched_s(self, now, window_s):
        """How much of the last window_s this device has been watched."""
        return self.observed(now - window_s, now)

    def _incident_state(self, longest, kpis, now):
        """{name: {active, value}} for the profile's incidents, written into the frame JSON; a non-tv_app analyzer hands them to the incident
        manager, which raises the ones the manifest declares as alerts. A KPI incident stays inactive (`warming_up`) until the window has been
        watched for `min_watch_s` (default: half the window) and, for a percentage of items (`pct_where`), until `min_samples` items stand behind
        it (default 10): one bad egg is 100 % bad, and a monitor that just started has watched nothing."""
        out = {}
        for name, inc in self.incidents.items():
            if inc.event is not None:
                ev = longest.get(inc.event)
                out[name] = {'active': bool(ev and ev['duration_ms'] >= inc.after_s * 1000),
                             'value': ev['duration_ms'] / 1000 if ev else 0}
            else:
                value = kpis.get(inc.kpi, 0)
                value = 0 if value is None else value
                value = value if isinstance(value, (int, float)) else sum(value.values())
                need_watch = inc.min_watch_s if inc.min_watch_s is not None else inc.window_s / 2
                spec = next((k for k in self.kpis if k.name == inc.kpi), None)
                need_samples = inc.min_samples if inc.min_samples is not None else (10 if spec is not None and spec.pct_where is not None else 0)
                if self.watched_s(now, inc.window_s) < need_watch or self._samples.get(inc.kpi, need_samples) < need_samples:
                    out[name] = {'active': False, 'value': value, 'warming_up': True}
                    continue
                out[name] = {'active': value > inc.above if inc.above is not None else value < inc.below, 'value': value}
        return out
