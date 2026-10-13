"""Live-TV companion pipeline (TASK-05), driven by the vpt-companion service (companion_monitor.py).

Opt-in per device with ``DEVICE{N}_COMPANION=true``. For each enabled device a background
thread runs the companion pipeline on the newest captured frame:

1. identify — a vision call every ``identify_interval_s`` of the programme's profile (else
   ``COMPANION_INTERVAL_S``, default 60 s), or sooner on a zap or when the screen turns from video to a
   UI and back. Skipped on black frames.
2. enrich   — facts about the programme, looked up on the web once per programme (background).
3. track    — ``time_window`` (film, series): elapsed / remaining from the banner's broadcast
   slot. ``transcript_window`` (news): every ``interval_s`` a text model digests the last
   ``window_s`` of live transcript + on-screen text into stories (lib/digest.py). ``scoreboard`` (soccer, rugby, basketball): re-read a crop of the score bug every
   ``interval_s`` (profile) and keep a stabilised score, clock and goals. A fixed cadence, not a
   pixel-change gate: on real stb4 frames a new digit changes ~14 px of the crop, inside the noise
   of the clock and the pitch behind a loosely located bug, so a gate either missed goals or fired
   on every tick. A crop read is small (~1.5 s, a few hundred tokens).

4. fact check — opt-in per device (``DEVICE{N}_COMPANION_FACTCHECK``): each new checkable claim of a
   debate digest gets one web-searched verdict, capped per hour (lib/factcheck.py). With the
   sentence meter on (TASK-45), the meter filters which sentences go to the web check: only
   those with P(factual_claim) >= ``COMPANION_FACTCHECK_MIN_CLAIM`` (default 0.7).

The service writes ``result()`` to ``<metadata>/companion.json`` (shape:
``features/companion/frontend/types.ts``). Everything is best-effort: an AI failure keeps the last
verdict.
"""

import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional

import cv2

from features.companion.lib import captions, digest, enrich, factcheck, identify, meter, timewindow
from features.companion.lib.meter import (KnownPeople, Meter, SentenceJoiner, build_state,
                                           parse_answers, speaker_question)
from features.companion.lib.usages import DIGEST, IDENTIFY, LIVE_READ
from features.companion.lib.usages import METER as METER_USAGE
from features.companion.lib.transcript import device_chunk_path, recent_lines
from features.companion.lib.profiles import PLAYBACK_SCREENS, load_profiles, profile_for
from features.companion.lib.scoreboard import ROI_PROMPT, ScoreStabiliser
from features.companion.lib import gates as companion_gates
from shared.src.lib.utils import cv2_io

logger = logging.getLogger("companion")

_TRUTHY = ("1", "true", "yes", "on")
BANNER_MAX_AGE_S = 4 * 3600
TRIGGER_MIN_GAP_S = 3      # never identify more often than this, even on triggers
VOTE_RECHECK_S = 20
TRANSCRIPT_FALLBACK_S = 60  # no subtitle for this long on a talk programme: the meter reads the transcript
TRANSCRIPT_READ_S = 10      # transcript chunk files read at most this often for the meter        # next identify when a category change waits for its second vote
# Crop margin around the score bug, as a fraction of its size: the identify call locates the bug
# only roughly (stb4: [0,0,337,96] on the 0-1000 grid for a bug at [35,51,317,93]).
ROI_MARGIN = 0.2
ROI_UPSCALE = 2


def _meter_per_hour() -> int:
    """Jev calls per device per hour (COMPANION_METER_PER_HOUR, default 900 = 15/min).

    One call per finished sentence: a debate shows ~10-15 sentences/min at peak; 900 leaves
    headroom and is far below Jev's budget (<$0.05/device-hour at the measured rate).
    """
    try:
        return max(0, int(os.getenv("COMPANION_METER_PER_HOUR", "900")))
    except ValueError:
        return 900


def _factcheck_min_claim() -> float:
    """Minimum P(factual_claim) to send a sentence to the web check (COMPANION_FACTCHECK_MIN_CLAIM)."""
    try:
        return max(0.0, min(1.0, float(os.getenv("COMPANION_FACTCHECK_MIN_CLAIM", "0.7"))))
    except ValueError:
        return 0.7


def _default_decide(team_id: str):
    """The host's Jev call: resolve the meter usage for the team (so the decision is logged)
    and ask. Imported lazily so the test suite can run without ``shared.src.lib.ai`` initialized."""
    from shared.src.lib.ai import decisions, router
    from features.companion.lib.usages import register_usages
    # The host resolves the route itself (decisions.decide), so the feature's usage keys must be in this
    # process's catalogue too: only the server registered them, and every call failed with
    # "Unknown AI usage 'text.decision.companion'" (stb4, 2026-10-04). Registering again is a no-op.
    register_usages()

    def decide(state: dict, questions: dict, refs: Optional[dict], timeout_s: int) -> dict:
        res = router.resolve(METER_USAGE, team_id)
        return decisions.decide(res, state, questions, timeout_s=timeout_s, refs=refs)

    return decide


def _default_gate(team_id: str):
    """The host's Jev gate (TASK-45 goal 5): one usage key for all three gates (factcheck /
    facts / digest), the gate name in refs. Same lazy import + register trick as ``_default_decide``;
    same fail-open contract: a missing answer / failed call returns ``{"success": False}`` and the
    caller keeps today's path."""
    from shared.src.lib.ai import decisions, router
    from features.companion.lib.usages import register_usages, GATE
    register_usages()

    def gate(state: dict, questions: dict, refs: Optional[dict], timeout_s: int) -> dict:
        res = router.resolve(GATE, team_id)
        return decisions.decide(res, state, questions, timeout_s=timeout_s, refs=refs)

    return gate


def _people_path_for(device_id: str) -> str:
    """Known-people file of a device: in its capture folder (cold storage, survives reboots),
    never in the RAM ``hot/`` folder."""
    from shared.src.lib.utils.storage_path_utils import (get_capture_folder_from_device_id,
                                                         get_cold_storage_path)
    return os.path.join(get_cold_storage_path(get_capture_folder_from_device_id(device_id), "companion"),
                        "known_people.json")


def _score_interval(track: dict) -> float:
    """Seconds between score-bug reads: COMPANION_SCORE_INTERVAL_S, else the profile's interval_s.

    The host override exists for slow local models: on the PC's LM Studio (RX 5700 XT, model
    partly on CPU) one image call takes 15-30 s, so the profile's 10 s only builds a queue.
    """
    try:
        override = float(os.getenv("COMPANION_SCORE_INTERVAL_S", "0"))
    except ValueError:
        override = 0.0
    return max(5.0, override) if override > 0 else float(track.get("interval_s", 10))


