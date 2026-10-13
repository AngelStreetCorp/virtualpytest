"""Companion Jev gates (TASK-45 goal 5): pure state / question / answer readers + thresholds.

Pure tests: no network, no DB. The module under test is ``features.companion.lib.gates``.
"""

import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from features.companion.lib import gates  # noqa: E402


# ----- gate 1: factcheck ---------------------------------------------------

def test_factcheck_state_includes_known_texts_and_normalises_empty():
    state = gates.build_factcheck_state("Claim X", "Jack Straw", "Tagesschau", "Midterms",
                                         ["claim A", "claim B"])
    assert state["sentence"] == "Claim X"
    assert state["speaker"] == "Jack Straw"
    assert state["programme"] == "Tagesschau"
    assert state["topic"] == "Midterms"
    assert state["checked"] == ["claim A", "claim B"]
    # None / missing fields become empty strings so Jev always sees the same shape.
    state2 = gates.build_factcheck_state("Claim Y", None, None, None, None)
    assert state2 == {"sentence": "Claim Y", "speaker": "", "programme": "", "topic": "", "checked": []}


def test_factcheck_questions_drop_repeat_when_nothing_was_checked_yet():
    """No prior claims to compare against: asking ``repeat`` would force a meaningless yes/no,
    so the question is omitted entirely."""
    qs = gates.factcheck_questions([])
    assert "specific" in qs and "repeat" not in qs
    qs = gates.factcheck_questions(["previous claim"])
    assert "specific" in qs and "repeat" in qs


def test_factcheck_answer_threshold_edges():
    """P(specific) below 0.5 skips (vague); at/above lets the claim in. P(repeat) at/above 0.7
    skips; below lets the claim in."""
    base = {"type": "noul"}
    # Vague: P(specific)=0.49 -> skip vague.
    out = {"success": True,
           "answers": {"specific": {**base, "noul": 0.49},
                       "repeat": {**base, "noul": 0.1}}}
    assert gates.read_factcheck_answer(out) == {"skip": True, "reason": "vague"}
    # Specific (0.50), not repeat (0.69) -> do not skip.
    out["answers"]["specific"]["noul"] = 0.50
    out["answers"]["repeat"]["noul"] = 0.69
    assert gates.read_factcheck_answer(out) == {"skip": False, "reason": None}
    # Specific (0.80), repeat (0.70) -> skip repeat.
    out["answers"]["specific"]["noul"] = 0.80
    out["answers"]["repeat"]["noul"] = 0.70
    assert gates.read_factcheck_answer(out) == {"skip": True, "reason": "repeat"}


def test_factcheck_answer_missing_specific_or_repeat_still_does_not_skip():
    """``repeat`` is only asked when ``checked`` is non-empty; the absence of the answer is
    not a skip. A specific answer of 0.5 lets the claim in either way."""
    base = {"type": "noul"}
    out = {"success": True, "answers": {"specific": {**base, "noul": 0.5}}}
    assert gates.read_factcheck_answer(out) == {"skip": False, "reason": None}


def test_factcheck_answer_fail_open():
    """Failed call, missing answers, wrong type, out-of-range: never skip — fall through to
    today's path (the web check)."""
    assert gates.read_factcheck_answer(None) is None
    assert gates.read_factcheck_answer({}) is None
    assert gates.read_factcheck_answer({"success": False, "answers": {}}) is None
    # Wrong type / out of range answers: skip is None (don't skip).
    out = {"success": True, "answers": {"specific": {"type": "score", "noul": 0.9}}}
    assert gates.read_factcheck_answer(out) is None
    out = {"success": True, "answers": {"specific": {"type": "noul", "noul": 1.5}}}
    assert gates.read_factcheck_answer(out) is None
    out = {"success": True, "answers": {"specific": {"type": "noul", "noul": -0.1}}}
    assert gates.read_factcheck_answer(out) is None


# ----- gate 2: programme facts ---------------------------------------------

def test_facts_state_keeps_string_entity_fields_only():
    state = gates.build_facts_state({"title": "L'Équipe du Soir", "home_team": "LIL", "n": 7},
                                     "sport", "soccer", "Foot+")
    assert state["entity"] == {"title": "L'Équipe du Soir", "home_team": "LIL"}
    assert state["category"] == "sport" and state["subcategory"] == "soccer" and state["channel"] == "Foot+"
    state2 = gates.build_facts_state(None, None, None, None)
    assert state2 == {"entity": {}, "category": "", "subcategory": "", "channel": ""}


