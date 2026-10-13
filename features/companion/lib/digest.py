"""Stage 3 tracker ``transcript_window`` — what is being said, as a digest.

Every ``interval_s`` the worker hands the last ``window_s`` of transcript plus the on-screen text
seen meanwhile (lower thirds, headlines, tickers) to a text model (``text.companion.digest``, a
small local model is enough). The live transcript is noisy (Whisper tiny: confidence ~0.04 on
French TV), so the prompt tells the model to trust on-screen text for names and numbers and to
say nothing rather than guess.

Everything the model gets is one timeline, oldest first, each entry stamped with its time: speech,
the channel's subtitles, name captions and straps. A caption naming a person is only tied to what was
said right after it: with two untimed blocks, SRF INFO's digest credited the weather forecast to the
correspondent captioned two minutes later (2026-09-30).

News digest shape: ``{stories: [{headline, summary, people, places, orgs}], sensitive: {flag, reason}}``.
Stories are merged into a rolling list, newest first.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .identify import extract_json

MAX_STORIES = 8
MAX_TRANSCRIPT_CHARS = 6000


# Transcript segments closer than this are one paragraph of the timeline.
SPEECH_GAP_S = 20
ATTRIBUTION_RULE = (
    "A person named by a caption is tied to what is said (a story's people, a speaker) only for the lines\n"
    "within 30 s after their caption and before the next strap or name caption; otherwise leave them out\n"
    "(people) or use null (speaker). A new strap starts a new segment: never merge lines of two segments\n"
    "into one story or claim unless they are clearly about the same subject. A subtitle starting with\n"
    "(Name) names who speaks from that line on."
)
# Who may be credited, checked after the model answered: a claim or a stance is matched to the speech
# line it comes from by shared words, and its speaker kept only if that line came within this many
# seconds after the person's caption (or a "(Name)" subtitle). On SRF INFO's "Club" gpt-4.1-mini
# credited a guest with lines spoken 48 s after his caption, by the presenter.
ATTRIBUTION_S = 30
_SUBTITLE_SPEAKER = re.compile(r"^\(([^()]{2,40})\)")
_WORD = re.compile(r"[^\W_]{4,}|\d+")


def _words(text: str) -> set:
    return {w.lower() for w in _WORD.findall(text or "")}


def _person_key(name: str) -> str:
    """Last name, lowercase: "Jack Straw" and a subtitle's "(Straw)" are the same person."""
    parts = (name or "").split()
    return parts[-1].lower() if parts else ""


def speaker_marks(captioned: dict, subtitles: list[tuple]) -> dict:
    """``{last name: [times]}`` when each person was named: captions (``{name: [t]}``) and subtitles
    that start with "(Name)"."""
    marks: dict = {}
    for name, times in captioned.items():
        marks.setdefault(_person_key(name), []).extend(times)
    for t, text in subtitles:
        m = _SUBTITLE_SPEAKER.match(text.strip())
        if m:
            marks.setdefault(_person_key(m.group(1)), []).append(t)
    return marks


def _source_time(text: str, speech: list[tuple]) -> Optional[float]:
    """Time of the speech line ``text`` was taken from: the line sharing the most words with it (at
    least 2, and at least a third of the line's words). None when it cannot be placed."""
    words = _words(text)
    best, best_t = 0.0, None
    for t, line in speech:
        lw = _words(line)
        shared = len(words & lw)
        if shared >= 2 and lw:
            score = shared / len(lw)
            if score > best:
                best, best_t = score, t
    return best_t if best >= 1 / 3 else None


def check_speakers(items: list[dict], field: str, speech: list[tuple], marks: dict) -> list[dict]:
    """Null every ``speaker`` the timeline does not support (see ATTRIBUTION_S)."""
    out = []
    for item in items:
        who = item.get("speaker")
        if who:
            at = _source_time(item.get(field) or "", speech)
            named = marks.get(_person_key(who), [])
            if at is None or not any(c <= at <= c + ATTRIBUTION_S for c in named):
                item = {**item, "speaker": None}
        out.append(item)
    return out


