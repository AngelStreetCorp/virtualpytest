"""Live-TV companion core (TASK-05): profiles, identify parsing, score stabiliser, fact cache.

Pure: no AI, no network, no DB.

Run: pytest tests/backend_server/test_companion.py -v
"""
import json
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from features.companion.lib import enrich, identify  # noqa: E402
from features.companion.lib.profiles import SCREENS, load_profiles, profile_for  # noqa: E402
from features.companion.lib.scoreboard import ScoreStabiliser, parse_clock  # noqa: E402

pytestmark = pytest.mark.unit


SOCCER = load_profiles()["sport/soccer"]


# ---------------------------------------------------------------- profiles
def test_soccer_profile_loads_and_matches_most_specific():
    assert SOCCER.tracker == "scoreboard" and SOCCER.render == "match"
    assert "home_lineup" in SOCCER.facts
    assert profile_for("sport", "soccer") is SOCCER
    assert profile_for("sport", "tennis") is None  # no generic sport profile yet
    assert profile_for("movie", None).render == "title"
    assert profile_for("series", "sitcom").id == "series"  # the category profile covers any kind


def test_profile_with_unknown_tracker_is_rejected(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps(
        {"id": "sport/x", "category": "sport", "track": {"type": "teleport"}}))
    with pytest.raises(ValueError, match="unknown tracker"):
        load_profiles(str(tmp_path))


# ---------------------------------------------------------------- identify
def test_extract_json_takes_last_object_and_ignores_prose_and_braces_in_strings():
    text = 'Sure! {"a": 1} then the answer:\n```json\n{"screen": "menu", "note": "a } brace"}\n```'
    assert identify.extract_json(text) == {"screen": "menu", "note": "a } brace"}
    assert identify.extract_json("no json here") is None


def test_parse_playback_verdict_with_scoreboard():
    answer = json.dumps({
        "screen": "live_tv", "category": "sport", "subcategory": "Soccer",
        "entity": {"home_team": "Slavia Prague", "away_team": "RC Lens", "title": "null", "season": None},
        "banner": {"channel_number": "355", "program_name": "Slavia Prague - RC Lens", "end_time": ""},
        "scoreboard": {"present": True, "bbox": [30, 40, 250, 90], "score_bbox": [120, 40, 160, 90]},
        "confidence": 0.91,
    })
    v = identify.parse(answer)
    assert v["screen"] == "live_tv" and v["category"] == "sport" and v["subcategory"] == "soccer"
    assert v["entity"] == {"home_team": "Slavia Prague", "away_team": "RC Lens"}
    assert v["banner"] == {"channel_number": "355", "program_name": "Slavia Prague - RC Lens"}
    assert v["scoreboard"]["bbox"] == [0.03, 0.04, 0.25, 0.09]


def test_parse_rejects_a_bug_box_the_model_could_not_locate():
    answer = {"screen": "live_tv", "category": "sport", "subcategory": "soccer",
              "scoreboard": {"present": True, "bbox": [0, 0, 1000, 60], "score_bbox": [100, 20, 300, 60]}}
    assert identify.parse(json.dumps(answer))["scoreboard"] is None


def test_parse_drops_category_and_entity_off_playback_and_rejects_unknown_screen():
    v = identify.parse('{"screen": "menu", "category": "sport", "entity": {"title": "X"}}')
    assert v["category"] is None and v["entity"] == {} and v["scoreboard"] is None
    assert identify.parse('{"screen": "tv_show"}') is None
    assert set(SCREENS) >= {"advertisement", "error_no_signal"}


def test_prompt_carries_prior_banner_and_known_kinds():
    prompt = identify.build_prompt(load_profiles(), previous={"screen": "live_tv", "category": "sport"},
                                   banner={"channel_number": "355"})
    assert "sport/soccer" in prompt and '"channel_number": "355"' in prompt and "Previous verdict" in prompt


# ---------------------------------------------------------------- scoreboard
@pytest.mark.parametrize("clock,minute", [("34:12", 34), ("45+2", 47), ("90'", 90), ("HT", None), (None, None)])
def test_parse_clock(clock, minute):
    assert parse_clock(clock) == minute


def _read(h, a, clock="10:00", visible=True, **extra):
    return {"visible": visible, "home_team": "SLA", "away_team": "RCL", "home_score": h, "away_score": a,
            "clock": clock, **extra}


def test_stabiliser_needs_two_reads_to_start_and_to_accept_a_goal():
    s = ScoreStabiliser("Slavia Prague", "RC Lens")
    s.feed(_read(0, 0), now=0)
    assert s.score is None
    s.feed(_read(0, 0), now=2)
    assert s.score == (0, 0) and s.status == "live"
    s.feed(_read(1, 0, "27:03"), now=4)
    assert s.score == (0, 0)  # one read is not enough
    s.feed(_read(1, 0, "27:05"), now=6)
    assert s.score == (1, 0)
    assert s.events == [{"minute": 27, "type": "goal", "home": True, "points": 1, "player": None}]
    assert s.home_team == "Slavia Prague"  # the identified names win over bug codes


