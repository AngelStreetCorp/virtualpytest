"""Atlas daily memory (TASK-172).

Pure unit tests: no LLM, no database, no network. The memory is a set of markdown files under a
temporary directory, so every test here is about the file contract — what is written, what is
recalled, and who may see it.

The contract that matters most for the product is the **off-path**: with ``ATLAS_MEMORY`` unset,
Atlas must behave exactly as it does today. Those tests are first, because they are the ones that
protect the deployed system while the memory is still a prototype.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))

try:
    from agent import faqs, memory, memory_step  # noqa: E402
    from agent.core import message_types as mt  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


@pytest.fixture()
def mem_root(tmp_path, monkeypatch):
    """A memory tree in a temporary directory, with the memory switched on."""
    root = tmp_path / "atlas_memory"
    monkeypatch.setenv("ATLAS_MEMORY_DIR", str(root))
    monkeypatch.setenv("ATLAS_MEMORY", "on")
    yield root


def _session(**context):
    return SimpleNamespace(id="s1", context={"team_id": "t1", "user_id": "u1", **context})


# ------------------------------------------------------------------ the off-path (first, on purpose)

def test_memory_is_off_for_every_user_by_default(mem_root, monkeypatch):
    """The default is on demand: nobody has a memory until they switch it on for themselves."""
    monkeypatch.delenv("ATLAS_MEMORY", raising=False)
    assert memory.opt_in_only() is True
    assert memory.enabled_for("t1", "u1") is False
    assert memory.record(team_id="t1", user_id="u1", question="create a script", answer="a") is None
    assert memory_step.step("create a script", _session(), team_id="t1", user_id="u1").answer is None


def test_env_switch_off_turns_the_memory_off(monkeypatch):
    monkeypatch.setenv("ATLAS_MEMORY", "off")
    assert memory.enabled() is False
    monkeypatch.setenv("ATLAS_MEMORY", "on")
    assert memory.enabled() is True


def test_off_path_writes_nothing(mem_root, monkeypatch):
    """With the memory off, a turn that ends must not create a file anywhere."""
    monkeypatch.setenv("ATLAS_MEMORY", "off")
    assert memory.record(team_id="t1", user_id="u1", question="create a script", answer="done") is None
    assert memory_step.record_turn(team_id="t1", user_id="u1", question="create a script",
                                   answer="done", tool_calls=[{"tool_name": "manage_script"}]) is None
    assert not list(mem_root.rglob("*.md"))


def test_off_path_step_is_a_miss(mem_root, monkeypatch):
    """With the memory off the step never answers, so the turn falls through to the model."""
    monkeypatch.setenv("ATLAS_MEMORY", "off")
    decision = memory_step.step("create a script", _session(), team_id="t1", user_id="u1", session_id="s1")
    assert decision.answer is None
    assert decision.source == memory_step.SOURCE_NONE
    assert decision.had_answer is False


# ------------------------------------------------------------------ the write

def test_record_writes_a_daily_markdown_file(mem_root):
    """One file per user per day — the shape the owner asked for."""
    path = memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.")
    assert path is not None
    assert path.name == f"{datetime.now(timezone.utc):%Y-%m-%d}.md"
    assert path.parent.name == "u1"
    assert path.parent.parent.name == "t1"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Atlas memory — ")
    assert "- key: create a script" in text
    assert "- question: create a script" in text


def test_record_appends_to_the_same_file_on_the_same_day(mem_root):
    first = memory.record(team_id="t1", user_id="u1", question="create a script", answer="one")
    second = memory.record(team_id="t1", user_id="u1", question="cap 5", answer="two")
    assert first == second
    text = first.read_text(encoding="utf-8")
    assert text.count("# Atlas memory — ") == 1
    assert "- key: create a script" in text and "- key: cap 5" in text


def test_record_stores_the_tools_and_the_artefacts(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.",
                  tools=["manage_script"], artefacts=["script_id=abc123", "script_name=nightly-smoke"])
    text = next(mem_root.rglob("*.md")).read_text(encoding="utf-8")
    assert "- tools: manage_script" in text
    assert "- artefacts: script_id=abc123, script_name=nightly-smoke" in text


def test_record_without_a_user_writes_nothing(mem_root):
    """A memory with no owner would be a global store — that is the FAQ's job, not this one's."""
    assert memory.record(team_id="t1", user_id=None, question="create a script", answer="x") is None
    assert memory.record(team_id=None, user_id="u1", question="create a script", answer="x") is None
    assert not list(mem_root.rglob("*.md"))


def test_record_never_raises(mem_root, monkeypatch):
    """A broken memory must never break the turn that produced it."""
    monkeypatch.setattr(memory, "day_path", lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone")))
    assert memory.record(team_id="t1", user_id="u1", question="q", answer="a") is None


# ------------------------------------------------------------------ the read

def test_lookup_finds_the_entry_by_key(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.")
    entry = memory.lookup("t1", "u1", "create a script")
    assert entry is not None
    assert entry.answer == "Created it."


def test_lookup_ignores_case_and_punctuation(mem_root):
    """The key is the FAQ's normalised form, so the same question in another shape still hits."""
    memory.record(team_id="t1", user_id="u1", question="Create a script!", answer="Created it.")
    assert memory.lookup("t1", "u1", "create a script") is not None
    assert memory.lookup("t1", "u1", "  CREATE   A SCRIPT  ") is not None


