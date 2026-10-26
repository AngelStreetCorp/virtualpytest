"""Atlas Prepared FAQ (TASK-152 phase 9).

Pure unit tests: no LLM, no real database (the DB module is mocked; the in-memory cache and the
manager-side hook are tested directly). Mirrors the style of ``test_atlas_quick_step.py``.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))

# scripts/usecase_contract.py — loaded by path: putting scripts/ on sys.path would
# shadow the backend's own "agent" package with scripts/agent/.
_spec = importlib.util.spec_from_file_location(
    "usecase_contract", str(REPO / "scripts" / "usecase_contract.py"))
_usecase_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_usecase_contract)
contract_rows = _usecase_contract.contract_rows

try:
    from agent import faqs, faqs_step  # noqa: E402
    from agent.core import message_types as mt  # noqa: E402
    from agent.core.manager import QAManagerAgent  # noqa: E402
    from shared.src.lib.database import agent_faq_db  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ normalisation

@pytest.mark.parametrize("text,expected", [
    ("What is Fixnet?", "what is fixnet"),
    # Hyphens and punctuation drop (they become whitespace); underscores stay (they preserve
    # technical identifiers like IR_IP).
    ("  HOW   does IR-PATH   differ from IR_IP ? ", "how does ir path differ from ir_ip"),
    ("Sömé unicode — éàü", "sömé unicode éàü"),
    ("", ""),
    (None, ""),
])
def test_normalise_lowercase_punctuation_and_whitespace(text, expected):
    assert faqs.normalize(text) == expected


def test_alias_tokens_returns_unique_set():
    assert faqs.alias_tokens("alpha beta gamma beta") == {"alpha", "beta", "gamma"}


def test_alias_tokens_drops_function_words():
    assert faqs.alias_tokens("what is the ir keymap") == {"ir", "keymap"}


# ------------------------------------------------------------------ HotFaqCache

def _row(faq_id="1", question="Which IR standard?", aliases=(), short="ANS", count=0):
    return {
        "id": faq_id,
        "question_text": question,
        "normalised_question": faqs.normalize(question),
        "aliases": list(aliases),
        "short": short,
        "long": short + " (long)",
        "sources": ["docs/agent/foo.md"],
        "tags": ["seed"],
        "count": count,
        "last_asked_at": None,
    }


def test_hot_cache_load_keeps_top_n_by_count():
    cache = faqs.HotFaqCache(capacity=3)
    rows = [
        _row("a", "alpha", count=1),
        _row("b", "bravo", count=10),
        _row("c", "charlie", count=5),
        _row("d", "delta", count=2),
    ]
    n = cache.load(rows)
    assert n == 3
    ids = [e.id for e in cache.kv()]
    assert ids == ["b", "c", "d"]


def test_hot_cache_lookup_exact_match():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "Which IR standard do you use?", short="NEC/RC-MM")])
    hit = cache.lookup("Which IR standard do you use?")
    assert hit is not None
    assert hit.source == faqs.SOURCE_HOT
    assert hit.score == 1.0
    assert "NEC/RC-MM" in hit.entry.short


def test_hot_cache_lookup_miss_on_unrelated_question():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "Which IR standard do you use?")])
    assert cache.lookup("How is Fixnet wired?") is None


def test_hot_cache_lookup_alias_match():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "How does one script work for all devices?", aliases=("cross device script",))])
    hit = cache.lookup("cross device script")  # type: ignore[arg-type]
    assert hit is not None
    assert hit.source == faqs.SOURCE_HOT
    # 3-token query, 3 tokens overlapped → score 3/3 = 1.0.
    assert hit.score >= 0.5


# ------------------------------------------------------------------ alias-tier guards (2026-10-22)

def test_alias_tier_rejects_single_shared_token():
    """The regression that shipped in phase 9a: two different IR questions share the token "ir",
    so the old tier answered the IR_PATH-vs-IR_IP entry for "Which IR standard do you use?"."""
    cache = faqs.HotFaqCache()
    cache.load([
        _row("ir-01", "Which IR standard do you use, and where is the keymap?"),
        _row("ir-04", "What's the difference between IR_PATH and IR_IP?"),
    ])
    # A genuine alias-style paraphrase of ir-01, with three shared CONTENT tokens
    # ("ir", "standard", "keymap" — "which" and "used" are function words and do not count).
    hit = cache.lookup("which ir standard keymap is used")
    assert hit is not None
    assert hit.entry.id == "ir-01"


def test_alias_tier_requires_three_shared_content_tokens():
    """Two shared content tokens are no longer enough (2026-10-24).

    "ir standard" is exactly the kind of pair that used to pull the wrong IR row in, and on a
    non-technical phrasing two shared tokens were enough to land on the wrong row 15 times out of
    46 resolved. The floor is now three; a miss falls through to the model, which is slow but
    right.
    """
    cache = faqs.HotFaqCache()
    cache.load([
        _row("ir-01", "Which IR standard do you use, and where is the keymap?"),
        _row("ir-04", "What's the difference between IR_PATH and IR_IP?"),
    ])
    # "ir" and "standard" are shared with ir-01 — two content tokens, under the floor.
    assert cache.lookup("which ir standard is used") is None
    # The same query with a third content token resolves.
    hit = cache.lookup("which ir standard keymap")
    assert hit is not None
    assert hit.entry.id == "ir-01"


def test_alias_tier_requires_two_shared_tokens():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "How does one script work for all devices?")])
    # Only "devices" is shared with the entry; that alone must not resolve.
    assert cache.lookup("devices") is None


def test_alias_tier_requires_minimum_share():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "monitor profiles resolve per device model")])
    # Six shared tokens, but buried in a 23-token question: 6/23 = 26 %, under the 30 % floor.
    padded = ("please could you tell me about the monitor profiles resolve per device model "
              "configuration in our production deployment environment right now today ok")
    assert cache.lookup(padded) is None


def test_alias_tier_rejects_single_token_query():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "How does one script work for all devices?")])
    assert cache.lookup("devices") is None


# ------------------------------------------------------------------ hot-cache TTL (2026-10-22)

def test_alias_tier_ignores_function_words():
    """The regression that survived the first round of guards.

    "Which IR standard do you use, and where is the keymap?" shares only the function words
    is/the/and/do with "What is env_backup.py on the host side and what does it do" — 4 of 11
    tokens, 36 %. With function words in the score that beat the exact match. Content words
    only: the two questions share nothing.
    """
    cache = faqs.HotFaqCache()
    cache.load([_row("env", "What is env_backup.py on the host side and what does it do?")])
    assert cache.lookup("Which IR standard do you use, and where is the keymap?") is None


def test_alias_tier_still_matches_on_real_content_words():
    cache = faqs.HotFaqCache()
    cache.load([_row("a", "Which IR standard do you use, and where is the keymap?")])
    hit = cache.lookup("which ir standard keymap is used")
    assert hit is not None
    assert hit.entry.id == "a"


def test_canonical_match_beats_a_weak_alias_hit():
    """A hot-cache alias guess must not short-circuit the indexed canonical lookup."""
    cache = faqs.HotFaqCache()
    cache.load([_row("guess", "ir standard stb json profile remote keymap layout")])
    # The hot cache would alias onto "guess"; the DB has the exact canonical row.
    with patch.object(agent_faq_db, "find_match", return_value=_row("exact", "Which IR standard do you use, and where is the keymap?")):
        decision = faqs_step.step("Which IR standard do you use, and where is the keymap?",
                                  SimpleNamespace(id=None, context={}))
    assert decision.source == faqs.SOURCE_NORMALISED
    assert decision.faq_id == "exact"


def test_is_stale_true_when_never_loaded():
    cache = faqs.HotFaqCache()
    assert cache.is_stale(600.0)


def test_is_stale_false_right_after_load():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "hello world")])
    assert not cache.is_stale(600.0)


def test_is_stale_true_after_ttl():
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "hello world")])
    # Pretend the load happened a long time ago.
    cache._last_loaded_at -= 5000.0
    assert cache.is_stale(600.0)


def test_maybe_refresh_noop_while_fresh():
    faqs.cache().load([_row("1", "fresh entry")])
    calls = []

    def loader():
        calls.append(1)
        return []

    assert not faqs.maybe_refresh(ttl_s=600.0, loader=loader)
    assert calls == []


def test_maybe_refresh_reloads_when_stale():
    faqs.cache().load([_row("1", "old entry")])
    faqs.cache()._last_loaded_at -= 5000.0

    def loader():
        return [_row("1", "new entry"), _row("2", "second entry")]

    assert faqs.maybe_refresh(ttl_s=600.0, loader=loader)
    ids = {e.id for e in faqs.cache().kv()}
    assert "2" in ids


def test_maybe_refresh_survives_a_broken_loader():
    faqs.cache().load([_row("1", "still here")])
    faqs.cache()._last_loaded_at -= 5000.0

    def loader():
        raise RuntimeError("database is down")

    assert not faqs.maybe_refresh(ttl_s=600.0, loader=loader)
    # The previous snapshot survives a failed refresh — a DB blip must not empty the cache.
    assert faqs.cache().size() == 1


def test_hot_cache_empty_returns_none():
    cache = faqs.HotFaqCache()
    assert cache.lookup("anything") is None


def test_hot_cache_dedupes_normalised_collision():
    """If two rows normalise to the same key, the first loaded wins and the second is shadowed."""
    cache = faqs.HotFaqCache()
    cache.load([
        _row("1", "How is Fixnet wired?", short="FIRST"),
        _row("2", "How is fixnet wired?", short="SECOND"),
    ])
    hit = cache.lookup("how is fixnet wired?")
    assert hit is not None
    assert hit.entry.id == "1"
    assert hit.entry.short == "FIRST"


# ------------------------------------------------------------------ pool of 100

def test_pool_of_100_from_seed_loads_and_top_n_holds_only_64():
    seed_path = REPO / "docs" / "tasks" / "TASK-152-faq-seed.md"
    if not seed_path.exists():
        pytest.skip("seed not present (docs/tasks/TASK-152-faq-seed.md)")
    rows = []
    for i in range(1, 101):
        rows.append(_row(
            faq_id=f"q{i:03d}",
            question=f"Question number {i} about VirtualPyTest",
            count=101 - i,
        ))
    cache = faqs.HotFaqCache(capacity=64)
    n = cache.load(rows)
    assert n == 64
    assert len(cache.kv()) == 64
    # The top entry by count (q001 with 100) is in.
    assert cache.kv()[0].id == "q001"
    # A bottom entry (q100 with 1) was dropped.
    assert all(e.id != "q100" for e in cache.kv())


# ------------------------------------------------------------------ kill switch and helper

def test_enabled_default_on_and_env_off(monkeypatch):
    monkeypatch.delenv("ATLAS_FAQ", raising=False)
    assert faqs.enabled()
    monkeypatch.setenv("ATLAS_FAQ", "off")
    assert not faqs.enabled()


def _agent_with_fake_cache(rows):
    """Build a fixture-style agent-like object used by helper-only tests (deprecated;
    kept so the module's later tests still get the imports)."""
    faqs.cache().load(rows)
    return SimpleNamespace(id="s1", context={"team_id": "t1", "user_id": "u1"})


def test_step_returns_miss_when_disabled(monkeypatch):
    monkeypatch.setenv("ATLAS_FAQ", "off")
    session = SimpleNamespace(id=None, context={})
    decision = faqs_step.step("Which IR standard?", session)
    assert decision.answer is None
    assert decision.source == faqs.SOURCE_NONE
    assert decision.had_answer is False


# ------------------------------------------------------------------ manager hook integration

def _agent_with_fake_cache(rows):
    """Build a QAManagerAgent with the FAQ cache pre-loaded and the DB layer mocked."""
    cache = faqs.HotFaqCache(capacity=64)
    cache.load(rows)
    agent = QAManagerAgent.__new__(QAManagerAgent)  # bypass __init__
    agent.agent_id = "assistant"
    ai_settings = {"api_key_configured": True, "endpoint": "test", "error": None}
    agent_config = {"nickname": "Atlas", "available_skills": [], "ai_settings": ai_settings}
    agent.agent_config = agent_config
    agent._active_skill = None
    agent._is_background = False
    agent._quick_handled = False
    agent.logger = __import__("logging").getLogger("test_atlas_faq")
    session = SimpleNamespace(
        id="s1", context={"team_id": "t1", "user_id": "u1"},
        add_message=lambda role, content, **kw: None,
        cancelled=False,
        needs_compaction=lambda *a, **kw: False,
        pending_approval=False,
        set_context=lambda *a, **kw: None,
    )
    return agent, session


def test_manager_hook_short_circuits_on_hot_cache_hit():
    """Direct unit test of the helper that powers the manager hook.

    The full ``agent._process_message`` integration needs the AI client, RoutingTracker,
    SessionManager and the live database; those are exercised by the live benchmark
    (``scripts/agent/atlas_faq_bench.py``). This test pins the helper contract.
    """
    faqs.cache().load([_row("1", "Which IR standard?", short="NEC/RC-MM, learned waveform.")])
    session = SimpleNamespace(id="s1", context={"team_id": "t1", "user_id": "u1"})
    decision = faqs_step.step("Which IR standard?", session, team_id="t1", user_id="u1", session_id="s1")
    assert decision.answer is not None
    assert "NEC/RC-MM" in decision.answer
    events = faqs_step.emit(decision, agent_name="Atlas")
    assert events and events[0].type == mt.EventType.MESSAGE
    # The hot-cache hit is the only source today; the DB tier writes the same shape but with a
    # different source string (the path through ``agent_faq_db.find_match`` is exercised in the
    # live bench).
    assert decision.source == faqs.SOURCE_HOT


def test_manager_hook_falls_through_on_miss(monkeypatch):
    """On a miss, ``step`` returns a decision with ``answer=None``. The manager loop then enters
    the model loop exactly as before — the test pins that contract without dragging the model."""
    faqs.cache().load([])   # empty cache
    session = SimpleNamespace(id=None, context={})
    decision = faqs_step.step("How is Fixnet wired?", session)
    assert decision.answer is None
    assert decision.source == faqs.SOURCE_NONE
    assert decision.had_answer is False
    events = faqs_step.emit(decision, agent_name="Atlas")
    assert events == []


# ------------------------------------------------------------------ self-promotion

def test_maybe_promote_from_model_answer_picks_citations():
    captured = {}

    def fake_upsert(*, question_text, normalised, short, long, sources, tags):
        captured["q"] = question_text
        captured["sources"] = list(sources)
        captured["short"] = short
        return "fake-id"

    with patch.object(agent_faq_db, "upsert_promoted", side_effect=fake_upsert), \
         patch.object(agent_faq_db, "record_question", lambda **kw: None):
        faq_id = faqs_step.maybe_promote_from_model_answer(
            "Which IR standard do you use?",
            "The platform replays the learned waveform (source: docs/agent/devices/INFRARED.md).",
        )
    assert faq_id == "fake-id"
    assert captured["sources"] == ["docs/agent/devices/INFRARED.md"]
    assert captured["short"].startswith("The platform replays the learned waveform")


def test_maybe_promote_skips_answer_without_citations():
    with patch.object(agent_faq_db, "upsert_promoted") as upsert:
        faq_id = faqs_step.maybe_promote_from_model_answer(
            "How is the weather?", "Sunny today."
        )
    assert faq_id is None
    upsert.assert_not_called()


def test_step_lazily_loads_hot_cache_on_first_miss_then_tier2_match():
    """When the hot cache is empty, the first call lazy-loads rows from the DB; a normalised
    canonical SQL on the same normalised text then surfaces a tier-2 hit. Both happen for the
    same call when tier-1 misses but tier-2 matches."""
    faqs.cache().load([])           # force-cold
    session = SimpleNamespace(id="s2", context={})
    row = _row("1", "How is Fixnet wired?", short="FX-over-USB.")
    # load_hot returns the row (so tier-1 will see it after lazy-load), but we still test the
    # scenario where tier-1 misses on a phrasing that tier-2 catches via normalised SQL.
    # For this test we keep the cache empty after lazy-load and only return a row from find_match.
    with patch.object(agent_faq_db, "load_hot", return_value=[]), \
         patch.object(agent_faq_db, "find_match", return_value=row):
        decision = faqs_step.step("how is fixnet wired?", session)
    assert decision.answer is not None
    assert "FX-over-USB" in decision.answer
    assert decision.source == faqs.SOURCE_NORMALISED
    assert decision.faq_id == "1"
    assert decision.had_answer is True


def test_step_kill_switch_returns_miss_with_zero_source():
    faqs.cache().load([_row("1", "hello", short="x")])
    session = SimpleNamespace(id=None, context={})
    with patch.object(os, "environ", {**os.environ, "ATLAS_FAQ": "off"}):
        # simulate the env read just for this call
        decision = faqs_step.step("hello", session)
    assert decision.answer is None
    assert decision.had_answer is False


# ------------------------------------------------------------------ admission guard (phase 9c)
#
# The FAQ tier answers BEFORE the router and a hit short-circuits the turn. A message that asks
# for a live action must therefore never be answered from the docs store: it would get a stored
# paragraph instead of the action it asked for. Measured on the TASK-163 use-case contract, 38 of
# the 109 prompts matched a FAQ row ("Take control of {device}" was answered with "What stops
# scripts from clobbering a manual take-control session?").

@pytest.mark.parametrize("message", [
    "Take control of stb3",
    "take control of stb3 on vpt-pi1",
    "Release stb3",
    "Release control of stb3 when you are done",
    "Press HOME on the stb",
    "Turn stb3 on",
    "Turn off stb3",
    "Screenshot stb3 on host1",
    "Screenshot every device on host1",
    "List my test cases",
    "Execute smoke.sh on host1 stb3",
    "Wake up all devices of profile p1",
    "I want to control stb3",
    "Take control of all available stb and if not awake wake them up",
    "Go back on stb3",
    "Send stb3 a key",
])
def test_is_device_operation_catches_commands(message):
    assert faqs.is_device_operation(message)


@pytest.mark.parametrize("message", [
    "Is {device} free or in use?",
    "Who is controlling {device}?",
    "Is {device} awake?",
    "What is on the screen of {device}?",
    "Are all devices OK?",
    "Which devices are online?",
    "Which hosts are down?",
    "What is the status of {device}?",
    "What actions can I run on {device}?",
    "Is {device} showing a black screen?",
    "What scripts can I run?",
    "Did the last script run pass?",
    # "check" openings: the model answers these with docs text, and the learned entry then
    # stores that paragraph as the answer to a device command.
    "Check which phone_agent are asleep",
    "Check which devices are offline",
    # the same shapes with a real device name, not the {device} placeholder
    "What is the status of stb3?",
    "Is stb3 showing a black screen?",
    "Who is controlling stb3?",
    "Is stb3 free or in use?",
])
def test_is_device_operation_catches_live_state_questions(message):
    assert faqs.is_device_operation(message)


@pytest.mark.parametrize("message", [
    "Which devices are supported?",
    "How do I configure a phone device slot in the host?",
    "Can I run a screen capture test without the device?",
    "What is env_backup.py and what does it do?",
    "How do I verify the correct screen is showing?",
    "Where do I put customer-specific .env files?",
    "Why does the leak gate scan the change set instead of the full tree?",
    "What are the 12 prerequisite checks in the Platform update?",
    "How many prereqs does the platform update need?",
    "Is VirtualPyTest free to use?",
    "Check the leak gate docs",
    # symptom statements: no question word, but the FAQ is exactly the right place for them
    "The campaign finished but the next step didn't run.",
    "I have a black screen but the capture ran.",
    "A STB UI tree stale - but new releases haven't changed the UI.",
])
def test_is_device_operation_leaves_documentation_questions_alone(message):
    assert not faqs.is_device_operation(message)


def test_step_hands_a_live_operation_back_without_consulting_the_faq():
    """A live operation must not be answered from the docs store, and must not be logged as a miss."""
    faqs.cache().load([_row("1", "What stops scripts from clobbering a manual take-control session?",
                            short="locks are per session", count=5)])
    session = SimpleNamespace(id=None, context={})
    with patch.object(agent_faq_db, "find_match") as find_match:
        decision = faqs_step.step("Take control of stb3", session)
    assert decision.answer is None
    assert decision.had_answer is False
    assert decision.source == faqs.SOURCE_NONE
    assert decision.log is None          # the FAQ was never consulted: not a miss either
    find_match.assert_not_called()


def test_step_still_answers_a_documentation_question():
    faqs.cache().load([_row("1", "What stops scripts from clobbering a manual take-control session?",
                            short="locks are per session", count=5)])
    session = SimpleNamespace(id=None, context={})
    decision = faqs_step.step("What stops scripts from clobbering a manual take-control session?",
                              session)
    assert decision.answer is not None
    assert decision.had_answer is True


def test_record_log_ignores_a_hand_back():
    decision = faqs_step.FaqTurnDecision(
        answer=None, source=faqs.SOURCE_NONE, faq_id=None, latency_ms=1, had_answer=False, log=None,
    )
    with patch.object(agent_faq_db, "record_question") as record:
        faqs_step.record_log(decision)
    record.assert_not_called()


# ------------------------------------------------------------------ corpus residency (phase 9c)

def test_default_cache_cap_covers_a_corpus_larger_than_64():
    """The alias tier lives ONLY in the hot cache, so a row outside the cap is unreachable by alias."""
    rows = [_row(f"q{i:03d}", f"Question number {i} about VirtualPyTest", count=100 - i)
            for i in range(1, 101)]
    cache = faqs.HotFaqCache()          # the default capacity, i.e. faqs.HOT_CAP
    assert cache.load(rows) == 100
    assert faqs.HOT_CAP >= 100


def test_an_alias_on_a_cold_row_is_reachable():
    """A row ranked below the old top-64 must still be findable through its alias."""
    rows = [_row(f"q{i:03d}", f"Question number {i} about VirtualPyTest", count=200 - i)
            for i in range(1, 101)]
    rows.append(_row("cold", "How is env_backup.py used on the host side?",
                     aliases=["what does the env_backup.py script do on the host"], count=0))
    cache = faqs.HotFaqCache()
    cache.load(rows)
    hit = cache.lookup("what does the env_backup.py script do on the host")
    assert hit is not None
    assert hit.entry.id == "cold"


# ------------------------------------------------------------------ use-case contract (phase 9c)
#
# The FAQ tier runs before the router and a hit short-circuits the turn, so a TASK-163 use-case
# prompt that matches a FAQ row never reaches the tool it asked for. This test pins that property
# without a database: it loads the curated seed and checks every use-case prompt.

def _seed_rows():
    """The curated seed as cache rows (same alias generator the loader uses)."""
    seed_path = REPO / "docs" / "tasks" / "TASK-152-faq-seed.md"
    if not seed_path.exists():
        pytest.skip("seed not present (docs/tasks/TASK-152-faq-seed.md)")
    sys.path.insert(0, str(REPO / "scripts" / "agent"))
    from faq_load_seed import alias_seed, parse_seed  # noqa: E402

    rows = []
    for i, entry in enumerate(parse_seed(seed_path)):
        question = entry.get("question") or ""
        rows.append(_row(
            f"seed{i:03d}",
            question,
            aliases=alias_seed(question, entry.get("topic") or ""),
            count=1,
        ))
    return rows


def _use_case_prompts():
    """The UC-nnn prompts of the TASK-163 contract.

    The contract table only: docs/agent/atlas/USECASES.md also holds the results
    tables and the browser-verification table, whose rows start with a UC- id too.
    Those are documentation — one of them carries a real device name — and they must
    not enter the FAQ-hijack check as if they were live operations. The table is
    found by its section (scripts/usecase_contract.py).
    """
    path = REPO / "docs" / "agent" / "atlas" / "USECASES.md"
    if not path.exists():
        pytest.skip("use-case contract not present (docs/agent/atlas/USECASES.md)")
    return [(row["id"], row["cells"][0]) for row in contract_rows(path.read_text(encoding="utf-8"))
            if row["cells"]]


def test_the_faq_tier_never_answers_a_use_case_prompt():
    """A live operation must reach the router, not the docs store."""
    cache = faqs.HotFaqCache(faqs.HOT_CAP)
    cache.load(_seed_rows())
    hijacked = []
    for uc_id, prompt in _use_case_prompts():
        if faqs.should_decline(prompt):
            continue
        if cache.lookup(prompt) is not None:
            hijacked.append((uc_id, prompt))
    assert not hijacked, f"the FAQ tier would answer these use-case prompts: {hijacked}"


def test_a_documentation_question_still_answers_from_the_seed():
    """The guard must not swallow the questions the corpus exists for."""
    rows = _seed_rows()
    cache = faqs.HotFaqCache(faqs.HOT_CAP)
    cache.load(rows)
    for row in rows:
        question = row["question_text"]
        if not question:
            continue
        assert not faqs.should_decline(question), f"the guard swallowed a seed question: {question!r}"
        hit = cache.lookup(question)
        assert hit is not None, f"a seed question does not answer itself: {question!r}"
        break


# ------------------------------------------------------------------ alias ownership (2026-10-24)

def test_the_seed_loader_writes_no_aliases():
    """The loader used to write machine-made aliases ("IR what", "why are my") that resolved to
    another row or to nothing. Aliases belong to the validated backfill alone."""
    sys.path.insert(0, str(REPO / "scripts" / "agent"))
    from faq_load_seed import alias_seed
    assert alias_seed("Which IR standard do you use, and where is the keymap?", "ir") == []


class _FakeFaqTable:
    """Just enough of the postgrest chain for the alias-ownership test."""

    def __init__(self, store):
        self.store = store
        self.filters = {}
        self.upserted = None

    def select(self, *_cols):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def limit(self, _n):
        return self

    def execute(self):
        key = self.filters.get("normalised_question")
        return SimpleNamespace(data=self.store.get(key, []))

    def upsert(self, row, on_conflict=None):
        self.upserted = row
        return self


class _FakeFaqClient:
    def __init__(self, store):
        self.store = store
        self.table_obj = _FakeFaqTable(store)

    def table(self, _name):
        return self.table_obj


def test_upsert_seeded_keeps_an_existing_alias_set():
    """A re-seed must not throw away the alias set the backfill owns."""
    store = {"what is fixnet": [{"aliases": ["fixnet modem fx wiring"]}]}
    client = _FakeFaqClient(store)
    with patch.object(agent_faq_db, "_supabase", return_value=client):
        agent_faq_db.upsert_seeded(
            question_text="What is Fixnet?",
            normalised="what is fixnet",
            aliases=["junk alias"],
            short="s", long="l", sources=["docs/x.md"], tags=[],
        )
    assert "aliases" not in client.table_obj.upserted


def test_upsert_seeded_fills_an_empty_alias_set():
    store = {"what is fixnet": [{"aliases": []}]}
    client = _FakeFaqClient(store)
    with patch.object(agent_faq_db, "_supabase", return_value=client):
        agent_faq_db.upsert_seeded(
            question_text="What is Fixnet?",
            normalised="what is fixnet",
            aliases=["fixnet modem fx wiring"],
            short="s", long="l", sources=["docs/x.md"], tags=[],
        )
    assert client.table_obj.upserted["aliases"] == ["fixnet modem fx wiring"]


# ------------------------------------------------------------------ miss logging (2026-10-24)

def test_a_miss_is_logged_with_source_none():
    """A FAQ miss must reach atlas_faq_log.

    The manager only logs a decision that carried an answer, so `match_source` never got a
    'none' row and the log showed what the FAQ answered, never what it failed on. That is the
    signal that says which questions to add next.
    """
    import time as _time

    faqs.cache().load([_row("1", "Which IR standard do you use, and where is the keymap?")])
    session = SimpleNamespace(id=None, context={})
    with patch.object(agent_faq_db, "record_question") as record, \
         patch.object(agent_faq_db, "find_match", return_value=None):
        decision = faqs_step.step("a question nothing in the corpus answers", session)
        assert decision.answer is None
        for _ in range(50):          # the write happens in a daemon thread
            if record.called:
                break
            _time.sleep(0.02)
    assert record.called, "the miss was not logged"
    assert record.call_args.kwargs["match_source"] == faqs.SOURCE_NONE


def test_a_hit_is_not_logged_twice():
    """The manager logs a hit; the step must not log it again."""
    faqs.cache().load([_row("1", "Which IR standard do you use, and where is the keymap?")])
    session = SimpleNamespace(id=None, context={})
    with patch.object(agent_faq_db, "record_question") as record:
        decision = faqs_step.step("Which IR standard do you use, and where is the keymap?", session)
        assert decision.answer is not None
        import time as _time
        _time.sleep(0.1)
    assert not record.called


def test_the_review_pass_refuses_to_promote_a_live_operation():
    """A learned row whose question is a device command must never go live.

    The FAQ tier answers before the router runs, so a live row like "Lock stb3 for me" turns a
    device command into a stored paragraph. The model answering a command with docs text is a
    routing mistake, not a knowledge entry.
    """
    sys.path.insert(0, str(REPO / "scripts" / "agent"))
    from faq_review import _is_live_operation
    assert _is_live_operation("Lock stb3 for me")
    assert _is_live_operation("Check which phone_agent are asleep")
    assert not _is_live_operation("Is VirtualPyTest free to use?")
    assert not _is_live_operation("How do I configure a phone device slot in the host?")


# ------------------------------------------------------------------ exact-alias equality (E59, 2026-10-25)
#
# The alias tier needed ALIAS_MIN_OVERLAP (3) shared CONTENT tokens, and shared tokens can never
# exceed the query's own content-token count. So a query with fewer than three content tokens was
# STRUCTURALLY unreachable, no matter how often it was asked: the curated alias was stored,
# validated and dead. On the live corpus 33 of 1002 aliases (3.3 %) were dead that way, and all
# 11 CJK aliases were among them — the whitespace tokenizer keeps a Chinese phrase as ONE token.
#
# The fix is an equality lookup, not a looser score: a question that IS a curated alias resolves
# on identity, with no floor to clear. It is placed after the canonical check (a canonical
# question keeps its own row) and before the fuzzy path (an exact alias beats a token guess).


def test_a_dead_alias_below_the_overlap_floor_is_reachable():
    """THE acceptance case — it fails on pristine main and passes here.

    "Pricing" is ONE content token: below ALIAS_MIN_QUERY_TOKENS (2) and far below
    ALIAS_MIN_OVERLAP (3), so the fuzzy tier never even entered. The alias was curated, stored
    and answered by nothing. On main this lookup returns None.
    """
    cache = faqs.HotFaqCache()
    cache.load([_row("pricing", "What does VirtualPyTest cost?", aliases=["Pricing"])])
    hit = cache.lookup("Pricing")
    assert hit is not None, "a curated alias below the overlap floor is still unreachable"
    assert hit.entry.id == "pricing"
    assert hit.source == faqs.SOURCE_HOT
    assert hit.score == 1.0


def test_a_cjk_alias_is_reachable():
    """A Chinese phrase is ONE token for the whitespace tokenizer, so EVERY CJK alias was dead.

    11 of the 33 rescued aliases are CJK ('多少钱', '价格是多少' and 9 others).
    """
    cache = faqs.HotFaqCache()
    cache.load([_row("pricing", "What does VirtualPyTest cost?", aliases=["多少钱", "价格是多少"])])
    for alias in ("多少钱", "价格是多少"):
        hit = cache.lookup(alias)
        assert hit is not None, f"the CJK alias {alias!r} is still unreachable"
        assert hit.entry.id == "pricing"
        assert hit.source == faqs.SOURCE_HOT


def test_the_exact_alias_lookup_runs_before_the_fuzzy_path():
    """The exact-alias lookup runs BEFORE the fuzzy path.

    Both rows share the query's tokens, so the fuzzy tier alone would tie-break by load order
    and answer the OTHER row. The exact alias must answer with its own row.
    """
    cache = faqs.HotFaqCache()
    cache.load([
        _row("other", "is the platform really free for small teams"),
        _row("exact", "What does VirtualPyTest cost?", aliases=["is the platform really free"]),
    ])
    hit = cache.lookup("is the platform really free")
    assert hit is not None
    assert hit.entry.id == "exact"
    assert hit.score == 1.0


def test_a_canonical_question_still_wins_over_a_colliding_alias():
    """An alias that is another row's canonical question must not steal that question's row."""
    cache = faqs.HotFaqCache()
    cache.load([
        _row("other", "Something else entirely", aliases=["Which IR standard do you use?"]),
        _row("real", "Which IR standard do you use?"),
    ])
    hit = cache.lookup("Which IR standard do you use?")
    assert hit is not None
    assert hit.entry.id == "real"


def test_an_alias_on_a_row_outside_the_cap_stays_unreachable():
    """The alias map is built from the SAME truncated list the cache holds.

    A row outside the cap stays unreachable by alias, exactly as it is today — the fix does not
    widen the cache's residency.
    """
    rows = [_row(f"q{i:03d}", f"Question number {i} about VirtualPyTest", count=100 - i)
            for i in range(1, 4)]
    rows.append(_row("cold", "What does VirtualPyTest cost?", aliases=["Pricing"], count=0))
    cache = faqs.HotFaqCache(capacity=3)
    cache.load(rows)
    assert cache.lookup("Pricing") is None


# --- negative controls: the fix must not answer anything it did not answer before ---------------

def test_a_greeting_still_misses():
    """Negative control: a greeting is not a question and must stay a miss."""
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "Which IR standard do you use?", aliases=["Pricing", "多少钱"])])
    assert cache.lookup("hello there friend") is None