def test_stabiliser_ignores_a_misread_jump_and_needs_three_reads_for_it():
    s = ScoreStabiliser()
    for t in (0, 2):
        s.feed(_read(1, 0), now=t)
    s.feed(_read(7, 0), now=4)
    s.feed(_read(1, 0), now=6)
    s.feed(_read(7, 0), now=8)
    assert s.score == (1, 0)
    for t in (10, 12, 14):
        s.feed(_read(7, 0), now=t)
    assert s.score == (7, 0) and s.events == []  # accepted, but not invented as six goals


def test_stabiliser_var_removes_last_goal_of_that_side():
    s = ScoreStabiliser()
    for t in (0, 2):
        s.feed(_read(0, 0), now=t)
    for t in (4, 6):
        s.feed(_read(0, 1, "60:00"), now=t)
    assert s.events and s.events[-1]["home"] is False
    for t in (8, 10, 12):
        s.feed(_read(0, 0, "62:00"), now=t)
    assert s.score == (0, 0) and s.events == []


def test_stabiliser_pauses_when_bug_hidden_and_clock_never_goes_back():
    s = ScoreStabiliser()
    for t in (0, 2):
        s.feed(_read(0, 0, "30:00"), now=t)
    s.feed(_read(0, 0, "29:00"), now=4)
    assert s.minute == 30
    s.feed({"visible": False}, now=6)
    assert s.status == "live"
    s.feed({"visible": False}, now=8)
    assert s.status == "paused"
    s.feed(_read(0, 0, "31:00"), now=10)
    assert s.status == "live"


def test_fixture_shape_matches_labox_and_advances_minute_with_wall_time():
    s = ScoreStabiliser("A", "B")
    for t in (0, 2):
        s.feed(_read(2, 1, "40:00"), now=t)
    f = s.fixture("id1", league="Cup", now=2 + 180)
    assert set(f) >= {"id", "league", "homeTeam", "awayTeam", "homeScore", "awayScore", "minute", "status", "events"}
    assert (f["homeScore"], f["awayScore"], f["minute"]) == (2, 1, 43)


# ---------------------------------------------------------------- enrich
def test_entity_key_needs_both_teams_for_a_match():
    assert enrich.entity_key(SOCCER, {"home_team": "Slavia Prague"}) is None
    key = enrich.entity_key(SOCCER, {"home_team": "Slavia Prague", "away_team": "RC Lens"})
    assert key.startswith("sport/soccer/slavia-prague_rc-lens/")


def test_fact_cache_parses_nulls_and_keeps_sources_and_does_not_repeat_lookups():
    calls = []

    def lookup(prompt):
        calls.append(prompt)
        return {"success": True, "content": '{"venue": "Fortuna Arena, Prague", "home_coach": "unknown"}',
                "sources": [{"url": "https://x.test", "title": "X"}]}

    cache = enrich.FactCache(lookup)
    entity = {"home_team": "Slavia Prague", "away_team": "RC Lens"}
    entry = cache.get("k", SOCCER, entity, background=False)
    assert entry["status"] == "ready"
    assert entry["facts"]["venue"] == "Fortuna Arena, Prague"
    assert entry["facts"]["home_coach"] is None and entry["facts"]["home_lineup"] is None
    assert entry["sources"] == [{"url": "https://x.test", "title": "X"}]
    cache.get("k", SOCCER, entity, background=False)
    assert len(calls) == 1 and "Do not guess" in calls[0]


def test_fact_cache_failure_is_reported_not_raised():
    cache = enrich.FactCache(lambda p: {"success": False, "error": "no web-capable profile"})
    entry = cache.get("k2", SOCCER, {"home_team": "A", "away_team": "B"}, background=False)
    assert entry["status"] == "failed" and "web-capable" in entry["error"]


# ---------------------------------------------------------------- L3: more sports, films, series
from datetime import datetime  # noqa: E402

from features.companion.lib import timewindow  # noqa: E402


def test_all_profiles_load_with_their_trackers_and_templates():
    profiles = load_profiles()
    assert {"sport/soccer", "sport/rugby", "sport/basketball", "movie", "series"} <= set(profiles)
    assert profiles["sport/rugby"].scoring_steps == {5: "try", 2: "conversion", 3: "penalty", 7: "penalty_try"}
    assert profiles["sport/basketball"].clock_up is False
    assert profiles["series"].tracker == "time_window" and profiles["series"].render == "title"
    prompt = identify.build_prompt(profiles)
    assert "- movie:" in prompt and "- sport/rugby:" in prompt and "season and episode" in prompt


def test_rugby_try_then_conversion_become_events_and_tmo_removes_a_try():
    rugby = load_profiles()["sport/rugby"]
    s = ScoreStabiliser("Toulouse", "Leinster", steps=rugby.scoring_steps)
    for t in (0, 2):
        s.feed(_read(0, 0, "12:00"), now=t)
    for t in (4, 6):
        s.feed(_read(5, 0, "14:00"), now=t)
    for t in (8, 10):
        s.feed(_read(7, 0, "15:00"), now=t)
    assert [(e["type"], e["points"]) for e in s.events] == [("try", 5), ("conversion", 2)]
    for t in (12, 14, 16):
        s.feed(_read(7, 3, "20:00"), now=t)
    assert s.events[-1]["type"] == "penalty" and s.events[-1]["home"] is False
    for t in (18, 20, 22):
        s.feed(_read(2, 3, "22:00"), now=t)       # TMO: the try is struck off
    assert [e["type"] for e in s.events] == ["conversion", "penalty"]


