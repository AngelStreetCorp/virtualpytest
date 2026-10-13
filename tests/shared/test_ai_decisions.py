"""Decision models (TASK-38/39): shared/src/lib/ai/decisions.py.

Fake HTTP only — no network, no keys, no DB.

Run: pytest tests/shared/test_ai_decisions.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, _test_dir)

from ai_routing_fixtures import clear_routing, default_snapshot, endpoint, install_routing, profile  # noqa: E402
from shared.src.lib.ai import decisions, router  # noqa: E402


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.text = body, status, str(body)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return self.body


ANSWER = {"model": "typesafe/jev-1.13-20260917", "answers": {"choice": {
    "type": "choice", "choice": "live", "confidence": 0.9, "probabilities": {"home": 0.1, "live": 0.9}}},
    "usage": {"input_tokens": 441, "output_tokens": 48, "cost": 1.85e-05}}


@pytest.fixture
def jev(monkeypatch):
    snap = default_snapshot()
    snap["endpoints"]["ep-or"] = endpoint("ep-or", name="openrouter", preset="openrouter",
                                          base_url="https://openrouter.ai/api/v1", secret_name="openrouter")
    snap["profiles"]["pf-jev"] = profile("pf-jev", name="jev", model="typesafe/jev-1.13", endpoint_id="ep-or",
                                         extra={"api": "decisions"})
    install_routing(monkeypatch, snapshot=snap)
    recorded, posts = [], []
    monkeypatch.setattr(router, "record", lambda *a, **k: recorded.append(k))
    monkeypatch.setattr(decisions, "get_secret", lambda name: "sk-test" if name == "openrouter" else None)
    import requests
    answers = [ANSWER]
    monkeypatch.setattr(requests, "post", lambda url, **kw: posts.append((url, kw)) or FakeResponse(answers.pop(0)))
    yield posts, recorded, answers
    clear_routing()


def _options():
    return [{"id": "home", "facts": "Home, tabs on top"}, {"id": "live", "facts": "Full-screen live video"}]


def test_choose_posts_the_decisions_api_and_returns_the_choice(jev):
    posts, recorded, _ = jev
    out = decisions.choose(router.resolve_profile("jev", "text.decision"), "OCR: BBC One 15:00",
                           _options(), instructions="Which screen?")
    url, kw = posts[0]
    assert url == "https://openrouter.ai/api/alpha/decisions"  # beside /api/v1, not under it
    assert kw["headers"]["Authorization"] == "Bearer sk-test"
    assert kw["json"]["model"] == "typesafe/jev-1.13"
    assert kw["json"]["questions"]["choice"]["criteria"] == {"home": "Home, tabs on top",
                                                             "live": "Full-screen live video"}
    assert out["success"] and out["choice"] == "live" and out["confidence"] == 0.9
    assert out["reason"] is None and out["cost"] == 1.85e-05
    assert out["usage"] == {"input_tokens": 441, "output_tokens": 48} and out["profile"] == "jev"
    assert recorded[0]["ok"] is True and recorded[0]["tokens_in"] == 441


def test_a_chat_profile_is_refused(jev):
    posts, _, _ = jev
    out = decisions.choose(router.resolve_profile("default", "text.decision"), "s", _options(), instructions="?")
    assert not out["success"] and "not a decision profile" in out["error"] and posts == []


def test_an_answer_outside_the_options_fails(jev):
    _, _, answers = jev
    answers[0] = {**ANSWER, "answers": {"choice": {"type": "choice", "choice": "settings", "confidence": 1}}}
    out = decisions.choose(router.resolve_profile("jev", "text.decision"), "s", _options(), instructions="?")
    assert not out["success"] and out["choice"] is None and "not one of the options" in out["error"]


def test_http_error_is_a_failed_result_and_recorded(jev, monkeypatch):
    posts, recorded, _ = jev
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kw: FakeResponse({"error": "402"}, status=402))
    out = decisions.decide(router.resolve_profile("jev", "text.decision"), "s",
                           {"q": {"type": "noul", "instructions": "?", "criteria": {"true": "a", "false": "b"}}})
    assert not out["success"] and "decisions call failed" in out["error"] and recorded[-1]["ok"] is False


@pytest.mark.parametrize("questions", [{}, {"q": {"type": "text"}}])
def test_untyped_questions_are_refused(jev, questions):
    posts, _, _ = jev
    out = decisions.decide(router.resolve_profile("jev", "text.decision"), "s", questions)
    assert not out["success"] and posts == []


def test_duplicate_option_ids_are_refused(jev):
    posts, _, _ = jev
    out = decisions.choose(router.resolve_profile("jev", "text.decision"), "s",
                           [{"id": "a"}, {"id": "a"}], instructions="?")
    assert not out["success"] and "unique" in out["error"] and posts == []


@pytest.fixture
def logged(monkeypatch):
    from shared.src.lib.database import ai_decisions_db
    rows = []
    monkeypatch.setattr(ai_decisions_db, "insert_decision", lambda row: rows.append(row) or "dec-1")
    return rows


def test_a_team_call_is_logged_with_state_answers_and_refs(jev, logged):
    out = decisions.choose(router.resolve_profile("jev", "text.decision", "team-1"), "OCR: BBC One",
                           _options(), instructions="Which screen?", refs={"alert_id": "a-1"})
    assert out["success"] and out["decision_id"] == "dec-1"
    row = logged[0]
    assert row["team_id"] == "team-1" and row["usage_key"] == "eval:text.decision"
    assert row["state"] == "OCR: BBC One"
    # The caller's refs round-trip unchanged; the host stamp (load / cpu_count / tier)
    # is merged in alongside them by decisions.stamp_refs — TASK-68.
    assert row["refs"]["alert_id"] == "a-1"
    assert row["refs"]["tier"] == "model" and "cpu_count" in row["refs"]
    assert row["answers"]["choice"]["probabilities"] == {"home": 0.1, "live": 0.9}
    assert row["ok"] is True and row["tokens_in"] == 441 and row["cost"] == 1.85e-05


def test_no_team_or_log_off_is_not_logged(jev, logged):
    _, _, answers = jev
    answers.append(ANSWER)
    out = decisions.choose(router.resolve_profile("jev", "text.decision"), "s", _options(), instructions="?")
    off = decisions.choose(router.resolve_profile("jev", "text.decision", "team-1"), "s", _options(),
                           instructions="?", log=False)
    assert out["decision_id"] is None and off["decision_id"] is None and logged == []


def test_a_mistyped_answer_fails(jev):
    _, recorded, answers = jev
    answers[0] = {**ANSWER, "answers": {"q": {"type": "choice", "choice": "x"}}}
    out = decisions.decide(router.resolve_profile("jev", "text.decision"), "s",
                           {"q": {"type": "noul", "instructions": "?"}})
    assert not out["success"] and "mistyped" in out["error"] and recorded[-1]["ok"] is False


def test_an_endpoint_without_key_is_not_called(jev, monkeypatch):
    posts, _, _ = jev
    monkeypatch.setattr(decisions, "get_secret", lambda name: None)
    out = decisions.choose(router.resolve_profile("jev", "text.decision"), "s", _options(), instructions="?")
    assert not out["success"] and "no API key" in out["error"] and posts == []


def test_set_outcome_goes_to_the_team_row(monkeypatch):
    from shared.src.lib.database import ai_decisions_db
    calls = []
    monkeypatch.setattr(ai_decisions_db, "set_outcome", lambda *a: calls.append(a) or True)
    assert decisions.set_outcome("dec-1", "team-1", {"real": True})
    assert calls == [("dec-1", "team-1", {"real": True})]


# ---- host path: hosts hold no key, the server runs the call (POST /server/ai/decide) -------

@pytest.fixture
def on_host(jev, monkeypatch):
    from shared.src.lib.ai import gateway
    posts, _, _ = jev
    sent = []
    monkeypatch.setattr(gateway, "_local_routing", False)
    monkeypatch.setattr(gateway, "_host_context", lambda context: {"host_name": "labox-web"})
    reply = {"success": True, "answers": ANSWER["answers"], "error": "", "cost": 1.85e-05, "ms": 300,
             "usage": {"input_tokens": 441, "output_tokens": 48}, "model": "typesafe/jev-1.13",
             "profile": "jev", "endpoint": "openrouter", "decision_id": "dec-9"}
    monkeypatch.setattr(gateway, "_server_post", lambda path, payload, timeout: sent.append((path, payload, timeout)) or reply)
    return sent, posts


def test_a_host_sends_the_call_to_the_server_and_never_calls_openrouter(on_host):
    sent, posts = on_host
    out = decisions.choose(router.resolve_profile("jev", "text.decision", "team-1"), {"ocr": "x"},
                           _options(), instructions="Which screen?", refs={"alert_id": "a1"})
    path, payload, timeout = sent[0]
    assert path == "/server/ai/decide" and posts == []
    assert payload["profile"] == "jev" and payload["usage"] == "text.decision" and payload["team_id"] == "team-1"
    assert payload["context"] == {"host_name": "labox-web"} and payload["refs"] == {"alert_id": "a1"}
    assert payload["questions"]["choice"]["criteria"]["live"] == "Full-screen live video"
    assert out["success"] and out["choice"] == "live" and out["decision_id"] == "dec-9"


def test_a_routed_host_call_sends_the_usage_not_a_profile(on_host):
    sent, _ = on_host
    snap_res = router.resolve_profile("jev", "text.decision")
    snap_res.layer = "default"
    decisions.decide(snap_res, "s", {"q": {"type": "noul", "instructions": "?", "criteria": {"true": "a", "false": "b"}}})
    assert sent[0][1]["profile"] is None and sent[0][1]["usage"] == "text.decision"


def test_a_server_failure_comes_back_as_a_failed_result(on_host, monkeypatch):
    from shared.src.lib.ai import gateway
    monkeypatch.setattr(gateway, "_server_post", lambda *a: (_ for _ in ()).throw(ConnectionError("down")))
    out = decisions.choose(router.resolve_profile("jev", "text.decision"), "s", _options(), instructions="?")
    assert not out["success"] and "server decide call failed" in out["error"]
    assert out["choice"] is None and out["decision_id"] is None and out["answers"] == {}


# ---- reading the log over the API (db helpers + routes), in-memory fake table --------------------

class FakeQuery:
    """Just enough of the supabase query builder over a list of dict rows."""

    def __init__(self, rows):
        self.rows, self.ops, self._update, self._range = rows, [], None, None

    @property
    def not_(self):
        self.ops.append(("negate",))
        return self

    def select(self, cols):
        self.cols = cols
        return self

    def update(self, values):
        self._update = values
        return self

    def eq(self, col, val):
        self.ops.append(("eq", col, val))
        return self

    def like(self, col, pat):
        self.ops.append(("like", col, pat))
        return self

    def is_(self, col, val):
        self.ops.append(("is", col, val))
        return self

    def gte(self, col, val):
        self.ops.append(("gte", col, val))
        return self

    def lt(self, col, val):
        self.ops.append(("lt", col, val))
        return self

    def order(self, *a, **k):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def _match(self, row):
        negate = False
        for op in self.ops:
            if op[0] == "negate":
                negate = True
                continue
            kind, col, val = op
            v = row.get(col.split("->>")[1]) if "->>" in col else row.get(col)
            if "->>" in col:
                v = (row.get("refs") or {}).get(col.split("->>")[1])
            hit = {"eq": lambda: v == val, "like": lambda: str(v).startswith(val.rstrip("*").replace("\\", "")),
                   "is": lambda: v is None, "gte": lambda: v >= val, "lt": lambda: v < val}[kind]()
            if negate:
                hit, negate = not hit, False
            if not hit:
                return False
        return True

    def execute(self):
        class R:
            pass
        out = R()
        hits = sorted((r for r in self.rows if self._match(r)), key=lambda r: r["created_at"], reverse=True)
        if self._update is not None:
            for r in hits:
                r.update(self._update)
            out.data = [dict(r) for r in hits]
            return out
        if self._range:
            hits = hits[self._range[0]:self._range[1] + 1]
        keep = self.cols.split(",") if getattr(self, "cols", None) else None
        out.data = [{k: v for k, v in r.items() if keep is None or k in keep} for r in hits]
        return out


def _row(i, team="team-1", usage="text.decision.manager", ok=True, day="2026-10-03", outcome_at=None, refs=None):
    return {"id": f"id-{i}", "team_id": team, "usage_key": usage, "ok": ok, "cost": 0.5, "state": "BIG",
            "created_at": f"{day}T10:00:{i:02d}+00:00", "outcome": None, "outcome_at": outcome_at,
            "refs": refs or {}, "questions": {}, "answers": {}}


@pytest.fixture
def table(monkeypatch):
    from shared.src.lib.database import ai_decisions_db
    rows = [
        _row(1, refs={"source": "ghosty-manager"}),
        _row(2, ok=False, outcome_at="2026-10-03T11:00:00+00:00"),
        _row(3, usage="text.decision.sherlock", day="2026-09-01"),
        _row(4, team="team-2"),
    ]
    monkeypatch.setattr(ai_decisions_db, "get_supabase", lambda: type("C", (), {"table": lambda s, t: FakeQuery(rows)})())
    return ai_decisions_db, rows


def test_query_filters_and_team_isolation(table):
    db, _ = table
    ids = lambda **kw: sorted(r["id"] for r in db.query_decisions("team-1", **kw))
    assert ids() == ["id-1", "id-2", "id-3"]                       # never team-2's row
    assert ids(usage="text.decision.") == ["id-1", "id-2", "id-3"]  # prefix
    assert ids(usage="text.decision.manager") == ["id-1", "id-2"]   # exact
    assert ids(usage="text.decision") == []                         # no trailing dot = exact
    assert ids(ok=False) == ["id-2"]
    assert ids(has_outcome=True) == ["id-2"]
    assert ids(has_outcome=False) == ["id-1", "id-3"]
    assert ids(since="2026-10-01T00:00:00+00:00") == ["id-1", "id-2"]
    assert ids(until="2026-10-01T00:00:00+00:00") == ["id-3"]
    assert ids(refs={"source": "ghosty-manager"}) == ["id-1"]
    assert db.query_decisions("team-1", limit=1, offset=1)[0]["id"] == "id-1"
    with pytest.raises(ValueError):
        db.query_decisions("team-1", refs={"a;b": "x"})


def test_query_state_only_on_request(table):
    db, _ = table
    assert "state" not in db.query_decisions("team-1")[0]
    assert db.query_decisions("team-1", include_state=True)[0]["state"] == "BIG"


def test_summary(table):
    from datetime import datetime, timezone
    db, _ = table
    out = db.summarize_decisions("team-1", now=datetime(2026, 10, 4, tzinfo=timezone.utc))
    mgr = next(u for u in out["usages"] if u["usage_key"] == "text.decision.manager")
    assert (mgr["calls"], mgr["failed"], mgr["with_outcome"], mgr["without_outcome"]) == (2, 1, 1, 1)
    assert mgr["cost"] == 1.0 and mgr["per_day"]["2026-10-03"] == 2 and len(mgr["per_day"]) == 14
    assert len(out["usages"]) == 2


def test_outcome_is_team_scoped(table):
    db, rows = table
    assert db.set_outcome("id-1", "team-1", {"label": "ok", "by": "human"})
    assert rows[0]["outcome"]["label"] == "ok"
    assert not db.set_outcome("id-4", "team-1", {"label": "x"})     # id of another team: no row
    assert rows[3]["outcome"] is None


def test_routes(table, monkeypatch):
    from flask import Flask
    from backend_server.src.routes import server_ai_routing_routes as routes
    monkeypatch.setattr(routes, "_is_valid_service_api_key", lambda: True)
    app = Flask(__name__)
    app.register_blueprint(routes.server_ai_routing_bp)
    c = app.test_client()
    assert c.get("/server/ai/decisions").status_code == 400                      # team_id required
    body = c.get("/server/ai/decisions?team_id=team-1&usage=text.decision.&ref.source=ghosty-manager").get_json()
    assert [r["id"] for r in body["decisions"]] == ["id-1"] and "state" not in body["decisions"][0]
    assert c.get("/server/ai/decisions?team_id=team-1&ok=maybe").status_code == 400
    assert c.get("/server/ai/decisions?team_id=team-1&since=garbage").status_code == 400
    assert c.get("/server/ai/decisions/summary?team_id=team-1").get_json()["success"]
    url = "/server/ai/decisions/id-1/outcome"
    assert c.post(url, json={"team_id": "team-1", "outcome": {"label": "ok", "by": "me"}}).status_code == 200
    assert c.post("/server/ai/decisions/id-4/outcome",
                  json={"team_id": "team-1", "outcome": {"label": "ok"}}).status_code == 404
    assert c.post(url, json={"team_id": "team-1", "outcome": {}}).status_code == 400
    monkeypatch.setattr(routes, "_is_valid_service_api_key", lambda: False)
    assert c.get("/server/ai/decisions?team_id=team-1").status_code == 403


def test_credits_route_reports_balance_and_key_limit(monkeypatch):
    from flask import Flask
    from backend_server.src.routes import server_ai_routing_routes as routes
    monkeypatch.setattr(routes, "_is_valid_service_api_key", lambda: True)
    monkeypatch.setattr(routes.ai_routing_db, "list_endpoints", lambda: [
        {"name": "openrouter", "preset": "openrouter", "base_url": None, "secret_name": "openrouter"},
        {"name": "local", "base_url": "http://127.0.0.1:11434", "secret_name": None}])
    monkeypatch.setattr(routes.secrets_store, "get_secret", lambda n: "sk-test" if n == "openrouter" else None)
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append((url, headers))
        data = {"total_credits": 210, "total_usage": 210.2} if url.endswith("/credits") else \
               {"limit": 10, "limit_remaining": 5.86, "usage": 21.4, "usage_daily": 0, "usage_monthly": 4.14, "is_free_tier": False}
        return FakeResponse({"data": data})
    monkeypatch.setattr(routes.requests, "get", fake_get)
    app = Flask(__name__)
    app.register_blueprint(routes.server_ai_routing_bp)
    body = app.test_client().get("/server/ai/credits").get_json()
    assert [e["endpoint"] for e in body["endpoints"]] == ["openrouter"]          # only OpenRouter endpoints
    e = body["endpoints"][0]
    assert e["balance"] == -0.2 and e["key"]["limit_remaining"] == 5.86
    assert all(h["Authorization"] == "Bearer sk-test" for _, h in seen)
    monkeypatch.setattr(routes.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
    e = app.test_client().get("/server/ai/credits").get_json()["endpoints"][0]
    assert "credits_error" in e and "key_error" in e                              # reported, never raised
