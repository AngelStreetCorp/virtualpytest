"""Companion Jev gates (TASK-45 goal 5).

Three Jev calls that decide whether a companion LLM / web call is worth making. Each gate is one
``decisions.decide`` call (parent ``text.decision`` -> Jev profile). A gate only ever SKIPS the
underlying call: a failure (no answer, ``success`` false, exception) keeps today's path. This
module holds the pure state builders, question dicts and answer readers plus the per-gate
thresholds — everything testable without a network call. The host glue is in
``features/companion/backend_host/companion.py``.
"""

from __future__ import annotations

from typing import Dict, Optional


# ----- thresholds (module constants; per task spec) ---------------------------

# Factcheck gate: P(specific) below this skips the web check (claim too vague to search);
# P(repeat) at or above this skips because the claim is already covered by an earlier web check.
FACTCHECK_SPECIFIC_THRESHOLD = 0.5
FACTCHECK_REPEAT_THRESHOLD = 0.7

# Programme facts gate: P(worth_lookup) below this skips the web lookup entirely.
FACTS_WORTH_LOOKUP_THRESHOLD = 0.5

# Digest gate: P(new_content) below this skips the LLM digest call when there is already a
# previous digest. The first digest of a programme is never gated (gate only fires on second+).
DIGEST_NEW_CONTENT_THRESHOLD = 0.3


# ----- gate 1: factcheck (before the web fact check call) -------------------

FACTCHECK_QUESTIONS: Dict[str, dict] = {
    "specific": {
        "type": "noul",
        "instructions": "Is the sentence a concrete, checkable claim?",
        "criteria": {
            "true": "states a concrete fact a web search can confirm or refute: a named person, "
                    "organisation or place plus a number, a date, a record or a specific event",
            "false": "a vague, general or hypothetical statement, with no named entity or no "
                     "verifiable claim",
        },
    },
    "repeat": {
        "type": "noul",
        "instructions": "Does the sentence say the same thing as one of the already-checked claims, in other words?",
        "criteria": {
            "true": "the sentence restates or paraphrases a claim that is already in `checked`; "
                    "the underlying fact is the same even when the wording is different",
            "false": "the sentence makes a new claim not already covered by any item in `checked`",
        },
    },
}


def build_factcheck_state(sentence: str, speaker: Optional[str], programme: Optional[str],
                          topic: Optional[str], checked: list[str]) -> dict:
    """State for the factcheck gate. ``checked`` is the texts of claims already web-checked for
    this programme (last 15), newest last. ``topic`` and ``programme`` may be None."""
    return {
        "sentence": sentence or "",
        "speaker": speaker or "",
        "programme": programme or "",
        "topic": topic or "",
        "checked": list(checked or []),
    }


def factcheck_questions(checked: list[str]) -> Dict[str, dict]:
    """The questions for the factcheck gate. ``repeat`` is only asked when there is at least one
    already-checked claim to compare against; otherwise asking Jev the repeat question would
    force a meaningless yes/no on an empty list."""
    qs = {"specific": FACTCHECK_QUESTIONS["specific"]}
    if checked:
        qs["repeat"] = FACTCHECK_QUESTIONS["repeat"]
    return qs


def read_factcheck_answer(out: dict) -> Optional[dict]:
    """``{ "skip": bool, "reason": "vague"|"repeat"|None }`` from a ``decisions.decide`` answer.

    Returns ``None`` (no skip) when the answer is unusable (call failed, missing answers, value
    out of range, wrong type) — the fail-open contract. Above ``FACTCHECK_SPECIFIC_THRESHOLD``
    and below ``FACTCHECK_REPEAT_THRESHOLD`` returns ``{"skip": False, "reason": None}``.
    """
    if not out or not out.get("success"):
        return None
    answers = out.get("answers") or {}
    specific = answers.get("specific") or {}
    specific_v = _safe_noul(specific)
    if specific_v is None:
        return None  # fail open: missing / wrong type / out-of-range specific -> don't skip
    if specific_v < FACTCHECK_SPECIFIC_THRESHOLD:
        return {"skip": True, "reason": "vague"}
    repeat = answers.get("repeat") or {}
    repeat_v = _safe_noul(repeat)
    # ``repeat`` is only asked when ``checked`` is non-empty; absent means Jev was not asked.
    if repeat_v is not None and repeat_v >= FACTCHECK_REPEAT_THRESHOLD:
        return {"skip": True, "reason": "repeat"}
    return {"skip": False, "reason": None}


# ----- gate 2: programme facts (before the text.web.companion lookup) --------

