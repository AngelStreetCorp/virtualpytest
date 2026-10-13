"""TASK-55 step 3: Nightwatch asks Jev about freeze alerts with host facts, in shadow only."""
from datetime import datetime, timedelta, timezone

import pytest

from backend_server.src.agent.core import nightwatch_handler as nw
from shared.src.lib.ai import decisions, freeze_triage, router

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
FACTS = {"version": 1, "device_model": "H96_MAX", "n_frames": 3, "facts": ["0% changed"],
         "text": {"read_first": "Entdecken Filme", "read_last": "Entdecken Filme"}}


def _alert(id="a1", kind="freeze", facts=FACTS, **kw):
    meta = {"jev_facts": dict(facts)} if facts else {}
    return {"id": id, "host_name": "vpt-pi1", "device_id": "device3", "device_name": "stb3",
            "incident_type": kind, "start_time": T0.isoformat(), "end_time": None, "metadata": meta, **kw}


class Jev:
    def __init__(self, monkeypatch, choice="freeze", ui=0.9, enabled=True):
        self.calls, self.choose_refs = [], []
        monkeypatch.setattr(decisions, "enabled", lambda usage=None: enabled)
        monkeypatch.setattr(router, "resolve", lambda usage, team=None, **k: "resolution")

        def choose(resolution, state, options, **kw):
            self.calls.append("choose")
            self.choose_refs.append(kw["refs"])
            return {"success": True, "choice": choice, "confidence": 0.8, "cost": 0.00002, "decision_id": "d1"}

        def decide(resolution, state, questions, **kw):
            self.calls.append("decide")
            return {"success": True, "answers": {"ui": {"noul": ui}}, "cost": 0.00002, "decision_id": "d2"}

        monkeypatch.setattr(decisions, "choose", choose)
        monkeypatch.setattr(decisions, "decide", decide)


def _handler(monkeypatch, mode=None):
    if mode is None:
        monkeypatch.delenv("ALERT_JEV_MODE", raising=False)
    else:
        monkeypatch.setenv("ALERT_JEV_MODE", mode)
    return nw.NightwatchHandler()


def test_shadow_asks_once_per_alert_and_logs(monkeypatch, capsys):
    jev = Jev(monkeypatch, choice="freeze", ui=0.9)
    h = _handler(monkeypatch)
    alert = _alert()
    before = dict(alert)
    h._jev_shadow(alert)
    h._jev_shadow(alert)  # next poll cycle
    assert jev.calls == ["choose", "decide"]
    assert jev.choose_refs[0] == {"alert_id": "a1", "host_name": "vpt-pi1", "device_id": "device3",
                                  "device_model": "H96_MAX", "mode": "shadow"}
    assert alert == before
    assert "jev shadow a1 vpt-pi1/device3: freeze conf=0.80 ui=0.90 -> dismiss" in capsys.readouterr().out


def test_real_freeze_is_kept(monkeypatch, capsys):
    Jev(monkeypatch, choice="freeze", ui=0.1)
    _handler(monkeypatch)._jev_shadow(_alert())
    assert "-> keep" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["off", "gate", "bogus"])
def test_mode_other_than_shadow_is_off(monkeypatch, mode):
    jev = Jev(monkeypatch)
    _handler(monkeypatch, mode)._jev_shadow(_alert())
    assert jev.calls == []


def test_unknown_mode_is_logged_once(monkeypatch, capsys):
    Jev(monkeypatch)
    h = _handler(monkeypatch, "gate")
    h._jev_shadow(_alert())
    h._jev_shadow(_alert("a2"))
    assert capsys.readouterr().out.count("ALERT_JEV_MODE='gate' is not implemented") == 1


def test_jev_disabled_asks_nothing(monkeypatch):
    jev = Jev(monkeypatch, enabled=False)
    _handler(monkeypatch)._jev_shadow(_alert())
    assert jev.calls == []


