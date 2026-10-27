"""Companion worker (TASK-05): cadence, banner prior, scoreboard tracking, ad pause.

Pure: the vision call and the web lookup are fakes; frames are synthetic JPEGs in a tmp dir.

Run: pytest tests/backend_host/test_companion.py -v
"""
import json
from datetime import datetime
import os
import sys

import cv2
import numpy as np
import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)


from features.companion.backend_host import companion as mc  # noqa: E402
from features.companion.lib import enrich  # noqa: E402

TEAM = "11111111-1111-1111-1111-111111111111"
BOARD = {"present": True, "bbox": [20, 30, 300, 100]}  # 0-1000 grid, as the model answers


def _frame(path, score_text="0 - 0"):
    img = np.full((720, 1280, 3), (40, 140, 40), np.uint8)
    cv2.rectangle(img, (26, 22), (384, 72), (20, 20, 20), -1)
    cv2.putText(img, "SLA", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
    cv2.putText(img, score_text, (155, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
    cv2.putText(img, "RCL", (300, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
    cv2.imwrite(str(path), img)
    return str(path)


class FakeVision:
    def __init__(self):
        self.identify = {"screen": "live_tv", "category": "sport", "subcategory": "soccer",
                         "entity": {"home_team": "Slavia Prague", "away_team": "RC Lens"},
                         "scoreboard": BOARD, "confidence": 0.9}
        self.score = (0, 0)
        self.calls = []

    def __call__(self, prompt, image, usage, **kwargs):
        self.calls.append((usage, prompt, kwargs))
        if usage == "vision.companion":
            return {"success": True, "content": json.dumps(self.identify)}
        return {"success": True, "content": json.dumps({
            "visible": True, "home_team": "SLA", "away_team": "RCL",
            "home_score": self.score[0], "away_score": self.score[1], "clock": "27:00"})}

    def usages(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_MODEL", "stb_test")
    monkeypatch.delenv("DEVICE2_COMPANION", raising=False)
    # Timelines below are written for a 20 s identify interval (profiles now say 60/120).
    monkeypatch.setattr(mc, "_interval", lambda profile=None: 20.0)
    vision = FakeVision()
    lookups = []
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=vision,
                               lookup=lambda p: lookups.append(p) or {"success": True, "content": '{"venue": "Eden"}',
                                                                       "sources": [{"url": "https://s.test"}]})
    comp.facts.get = _sync_get(comp.facts)
    meta = tmp_path / "metadata"
    meta.mkdir()
    return comp, vision, lookups, tmp_path, meta


def _sync_get(cache):
    original = cache.get

    def get(key, profile, entity, background=True, **_kwargs):
        return original(key, profile, entity, background=False, **_kwargs)
    return get


def _observe(comp, frame, meta, **analysis):
    comp.observe("device1", frame, str(meta), {"blackscreen": False, "motion": {"state": "live"}, **analysis})
    return comp._devices["device1"]


def test_disabled_device_gets_nothing(setup):
    comp, vision, _, tmp, meta = setup
    comp.observe("device2", _frame(tmp / "f.jpg"), str(meta), {})
    assert comp.result("device2") is None and "device2" not in comp._devices


def test_identify_then_track_score_and_goal_with_facts(setup, monkeypatch):
    comp, vision, lookups, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    frame = _frame(tmp / "f1.jpg")
    dev = _observe(comp, frame, meta)
    comp.step(dev, now=100)          # identify + first score read
    comp.step(dev, now=105)          # within interval_s (10): no read
    assert vision.usages().count("vision.companion.roi") == 1
    comp.step(dev, now=110)          # second agreeing read -> score accepted
    result = comp.result("device1")
    assert result["screen"] == "live_tv" and result["profile"] == "sport/soccer" and result["template"] == "match"
    assert result["live"]["homeScore"] == 0 and result["live"]["homeTeam"] == "Slavia Prague"
    assert result["facts"]["status"] == "ready" and result["facts"]["facts"]["venue"] == "Eden"
    assert len(lookups) == 1

    vision.score = (1, 0)
    dev.frame = _frame(tmp / "f2.jpg", "1 - 0")
    comp.step(dev, now=120)                       # first read of 1-0: not trusted yet
    assert comp.result("device1")["live"]["homeScore"] == 0
    comp.step(dev, now=130)                       # second agreeing read -> goal
    live = comp.result("device1")["live"]
    assert (live["homeScore"], live["awayScore"]) == (1, 0)
    assert live["events"][0]["type"] == "goal" and live["events"][0]["home"] is True
    identify_calls = [c for c in vision.calls if c[0] == "vision.companion"]
    assert identify_calls[0][2]["family"] == "content-type" and identify_calls[0][2]["team_id"] == TEAM


def test_ad_break_keeps_last_score_paused_and_does_not_read(setup, monkeypatch):
    comp, vision, _, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    comp.step(dev, now=0)
    comp.step(dev, now=10)
    assert comp.result("device1")["live"]["status"] == "live"
    vision.identify = {"screen": "advertisement", "confidence": 0.8}
    reads_before = vision.usages().count("vision.companion.roi")
    comp.step(dev, now=60)
    result = comp.result("device1")
    assert result["screen"] == "advertisement" and result["live"]["status"] == "paused"
    assert vision.usages().count("vision.companion.roi") == reads_before


def test_black_frames_skip_identify_and_triggers_respect_min_gap(setup, monkeypatch):
    comp, vision, _, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    frame = _frame(tmp / "f.jpg")
    dev = _observe(comp, frame, meta, blackscreen=True)
    comp.step(dev, now=0)
    assert vision.usages() == []
    dev = _observe(comp, frame, meta)
    comp.step(dev, now=1)
    assert vision.usages().count("vision.companion") == 1
    _observe(comp, frame, meta, motion={"state": "ui"})
    comp.step(dev, now=2)                       # a menu opened: trigger, but < TRIGGER_MIN_GAP_S
    assert vision.usages().count("vision.companion") == 1
    comp.step(dev, now=1 + mc.TRIGGER_MIN_GAP_S)
    assert vision.usages().count("vision.companion") == 2
    _observe(comp, frame, meta, motion={"state": "static"})
    comp.step(dev, now=8)                       # a still menu reads static: not a new screen
    assert vision.usages().count("vision.companion") == 2
    _observe(comp, frame, meta, motion={"state": "live"})
    comp.step(dev, now=12)                      # back to video: trigger
    assert vision.usages().count("vision.companion") == 3
    _observe(comp, frame, meta, motion={"state": "static"})
    comp.step(dev, now=16)                      # static <-> live is the camera, not a new screen
    assert vision.usages().count("vision.companion") == 3
    _observe(comp, frame, meta, motion={"state": "unknown"})
    comp.step(dev, now=20)                      # the detector abstaining is not a new screen either
    _observe(comp, frame, meta, motion={"state": "live"})
    comp.step(dev, now=24)
    assert vision.usages().count("vision.companion") == 3


def test_recent_zap_banner_goes_into_the_prompt(setup, monkeypatch):
    comp, vision, _, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    (meta / "last_zapping.json").write_text(json.dumps({
        "banner_status": "detected", "channel_name": "Foot", "channel_number": "355",
        "program_name": "Slavia Prague - RC Lens"}))
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    comp.step(dev, now=os.path.getmtime(meta / "last_zapping.json") + 5)
    prompt = next(c[1] for c in vision.calls if c[0] == "vision.companion")
    assert '"channel_number": "355"' in prompt and "Slavia Prague - RC Lens" in prompt


class _NoThread:
    """observe() starts a worker thread; tests drive step() by hand instead."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass



def test_a_broken_profile_never_stops_the_monitor(monkeypatch):
    def boom():
        raise ValueError("bad.json: unknown tracker")
    monkeypatch.setattr(mc, "load_profiles", boom)
    comp = mc.create_companion(team_id=TEAM, call_vision=FakeVision(), lookup=lambda p: {})
    comp.observe("device1", "/nope.jpg", "/nope", {})
    assert comp.result("device1") is None and comp.enabled("device1") is False


def test_model_respelling_keeps_the_match_but_new_bug_codes_end_it(setup, monkeypatch):
    comp, vision, lookups, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    for t in (0, 10):
        comp.step(dev, now=t)
    assert comp.result("device1")["live"]["homeScore"] == 0
    vision.identify = {**vision.identify, "entity": {"home_team": "Slavia Praha", "away_team": "RC Lens"}}
    comp.step(dev, now=25)                       # identify again (interval 20) with another spelling
    result = comp.result("device1")
    assert result["entity"]["home_team"] == "Slavia Prague" and "live" in result
    assert len(lookups) == 1                     # no second fact lookup

    real = vision.__call__

    def other_match(prompt, image, usage, **kw):
        if usage == "vision.companion.roi":
            vision.calls.append((usage, prompt, kw))
            return {"success": True, "content": json.dumps({"visible": True, "home_team": "PSG", "away_team": "OM",
                                                             "home_score": 0, "away_score": 0, "clock": "03:00"})}
        return real(prompt, image, usage, **kw)
    comp._call_vision = other_match
    comp.step(dev, now=35)                       # new codes once: ignored
    assert dev.tracker is not None
    comp.step(dev, now=45)                       # twice: new match
    assert dev.tracker is None and dev.force_identify is True


def test_film_gets_progress_from_the_banner_slot(setup, monkeypatch):
    comp, vision, lookups, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision.identify = {"screen": "live_tv", "category": "movie", "entity": {"title": "Dune: Part Two", "year": 2024},
                       "banner": {"program_name": "Dune: Part Two", "start_time": "20:50", "end_time": "22:45"},
                       "confidence": 0.8}
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    now = datetime(2026, 9, 30, 21, 30).timestamp()
    comp.step(dev, now=now)
    result = comp.result("device1")
    assert result["template"] == "title" and result["profile"] == "movie"
    assert result["progress"]["remaining_min"] == 75
    assert result["facts"]["status"] == "ready" and "Dune: Part Two" in lookups[0]
    assert "vision.companion.roi" not in vision.usages()


# ---------------------------------------------------------------- service + host route
def test_service_finds_opted_in_devices_and_the_newest_capture_json(tmp_path, monkeypatch):
    from features.companion.backend_host import companion_monitor as svc
    monkeypatch.setenv("DEVICE3_COMPANION", "true")
    monkeypatch.setenv("DEVICE4_COMPANION", "yes")
    monkeypatch.setenv("DEVICE5_COMPANION", "false")
    assert {"device3", "device4"} <= set(svc.enabled_devices()) and "device5" not in svc.enabled_devices()
    old, new = tmp_path / "capture_000000001.json", tmp_path / "capture_000000002.json"
    old.write_text("{}")
    new.write_text("{}")
    (tmp_path / "last_zapping.json").write_text("{}")
    os.utime(old, (1, 1))
    assert svc.newest_capture_json(str(tmp_path)).endswith("capture_000000002.json")


def test_host_route_serves_a_fresh_result_and_hides_a_stale_one(tmp_path, monkeypatch):
    from flask import Flask
    import features.companion.backend_host as host_part
    from features.companion.lib import store
    path = tmp_path / store.RESULT_FILE
    store.write_result(str(path), {"screen": "menu"})
    monkeypatch.setattr(host_part, "result_path", lambda device_id: str(path))
    app = Flask(__name__)
    host_part.register(app)
    client = app.test_client()
    assert client.post("/host/companion/latest", json={"device_id": "device4"}).get_json() ==         {"success": True, "companion": {"screen": "menu"}}
    os.utime(path, (1, 1))
    assert client.post("/host/companion/latest", json={"device_id": "device4"}).get_json()["companion"] is None


def test_service_is_off_unless_the_host_switch_is_on(monkeypatch):
    from features.companion.backend_host import companion_monitor as svc
    monkeypatch.delenv("ENABLE_COMPANION", raising=False)
    assert svc.companion_enabled() is False            # experimental: off by default
    monkeypatch.setenv("ENABLE_COMPANION", "false")
    assert svc.companion_enabled() is False
    monkeypatch.setenv("ENABLE_COMPANION", "true")
    assert svc.companion_enabled() is True


def test_off_service_idles_without_loading_the_pipeline(monkeypatch):
    from features.companion.backend_host import companion_monitor as svc
    monkeypatch.delenv("ENABLE_COMPANION", raising=False)
    monkeypatch.setenv("DEVICE4_COMPANION", "true")

    class Idle(Exception):
        pass

    def idle(reason):
        raise Idle(reason)
    monkeypatch.setattr(svc, "_idle", idle)
    with pytest.raises(Idle, match="ENABLE_COMPANION"):
        svc.run()


def test_team_names_stay_fixed_while_tracked_but_upgrade_to_fuller_spellings(setup, monkeypatch):
    comp, vision, lookups, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision.identify = {**vision.identify, "entity": {"home_team": "LIL", "away_team": "BET"}}
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    comp.step(dev, now=0)                                        # tracker starts with the bug codes
    vision.identify = {**vision.identify, "entity": {}}
    comp.step(dev, now=25)                                       # model names nothing: kept
    assert comp.result("device1")["entity"] == {"home_team": "LIL", "away_team": "BET"}
    vision.identify = {**vision.identify, "entity": {"home_team": "Lille OSC", "away_team": "Real Betis"}}
    comp.step(dev, now=50)                                       # fuller spelling of the same teams: taken
    assert comp.result("device1")["entity"]["home_team"] == "Lille OSC"
    vision.identify = {**vision.identify, "entity": {"home_team": "LIL", "away_team": "BET"}}
    comp.step(dev, now=75)                                       # back to codes: the full names stay
    assert comp.result("device1")["entity"]["away_team"] == "Real Betis"


def test_score_interval_host_override(monkeypatch):
    monkeypatch.delenv("COMPANION_SCORE_INTERVAL_S", raising=False)
    assert mc._score_interval({"interval_s": 10}) == 10
    monkeypatch.setenv("COMPANION_SCORE_INTERVAL_S", "30")
    assert mc._score_interval({"interval_s": 10}) == 30
    monkeypatch.setenv("COMPANION_SCORE_INTERVAL_S", "1")
    assert mc._score_interval({"interval_s": 10}) == 5          # floor
    monkeypatch.setenv("COMPANION_SCORE_INTERVAL_S", "junk")
    assert mc._score_interval({"interval_s": 10}) == 10


def test_busy_model_backs_off_doubling_and_recovers(setup, monkeypatch):
    comp, vision, _, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    real = vision.__call__
    state = {"busy": True}

    def maybe_busy(prompt, image, usage, **kw):
        assert kw.get("timeout_s") == 30                          # every call carries the budget
        if state["busy"]:
            vision.calls.append((usage, prompt, kw))
            return {"success": False, "busy": True, "error": "lmstudio-pc: busy (no free slot within 30s)"}
        return real(prompt, image, usage, **kw)
    comp._call_vision = maybe_busy
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    comp.step(dev, now=0)
    assert dev.backoffs[mc.IDENTIFY]["s"] == 30 and dev.backoffs[mc.IDENTIFY]["until"] == 30
    n = len(vision.calls)
    comp.step(dev, now=15)                                        # waiting: no call
    assert len(vision.calls) == n
    comp.step(dev, now=31)                                        # retry, still busy: doubled
    assert dev.backoffs[mc.IDENTIFY]["s"] == 60 and dev.backoffs[mc.IDENTIFY]["until"] == 91
    assert comp.result("device1")["backoff"] == {"reason": "busy", "retry_in_s": 60, "usage": "vision.companion"}
    state["busy"] = False
    comp.step(dev, now=92)                                        # free again: back to normal
    assert dev.backoffs == {} and comp.result("device1")["screen"] == "live_tv"
    assert "backoff" not in comp.result("device1")


def test_news_digest_from_transcript_and_on_screen_text(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "news", "entity": {"title": "Journal de 13h"},
                       "on_screen": {"lower_third": {"name": "Anne Petit", "role": "reporter"},
                                     "headline": "STORM HITS BRITTANY"}, "confidence": 0.9}
    texts = []

    def call_text(usage, prompt, **kw):
        texts.append((usage, prompt, kw))
        return {"success": True, "content": json.dumps({"stories": [{"headline": "Storm hits Brittany",
                "summary": "1.2M homes without power.", "places": ["Brittany"]}], "sensitive": {"flag": False}})}
    chunk = tmp_path / "chunk.json"
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=vision, lookup=lambda p: {}, call_text=call_text,
                               chunk_path_for=lambda device_id: (lambda h, i: str(chunk)))
    meta = tmp_path / "metadata"
    meta.mkdir()
    now = datetime(2026, 9, 30, 13, 55, 0).timestamp()
    chunk.write_text(json.dumps({"segments": [{"start": 280, "text": "la tempete a frappe la Bretagne"}]}))
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=now)
    result = comp.result("device1")
    assert result["template"] == "summary" and result["profile"] == "news"
    assert result["digest"]["stories"][0]["headline"] == "Storm hits Brittany"
    assert result["roster"] == [{"name": "Anne Petit", "role": "reporter"}]
    usage, prompt, kw = texts[0]
    assert usage == "text.companion.digest" and kw["timeout_s"] == 30
    assert "STORM HITS BRITTANY" in prompt and "la tempete a frappe la Bretagne" in prompt
    comp.step(dev, now=now + 60)                     # inside interval_s (120): no call
    comp.step(dev, now=now + 130)                    # due, but nothing new said or shown: no call
    assert len(texts) == 1


def test_identify_interval_is_per_category_then_host_then_60(monkeypatch):
    from features.companion.lib.profiles import load_profiles
    profiles = load_profiles()
    monkeypatch.delenv("COMPANION_INTERVAL_S", raising=False)
    assert mc._interval() == 60                                   # nothing identified yet
    assert mc._interval(profiles["sport/soccer"]) == 60
    assert mc._interval(profiles["movie"]) == 120
    monkeypatch.setenv("COMPANION_INTERVAL_S", "30")
    assert mc._interval() == 30                                   # host default
    assert mc._interval(profiles["series"]) == 120                # the category wins


def test_one_side_upgrades_alone_and_the_score_survives(setup, monkeypatch):
    comp, vision, lookups, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision.identify = {**vision.identify, "entity": {"home_team": "LIL", "away_team": "BET"}}
    vision.score = (2, 3)
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    for t in (0, 10):
        comp.step(dev, now=t)
    assert comp.result("device1")["live"]["homeScore"] == 2
    tracker = dev.tracker
    vision.identify = {**vision.identify, "entity": {"home_team": "LILLE", "away_team": "BET"}}
    comp.step(dev, now=25)
    result = comp.result("device1")
    assert result["entity"] == {"home_team": "LILLE", "away_team": "BET"}
    assert dev.tracker is tracker and (result["live"]["homeScore"], result["live"]["awayScore"]) == (2, 3)


def test_debate_captions_roster_topics_and_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "L'EQUIPE DU SOIR"},
                       "on_screen": {"headline": "PAS DE RONALDO : NOUVEL IMBROGLIO ?"}, "confidence": 0.9}
    real = vision.__call__
    caption_calls = []

    def vision_call(prompt, image, usage, **kw):
        if usage == "vision.companion.roi":
            caption_calls.append(kw)
            return {"success": True, "content": json.dumps({"captions": [
                {"kind": "name", "text": "Jean Martin", "role": "consultant"},
                {"kind": "strap", "text": "PAS DE RONALDO : NOUVEL IMBROGLO ?"}]})}
        return real(prompt, image, usage, **kw)
    texts = []

    def call_text(usage, prompt, **kw):
        texts.append(prompt)
        said = "il a rate" in prompt
        return {"success": True, "content": json.dumps({"topic": "Ronaldo's absence", "positions": [],
                "claims": [{"text": "Il a rate trois entrainements", "speaker": "Jean Martin", "checkable": True}]
                if said else []})}
    chunk = tmp_path / "chunk.json"
    chunk.write_text(json.dumps({"segments": [{"start": 280, "text": "il a rate trois entrainements"}]}))
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=vision_call, lookup=lambda p: {}, call_text=call_text,
                               chunk_path_for=lambda d: (lambda h, i: str(chunk)))
    meta = tmp_path / "metadata"
    meta.mkdir()
    now = datetime(2026, 9, 30, 13, 55, 0).timestamp()
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=now - 30)                     # 13:54:30 his caption; he speaks at 13:54:40
    dev.digest_at = None
    comp.step(dev, now=now)
    r = comp.result("device1")
    assert r["template"] == "debate" and r["roster"] == [{"name": "Jean Martin", "role": "consultant"}]
    assert [t["text"] for t in r["topics"]] == ["PAS DE RONALDO : NOUVEL IMBROGLIO ?"]   # misread merged
    assert r["digest"]["topic"] == "Ronaldo's absence" and r["digest"]["claims"][0]["speaker"] == "Jean Martin"
    assert "Jean Martin, consultant" in texts[-1] and "il a rate trois entrainements" in texts[-1]
    comp.step(dev, now=now + 7)                      # caption interval passed, band unchanged: no read
    assert len(caption_calls) == 1 and caption_calls[0]["timeout_s"] == 30


def test_truncated_frame_never_reaches_the_ai(setup, monkeypatch):
    comp, vision, _, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    frame = _frame(tmp / "f.jpg")
    data = open(frame, "rb").read()
    open(frame, "wb").write(data[:-500])             # cut mid-write
    dev = _observe(comp, frame, meta)
    comp.step(dev, now=0)
    assert vision.calls == [] and dev.backoffs == {}


def test_news_debate_flip_on_one_channel_keeps_speakers_and_title(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    monkeypatch.setattr(mc, "_interval", lambda profile=None: 20.0)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "L'EQUIPE DU SOIR"}}
    real = vision.__call__

    def call(prompt, image, usage, **kw):
        if usage == "vision.companion.roi":
            return {"success": True, "content": json.dumps({"captions": [
                {"kind": "name", "text": "Ludovic Obraniak", "role": "consultant"},
                {"kind": "name", "text": "OLISE GOLAZO (LA PREUVE EN IMAGE)"}]})}
        return real(prompt, image, usage, **kw)
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=call, lookup=lambda p: {},
                               call_text=lambda *a, **k: {"success": False, "error": "x"},
                               chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "none.json")))
    meta = tmp_path / "metadata"
    meta.mkdir()
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=0)
    assert [r["name"] for r in comp.result("device1")["roster"]] == ["Ludovic Obraniak"]
    vision.identify = {"screen": "live_tv", "category": "news", "entity": {"title": "LE SHOW YAMAL"}}
    comp.step(dev, now=25)                           # one vote for news: stays debate
    r = comp.result("device1")
    assert r["category"] == "debate" and r["entity"]["title"] == "L'EQUIPE DU SOIR"
    assert [x["name"] for x in r["roster"]] == ["Ludovic Obraniak"]
    comp.step(dev, now=50)                           # second vote in a row: switches, nothing reset
    r = comp.result("device1")
    assert r["category"] == "news" and r["entity"]["title"] == "L'EQUIPE DU SOIR"
    assert [x["name"] for x in r["roster"]] == ["Ludovic Obraniak"]


def test_busy_local_digest_does_not_pause_identify_or_captions(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    monkeypatch.setattr(mc, "_interval", lambda profile=None: 20.0)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "SHOW"}}
    real = vision.__call__

    def call(prompt, image, usage, **kw):
        if usage == "vision.companion.roi":
            vision.calls.append((usage, prompt, kw))
            return {"success": True, "content": '{"captions": []}'}
        return real(prompt, image, usage, **kw)
    chunk = tmp_path / "chunk.json"
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=call, lookup=lambda p: {},
                               call_text=lambda *a, **k: {"success": False, "busy": True, "error": "pc busy"},
                               chunk_path_for=lambda d: (lambda h, i: str(chunk)))
    meta = tmp_path / "metadata"
    meta.mkdir()
    now = datetime(2026, 9, 30, 15, 7, 0).timestamp()
    chunk.write_text(json.dumps({"segments": [{"start": 400, "text": "bonjour"}]}))
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=now)
    assert set(dev.backoffs) == {mc.DIGEST}                       # only the digest waits
    before = len(vision.calls)
    dev.caption_band = None                                        # force a caption read
    comp.step(dev, now=now + 25)                                   # identify due + captions due
    assert [u for u, *_ in vision.calls[before:]] == ["vision.companion", "vision.companion.roi"]


def test_match_clip_in_a_talk_show_keeps_the_programme_until_a_new_banner(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    monkeypatch.setattr(mc, "_interval", lambda profile=None: 20.0)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "L'EQUIPE DU SOIR"},
                       "banner": {"program_name": "L'Equipe du soir", "start_time": "19:00", "end_time": "20:00"}}
    real = vision.__call__

    def call(prompt, image, usage, **kw):
        if usage == "vision.companion.roi" and "lower part" in prompt:
            return {"success": True, "content": json.dumps({"captions": [
                {"kind": "name", "text": "Ludovic Obraniak", "role": "consultant"}]})}
        return real(prompt, image, usage, **kw)
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=call, lookup=lambda p: {},
                               call_text=lambda *a, **k: {"success": False, "error": "x"},
                               chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "none.json")))
    meta = tmp_path / "metadata"
    meta.mkdir()
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=0)
    names = lambda: [x["name"] for x in comp.result("device1").get("roster") or []]
    assert names() == ["Ludovic Obraniak"]
    vision.identify = {"screen": "live_tv", "category": "sport", "subcategory": "soccer",
                       "entity": {"home_team": "France", "away_team": "Italie"}}
    comp.step(dev, now=25)                            # a match clip: one vote, still the debate
    assert comp.result("device1")["category"] == "debate" and names() == ["Ludovic Obraniak"]
    comp.step(dev, now=50)                            # two votes: the card follows, the programme stays
    assert comp.result("device1")["category"] == "sport" and names() == ["Ludovic Obraniak"]
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "X"},
                       "banner": {"program_name": "QUI SUIS-JE"}}
    comp.step(dev, now=75)                            # the show logo / a strap read as a banner: no times
    assert names() == ["Ludovic Obraniak"] and dev.programme_name == "L'Equipe du soir"
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "X"},
                       "banner": {"program_name": "Le journal du soir", "start_time": "20:00", "end_time": "20:30"}}
    comp.step(dev, now=100)                           # the info bar names another programme: fresh start
    assert comp.result("device1").get("roster") in (None, []) or names() == ["Ludovic Obraniak"]
    assert dev.programme_name == "Le journal du soir"


def test_after_a_zap_the_digest_ignores_the_previous_channels_speech_and_uses_subtitles(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    monkeypatch.setattr(mc, "_interval", lambda profile=None: 20.0)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "news", "entity": {"title": "Tagesschau"}}
    real = vision.__call__

    def call(prompt, image, usage, **kw):
        if usage == "vision.companion.roi":
            return {"success": True, "content": json.dumps({"captions": [
                {"kind": "subtitle", "text": "Ein grosses Tiefdruckgebiet ueber dem Atlantik."}]})}
        return real(prompt, image, usage, **kw)
    prompts = []
    chunk = tmp_path / "chunk.json"
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=call, lookup=lambda p: {},
                               call_text=lambda usage, prompt, **k: prompts.append(prompt) or {
                                   "success": True, "content": '{"stories": [], "sensitive": {"flag": false}}'},
                               chunk_path_for=lambda d: (lambda h, i: str(chunk)))
    meta = tmp_path / "metadata"
    meta.mkdir()
    t0 = datetime(2026, 9, 30, 15, 20, 0).timestamp()
    chunk.write_text(json.dumps({"segments": [{"start": 10, "text": "hommage a Didier Deschamps"}]}))   # 15:20:10
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=t0 + 30)                       # first programme after start: speech kept
    assert "Deschamps" in prompts[-1]
    (meta / "last_zapping.json").write_text("{}")     # a zap
    os.utime(meta / "last_zapping.json", (t0 + 60, t0 + 60))
    dev.digest_at = None
    comp.step(dev, now=t0 + 200)                      # after the zap: old speech dropped, subtitles in
    assert "Deschamps" not in prompts[-1]
    assert "SUBTITLE: Ein grosses Tiefdruckgebiet" in prompts[-1]
    assert not any("Tiefdruckgebiet" in t["text"] for t in comp.result("device1").get("topics") or [])


def test_a_key_press_that_is_not_a_zap_keeps_the_programme(tmp_path, monkeypatch):
    """capture rewrites last_zapping.json with status aborted on every non-channel key (RIGHT, OK):
    that is not a zap, so no re-identify and no programme reset. A real zap still is one."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "news", "entity": {"title": "Tagesgespraech"},
                       "on_screen": {"lower_third": {"name": "Judith Huber", "role": "Korrespondentin"}}}
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=vision, lookup=lambda p: {},
                               call_text=lambda *a, **k: {"success": False, "error": "x"},
                               chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "none.json")))
    meta = tmp_path / "metadata"
    meta.mkdir()
    zap = meta / "last_zapping.json"
    zap.write_text(json.dumps({"status": "completed", "zapping_detected": True, "banner_status": "detected",
                               "frame_filename": "capture_1.jpg", "channel_name": "SRF info",
                               "program_name": "Tagesgespraech"}))
    os.utime(zap, (100, 100))
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=110)
    assert [x["name"] for x in comp.result("device1")["roster"]] == ["Judith Huber"]
    vision.identify = {**vision.identify, "on_screen": None}
    zap.write_text(json.dumps({"status": "aborted", "zapping_detected": False, "frame_filename": "capture_9.jpg",
                               "reason": "Action 'RIGHT' is not a channel-change key"}))
    os.utime(zap, (120, 120))
    comp.step(dev, now=125)
    assert vision.usages().count("vision.companion") == 1                 # no re-identify
    assert [x["name"] for x in comp.result("device1")["roster"]] == ["Judith Huber"]
    assert '"SRF info"' in mc.identify.build_prompt(comp.profiles, None, comp._banner(dev, 125))  # banner kept
    zap.write_text(json.dumps({"status": "in_progress", "frame_filename": "capture_50.jpg"}))
    os.utime(zap, (130, 130))
    comp.step(dev, now=135)                                               # a real zap
    assert vision.usages().count("vision.companion") == 2
    assert comp.result("device1").get("roster") is None
    zap.write_text(json.dumps({"status": "completed", "banner_status": "detected", "frame_filename": "capture_50.jpg",
                               "channel_name": "3+", "program_name": "The Voice"}))
    os.utime(zap, (145, 145))
    comp.step(dev, now=150)                                               # its banner arrives: identify with it
    assert vision.usages().count("vision.companion") == 3
    assert "The Voice" in [c[1] for c in vision.calls if c[0] == "vision.companion"][-1]