FACTS_QUESTIONS: Dict[str, dict] = {
    "worth_lookup": {
        "type": "noul",
        "instructions": "Is the entity worth a web lookup for facts?",
        "criteria": {
            "true": "names a specific programme, film, series episode or match that has facts on "
                    "the web (cast, line-ups, synopsis); a named sport fixture with two teams and "
                    "a competition",
            "false": "a headline strap, a news topic, a channel name or a generic slot like "
                     "Weather, News or Teleshopping",
        },
    },
}


def build_facts_state(entity: dict, category: Optional[str], subcategory: Optional[str],
                      channel: Optional[str]) -> dict:
    """State for the facts gate: the entity fields (title, teams...), the category / subcategory
    (sport/soccer, …) and the channel name."""
    return {
        "entity": {k: (v or "") for k, v in (entity or {}).items() if isinstance(v, str)},
        "category": category or "",
        "subcategory": subcategory or "",
        "channel": channel or "",
    }


def read_facts_answer(out: dict) -> bool:
    """``True`` when the gate says SKIP the web lookup. ``False`` means run the lookup.

    Fails open: a missing / failed / unparseable answer runs the lookup (the default today's
    path)."""
    if not out or not out.get("success"):
        return False
    answers = out.get("answers") or {}
    worth = answers.get("worth_lookup") or {}
    v = _safe_noul(worth)
    if v is None:
        return False
    return v < FACTS_WORTH_LOOKUP_THRESHOLD


# ----- gate 3: digest (before text.companion.digest) --------------------------

DIGEST_QUESTIONS: Dict[str, dict] = {
    "new_content": {
        "type": "noul",
        "instructions": "Do the new lines bring something not already in the previous digest?",
        "criteria": {
            "true": "the new lines bring a new story, topic, claim or position not already in "
                    "`previous`",
            "false": "more of the same content already in `previous`, small talk, or noise that "
                     "does not add a new story, topic, claim or position",
        },
    },
}


def build_digest_state(new: str, previous: list[str]) -> dict:
    """State for the digest gate. ``new`` is the speech + on-screen lines newer than the last
    digest (already truncated to ~2000 chars). ``previous`` is the current digest's headlines /
    topic / claims as short strings (max 10)."""
    return {
        "new": new or "",
        "previous": list(previous or []),
    }


def read_digest_answer(out: dict) -> bool:
    """``True`` when the gate says SKIP the LLM digest call. ``False`` means run the LLM.

    Fails open: a missing / failed / unparseable answer runs the digest."""
    if not out or not out.get("success"):
        return False
    answers = out.get("answers") or {}
    new_content = answers.get("new_content") or {}
    v = _safe_noul(new_content)
    if v is None:
        return False
    return v < DIGEST_NEW_CONTENT_THRESHOLD


def digest_previous_strings(digest: Optional[dict], debate: bool, max_items: int = 10) -> list[str]:
    """The flat list of strings the digest gate feeds as ``previous``: headlines for news, the
    topic + claims for debate. Empty list when there is no previous digest (the runner must not
    gate the first digest of a programme)."""
    if not digest:
        return []
    out: list[str] = []
    if debate:
        topic = digest.get("topic")
        if topic:
            out.append(str(topic))
        for c in (digest.get("claims") or [])[:max_items]:
            text = (c or {}).get("text")
            if text:
                out.append(str(text))
    else:
        for s in (digest.get("stories") or [])[:max_items]:
            headline = (s or {}).get("headline")
            if headline:
                out.append(str(headline))
    return out[:max_items]


def digest_new_tokens(lines: list[dict], subs: list[tuple], shown: list[tuple],
                     max_chars: int = 2000) -> str:
    """The new speech + on-screen text since the last digest, oldest first, capped at
    ``max_chars`` characters (one block). Mirrors what the digest prompt's ``timeline`` is built
    from so the gate sees the same input shape."""
    parts: list[str] = []
    for line in lines:
        if line.get("text"):
            parts.append(str(line["text"]))
    for _, text in subs:
        if text:
            parts.append(str(text))
    for _, text in shown:
        if text:
            parts.append(str(text))
    text = " ".join(parts).strip()
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


# ----- helpers ----------------------------------------------------------------

def _safe_noul(answer: dict) -> Optional[float]:
    """The float probability of a noul answer, or ``None`` when the answer is missing, of the
    wrong type or out of [0, 1]. Never raises."""
    if not isinstance(answer, dict):
        return None
    if answer.get("type") != "noul":
        return None
    try:
        v = float(answer.get("noul"))
    except (TypeError, ValueError):
        return None
    if not 0.0 <= v <= 1.0:
        return None
    return v