def test_lookup_misses_on_a_paraphrase(mem_root):
    """Exact key only. A wrong memory is worse than no memory: the answer would be about
    something the user did not ask."""
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.")
    assert memory.lookup("t1", "u1", "create a python script") is None
    assert memory.lookup("t1", "u1", "create a user interface") is None


def test_lookup_misses_when_nothing_was_recorded(mem_root):
    assert memory.lookup("t1", "u1", "create a script") is None


def test_memory_is_user_scoped(mem_root):
    """User B must never see user A's memory."""
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="A's script.")
    assert memory.lookup("t1", "u2", "create a script") is None
    assert memory.lookup("t1", "u1", "create a script") is not None


def test_memory_is_team_scoped(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="A.")
    assert memory.lookup("t2", "u1", "create a script") is None


def test_the_newest_day_wins(mem_root):
    """A question asked twice keeps the latest answer."""
    now = datetime.now(timezone.utc)
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="first",
                  now=now - timedelta(days=1))
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="second", now=now)
    entry = memory.lookup("t1", "u1", "create a script")
    assert entry is not None and entry.answer == "second"


def test_an_entry_older_than_the_lookback_is_not_offered(mem_root):
    old = datetime.now(timezone.utc) - timedelta(days=memory.LOOKBACK_DAYS + 2)
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="ancient", now=old)
    assert memory.lookup("t1", "u1", "create a script") is None


# ------------------------------------------------------------------ the toggle

def test_the_per_user_marker_turns_the_memory_off_for_one_user(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.")
    assert memory.enabled_for("t1", "u1") is True
    assert memory.set_disabled("t1", "u1", True) is True
    assert memory.enabled_for("t1", "u1") is False
    assert memory.lookup("t1", "u1", "create a script") is None
    # the other user is untouched
    assert memory.enabled_for("t1", "u2") is True
    # and it can be turned back on
    memory.set_disabled("t1", "u1", False)
    assert memory.enabled_for("t1", "u1") is True


def test_forget_removes_only_that_users_files(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="A.")
    memory.record(team_id="t1", user_id="u2", question="create a script", answer="B.")
    assert memory.forget("t1", "u1") >= 1
    assert memory.lookup("t1", "u1", "create a script") is None
    assert memory.lookup("t1", "u2", "create a script") is not None


def test_prune_removes_the_files_past_the_retention(mem_root):
    old = datetime.now(timezone.utc) - timedelta(days=memory.RETENTION_DAYS + 5)
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="old", now=old)
    memory.record(team_id="t1", user_id="u1", question="cap 5", answer="new")
    # The first write of a new day prunes on its own, so the old file is already gone.
    remaining = [p.name for p in mem_root.rglob("*.md")]
    assert len(remaining) == 1
    assert memory.prune("t1", "u1") == 0


def test_the_memory_is_kept_30_days_at_most():
    assert memory.RETENTION_DAYS == 30
    assert memory.LOOKBACK_DAYS <= memory.RETENTION_DAYS