def timeline(lines: list[dict], shown: list[tuple], subtitles: Optional[list[tuple]] = None) -> str:
    """Speech, subtitles and on-screen text as one list, oldest first: ``[HH:MM:SS] KIND: text``.
    ``lines`` are transcript segments ``{t, text}``; ``shown`` and ``subtitles`` are ``(t, text)``."""
    marks = sorted(t for t, _ in shown)
    paragraphs: list[dict] = []        # speech, cut at a gap or at a caption / strap
    for line in lines:
        last = paragraphs[-1] if paragraphs else None
        if (last and line["t"] - last["end"] <= SPEECH_GAP_S
                and not any(last["end"] < m <= line["t"] for m in marks)):
            last["texts"].append(line["text"])
            last["end"] = line["t"]
        else:
            paragraphs.append({"t": line["t"], "end": line["t"], "texts": [line["text"]]})
    out = [(p["t"], "SPEECH (noisy)", " ".join(p["texts"])) for p in paragraphs]
    out += [(t, "SUBTITLE", text) for t, text in subtitles or []]
    out += [(t, "ON SCREEN", text) for t, text in shown]
    out.sort(key=lambda e: e[0])
    rendered = [f"[{datetime.fromtimestamp(t):%H:%M:%S}] {kind}: {text}" for t, kind, text in out]
    text = "\n".join(rendered)
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = "...\n" + text[-MAX_TRANSCRIPT_CHARS:].split("\n", 1)[-1]
    return text or "(nothing said or shown)"


def build_news_prompt(lines: list[dict], shown: list[tuple], previous: list[dict],
                      language: Optional[str] = None, subtitles: Optional[list[tuple]] = None) -> str:
    known = "\n".join(f"- {s['headline']}" for s in previous[:MAX_STORIES]) or "- (none)"
    answer_in = f"Answer in {language}." if language else "Answer in the language of the programme."
    return (
        "You summarise a live TV news programme for a viewer. Below, oldest first: what was said in the last\n"
        "minutes and what the channel showed. SPEECH is automatic speech recognition (NOISY: words may be\n"
        "wrong or missing); SUBTITLE is the channel's own subtitles and ON SCREEN its captions and straps\n"
        "(both reliable).\n\n"
        f"Timeline:\n{timeline(lines, shown, subtitles)}\n\n"
        f"Stories already listed (reuse the same headline when it is the same story):\n{known}\n\n"
        "Answer ONLY with one JSON object:\n"
        '{"stories": [{"headline": "short headline", "summary": "at most 2 sentences",\n'
        '  "people": [names], "places": [places], "orgs": [organisations]}],\n'
        ' "sensitive": {"flag": true|false, "reason": "why, or null"}}\n'
        "Rules: only the stories covered in THIS window; names and numbers only when on-screen text\n"
        "or a clear transcript passage gives them; a story you cannot summarise without guessing is\n"
        "left out; sensitive = violence, injured or dead people, disturbing images.\n"
        f"{ATTRIBUTION_RULE} {answer_in}"
    )


def _names(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, (str, int)) and str(v).strip()][:6]


def parse_news(content: str) -> Optional[dict]:
    raw = extract_json(content)
    if raw is None:
        return None
    stories = []
    for s in raw.get("stories") or []:
        if not isinstance(s, dict) or not str(s.get("headline") or "").strip():
            continue
        stories.append({
            "headline": str(s["headline"]).strip()[:160],
            "summary": str(s.get("summary") or "").strip()[:400],
            "people": _names(s.get("people")),
            "places": _names(s.get("places")),
            "orgs": _names(s.get("orgs")),
        })
    sensitive = raw.get("sensitive") if isinstance(raw.get("sensitive"), dict) else {}
    return {
        "stories": stories,
        "sensitive": {"flag": bool(sensitive.get("flag")),
                      "reason": (str(sensitive.get("reason")).strip() or None) if sensitive.get("reason") else None},
    }


