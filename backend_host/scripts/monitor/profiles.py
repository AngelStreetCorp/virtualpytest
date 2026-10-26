"""Monitor profile manifest: pydantic models and loader (TASK-90 §4.4).

A profile says which of the three services a device needs and what the img service runs. There is
no expression language: events and incidents use the fixed keys validated here.
"""
import logging
import os
from typing import Any, Dict, List, Literal, Optional

try:
    import yaml
except ImportError:   # deploys do not run pip: a host that has not installed pyyaml yet still runs tv_app
    yaml = None
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.src.lib.utils.monitor_profile import ANALYZER_TYPES, DEFAULT_CAPTION_DELAY_S, DEFAULT_PROFILE, PROFILES_DIR

logger = logging.getLogger('capture_monitor')

class ProfileError(ValueError):
    pass


class Services(BaseModel):
    model_config = ConfigDict(extra='forbid')
    img: bool = True
    audio: bool = False
    subtitle: bool = False
    archiver: bool = True    # TASK-95: host services a profile may switch off; on unless it says so
    kpi: bool = True
    avq: bool = True


class AnalyzerSpec(BaseModel):
    """One analyzer. Keys beyond `type` and `sample_hz` belong to the analyzer and are passed through."""
    model_config = ConfigDict(extra='allow')
    type: str
    sample_hz: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode='after')
    def _known_type(self):
        if self.type not in ANALYZER_TYPES:
            raise ValueError(f"unknown analyzer type {self.type!r}; known: {sorted(ANALYZER_TYPES)}")
        return self


class Track(BaseModel):
    model_config = ConfigDict(extra='forbid')
    algo: Literal['iou', 'ocsort'] = 'iou'
    max_gap_s: float = Field(default=2.0, gt=0)
    min_iou: float = Field(default=0.3, ge=0, le=1)
    # Per-track verdict by voting: attributors (colour, later egg condition) vote at each sample of a track, the majority
    # wins, ONE event is emitted when the track has `votes` votes or leaves the frame; a track that leaves with fewer than
    # `min_votes` is `unverified`. votes: 1 = decide at first sight (no voting).
    votes: int = Field(default=1, ge=1, le=15)
    min_votes: Optional[int] = Field(default=None, ge=1)
    # ocsort only: match a track seen once (no velocity yet) to a detection whose centre is within this many box sizes, for objects
    # that move more than their own size between samples (eggs on a fast belt). 0 = off.
    cold_gate: float = Field(default=0.0, ge=0, le=5)
    # A belt: count an object once, when its centre crosses this vertical line (a fraction of the frame width) in the
    # direction of travel, instead of when its track is confirmed or ends. A track that breaks and restarts on the same
    # object is then still counted once: only the piece that crosses the line counts (BUG-0915). None = off.
    count_line_x: Optional[float] = Field(default=None, gt=0, lt=1)
    count_dir: Literal['right', 'left'] = 'right'

    @model_validator(mode='after')
    def _votes(self):
        if self.min_votes is not None and self.min_votes > self.votes:
            raise ValueError("min_votes cannot exceed votes")
        return self


class ResetCounters(BaseModel):
    """Start the counters again when the SOURCE starts again, not when the device is restarted.

    A `videofile` device plays the same clip in a loop (`-stream_loop -1`), so without this the "eggs inspected" /
    "cars in the last hour" totals grow for ever and describe N passes instead of one. The monitor then drops the tracks
    and the fired events, so the overlay counts ONE pass and you can check the number by hand.

    `every_s` is the plain, deterministic trigger: the clip is that many seconds long, so every that many seconds the
    count starts again at 0. `cut_below` is the other one, for a loop of any length (or a stream that changed under us):
    a 32x18 grey descriptor of consecutive frames is correlated, and a correlation under it means the picture jumped.
    Measured on the cars clip: 0.92 median and 0.868 worst inside one pass, 0.836 across the loop. `for_samples`
    consecutive jumps are needed so one noisy frame cannot zero a counter, and `cooldown_s` keeps a busy scene from
    firing over and over. Neither trigger is set = counters run for ever (the old behaviour).
    """
    model_config = ConfigDict(extra='forbid')
    every_s: Optional[float] = Field(default=None, gt=0)
    cut_below: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    for_samples: int = Field(default=2, ge=1, le=30)
    cooldown_s: float = Field(default=10.0, gt=0)

    @model_validator(mode='after')
    def _a_trigger(self):
        if self.every_s is None and self.cut_below is None:
            raise ValueError('reset_counters needs every_s and/or cut_below')
        return self