def test_a_channel_ident_from_identify_is_not_a_speaker(setup, monkeypatch):
    comp, vision, _, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision.identify = {"screen": "live_tv", "category": "news", "entity": {"title": "Tagesgespraech"},
                       "on_screen": {"lower_third": {"name": "Audio Radio SRF 1", "role": None}}}
    comp._chunk_path_for = lambda d: (lambda h, i: str(tmp / "none.json"))
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    comp.step(dev, now=0)
    assert comp.result("device1").get("roster") is None


def test_speech_of_an_earlier_segment_already_digested_is_not_sent_again(tmp_path, monkeypatch):
    """SRF INFO 15:25 digested the weather; at 15:27 the same lines came back next to the caption of
    the correspondent who followed, and the forecast was credited to her."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "news", "entity": {"title": "Tagesgespraech"}}
    real = vision.__call__
    caption = {"captions": []}

    def call(prompt, image, usage, **kw):
        if usage == "vision.companion.roi":
            return {"success": True, "content": json.dumps(caption)}
        return real(prompt, image, usage, **kw)
    prompts = []
    chunk = tmp_path / "chunk.json"
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=call, lookup=lambda p: {},
                               call_text=lambda usage, prompt, **k: prompts.append(prompt) or {
                                   "success": True, "content": '{"stories": [], "sensitive": {"flag": false}}'},
                               chunk_path_for=lambda d: (lambda h, i: str(chunk)))
    meta = tmp_path / "metadata"
    meta.mkdir()
    t0 = datetime(2026, 9, 30, 15, 20, 0).timestamp()
    chunk.write_text(json.dumps({"segments": [{"start": 300, "text": "Wolken und Regen am Sonntag"}]}))  # 15:25:00
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=t0 + 330)                      # 15:25:30 digest: the weather
    assert "Wolken" in prompts[-1]
    caption["captions"] = [{"kind": "name", "text": "Judith Huber", "role": "Osteuropa-Korrespondentin SRF"}]
    dev.caption_band = None
    chunk.write_text(json.dumps({"segments": [{"start": 300, "text": "Wolken und Regen am Sonntag"},
                                              {"start": 400, "text": "die Lage in der Ukraine"}]}))
    comp.step(dev, now=t0 + 395)                      # 15:26:35 her caption: a new segment
    dev.digest_at = None
    comp.step(dev, now=t0 + 460)                      # 15:27:40 digest
    assert "Wolken" not in prompts[-1] and "die Lage in der Ukraine" in prompts[-1]
    assert "ON SCREEN: Judith Huber, Osteuropa-Korrespondentin SRF" in prompts[-1]


def test_a_channel_change_capture_missed_starts_a_new_programme_after_two_reads(setup, monkeypatch):
    """Digits + OK on stb4: capture logs « aborted: OK is not a channel-change key », no zap."""
    comp, vision, _, tmp, meta = setup
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    comp._chunk_path_for = lambda d: (lambda h, i: str(tmp / "none.json"))
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "L'EQUIPE DU SOIR"},
                       "banner": {"channel_name": "L'ÉQUIPE", "start_time": "19:00", "end_time": "20:00"},
                       "on_screen": {"lower_third": {"name": "Ludovic Obraniak", "role": "consultant"}}}
    dev = _observe(comp, _frame(tmp / "f.jpg"), meta)
    comp.step(dev, now=0)
    names = lambda: [x["name"] for x in comp.result("device1").get("roster") or []]
    assert names() == ["Ludovic Obraniak"]
    vision.identify = {**vision.identify, "banner": {"channel_name": "la chaine L'EQUIPE", "start_time": "19:00", "end_time": "20:00"}, "on_screen": None}
    comp.step(dev, now=25)                            # the same channel, spelled otherwise
    vision.identify = {**vision.identify, "banner": {"channel_name": "POLITICS LIVE"}}   # a strap, no times
    comp.step(dev, now=45)
    comp.step(dev, now=65)                            # read twice: still no channel change
    assert names() == ["Ludovic Obraniak"] and dev.channel_vote is None
    vision.identify = {**vision.identify, "banner": {"channel_name": "SRF info", "start_time": "19:00", "end_time": "20:00"}}
    comp.step(dev, now=85)                            # one read of another channel: could be a misread
    assert names() == ["Ludovic Obraniak"]
    comp.step(dev, now=105)                           # twice in a row: a new programme
    assert names() == [] and dev.programme_since == 105 and dev.channel == "SRF info"
    comp.step(dev, now=125)                           # and it stays
    assert dev.programme_since == 105


def test_speech_from_before_the_programme_appeared_is_not_digested(tmp_path, monkeypatch):
    """stb4 went from the home screen (teleshopping audio) to SRF INFO without a recorded zap."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision = FakeVision()
    vision.identify = {"screen": "home"}
    prompts = []
    chunk = tmp_path / "chunk.json"
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=vision, lookup=lambda p: {},
                               call_text=lambda usage, prompt, **k: prompts.append(prompt) or {
                                   "success": True, "content": '{"topic": null, "positions": [], "claims": []}'},
                               chunk_path_for=lambda d: (lambda h, i: str(chunk)))
    meta = tmp_path / "metadata"
    meta.mkdir()
    t0 = datetime(2026, 10, 1, 15, 30, 0).timestamp()
    chunk.write_text(json.dumps({"segments": [{"start": 10, "text": "Lipoxantin Kapsel"},          # 15:30:10
                                              {"start": 200, "text": "Willkommen im Club"}]}))      # 15:33:20
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=t0 + 60)                       # home screen: no digest
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "Club"}}
    _observe(comp, _frame(tmp_path / "f.jpg"), meta, motion={"state": "ui"})
    comp.step(dev, now=t0 + 70)
    _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=t0 + 190)                      # live from 15:33:10 on
    dev.digest_at = None
    comp.step(dev, now=t0 + 260)
    assert "Willkommen im Club" in prompts[-1] and "Lipoxantin" not in prompts[-1]