def test_facts_answer_threshold_edge():
    """P(worth_lookup) below 0.5 -> skip; at/above -> run the lookup."""
    good = {"success": True, "answers": {"worth_lookup": {"type": "noul", "noul": 0.5}}}
    assert gates.read_facts_answer(good) is False       # at threshold: run
    good["answers"]["worth_lookup"]["noul"] = 0.49
    assert gates.read_facts_answer(good) is True        # just below: skip
    good["answers"]["worth_lookup"]["noul"] = 0.9
    assert gates.read_facts_answer(good) is False


def test_facts_answer_fail_open():
    """Failed call / missing answer: never skip — run the lookup (today's path)."""
    assert gates.read_facts_answer(None) is False
    assert gates.read_facts_answer({"success": False, "answers": {}}) is False
    # Wrong type / out-of-range: run.
    assert gates.read_facts_answer({"success": True, "answers": {"worth_lookup": {"type": "score"}}}) is False
    assert gates.read_facts_answer({"success": True, "answers": {"worth_lookup": {"type": "noul", "noul": 2.0}}}) is False


# ----- gate 3: digest ------------------------------------------------------

def test_digest_new_tokens_truncates_to_max():
    """``digest_new_tokens`` (the helper that builds the gate's ``new`` field) caps the joined
    text so a long window never blows the Jev state budget."""
    long_lines = [{"text": "x"} for _ in range(10)]
    text = gates.digest_new_tokens(long_lines, [(0, "y"), (0, "y")], [(0, "z")], max_chars=20)
    assert len(text) <= 20
    # And the state itself just passes the truncated text through.
    state = gates.build_digest_state(text, ["a", "b"])
    assert state["new"] == text and state["previous"] == ["a", "b"]


def test_digest_previous_strings_news_and_debate_shapes():
    news = {"stories": [{"headline": "Story A"}, {"headline": "Story B"}]}
    assert gates.digest_previous_strings(news, debate=False) == ["Story A", "Story B"]
    debate = {"topic": "Midterms", "claims": [{"text": "Claim 1"}, {"text": "Claim 2"}]}
    assert gates.digest_previous_strings(debate, debate=True) == ["Midterms", "Claim 1", "Claim 2"]
    assert gates.digest_previous_strings(None, debate=True) == []
    assert gates.digest_previous_strings(None, debate=False) == []


def test_digest_answer_threshold_edges():
    """P(new_content) below 0.3 -> skip; at/above -> run."""
    base = {"type": "noul"}
    out = {"success": True, "answers": {"new_content": {**base, "noul": 0.29}}}
    assert gates.read_digest_answer(out) is True        # below: skip
    out["answers"]["new_content"]["noul"] = 0.30
    assert gates.read_digest_answer(out) is False       # at threshold: run
    out["answers"]["new_content"]["noul"] = 0.8
    assert gates.read_digest_answer(out) is False


def test_digest_answer_fail_open():
    """Failed / missing answer: run the digest (today's path)."""
    assert gates.read_digest_answer(None) is False
    assert gates.read_digest_answer({"success": False, "answers": {}}) is False
    assert gates.read_digest_answer({"success": True, "answers": {}}) is False


def test_digest_new_tokens_caps_at_max():
    lines = [{"text": "x"} for _ in range(10)]
    text = gates.digest_new_tokens(lines, [(0, "i"), (0, "i")], [(0, "s")], max_chars=20)
    assert len(text) <= 20
    # Empty lines / subs / shown: empty result.
    assert gates.digest_new_tokens([], [], []) == ""


# ----- thresholds (constants) ----------------------------------------------

def test_thresholds_are_module_level_constants():
    """Thresholds live as module constants per the spec; they are not derived from data."""
    assert gates.FACTCHECK_SPECIFIC_THRESHOLD == 0.5
    assert gates.FACTCHECK_REPEAT_THRESHOLD == 0.7
    assert gates.FACTS_WORTH_LOOKUP_THRESHOLD == 0.5
    assert gates.DIGEST_NEW_CONTENT_THRESHOLD == 0.3