class ImgSection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    runtime: Literal['edge', 'remote'] = 'edge'   # remote is reserved, not implemented
    analyzers: List[AnalyzerSpec] = Field(min_length=1)
    track: Optional[Track] = None
    reset_counters: Optional[ResetCounters] = None
    # TASK-157: count frames, JPEG bytes, frame age and drops per device and publish them (img_telemetry.py). tv_app turns it on;
    # IMG_TELEMETRY=false on a host is the kill switch for every profile.
    telemetry: bool = False


class EventSpec(BaseModel):
    """An event is a per-observation test: `{attr, equals}` or `{attr, in}`."""
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    attr: str
    equals: Any = None
    in_: Optional[List[Any]] = Field(default=None, alias='in')

    @model_validator(mode='after')
    def _one_test(self):
        if (self.equals is None) == (self.in_ is None):
            raise ValueError("an event needs exactly one of `equals` or `in`")
        return self


class IncidentSpec(BaseModel):
    """An incident is `{event, after_s}` or `{kpi, above|below, window_s}`."""
    model_config = ConfigDict(extra='forbid')
    event: Optional[str] = None
    after_s: Optional[float] = Field(default=None, ge=0)
    kpi: Optional[str] = None
    above: Optional[float] = None
    below: Optional[float] = None
    window_s: Optional[float] = Field(default=None, gt=0)
    # kpi incidents only: stay inactive until the window has been watched this long (default half of window_s) and, for a percentage of
    # items (pct_where), until this many items stand behind it (default 10), so a fresh start or one bad egg cannot raise an alert
    min_watch_s: Optional[float] = Field(default=None, ge=0)
    min_samples: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode='after')
    def _shape(self):
        if (self.event is None) == (self.kpi is None):
            raise ValueError("an incident needs exactly one of `event` or `kpi`")
        if self.event is not None:
            if self.after_s is None:
                raise ValueError("an event incident needs `after_s`")
            if any(v is not None for v in (self.above, self.below, self.window_s, self.min_watch_s, self.min_samples)):
                raise ValueError("an event incident takes only `event` and `after_s`")
        else:
            if (self.above is None) == (self.below is None):
                raise ValueError("a kpi incident needs exactly one of `above` or `below`")
            if self.window_s is None:
                raise ValueError("a kpi incident needs `window_s`")
            if self.after_s is not None:
                raise ValueError("a kpi incident takes `kpi`, `above`|`below` and `window_s`")
        return self


class KpiStat(BaseModel):
    """A KPI that is a statistic of a telemetry value over the current flight (drone): min battery, max altitude, flight time."""
    model_config = ConfigDict(extra='forbid')
    field: str                                     # a key of the frame JSON's `telemetry` (bat, temp, alt, spd, ft, ...)
    fn: Literal['min', 'max', 'last']


class KpiSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    name: str
    of: Optional[str] = None     # an event name (not with `stat`)
    window_s: Optional[float] = Field(default=None, gt=0)
    # telemetry KPI: the analyzer computes it from the vehicle's telemetry since the last takeoff; takes neither `of` nor `window_s`
    stat: Optional[KpiStat] = None
    group_by: Optional[str] = None
    # percentage of the verified firings in the window whose attribute passes `{attr, equals|in}` (unverified ones are left
    # out): broken_pct = cracked among all verified eggs. Mutually exclusive with group_by.
    pct_where: Optional[EventSpec] = None
    # for events that last (ad_break): the share of the window (in percent) the event was in progress, or the minutes from the
    # start of the current clock hour to the first such event that started in it (null until one has). Exclusive shapes.
    pct_time: bool = False
    first_in_hour: bool = False
    # pct_time only: measure from the start of the local day (host timezone) instead of the last window_s; window_s then only says how
    # long events are kept (at least 25 h, a DST day is 25 hours long)
    since_midnight: bool = False

    @model_validator(mode='after')
    def _one_shape(self):
        if self.stat is not None:
            if self.of is not None or self.window_s is not None or self.group_by or self.pct_where or self.pct_time or self.first_in_hour or self.since_midnight:
                raise ValueError("a stat kpi takes only `name` and `stat`")
            return self
        if self.of is None or self.window_s is None:
            raise ValueError("a kpi needs `of` (an event) and `window_s`, or `stat`")
        shapes = [self.pct_where is not None, self.group_by is not None, self.pct_time, self.first_in_hour]
        if sum(shapes) > 1:
            raise ValueError("a kpi takes one of group_by, pct_where, pct_time or first_in_hour")
        if self.since_midnight and not self.pct_time:
            raise ValueError("since_midnight goes with pct_time")
        if self.since_midnight and self.window_s < 90000:
            raise ValueError("since_midnight needs window_s of at least 90000 (25 h) so a DST day is kept whole")
        return self


class OnIncident(BaseModel):
    model_config = ConfigDict(extra='forbid')
    script: Optional[str] = None  # reserved (room_guard); not acted on in this task