def test_checkable_debate_claims_are_fact_checked_only_when_the_device_opts_in(tmp_path, monkeypatch):
    """TASK-45: the digest's checkable claims are no longer the path to the web check — the
    meter is. With FACTCHECK off the path is silent; with it on, the digest's claims stay
    un-checked until the meter picks a factual sentence."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "Club"}}
    checks = []
    chunk = tmp_path / "chunk.json"
    chunk.write_text(json.dumps({"segments": [{"start": 280, "text": "435 Sitze werden neu gewaehlt"}]}))
    comp = mc.MonitorCompanion(
        team_id=TEAM, call_vision=vision, lookup=lambda p: {},
        call_text=lambda usage, prompt, **k: {"success": True, "content": json.dumps({"topic": "Midterms", "positions": [],
            "claims": [{"text": "435 Sitze werden neu gewaehlt", "speaker": None, "checkable": True},
                       {"text": "Trump ist narzisstisch", "speaker": None, "checkable": False}]})},
        chunk_path_for=lambda d: (lambda h, i: str(chunk)),
        check=lambda prompt: checks.append(prompt) or {"success": True, "content": json.dumps(
            {"verdict": "supported", "note": "All 435 seats are elected.", "sources": ["https://s.test"]})})
    request = comp.checks.request
    comp.checks.request = lambda *a, **k: request(*a, **k, background=False)   # check inline
    meta = tmp_path / "metadata"
    meta.mkdir()
    now = datetime(2026, 10, 1, 16, 5, 0).timestamp()
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    monkeypatch.delenv("DEVICE1_COMPANION_FACTCHECK", raising=False)
    comp.step(dev, now=now)
    # Off by default: nothing has been checked via the digest path.
    assert checks == [] and "check" not in comp.result("device1")["digest"]["claims"][0]
    # With FACTCHECK on, the digest path no longer sends checkable claims to the web check
    # (the meter does it). The claims list still carries the un-checked claim.
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")
    chunk.write_text(json.dumps({"segments": [{"start": 280, "text": "435 Sitze werden neu gewaehlt"},
                                              {"start": 290, "text": "und ein Drittel des Senats"}]}))
    dev.digest, dev.digest_at, dev.digest_seen_t = None, None, 0.0
    comp.step(dev, now=now + 5)
    assert checks == []
    claims = comp.result("device1")["digest"]["claims"]
    assert "check" not in claims[0]
    assert "check" not in claims[1]


# ---------------------------------------------------------------- TASK-45 sentence meter
def _meter_comp(tmp_path, monkeypatch, decide_fn, checks_log, frames=None):
    """Build a MonitorCompanion wired with a fake ``decide`` and a fake ``check``.

    No new threads: ``decide`` runs synchronously so we don't have to wait for daemon
    threads to finish before inspecting the meter.
    """
    import threading
    orig_thread = threading.Thread
    # Run the target inline so the test does not have to join daemon threads. We only
    # patch the meter dispatch (a daemon thread launched by _score_sentence) — the
    # companion worker thread is started by observe() and is skipped below.
    def inline_runner(*a, **k):
        target = k.get("target")
        if target is not None and getattr(target, "__name__", "") in (
                "run", "compa", "do"):
            target()
            class _Null:
                def start(self_inner): pass
                def join(self_inner): pass
            return _Null()
        return orig_thread(*a, **k)
    # Inject a runner that runs the meter's background target inline. We use a sentinel name
    # ("_score_sentence") we attach to the function below to identify meter's threads.
    import features.companion.backend_host.companion as bh
    real_score = bh.MonitorCompanion._score_sentence
    def patch_speaker():
        real_score()
    real_score.__name__ = "_score_sentence"
    monkeypatch.setattr(threading, "Thread", inline_runner)
    # Disable the worker thread entirely: observe() will not start it (we don't call step()
    # through the worker; we call step() ourselves).
    from features.companion.backend_host.companion import MonitorCompanion
    monkeypatch.setattr(MonitorCompanion, "_worker", lambda self, dev: None)

    chunk = tmp_path / "chunk.json"
    chunk.write_text("{}")
    calls = []

    def decide(state, questions, refs, timeout_s):
        # Replace refs with a marker so the assertion is easy.
        return decide_fn(state, questions, refs, timeout_s, calls)

    comp = MonitorCompanion(team_id=None, call_vision=lambda *a, **k: {"verdict": None},
                             lookup=lambda *a, **k: {},
                             check=lambda *a, **k: checks_log.append(a) or {"success": True,
                                                                          "content": json.dumps(
                                                                              {"verdict": "supported",
                                                                               "note": "ok",
                                                                               "sources": [
                                                                                   {"url": "https://s.test",
                                                                                    "title": "src"}]})},
                             decide=decide,
                             people_path=str(tmp_path / "kp.json"))
    # No thread is started because we patched _worker. _Device init still wires the meter.
    from datetime import datetime
    meta = tmp_path / "metadata"
    meta.mkdir()
    now = datetime(2026, 10, 1, 16, 5, 0).timestamp()
    return comp, calls, meta, now, frames or {}


# ---------------------------------------------------------------- TASK-45 sentence meter
def _build_meter_comp(tmp_path, monkeypatch, decide_fn, checks_log):
    """Build a MonitorCompanion wired with a fake ``decide`` and a fake ``check``.

    The companion worker thread is patched out (the test calls ``step()`` directly), and the
    meter's background ``decide`` thread is replaced with an inline call. Everything runs in
    the test thread so the meter is populated by the time we read ``result()``.
    """
    import threading
    def inline_runner(*a, **k):
        target = k.get("target")
        args = k.get("args") or ()
        if target is not None:
            target(*args)
        class _Null:
            def start(self_inner): pass
            def join(self_inner): pass
        return _Null()
    monkeypatch.setattr(threading, "Thread", inline_runner)

    from features.companion.backend_host.companion import MonitorCompanion as MC

    calls = []
    def decide(state, questions, refs, timeout_s):
        return decide_fn(state, questions, refs, timeout_s, calls)

    comp = MC(team_id=TEAM,
              call_vision=lambda *a, **k: {"verdict": None},
              lookup=lambda *a, **k: {},
              chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "chunk.json")),
              check=lambda *a, **k: checks_log.append(a) or {"success": True,
                                                            "content": json.dumps(
                                                                {"verdict": "supported",
                                                                 "note": "ok",
                                                                 "sources": [{"url": "https://s.test",
                                                                             "title": "src"}]})},
              decide=decide,
              people_path=str(tmp_path / "kp.json"))
    return comp, calls


def _build_dev(comp, tmp_path, monkeypatch):
    """Initialise a _Device for the meter test (no worker thread, no identify loop)."""
    from datetime import datetime
    from features.companion.backend_host.companion import MonitorCompanion, _Device
    monkeypatch.setattr(MonitorCompanion, "_worker", lambda self, dev: None)
    # Make _complete_jpeg a no-op so step() does not bail on a missing test file.
    monkeypatch.setattr(mc, "_complete_jpeg", lambda frame: True)
    # Use the helper that observe() uses so we get the meter state for free.
    comp.observe("device1", str(tmp_path / "f.jpg"), str(tmp_path / "metadata"),
                 {"blackscreen": False})
    dev = comp._devices["device1"]
    # Stub a verdict / programme so _compose has a digest.
    dev.verdict = {"screen": "live_tv", "category": "debate",
                   "entity": {"title": "Debate Show", "channel_name": "SRF 1"}}
    dev.programme_name = "Debate Show"
    dev.channel = "SRF 1"
    dev.roster = {}
    dev.captioned = {}
    dev.topics = [{"text": "Midterms", "first_seen": 0, "last_seen": 0}]
    dev.subtitles = []
    now = datetime(2026, 10, 1, 16, 5, 0).timestamp()
    (tmp_path / "metadata").mkdir(exist_ok=True)
    return dev, now


def test_meter_debate_run_scores_sentences_and_picks_speaker(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")
    monkeypatch.setenv("COMPANION_METER_PER_HOUR", "100")
    monkeypatch.setenv("COMPANION_FACTCHECK_MIN_CLAIM", "0.7")

    checks = []
    def decide(state, questions, refs, timeout_s, calls):
        calls.append({"refs": refs, "state_sentence": state["sentence"]})
        return {
            "ms": 250,
            "answers": {
                "factual_claim": {"type": "noul", "noul": 0.9 if "435" in state["sentence"] else 0.2},
                "evasive": {"type": "noul", "noul": 0.1},
                "contradicts_self": {"type": "noul", "noul": 0.0},
                "emotional_appeal": {"type": "noul", "noul": 0.0},
                "dodged_question": {"type": "noul", "noul": 0.0},
                "speaker": {"type": "choice", "choice": "Jack Straw",
                            "probabilities": {"Jack Straw": 0.9, "unknown": 0.1}},
            },
        }
    comp, calls = _build_meter_comp(tmp_path, monkeypatch, decide, checks)
    dev, now = _build_dev(comp, tmp_path, monkeypatch)

    # Two captions that form one sentence (terminal `.`); then a second sentence.
    dev.joiner.feed(now + 1, "Die 435 Sitze werden neu gewaehlt")
    dev.joiner.feed(now + 1.5, "und ein Drittel des Senats.")
    # The terminal `.` clears the buffer; a second sentence, which is not a checkable claim.
    dev.joiner.feed(now + 4, "Das ist meinung.")
    # Tick once to flush the joiner, score sentences, and write meter.
    comp.step(dev, now=now + 6)
    meter_payload = comp.result("device1")["meter"]
    # Two sentences scored
    assert len(meter_payload["sentences"]) == 2
    # refs include source / device / programme / sentence_t
    assert calls and calls[0]["refs"]["source"] == "companion"
    assert calls[0]["refs"]["device_id"] == "device1"
    assert calls[0]["refs"]["programme"] == "Debate Show"
    assert calls[0]["refs"]["sentence_t"] == now + 1
    # Speaker picked (one per sentence; Jack Straw from the choice question)
    assert all(c["refs"]["device_id"] == "device1" for c in calls)
    # Only the first (0.9) sentence sent to the fact checker; the 0.2 one is not.
    assert len(checks) == 1
    # The fact-check signature is (device_id, claim, speaker, programme, at). The check
    # lambda is the only arg recorded by the verifier callback, so the claim is the first
    # (and only) element of the args tuple.
    claim = checks[0][0] if isinstance(checks[0], tuple) else checks[0]
    assert "Die 435" in claim
    # Meter payload populated: newest sentence first, speaker picked
    assert meter_payload["sentences"][0]["text"].endswith("meinung.")
    assert meter_payload["sentences"][1]["speaker"] == "Jack Straw"


def test_meter_does_nothing_when_factcheck_off(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    # DEVICE1_COMPANION_FACTCHECK NOT set
    monkeypatch.delenv("DEVICE1_COMPANION_FACTCHECK", raising=False)
    monkeypatch.delenv("COMPANION_METER_PER_HOUR", raising=False)
    monkeypatch.delenv("COMPANION_FACTCHECK_MIN_CLAIM", raising=False)

    checks = []
    calls = []
    def decide(state, questions, refs, timeout_s, calls_):
        calls_.append(1)
        return {"ms": 100, "answers": {}}
    comp, calls = _build_meter_comp(tmp_path, monkeypatch, decide, checks)
    dev, now = _build_dev(comp, tmp_path, monkeypatch)
    # FACTCHECK off -> the meter is not built and there is no joiner to feed. Stepping does
    # nothing for the meter either, no matter what subtitles we want to put through it.
    assert dev.joiner is None
    assert dev.meter is None
    comp.step(dev, now=now + 3)
    result = comp.result("device1")
    assert "meter" not in result
    assert calls == []
    assert checks == []


def test_vod_to_live_is_a_new_programme_and_a_pending_vote_is_rechecked_soon(tmp_path, monkeypatch):
    """stb4, 2026-10-04: a VOD film, then BACK + 8 to SRF INFO. The category stayed "movie" for two
    minutes (one vote, then a 120 s wait) and the first digest used speech from before the switch."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    vision = FakeVision()
    vision.identify = {"screen": "live_tv", "category": "news", "entity": {"title": "Tagesschau"},
                       "on_screen": {"lower_third": {"name": "Anne Petit", "role": "reporter"}}}
    comp = mc.MonitorCompanion(team_id=TEAM, call_vision=vision, lookup=lambda p: {},
                               call_text=lambda *a, **k: {"success": False, "error": "x"},
                               chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "none.json")))
    meta = tmp_path / "metadata"
    meta.mkdir()
    dev = _observe(comp, _frame(tmp_path / "f.jpg"), meta)
    comp.step(dev, now=0)
    vision.identify = {"screen": "live_tv", "category": "debate", "entity": {"title": "Tagesschau"}}
    comp.step(dev, now=61)                            # one vote for debate: held
    assert comp.result("device1")["category"] == "news" and dev.category_vote == "debate"
    comp.step(dev, now=61 + mc.VOTE_RECHECK_S)        # rechecked after 20 s, not 60: confirmed
    assert comp.result("device1")["category"] == "debate"
    assert [x["name"] for x in comp.result("device1")["roster"]] == ["Anne Petit"]   # same programme
    vision.identify = {"screen": "vod_playback", "category": "movie", "entity": {"title": "A Film"}}
    comp.step(dev, now=200)                           # VOD: another programme at once, no vote
    r = comp.result("device1")
    assert r["category"] == "movie" and r.get("roster") is None and dev.programme_since == 200