def _complete_jpeg(path: str) -> bool:
    """True when ``path`` is a whole JPEG (ends with the EOI marker)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() < 1024:
                return False
            f.seek(-2, os.SEEK_END)
            return f.read(2) == b"\xff\xd9"
    except OSError:
        return False


def _checks_per_hour() -> int:
    """Fact checks per device per hour (COMPANION_FACTCHECK_PER_HOUR, default 6): each is a web search."""
    try:
        return max(0, int(os.getenv("COMPANION_FACTCHECK_PER_HOUR", str(factcheck.DEFAULT_PER_HOUR))))
    except ValueError:
        return factcheck.DEFAULT_PER_HOUR


def _call_budget() -> int:
    """Seconds one AI call may take, slot wait and answer each (COMPANION_CALL_TIMEOUT_S, default 30)."""
    try:
        return max(5, int(os.getenv("COMPANION_CALL_TIMEOUT_S", "30")))
    except ValueError:
        return 30


# Back-off after a busy or failed call: 30 s, doubling to 5 min, reset by the next success.
# News and debate are one family: a flip between them on the same channel is noise, not a new programme.
TALK = ("news", "debate")
BACKOFF_START_S = 30
BACKOFF_MAX_S = 300


def _interval(profile=None) -> float:
    """Seconds between identify calls: the current programme's profile (identify_interval_s),
    else COMPANION_INTERVAL_S, else 60. A programme rarely changes within a minute, and zaps and
    motion/screen changes re-identify at once anyway."""
    if profile is not None and profile.identify_interval_s:
        return max(5.0, float(profile.identify_interval_s))
    try:
        return max(5.0, float(os.getenv("COMPANION_INTERVAL_S", "60")))
    except ValueError:
        return 60.0


def _crop(img, bbox, margin: float = 0.0):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = bbox
    mx, my = (x1 - x0) * margin, (y1 - y0) * margin
    left, top = int(max(0.0, x0 - mx) * w), int(max(0.0, y0 - my) * h)
    right, bottom = int(min(1.0, x1 + mx) * w), int(min(1.0, y1 + my) * h)
    if right - left < 4 or bottom - top < 4:
        return None
    return img[top:bottom, left:right]


def _screen_class(motion: Optional[str], previous: Optional[str] = None) -> Optional[str]:
    """What the screen is, coarsely, for the re-identify trigger: ``video`` for live and motion, ``ui``
    for a menu or banner overlay, ``blackscreen`` / ``no_signal`` as is. Any other state (``static``,
    ``unknown``, none) keeps the previous class: those alternate with the definite ones every few
    frames (live <-> static on SRF INFO's camera cuts, ui <-> static on stb4's still menus,
    live <-> unknown on a teleshopping programme), and identify re-ran every ~4 s instead of every 60 s."""
    if motion in ("live", "motion"):
        return "video"
    if motion in ("ui", "blackscreen", "no_signal"):
        return motion
    return previous or "video"


class _DisabledCompanion:
    """Stand-in when the companion cannot start (bad profile, import error): does nothing."""

    def enabled(self, device_id: str) -> bool:
        return False

    def observe(self, device_id: str, frame_path: str, metadata_path: str, analysis: dict) -> None:
        return None

    def result(self, device_id: str) -> Optional[dict]:
        return None


def create_companion(**kwargs):
    """The companion for the service, or a no-op one if it fails to start.

    A broken profile must never crash-loop the service: it logs and idles instead.
    """
    try:
        return MonitorCompanion(**kwargs)
    except Exception as e:
        logger.error(f"[companion] disabled, failed to start: {e}")
        return _DisabledCompanion()


class _Device:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.lock = threading.Lock()
        self.frame: Optional[str] = None
        self.metadata_path: Optional[str] = None
        self.black = False
        self.motion: Optional[str] = None
        # pipeline state (worker thread only)
        self.verdict: Optional[dict] = None
        self.identified_at: Optional[float] = None  # None: never identified
        self.changed_at = 0.0
        self.last_trigger: tuple = ()
        self.error: Optional[str] = None
        self.tracker: Optional[ScoreStabiliser] = None
        self.tracker_key: Optional[str] = None
        # Team codes on the score bug (e.g. SLA/LEN), stable where the identify model's spelling
        # of team names is not; a new pair seen twice in a row means a new match.
        self.codes: Optional[tuple] = None
        self.new_codes: Optional[tuple] = None
        self.roi_read_at: Optional[float] = None
        self.force_identify = False
        # The last real zap (see _zap): its frame name, the mtime it was read at, its banner.
        self.zap_marker: Optional[str] = None
        self.zap_mtime: float = 0.0
        self.zap_banner: Optional[dict] = None
        # Back-off per AI usage when its model is saturated (busy) or failing: {usage: {s, until,
        # reason}}. Per usage, so a busy local digest model never pauses identify / captions
        # served by another model (seen on L'Équipe: the PC timed out and all calls stopped).
        self.backoffs: Dict[str, dict] = {}
        # Per-programme on-screen memory: every lower third seen (the speaker roster) and the
        # recent headlines / tickers, fed to the digest. Reset when the programme changes.
        self.programme_key: Optional[tuple] = None
        self.roster: Dict[str, Optional[str]] = {}
        self.captioned: Dict[str, list] = {}    # {name: [times its caption was read]}, for attribution
        # When the current segment began: a new strap / headline or a new person captioned. Speech
        # from an earlier segment that a digest already covered is not sent again (see _digest).
        self.segment_at: float = 0.0
        self.on_screen_log: list = []          # [(t, text)]
        # transcript_window digest
        self.digest: Optional[dict] = None     # {stories, sensitive, at, lines}
        self.digest_at: Optional[float] = None
        self.digest_seen_t: float = 0.0        # newest transcript line already digested
        self.digest_seen_screen: float = 0.0   # newest on-screen text already digested
        # caption watcher (profiles with a captions block)
        self.caption_at: Optional[float] = None
        self.caption_band = None               # small grey copy of the last band read
        self.topics: list = []                 # strap timeline, newest first
        self.not_names: set = set()            # programme / channel / strap texts: never a speaker
        self.subtitles: list = []              # [(t, text)] the channel's own subtitles: clean speech text
        self.programme_since: float = 0.0      # when this programme started here (reset / zap)
        self.playback_since: float = 0.0       # when the screen last turned to live / VOD playback
        self.channel: Optional[str] = None     # channel name identify read on the banner / logo
        self.channel_vote: Optional[str] = None
        self.category_vote: Optional[str] = None
        self.new_programme = False             # set by identify on a VOD <-> live switch
        self.programme_name: Optional[str] = None   # from a banner naming the programme on air
        # Broadcast slot of the identified film/episode ({start, end} "HH:MM"), for time_window.
        self.window: Optional[dict] = None
        self.window_title: Optional[str] = None
        # Sentence meter (TASK-45): one SentenceJoiner + one Meter per device, on only when
        # fact checking is on (the same DEVICE{N}_COMPANION_FACTCHECK switch — the meter and
        # the web checks ride together). The known-people store is per MonitorCompanion so
        # the file is shared across devices on the same host.
        self.joiner: Optional[SentenceJoiner] = None
        self.meter: Optional[Meter] = None
        self.meter_started: Deque[float] = None       # call starts in the last hour, for the cap
        self.meter_scored: Deque[dict] = None         # last 3 scored sentences (state.previous)
        self.known: Optional[KnownPeople] = None
        self.meter_transcript_read: float = 0.0       # last time the transcript fallback read the chunks
        self.meter_transcript_t: float = 0.0          # newest transcript line fed to the joiner
        self.meter_speech: str = "subtitles"          # what fed the last sentences: subtitles | transcript
        self.result: Optional[dict] = None


class MonitorCompanion:
    def __init__(self, team_id: Optional[str] = None,
                 call_vision: Optional[Callable[..., Dict[str, Any]]] = None,
                 lookup: Optional[enrich.LookupFn] = None,
                 call_text: Optional[Callable[..., Dict[str, Any]]] = None,
                 chunk_path_for: Optional[Callable[[str], Callable[[int, int], str]]] = None,
                 check: Optional[factcheck.LookupFn] = None,
                 decide: Optional[Callable[..., Dict[str, Any]]] = None,
                 gate: Optional[Callable[..., Dict[str, Any]]] = None,
                 people_path: Optional[str] = None):
        if not team_id:
            from shared.src.lib.utils.app_utils import DEFAULT_TEAM_ID
            team_id = DEFAULT_TEAM_ID
        self.team_id = team_id
        if call_vision is None:
            from shared.src.lib.utils.ai_utils import call_vision_ai
            call_vision = call_vision_ai
        self._call_vision = call_vision
        if call_text is None:
            from shared.src.lib.ai import gateway
            call_text = gateway.complete
        self._call_text = call_text
        self._chunk_path_for = chunk_path_for or device_chunk_path
        self._decide = decide or _default_decide(team_id)
        # TASK-45 goal 5: one Jev gate shared across the three call sites (factcheck / facts /
        # digest). Same signature as ``_decide`` (``state, questions, refs, timeout_s -> dict``)
        # so a test can drop in a fake without touching the call sites.
        self._gate = gate or _default_gate(team_id)
        self.facts = enrich.FactCache(lookup or enrich.default_lookup(team_id), gate=self._gate)
        self.checks = factcheck.FactChecker(check or factcheck.default_lookup(team_id), _checks_per_hour())
        self.profiles = load_profiles()
        self._shared_known = KnownPeople(people_path) if people_path else None
        self._enabled: Dict[str, bool] = {}
        self._devices: Dict[str, _Device] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ frame loop side
    def enabled(self, device_id: str) -> bool:
        if device_id not in self._enabled:
            m = re.match(r"device(\d+)$", device_id or "")
            on = bool(m) and os.getenv(f"DEVICE{m.group(1)}_COMPANION", "").strip().lower() in _TRUTHY
            self._enabled[device_id] = on
            if on:
                logger.info(f"[companion] Enabled for {device_id}")
        return self._enabled[device_id]

    def observe(self, device_id: str, frame_path: str, metadata_path: str, analysis: dict) -> None:
        """Record the newest frame + its cheap CV state (one dict write). Starts the worker lazily."""
        if not self.enabled(device_id):
            return
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                dev = self._devices[device_id] = _Device(device_id)
                if self.factcheck_enabled(device_id):
                    dev.joiner = SentenceJoiner()
                    dev.meter = Meter()
                    dev.meter_started = deque(maxlen=_meter_per_hour() * 2 or 1)
                    dev.meter_scored = deque(maxlen=3)
                    try:
                        dev.known = self._shared_known or KnownPeople(_people_path_for(device_id))
                    except Exception as e:
                        logger.info(f"[companion] {device_id} known people store off: {e}")
                        dev.known = KnownPeople(None)
                threading.Thread(target=self._worker, args=(dev,), daemon=True,
                                 name=f"companion-{device_id}").start()
        with dev.lock:
            dev.frame = frame_path
            dev.metadata_path = metadata_path
            dev.black = bool(analysis.get("blackscreen"))
            dev.motion = (analysis.get("motion") or {}).get("state")

    @staticmethod
    def factcheck_enabled(device_id: str) -> bool:
        m = re.match(r"device(\d+)$", device_id or "")
        return bool(m) and os.getenv(f"DEVICE{m.group(1)}_COMPANION_FACTCHECK", "").strip().lower() in _TRUTHY

    def result(self, device_id: str) -> Optional[dict]:
        dev = self._devices.get(device_id)
        return dev.result if dev else None

    # ------------------------------------------------------------------ worker
    def _worker(self, dev: _Device) -> None:
        while True:
            try:
                self.step(dev)
            except Exception as e:
                logger.warning(f"[companion] {dev.device_id} step failed: {e}")
            time.sleep(1.0)

    def step(self, dev: _Device, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        with dev.lock:
            frame, metadata_path, black, motion = dev.frame, dev.metadata_path, dev.black, dev.motion
        # The zap's banner lands seconds after the zap itself (capture's AI read): re-identify with it.
        trigger = (_screen_class(motion, dev.last_trigger[0] if dev.last_trigger else None),
                   self._zap(dev, metadata_path), dev.zap_banner is not None)
        if not frame:
            return
        if not _complete_jpeg(frame):
            # Caught mid-write or already rotated away: skip this tick, not an AI failure (an
            # invalid image once came back from OpenRouter as HTTP 400 and triggered a back-off).
            dev.result = self._compose(dev, now)
            return
        if not black:
            since = None if dev.identified_at is None else now - dev.identified_at
            triggered = bool(dev.last_trigger) and trigger != dev.last_trigger
            # A category change waiting for its second vote is confirmed (or dropped) after VOTE_RECHECK_S,
            # not a full interval later: from a film (120 s) to SRF INFO the card stayed "movie" 2 minutes.
            interval = min(_interval(self._profile(dev.verdict)), VOTE_RECHECK_S) if dev.category_vote \
                else _interval(self._profile(dev.verdict))
            due = since is None or since >= interval or dev.force_identify
            if (due or (triggered and since >= TRIGGER_MIN_GAP_S)) and not self._waiting(dev, IDENTIFY, now):
                dev.last_trigger = trigger
                self._identify(dev, frame, metadata_path, now)
            elif not dev.last_trigger:
                dev.last_trigger = trigger
            self._track(dev, frame, now)
            # Sentence meter (TASK-45): flush finished sentences from the joiner and feed each to
            # one Jev decision call (per skill + hourly cap). The result lands in dev.meter.
            if dev.joiner is not None:
                self._feed_transcript(dev, now)
                self._drain_meter(dev, now)
        dev.result = self._compose(dev, now)

    def _device_model(self, device_id: str) -> Optional[str]:
        m = re.match(r"device(\d+)$", device_id or "")
        return os.getenv(f"DEVICE{m.group(1)}_MODEL") if m else None

    def _feed_transcript(self, dev: _Device, now: float) -> None:
        """No channel subtitles for a minute on a talk programme (news, debate): the live transcript
        feeds the meter instead. Noisier and ~1 min late, but CANAL+ / L'Équipe talk shows carry no
        subtitles at all. Read at most every TRANSCRIPT_READ_S, only speech of this programme."""
        profile = self._profile(dev.verdict)
        if not (profile and profile.captions):
            return
        if dev.subtitles and now - dev.subtitles[-1][0] < TRANSCRIPT_FALLBACK_S:
            return
        if now - dev.meter_transcript_read < TRANSCRIPT_READ_S:
            return
        dev.meter_transcript_read = now
        since = max(dev.meter_transcript_t, dev.programme_since, dev.playback_since)
        try:
            lines = recent_lines(self._chunk_path_for(dev.device_id), 300, datetime.fromtimestamp(now))
        except Exception:
            return
        for line in lines:
            if line["t"] > since:
                dev.joiner.feed(line["t"], line["text"])
                dev.meter_transcript_t = line["t"]
                dev.meter_speech = "transcript"

    def _drain_meter(self, dev: _Device, now: float) -> None:
        """Pick up finished sentences from the joiner, one decide call each (with the per-hour cap).

        Each call runs in a background thread so the worker loop never waits on Jev. The
        callback stores the result in the meter and triggers the web check on factual claims.
        """
        joiner = dev.joiner
        if joiner is None or dev.meter is None:
            return
        try:
            sentences = joiner.drain(now)
        except Exception:
            return
        if not sentences:
            return
        cap = _meter_per_hour()
        started = dev.meter_started
        while started and now - started[0] >= 3600:
            started.popleft()
        programme = dev.programme_name or ((dev.verdict or {}).get("entity") or {}).get("title")
        channel = dev.channel
        topic_str = dev.topics[0]["text"] if dev.topics else None
        known_people = dev.known.get(programme) if (cap and dev.known) else []
        # The doc says known = KnownPeople.get(programme) ∪ current roster; union both.
        current_names = [{"name": n, "role": r, "seen": len(dev.captioned.get(n, [])),
                          "last_seen": (dev.captioned.get(n, []) or [0.0])[-1]}
                         for n, r in dev.roster.items()]
        by_name = {p["name"]: p for p in known_people}
        for p in current_names:
            by_name.setdefault(p["name"], p)
        combined = list(by_name.values())
        for sentence in sentences:
            if len(started) >= cap:
                break
            started.append(now)
            self._score_sentence(dev, sentence, programme, channel, topic_str, combined, now)

    def _score_sentence(self, dev: _Device, sentence: dict, programme: Optional[str],
                         channel: Optional[str], topic: Optional[str],
                         known_people: List[dict], now: float) -> None:
        """One Jev call for ``sentence``: build state, ask, parse, stash in the meter."""
        previous = [{"text": s.get("text"), "speaker": s.get("speaker")}
                    for s in list(dev.meter_scored or [])]
        # Caption ages are taken at the time the sentence was said, not now: a transcript sentence
        # arrives ~1 min late, and a caption shown after it says nothing about who said it.
        said_at = float(sentence.get("t") or now)
        recent = []
        for n, r in dev.roster.items():
            before = [c for c in dev.captioned.get(n, []) if c <= said_at + 5]
            if before:
                recent.append({"name": n, "role": r, "age_s": max(0, int(said_at - before[-1]))})
        state = build_state(sentence, previous, topic, programme, channel, recent,
                            sentence.get("prefix_speaker"))
        questions: Dict[str, dict] = dict(meter.QUESTIONS)
        sq = speaker_question(known_people, recent)
        if sq is not None:
            questions["speaker"] = sq
        refs = {"source": "companion", "speech": dev.meter_speech, "device_id": dev.device_id,
                "channel": channel, "programme": programme, "sentence_t": sentence.get("t")}

        meter_obj = dev.meter   # a programme change swaps dev.meter; a late answer must not land in the new one

        def run() -> None:
            try:
                self._score_and_store(dev, meter_obj, sentence, state, questions, refs, programme, topic, now)
            except Exception as e:
                logger.info(f"[companion] {dev.device_id} meter decide failed: {e}")

        threading.Thread(target=run, daemon=True, name=f"companion-meter-{dev.device_id}").start()

    def _score_and_store(self, dev: _Device, meter_obj: Meter, sentence: dict, state: dict, questions: dict,
                         refs: dict, programme: Optional[str], topic: Optional[str], now: float) -> None:
        out = self._decide(state, questions, refs, 5)
        parsed = parse_answers(out)
        scores = parsed.get("scores") or {}
        if not scores:
            return
        record = {"text": sentence.get("text") or "",
                  "scores": scores,
                  "speaker": parsed.get("speaker"),
                  "speaker_p": parsed.get("speaker_p"),
                  "t": sentence.get("t"),
                  "end_at": sentence.get("end_at"),
                  "ms": int(out.get("ms") or 0)}
        meter_obj.add(record)
        if dev.meter is meter_obj and dev.meter_scored is not None:
            dev.meter_scored.append(record)
        # Web check: only sentences Jev thinks are factual claims, above the threshold.
        p = scores.get("factual_claim")
        if dev.meter is meter_obj and p is not None and p >= _factcheck_min_claim():
            # TASK-45 goal 5: a second Jev call decides whether the web check is worth making
            # (the claim is vague or repeats one already checked this programme). Fail open —
            # any failure runs today's path.
            checked = meter_obj.claims_checked() if meter_obj is not None else []
            gate_state = companion_gates.build_factcheck_state(record["text"], record.get("speaker"),
                                                                programme, topic, checked)
            gate_qs = companion_gates.factcheck_questions(checked)
            gate_refs = {"source": "companion", "gate": "factcheck",
                         "device_id": dev.device_id, "programme": programme,
                         "sentence_t": sentence.get("t")}
            try:
                gate_resp = self._gate(gate_state, gate_qs, gate_refs, 5)
            except Exception as e:
                logger.info(f"[companion] {dev.device_id} gate factcheck error, falling back: {e}")
                gate_resp = {}
            verdict = companion_gates.read_factcheck_answer(gate_resp)
            if verdict is not None and verdict.get("skip"):
                # Record on the FactChecker so the meter row shows it; do not run the web check.
                self.checks.skip(record["text"], verdict.get("reason") or "vague")
                logger.info(f"[companion] {dev.device_id} gate factcheck skipped: {verdict.get('reason')}")
                return
            meter_obj.record_checked(record["text"])
            self.checks.request(dev.device_id, record["text"], record.get("speaker"), programme, now,
                                topic=topic)

    @staticmethod
    def _zap(dev: _Device, metadata_path: Optional[str]) -> Optional[str]:
        """The last real zap on this device: the frame name capture stamped on it (None before any).

        capture rewrites ``last_zapping.json`` on every key press, also with ``status: aborted`` for
        a key that is not a channel change (RIGHT, OK...). Only a real zap counts: an aborted write
        used to reset the programme (roster, digest) and re-identify on every menu key. The zap's
        banner is kept here too, since an aborted write overwrites it in the file."""
        path = os.path.join(metadata_path or "", "last_zapping.json")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return dev.zap_marker
        if mtime == dev.zap_mtime:
            return dev.zap_marker
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return dev.zap_marker   # mid-write: read it next tick
        dev.zap_mtime = mtime
        if data.get("status") == "aborted":
            return dev.zap_marker
        dev.zap_marker = str(data.get("frame_filename") or mtime)
        dev.zap_banner = None
        if str(data.get("banner_status", "")).startswith("detected"):
            keys = ("channel_name", "channel_number", "program_name", "program_start_time", "program_end_time")
            dev.zap_banner = {k: data.get(k) for k in keys if data.get(k)} or None
            if dev.zap_banner:
                dev.zap_banner["_at"] = mtime
        return dev.zap_marker

    @staticmethod
    def _banner(dev: _Device, now: float) -> Optional[dict]:
        """Channel/programme from the last zap banner read on this device, if recent."""
        banner = dev.zap_banner
        if not banner or now - banner["_at"] > BANNER_MAX_AGE_S:
            return None
        return {k: v for k, v in banner.items() if k != "_at"}

    def _identify(self, dev: _Device, frame: str, metadata_path: Optional[str], now: float) -> None:
        dev.identified_at = now
        dev.force_identify = False
        zap_banner = self._banner(dev, now)
        prompt = identify.build_prompt(self.profiles, dev.verdict, zap_banner)
        result = self._call_vision(prompt, frame, IDENTIFY, max_tokens=700, family="content-type",
                                   team_id=self.team_id, device_model=self._device_model(dev.device_id),
                                   timeout_s=_call_budget())
        verdict = identify.parse(result.get("content") or "") if result.get("success") else None
        if verdict is None:
            dev.error = (result.get("error") or "unparseable identify answer")[:200]
            if not result.get("success"):
                self._back_off(dev, now, result, IDENTIFY)
            return
        self._recovered(dev, IDENTIFY)
        dev.error = None
        keys = ("screen", "category", "subcategory", "entity")
        if dev.verdict is None or any(verdict.get(k) != dev.verdict.get(k) for k in keys):
            dev.changed_at = now
        # While a match is tracked, keep the names it was identified with: the model may say
        # "Lille OSC" once and "LIL" (the bug code) or nothing the next time, and on stb4 that reset
        # the score and fired a second fact lookup within 30 s. Only new team codes on the bug
        # (see _track) end the match. A longer spelling of the same teams (LIL -> Lille OSC) is kept.
        if (dev.tracker is not None and dev.verdict and dev.verdict.get("entity")
                and (verdict.get("category"), verdict.get("subcategory"))
                == (dev.verdict.get("category"), dev.verdict.get("subcategory"))):
            kept = dev.verdict["entity"]
            said = verdict.get("entity") or {}
            merged = self._merge_names(kept, said)
            if merged != kept:
                logger.info(f"[companion] {dev.device_id} entity {kept} -> {merged} (fuller names)")
                # Same match, better names: the running score tracker moves to the new key.
                profile = self._profile(verdict)
                if profile and dev.tracker is not None and dev.tracker_key == enrich.entity_key(profile, kept):
                    dev.tracker_key = enrich.entity_key(profile, merged) or dev.tracker_key
            elif said != kept:
                logger.info(f"[companion] {dev.device_id} keeps entity {kept} (model said {said})")
            verdict["entity"] = merged
        self._steady_category(dev, verdict, dev.zap_marker)
        # A same-programme verdict without a bug location keeps the last one: the bug hides
        # during replays and ads, and the tracker handles that as 'paused'.
        if dev.verdict and not verdict.get("scoreboard") and self._same_programme(dev.verdict, verdict):
            verdict["scoreboard"] = dev.verdict.get("scoreboard")
        # Speech from a menu, the home screen or an ad break is not the programme's. capture does not
        # always see a zap (digits + OK is logged "aborted: OK is not a channel-change key"), so on
        # stb4 the first SRF INFO digest summarised the teleshopping heard before it.
        if verdict["screen"] in PLAYBACK_SCREENS and (dev.verdict or {}).get("screen") not in PLAYBACK_SCREENS:
            dev.playback_since = now if dev.verdict is not None else 0.0
        # From VOD to live TV (or back) is another programme even without a recorded zap: on stb4 a VOD
        # film, then BACK + 8, gave an SRF INFO digest of an ad heard before the switch.
        dev.new_programme = self._other_playback(dev.verdict or {}, verdict)
        dev.verdict = verdict
        self._update_window(dev, verdict, zap_banner)
        self._note_on_screen(dev, verdict, now, dev.zap_marker)

    @staticmethod
    def _other_playback(prev: dict, verdict: dict) -> bool:
        """Both verdicts are playback, one VOD and the other live TV."""
        a, b = prev.get("screen"), verdict.get("screen")
        return a in PLAYBACK_SCREENS and b in PLAYBACK_SCREENS and a != b

    @staticmethod
    def _steady_category(dev: _Device, verdict: dict, zap_marker: Optional[str]) -> None:
        """No category flip-flop on one channel. L'Équipe du Soir went news <-> debate <-> sport
        (when it plays a match clip) and read clip straps as the title. Without a zap in between, a
        category change needs two identify calls in a row agreeing; a talk programme keeps its title
        (the banner's programme name when known, else the first title read)."""
        prev = dev.verdict or {}
        same_channel = dev.programme_key is not None and dev.programme_key[0] == zap_marker
        if MonitorCompanion._other_playback(prev, verdict):
            same_channel = False   # VOD <-> live is another programme: no vote needed
        if not (same_channel and prev.get("category") and verdict.get("category")):
            dev.category_vote = None
            return
        if verdict["category"] != prev["category"]:
            if dev.category_vote == verdict["category"]:
                dev.category_vote = None
            else:
                dev.category_vote = verdict["category"]
                verdict["category"], verdict["subcategory"] = prev["category"], prev.get("subcategory")
        else:
            dev.category_vote = None
        if verdict.get("category") not in TALK:
            return
        title = dev.programme_name or (prev.get("entity") or {}).get("title")
        if title:
            new_title = (verdict.get("entity") or {}).get("title")
            if new_title and new_title != title:
                dev.not_names.add(new_title)
            verdict["entity"] = {**(verdict.get("entity") or {}), "title": title}

    @staticmethod
    def _update_window(dev: _Device, verdict: dict, zap_banner: Optional[dict]) -> None:
        """Remember the broadcast slot of the programme on screen, from a banner that names it."""
        title = (verdict.get("entity") or {}).get("title")
        slots = []
        if verdict.get("banner"):
            b = verdict["banner"]
            slots.append((b.get("program_name"), b.get("start_time"), b.get("end_time")))
        if zap_banner:
            slots.append((zap_banner.get("program_name"), zap_banner.get("program_start_time"),
                          zap_banner.get("program_end_time")))
        for name, start, end in slots:
            if start and end and timewindow.same_programme(name, title):
                dev.window, dev.window_title = {"start": start, "end": end}, title
                return
        if title != dev.window_title:
            dev.window, dev.window_title = None, None

    @staticmethod
    def _merge_names(kept: dict, new: dict) -> dict:
        """The kept entity, with each team name replaced by a fuller spelling of the same team when
        the model gives one: the kept name's letters appear in order in the new one (LIL -> Lille OSC,
        BET -> Real Betis). Each side on its own; nothing else changes."""
        def expands(short: str, full: str) -> bool:
            letters = iter(full.lower())
            return len(full) > len(short) > 0 and all(ch in letters for ch in short.lower() if ch.isalnum())
        merged = dict(kept)
        for side in ("home_team", "away_team"):
            if expands(kept.get(side) or "", new.get(side) or ""):
                merged[side] = new[side]
        return merged

    @staticmethod
    def _same_programme(a: dict, b: dict) -> bool:
        return (a.get("category"), a.get("subcategory"), a.get("entity")) == \
               (b.get("category"), b.get("subcategory"), b.get("entity"))

    def _profile(self, verdict: Optional[dict]):
        if not verdict or verdict.get("screen") not in PLAYBACK_SCREENS:
            return None
        return profile_for(verdict.get("category"), verdict.get("subcategory"), self.profiles)

    @staticmethod
    def _note_on_screen(dev: _Device, verdict: dict, now: float, zap_marker: Optional[str] = None) -> None:
        """Remember the lower thirds (roster) and headlines/tickers of the current programme.

        The programme changes on a zap, or when the info bar names a different programme — never
        because identify re-reads the category or title differently (a talk show that plays a match
        clip stays the same programme). Only a banner with its broadcast times is the info bar: on
        L'Équipe the model read the show logo and clip straps as a "banner" whose program_name changed
        every call (QUI SUIS-JE, LE SHOW YAMAL...), and each change wiped the speakers and the digest."""
        banner = verdict.get("banner") or {}
        info_bar = bool(banner.get("start_time") and banner.get("end_time"))
        on_air = banner.get("program_name") if info_bar else None
        new_name = bool(on_air and dev.programme_name and not captions.same_text(on_air, dev.programme_name))
        if dev.programme_key is None or dev.programme_key[0] != zap_marker or new_name or dev.new_programme \
                or MonitorCompanion._new_channel(dev, banner.get("channel_name") if info_bar else None):
            # A change of programme cuts the speech window; the first programme after a start keeps it.
            dev.subtitles, dev.programme_since = [], (now if dev.programme_key is not None else 0.0)
            dev.programme_key, dev.roster, dev.on_screen_log = (zap_marker,), {}, []
            dev.captioned = {}
            dev.segment_at = 0.0
            dev.programme_name = None
            dev.channel, dev.channel_vote = None, None
            dev.not_names = set()
            dev.digest, dev.digest_at, dev.digest_seen_t, dev.digest_seen_screen = None, None, 0.0, 0.0
            dev.caption_at, dev.caption_band, dev.topics = None, None, []
            # Sentence meter (TASK-45): reset on a programme switch so old speakers and sentences
            # don't bleed into the next programme's first read.
            if dev.joiner is not None:
                dev.joiner.reset()
            if dev.meter is not None:
                dev.meter = Meter()   # fresh sentences and fresh checked-claims list
                dev.meter_scored.clear()
        if on_air:
            dev.programme_name = on_air
        # Only the info bar (with broadcast times) names the channel: on BBC Two « Politics Live » the
        # model put the show's strap (« POLITICS LIVE ») in channel_name, two reads in a row passed as a
        # zap, and every such "zap" wiped the meter before the lagging transcript could fill it.
        if info_bar and banner.get("channel_name") and dev.channel_vote is None:   # not while a vote waits
            dev.channel = banner["channel_name"]
        dev.not_names |= {t for t in ((verdict.get("entity") or {}).get("title"), banner.get("channel_name"),
                                      banner.get("program_name"), banner.get("next_program")) if t}
        shown = verdict.get("on_screen") or {}
        if shown.get("headline"):
            dev.not_names.add(shown["headline"])
            MonitorCompanion._add_topic(dev, shown["headline"], now)
        third = shown.get("lower_third")
        texts = []
        not_names = list(dev.not_names) + [t["text"] for t in dev.topics]
        if third and third.get("name") and captions.is_person(third["name"], not_names):
            MonitorCompanion._add_speaker(dev, third["name"], third.get("role"), now)
            texts.append(f"{third['name']}{', ' + third['role'] if third.get('role') else ''} (on screen)")
        texts += [t for t in (shown.get("headline"), shown.get("ticker")) if t]
        recent = {text for _, text in dev.on_screen_log[-10:]}
        dev.on_screen_log += [(now, t) for t in texts if t not in recent]
        dev.on_screen_log = dev.on_screen_log[-60:]

    @staticmethod
    def _new_channel(dev: _Device, channel: Optional[str]) -> bool:
        """Another channel's name on screen, read in two identify calls in a row: a zap capture did not
        record. One read is not enough: the model misreads a logo now and then ("la chaine L'EQUIPE" /
        "L'ÉQUIPE" are the same channel, a name inside the other)."""
        if not channel or not dev.channel:
            return False
        a, b = captions._key(channel), captions._key(dev.channel)
        if not a or not b or a in b or b in a or captions.same_text(channel, dev.channel):
            dev.channel_vote = None
            return False
        if dev.channel_vote and captions.same_text(channel, dev.channel_vote):
            return True
        dev.channel_vote = channel
        return False

    @staticmethod
    def _add_topic(dev: _Device, text: str, now: float) -> None:
        """A strap / headline into the topic timeline; a new one starts a segment."""
        if not any(captions.same_text(t["text"], text) for t in dev.topics):
            dev.segment_at = now
        dev.topics = captions.add_to_timeline(dev.topics, text, now)

    @staticmethod
    def _add_speaker(dev: _Device, name: str, role: Optional[str], now: float) -> None:
        """A captioned person into the roster; a person not seen before starts a segment."""
        if name not in dev.roster:
            dev.segment_at = now
        dev.roster[name] = role or dev.roster.get(name)
        dev.captioned[name] = (dev.captioned.get(name, []) + [now])[-20:]
        # Sentence meter (TASK-45): the known-people store, so Jev can pick this speaker next time.
        # Only with the meter on (DEVICE{N}_COMPANION_FACTCHECK): dev.known is None otherwise.
        if dev.known is not None:
            try:
                dev.known.add(dev.programme_name, name, role, now)
            except Exception as e:
                logger.info(f"[companion] {dev.device_id} known people not saved: {e}")

    def _track(self, dev: _Device, frame: str, now: float) -> None:
        verdict = dev.verdict
        profile = self._profile(verdict)
        if verdict and profile and profile.captions and not self._waiting(dev, LIVE_READ, now):
            self._captions(dev, frame, profile, now)
        if verdict and profile and profile.tracker == "transcript_window":
            if not self._waiting(dev, DIGEST, now):
                self._digest(dev, profile, now)
            return
        if self._waiting(dev, LIVE_READ, now):
            return
        if not verdict or not profile or profile.tracker != "scoreboard":
            return
        key = enrich.entity_key(profile, verdict.get("entity") or {}) or profile.id
        if dev.tracker is None or dev.tracker_key != key:
            entity = verdict.get("entity") or {}
            logger.info(f"[companion] {dev.device_id} tracking {key}")
            dev.tracker = ScoreStabiliser(entity.get("home_team"), entity.get("away_team"),
                                          steps=profile.scoring_steps, clock_up=profile.clock_up)
            dev.tracker_key, dev.roi_read_at, dev.codes, dev.new_codes = key, None, None, None
        tracker = dev.tracker
        track = profile.track or {}
        if dev.roi_read_at is not None and now - dev.roi_read_at < _score_interval(track):
            return
        dev.roi_read_at = now
        board = verdict.get("scoreboard")
        if not board:
            tracker.feed(None, now)
            return
        img = cv2_io.imread(frame)
        if img is None:
            return
        crop = _crop(img, board["bbox"], ROI_MARGIN)
        if crop is None:
            return
        crop = cv2.resize(crop, None, fx=ROI_UPSCALE, fy=ROI_UPSCALE, interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            return
        result = self._call_vision(ROI_PROMPT, buf.tobytes(), LIVE_READ, max_tokens=200,
                                   record=False, team_id=self.team_id,
                                   device_model=self._device_model(dev.device_id), timeout_s=_call_budget())
        if not result.get("success"):
            self._back_off(dev, now, result, LIVE_READ)
            return
        self._recovered(dev, LIVE_READ)
        read = identify.extract_json(result.get("content") or "")
        if read is None:
            return
        codes = (read.get("home_team"), read.get("away_team")) if read.get("visible") else None
        if codes and all(codes):
            if dev.codes is None:
                dev.codes = codes
            elif codes != dev.codes:
                if codes == dev.new_codes:
                    # Seen twice: a different match. Drop the tracker and re-identify now.
                    logger.info(f"[companion] {dev.device_id} bug codes {dev.codes} -> {codes}: new match")
                    dev.tracker = dev.codes = dev.new_codes = None
                    dev.force_identify = True
                    return
                dev.new_codes = codes
                return
            dev.new_codes = None
        tracker.feed(read, now)
        if not read.get("visible"):
            # The bug moved or went away: let the next identify relocate it soon.
            dev.force_identify = dev.identified_at is None or now - dev.identified_at >= TRIGGER_MIN_GAP_S * 2

    def _captions(self, dev: _Device, frame: str, profile, now: float) -> None:
        """Read the lower band for name captions / straps / tickers, unless it has not changed."""
        if dev.caption_at is not None and now - dev.caption_at < float(profile.captions.get("interval_s", 6)):
            return
        dev.caption_at = now
        img = cv2_io.imread(frame)
        if img is None:
            return
        h, w = img.shape[:2]
        band = img[int(captions.BAND[0] * h):int(captions.BAND[1] * h), :]
        small = cv2.resize(cv2.cvtColor(band, cv2.COLOR_BGR2GRAY), (160, 40), interpolation=cv2.INTER_AREA)
        if dev.caption_band is not None and float(cv2.absdiff(small, dev.caption_band).mean()) < captions.UNCHANGED_DIFF:
            return  # same picture down there as at the last read: nothing new to read
        if w > 960:
            band = cv2.resize(band, (960, int(band.shape[0] * 960 / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", band, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return
        result = self._call_vision(captions.CAPTIONS_PROMPT, buf.tobytes(), LIVE_READ, max_tokens=300,
                                   record=False, team_id=self.team_id,
                                   device_model=self._device_model(dev.device_id), timeout_s=_call_budget())
        if not result.get("success"):
            self._back_off(dev, now, result, LIVE_READ)
            return
        self._recovered(dev, LIVE_READ)
        found = captions.parse(result.get("content") or "")
        if found is None:
            return
        dev.caption_band = small
        # Straps first, so a clip title shown as a strap can never enter the speaker list.
        for item in found:
            if item["kind"] in ("strap", "ticker") and item["text"]:
                dev.not_names.add(item["text"])
        not_names = list(dev.not_names) + [t["text"] for t in dev.topics]
        recent = {text for _, text in dev.on_screen_log[-10:]}
        for item in found:
            if item["kind"] == "name" and not (item["name"] and captions.is_person(item["name"], not_names)):
                continue
            if item["kind"] == "name" and item["name"]:
                self._add_speaker(dev, item["name"], item["role"], now)
                text = f"{item['name']}{', ' + item['role'] if item['role'] else ''} (on screen)"
            elif item["kind"] == "strap" and item["text"]:
                self._add_topic(dev, item["text"], now)
                text = item["text"]
            elif item["kind"] == "subtitle" and item["text"]:
                # Speech, not a topic: SRF INFO's subtitles had landed in the topic list.
                if not dev.subtitles or not captions.same_text(dev.subtitles[-1][1], item["text"]):
                    dev.subtitles = (dev.subtitles + [(now, item["text"])])[-120:]
                    # Sentence meter: feed the joiner with the new fragment; finished sentences
                    # are picked up at the next step().
                    if dev.joiner is not None:
                        dev.joiner.feed(now, item["text"])
                        dev.meter_speech = "subtitles"
                continue
            else:
                text = item["text"]
            if text and text not in recent:
                dev.on_screen_log.append((now, text))
                recent.add(text)
        dev.on_screen_log = dev.on_screen_log[-60:]

    def _digest(self, dev: _Device, profile, now: float) -> None:
        """Turn the last minutes of transcript + on-screen text into news stories or a debate digest."""
        track = profile.track or {}
        if dev.digest_at is not None and now - dev.digest_at < float(track.get("interval_s", 120)):
            return
        window_s = int(track.get("window_s", 300))
        lines = recent_lines(self._chunk_path_for(dev.device_id), window_s, datetime.fromtimestamp(now))
        # Only speech from this programme: the transcript lags 60-90 s and the window is minutes, so
        # right after a zap it still holds the previous channel (SRF INFO got a digest of L'Équipe).
        lines = [line for line in lines if line["t"] >= max(dev.programme_since, dev.playback_since)]
        subs = [(t, text) for t, text in dev.subtitles if t >= now - window_s]
        shown = [(t, text) for t, text in dev.on_screen_log if t >= now - window_s]
        newest_line = max(lines[-1]["t"] if lines else 0.0, subs[-1][0] if subs else 0.0)
        # Speech from before the current segment that a digest already covered is not sent again:
        # the weather forecast digested at 15:25 came back at 15:27 next to the caption of the
        # correspondent who followed it, and was credited to her.
        def fresh(t: float) -> bool:
            return t >= dev.segment_at or t > dev.digest_seen_t
        lines = [line for line in lines if fresh(line["t"])]
        subs = [(t, text) for t, text in subs if fresh(t)]
        newest_screen = shown[-1][0] if shown else 0.0
        dev.digest_at = now
        if newest_line <= dev.digest_seen_t and newest_screen <= dev.digest_seen_screen:
            return  # nothing new said or shown since the last digest: no call
        language = os.getenv("COMPANION_LANGUAGE") or None
        debate = track.get("digest", "news") == "debate"
        # TASK-45 goal 5: a Jev gate skips the LLM digest call when the new lines do not bring
        # anything new over the current digest (a 2-min run that would otherwise say the same
        # thing). Only the second+ digest is gated; the first always runs.
        previous = companion_gates.digest_previous_strings(dev.digest, debate) if dev.digest is not None else []
        if previous:
            new_text = companion_gates.digest_new_tokens(lines, subs, shown)
            gate_state = companion_gates.build_digest_state(new_text, previous)
            gate_refs = {"source": "companion", "gate": "digest",
                         "device_id": dev.device_id, "programme": dev.programme_name,
                         "debate": debate}
            try:
                gate_resp = self._gate(gate_state, companion_gates.DIGEST_QUESTIONS, gate_refs, 5)
            except Exception as e:
                logger.info(f"[companion] {dev.device_id} gate digest error, falling back: {e}")
                gate_resp = {}
            if companion_gates.read_digest_answer(gate_resp):
                # Keep dev.digest as is, but advance the seen pointers so the next tick does not
                # re-send the same window.
                dev.digest_seen_t = newest_line
                dev.digest_seen_screen = newest_screen
                logger.info(f"[companion] {dev.device_id} gate digest skipped: nothing new")
                return
        if debate:
            previous = (dev.digest or {}).get("claims") or []
            speakers = [{"name": n, "role": r} for n, r in dev.roster.items()]
            prompt = digest.build_debate_prompt(lines, speakers, [t["text"] for t in dev.topics], previous, language,
                                                subs, shown)
        else:
            previous = (dev.digest or {}).get("stories") or []
            prompt = digest.build_news_prompt(lines, shown, previous, language, subs)
        result = self._call_text(DIGEST, prompt, max_tokens=900, temperature=0.0, team_id=self.team_id,
                                 timeout_s=_call_budget())
        if not result.get("success"):
            self._back_off(dev, now, result, DIGEST)
            return
        self._recovered(dev, DIGEST)
        parsed = (digest.parse_debate if debate else digest.parse_news)(result.get("content") or "")
        if parsed is None:
            return
        if debate:
            speech = [(line["t"], line["text"]) for line in lines] + subs
            marks = digest.speaker_marks(dev.captioned, subs)
            parsed["claims"] = digest.check_speakers(parsed["claims"], "text", speech, marks)
            parsed["positions"] = digest.check_speakers(parsed["positions"], "stance", speech, marks)
        dev.digest_seen_t, dev.digest_seen_screen = newest_line, newest_screen
        base = {"at": now, "window_min": window_s // 60, "lines": len(lines)}
        if debate:
            dev.digest = {**base, "topic": parsed["topic"], "positions": parsed["positions"],
                          "claims": digest.merge_claims(previous, parsed["claims"], now)}
            # Task-45: with the meter on (same DEVICE{N}_COMPANION_FACTCHECK switch), the
            # sentence meter is the only path that triggers the web check, so the digest's
            # checkable claims are no longer sent here.
        else:
            dev.digest = {**base, "stories": digest.merge_stories(previous, parsed["stories"], now),
                          "sensitive": parsed["sensitive"]}

    @staticmethod
    def _back_off(dev: _Device, now: float, result: dict, usage: str) -> None:
        """Stop calling this usage's model for a while: it is saturated (busy) or failing."""
        prev = dev.backoffs.get(usage, {}).get("s", 0)
        wait = min(BACKOFF_MAX_S, prev * 2 if prev else BACKOFF_START_S)
        reason = "busy" if result.get("busy") else "error"
        dev.backoffs[usage] = {"s": wait, "until": now + wait, "reason": reason}
        logger.info(f"[companion] {dev.device_id} {usage} {reason}, retry in {wait}s: "
                    f"{(result.get('error') or '')[:160]}")

    @staticmethod
    def _recovered(dev: _Device, usage: str) -> None:
        dev.backoffs.pop(usage, None)

    @staticmethod
    def _waiting(dev: _Device, usage: str, now: float) -> bool:
        entry = dev.backoffs.get(usage)
        return bool(entry) and now < entry["until"]

    def _compose(self, dev: _Device, now: float) -> Optional[dict]:
        verdict = dev.verdict
        waiting = None
        active = [(u, e) for u, e in dev.backoffs.items() if now < e["until"]]
        if active:
            usage, entry = max(active, key=lambda ue: ue[1]["until"])
            waiting = {"reason": entry["reason"], "retry_in_s": int(entry["until"] - now), "usage": usage}
        if verdict is None:
            if not dev.error:
                return None
            return {"error": dev.error, "ts": dev.identified_at, **({"backoff": waiting} if waiting else {})}
        profile = self._profile(verdict)
        out = {
            "screen": verdict["screen"],
            "category": verdict.get("category"),
            "subcategory": verdict.get("subcategory"),
            "entity": verdict.get("entity") or {},
            "banner": verdict.get("banner"),
            "confidence": verdict.get("confidence"),
            "profile": profile.id if profile else None,
            "template": profile.render if profile else "label",
            "ts": dev.identified_at,
            "changed_at": dev.changed_at,
        }
        if dev.error:
            out["error"] = dev.error
        if waiting:
            out["backoff"] = waiting
        if profile and profile.facts:
            key = enrich.entity_key(profile, out["entity"])
            if key:
                out["facts"] = enrich.facts_payload(self.facts.get(key, profile, out["entity"],
                                                                  category=out.get("category"),
                                                                  subcategory=out.get("subcategory"),
                                                                  channel=dev.channel,
                                                                  device_id=dev.device_id))
        if profile and profile.tracker == "scoreboard" and dev.tracker is not None and dev.tracker.score is not None:
            fixture = dev.tracker.fixture(dev.tracker_key or profile.id,
                                          league=(out.get("facts") or {}).get("facts", {}).get("competition") or
                                          out["entity"].get("competition") or "", now=now)
            out["live"] = fixture
        elif verdict["screen"] == "advertisement" and dev.tracker is not None and dev.tracker.score is not None:
            # Keep the last score visible (greyed) through the ad break.
            out["live"] = {**dev.tracker.fixture(dev.tracker_key or "", now=now), "status": "paused"}
        if verdict.get("on_screen"):
            out["on_screen"] = verdict["on_screen"]
        if dev.roster:
            out["roster"] = [{"name": n, "role": r} for n, r in dev.roster.items()]
        if dev.topics:
            out["topics"] = dev.topics
        if profile and profile.tracker == "transcript_window" and dev.digest:
            out["digest"] = dev.digest
        if dev.meter is not None:
            payload = dev.meter.payload()
            # Each sentence carries its fact-check verdict when one is ready.
            sentences = payload.get("sentences") or []
            for sent in sentences:
                checked = self.checks.get(sent.get("text") or "")
                if checked:
                    sent["check"] = checked
            payload["sentences"] = sentences
            out["meter"] = payload
        if profile and profile.tracker == "time_window" and dev.window:
            progress = timewindow.progress(dev.window["start"], dev.window["end"],
                                           datetime.fromtimestamp(now))
            if progress:
                out["progress"] = progress
        return out
