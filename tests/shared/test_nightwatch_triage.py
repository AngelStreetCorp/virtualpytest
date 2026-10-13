"""Alert triage (vpt-discard-incidents): cost rules, verdict parsing, no Redis on the producer."""
import inspect
from datetime import datetime, timedelta, timezone

from backend_server.src.agent.core import nightwatch_handler as nw
from shared.src.lib.ai import usages
from shared.src.lib.database import alerts_db

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


FRAME = {"r2_images": {"thumbnail_r2_paths": ["alerts/freeze/c1/t_0.jpg"]}}


def _alert(start, end=None, host="vpt-pi1", device="device3", kind="freeze", **kw):
    return dict(id=kw.get("id", "a1"), host_name=host, device_id=device, incident_type=kind,
                start_time=start.isoformat(), end_time=end.isoformat() if end else None,
                metadata=kw.get("metadata", FRAME), device_name=kw.get("device_name", "stb3"))


def _handler(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return nw.NightwatchHandler()


def test_alert_without_frame_is_kept_for_a_human(monkeypatch):
    # BUG-0492: the image-only vision route failed on every frameless alert and blocked triage for all.
    h = _handler(monkeypatch)
    rule, detail = h.decide(_alert(T0, metadata={}), {}, 0)
    assert rule == "no_frame" and "human" in detail
    assert h.decide(_alert(T0), {}, 0) is None


def test_short_alert_is_skipped(monkeypatch):
    h = _handler(monkeypatch)
    assert h.decide(_alert(T0, T0 + timedelta(seconds=10)), {}, 0)[0] == "short"
    assert h.decide(_alert(T0, T0 + timedelta(seconds=45)), {}, 0) is None
    assert h.decide(_alert(T0), {}, 0) is None  # still active past the wait: analysed


def test_repeat_within_window_points_at_first_verdict(monkeypatch):
    h = _handler(monkeypatch, ALERT_DISCARD_REPEAT_WINDOW_H=6)
    last = {("vpt-pi1", "device3", "freeze"): {"id": "first", "start_time": T0.isoformat(), "discard": True}}
    rule, detail = h.decide(_alert(T0 + timedelta(hours=2)), last, 0)
    assert rule == "repeat" and "first" in detail and "discard" in detail
    assert h.decide(_alert(T0 + timedelta(hours=7)), last, 0) is None
    # another type or device is not a repeat
    assert h.decide(_alert(T0 + timedelta(hours=2), kind="audio_loss"), last, 0) is None
    assert h.decide(_alert(T0 + timedelta(hours=2), device="device4"), last, 0) is None


def test_test_stream_freeze_never_goes_to_the_model(monkeypatch):
    h = _handler(monkeypatch)
    assert h.decide(_alert(T0, device="hls_bipbop_4x3", device_name="hls_bipbop_4x3"), {}, 0)[0] == "test_stream"
    assert h.decide(_alert(T0, kind="blackscreen", device_name="Smoke Loop Local"), {}, 0)[0] == "test_stream"
    # audio on a test stream still goes to the model
    assert h.decide(_alert(T0, kind="audio_loss", device_name="HLS bipbop"), {}, 0) is None


def test_daily_cap(monkeypatch):
    h = _handler(monkeypatch, ALERT_DISCARD_DAILY_MAX=5)
    assert h.decide(_alert(T0), {}, 4) is None
    assert h.decide(_alert(T0), {}, 5)[0] == "daily_cap"


def test_parse_verdict():
    assert nw.parse_verdict('{"verdict": "expected", "reason": "menu"}') == ("expected", "menu")
    assert nw.parse_verdict('```json\n{"verdict":"REAL","reason":"x"}\n```') == ("real", "x")
    assert nw.parse_verdict('{"verdict": "maybe"}') is None
    assert nw.parse_verdict("no json") is None
    assert set(nw.VERDICT_DISCARD) == {"real", "expected", "false_alarm"}
    assert nw.VERDICT_DISCARD["real"] is False


def test_image_path_per_alert_shape():
    freeze = {"metadata": {"r2_images": {"thumbnail_r2_paths": ["alerts/freeze/c1/t_0.jpg", "x"]}}}
    audio = {"metadata": {"r2_images": {"thumbnail_r2_path": "alerts/audio_loss/c1/s.jpg"}}}
    assert nw.alert_image_path(freeze) == "alerts/freeze/c1/t_0.jpg"
    assert nw.alert_image_path(audio) == "alerts/audio_loss/c1/s.jpg"
    assert nw.alert_image_path({"metadata": {}}) is None


def test_prompt_carries_the_facts():
    a = _alert(T0, metadata={"freeze_event_duration_ms": 90000, "mean_volume_db": -91.0,
                             "motion": {"state": "static", "pct": 0.0}}, device="host",
               device_name="labox-web_Host")
    p = nw.build_prompt(a, 12, has_image=False, now=T0 + timedelta(seconds=40))
    assert "90 s" in p and "-91.0 dB" in p and "previous 24 h: 12" in p
    assert "desktop" in p and "no frame was uploaded" in p


def test_usage_is_registered_as_cheap_json_vision():
    u = usages.get(nw.USAGE)
    assert u.parent == "vision" and u.output == "json" and u.thinking == "off"


def test_create_alert_never_touches_redis():
    src = inspect.getsource(alerts_db.create_alert)
    assert "redis" not in src.lower() and "queue_processor" not in src


def test_empty_model_answer_is_a_content_failure_not_a_global_back_off(monkeypatch):
    h = _handler(monkeypatch)
    assert h._is_content_failure("minimax-vlm: empty answer from 'minimax-vlm'")
    assert h._is_content_failure("unparseable answer")
    assert not h._is_content_failure("openrouter (openrouter) HTTP 402 for model: Insufficient credits")
    assert not h._is_content_failure("timeout")


def _run_once_with(monkeypatch, h, alert, result):
    monkeypatch.setattr(h, "_pending", lambda now: [alert])
    monkeypatch.setattr(h, "_last_verdicts", lambda now: {})
    monkeypatch.setattr(h, "_calls_today", lambda now: 0)
    monkeypatch.setattr(h, "_repeats_24h", lambda a: 0)
    monkeypatch.setattr(h, "_expire_old", lambda now: None)
    monkeypatch.setattr(h, "_jev_shadow", lambda a: None)
    monkeypatch.setattr(h, "_awaiting_jev_facts", lambda a, n: False)
    monkeypatch.setattr(nw, "classify", lambda *a, **k: result)
    skipped = []
    monkeypatch.setattr(h, "_skip", lambda alert, rule, detail: skipped.append(rule))
    h.run_once()
    return skipped


def test_two_empty_answers_skip_that_alert_and_never_block_the_others(monkeypatch):
    h = _handler(monkeypatch)
    alert = _alert(T0)
    empty = {"success": False, "reason": "minimax-vlm: empty answer from 'minimax-vlm'", "tokens": {}}
    assert _run_once_with(monkeypatch, h, alert, empty) == []        # first try: stays for a retry
    assert not h._model_blocked() and h._backoff_s == 0              # and no global back-off
    assert _run_once_with(monkeypatch, h, alert, empty) == ["model_empty"]   # second: given up on
    assert not h._model_blocked()


def test_credit_failure_still_blocks_every_alert(monkeypatch):
    h = _handler(monkeypatch)
    res = {"success": False, "reason": "openrouter HTTP 402 Insufficient credits", "tokens": {}}
    _run_once_with(monkeypatch, h, _alert(T0), res)
    assert h._model_blocked() and h._backoff_s == 60