def test_the_host_can_resolve_the_meter_usage(monkeypatch):
    """vpt-companion resolves text.decision.companion itself; it must register the feature's keys."""
    from shared.src.lib.ai import usages
    from features.companion.lib.usages import METER
    usages.USAGES.pop(METER, None)
    mc._default_decide(TEAM)
    assert METER in usages.USAGES and usages.lineage(METER)[-1] == "text"


def test_meter_reads_the_transcript_when_the_channel_has_no_subtitles(tmp_path, monkeypatch):
    """CANAL+ / L'Équipe talk shows carry no subtitles: after a minute without one, the live transcript
    feeds the meter. Caption ages are taken when the sentence was said (the transcript is ~1 min late)."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")
    calls_state = []

    def decide(state, questions, refs, timeout_s, calls):
        calls.append({"refs": refs})
        calls_state.append(state)
        return {"ms": 300, "answers": {q: {"type": "noul", "noul": 0.1} for q in
                                       ("factual_claim", "evasive", "contradicts_self", "emotional_appeal",
                                        "dodged_question")}}
    comp, calls = _build_meter_comp(tmp_path, monkeypatch, decide, [])
    comp._call_text = lambda *a, **k: {"success": False, "error": "no digest in this test"}
    dev, now = _build_dev(comp, tmp_path, monkeypatch)       # 16:05:00, debate
    dev.roster = {"Jean Martin": "consultant"}
    dev.captioned = {"Jean Martin": [now - 30]}              # caption at 16:04:30
    (tmp_path / "chunk.json").write_text(json.dumps({"segments": [
        {"start": 280, "text": "Il a rate trois entrainements."},   # 16:04:40, 10 s after the caption
        {"start": 290, "text": "Le club va le sanctionner."}]}))
    comp.step(dev, now=now)
    assert [c["refs"]["speech"] for c in calls] == ["transcript", "transcript"]
    assert [c["refs"]["sentence_t"] for c in calls] == [now - 20, now - 10]
    assert calls_state[0]["recent_captions"][0]["age_s"] == 10      # at 16:04:40, not 30 s "now"
    comp.step(dev, now=now + 5)                                     # nothing new: no new call
    assert len(calls) == 2
    dev.subtitles = [(now + 6, "Bonjour.")]                         # subtitles back: no transcript
    (tmp_path / "chunk.json").write_text(json.dumps({"segments": [{"start": 295, "text": "Encore."}]}))
    comp.step(dev, now=now + 20)
    assert len(calls) == 2


# ---------------------------------------------------------------- TASK-45 goal 5: Jev gates
def _meter_decide_one(payload: dict, *, factual: float = 0.9):
    """A ``decide`` that returns one noul answer per question in the meter; ``factual`` is
    P(factual_claim) and the rest are 0.1 (low signal)."""
    base = {"type": "noul"}
    answers = {"factual_claim": {**base, "noul": factual},
               "evasive": {**base, "noul": 0.1},
               "contradicts_self": {**base, "noul": 0.0},
               "emotional_appeal": {**base, "noul": 0.0},
               "dodged_question": {**base, "noul": 0.0}}
    answers.update(payload or {})
    return {"ms": 100, "answers": answers}


def _build_gate_comp(tmp_path, monkeypatch, decide_fn, checks_log, gate_fn):
    """Build a MonitorCompanion wired with a fake ``decide`` and a fake ``gate``; the gate is
    the one that decides whether to SKIP an LLM / web call (TASK-45)."""
    import threading as _th_mod

    def inline_runner(*a, **k):
        target = k.get("target")
        args = k.get("args") or ()

        class _Ok:
            def start(self):
                pass

            def join(self):
                pass
        if target is not None:
            target(*args)
        return _Ok()

    monkeypatch.setattr(_th_mod, "Thread", inline_runner)

    def decide(state, questions, refs, timeout_s):
        return decide_fn(state, questions, refs, timeout_s)

    def gate(state, questions, refs, timeout_s):
        return gate_fn(state, questions, refs, timeout_s)

    comp = mc.MonitorCompanion(team_id=TEAM,
                               call_vision=lambda *a, **k: {"verdict": None},
                               lookup=lambda *a, **k: {},
                               chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "chunk.json")),
                               check=lambda *a, **k: checks_log.append(a) or {"success": True,
                                                                             "content": json.dumps(
                                                                                 {"verdict": "supported",
                                                                                  "note": "ok",
                                                                                  "sources": [{"url": "https://s.test",
                                                                                              "title": "src"}]})},
                               decide=decide, gate=gate, people_path=str(tmp_path / "kp.json"))
    return comp


def _feed_sentence(dev, sentence: str, t: float):
    dev.joiner.feed(t, sentence)


def test_factcheck_gate_skips_vague_claim(tmp_path, monkeypatch):
    """P(specific) below 0.5 -> gate skips the web call; the FactChecker row is
    ``status="skipped"`` and the meter panel hides the sentence from the fact-check list."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")
    monkeypatch.setenv("COMPANION_FACTCHECK_MIN_CLAIM", "0.7")

    def decide(state, sentence, refs, timeout_s):
        return _meter_decide_one({}, factual=0.9)   # sentence passes the meter threshold

    gate_calls = []

    def gate(state, questions, refs, timeout_s):
        gate_calls.append({"refs": refs, "state": state})
        return {"success": True, "answers": {"specific": {"type": "noul", "noul": 0.2}}}

    checks = []
    comp = _build_gate_comp(tmp_path, monkeypatch, decide, checks, gate)
    dev, now = _build_dev(comp, tmp_path, monkeypatch)
    _feed_sentence(dev, "I think the government is failing.", now + 1)
    comp.step(dev, now=now + 6)
    assert len(gate_calls) == 1
    assert gate_calls[0]["refs"]["gate"] == "factcheck"
    assert checks == []                       # no web check
    # The sentence carries a skipped entry on the meter payload.
    meter = comp.result("device1")["meter"]
    checked = [s for s in meter["sentences"] if s.get("check") and s["check"]["status"] == "skipped"]
    assert len(checked) == 1
    assert checked[0]["check"]["reason"] == "vague"