def test_alerts_without_facts_or_other_types_are_ignored(monkeypatch):
    jev = Jev(monkeypatch)
    h = _handler(monkeypatch)
    h._jev_shadow(_alert(facts=None))
    h._jev_shadow(_alert("a2", kind="blackscreen"))
    assert jev.calls == []


def test_camera_is_kept_whatever_jev_says(monkeypatch, capsys):
    jev = Jev(monkeypatch, choice="still", ui=0.9)
    _handler(monkeypatch)._jev_shadow(_alert(facts={**FACTS, "device_model": "camera"}))
    assert jev.calls == ["choose"]  # no words to read on a camera
    assert "-> keep" in capsys.readouterr().out


def test_failure_and_disabled_reply_are_logged_and_ignored(monkeypatch, capsys):
    Jev(monkeypatch)
    monkeypatch.setattr(decisions, "choose", lambda *a, **k: {"success": False, "error": "timeout"})
    _handler(monkeypatch)._jev_shadow(_alert())
    assert "failed, ignored (timeout)" in capsys.readouterr().out
    monkeypatch.setattr(decisions, "choose", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _handler(monkeypatch)._jev_shadow(_alert("a2"))
    assert "failed, ignored (boom)" in capsys.readouterr().out


def test_run_once_asks_even_when_a_rule_skips_and_never_writes_jev_fields(monkeypatch):
    jev = Jev(monkeypatch)
    h = _handler(monkeypatch)
    alert = _alert(device_name="hls_bipbop")  # test_stream rule skips it
    writes = []
    monkeypatch.setattr(h, "_expire_old", lambda now: None)
    monkeypatch.setattr(h, "_pending", lambda now: [alert])
    monkeypatch.setattr(h, "_last_verdicts", lambda now: {})
    monkeypatch.setattr(h, "_calls_today", lambda now: 0)
    monkeypatch.setattr(h, "_write", lambda alert_id, fields: writes.append(fields) or True)
    assert h.run_once() == 1 and h.run_once() == 1
    assert jev.calls == ["choose", "decide"]
    assert len(writes) == 2 and all(w["check_type"] == nw.SKIP_CHECK_TYPE for w in writes)


def test_ask_returns_cost_and_decision_ids():
    out = freeze_triage.ask("r", FACTS, "H96_MAX", {"alert_id": "a"},
                            lambda *a, **k: {"success": True, "choice": "freeze", "confidence": 0.7,
                                             "cost": 0.1, "decision_id": "d1"},
                            lambda *a, **k: {"success": True, "answers": {"ui": {"noul": 0.2}},
                                             "cost": 0.2, "decision_id": "d2"})
    assert out["triage"] == "keep" and out["decision_ids"] == ["d1", "d2"] and out["cost"] == pytest.approx(0.3)


def test_fresh_freeze_alert_waits_for_host_facts(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from backend_server.src.agent.core import nightwatch_handler as nh
    monkeypatch.setenv("ALERT_JEV_MODE", "shadow")
    h = nh.NightwatchHandler()
    now = datetime.now(timezone.utc)
    fresh = {"id": "a", "incident_type": "freeze", "metadata": {}, "created_at": (now - timedelta(seconds=5)).isoformat()}
    old = {**fresh, "id": "b", "created_at": (now - timedelta(seconds=120)).isoformat()}
    with_facts = {**fresh, "id": "c", "metadata": {"jev_facts": {"facts": []}}}
    audio = {**fresh, "id": "d", "incident_type": "audio_loss"}
    assert h._awaiting_jev_facts(fresh, now) is True
    assert h._awaiting_jev_facts(old, now) is False
    assert h._awaiting_jev_facts(with_facts, now) is False
    assert h._awaiting_jev_facts(audio, now) is False
    monkeypatch.setenv("ALERT_JEV_MODE", "off")
    assert nh.NightwatchHandler()._awaiting_jev_facts(fresh, now) is False