def test_basketball_scores_above_99_no_events_and_countdown_clock():
    bb = load_profiles()["sport/basketball"]
    s = ScoreStabiliser("LAL", "BOS", steps=bb.scoring_steps, clock_up=bb.clock_up)
    for t in (0, 2):
        s.feed(_read(98, 97, "5:32", period="Q4"), now=t)
    for t in (4, 6):
        s.feed(_read(101, 97, "5:10", period="Q4"), now=t)
    assert s.score == (101, 97) and s.events == []
    s.feed(_read(101, 97, "5:40", period="Q4"), now=8)   # a countdown clock never goes back up
    assert s.clock == "5:10"
    s.feed(_read(101, 97, "12:00", period="OT"), now=10)  # a new period restarts it
    assert s.clock == "12:00" and s.period == "OT"
    f = s.fixture("x", now=10 + 600)
    assert f["minute"] == 12 and f["period"] == "OT"      # not extrapolated on a countdown


def test_time_window_progress_and_midnight():
    now = datetime(2026, 9, 30, 21, 30)
    assert timewindow.progress("20:50", "22:45", now) == {
        "start": "20:50", "end": "22:45", "total_min": 115, "elapsed_min": 40, "remaining_min": 75}
    late = timewindow.progress("23:30", "01:10", datetime(2026, 10, 1, 0, 10))
    assert late["elapsed_min"] == 40 and late["remaining_min"] == 60
    assert timewindow.progress("18:00", "19:00", now) is None        # slot long over: stale banner
    assert timewindow.progress("bad", "19:00", now) is None


def test_same_programme_is_loose_but_not_blind():
    assert timewindow.same_programme("Lupin - Staffel 2", "Lupin")
    assert timewindow.same_programme(None, "Lupin")
    assert not timewindow.same_programme("Tagesschau", "Lupin")


def test_title_programmes_need_a_title_for_facts():
    movie = load_profiles()["movie"]
    assert enrich.entity_key(movie, {"year": "2024"}) is None
    a = enrich.entity_key(movie, {"title": "Dune: Part Two", "year": "2024"})
    assert a == enrich.entity_key(movie, {"title": "Dune: Part Two"})   # year flicker keeps the key


# ---------------------------------------------------------------- feature packaging (FEATURES.md)
from flask import Flask  # noqa: E402

from shared.src.lib.ai import usages  # noqa: E402
from shared.src.lib.utils import features as feature_discovery  # noqa: E402

COMPANION_KEYS = ("vision.companion", "vision.companion.roi", "text.web.companion")


def _app(monkeypatch, disabled):
    monkeypatch.setenv("DISABLED_FEATURES", ",".join(disabled))
    for key in COMPANION_KEYS:
        monkeypatch.delitem(usages.USAGES, key, raising=False)
    app = Flask(__name__)
    app.add_url_rule("/server/<path:endpoint>", "auto_proxy", lambda endpoint: "proxied")
    feature_discovery.register_feature_blueprints(app, "backend_server")
    return app


def _others():
    return [f["name"] for f in feature_discovery.enabled_features() if f["name"] != "companion"]


def test_enabled_feature_registers_its_route_and_ai_usages(monkeypatch):
    app = _app(monkeypatch, _others())
    assert app.url_map.bind("localhost").match("/server/companion/latest", method="POST")[0] ==         "feature_companion.latest"
    assert all(key in usages.USAGES for key in COMPANION_KEYS)
    assert "web" in usages.needs("text.web.companion")     # facts are never answered ungrounded
    for key in COMPANION_KEYS:
        usages.USAGES.pop(key, None)


def test_disabled_feature_leaves_no_route_and_no_usage(monkeypatch):
    app = _app(monkeypatch, _others() + ["companion"])
    assert "/server/companion/latest" not in {r.rule for r in app.url_map.iter_rules()}
    assert not any(key in usages.USAGES for key in COMPANION_KEYS)


def test_sources_listed_by_the_model_are_merged_with_provider_citations():
    calls = []

    def lookup(prompt):
        calls.append(prompt)
        return {"success": True, "sources": [{"url": "https://a.test", "title": "A"}],
                "content": '{"venue": "Decathlon Arena", "sources": ["https://a.test", "https://b.test/x", "not a url"]}'}

    entry = enrich.FactCache(lookup).get("k3", SOCCER, {"home_team": "LIL", "away_team": "BET"}, background=False)
    assert [s["url"] for s in entry["sources"]] == ["https://a.test", "https://b.test/x"]
    assert '"sources"' in calls[0] and "standings" in calls[0]
    assert "sources" not in entry["facts"]                       # sources are metadata, not a fact


def test_sport_profiles_ask_for_full_names_and_the_table():
    for pid in ("sport/soccer", "sport/rugby", "sport/basketball"):
        facts = load_profiles()[pid].facts
        assert {"home_team_name", "away_team_name", "standings"} <= set(facts)


# ---------------------------------------------------------------- L4a: news digest
from features.companion.lib import digest, transcript  # noqa: E402