class UiCounter(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str                       # a class of the counters' KPI (a group_by value), e.g. clean, or `unverified`
    colour: Literal['green', 'red', 'amber', 'grey', 'blue', 'purple', 'white', 'black', 'yellow', 'brown']
    label: Optional[str] = None


class UiCounters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kpi: str                       # a group_by KPI: {class: count}
    items: List[UiCounter] = Field(min_length=1)


class UiHeadline(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kpi: str                       # a plain number KPI
    label: str
    unit: Optional[Literal['%', 'min']] = None    # written after the number


class UiStat(BaseModel):
    """One number in the overlay's stat row: `Eggs 253 · Detections 82`.

    `kpi` reads a KPI off the profile. `observations` reads the number of detections in the analysed
    frame instead — a different animal, and the reason this is a flag rather than a magic KPI name:
    it is not a KPI at all, it is the length of the `observations` list in the same frame JSON, and it
    is what says how much of the picture the detector actually covered (a high eggs count with a low
    detections count means eggs are passing uncounted).
    """
    model_config = ConfigDict(extra='forbid')
    label: str
    kpi: Optional[str] = None
    observations: bool = False

    @model_validator(mode='after')
    def _one_source(self):
        if bool(self.kpi) == bool(self.observations):
            raise ValueError("a ui stat needs exactly one of `kpi:` or `observations: true`")
        return self


class UiBox(BaseModel):
    model_config = ConfigDict(extra='forbid')
    shape: Literal['rect', 'ellipse'] = 'rect'
    badge: Literal['none', 'votes'] = 'none'
    colour_by: Literal['none', 'verdict'] = 'none'   # verdict: the counter colour of the class, purple while still voting


class UiFocus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    crop: bool = True
    probs: bool = True
    title: str = 'Last checked'


class UiStateBadge(BaseModel):
    """A badge on the picture while an event is in progress (the frame JSON's `events` has it): the AD sign of ad_meter."""
    model_config = ConfigDict(extra='forbid')
    event: str
    label: str
    colour: Literal['green', 'red', 'amber', 'grey', 'blue', 'purple', 'white', 'black', 'yellow', 'brown'] = 'red'


class UiHudItem(BaseModel):
    """One field of the top-right HUD: a value of the frame JSON's `telemetry` dict, drawn by ProfileOverlay. Hidden while its value is
    null (a GPS row appears when a fix comes)."""
    model_config = ConfigDict(extra='forbid')
    key: str                                         # telemetry key (bat, temp, alt, spd, ft, lat, ...)
    label: str
    format: Literal['number', 'battery', 'duration', 'latlon'] = 'number'   # battery: bars + colour; duration: seconds as m:ss; latlon: `key` is lat, `key2` lon
    key2: Optional[str] = None
    short: Optional[str] = Field(default=None, max_length=4)   # label in the narrow HUD of a small player (default: the first three letters)
    unit: Optional[str] = None
    decimals: int = Field(default=0, ge=0, le=6)
    warn_above: Optional[float] = None               # the value turns red above / below this
    warn_below: Optional[float] = None

    @model_validator(mode='after')
    def _latlon(self):
        if (self.format == 'latlon') != (self.key2 is not None):
            raise ValueError("`key2` goes with format latlon (key = lat, key2 = lon) and only with it")
        return self


class Ui(BaseModel):
    """How the web overlay draws this profile (ProfileOverlay): data, not code. Profiles without `ui` get the generic overlay."""
    model_config = ConfigDict(extra='forbid')
    title: str
    headline: Optional[UiHeadline] = None
    stats: Optional[List[UiStat]] = Field(default=None, min_length=1)
    counters: Optional[UiCounters] = None
    box: UiBox = UiBox()
    focus_panel: Optional[UiFocus] = None
    state_badge: Optional[UiStateBadge] = None
    hud: Optional[List[UiHudItem]] = Field(default=None, min_length=1)


class Captions(BaseModel):
    """TASK-103 caption playback: the device's audio is transcribed (this device only) and played `delay_s` behind live."""
    model_config = ConfigDict(extra='forbid')
    delay_s: float = Field(default=DEFAULT_CAPTION_DELAY_S, ge=60, le=600)
    whisper_model: Literal['tiny', 'base'] = 'tiny'
    language: Optional[str] = Field(default=None, pattern=r'^[a-z]{2,3}$')   # pinned: auto-detection was wrong in 8 % of minutes


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    services: Services = Services()
    stream: Literal['full', 'lean'] = 'full'    # lean = run_ffmpeg.sh writes only the outputs a stream-and-control device needs (TASK-95)
    img: ImgSection
    audio: Optional[Dict[str, Any]] = None      # sections for the audio and subtitle services are filled in
    subtitle: Optional[Dict[str, Any]] = None   # when a profile needs them; tv_app's behaviour is in code
    events: Dict[str, EventSpec] = {}
    incidents: Dict[str, IncidentSpec] = {}
    kpis: List[KpiSpec] = []
    on_incident: Optional[OnIncident] = None
    ui: Optional[Ui] = None
    # draw the telemetry HUD into the video itself (run_ffmpeg.sh): stream, recordings, captures, thumbnails. Opt-in: burned pixels cannot be
    # removed and detectors see them. DEVICE<N>_TELEMETRY_BURN_IN=1/0 overrides this per device.
    burn_in: bool = False
    captions: Optional[Captions] = None

    @model_validator(mode='after')
    def _references(self):
        kpi_names = {k.name for k in self.kpis}
        if self.ui:
            grouped = {k.name for k in self.kpis if k.group_by}
            plain = {k.name for k in self.kpis if not k.group_by}
            if self.ui.headline and self.ui.headline.kpi not in plain:
                raise ValueError(f"ui.headline.kpi {self.ui.headline.kpi!r} must be a plain (not grouped) kpi")
            if self.ui.counters and self.ui.counters.kpi not in grouped:
                raise ValueError(f"ui.counters.kpi {self.ui.counters.kpi!r} must be a group_by kpi")
            for s in (self.ui.stats or []):
                if s.kpi and s.kpi not in plain:
                    raise ValueError(f"ui.stats kpi {s.kpi!r} must be a plain (not grouped) kpi")
            if self.ui.state_badge and self.ui.state_badge.event not in self.events:
                raise ValueError(f"ui.state_badge.event {self.ui.state_badge.event!r} is not a declared event")
        if self.captions is not None and not self.services.audio:
            raise ValueError("captions needs services.audio: true")
        if len(kpi_names) != len(self.kpis):
            raise ValueError("duplicate kpi names")
        stat_names = {k.name for k in self.kpis if k.stat is not None}
        for k in self.kpis:
            if k.of is not None and k.of not in self.events:
                raise ValueError(f"kpi {k.name!r}: `of: {k.of}` is not a declared event")
        for iname, inc in self.incidents.items():
            if inc.event is not None and inc.event not in self.events:
                raise ValueError(f"incident {iname!r}: event {inc.event!r} is not declared")
            if inc.kpi is not None and inc.kpi not in kpi_names:
                raise ValueError(f"incident {iname!r}: kpi {inc.kpi!r} is not declared")
            if inc.kpi in stat_names:
                raise ValueError(f"incident {iname!r}: kpi {inc.kpi!r} is a telemetry statistic; an incident reads an event or a windowed kpi")
        return self


def builtin_tv_app() -> Profile:
    """tv_app without reading its manifest (same content as tv_app.yaml): the fallback when PyYAML is missing."""
    return Profile(name='tv_app', services=Services(img=True, audio=True, subtitle=True),
                   img=ImgSection(analyzers=[AnalyzerSpec(type='tv_app')], telemetry=True))


def load_profile(name: str, profiles_dir: Optional[str] = None) -> Profile:
    """Load and validate <profiles_dir>/<name>.yaml. Raises ProfileError."""
    if yaml is None:
        if name == DEFAULT_PROFILE:
            logger.error("PyYAML is not installed (pip install 'pyyaml>=6'); running the built-in tv_app profile")
            return builtin_tv_app()
        raise ProfileError(f"cannot read profile {name!r}: PyYAML is not installed (pip install 'pyyaml>=6')")
    path = os.path.join(profiles_dir or PROFILES_DIR, f'{name}.yaml')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)
    except OSError as e:
        raise ProfileError(f"cannot read profile {name!r}: {e}")
    except yaml.YAMLError as e:
        raise ProfileError(f"profile {name!r} is not valid YAML: {e}")
    if not isinstance(raw, dict):
        raise ProfileError(f"profile {name!r}: top level must be a mapping")
    try:
        profile = Profile.model_validate(raw)
    except ValidationError as e:
        raise ProfileError(f"profile {name!r} is invalid: {e}")
    if profile.name != name:
        raise ProfileError(f"profile file {name}.yaml declares name {profile.name!r}")
    return profile


def load_profile_or_default(name: str, profiles_dir: Optional[str] = None) -> Profile:
    """The monitor never crashes on a bad manifest: log the error and run tv_app."""
    try:
        return load_profile(name, profiles_dir)
    except ProfileError as e:
        if name == DEFAULT_PROFILE:
            raise
        logger.error("%s; falling back to %s", e, DEFAULT_PROFILE)
        return load_profile(DEFAULT_PROFILE, profiles_dir)
