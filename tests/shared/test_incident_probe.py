"""TASK-158: last key correlation and the wake probe (fixtures: standby, splash, real fault, busy, cooldown, send failure)."""
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from backend_server.src.agent.core import incident_probe as ip
from backend_server.src.agent.core import nightwatch_handler as nw
from shared.src.lib.utils.last_key import last_key_event

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _jpg(value=0, noise=False):
    img = np.full((72, 128, 3), value, np.uint8)
    if noise:
        img[::2, ::2] = 255 - value
        img[:20, :40] = 200
    return cv2.imencode(".jpg", img)[1].tobytes()


BLACK, PICTURE = _jpg(0), _jpg(30, noise=True)


def _alert(kind="blackscreen", host="vpt-mf1", device="device1", end=None, meta=None):
    return dict(id="a1", host_name=host, device_id=device, device_name="stbv1", incident_type=kind,
                start_time=T0.isoformat(), end_time=end, metadata=meta or {})


def _cfg(mode="on", **kw):
    return ip.ProbeConfig(mode=mode, devices={"vpt-mf1/device1": "OK"}, settle_s=0, **kw)


class Rig:
    def __init__(self, send=(True, ""), after=PICTURE):
        self.sent, self.send, self.after = [], send, after

    def send_key(self, host, device, key):
        self.sent.append((host, device, key))
        return self.send

    def capture(self, host, device):
        return self.after

    def run(self, alert, before, cfg=None):
        return ip.run_probe(alert, "OK", cfg or _cfg(), before=before, is_blank=nw.is_blank_frame,
                            send_key=self.send_key, capture=self.capture, sleep=lambda s: None, now=T0)


# ---- last key -------------------------------------------------------------------------------
def test_last_key_event_reads_the_host_stamp():
    meta = {"last_key": {"at": (T0 - timedelta(minutes=42)).isoformat().replace("+00:00", "Z"),
                         "source": "executor", "key": "OK"}}
    ev = last_key_event(_alert(meta=meta))
    assert ev["source"] == "script" and ev["key"] == "OK" and ev["seconds_before_alert"] == 42 * 60


def test_last_key_event_is_none_without_a_record():
    assert last_key_event(_alert()) is None
    assert last_key_event(_alert(meta={"last_key": {"at": "garbage"}})) is None


def test_facts_name_standby_candidate_and_key_before_freeze(monkeypatch):
    black = _alert(meta={"seconds_since_last_key": 2700, "last_key_source": "remote"})
    assert "expected-candidate" in "\n".join(nw.last_key_lines(black))
    freeze = _alert(kind="freeze", meta={"seconds_since_last_key": 5, "last_key_source": "script"})
    assert "real fault" in "\n".join(nw.last_key_lines(freeze))
    assert nw.last_key_lines(_alert()) == []


# ---- configuration and safety ---------------------------------------------------------------
def test_off_by_default_and_unlisted_device_never_probed(monkeypatch):
    monkeypatch.delenv("ALERT_PROBE_MODE", raising=False)
    assert ip.load_config().mode == "off"
    assert ip.candidate(_alert(), "blank_frame", ip.ProbeConfig()) is None
    assert ip.candidate(_alert(device="other"), "blank_frame", _cfg()) is None
    assert ip.candidate(_alert(), "blank_frame", _cfg()) == "OK"


def test_power_and_toggle_keys_are_refused():
    assert ip.parse_devices("a/b=POWER,c/d=HOME,e/f=ok,g/h=STANDBY") == {"e/f": "OK"}
    r = Rig().run(_alert(), BLACK)
    assert r.outcome == "woke_from_standby"
    bad = ip.run_probe(_alert(), "POWER", _cfg(), before=BLACK, is_blank=nw.is_blank_frame,
                       send_key=Rig().send_key, capture=Rig().capture, sleep=lambda s: None)
    assert bad.outcome == "send_failed"


def test_only_blank_or_empty_black_and_no_signal_qualify():
    assert ip.candidate(_alert(kind="freeze"), "blank_frame", _cfg()) is None
    assert ip.candidate(_alert(), "repeat", _cfg()) is None
    assert ip.candidate(_alert(end=T0.isoformat()), "blank_frame", _cfg()) is None  # recovered by itself