def test_identify_reads_on_screen_text_and_knows_debate():
    v = identify.parse(json.dumps({
        "screen": "live_tv", "category": "debate", "entity": {"title": "Late Football Club"},
        "on_screen": {"lower_third": {"name": "Jean Martin", "role": "consultant"}, "headline": "Lille-Betis: the debrief",
                      "ticker": None}}))
    assert v["category"] == "debate"
    assert v["on_screen"] == {"lower_third": {"name": "Jean Martin", "role": "consultant"},
                              "headline": "Lille-Betis: the debrief", "ticker": None}
    assert identify.parse('{"screen": "menu", "on_screen": {"headline": "x"}}')["on_screen"] is None
    prompt = identify.build_prompt(load_profiles())
    assert "lower_third" in prompt and "debate =" in prompt and "- news:" in prompt


def test_an_interview_is_a_debate_in_the_prompt():
    """SRF INFO Tagesgespräch (presenter + one guest) came back as news."""
    prompt = identify.build_prompt(load_profiles())
    assert "an interview: a presenter talking" in prompt and "Tagesgespräch" in prompt
    assert "interview (a presenter with one guest" in load_profiles()["debate"].hints


def test_season_and_episode_come_from_the_banner_when_the_entity_has_none():
    """3+ The Voice: the banner showed « S1, Ep11 » and the slot; the entity kept neither."""
    v = identify.parse(json.dumps({
        "screen": "live_tv", "category": "game_show", "entity": {"title": "The Voice"},
        "banner": {"channel_name": "3+", "program_name": "The Voice", "start_time": "14:45", "end_time": "16:50",
                   "episode": "S1, Ep11", "next_program": "Bachelor S2, Ep3"}}))
    assert v["entity"] == {"title": "The Voice", "season": "1", "episode": "11"}
    assert v["banner"]["start_time"] == "14:45" and v["banner"]["episode"] == "S1, Ep11"
    for text, se in (("Tatort S2 E7", ("2", "7")), ("Staffel 2, Folge 7", ("2", "7")),
                     ("Saison 3 Épisode 4", ("3", "4"))):
        v = identify.parse(json.dumps({"screen": "live_tv", "category": "series", "entity": {"title": "X"},
                                       "banner": {"program_name": text}}))
        assert (v["entity"]["season"], v["entity"]["episode"]) == se, text
    # the next programme's episode is not this one's; a model answer wins over the banner
    v = identify.parse(json.dumps({"screen": "live_tv", "category": "kids", "entity": {"title": "Pinguine"},
                                   "banner": {"program_name": "Pinguine", "next_program": "Pinky S2, Ep2"}}))
    assert "season" not in v["entity"]
    v = identify.parse(json.dumps({"screen": "live_tv", "category": "series",
                                   "entity": {"title": "X", "season": "4", "episode": "1"},
                                   "banner": {"episode": "S1, Ep11"}}))
    assert (v["entity"]["season"], v["entity"]["episode"]) == ("4", "1")
    assert "episode as printed ('S1, Ep11')" in identify.build_prompt(load_profiles())


def test_recent_lines_spans_chunks_and_keeps_only_the_window(tmp_path):
    def write(hour, index, segs):
        (tmp_path / f"{hour}_{index}.json").write_text(json.dumps({"segments": segs}))
    write(13, 4, [{"start": 590, "text": "old but in window"}, {"start": 100, "text": "too old"}])
    write(13, 5, [{"start": 20, "text": "first"}, {"start": 50, "text": "second"}, {"start": 400, "text": "future"}])
    now = datetime(2026, 9, 30, 13, 51, 0)                 # chunk 5 started 13:50
    lines = transcript.recent_lines(lambda h, i: str(tmp_path / f"{h}_{i}.json"), 120, now)
    assert [l["text"] for l in lines] == ["old but in window", "first", "second"]


def test_news_digest_parse_and_rolling_merge():
    parsed = digest.parse_news('{"stories": [{"headline": "Storm hits Brittany", "summary": "Red alert.",'
                               ' "people": [], "places": ["Brittany"], "orgs": ["Meteo-France"]},'
                               ' {"headline": ""}], "sensitive": {"flag": false, "reason": null}}')
    assert len(parsed["stories"]) == 1 and parsed["sensitive"] == {"flag": False, "reason": None}
    first = digest.merge_stories([], [{"headline": "A story"}, {"headline": "B story"}], at=1)
    assert [s["headline"] for s in first] == ["A story", "B story"]            # model order kept
    again = digest.merge_stories(first, [{"headline": "B story, update"}, {"headline": "C story"}], at=2)
    assert [s["headline"] for s in again] == ["B story, update", "C story", "A story"]
    assert again[0]["first_seen"] == 1 and again[0]["updated"] == 2           # same story, updated
    prompt = digest.build_news_prompt([{"t": 0, "text": "bonjour"}], [(1, "Headline X")], first)
    assert "NOISY" in prompt and "ON SCREEN: Headline X" in prompt and "- A story" in prompt


