"""Screen memory (TASK-84): fingerprint, match, trust, votes, worker rule and back-off."""
from datetime import datetime, timedelta, timezone

import numpy as np

from backend_server.src.agent.core import nightwatch_handler as nw
from shared.src.lib import screen_memory as sm

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def _desktop(seed=1, noise=0):
    rng = np.random.default_rng(seed)
    img = (rng.random((90, 160, 3)) * 255).astype(np.uint8)
    if noise:
        img[:2, :20] = 255 - img[:2, :20]  # a few pixels (a clock) change
    return img


def test_flat_frame_is_not_keyable():
    assert sm.fingerprint_frame(np.zeros((90, 160, 3), np.uint8)) is None
    assert sm.fingerprint_frame(None) is None


def test_same_screen_matches_and_a_different_one_does_not():
    a = sm.fingerprint_frame(_desktop(1))
    row = {"id": "r1", **a}
    hit = sm.match_screen(sm.fingerprint_frame(_desktop(1, noise=1)), [row])
    assert hit and hit[0]["id"] == "r1" and hit[1] <= 12
    assert sm.match_screen(sm.fingerprint_frame(_desktop(2)), [row]) is None


def test_match_needs_full_and_center_both_tight(monkeypatch):
    a = sm.fingerprint_frame(_desktop(1))
    other = sm.fingerprint_frame(_desktop(2))
    mixed = {"dhash": a["dhash"], "region_center": other["region_center"]}  # same frame, other centre
    assert sm.match_screen(mixed, [{"id": "r", **a}]) is None


def test_ai_votes_trust_and_bad_is_sticky(monkeypatch):
    monkeypatch.setenv("ALERT_SCREEN_AI_VOTES", "2")
    row = {"id": "s", "verdict": "unknown", "source": "none", "ai_votes_expected": 0, "ai_votes_bad": 0}
    row.update(sm.apply_ai_verdict(row, "expected"))
    assert row["verdict"] == "unknown" and not sm.is_trusted_expected(row)
    row.update(sm.apply_ai_verdict(row, "false_alarm"))
    assert sm.is_trusted_expected(row)
    row.update(sm.apply_ai_verdict(row, "real"))  # one real alert makes it bad and clears the votes
    assert row["verdict"] == "bad" and row["ai_votes_expected"] == 0
    row.update(sm.apply_ai_verdict(row, "expected"))
    row.update(sm.apply_ai_verdict(row, "expected"))
    assert row["verdict"] == "bad"  # only a human turns a bad screen back


def test_human_verdict_is_never_overwritten():
    row = {"verdict": "expected", "source": "human", "ai_votes_expected": 0, "ai_votes_bad": 0}
    assert sm.apply_ai_verdict(row, "real") == {}


def test_audit_every_nth_sighting(monkeypatch):
    monkeypatch.setenv("ALERT_SCREEN_AUDIT_EVERY", "20")
    assert sm.should_audit({"seen_count": 40}) and not sm.should_audit({"seen_count": 41})
    monkeypatch.setenv("ALERT_SCREEN_AUDIT_EVERY", "0")
    assert not sm.should_audit({"seen_count": 40})


def _alert(**kw):
    return dict(id="a1", host_name="vpt-pi4", device_id="host", incident_type=kw.get("kind", "freeze"),
                start_time=T0.isoformat(), end_time=None, metadata={"screen_id": "s1", "screen_dist": 3},
                device_name="host")


def _handler(monkeypatch, mode):
    monkeypatch.setenv("ALERT_SCREEN_MEMORY", mode)
    return nw.NightwatchHandler()


def _screen(**kw):
    return {"id": "s1", "incident_type": "freeze", "verdict": "expected", "source": "ai", "seen_count": 5, **kw}


def test_worker_discards_trusted_screen_only_in_on_mode(monkeypatch):
    assert _handler(monkeypatch, "on").decide(_alert(), {}, 0, _screen())[0] == "fingerprint"
    assert _handler(monkeypatch, "dryrun").decide(_alert_img(), {}, 0, _screen()) is None
    assert _handler(monkeypatch, "off").decide(_alert_img(), {}, 0, _screen()) is None


def test_worker_does_not_discard_other_type_unknown_or_audit(monkeypatch):
    h = _handler(monkeypatch, "on")
    assert h.decide(_alert_img(kind="blackscreen"), {}, 0, _screen()) is None
    assert h.decide(_alert_img(), {}, 0, _screen(verdict="unknown")) is None
    assert h.decide(_alert_img(), {}, 0, _screen(seen_count=20)) is None  # 20th sighting is audited


def test_failed_model_blocks_calls_and_counts_toward_cap(monkeypatch):
    h = _handler(monkeypatch, "off")
    h._model_failed()
    assert h._model_blocked() and h._backoff_s == 60 and h._failed_today == 1
    h._model_failed()
    assert h._backoff_s == 120
    h._model_ok()
    assert not h._model_blocked() and h._backoff_s == 0


def _alert_img(end_after_s=None, **kw):
    a = _alert(**kw)
    a["metadata"]["r2_images"] = {"thumbnail_r2_paths": ["alerts/freeze/c1/t_0.jpg"]}
    if end_after_s is not None:
        a["end_time"] = (T0 + timedelta(seconds=end_after_s)).isoformat()
    return a


def test_trusted_screen_discards_a_flapping_short_alert(monkeypatch):
    h = _handler(monkeypatch, "on")
    assert h.decide(_alert_img(end_after_s=5), {}, 0, _screen())[0] == "fingerprint"  # before `short`