def test_cooldown_hourly_cap_and_busy_device():
    recent = [{"device": "vpt-mf1/device1", "at": (T0 - timedelta(minutes=10)).isoformat(), "outcome": "no_change"}]
    assert "cooldown" in ip.rate_limited(recent, _alert(), _cfg(), T0)
    assert ip.rate_limited(recent, _alert(device="device2"), _cfg(), T0) is None
    many = [{"device": f"x/{i}", "at": T0.isoformat(), "outcome": "no_change"} for i in range(6)]
    assert "hourly cap" in ip.rate_limited(many, _alert(), _cfg(max_per_hour=6), T0)
    dry = [dict(r, outcome="dryrun") for r in recent]
    assert ip.rate_limited(dry, _alert(), _cfg(), T0) is None
    assert ip.device_busy([{"ended_at": None}]) and not ip.device_busy([{"ended_at": "2026-10-22T11:00:00Z"}])


# ---- outcomes -------------------------------------------------------------------------------
def test_standby_wakes():
    rig = Rig(after=PICTURE)
    r = rig.run(_alert(), BLACK)
    assert r.outcome == "woke_from_standby" and r.discards and rig.sent == [("vpt-mf1", "device1", "OK")]


def test_splash_changes_to_home():
    r = Rig(after=_jpg(120, noise=True)).run(_alert(kind="no_signal"), PICTURE)
    assert r.outcome == "splash_to_home" and r.discards


def test_real_fault_stays_open():
    assert Rig(after=BLACK).run(_alert(), BLACK).outcome == "no_change"
    assert not Rig(after=PICTURE).run(_alert(), PICTURE).discards  # same picture before and after


def test_send_failure_and_no_frame_keep_the_alert():
    r = Rig(send=(False, "no BLE peer")).run(_alert(), BLACK)
    assert r.outcome == "send_failed" and not r.discards and "no BLE peer" in r.detail
    assert Rig(after=None).run(_alert(), BLACK).outcome == "no_frame"


def test_dry_run_sends_nothing():
    rig = Rig()
    r = rig.run(_alert(), BLACK, _cfg("dryrun"))
    assert r.outcome == "dryrun" and rig.sent == [] and not r.discards


# ---- handler wiring -------------------------------------------------------------------------
def _handler(monkeypatch, busy=False, writes=None, **env):
    for k, v in {"ALERT_PROBE_MODE": "on", "ALERT_PROBE_DEVICES": "vpt-mf1/device1=OK", "ALERT_PROBE_SETTLE_S": "0",
                 **env}.items():
        monkeypatch.setenv(k, v)
    h = nw.NightwatchHandler()
    writes = writes if writes is not None else []
    monkeypatch.setattr(h, "_device_busy", lambda a: busy)
    monkeypatch.setattr(h, "_recent_probes", lambda now: [])
    monkeypatch.setattr(h, "_write", lambda i, f: writes.append(f) or True)
    monkeypatch.setattr(nw, "load_image", lambda p: BLACK)
    monkeypatch.setattr(h, "_send_key", lambda *a: (True, ""))
    monkeypatch.setattr(h, "_capture", lambda *a: PICTURE)
    monkeypatch.setattr(ip.time, "sleep", lambda s: None)
    from shared.src.lib.database import audit_events_db
    monkeypatch.setattr(audit_events_db, "record", lambda **f: True)
    return h


def test_handler_discards_with_named_reason(monkeypatch):
    writes = []
    h = _handler(monkeypatch, writes=writes)
    assert h._try_probe(_alert(meta={"r2_images": {"thumbnail_r2_paths": ["x.jpg"]}}), "blank_frame", "flat", None, T0)
    w = writes[0]
    assert w["check_type"] == "probe" and w["discard"] and w["discard_type"] == "expected"
    assert w["discard_comment"].startswith("probe: woke_from_standby") and w["metadata"]["probe"]["key"] == "OK"


def test_handler_does_nothing_when_held_or_off(monkeypatch):
    writes = []
    assert not _handler(monkeypatch, busy=True, writes=writes)._try_probe(_alert(), "blank_frame", "", None, T0)
    assert not _handler(monkeypatch, writes=writes, ALERT_PROBE_MODE="off")._try_probe(_alert(), "blank_frame", "", None, T0)
    assert writes == []


def test_handler_dry_run_only_comments(monkeypatch):
    writes = []
    h = _handler(monkeypatch, writes=writes, ALERT_PROBE_MODE="dryrun")
    assert h._try_probe(_alert(), "blank_frame", "flat", None, T0)
    assert writes[0]["check_type"] == "ai_strategy_skip" and "dry run" in writes[0]["discard_comment"]