def test_digest_timeline_puts_captions_between_the_lines_they_separate():
    """SRF INFO 2026-09-30 15:27: the weather forecast, then Judith Huber's caption, then the interview.
    Untimed, the model credited the forecast to her; the timeline keeps the order and the times."""
    t0 = datetime(2026, 9, 30, 15, 25, 0).timestamp()
    lines = [{"t": t0, "text": "Wolken und Regen"}, {"t": t0 + 10, "text": "am Sonntag sonnig"},
             {"t": t0 + 70, "text": "die Lage in der Ukraine"}]
    shown = [(t0 + 60, "Judith Huber, Osteuropa-Korrespondentin SRF (on screen)")]
    text = digest.timeline(lines, shown, [(t0 + 75, "Die Menschen frieren.")])
    assert text.split("\n") == [
        "[15:25:00] SPEECH (noisy): Wolken und Regen am Sonntag sonnig",
        "[15:26:00] ON SCREEN: Judith Huber, Osteuropa-Korrespondentin SRF (on screen)",
        "[15:26:10] SPEECH (noisy): die Lage in der Ukraine",
        "[15:26:15] SUBTITLE: Die Menschen frieren.",
    ]
    # a caption inside a run of speech cuts the paragraph
    cut = digest.timeline([{"t": t0, "text": "a"}, {"t": t0 + 10, "text": "b"}], [(t0 + 5, "X Y (on screen)")])
    assert cut.count("SPEECH") == 2
    assert "within 30 s after their caption" in digest.build_news_prompt(lines, shown, [])


# ---------------------------------------------------------------- L4b: captions + debate digest
from features.companion.lib import captions  # noqa: E402


def test_captions_parse_and_strap_timeline_tolerate_a_misread():
    found = captions.parse('{"captions": [{"kind": "name", "text": "Jean Martin", "role": "consultant"},'
                           ' {"kind": "strap", "text": "PAS DE RONALDO : NOUVEL IMBROGLIO ?"}, {"kind": "weird", "text": ""}]}')
    assert found == [{"kind": "name", "text": "Jean Martin", "name": "Jean Martin", "role": "consultant"},
                     {"kind": "strap", "text": "PAS DE RONALDO : NOUVEL IMBROGLIO ?", "name": None, "role": None}]
    assert captions.same_text("NOUVEL IMBROGLO ?", "NOUVEL IMBROGLIO ?")
    assert not captions.same_text("MBAPPE FORFAIT", "NOUVEL IMBROGLIO")
    tl = captions.add_to_timeline([], "PAS DE RONALDO : NOUVEL IMBROGLIO ?", 1)
    tl = captions.add_to_timeline(tl, "PAS DE RONALDO : NOUVEL IMBROGLO ?", 5)      # same strap, misread
    tl = captions.add_to_timeline(tl, "MBAPPE FORFAIT CONTRE LE REAL ?", 9)
    assert [t["text"] for t in tl] == ["MBAPPE FORFAIT CONTRE LE REAL ?", "PAS DE RONALDO : NOUVEL IMBROGLIO ?"]
    assert tl[1]["last_seen"] == 5


def test_debate_digest_parse_and_claim_merge():
    parsed = digest.parse_debate('{"topic": "Ronaldo absent", "positions": [{"speaker": "null", "stance": "Crisis"}],'
                                 ' "claims": [{"text": "He missed 3 sessions", "speaker": "Jean Martin", "checkable": true}]}')
    assert parsed["positions"] == [{"speaker": None, "stance": "Crisis"}]
    merged = digest.merge_claims([], parsed["claims"], at=1)
    again = digest.merge_claims(merged, [{"text": "He missed 3 sessions!", "speaker": None, "checkable": True},
                                         {"text": "The club fined him", "speaker": None, "checkable": True}], at=2)
    assert [c["text"] for c in again] == ["The club fined him", "He missed 3 sessions"]
    prompt = digest.build_debate_prompt([], [{"name": "Jean Martin", "role": "consultant"}], ["STRAP"], merged)
    assert "Jean Martin, consultant" in prompt and "STRAP" in prompt and "- He missed 3 sessions" in prompt


def test_logo_or_programme_is_not_a_speaker():
    assert captions.is_person("Jean Martin", ["L'EQUIPE DU SOIR"])
    assert not captions.is_person("L'ÉQUIPE 7 du Soir", ["L'EQUIPE DU SOIR"])
    assert not captions.is_person("Ronaldo", [])                  # one word: not a caption name
    assert "never a programme" in captions.CAPTIONS_PROMPT


def test_speaker_filter_on_what_lequipe_du_soir_really_returned():
    seen = ["LE SHOW YAMAL", "L'ÉQUIPE DU SOIR", "LA PREUVE EN IMAGE"]
    assert captions.is_person("Ludovic Obraniak", seen)
    assert not captions.is_person("OLISE GOLAZO (LA PREUVE EN IMAGE)", seen)   # brackets: a clip title
    assert not captions.is_person("L'ÉQUIPE DU SOIR", seen)                    # the show logo
    assert not captions.is_person("QUI EST LE MEILLEUR ?", [])                 # a question strap


def test_channel_idents_are_not_speakers():
    """SRF INFO's radio simulcast shows « * Audio Radio SRF 1 * »; it entered the speaker list."""
    assert not captions.is_person("Audio Radio SRF 1", [])
    assert not captions.is_person("Audio Radio SRF", [])
    assert not captions.is_person("* Judith Huber *", [])
    assert not captions.is_person("SRF Meteo Team", [])
    assert captions.is_person("Judith Huber", [])
    assert captions.is_person("Simon Eschle", [])