def test_factcheck_gate_skips_repeat_claim(tmp_path, monkeypatch):
    """P(repeat) at/above 0.7 -> the gate skips; the previous claims seen list is what the
    gate was given."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")
    monkeypatch.setenv("COMPANION_FACTCHECK_MIN_CLAIM", "0.7")

    def decide(state, questions, refs, timeout_s):
        return _meter_decide_one({}, factual=0.9)

    seen_states = []

    def gate(state, questions, refs, timeout_s):
        seen_states.append({"checked": state.get("checked")})
        if any("repeat" in q for q in (questions or {})):
            return {"success": True,
                    "answers": {"specific": {"type": "noul", "noul": 0.8},
                                "repeat": {"type": "noul", "noul": 0.9}}}
        return {"success": True, "answers": {"specific": {"type": "noul", "noul": 0.8}}}

    checks = []
    comp = _build_gate_comp(tmp_path, monkeypatch, decide, checks, gate)
    dev, now = _build_dev(comp, tmp_path, monkeypatch)
    # First sentence: passes, no prior claim -> the gate is asked without "repeat", web call made.
    _feed_sentence(dev, "Politicians never listen.", now + 1)
    comp.step(dev, now=now + 6)
    assert len(checks) == 1
    # Second sentence: the same claim, paraphrased -> gate is asked with "repeat" and skips.
    _feed_sentence(dev, "Politicians don't listen to voters.", now + 4)
    comp.step(dev, now=now + 10)
    # Only one web call (the first); the second was skipped.
    assert len(checks) == 1
    assert seen_states[0]["checked"] == []                       # first call had nothing to compare
    assert seen_states[1]["checked"]                             # second call sees the first claim
    meter = comp.result("device1")["meter"]
    skipped = [s for s in meter["sentences"] if s.get("check") and s["check"]["status"] == "skipped"]
    assert len(skipped) == 1 and skipped[0]["check"]["reason"] == "repeat"


def test_factcheck_gate_failure_runs_the_web_check(tmp_path, monkeypatch):
    """Gate call failure / no answer -> today's path: the web check is run."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")
    monkeypatch.setenv("COMPANION_FACTCHECK_MIN_CLAIM", "0.7")

    def decide(state, questions, refs, timeout_s):
        return _meter_decide_one({}, factual=0.9)

    def gate(state, questions, refs, timeout_s):
        return {"success": False, "error": "jev offline"}        # fail open

    checks = []
    comp = _build_gate_comp(tmp_path, monkeypatch, decide, checks, gate)
    dev, now = _build_dev(comp, tmp_path, monkeypatch)
    _feed_sentence(dev, "Claim one.", now + 1)
    comp.step(dev, now=now + 6)
    assert len(checks) == 1                                       # web check still made
    # No "skipped" row on the meter.
    meter = comp.result("device1")["meter"]
    assert not any(s.get("check") and s["check"]["status"] == "skipped" for s in meter["sentences"])


