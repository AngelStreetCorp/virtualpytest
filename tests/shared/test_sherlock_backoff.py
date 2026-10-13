"""Sherlock back-off: a provider that fails is not called for 1 h, 5 h, then 24 h; a success resets it."""
from backend_server.src.agent.core import sherlock_jev
from backend_server.src.agent.core.backoff import Backoff
from backend_server.src.agent.core.sherlock_handler import SherlockHandler


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_steps_are_1h_5h_24h_then_reset():
    clock = Clock()
    b = Backoff("x", clock=clock)
    assert not b.blocked()
    assert [b.failed("402"), b.failed("402"), b.failed("402"), b.failed("402")] == [3600, 18000, 86400, 86400]
    assert b.blocked() and b.remaining_s() == 86400
    clock.t += 86401
    assert not b.blocked()
    b.succeeded()
    assert b.failed("402") == 3600


def test_env_overrides_steps(monkeypatch):
    monkeypatch.setenv("ANALYZER_BACKOFF_S", "60, 120")
    assert Backoff("x").steps == (60, 120)
    monkeypatch.setenv("ANALYZER_BACKOFF_S", "oops")
    assert Backoff("x").steps == (3600, 18000, 86400)


def test_jev_is_not_asked_while_paused(monkeypatch):
    calls = []
    monkeypatch.setattr(sherlock_jev, "BACKOFF", Backoff("jev", clock=Clock()))
    monkeypatch.setattr(sherlock_jev.decisions, "enabled", lambda usage: True)
    monkeypatch.setattr(sherlock_jev.router, "resolve", lambda usage, team: "res")
    monkeypatch.setattr(sherlock_jev.decisions, "choose",
                        lambda *a, **kw: calls.append(1) or {"success": False, "error": "HTTP 402"})
    record = {"id": "sr-1", "team_id": "t", "success": False}
    assert sherlock_jev.ask(record, "", 0.9)["success"] is False
    assert sherlock_jev.ask(record, "", 0.9) is None and len(calls) == 1


def test_llm_is_not_called_while_paused(monkeypatch):
    from backend_server.src.agent.core import sherlock_handler
    calls = []
    monkeypatch.setattr(sherlock_handler, "call_text_ai",
                        lambda **kw: calls.append(1) or {"success": False, "error": "HTTP 402"})
    h = SherlockHandler()
    h.llm_backoff = Backoff("analyzer.sherlock", clock=Clock())
    record = {"id": "sr-1", "team_id": "t", "script_name": "zap", "success": False}
    for _ in range(3):
        try:
            h._classify_with_llm(record, "")
        except RuntimeError as e:
            last = str(e)
    assert len(calls) == 1 and "paused until" in last