def test_ocr_variants_of_one_strap_are_the_same_text():
    a = "LA COMPO DE LUDOVIC OBRANIAC FACE À L'ITALIE"
    assert captions.same_text(a, "LA COMPO DE LUDOVIC OBRANIAT FACE À L'ITALIE")
    assert captions.same_text(a, "LA COMPO DE LUDOVIC OBRANI AK FACE À L'ITALIE")
    assert not captions.same_text(a, "QUELS BLEUS D'ENTRÉE CONTRE L'ITALIE ?")


def test_every_programme_category_has_a_profile():
    from features.companion.lib.profiles import CATEGORIES
    covered = {p.category for p in load_profiles().values()}
    # 'other' is deliberately bare; everything else gets facts and a card.
    assert covered >= set(CATEGORIES) - {"other"}
    assert load_profiles()["game_show"].render == "title" and "jury" in load_profiles()["game_show"].facts


def test_speakers_are_checked_against_caption_times_on_real_srf_club_lines():
    """SRF INFO « Club », 2026-10-01 16:06: gpt-4.1-mini credited Jack Straw (caption 16:06:18) with the
    « 435 Sitze » lines said at 16:07:06 by the presenter. Only lines within 30 s of a caption keep him."""
    t = lambda hms: datetime(2026, 10, 1, *map(int, hms.split(":"))).timestamp()
    subs = [(t("16:05:41"), "(Colpi) Trump hat diese Tendenz, die es vorher auch schon gab,"),
            (t("16:06:25"), "Er ist natürlich sehr narzisstisch und meinte, er kann alles regeln."),
            (t("16:06:34"), "Amerika ist in einer Zeitenwende seit Jahrzehnten."),
            (t("16:07:06"), "435 Sitze im Repräsentantenhaus,"),
            (t("16:07:12"), "ein Drittel der Sitze im Senat werden neu gewählt, werden neu bestellt.")]
    marks = digest.speaker_marks({"Jack Straw": [t("16:06:18")]}, subs)
    assert set(marks) == {"straw", "colpi"}
    claims = [{"text": "435 Sitze im Repräsentantenhaus und ein Drittel der Sitze im Senat werden neu gewählt.",
               "speaker": "Jack Straw"},
              {"text": "Trump hat diese Tendenz verstärkt", "speaker": "Colpi"},
              {"text": "Something nobody said at all", "speaker": "Jack Straw"},
              {"text": "435 Sitze", "speaker": None}]
    checked = digest.check_speakers(claims, "text", subs, marks)
    assert [c["speaker"] for c in checked] == [None, "Colpi", None, None]
    stance = [{"stance": "Trump ist narzisstisch und glaubt, er könne alles regeln", "speaker": "Jack Straw"}]
    assert digest.check_speakers(stance, "stance", subs, marks)[0]["speaker"] == "Jack Straw"


# ---------------------------------------------------------------- L4c: fact check
from features.companion.lib import factcheck  # noqa: E402


def test_factcheck_verdict_needs_a_source():
    ok = factcheck.parse('{"verdict": "supported", "note": "435 seats are up every two years.",'
                         ' "sources": ["https://www.house.gov/elections"]}', [])
    assert ok == {"verdict": "supported", "note": "435 seats are up every two years.",
                  "sources": [{"url": "https://www.house.gov/elections", "title": ""}]}
    # the provider's own citations count too
    # unverified keeps no pages: they did not settle the claim
    assert factcheck.parse('{"verdict": "unverified", "note": "nothing found",'
                           ' "sources": ["https://support.google.com/x"]}', [])["sources"] == []
    cited = factcheck.parse('{"verdict": "contradicted", "note": "x"}', [{"url": "https://a.test", "title": "A"}])
    assert cited["verdict"] == "contradicted" and cited["sources"][0]["url"] == "https://a.test"
    # no page, no verdict
    assert factcheck.parse('{"verdict": "contradicted", "note": "I think not"}', [])["verdict"] == "unverified"
    assert factcheck.parse('{"verdict": "false", "sources": ["https://a.test"]}', [])["verdict"] == "unverified"
    assert factcheck.parse("no json", []) is None
    prompt = factcheck.build_prompt("435 Sitze werden neu gewählt", "Jack Straw", "Club", topic="US-Zwischenwahlen")
    assert "« 435 Sitze werden neu gewählt »" in prompt and "Jack Straw" in prompt and "Club" in prompt
    assert "The discussion is about: US-Zwischenwahlen" in prompt


