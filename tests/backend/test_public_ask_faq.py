"""Public Ask prepared FAQ + doc retrieval (no server, no DB, no model).

The widget answers from agent_faq rows flagged public before it asks a model; these tests pin the
matching rules (what must hit, what must miss) and the doc-excerpt retrieval that feeds the model.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))

from backend_server.src.agent import faqs, faqs_public  # noqa: E402
from shared.src.lib.database import agent_faq_db  # noqa: E402

SEED = json.loads((REPO / "scripts" / "agent" / "public_faq_seed.json").read_text(encoding="utf-8"))


def _rows():
    return [{
        "id": f"{e['group']}-{e['lang']}", "question_text": e["question"], "normalised_question": faqs.normalize(e["question"]),
        "aliases": e["aliases"], "short": e["short"], "long": e["long"], "sources": e["sources"],
        "tags": ["public", f"lang:{e['lang']}", f"group:{e['group']}"], "count": 0,
    } for e in SEED]


@pytest.fixture(autouse=True)
def public_index(monkeypatch):
    monkeypatch.setattr(agent_faq_db, "load_public", lambda limit=1000: _rows())
    faqs_public.reset()
    yield
    faqs_public.reset()


@pytest.mark.parametrize("question,group", [
    ("how is fixnet working", "fixnet"),
    ("How does Fixnet work?", "fixnet"),
    ("what is fixnet for", "fixnet"),
    ("Does it work with IR remotes?", "ir-remotes"),
    ("does VirtualPyTest work with infrared remotes", "ir-remotes"),
    ("How is it priced?", "pricing"),
    ("is it free", "pricing"),
    ("Which devices are supported?", "devices"),
    ("What devices are supported?", "devices"),
    ("Does VirtualPyTest support Android TV?", "devices"),
    ("comment fonctionne fixnet", "fixnet"),
    ("C'est quoi Fixnet ?", "fixnet"),
    ("Combien ça coûte ?", "pricing"),
])
def test_hits(question, group):
    hit = faqs_public.lookup(question)
    assert hit is not None, question
    assert f"group:{group}" in hit.entry.tags


@pytest.mark.parametrize("question", [
    "Does it support Apple TV with Siri remote voice commands?",
    "how is fixnet working with a Cisco gateway on port 5060",
    "what is the capital of France",
    "how do I write a pancake recipe",
    "Does it work with Roku?",
])
def test_misses_go_to_the_model(question):
    assert faqs_public.lookup(question) is None


WIDGET_CHIPS = {   # the suggested-question chips of every widget locale (virtualpytest.com/locales.json)
    "en": ["Does it work with IR remotes?", "How is it priced?", "Which devices are supported?"],
    "fr": ["Est-ce compatible avec les télécommandes IR ?", "Quels sont les tarifs ?", "Quels appareils sont pris en charge ?"],
    "es": ["¿Funciona con mandos IR?", "¿Cuánto cuesta?", "¿Qué dispositivos son compatibles?"],
    "de": ["Funktioniert es mit IR-Fernbedienungen?", "Wie ist der Preis?", "Welche Geräte werden unterstützt?"],
    "zh-CN": ["它可以与红外遥控器一起使用吗？", "它的定价如何？", "支持哪些设备？"],
    "hi": ["क्या यह आईआर रिमोट के साथ काम करता है?", "इसकी कीमत कैसी है?", "कौन से उपकरण समर्थित हैं?"],
}


@pytest.mark.parametrize("lang,question", [(l, q) for l, qs in WIDGET_CHIPS.items() for q in qs])
def test_every_suggested_chip_is_an_instant_hit_in_its_own_language(lang, question):
    hit = faqs_public.lookup(question, lang)
    assert hit is not None, (lang, question)
    assert f"lang:{lang.split('-')[0]}" in hit.entry.tags


def test_language_sibling_answers_in_the_widget_language():
    assert "Fixnet est la façon" in faqs_public.lookup("how is fixnet working", "fr").answer
    assert "Fixnet is how" in faqs_public.lookup("how is fixnet working", "en").answer
    assert "Fixnet is how" in faqs_public.lookup("how is fixnet working", "zh-CN").answer   # no zh row: the match stands


def test_only_public_rows_are_loaded_by_the_db_module(monkeypatch):
    calls = {}

    class Q:
        def __getattr__(self, name):
            def call(*a, **k):
                calls.setdefault(name, []).append((a, k))
                return self
            return call

        def execute(self):
            class R:
                data = []
            return R()

    class Client:
        def table(self, name):
            calls["table"] = name
            return Q()

    monkeypatch.setattr(agent_faq_db, "_supabase", lambda: Client())
    monkeypatch.undo()  # keep the autouse patch out of the way for the real function
    monkeypatch.setattr(agent_faq_db, "_supabase", lambda: Client())
    agent_faq_db.load_public(10)
    assert ("public", True) in [a for a, _ in calls["eq"]]
    assert ("live", True) in [a for a, _ in calls["eq"]]


def test_empty_store_never_raises(monkeypatch):
    monkeypatch.setattr(agent_faq_db, "load_public", lambda limit=1000: [])
    faqs_public.reset()
    assert faqs_public.lookup("how is fixnet working") is None


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("ATLAS_FAQ", "off")
    assert faqs_public.lookup("how is fixnet working") is None


def test_seed_is_docs_only():
    """Public rows may not carry hosts, IPs, env blocks or secrets, and every source must exist in docs/."""
    import re
    bad = re.compile(r"(\b\d{1,3}(\.\d{1,3}){3}\b|/dev/|\.env|password|token|secret|sudo|vpt-)", re.I)
    for e in SEED:
        for field in ("question", "short", "long", *e["aliases"]):
            assert not bad.search(field), (e["group"], field[:60])
        assert len(e["short"]) <= 320
        for src in e["sources"]:
            assert (REPO / "docs" / src).is_file(), src
    assert {e["group"] for e in SEED if e["lang"] == "en"} == {e["group"] for e in SEED if e["lang"] == "fr"}


def test_doc_context_finds_the_fixnet_doc_and_ignores_unrelated():
    from backend_server.src.agent import public_docs_context as ctx
    found = ctx.find("how is fixnet working with the modems")
    assert found.grounded and "agent/devices/FIXNET_FX_MODEMS.md" in found.sources
    assert not ctx.find("what is the capital of France").grounded
    assert not any(s.path.startswith(("tasks/", "bugs/", "release_note/")) for s in found.sections)
    assert len(found.render()) <= ctx.MAX_CONTEXT_CHARS + 200


# --------------------------------------------------------------------------- route flow with a fake model

class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Hop:
    model = "fake"

    def __init__(self, replies, calls):
        self.replies, self.calls = replies, calls

    def client(self, timeout=None):
        return self


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    from flask import Flask
    from backend_server.src.routes import server_public_ask_routes as r

    monkeypatch.setattr(r, "CACHE_FILE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(r, "LOG_FILE", str(tmp_path / "log.jsonl"))
    r._cache.clear()
    r._cache_loaded = True
    monkeypatch.setattr(r.ai_router, "is_available", lambda usage: True)
    monkeypatch.setattr(r.ai_router, "record_avoided", lambda *a, **k: None)
    monkeypatch.setattr(r.tracing, "trace_call", lambda **k: None)
    monkeypatch.setattr(r, "_rate_limited", lambda ip: False)
    app = Flask(__name__)
    app.register_blueprint(r.server_public_ask_bp)
    return app.test_client(), r


def _install_model(monkeypatch, r, replies):
    calls = []

    def traced_create(client, hop, attempts, **kw):
        calls.append(kw)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _Block(content=reply)

    monkeypatch.setattr(r.tracing, "traced_create", traced_create)
    monkeypatch.setattr(r.ai_router, "resolve", lambda usage: _Block(primary=_Hop(replies, calls)))
    return calls


def _ask(client, question, **extra):
    return client.post("/server/public/ask", json={"question": question, **extra}, headers={"Origin": "https://virtualpytest.com"})


def test_route_faq_hit_makes_no_model_call(app_client, monkeypatch):
    client, r = app_client
    calls = _install_model(monkeypatch, r, [])
    body = _ask(client, "how is fixnet working").get_json()
    assert body["success"] and body["faq"] and body["cached"] and not calls
    assert "agent/devices/FIXNET_FX_MODEMS.md" in body["sources"]
    assert "**" not in body["answer"]


def test_route_grounded_miss_is_one_call_with_excerpts_in_the_prompt(app_client, monkeypatch):
    client, r = app_client
    calls = _install_model(monkeypatch, r, [[_Block(type="text", text="The modems are ringing lines.")]])
    body = _ask(client, "which AT command picks up the called modem on fixnet").get_json()
    assert body["success"] and body["answer"].startswith("The modems")
    assert len(calls) == 1
    assert "Documentation excerpts" in calls[0]["messages"][0]["content"]
    assert body["sources"] and body["sources"][0].endswith(".md")


def test_route_off_topic_marker_has_no_sources_and_is_not_cached(app_client, monkeypatch):
    client, r = app_client
    _install_model(monkeypatch, r, [[_Block(type="text", text="OFF_TOPIC: I only answer questions about VirtualPyTest.")]])
    body = _ask(client, "what is the capital of France").get_json()
    assert body["success"] and body["sources"] == [] and body["answer"].startswith("I only answer")
    assert r._cache == {}


def test_route_model_failure_serves_the_top_excerpt_within_budget(app_client, monkeypatch):
    client, r = app_client
    _install_model(monkeypatch, r, [TimeoutError("read timeout")])
    body = _ask(client, "which AT command picks up the called modem on fixnet").get_json()
    assert body["success"] and body["partial"] and body["sources"]
    assert r._cache == {}          # a partial answer is never remembered


def test_route_keeps_guards(app_client):
    client, _ = app_client
    assert client.post("/server/public/ask", json={"question": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert _ask(client, "").status_code == 400


# --------------------------------------------------------------------------- learned answers

def test_learned_answer_is_a_hit_on_the_second_ask_and_goes_stale_with_its_docs(monkeypatch):
    import time as _t
    saved = []

    def fake_upsert(**kw):
        saved.append(kw)
        return "learned-1"

    monkeypatch.setattr(agent_faq_db, "upsert_learned_public", fake_upsert)
    q = "which AT command picks up the called modem on fixnet"
    assert faqs_public.lookup(q) is None
    faqs_public.learn(q, "The modem is put in voice mode first, then ATA picks up.", ["agent/devices/FIXNET_FX_MODEMS.md"])
    for _ in range(50):
        if saved and faqs_public.lookup(q):
            break
        _t.sleep(0.05)
    hit = faqs_public.lookup(q)
    assert hit and "voice mode" in hit.answer and saved[0]["manifest_hash"]
    # near-identical re-ask still hits, a loose paraphrase does not (learned entries are strict)
    assert faqs_public.lookup("Which AT command picks up the called modem on Fixnet?")
    assert faqs_public.lookup("fixnet modem picks up") is None
    # the cited doc changed: the stored answer is no longer served
    monkeypatch.setattr(faqs_public, "manifest_hash", lambda sources: "changed")
    assert faqs_public.lookup(q) is None


def test_learn_ignores_declines_and_empty_sources(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_faq_db, "upsert_learned_public", lambda **kw: calls.append(kw))
    faqs_public.learn("what is the capital of France", "I only answer questions about VirtualPyTest.", [])
    faqs_public.learn("", "x", ["faq/README.md"])
    import time as _t
    _t.sleep(0.2)
    assert calls == []


def test_route_remembers_a_model_answer_for_the_next_ask(app_client, monkeypatch):
    import time as _t
    client, r = app_client
    stored = []
    monkeypatch.setattr(agent_faq_db, "upsert_learned_public", lambda **kw: stored.append(kw) or "id-1")
    _install_model(monkeypatch, r, [[_Block(type="text", text="Voice mode first, then ATA.")]])
    q = "which AT command picks up the called modem on fixnet"
    assert not _ask(client, q).get_json()["cached"]
    for _ in range(50):
        if stored:
            break
        _t.sleep(0.05)
    r._cache.clear()                       # a restart / another process: only the database remembers
    again = _ask(client, q).get_json()
    assert again["faq"] and "Voice mode" in again["answer"]


def test_route_timeout_without_excerpt_is_a_503_not_a_500(app_client, monkeypatch):
    client, r = app_client
    _install_model(monkeypatch, r, [TimeoutError("read timeout")])
    monkeypatch.setattr(r.public_docs_context, "find", lambda q: r.public_docs_context.Context([], False))
    response = _ask(client, "can I control a windows pc remotely")
    assert response.status_code == 503 and not response.get_json()["success"]


def test_route_stops_reading_at_half_budget_and_forces_a_final_answer(app_client, monkeypatch):
    import time as _t
    client, r = app_client
    monkeypatch.setattr(r, "WALL_SECONDS", 6.0)
    monkeypatch.setattr(r.public_docs_context, "find", lambda q: r.public_docs_context.Context([], False))
    calls = _install_model(monkeypatch, r, [
        [_Block(type="tool_use", id="t1", name="read_doc", input={"path": "faq/README.md"})],
        [_Block(type="text", text="Yes, through the desktop controller.")],
    ])
    real = r.tracing.traced_create

    def slow(client_, hop, attempts, **kw):
        if len(calls) == 0:
            _t.sleep(3.2)            # the first turn eats more than half of the 6 s budget
        return real(client_, hop, attempts, **kw)

    monkeypatch.setattr(r.tracing, "traced_create", slow)
    body = _ask(client, "can I control a windows pc remotely").get_json()
    assert body["success"] and body["answer"].startswith("Yes") and len(calls) == 2
    assert not calls[1]["tools"]      # the second call is the forced, tool-less final answer