def test_unknown_screen_is_judged_even_when_short_or_a_repeat(monkeypatch):
    h = _handler(monkeypatch, "dryrun")
    unknown = _screen(verdict="unknown", source="none")
    last = {("vpt-pi4", "host", "freeze"): {"id": "p", "start_time": T0.isoformat(), "discard": True}}
    assert h.decide(_alert_img(end_after_s=5), last, 0, unknown) is None  # not skipped: it teaches the memory
    # without memory the same alert is skipped as before
    assert h.decide(_alert_img(end_after_s=5), last, 0, None)[0] == "short"
    # a screen seen once is random so far: it keeps the cost rules
    assert h.decide(_alert_img(end_after_s=5), last, 0, _screen(verdict="unknown", source="none", seen_count=1))[0] == "short"


def test_learning_needs_an_image_and_ignores_bad_or_human_screens(monkeypatch):
    h = _handler(monkeypatch, "on")
    unknown = _screen(verdict="unknown", source="none")
    assert h.decide(_alert(), {}, 0, unknown)[0] == "no_frame"  # no frame: nothing for the model to judge, no bypass...
    assert h.decide(_alert(), {}, 0, None)[0] == "no_frame"
    short_no_img = _alert(); short_no_img["end_time"] = (T0 + timedelta(seconds=5)).isoformat()
    assert h.decide(short_no_img, {}, 0, unknown)[0] == "short"
    assert h.decide(_alert_img(end_after_s=5), {}, 0, _screen(verdict="bad", source="ai"))[0] == "short"
    assert h.decide(_alert_img(end_after_s=5), {}, 0, _screen(verdict="unknown", source="human"))[0] == "short"


def test_a_screen_is_recurring_from_keep_min_seen_sightings(monkeypatch):
    monkeypatch.setenv("ALERT_SCREEN_KEEP_MIN_SEEN", "3")
    assert not sm.is_recurring(None)
    assert not sm.is_recurring({"seen_count": 2})
    assert sm.is_recurring({"seen_count": 3})
    assert sm.is_recurring({"seen_count": 1}, seen=3)  # the alert's own sighting number wins over a stale row


def _sparse_desktop(seed=7, clock=0):
    """A flat navy frame with a handful of icon-like blocks: few dHash set bits, like the labox-web VNC desktop."""
    rng = np.random.default_rng(seed)
    img = np.full((720, 1280, 3), (40, 30, 20), np.uint8)
    for _ in range(6):
        y, x = int(rng.integers(40, 650)), int(rng.integers(20, 1200))
        img[y:y + 50, x:x + 60] = rng.integers(60, 255, 3)
    img[8:18, 1030 + clock:1075 + clock] = (230, 230, 230)  # the clock text moves a little
    return img


def test_sparse_flat_desktop_is_keyable_and_matches_itself_across_clock_changes():
    fp = sm.fingerprint_frame(_sparse_desktop())
    assert fp is not None and 8 <= sm.dhash_popcount(fp["dhash"]) < 20  # used to be rejected as "flat"
    row = {"id": "d", **fp}
    assert sm.match_screen(sm.fingerprint_frame(_sparse_desktop(clock=3)), [row]) is not None


def test_sparse_screens_with_a_different_layout_do_not_match():
    row = {"id": "d", **sm.fingerprint_frame(_sparse_desktop(seed=7))}
    for seed in (8, 9, 10, 11):
        other = sm.fingerprint_frame(_sparse_desktop(seed=seed))
        assert other is None or sm.match_screen(other, [row]) is None


def test_human_discard_and_keep_teach_the_screen(monkeypatch):
    from backend_server.src.routes import server_alerts_routes as routes
    from shared.src.lib.database import screen_fingerprints_db as sdb
    calls = []
    monkeypatch.setattr(routes, "get_alert_by_id", lambda i: {"metadata": {"screen_id": "s9"}} if i == "a" else {"metadata": {}})
    monkeypatch.setattr(sdb, "set_human_verdict", lambda s, e, a: calls.append((s, e, a)))
    routes._teach_screen_memory("a", True, "manual")      # person discards -> expected
    routes._teach_screen_memory("a", False, "manual")     # person keeps -> bad
    routes._teach_screen_memory("a", True, "ai")          # the model's own write is not a human verdict
    routes._teach_screen_memory("b", True, "manual")      # alert without a screen id
    assert calls == [("s9", True, "a"), ("s9", False, "a")]


def test_audit_uses_the_alerts_own_sighting_number(monkeypatch):
    monkeypatch.setenv("ALERT_SCREEN_AUDIT_EVERY", "20")
    row = {"seen_count": 37}  # the row moved on while the worker was busy
    assert sm.should_audit(row, 20) and not sm.should_audit(row, 21)
    assert sm.should_audit({"seen_count": 40}) and not sm.should_audit({"seen_count": 37})  # no stamp: old behaviour


def test_worker_audits_on_the_alerts_stamped_sighting(monkeypatch):
    h = _handler(monkeypatch, "on")
    a = _alert_img(); a["metadata"]["screen_seen"] = 20
    assert h.decide(a, {}, 0, _screen(seen_count=55)) is None                      # audit sighting: goes to the model
    a["metadata"]["screen_seen"] = 21
    assert h.decide(a, {}, 0, _screen(seen_count=40))[0] == "fingerprint"          # row says 40, alert says 21


def test_audit_sighting_bypasses_short_and_repeat(monkeypatch):
    h = _handler(monkeypatch, "on")
    last = {("vpt-pi4", "host", "freeze"): {"id": "p", "start_time": T0.isoformat(), "discard": True}}
    a = _alert_img(end_after_s=5); a["metadata"]["screen_seen"] = 40
    assert h.decide(a, last, 0, _screen(seen_count=80)) is None                    # audited: reaches the model
    a["metadata"]["screen_seen"] = 41
    assert h.decide(a, last, 0, _screen(seen_count=80))[0] == "fingerprint"       # ordinary sighting: discarded
