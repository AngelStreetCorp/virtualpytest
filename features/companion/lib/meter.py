"""Live-TV companion fact check meter (TASK-45).

Turns the stream of subtitle fragments into scored sentences: a sentence joiner builds whole
sentences from the caption watcher's fragments (one fragment per caption read, not all
contiguous words), and a Jev decision model call per sentence scores five rhetoric questions
and picks the speaker from the people known for the programme. The web fact check only runs for
sentences Jev thinks is a checkable claim (P(factual_claim) >= COMPANION_FACTCHECK_MIN_CLAIM).

Everything here is pure: the meter does no I/O except the known-people file store. The host
glue (``features/companion/backend_host/companion.py``) is the one that calls ``decisions.decide``
and ``self.checks.request``, and the one that wires the meter into ``_compose``.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from collections import deque
from threading import Lock
from typing import Callable, Deque, Dict, Iterable, List, Optional, Tuple

# ----- sentence joining ------------------------------------------------------

# SRF INFO and similar broadcasters prefix a subtitle line with the speaker's name in
# parentheses: "(Jack Straw) The 435 seats...". The name is dropped from the sentence text
# and returned as prefix_speaker so Jev sees it once and the speaker pick can default to it.
_SRF_PREFIX = re.compile(r"^\(([^()]{2,60})\)\s*")
# A sentence boundary: a terminal punctuation mark (the spec includes the ellipsis).
_END_PUNCT = (".", "?", "!", "…")
_FLUSH_AFTER_S = 8.0
# Cap a single sentence so a runaway fragment stream cannot build an unbounded text; the
# caption watcher's subtitles already slide, but a long silence with no punctuation would.
_MAX_SENTENCE_CHARS = 800


_WORDS = re.compile(r"[^\W\d_]{2,}")


class SentenceJoiner:
    """Feed subtitle fragments in ``feed(t, text)``; finished sentences come out of ``drain(now)``.

    A finished sentence is one whose text ends with ``.``, ``?``, ``!``, or 8 s have passed
    since the last fragment. ``flush(now)`` returns the pending sentence when the host wants
    to drain on shutdown. ``t`` is the fragment's time (unix seconds); the sentence's ``t``
    is the first fragment's time, so the host can stamp each scored sentence with when it
    began, not when it ended.
    """

    def __init__(self) -> None:
        self._start: Optional[float] = None
        self._parts: List[str] = []
        self._prefix_speaker: Optional[str] = None
        self._last_at: Optional[float] = None
        # When terminal punctuation is hit, the joined text moves here and _parts clears. The
        # next drain() pops from this queue. Keeps the contract: parts is empty between
        # sentences; the joiner holds a small queue of finished sentences + one being built.
        self._pending: deque = deque()

    @property
    def parts(self) -> List[str]:
        """Read-only view of the joined fragments (used by tests; the joiner never exposes
        mutation so callers can't shortcut the boundary/flush logic)."""
        return list(self._parts)

    def feed(self, t: float, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # A leading "(Name)" on the first fragment of a sentence names the speaker. On a
        # continuation fragment it is not a name — strip just the leading one.
        if not self._parts:
            m = _SRF_PREFIX.match(text)
            if m:
                self._prefix_speaker = m.group(1).strip()
                text = text[m.end():].strip()
                if not text:
                    return
            self._start = t
            self._parts.append(text)
        else:
            self._parts.append(text)
        self._last_at = t
        # Terminal punctuation: the joined sentence ends, queue it. If a sentence was
        # already pending, queue this one too — drain() emits them in order.
        if text.endswith(_END_PUNCT):
            self._pending.append(self._compose_pending())

    def drain(self, now: float) -> List[dict]:
        """Emit any sentence whose buffer is finished (terminal punctuation) or whose last
        fragment was 8+ s ago. ``now`` is the current wall-clock in seconds."""
        out: List[dict] = []
        while self._pending:
            out.append(self._pending.popleft())
        if self._parts and self._last_at is not None and now - self._last_at >= _FLUSH_AFTER_S:
            out.append(self._compose_pending(now))
        # "..." or a lone word is not a sentence worth a decision (the transcript emits both).
        return [s for s in out if len(_WORDS.findall(s["text"])) >= 2]

    def flush(self, now: Optional[float] = None) -> List[dict]:
        """Force-emit the pending sentence (used on programme change / shutdown)."""
        out: List[dict] = []
        while self._pending:
            out.append(self._pending.popleft())
        if self._parts:
            end = now if now is not None else (self._last_at if self._last_at is not None else time.time())
            out.append(self._compose_pending(end))
        return out

    def reset(self) -> None:
        self._start = None
        self._parts = []
        self._prefix_speaker = None
        self._last_at = None
        self._pending = deque()

    def _compose_pending(self, end_at: Optional[float] = None) -> dict:
        text = " ".join(self._parts).strip()
        end = end_at if end_at is not None else (self._last_at if self._last_at is not None else time.time())
        start = self._start if self._start is not None else end
        prefix = self._prefix_speaker
        sentence = {"t": start, "text": text, "prefix_speaker": prefix, "end_at": end}
        # The fragment buffer and the SRF prefix are spent; start fresh on the next feed().
        self._parts = []
        self._start = None
        self._prefix_speaker = None
        return sentence


# ----- questions -------------------------------------------------------------

# The five rhetoric questions for one sentence. Each is a Jev noul: P(true). The criteria
# phrase the two ends so a 0.0 or 1.0 is grounded, not the median of a fuzzy continuum.
QUESTIONS: Dict[str, dict] = {
    "factual_claim": {
        "type": "noul",
        "instructions": "Does this sentence state a checkable fact?",
        "criteria": {
            "true": "the sentence makes a factual statement that can be checked against the public record (a number, a date, a vote, an event, a quotation attributed to someone)",
            "false": "the sentence is an opinion, a prediction, a vague framing, or a statement with no verifiable claim",
        },
    },
    "evasive": {
        "type": "noul",
        "instructions": "Is this sentence evasive?",
        "criteria": {
            "true": "the sentence dodges or deflects the question or topic rather than addressing it (pivoting to a different subject, giving a non-answer, hiding behind a generality)",
            "false": "the sentence engages with the question or topic directly, even when the answer is short or unconvincing",
        },
    },
    "contradicts_self": {
        "type": "noul",
        "instructions": "Does this sentence contradict what the same speaker said earlier in the recent context?",
        "criteria": {
            "true": "the sentence states something materially inconsistent with a previous sentence by the same speaker in the supplied context (a different number, a different stance on the same issue, a denial of what they just said)",
            "false": "no prior sentence by the same speaker covers the same claim, or this sentence is consistent with them",
        },
    },
    "emotional_appeal": {
        "type": "noul",
        "instructions": "Does this sentence argue by emotion rather than by facts?",
        "criteria": {
            "true": "the sentence leans on fear, anger, pity, pride or moral outrage to persuade rather than on verifiable claims and reasoning",
            "false": "the sentence makes its case with facts, reasons or a neutral statement of position",
        },
    },
    "dodged_question": {
        "type": "noul",
        "instructions": "Was a question put to this speaker and does this sentence not answer it?",
        "criteria": {
            "true": "the recent context contains a question directed at the speaker (or at the panel for this speaker to take) and the sentence does not answer it (ignores it, pivots, answers a different one)",
            "false": "no question was pending, or the sentence answers the question that was asked",
        },
    },
}


def build_state(sentence: dict, previous: List[dict], topic: Optional[str], programme: Optional[str],
                channel: Optional[str], recent_captions: List[dict],
                prefix_speaker: Optional[str]) -> dict:
    """The state passed to Jev: the sentence, three sentences of context, the names seen in
    the last 30 s with their age, the topic / programme / channel, and the SRF (Name) prefix
    when the caption watcher saw one."""
    return {
        "sentence": sentence.get("text") or "",
        "previous": [{"text": p.get("text"), "speaker": p.get("speaker")} for p in (previous or [])],
        "topic": topic or "",
        "programme": programme or "",
        "channel": channel or "",
        "recent_captions": recent_captions or [],
        "prefix_speaker": prefix_speaker or "",
    }


def speaker_question(known: List[dict], recent_captions: Optional[List[dict]] = None) -> Optional[dict]:
    """A ``choice`` question, one option per known person plus ``unknown``.

    ``known``: the people of this programme (``KnownPeople.get()`` / the roster: ``name``, ``role``).
    ``recent_captions``: ``[{name, role, age_s}]``, the age of each person's last name caption at the
    time the sentence was said. A person's criterion says when their caption was last shown, because
    a name caption appears when that person starts speaking. With bare roles, Jev put 0.6 on
    "unknown" for a guest's own sentence 7 s after his caption (SRF « Club », replayed 2026-10-05).
    ``None`` when no known people.
    """
    if not known:
        return None
    ages = {c["name"]: c.get("age_s") for c in recent_captions or [] if c.get("name")}
    options: Dict[str, str] = {}
    for person in known:
        role = person.get("role") or "a participant"
        age = ages.get(person["name"])
        if age is not None and age <= 90:
            when = f"their name caption was shown {int(age)} s before this sentence"
        else:
            when = "no name caption for them in the last 90 s"
        options[person["name"]] = f"{role}; {when}"
    options["unknown"] = ("someone else: a voice-over, a clip, or a person with no caption; "
                          "or nothing in the sentence or the captions points to one of the known people")
    return {
        "type": "choice",
        "instructions": ("Who said this sentence? A name caption appears when that person starts speaking, so "
                         "the person captioned shortly before the sentence (under ~60 s) is usually the "
                         "speaker, unless the sentence is a question or a turn handed to someone else (then "
                         "it is the presenter / interviewer)."),
        "criteria": options,
    }


# ----- answer parsing --------------------------------------------------------

# Speaker confidence threshold below which the speaker is treated as unknown: a weak 0.45 on
# Jack Straw should not be shown to the user as "Jack Straw said this". The threshold is
# generous because Jev's choice confidences are usually well below the noul ones.
SPEAKER_THRESHOLD = 0.6


def parse_answers(out: dict) -> dict:
    """Turn a ``decisions.decide`` result into scores and an optional speaker.

    Never raises: a missing question or an answer of the wrong type simply omits that score.
    ``speaker`` is kept only when its probability is >= ``SPEAKER_THRESHOLD`` AND Jev picked
    a name (not ``unknown``); ``speaker_p`` is the probability of the picked option.
    """
    scores: Dict[str, float] = {}
    for name in QUESTIONS:
        ans = ((out or {}).get("answers") or {}).get(name) or {}
        if ans.get("type") != "noul":
            continue
        try:
            v = float(ans.get("noul"))
        except (TypeError, ValueError):
            continue
        if not 0.0 <= v <= 1.0:
            continue
        scores[name] = v
    speaker: Optional[str] = None
    speaker_p: Optional[float] = None
    choice = ((out or {}).get("answers") or {}).get("speaker") or {}
    if choice.get("type") == "choice":
        name = choice.get("choice")
        probs = choice.get("probabilities") or {}
        if isinstance(name, str) and name and name != "unknown" and name in probs:
            try:
                p = float(probs[name])
            except (TypeError, ValueError):
                p = 0.0
            if p >= SPEAKER_THRESHOLD:
                speaker = name
                speaker_p = p
    return {"scores": scores, "speaker": speaker, "speaker_p": speaker_p}


# ----- meter aggregate -------------------------------------------------------

# How many recent sentences to keep; the panel only shows a live, ever-shifting window, but
# Jev averages need at least one or two scored sentences before the index is meaningful.
MAX_SENTENCES = 30
# How many claim texts the factcheck gate remembers ("does this sentence restate one of the
# already-checked claims?"); a programme change swaps in a fresh Meter, so the list resets.
MAX_CHECKED_CLAIMS = 15
# The four questions whose average is the "rhetoric index" shown in the gauge; the factual
# claim score is separate because it is the filter for the web check, not a rhetorical metric.
INDEX_QUESTIONS: Tuple[str, ...] = ("evasive", "emotional_appeal", "contradicts_self", "dodged_question")


class Meter:
    """Per-device: the last ``MAX_SENTENCES`` scored sentences and a per-speaker average.

    ``None`` speakers aggregate under the "unknown" bucket so an unnamed two-shot still gets
    a gauge. ``payload()`` is the JSON for the frontend: sentences newest-first with their
    scores and a ``check`` entry when the web check has a verdict (filled in by the host),
    and per-speaker running averages with a 0-100 index.
    """

    def __init__(self) -> None:
        self._sentences: Deque[dict] = deque(maxlen=MAX_SENTENCES)
        self._by_speaker: Dict[str, List[dict]] = {}
        # Texts sent to the web check, newest last, capped; fed to the factcheck gate.
        self._claims_checked: Deque[str] = deque(maxlen=MAX_CHECKED_CLAIMS)
        self._lock = Lock()

    def add(self, sentence_record: dict) -> None:
        """Stash a scored sentence. The record carries ``text``, ``scores``, ``speaker``,
        ``speaker_p``, ``t``, ``end_at`` and the ``ms`` latency from Jev."""
        with self._lock:
            self._sentences.appendleft(dict(sentence_record))
            speaker = sentence_record.get("speaker") or "unknown"
            self._by_speaker.setdefault(speaker, []).append(sentence_record)

    def record_checked(self, claim: str) -> None:
        """A claim was sent to the web check: keep its text for the factcheck gate."""
        text = (claim or "").strip()
        if not text:
            return
        with self._lock:
            self._claims_checked.append(text)

    def claims_checked(self) -> List[str]:
        """A copy of the texts already sent to the web check (newest last)."""
        with self._lock:
            return list(self._claims_checked)

    def payload(self) -> dict:
        with self._lock:
            sentences = list(self._sentences)
            speakers = {name: list(items) for name, items in self._by_speaker.items()}
        out_sentences = []
        for s in sentences:
            out_sentences.append({
                "text": s.get("text") or "",
                "scores": {k: v for k, v in (s.get("scores") or {}).items() if k in QUESTIONS},
                "speaker": s.get("speaker"),
                "speaker_p": s.get("speaker_p"),
                "t": s.get("t"),
                "end_at": s.get("end_at"),
                "ms": s.get("ms"),
                "check": s.get("check"),
            })
        # Speakers sorted by the number of sentences (the two most frequent get the side panels;
        # the rest fold into a row below the video).
        speaker_list = []
        for name, items in speakers.items():
            avg = _averages(items)
            index = _index(avg)
            speaker_list.append({
                "name": name,
                "n": len(items),
                "avg": avg,
                "index": int(round(100 * index)),
            })
        speaker_list.sort(key=lambda s: (-s["n"], s["name"]))
        return {"sentences": out_sentences, "speakers": speaker_list,
                "last_ms": out_sentences[0]["ms"] if out_sentences else None}


def _averages(items: Iterable[dict]) -> Dict[str, float]:
    totals: Dict[str, float] = {q: 0.0 for q in QUESTIONS}
    counts: Dict[str, int] = {q: 0 for q in QUESTIONS}
    for it in items:
        for q, v in (it.get("scores") or {}).items():
            if q in totals and isinstance(v, (int, float)):
                totals[q] += float(v)
                counts[q] += 1
    return {q: totals[q] / counts[q] if counts[q] else 0.0 for q in QUESTIONS}


def _index(avg: Dict[str, float]) -> float:
    # Mean of the four per-question averages, including zeros: a speaker with no contradictions
    # (avg 0) on a debate should not look the same as one with no signal at all. Empty averages
    # become 0 too, so the panel has a number for every speaker.
    vs = [float(avg.get(k) or 0.0) for k in INDEX_QUESTIONS]
    return sum(vs) / len(vs) if vs else 0.0


# ----- known people file store -----------------------------------------------

_PROGRAMME_ALNUM = re.compile(r"[^a-z0-9]+")


def programme_key(title: Optional[str]) -> str:
    """Lowercase alnum of the programme title: 'L'Équipe du Soir' -> 'lequipedusoir'.

    The host's programme_name or verdict's entity.title is the human title; the file store
    uses this key so a programme is the same across minor spelling differences and accents.
    """
    if not title:
        return ""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return _PROGRAMME_ALNUM.sub("", folded.lower())


class KnownPeople:
    """JSON file store: ``{programme_key: {name: {role, seen, last_seen}}}``.

    Atomic writes (``tmp`` + ``os.replace``) so a partial write cannot leave the file in a
    half-written state when the host crashes. A missing or corrupt file is treated as empty
    and is silently replaced on the next ``add``.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path
        self._lock = Lock()
        self._data: Dict[str, Dict[str, dict]] = {}

    def _load(self) -> None:
        if not self._path or not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json_loads(f.read())
        except (OSError, ValueError):
            return  # corrupt file: drop and rebuild
        if isinstance(raw, dict):
            cleaned = {}
            for prog, people in raw.items():
                if not isinstance(prog, str) or not isinstance(people, dict):
                    continue
                cleaned_prog: Dict[str, dict] = {}
                for name, info in people.items():
                    if not isinstance(name, str) or not isinstance(info, dict):
                        continue
                    cleaned_prog[name] = {
                        "role": info.get("role") if isinstance(info.get("role"), str) else None,
                        "seen": int(info.get("seen") or 0),
                        "last_seen": float(info.get("last_seen") or 0.0),
                    }
                cleaned[prog] = cleaned_prog
            self._data = cleaned

    def _save(self) -> None:
        if not self._path:
            return
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(_json_dumps(self._data))
        os.replace(tmp, self._path)

    def add(self, programme: Optional[str], name: str, role: Optional[str], at: float) -> None:
        if not programme or not name:
            return
        key = programme_key(programme)
        if not key:
            return
        with self._lock:
            if not self._data:
                self._load()
            prog = self._data.setdefault(key, {})
            entry = prog.get(name) or {"role": None, "seen": 0, "last_seen": 0.0}
            entry["role"] = role or entry.get("role")
            entry["seen"] = int(entry.get("seen") or 0) + 1
            entry["last_seen"] = float(at)
            prog[name] = entry
            self._save()

    def get(self, programme: Optional[str]) -> List[dict]:
        if not programme:
            return []
        key = programme_key(programme)
        if not key:
            return []
        with self._lock:
            if not self._data:
                self._load()
            prog = self._data.get(key) or {}
            return [
                {"name": n, "role": info.get("role"), "seen": info.get("seen", 0),
                 "last_seen": info.get("last_seen", 0.0)}
                for n, info in prog.items()
            ]


def json_loads(text: str):
    """Tiny wrapper so the test suite can monkeypatch the JSON library."""
    import json as _json
    return _json.loads(text)


def _json_dumps(obj) -> str:
    import json as _json
    return _json.dumps(obj, ensure_ascii=False, sort_keys=True)


# Default known-people file location: /var/lib/virtualpytest/known_people.json. The
# companion's __init__ overrides per device with the capture folder parent.
KNOWN_PEOPLE_DEFAULT_PATH = "/var/lib/virtualpytest/known_people.json"