def test_a_live_command_still_misses():
    """Negative control: a live command is handed back to the router.

    ``faqs.should_decline`` runs BEFORE the FAQ tier, so the exact-alias path never sees a live
    command — even when the command text is stored as an alias of a row.
    """
    assert faqs.should_decline("Lock stb3 for me")
    cache = faqs.HotFaqCache()
    cache.load([_row("1", "Which IR standard do you use?", aliases=["Lock stb3 for me"])])
    with patch.object(faqs, "cache", return_value=cache), \
         patch.object(agent_faq_db, "find_match", return_value=None):
        decision = faqs_step.step("Lock stb3 for me", SimpleNamespace(id=None, context={}))
    assert decision.answer is None
    assert decision.had_answer is False
    assert decision.log is None, "a hand-back is not a miss and must not be logged as one"


def test_an_exact_alias_hit_skips_the_database_round_trip():
    """score 1.0 means the step trusts the hot cache and never asks the DB for a canonical row."""
    cache = faqs.HotFaqCache()
    cache.load([_row("pricing", "What does VirtualPyTest cost?", aliases=["Pricing"])])
    with patch.object(faqs, "cache", return_value=cache), \
         patch.object(agent_faq_db, "find_match", return_value=None) as find:
        decision = faqs_step.step("Pricing", SimpleNamespace(id=None, context={}))
    assert decision.had_answer is True
    assert decision.source == faqs.SOURCE_HOT
    assert decision.faq_id == "pricing"
    assert not find.called, "the DB canonical round trip must be skipped for an exact alias hit"


def test_a_miss_log_that_cannot_start_its_thread_does_not_break_the_turn():
    """The audit write must never take the turn down with it.

    Creating the thread can fail on its own - no thread slots left, a patched threading module.
    The docstring of _log_in_background promises the turn survives; this is that promise, tested.
    """
    class _ThreadRefusesToStart:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("can't start new thread")

    with patch.object(faqs_step.threading, "Thread", _ThreadRefusesToStart):
        faqs_step._log_in_background({
            'team_id': 't1', 'session_id': 's1', 'user_id': 'u1',
            'question_text': 'a question that misses',
        })