def test_the_default_tree_is_outside_the_repo(monkeypatch):
    """The files hold users' questions and answers: a git checkout must never carry them."""
    monkeypatch.delenv("ATLAS_MEMORY_DIR", raising=False)
    assert REPO not in memory.memory_root().resolve().parents


# ------------------------------------------------------------------ the tier in front of the model

def test_a_hit_answers_and_says_it_is_a_recollection(mem_root):
    """The answer must never claim that something happened just now."""
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created script X.",
                  tools=["manage_script"], artefacts=["script_id=abc123"])
    decision = memory_step.step("create a script", _session(), team_id="t1", user_id="u1", session_id="s1")
    assert decision.answer is not None
    assert decision.source == memory_step.SOURCE_RECALL
    assert "recollection" in decision.answer
    assert "not a fresh run" in decision.answer
    assert "manage_script" in decision.answer
    assert "script_id=abc123" in decision.answer


def test_the_hit_emits_a_message_and_ends_the_turn(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.")
    decision = memory_step.step("create a script", _session(), team_id="t1", user_id="u1", session_id="s1")
    events = memory_step.emit(decision, agent_name="Atlas")
    assert [e.type for e in events] == [mt.EventType.MESSAGE, mt.EventType.SESSION_ENDED]


def test_the_faq_keeps_priority(mem_root):
    """A curated, reviewed FAQ answer is better than a user's own recollection."""
    faqs.cache().load([{
        "id": "1", "question_text": "Which IR standard?", "normalised_question": "which ir standard",
        "aliases": [], "short": "NEC/RC-MM", "long": "NEC/RC-MM", "sources": [], "tags": [], "count": 1,
    }])
    memory.record(team_id="t1", user_id="u1", question="Which IR standard?", answer="my own answer")
    decision = memory_step.step("Which IR standard?", _session(), team_id="t1", user_id="u1", session_id="s1")
    assert decision.answer is None          # the memory stands aside
    assert decision.source == memory_step.SOURCE_NONE
    faqs.cache().load([])


def test_the_turn_write_records_the_tools_and_the_artefacts(mem_root):
    memory_step.record_turn(
        team_id="t1", user_id="u1", question="create a script", answer="Created it.",
        tool_calls=[{"tool_name": "manage_script", "params": {"script_name": "nightly-smoke"}}],
        results=[{"script_id": "abc123"}],
    )
    entry = memory.lookup("t1", "u1", "create a script")
    assert entry is not None
    assert entry.tools == ("manage_script",)
    assert "script_id=abc123" in entry.artefacts
    assert "script_name=nightly-smoke" in entry.artefacts


def test_the_turn_write_is_skipped_without_a_user(mem_root):
    assert memory_step.record_turn(team_id="t1", user_id=None, question="q", answer="a",
                                   tool_calls=[{"tool_name": "x"}]) is None
    assert not list(mem_root.rglob("*.md"))


def test_a_turn_with_no_tool_call_is_not_remembered(mem_root):
    """'I don't understand' or a clarifying question is nothing worth recalling."""
    assert memory_step.record_turn(team_id="t1", user_id="u1", question="cap 5",
                                   answer="I don't understand 'cap 5'.", tool_calls=[]) is None
    assert memory.lookup("t1", "u1", "cap 5") is None


def test_a_turn_whose_tools_all_failed_is_not_remembered(mem_root):
    memory_step.record_turn(
        team_id="t1", user_id="u1", question="create a script", answer="manage_script failed",
        tool_calls=[{"tool_name": "manage_script", "params": {}, "success": False},
                    {"tool_name": "list_hosts", "params": {}}],
        results=[None, {"isError": True, "content": "backend unreachable"}],
    )
    assert memory.lookup("t1", "u1", "create a script") is None


def test_failed_calls_are_left_out_of_the_entry(mem_root):
    memory_step.record_turn(
        team_id="t1", user_id="u1", question="create a script", answer="Created it.",
        tool_calls=[{"tool_name": "list_hosts", "params": {}},
                    {"tool_name": "manage_script", "params": {"script_name": "nightly"}}],
        results=[{"success": False, "error": "timeout"}, {"script_id": "abc"}],
    )
    entry = memory.lookup("t1", "u1", "create a script")
    assert entry is not None and entry.tools == ("manage_script",)


def test_a_live_operation_is_never_answered_from_the_memory(mem_root):
    """The FAQ's own rule: a recollection of a command is not the command."""
    memory.record(team_id="t1", user_id="u1", question="take control of stb3", answer="Took it.",
                  tools=["take_control"])
    decision = memory_step.step("take control of stb3", _session(), team_id="t1", user_id="u1",
                                session_id="s1")
    assert decision.answer is None
    assert decision.source == memory_step.SOURCE_NONE


def test_the_same_question_again_in_the_session_runs_for_real(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.",
                  tools=["manage_script"])
    session = _session()
    first = memory_step.step("create a script", session, team_id="t1", user_id="u1", session_id="s1")
    second = memory_step.step("create a script", session, team_id="t1", user_id="u1", session_id="s1")
    assert first.answer is not None
    assert second.answer is None


def test_again_after_a_recall_resolves_to_the_recalled_question(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created it.",
                  tools=["manage_script"])
    session = _session()
    memory_step.step("create a script", session, team_id="t1", user_id="u1", session_id="s1")
    assert memory_step.resolve_rerun("Again!", session) == "create a script"
    assert memory_step.resolve_rerun("again", session) is None   # consumed once


def test_again_without_a_recall_is_left_alone(mem_root):
    assert memory_step.resolve_rerun("again", _session()) is None


@pytest.mark.parametrize("question,live", [
    ("create a script", False),
    ("create a user interface", False),
    ("cap 5", False),
    ("show me the script I made yesterday", False),
    ("send cmd to stb", True),
    ("take control of stb3", True),
    ("is stb3 free", True),
    ("restart the host", True),
    ("run the nightly script", True),
    ("create a user interface named bench_ui for an android_tv device", False),
    ("create a virtual script named SC_X and run it on stb3", True),
])
def test_what_counts_as_a_live_operation(question, live):
    assert memory_step.is_live_operation(question) is live


def test_optin_mode_runs_only_for_users_who_switched_it_on(mem_root, monkeypatch):
    """On demand (owner, 2026-10-25): nobody pays for the memory unless they asked for it."""
    monkeypatch.setenv("ATLAS_MEMORY", "optin")
    assert memory.enabled_for("t1", "u1") is False
    assert memory.record(team_id="t1", user_id="u1", question="create a script", answer="a") is None
    assert memory.set_enabled("t1", "u1") is True
    assert memory.enabled_for("t1", "u1") is True
    assert memory.enabled_for("t1", "u2") is False
    assert memory.set_enabled("t1", "u1", False) is True
    assert memory.enabled_for("t1", "u1") is False


@pytest.mark.parametrize("shared", sorted(memory.SHARED_USER_IDS))
def test_a_shared_login_has_no_memory(mem_root, shared):
    """Auto-sign, the API key, open mode: one id for everybody, so a memory would pool them."""
    assert memory.user_dir("t1", shared) is None
    assert memory.set_enabled("t1", shared) is False
    assert memory.status("t1", shared)["reason"] == "no_user"


def test_status_reports_the_switch_and_what_is_kept(mem_root, monkeypatch):
    monkeypatch.setenv("ATLAS_MEMORY", "optin")
    assert memory.status("t1", "u1")["enabled"] is False
    memory.set_enabled("t1", "u1")
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="a")
    memory.record(team_id="t1", user_id="u1", question="cap 5", answer="b")
    info = memory.status("t1", "u1")
    assert info["available"] and info["enabled"]
    assert (info["days"], info["entries"], info["retention_days"]) == (1, 2, 30)
    monkeypatch.setenv("ATLAS_MEMORY", "off")
    assert memory.status("t1", "u1")["reason"] == "off"