def _key(headline: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()


def merge_stories(previous: list[dict], new: list[dict], at: float) -> list[dict]:
    """Rolling list, newest first: a story seen again is updated and moves to the top."""
    merged = {_key(s["headline"]): s for s in previous}
    order = [_key(s["headline"]) for s in previous]
    for story in reversed(new):          # inserted at the top: keep the model's order
        key = _key(story["headline"])
        match = next((k for k in order if k and key and (k in key or key in k)), None)
        if match is not None:
            first_seen = merged[match].get("first_seen", at)
            del merged[match]
            order.remove(match)
        else:
            first_seen = at
        merged[key] = {**story, "first_seen": first_seen, "updated": at}
        order.insert(0, key)
    return [merged[k] for k in order][:MAX_STORIES]


# ---------------------------------------------------------------- debate / talk show
MAX_CLAIMS = 10


def build_debate_prompt(lines: list[dict], speakers: list[dict], topics: list[str], previous_claims: list[dict],
                        language: Optional[str] = None, subtitles: Optional[list[tuple]] = None,
                        shown: Optional[list[tuple]] = None) -> str:
    who = "\n".join(f"- {s['name']}{', ' + s['role'] if s.get('role') else ''}" for s in speakers) or "- (unknown)"
    straps = "\n".join(f"- {t}" for t in topics[:6]) or "- (none)"
    known = "\n".join(f"- {c['text']}" for c in previous_claims[:MAX_CLAIMS]) or "- (none)"
    answer_in = f"Answer in {language}." if language else "Answer in the language of the programme."
    return (
        "You follow a live TV debate / talk show for a viewer. Below: the topic straps the channel showed\n"
        "(reliable, newest first), the people its captions named (reliable), then the timeline of the last\n"
        "minutes, oldest first. SPEECH is automatic speech recognition (NOISY: words may be wrong or\n"
        "missing); SUBTITLE is the channel's own subtitles and ON SCREEN its captions and straps.\n\n"
        f"Topic straps:\n{straps}\n\nPeople named on screen:\n{who}\n\n"
        f"Timeline:\n{timeline(lines, shown or [], subtitles)}\n\n"
        f"Claims already listed (do not repeat them):\n{known}\n\n"
        "Answer ONLY with one JSON object:\n"
        '{"topic": "what they are discussing now, one line",\n'
        ' "positions": [{"speaker": "a name from the list, or null", "stance": "one sentence"}],\n'
        ' "claims": [{"text": "a factual statement someone made", "speaker": "name or null", "checkable": true|false}]}\n'
        "Rules: positions and claims only from clear passages, never guessed from noise; checkable = a\n"
        "verifiable fact (number, record, event), not an opinion. Empty lists are fine.\n"
        f"{ATTRIBUTION_RULE} {answer_in}"
    )


def parse_debate(content: str) -> Optional[dict]:
    raw = extract_json(content)
    if raw is None:
        return None

    def speaker(value) -> Optional[str]:
        text = str(value or "").strip()
        return text if text and text.lower() not in ("null", "none", "unknown") else None
    positions = [{"speaker": speaker(p.get("speaker")), "stance": str(p.get("stance") or "").strip()[:240]}
                 for p in raw.get("positions") or [] if isinstance(p, dict) and str(p.get("stance") or "").strip()]
    claims = [{"text": str(c.get("text") or "").strip()[:240], "speaker": speaker(c.get("speaker")),
               "checkable": bool(c.get("checkable"))}
              for c in raw.get("claims") or [] if isinstance(c, dict) and str(c.get("text") or "").strip()]
    topic = str(raw.get("topic") or "").strip()[:200] or None
    return {"topic": topic, "positions": positions[:6], "claims": claims}


def merge_claims(previous: list[dict], new: list[dict], at: float) -> list[dict]:
    """Rolling claim list, newest first, without repeats."""
    seen = {_key(c["text"]) for c in previous}
    fresh = [{**c, "at": at} for c in new if _key(c["text"]) and _key(c["text"]) not in seen]
    return (fresh + previous)[:MAX_CLAIMS]