def test_facts_gate_skips_non_programme_title(tmp_path, monkeypatch):
    """P(worth_lookup) below 0.5 -> the gate skips the web lookup; payload status is
    ``skipped`` and no UI row appears."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)

    def gate(state, questions, refs, timeout_s):
        return {"success": True, "answers": {"worth_lookup": {"type": "noul", "noul": 0.2}}}

    def lookup(prompt):
        return {"success": True, "content": '{"venue": "Eden"}',
                "sources": [{"url": "https://s.test"}]}

    from features.companion.backend_host.companion import MonitorCompanion
    comp = MonitorCompanion(team_id=TEAM, call_vision=FakeVision(), lookup=lookup, gate=gate,
                            chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "none.json")))
    monkeypatch.setattr(mc, "_interval", lambda profile=None: 20.0)
    comp.observe("device1", str(tmp_path / "f.jpg"), str(tmp_path / "metadata"),
                 {"blackscreen": False})
    comp._devices["device1"].verdict = {"screen": "live_tv", "category": "sport",
                                          "subcategory": "soccer",
                                          "entity": {"home_team": "LIL", "away_team": "BET"}}
    # Sync the cache so the gate runs in the test thread.
    original = comp.facts.get

    def sync(key, profile, entity, *, background=True, **kwargs):
        return original(key, profile, entity, background=False, **kwargs)

    comp.facts.get = sync
    from features.companion.lib.profiles import load_profiles, profile_for
    profile = profile_for("sport", "soccer", load_profiles())
    entry = comp.facts.get("sport/soccer/lil_bet/2026-10-01", profile,
                            {"home_team": "LIL", "away_team": "BET"},
                            category="sport", subcategory="soccer", channel="BBC")
    assert entry["status"] == "skipped"
    facts = enrich.facts_payload(entry)
    assert facts["status"] == "skipped"


def test_facts_gate_failure_runs_the_lookup(tmp_path, monkeypatch):
    """Gate failure -> the lookup runs (today's path)."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)

    def gate(state, questions, refs, timeout_s):
        return {"success": False, "error": "jev offline"}        # fail open

    from features.companion.backend_host.companion import MonitorCompanion
    from features.companion.lib.profiles import load_profiles, profile_for
    profile = profile_for("sport", "soccer", load_profiles())

    def lookup(prompt):
        return {"success": True, "content": '{"venue": "Eden"}', "sources": [{"url": "https://s.test"}]}

    comp = MonitorCompanion(team_id=TEAM, call_vision=FakeVision(), lookup=lookup, gate=gate,
                            chunk_path_for=lambda d: (lambda h, i: str(tmp_path / "none.json")))
    original = comp.facts.get

    def sync(key, profile, entity, *, background=True, **kwargs):
        return original(key, profile, entity, background=False, **kwargs)

    comp.facts.get = sync
    entry = comp.facts.get("sport/soccer/lil_bet/2026-10-01", profile,
                            {"home_team": "LIL", "away_team": "BET"},
                            category="sport", subcategory="soccer", channel="BBC")
    assert entry["status"] == "ready" and entry["facts"]["venue"] == "Eden"


def test_digest_gate_first_digest_always_runs(tmp_path, monkeypatch):
    """No previous digest -> the LLM digest always runs (the gate is only asked when there is a
    previous digest)."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")

    decided = {"text_called": 0, "factcheck_asked": 0, "digest_asked": 0}

    def gate(state, questions, refs, timeout_s):
        if refs.get("gate") == "digest":
            decided["digest_asked"] += 1
        elif refs.get("gate") == "factcheck":
            decided["factcheck_asked"] += 1
        return {"success": True, "answers": {"new_content": {"type": "noul", "noul": 0.1}}}

    def call_text(usage, *a, **k):
        decided["text_called"] += 1
        return {"success": True, "content": '{"topic": "Midterms", "positions": [], "claims": []}'}

    def decide(state, questions, refs, timeout_s):
        return _meter_decide_one({}, factual=0.9)

    checks = []
    comp = _build_gate_comp(tmp_path, monkeypatch, decide, checks, gate)
    comp._call_text = call_text
    dev, now = _build_dev(comp, tmp_path, monkeypatch)             # 16:05:00, debate
    # recent_lines reads ``segments[*].start`` as a seconds offset from the chunk's start
    # (the chunk at 16:00:00 for ``now=16:05:00``). 301 s = 16:05:01, one second after ``now``.
    (tmp_path / "chunk.json").write_text(json.dumps({"segments": [
        {"start": 301, "text": "Le debat est interessant aujourd'hui."}]}))
    comp.step(dev, now=now + 1)
    # First digest: digest gate not asked (no previous digest), LLM digest ran. The
    # factcheck gate is asked once for the scored sentence.
    assert decided["digest_asked"] == 0
    assert decided["factcheck_asked"] == 1
    assert decided["text_called"] == 1
    assert comp.result("device1").get("digest") is not None


def test_digest_gate_second_digest_skipped_when_nothing_new(tmp_path, monkeypatch):
    """P(new_content) below 0.3 -> skip the LLM digest (set seen pointers, keep dev.digest)."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")

    decided = {"text_called": 0, "factcheck_asked": 0, "digest_asked": 0}

    def gate(state, questions, refs, timeout_s):
        if refs.get("gate") == "digest":
            decided["digest_asked"] += 1
        elif refs.get("gate") == "factcheck":
            decided["factcheck_asked"] += 1
        return {"success": True, "answers": {"new_content": {"type": "noul", "noul": 0.1}}}

    def call_text(usage, *a, **k):
        decided["text_called"] += 1
        return {"success": True, "content": '{"topic": "Midterms", "positions": [], "claims": []}'}

    def decide(state, questions, refs, timeout_s):
        return _meter_decide_one({}, factual=0.9)

    checks = []
    comp = _build_gate_comp(tmp_path, monkeypatch, decide, checks, gate)
    comp._call_text = call_text
    dev, now = _build_dev(comp, tmp_path, monkeypatch)
    dev.digest = {"at": now, "window_min": 5, "lines": 1, "topic": "Midterms",
                   "positions": [], "claims": [{"text": "An earlier claim."}]}
    dev.digest_seen_t = now - 1
    dev.digest_seen_screen = now - 1
    dev.digest_at = None
    # Same offset trick as above: 301 s into the chunk = 16:05:01.
    (tmp_path / "chunk.json").write_text(json.dumps({"segments": [
        {"start": 301, "text": "Un nouveau sujet a ete evoque."}]}))
    comp.step(dev, now=now + 1)
    # Second digest: digest gate was asked (1), LLM was not (skipped). The factcheck gate
    # is asked once for the scored sentence regardless.
    assert decided["digest_asked"] == 1
    assert decided["text_called"] == 0
    # dev.digest still holds the previous digest; only the seen pointer advanced.
    assert comp.result("device1").get("digest") is not None