def test_ids_in_a_tool_text_answer_are_kept():
    """save_virtual_script answers in text, with the id only there and in virtual_script_id."""
    result = {"content": [{"type": "text", "text": "Virtual script 'SC_X' created (id 3f2a1b4c-0000-4000-8000-1234567890ab)."}],
              "isError": False, "virtual_script_id": "3f2a1b4c-0000-4000-8000-1234567890ab"}
    found = memory._artefacts_from({"name": "SC_X", "source": "..."}, result)
    assert "name=SC_X" in found
    assert "virtual_script_id=3f2a1b4c-0000-4000-8000-1234567890ab" in found
    assert "id=3f2a1b4c-0000-4000-8000-1234567890ab" in found


def test_a_turn_that_only_looked_is_not_remembered(mem_root):
    """'cap 5' searched the docs and read an empty transcript: nothing to recall (2026-10-25)."""
    memory_step.record_turn(
        team_id="t1", user_id="u1", question="cap 5", answer="no transcript available",
        tool_calls=[{"tool_name": "search_docs", "params": {}}, {"tool_name": "read_doc", "params": {}},
                    {"tool_name": "get_transcript", "params": {"device_id": "device2"}}],
        results=[{}, {}, {"status": "unavailable"}],
    )
    assert memory.lookup("t1", "u1", "cap 5") is None