def test_factcheck_runs_once_per_claim_and_respects_the_hourly_cap():
    calls = []
    checker = factcheck.FactChecker(lambda prompt: calls.append(prompt) or {
        "success": True, "content": '{"verdict": "supported", "note": "ok", "sources": ["https://s.test"]}'},
        per_hour=2)
    for i, text in enumerate(["Claim one is true", "claim one is TRUE!", "Claim two", "Claim three"]):
        checker.request("device4", text, None, "Club", now=100 + i, background=False)
    assert len(calls) == 2                                          # the repeat is the same claim
    assert checker.get("Claim one is true")["verdict"] == "supported"
    assert checker.get("Claim three")["status"] == "capped"
    checker.request("device4", "Claim four", None, "Club", now=100 + 3600, background=False)   # an hour later
    assert len(calls) == 3 and checker.get("Claim four")["status"] == "done"
    checker.request("device2", "Claim five", None, "X", now=101, background=False)              # per device
    assert checker.get("Claim five")["status"] == "done"
    failing = factcheck.FactChecker(lambda p: {"success": False, "error": "no web hop"})
    failing.request("device4", "Something", None, None, background=False)
    assert failing.get("Something")["status"] == "failed"


def test_factcheck_usage_inherits_the_web_requirement():
    from shared.src.lib.ai import usages
    from features.companion.lib.usages import FACTCHECK, register_usages
    register_usages()
    assert "web" in usages.needs(FACTCHECK)


# ---------------------------------------------------------------- sentence meter (TASK-45)
def test_sentence_joiner_joins_fragments_until_terminal_punctuation():
    from features.companion.lib.meter import SentenceJoiner
    j = SentenceJoiner()
    j.feed(100.0, "Les 435 sièges sont renouvelés")
    j.feed(100.5, "et un tiers du Sénat")
    j.feed(101.0, "tous les deux ans.")
    assert j.parts == []  # already flushed on the terminal '.'
    out = j.drain(102.0)
    assert len(out) == 1
    assert out[0]["text"].endswith("deux ans.")
    assert out[0]["prefix_speaker"] is None
    assert out[0]["t"] == 100.0  # first fragment time


def test_sentence_joiner_question_mark_and_ellipsis_boundary():
    from features.companion.lib.meter import SentenceJoiner
    j = SentenceJoiner()
    j.feed(0.0, "Vraiment pas ?")
    assert j.drain(0.5) == [{"t": 0.0, "text": "Vraiment pas ?", "prefix_speaker": None, "end_at": 0.0}]
    j.feed(10.0, "il dit que…")
    assert [x["text"] for x in j.drain(10.5)] == ["il dit que…"]  # the ellipsis ends a sentence


def test_sentence_joiner_flushes_after_eight_s_of_silence():
    from features.companion.lib.meter import SentenceJoiner
    j = SentenceJoiner()
    j.feed(0.0, "Die 435 Sitze werden neu gewählt")
    assert j.drain(1.0) == []  # 1 s: still building
    out = j.drain(8.5)  # 8 s of silence: flush
    assert len(out) == 1 and out[0]["text"].endswith("gewählt")
    j.feed(20.0, "und ein Drittel des Senats.")
    out = j.drain(20.5)
    assert len(out) == 1 and out[0]["text"].endswith("Senats.")


def test_sentence_joiner_strips_srf_name_prefix():
    from features.companion.lib.meter import SentenceJoiner
    j = SentenceJoiner()
    j.feed(0.0, "(Jack Straw) The 435 seats are renewed")
    j.feed(0.5, "every two years.")
    out = j.drain(1.0)
    assert len(out) == 1
    assert out[0]["text"] == "The 435 seats are renewed every two years."
    assert out[0]["prefix_speaker"] == "Jack Straw"
    # Continuation fragment: no second (Name) prefix allowed
    j.feed(5.0, "And it has always been so.")
    out = j.drain(5.5)
    assert out[0]["prefix_speaker"] is None


def test_parse_answers_speaker_above_threshold_is_kept():
    from features.companion.lib.meter import parse_answers
    out = {"answers": {
        "factual_claim": {"type": "noul", "noul": 0.9},
        "evasive": {"type": "noul", "noul": 0.1},
        "contradicts_self": {"type": "noul", "noul": 0.0},
        "emotional_appeal": {"type": "noul", "noul": 0.3},
        "dodged_question": {"type": "noul", "noul": 0.05},
        "speaker": {"type": "choice", "choice": "Jack Straw",
                    "probabilities": {"Jack Straw": 0.8, "unknown": 0.2}}}}
    parsed = parse_answers(out)
    assert parsed["speaker"] == "Jack Straw"
    assert parsed["speaker_p"] == 0.8
    assert parsed["scores"]["factual_claim"] == 0.9
    assert parsed["scores"]["evasive"] == 0.1


def test_parse_answers_speaker_below_threshold_is_none():
    from features.companion.lib.meter import parse_answers
    out = {"answers": {
        "factual_claim": {"type": "noul", "noul": 0.5},
        "speaker": {"type": "choice", "choice": "Jack Straw",
                    "probabilities": {"Jack Straw": 0.45, "unknown": 0.55}}}}
    parsed = parse_answers(out)
    assert parsed["speaker"] is None
    assert parsed["speaker_p"] is None


def test_parse_answers_drops_bad_or_missing_scores_and_never_raises():
    from features.companion.lib.meter import parse_answers
    assert parse_answers({})["scores"] == {}
    assert parse_answers({"answers": {"factual_claim": {"type": "noul", "noul": "x"}}})["scores"] == {}
    assert parse_answers({"answers": {"factual_claim": {"type": "noul", "noul": 1.5}}})["scores"] == {}
    assert parse_answers(None)["scores"] == {}  # never raises