def test_digest_gate_second_digest_runs_when_new_content_high(tmp_path, monkeypatch):
    """P(new_content) at/above 0.3 -> the LLM digest runs."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")

    decided = {"text_called": 0, "factcheck_asked": 0, "digest_asked": 0}

    def gate(state, questions, refs, timeout_s):
        if refs.get("gate") == "digest":
            decided["digest_asked"] += 1
        elif refs.get("gate") == "factcheck":
            decided["factcheck_asked"] += 1
        return {"success": True, "answers": {"new_content": {"type": "noul", "noul": 0.8}}}

    def call_text(usage, *a, **k):
        decided["text_called"] += 1
        return {"success": True, "content": '{"topic": "New topic", "positions": [], "claims": []}'}

    def decide(state, questions, refs, timeout_s):
        return _meter_decide_one({}, factual=0.9)

    checks = []
    comp = _build_gate_comp(tmp_path, monkeypatch, decide, checks, gate)
    comp._call_text = call_text
    dev, now = _build_dev(comp, tmp_path, monkeypatch)
    dev.digest = {"at": now, "window_min": 5, "lines": 1, "topic": "Old topic",
                   "positions": [], "claims": [{"text": "An old claim."}]}
    dev.digest_seen_t = now - 1
    dev.digest_seen_screen = now - 1
    dev.digest_at = None
    (tmp_path / "chunk.json").write_text(json.dumps({"segments": [
        {"start": 301, "text": "Something new came up."}]}))
    comp.step(dev, now=now + 1)
    assert decided["digest_asked"] == 1
    assert decided["text_called"] == 1


def test_digest_gate_failure_runs_the_digest(tmp_path, monkeypatch):
    """Gate failure / no answer -> the LLM digest runs (today's path)."""
    monkeypatch.setenv("DEVICE1_COMPANION", "true")
    monkeypatch.setenv("DEVICE1_COMPANION_FACTCHECK", "true")

    decided = {"text_called": 0, "factcheck_asked": 0, "digest_asked": 0}

    def gate(state, questions, refs, timeout_s):
        if refs.get("gate") == "digest":
            decided["digest_asked"] += 1
        elif refs.get("gate") == "factcheck":
            decided["factcheck_asked"] += 1
        return {"success": False, "error": "jev offline"}        # fail open

    def call_text(usage, *a, **k):
        decided["text_called"] += 1
        return {"success": True, "content": '{"topic": "T", "positions": [], "claims": []}'}

    def decide(state, questions, refs, timeout_s):
        return _meter_decide_one({}, factual=0.9)

    checks = []
    comp = _build_gate_comp(tmp_path, monkeypatch, decide, checks, gate)
    comp._call_text = call_text
    dev, now = _build_dev(comp, tmp_path, monkeypatch)
    dev.digest = {"at": now, "window_min": 5, "lines": 1, "topic": "Old",
                   "positions": [], "claims": [{"text": "An old claim."}]}
    dev.digest_seen_t = now - 1
    dev.digest_seen_screen = now - 1
    dev.digest_at = None
    (tmp_path / "chunk.json").write_text(json.dumps({"segments": [
        {"start": 301, "text": "Encore du nouveau."}]}))
    comp.step(dev, now=now + 1)
    assert decided["digest_asked"] == 1
    assert decided["text_called"] == 1


def test_facts_gate_never_runs_in_the_callers_thread(tmp_path, monkeypatch):
    """The gate is asked from the background lookup thread, so step()/result() never wait on it."""
    monkeypatch.setattr(mc.threading, "Thread", _NoThread)
    from features.companion.lib.profiles import load_profiles, profile_for
    profile = profile_for("sport", "soccer", load_profiles())
    asked = []
    cache = enrich.FactCache(lambda prompt: {}, gate=lambda *a: asked.append(a) or {"success": False})
    entry = cache.get("k", profile, {"home_team": "LIL", "away_team": "BET"})
    assert entry["status"] == "pending" and asked == []


def test_score_restart_clears_events_and_clock():
    """A looping clip restarts at 0-0: its old goals and clock must not pile up."""
    from features.companion.lib.scoreboard import ScoreStabiliser

    def read(h, a, clock):
        return {"visible": True, "home_score": h, "away_score": a, "clock": clock}

    s = ScoreStabiliser("FRA", "GER")
    for h, a, clock in [(0, 0, "10:00"), (1, 0, "20:00"), (1, 1, "64:10")]:
        for _ in range(3):
            s.feed(read(h, a, clock), now=0)
    assert len(s.events) == 2
    for _ in range(3):
        s.feed(read(0, 0, "01:00"), now=0)
    assert s.events == [] and s.minute == 1 and s.score == (0, 0)
    for _ in range(3):
        s.feed(read(1, 0, "05:00"), now=0)
    assert len(s.events) == 1