def test_a_turn_that_looked_then_created_is_remembered(mem_root):
    memory_step.record_turn(
        team_id="t1", user_id="u1", question="create a script", answer="Created SC_X.",
        tool_calls=[{"tool_name": "list_scripts", "params": {}},
                    {"tool_name": "save_virtual_script", "params": {"name": "SC_X"}}],
        results=[{}, {"virtual_script_id": "3f2a1b4c-0000-4000-8000-1234567890ab"}],
    )
    entry = memory.lookup("t1", "u1", "create a script")
    assert entry is not None and "save_virtual_script" in entry.tools


def test_the_artefacts_come_from_the_tools_that_acted(mem_root):
    """A script the model read as a template is not the artefact the turn produced."""
    memory_step.record_turn(
        team_id="t1", user_id="u1", question="create a script", answer="Created SC_NEW.",
        tool_calls=[{"tool_name": "get_virtual_script", "params": {"name": "SC_OTHER"}},
                    {"tool_name": "save_virtual_script", "params": {"name": "SC_NEW"}}],
        results=[{"virtual_script_id": "11111111-0000-4000-8000-000000000000"},
                 {"virtual_script_id": "22222222-0000-4000-8000-000000000000"}],
    )
    entry = memory.lookup("t1", "u1", "create a script")
    assert "name=SC_NEW" in entry.artefacts
    assert not any("SC_OTHER" in a or "11111111" in a for a in entry.artefacts)


def test_a_memory_of_a_deleted_artefact_is_dropped_not_recalled(mem_root):
    """The script the memory names was deleted: the turn runs for real and the entry is gone."""
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="Created SC_X.",
                  tools=["save_virtual_script"], artefacts=["name=SC_X", "virtual_script_id=11111111-0000-4000-8000-000000000000"])
    entry = memory.lookup("t1", "u1", "create a script")
    assert memory_step.artefact_gone(entry, "t1", exists=lambda kind, value, team: False) == \
        "virtual_script_id=11111111-0000-4000-8000-000000000000"
    assert memory_step.artefact_gone(entry, "t1", exists=lambda kind, value, team: True) is None
    assert memory.forget_key("t1", "u1", entry.key) == 1
    assert memory.lookup("t1", "u1", "create a script") is None


def test_a_lookup_error_keeps_the_memory(mem_root):
    memory.record(team_id="t1", user_id="u1", question="q", answer="a", tools=["save_virtual_script"],
                  artefacts=["virtual_script_id=11111111-0000-4000-8000-000000000000"])
    entry = memory.lookup("t1", "u1", "q")

    def boom(kind, value, team):
        raise RuntimeError("db down")
    assert memory_step.artefact_gone(entry, "t1", exists=boom) is None


def test_forget_key_keeps_the_other_entries(mem_root):
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="a", tools=["x"])
    memory.record(team_id="t1", user_id="u1", question="cap 5", answer="b", tools=["y"])
    memory.forget_key("t1", "u1", memory.question_key("create a script"))
    assert memory.lookup("t1", "u1", "cap 5") is not None
    assert memory.lookup("t1", "u1", "create a script") is None


def test_status_counts_the_recalls(mem_root):
    memory.set_enabled("t1", "u1")
    memory.record(team_id="t1", user_id="u1", question="create a script", answer="a", tools=["save_virtual_script"])
    decision = memory_step.step("create a script", _session(), team_id="t1", user_id="u1", session_id="s1")
    memory_step.record_log(decision, team_id="t1", user_id="u1")
    assert memory.status("t1", "u1")["recalls"] == 1