def test_meter_averages_and_index():
    from features.companion.lib.meter import Meter
    m = Meter()
    m.add({"text": "a", "scores": {"factual_claim": 0.0, "evasive": 0.4, "contradicts_self": 0.0,
                                    "emotional_appeal": 0.6, "dodged_question": 0.0}, "speaker": "A",
           "t": 0.0, "end_at": 0.0, "ms": 100})
    m.add({"text": "b", "scores": {"factual_claim": 0.0, "evasive": 0.2, "contradicts_self": 0.0,
                                    "emotional_appeal": 0.2, "dodged_question": 0.0}, "speaker": "A",
           "t": 0.0, "end_at": 0.0, "ms": 200})
    m.add({"text": "c", "scores": {"factual_claim": 0.0, "evasive": 0.0, "contradicts_self": 0.0,
                                    "emotional_appeal": 0.0, "dodged_question": 1.0}, "speaker": "B",
           "t": 0.0, "end_at": 0.0, "ms": 300})
    p = m.payload()
    # Sentences newest-first, including check=None
    assert [s["text"] for s in p["sentences"]] == ["c", "b", "a"]
    # Per-speaker averages, with A first (2 sentences > B "1")
    names = [s["name"] for s in p["speakers"]]
    assert names[0] == "A"
    a = p["speakers"][0]
    assert a["n"] == 2
    # A averages: evasive=0.3, contradicts_self=0, emotional_appeal=0.4, dodged_question=0
    # mean of (0.3, 0, 0.4, 0) = 0.175 → index = round(100 * 0.175) = 18
    assert a["index"] == 18
    # B: only dodged_question=1 → mean of (0, 0, 0, 1) = 0.25 → index = 25
    assert p["speakers"][1]["index"] == 25


def test_known_people_round_trip_and_corrupt_file(tmp_path):
    from features.companion.lib.meter import KnownPeople, programme_key
    p = tmp_path / "kp.json"
    kp = KnownPeople(str(p))
    kp.add("L'Équipe du Soir", "Jack Straw", "Minister", 1000.0)
    kp.add("Le Grand Débat", "Jane Doe", "Sénatrice", 2000.0)
    assert programme_key("L'Équipe du Soir") == programme_key("Lequipe du Soir") == "lequipedusoir"
    # Re-open and read: same store
    kp2 = KnownPeople(str(p))
    got = {person["name"]: person for person in kp2.get("L'Équipe du Soir")}
    assert got["Jack Straw"]["role"] == "Minister" and got["Jack Straw"]["seen"] == 1
    # Corrupt file is treated as empty, recovered on the next add
    p.write_text("not json at all {")
    kp3 = KnownPeople(str(p))
    assert kp3.get("L'Équipe du Soir") == []
    kp3.add("L'Équipe du Soir", "John", "MP", 5000.0)
    assert {p["name"] for p in kp3.get("L'Équipe du Soir")} == {"John"}


def test_speaker_options_say_when_each_caption_was_shown():
    """Replayed SRF « Club » lines (2026-10-05): with bare roles Jev chose "unknown" for a guest 7 s after
    his caption; with the caption age in the option it picked him (0.83)."""
    from features.companion.lib import meter
    known = [{"name": "Jack Straw", "role": "Politikwissenschaftler"}, {"name": "Barbara Lüthi", "role": "Moderatorin"}]
    q = meter.speaker_question(known, [{"name": "Jack Straw", "age_s": 7}, {"name": "Barbara Lüthi", "age_s": 400}])
    assert q["type"] == "choice" and set(q["criteria"]) == {"Jack Straw", "Barbara Lüthi", "unknown"}
    assert "shown 7 s before this sentence" in q["criteria"]["Jack Straw"]
    assert "no name caption for them in the last 90 s" in q["criteria"]["Barbara Lüthi"]
    assert "starts speaking" in q["instructions"]
    assert meter.speaker_question([], []) is None


def test_transcript_skips_yesterdays_chunk_and_the_joiner_drops_non_sentences(tmp_path):
    """stb4, 2026-10-05 13:00: the new 13:00 chunk was not written yet, and yesterday's file in the 24 h
    ring (French, another channel) was read as BBC News. Also "..." was scored as a sentence."""
    import os
    from features.companion.lib.meter import SentenceJoiner
    now = datetime(2026, 10, 5, 13, 1, 0)
    old = tmp_path / "13_0.json"
    old.write_text(json.dumps({"segments": [{"start": 10, "text": "Le directeur sportif."}]}))
    yesterday = (now.timestamp() - 86400)
    os.utime(old, (yesterday, yesterday))
    lines = transcript.recent_lines(lambda h, i: str(tmp_path / f"{h}_{i}.json"), 120, now)
    assert lines == []
    os.utime(old, (now.timestamp(), now.timestamp()))            # written this hour: read
    assert [l["text"] for l in transcript.recent_lines(lambda h, i: str(tmp_path / f"{h}_{i}.json"), 120, now)] \
        == ["Le directeur sportif."]
    j = SentenceJoiner()
    j.feed(0, "...")
    j.feed(1, "Yes.")
    j.feed(2, "The Senate will be elected.")
    assert [s["text"] for s in j.drain(20)] == ["The Senate will be elected."]
