"""
Nightwatch alert triage — the `vpt-discard-incidents` worker.

The `alerts` table is the queue. Hosts only write alerts to the DB (`alerts_db.create_alert`);
this worker, on the backend server, polls for alerts nobody has looked at yet
(`check_type IS NULL`), applies three cost rules, and sends the survivors to a cheap vision
model through the AI gateway (usage `vision.alert_triage`). The verdict lands on the alert row:

    real         -> checked=true, check_type='ai', discard=false
    expected     -> checked=true, check_type='ai', discard=true   (menu, idle phone, desktop, standby...)
    false_alarm  -> checked=true, check_type='ai', discard=true   (picture moving, not black, sound present)

An alert a rule skipped keeps checked=false (no verdict exists) and gets
check_type='ai_strategy_skip' with the rule in discard_comment, so it is never polled again.

Cost rules (env on the server, defaults in parentheses):
  ALERT_DISCARD_MIN_DURATION_S (30)  wait this long after the alert opened; an alert that resolved
                                     sooner is skipped ("short"). Every alert is already 30 s of
                                     continuous detection old when the host creates it.
  ALERT_DISCARD_REPEAT_WINDOW_H (6)  analyse only the first alert per host+device+type in this
                                     window; later ones are skipped ("repeat") with a pointer to
                                     the verdict they repeat.
  ALERT_DISCARD_DAILY_MAX (100)      at most this many model calls per UTC day ("daily_cap").
Plus two accuracy rules: an alert with no uploaded frame is never sent ("no_frame"): the vision route
(MiniMax VLM) rejects a text-only call, and each rejection used to block every other alert for the back-off.
And a freeze or blackscreen on a looping test stream (HLS / video loop) is
never sent to the model ("test_stream"): one frame of a test pattern cannot show that its timecode
stopped, and the evaluation saw the model call those "expected". They stay for a human.

Jev in shadow (TASK-55): a freeze alert whose host wrote `metadata.jev_facts` (host env
ALERT_JEV_FACTS_ENABLED) is shown to Jev (usage `text.decision.freeze_triage`, logged to ai_decisions):
one line says what Jev would do (keep / dismiss). It never changes the alert, the rules or the vision
call. Server env ALERT_JEV_MODE = off | shadow (default shadow; any other value is off, logged once);
also off when `decisions.enabled()` says so (JEV_ENABLED / JEV_DISABLED_USAGES). Each alert is asked once
per process lifetime.

Screen memory (TASK-84, ALERT_SCREEN_MEMORY = off | dryrun | on, default off): the host stamps a freeze
alert of any device with `metadata.screen_id` (a row of `screen_fingerprints`), and in mode `on` no longer opens a freeze
on a screen already trusted as expected (incident_manager). The worker
records each model verdict on that row; a screen the model judged harmless `ALERT_SCREEN_AI_VOTES` (2) times, or a
person did once, is trusted: its later alerts are discarded with check_type='fingerprint' and no model call, except
every `ALERT_SCREEN_AUDIT_EVERY`th (20) sighting, which still goes to the model. `dryrun` only logs what `on` would do.
The screen rule runs before `short`, and an alert on a not-yet-trusted screen (with a frame) skips `short` and `repeat`
so a flapping desktop freeze is judged ~2 times per screen instead of being skipped unseen.

A failed model call (no credits, timeout) counts toward ALERT_DISCARD_DAILY_MAX and blocks model calls for a
growing back-off (60 s doubling to 1 h); the cost rules keep running. An HTTP 402 (no credit) also pauses the
endpoint in the AI router for every usage of this process (BUG-0492), and the Alerts page shows
"triage unavailable: <reason>" while the last model request failed (`alerts_db.get_triage_stats`). One `[Nightwatch] cycle` line per busy cycle
reports calls / avoided / audit / failed / tokens, and a `day` line the UTC-day totals.

On/off: the worker runs only when `vpt-discard-incidents` is enabled on the server (installed
disabled). Nothing is queued anywhere when it is off.
"""

import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend_server.src.agent.core import incident_probe
from shared.src.lib import screen_memory
from shared.src.lib.utils.last_key import last_key_event
from shared.src.lib.database import screen_fingerprints_db
from shared.src.lib.utils.supabase_utils import get_supabase_client

USAGE = "vision.alert_triage"
VERDICT_DISCARD = {"real": False, "expected": True, "false_alarm": True}
SKIP_CHECK_TYPE = "ai_strategy_skip"
AI_CHECK_TYPE = "ai"
FINGERPRINT_CHECK_TYPE = "fingerprint"
PROBE_CHECK_TYPE = "probe"
BACKOFF_START_S, BACKOFF_MAX_S = 60, 3600
ALERT_COLUMNS = ("id,host_name,device_id,device_name,incident_type,status,consecutive_count,"
                 "start_time,end_time,metadata,check_type,discard,discard_comment,created_at")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _metadata(alert: Dict[str, Any]) -> Dict[str, Any]:
    meta = alert.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = {}
    return meta if isinstance(meta, dict) else {}


def alert_image_path(alert: Dict[str, Any]) -> Optional[str]:
    """Storage key of the frame the host uploaded with the alert (freeze: analysed frame; others: start frame)."""
    r2 = _metadata(alert).get("r2_images") or {}
    paths = r2.get("thumbnail_r2_paths") or r2.get("original_r2_paths") or []
    if paths:
        return paths[0]
    return r2.get("thumbnail_r2_path") or None


def _is_test_stream(alert: Dict[str, Any]) -> bool:
    name = f"{alert.get('device_name') or ''} {alert.get('device_id') or ''}".lower()
    return any(k in name for k in ("hls", "loop", "bipbop"))


def _device_kind(alert: Dict[str, Any]) -> str:
    device_id = str(alert.get("device_id") or "")
    name = str(alert.get("device_name") or "").lower()
    if device_id == "host" or name.endswith("_host"):
        return "the host machine's own desktop (VNC capture)"
    if _is_test_stream(alert):
        return "a looping test stream (HLS / video file)"
    if re.search(r"\b(s2\d|s21x?|s23|phone|mobile|tablet|mi)\b", name):
        return "an Android phone/tablet screen"
    if "cam" in name:
        return "a camera"
    return "a TV device (set-top box / streaming stick) on HDMI capture"


def standby_after_s() -> int:
    return _env_int("ALERT_STANDBY_AFTER_S", 1800, 60)


def last_key_lines(alert: Dict[str, Any]) -> List[str]:
    """Facts for the prompt: when a key last reached the device (TASK-158)."""
    meta = _metadata(alert)
    seconds = meta.get("seconds_since_last_key")
    if seconds is None:
        return []
    source = meta.get("last_key_source") or "unknown"
    line = f"Last key sent to this device: {int(seconds) // 60} min {int(seconds) % 60} s before the alert ({source})"
    kind = alert.get("incident_type")
    if kind in ("blackscreen", "no_signal") and seconds >= standby_after_s() and _device_kind(alert).startswith("a TV"):
        line += (f"; nobody touched it for {int(seconds) // 60} min, so black / no signal is most likely standby or off "
                 "(expected-candidate)")
    elif kind == "freeze" and seconds < 120:
        line += "; a freeze right after a key is more likely a real fault than an idle screen"
    return [line]


def build_facts(alert: Dict[str, Any], repeats_24h: int, now: datetime) -> str:
    meta = _metadata(alert)
    kind = alert.get("incident_type")
    start = _ts(alert.get("start_time"))
    end = _ts(alert.get("end_time"))
    lines = [
        f"Alert type: {kind}",
        f"Device: {alert.get('device_name') or alert.get('device_id')} on host {alert.get('host_name')} — {_device_kind(alert)}",
    ]
    event_ms = meta.get(f"{kind}_event_duration_ms") if kind != "audio_loss" else meta.get("audio_event_duration_ms")
    if event_ms:
        lines.append(f"Condition seen continuously for {int(event_ms) // 1000} s before the alert was raised")
    if end and start:
        lines.append(f"Alert resolved after {int((end - start).total_seconds())} s")
    elif start:
        lines.append(f"Alert still active, open for {int((now - start).total_seconds())} s")
    lines.append(f"Same alert type on this device in the previous 24 h: {repeats_24h}")
    lines.extend(last_key_lines(alert))
    motion = meta.get("motion") or {}
    if motion.get("state"):
        lines.append(f"Motion detector state: {motion.get('state')} ({motion.get('pct', '?')}% of the picture moving)")
    if meta.get("mean_volume_db") is not None:
        lines.append(f"Mean audio volume: {meta.get('mean_volume_db')} dB (below about -70 dB is silence)")
    if kind == "blackscreen" and meta.get("blackscreen_percentage") is not None:
        lines.append(f"Black pixels: {meta.get('blackscreen_percentage')}%")
    return "\n".join(lines)


PROMPT = """You triage monitoring alerts from a device-testing lab. A detector raised the alert below.
Decide whether it is a REAL incident someone should look at, or noise.

{facts}

The image is the captured frame from when the alert was raised{image_note}.

Answer with exactly one verdict:
- "real": content that should be playing is broken: video frozen mid-scene, black where a programme
  should show, live video that should have sound is silent, picture corrupted.
- "expected": the device state explains it, nothing is broken: a menu, guide, home screen,
  settings page, desktop or idle phone screen is legitimately still; screensaver; standby, off,
  "no signal" or a test pattern; a paused video; a radio or silent screen; a test stream whose own
  content is black, still or silent at that moment.
- "false_alarm": the detector is wrong: the picture is clearly moving, not black, or sound is present.

How to judge (most alerts in this lab are noise, but a missed real incident is worse than a kept noisy one):
- TV home screens show a large poster or still from a film/series with its TITLE LOGO painted on it,
  usually with a small channel/app logo: that is a menu backdrop, legitimately still -> "expected".
  Menus, guides, detail pages, desktops, idle phones and screensavers are also "expected", even for hours.
- A test pattern or test stream that carries a running timecode/counter must keep moving: if it froze
  or lost its picture, that is "real".
- A live programme (presenter, studio, sport, people mid-action, no title logo) that froze, went black
  or went silent is "real", also when it lasts long; a stuck device is a real incident.
- An alert that repeats all day on the same device usually means its normal screen is a still menu or
  idle screen; use it only when the image agrees.
- When the facts say nobody touched a TV device for a long time and the picture is black or "no signal", that is
  standby or off -> "expected" (a person can overrule). A freeze seconds after a key press is "real".
- If you cannot tell, answer "real" (a human will look).

Reply with JSON only: {{"verdict": "real|expected|false_alarm", "reason": "<max 25 words>"}}"""


def build_prompt(alert: Dict[str, Any], repeats_24h: int, has_image: bool, now: datetime) -> str:
    note = "" if has_image else " — no frame was uploaded for this alert, judge from the facts only"
    return PROMPT.format(facts=build_facts(alert, repeats_24h, now), image_note=note)


def parse_verdict(content: str) -> Optional[Tuple[str, str]]:
    """``(verdict, reason)`` from the model answer, or None when it is not a valid verdict."""
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICT_DISCARD:
        return None
    return verdict, str(data.get("reason", "")).strip()[:300]


def load_image(path: Optional[str]) -> Optional[bytes]:
    if not path:
        return None
    try:
        from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            result = get_cloudflare_utils().download_file(path, tmp.name)
            if not result.get("success"):
                return None
            with open(tmp.name, "rb") as f:
                return f.read()
    except Exception as e:
        print(f"[Nightwatch] image download failed {path}: {e}")
        return None


def _alert_ref(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Which alert a triage call judged: stored on the call (``ai_calls.ref_*``) so the usage page can group by
    incident type and link to the incident."""
    return {"ref_type": "alert", "ref_id": alert.get("id"), "ref_kind": alert.get("incident_type")}


BLANK_FRAME_SPREAD = 6  # a frame whose brightest and darkest pixel differ by less than this shows nothing to judge


def is_blank_frame(image: Optional[bytes]) -> bool:
    """True for a flat (all-black / all-one-colour) frame: the vision model answers it with nothing, every time
    (BUG-0515: 40 empty answers on a 750-byte frame, 0 saved by a retry). Unreadable images are not blank."""
    if not image:
        return False
    try:
        import cv2
        import numpy as np
        pixels = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_GRAYSCALE)
        return pixels is not None and int(pixels.max()) - int(pixels.min()) < BLANK_FRAME_SPREAD
    except Exception:  # noqa: BLE001 - no decoder: let the model look
        return False


def classify(alert: Dict[str, Any], repeats_24h: int, now: Optional[datetime] = None,
             resolution=None) -> Dict[str, Any]:
    """Run the model on one alert. ``resolution`` pins a profile (evaluation); None = routed usage."""
    import base64
    from shared.src.lib.ai import gateway

    now = now or datetime.now(timezone.utc)
    image = load_image(alert_image_path(alert))
    if is_blank_frame(image):  # no model call: nothing in the frame to judge
        from shared.src.lib.ai import router as ai_router
        ai_router.record_avoided(USAGE, context={"host_name": alert.get("host_name")}, reason="blank_frame")
        return {"success": False, "blank": True, "verdict": None, "has_image": True, "ms": 0, "tokens": {},
                "model": None, "raw": "", "reason": "the frame is blank (one flat colour): nothing for the vision model to judge"}
    prompt = build_prompt(alert, repeats_24h, image is not None, now)
    image_b64 = base64.b64encode(image).decode() if image else None
    started = time.time()
    from shared.src.lib.ai import caller as ai_caller
    with ai_caller.bound(origin="monitoring", job="alert_triage", host_name=alert.get("host_name"),
                         device_id=alert.get("device_id"), **_alert_ref(alert)):
        if resolution is not None:
            result = gateway.execute(resolution, prompt, image_b64=image_b64, max_tokens=120, temperature=0.0)
        else:
            result = gateway.complete(USAGE, prompt, image_b64=image_b64, max_tokens=120, temperature=0.0,
                                      context={"host_name": alert.get("host_name")})
    parsed = parse_verdict(result.get("content", "")) if result.get("success") else None
    return {
        "success": parsed is not None,
        "verdict": parsed[0] if parsed else None,
        "reason": parsed[1] if parsed else (result.get("error") or "unparseable answer"),
        "has_image": image is not None,
        "ms": int((time.time() - started) * 1000),
        "tokens": result.get("usage") or {},
        "model": result.get("model"),
        "raw": (result.get("content") or "")[:300],
    }


class NightwatchHandler:
    """Polls `alerts` for unchecked rows and triages them (see module docstring)."""

    def __init__(self, nickname: str = "Nightwatch"):
        self.nickname = nickname
        self.min_duration_s = _env_int("ALERT_DISCARD_MIN_DURATION_S", 30)
        self.repeat_window_h = _env_int("ALERT_DISCARD_REPEAT_WINDOW_H", 6)
        self.daily_max = _env_int("ALERT_DISCARD_DAILY_MAX", 100)
        self.lookback_h = max(self.repeat_window_h, 6)
        self._supabase = None
        self.jev_mode = self._jev_mode()
        # A freeze alert is "ripe" (start_time + 30 s) the moment the host writes it, but the host's
        # facts thread lands jev_facts a few seconds later: wait this long after created_at for them.
        self.jev_facts_wait_s = _env_int("ALERT_JEV_FACTS_WAIT_S", 60)
        self._jev_seen: set = set()
        self.screen_mode = screen_memory.mode()
        self._backoff_s = 0
        self._content_fails: Dict[str, int] = {}   # alert id -> model answers that were empty / unparseable
        self._last_expire = 0.0
        self._blocked_until = 0.0
        self._failed_today = 0
        self._day = ""
        self.day_stats = {"calls": 0, "avoided": 0, "audit": 0, "failed": 0, "tok_in": 0, "tok_out": 0}

    @staticmethod
    def _jev_mode() -> str:
        mode = os.getenv("ALERT_JEV_MODE", "shadow").strip().lower() or "shadow"
        if mode not in ("off", "shadow"):
            print(f"[Nightwatch] ALERT_JEV_MODE={mode!r} is not implemented (off | shadow): Jev step off")
            return "off"
        return mode

    @property
    def db(self):
        if self._supabase is None:
            self._supabase = get_supabase_client()
        return self._supabase

    # ---- DB reads -------------------------------------------------------------------
    def _pending(self, now: datetime) -> List[Dict[str, Any]]:
        since = (now - timedelta(hours=self.lookback_h)).isoformat()
        ripe = (now - timedelta(seconds=self.min_duration_s)).isoformat()
        res = (self.db.table("alerts").select(ALERT_COLUMNS).is_("check_type", "null")
               .gte("start_time", since).lte("start_time", ripe)
               .order("start_time").limit(200).execute())
        return res.data or []

    def _last_verdicts(self, now: datetime) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
        since = (now - timedelta(hours=self.repeat_window_h + self.lookback_h)).isoformat()
        res = (self.db.table("alerts").select("id,host_name,device_id,incident_type,start_time,discard")
               .eq("check_type", AI_CHECK_TYPE).gte("start_time", since).order("start_time").execute())
        last: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in res.data or []:
            last[(row["host_name"], row["device_id"], row["incident_type"])] = row
        return last

    def _calls_today(self, now: datetime) -> int:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        res = (self.db.table("alerts").select("id", count="exact").eq("check_type", AI_CHECK_TYPE)
               .gte("updated_at", midnight).limit(1).execute())
        return res.count or 0

    def _repeats_24h(self, alert: Dict[str, Any]) -> int:
        start = _ts(alert["start_time"])
        res = (self.db.table("alerts").select("id", count="exact")
               .eq("host_name", alert["host_name"]).eq("device_id", alert["device_id"])
               .eq("incident_type", alert["incident_type"])
               .gte("start_time", (start - timedelta(hours=24)).isoformat())
               .lt("start_time", alert["start_time"]).limit(1).execute())
        return res.count or 0

    # ---- DB writes (claim = only rows still unchecked are updated) --------------------
    def _count_avoided(self, alert: Dict[str, Any], rule: str) -> None:
        """The triage rule `rule` saved a model call: log it as an avoided call (TASK-87)."""
        from shared.src.lib.ai import caller as ai_caller, router
        with ai_caller.bound(origin="monitoring", job="alert_triage", host_name=alert.get("host_name"),
                             device_id=alert.get("device_id"), **_alert_ref(alert)):
            router.record_avoided(USAGE, None, {"host_name": alert.get("host_name")}, reason=rule)

    def _write(self, alert_id: str, fields: Dict[str, Any]) -> bool:
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = (self.db.table("alerts").update(fields).eq("id", alert_id)
               .is_("check_type", "null").execute())
        return bool(res.data)

    def _skip(self, alert: Dict[str, Any], rule: str, detail: str) -> None:
        self._write(alert["id"], {"check_type": SKIP_CHECK_TYPE,
                                  "discard_comment": f"[SKIP:{rule}] {detail}"[:500]})

    # ---- last key (TASK-158) and wake probe ------------------------------------------------
    CONTROL_SOURCES = {"manual_control": "take_control", "script_execution": "script", "deployment_execution": "script"}

    def _stamp_key(self, alert: Dict[str, Any]) -> None:
        """Store `seconds_since_last_key` / `last_key_source` (and the actor and key) on the alert's metadata, once.
        The host stamped `metadata.last_key`; a control session open at that moment names the source (take_control /
        script) and the actor. Never raises: no stamp = triage as before."""
        try:
            meta = _metadata(alert)
            if "seconds_since_last_key" in meta:
                return
            event = last_key_event(alert)
            if not event:
                return
            source, actor = event["source"], event["actor"]
            if source != "probe":
                rows = (self.db.table("device_control_sessions").select("owner_type,owner_user_id,started_at,ended_at")
                        .eq("host_name", alert["host_name"]).eq("device_id", alert["device_id"])
                        .lte("started_at", event["at"]).order("started_at", desc=True).limit(3).execute().data or [])
                for row in rows:
                    if not row.get("ended_at") or str(row["ended_at"]) >= str(event["at"]):
                        source = self.CONTROL_SOURCES.get(row.get("owner_type"), source)
                        actor = row.get("owner_user_id") or actor
                        break
            fields = {"seconds_since_last_key": event["seconds_before_alert"], "last_key_source": source,
                      "last_key_actor": actor, "last_key_name": event.get("key")}
            merged = {**meta, **fields}
            self.db.table("alerts").update({"metadata": merged}).eq("id", alert["id"]).execute()
            alert["metadata"] = merged
        except Exception as e:  # noqa: BLE001
            print(f"[{self.nickname}] last-key stamp failed for {alert.get('id')}: {e}")

    def _recent_probes(self, now: datetime) -> List[Dict[str, Any]]:
        since = (now - timedelta(hours=1)).isoformat()
        rows = (self.db.table("alerts").select("metadata").in_("check_type", [PROBE_CHECK_TYPE, SKIP_CHECK_TYPE])
                .gte("updated_at", since).limit(500).execute().data or [])
        return [_metadata(r).get("probe") for r in rows if isinstance(_metadata(r).get("probe"), dict)]

    def _device_busy(self, alert: Dict[str, Any]) -> bool:
        rows = (self.db.table("device_control_sessions").select("id,ended_at").eq("host_name", alert["host_name"])
                .eq("device_id", alert["device_id"]).is_("ended_at", "null").limit(1).execute().data or [])
        return incident_probe.device_busy(rows)

    @staticmethod
    def _send_key(host_name: str, device_id: str, key: str) -> Tuple[bool, str]:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        from shared.src.lib.utils.build_url_utils import call_host
        host = get_host_manager().get_host(host_name)
        if not host:
            return False, f"host {host_name} not registered"
        body, status = call_host(host, "/host/remote/executeCommand", data={
            "device_id": device_id, "command": "press_key", "params": {"key": key}, "source": "probe"}, timeout=20)
        ok = status == 200 and isinstance(body, dict) and bool(body.get("success"))
        return ok, "" if ok else str((body or {}).get("error") or (body or {}).get("message") or f"HTTP {status}")[:150]

    @staticmethod
    def _capture(host_name: str, device_id: str) -> Optional[bytes]:
        from urllib.parse import urlparse
        from backend_server.src.lib.utils.server_utils import get_host_manager
        from shared.src.lib.utils.build_url_utils import call_host
        host = get_host_manager().get_host(host_name)
        if not host:
            return None
        body, status = call_host(host, "/host/av/takeScreenshot", data={"device_id": device_id, "fast": True}, timeout=30)
        url = body.get("screenshot_url") if status == 200 and isinstance(body, dict) else None
        if not url:
            return None
        content, status = call_host(host, urlparse(url).path, method="GET", raw_response=True, timeout=20)
        return content if status == 200 and isinstance(content, bytes) else None

    def _try_probe(self, alert: Dict[str, Any], rule: str, detail: str, screen: Optional[Dict[str, Any]],
                   now: datetime) -> bool:
        """Wake probe for an alert triage cannot conclude on. True when the alert was written here (discarded, or
        skipped with the probe's finding in the comment); False when no probe applied and the caller skips as before."""
        cfg = incident_probe.load_config()
        key = incident_probe.candidate(alert, rule, cfg)
        if not key:
            return False
        where = f"{alert['host_name']}/{alert['device_id']}"
        if self._device_busy(alert):
            print(f"[{self.nickname}] probe {where}: not sent, device is held")
            return False
        limited = incident_probe.rate_limited(self._recent_probes(now), alert, cfg, now)
        if limited:
            print(f"[{self.nickname}] probe {where}: not sent, {limited}")
            return False
        before = load_image(alert_image_path(alert))
        result = incident_probe.run_probe(alert, key, cfg, before=before, is_blank=is_blank_frame,
                                          send_key=self._send_key, capture=self._capture, now=now)
        try:
            from shared.src.lib.database import audit_events_db
            audit_events_db.record(category="control", action="control.probe", actor_kind="system", actor_id="nightwatch",
                                   target=where, outcome="ok" if result.outcome not in ("send_failed", "no_frame") else "error",
                                   meta={"alert_id": alert["id"], "key": result.key, "outcome": result.outcome, "mode": cfg.mode})
        except Exception:  # noqa: BLE001
            pass
        probe_meta = {**_metadata(alert), "probe": result.as_metadata(where)}
        comment = result.comment()
        if result.discards and cfg.mode == "on":
            ok = self._write(alert["id"], {"checked": True, "check_type": PROBE_CHECK_TYPE, "discard": True,
                                           "discard_type": "expected", "discard_comment": f"{comment} (was {rule})"[:500],
                                           "metadata": probe_meta})
            if ok:
                self._learn(screen, "expected")
                print(f"[{self.nickname}] discard {where}: {comment}")
            return ok
        ok = self._write(alert["id"], {"check_type": SKIP_CHECK_TYPE, "discard_comment": f"[SKIP:{rule}] {comment}"[:500],
                                       "metadata": probe_meta})
        print(f"[{self.nickname}] skip {where}: {comment}")
        return ok

    def _skip_or_probe(self, alert: Dict[str, Any], rule: str, detail: str, screen: Optional[Dict[str, Any]],
                       now: datetime) -> None:
        if not self._try_probe(alert, rule, detail, screen, now):
            self._skip(alert, rule, detail)

    # ---- rules ----------------------------------------------------------------------
    def decide(self, alert: Dict[str, Any], last: Dict[Tuple[str, str, str], Dict[str, Any]],
               calls_today: int, screen: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
        """``(rule, detail)`` when a cost rule skips the alert, None when it goes to the model.

        Rule ``fingerprint`` is not a skip but a verdict: the alert sits on a screen trusted as expected
        (``screen`` is its row) and is discarded without a model call. Only returned in mode ``on``."""
        trusted = (screen_memory.is_trusted_expected(screen)
                   and screen.get("incident_type") == alert["incident_type"])
        if self.screen_mode == "on" and trusted and not screen_memory.should_audit(screen, _metadata(alert).get("screen_seen")):
            # before `short`: a flapping desktop freeze that resolves in seconds is exactly the noise to discard
            return "fingerprint", (f"screen {screen['id']} judged expected ({screen.get('source')}), "
                                   f"seen {screen.get('seen_count')}x, match dist {_metadata(alert).get('screen_dist')}")
        learning = self._learning(alert, screen)
        start = _ts(alert["start_time"])
        end = _ts(alert.get("end_time"))
        if end and (end - start).total_seconds() < self.min_duration_s and not learning:
            return "short", f"resolved after {(end - start).total_seconds():.0f}s < {self.min_duration_s}s"
        if not alert_image_path(alert):
            return "no_frame", "no frame was uploaded with the alert: the vision model cannot judge it, kept for a human"
        if alert["incident_type"] in ("freeze", "blackscreen") and _is_test_stream(alert):
            return "test_stream", "test stream freeze/blackscreen: one frame cannot judge it, kept for a human"
        prev = last.get((alert["host_name"], alert["device_id"], alert["incident_type"]))
        if prev and self.repeat_window_h and not learning:
            age_h = (start - _ts(prev["start_time"])).total_seconds() / 3600
            if 0 <= age_h < self.repeat_window_h:
                verdict = "discard" if prev.get("discard") else "real"
                return "repeat", f"repeats alert {prev['id']} ({verdict}) from {age_h:.1f}h earlier"
        if calls_today >= self.daily_max:
            return "daily_cap", f"{calls_today} model calls today >= ALERT_DISCARD_DAILY_MAX={self.daily_max}"
        return None

    # ---- Jev shadow (TASK-55): observe only ---------------------------------------------
    def _awaiting_jev_facts(self, alert: Dict[str, Any], now: datetime) -> bool:
        """A freeze alert without jev_facts, written less than jev_facts_wait_s ago, while the Jev step
        is on: leave it for a later cycle (delays its triage by at most that long)."""
        if self.jev_mode != "shadow" or alert.get("incident_type") != "freeze":
            return False
        if isinstance(_metadata(alert).get("jev_facts"), dict) or not alert.get("created_at"):
            return False
        return (now - _ts(alert["created_at"])).total_seconds() < self.jev_facts_wait_s

    def _jev_shadow(self, alert: Dict[str, Any]) -> None:
        """Ask Jev about one freeze alert that carries host facts and log what it would do.
        Writes nothing to the alert; never raises; once per alert per process."""
        try:
            if self.jev_mode != "shadow" or alert.get("incident_type") != "freeze":
                return
            facts = _metadata(alert).get("jev_facts")
            if not isinstance(facts, dict) or alert["id"] in self._jev_seen:
                return
            from shared.src.lib.ai import decisions, freeze_triage, router
            if not decisions.enabled(freeze_triage.USAGE):
                return
            from shared.src.lib.config.constants import get_team_id
            device_model = facts.get("device_model")
            refs = {"alert_id": alert["id"], "host_name": alert.get("host_name"),
                    "device_id": alert.get("device_id"), "device_model": device_model, "mode": "shadow"}
            out = freeze_triage.ask(router.resolve(freeze_triage.USAGE, get_team_id()), facts,
                                    device_model, refs, decisions.choose, decisions.decide)
            where = f"{alert['id']} {alert.get('host_name')}/{alert.get('device_id')}"
            if out["error"] == "jev_disabled":
                return  # switched off in the meantime: retry on a later cycle
            self._jev_seen.add(alert["id"])
            if not out["success"]:
                print(f"[{self.nickname}] jev shadow {where}: failed, ignored ({out['error']})")
                return
            ui = out["ui"]
            conf = out["confidence"]
            print(f"[{self.nickname}] jev shadow {where}: {out['choice']} "
                  f"conf={'n/a' if conf is None else format(conf, '.2f')} "
                  f"ui={'n/a' if ui is None else format(ui, '.2f')} -> {out['triage']}")
        except Exception as e:
            print(f"[{self.nickname}] jev shadow failed for {alert.get('id')}: {e}")

    # ---- screen memory + counters (TASK-84) ---------------------------------------------
    def _learning(self, alert: Dict[str, Any], screen: Optional[Dict[str, Any]]) -> bool:
        """True when this alert must reach the model for the screen memory's sake, so it skips `short` and `repeat`:

        - it teaches: its screen is stamped, recurring (seen ``ALERT_SCREEN_KEEP_MIN_SEEN`` times), not yet trusted,
          not bad and not set by a person (a flapping desktop is then judged ~ai_votes_needed times per screen instead
          of never; a screen seen once or twice is random and keeps the cost rules), or
        - it audits: its screen is trusted and this is the audit sighting (``ALERT_SCREEN_AUDIT_EVERY``). Without this
          the audit of a flapping desktop, whose alerts are all short, would be skipped before the model sees it.

        The alert needs a frame for the model to judge."""
        if self.screen_mode == "off" or not screen:
            return False
        if screen.get("incident_type") != alert["incident_type"] or not alert_image_path(alert):
            return False
        if screen_memory.is_trusted_expected(screen):
            return screen_memory.should_audit(screen, _metadata(alert).get("screen_seen"))
        return (screen_memory.is_recurring(screen, _metadata(alert).get("screen_seen"))
                and screen.get("verdict") != "bad" and screen.get("source") != "human")

    def _screen_for(self, alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The `screen_fingerprints` row the host stamped on this alert, when screen memory is on."""
        if self.screen_mode == "off":
            return None
        screen_id = _metadata(alert).get("screen_id")
        return screen_fingerprints_db.get(screen_id) if screen_id else None

    def _learn(self, screen: Optional[Dict[str, Any]], verdict: str) -> None:
        """Record the model's verdict on the alert's screen row (human verdicts are never touched)."""
        if not screen:
            return
        fields = screen_memory.apply_ai_verdict(screen, verdict)
        if fields:
            screen_fingerprints_db.update_fields(screen["id"], fields)

    def _roll_day(self, now: datetime) -> None:
        day = now.strftime("%Y-%m-%d")
        if day != self._day:
            self._day = day
            self._failed_today = 0
            self.day_stats = {k: 0 for k in self.day_stats}
            if self.screen_mode != "off":
                pruned = screen_fingerprints_db.prune_rare()
                print(f"[{self.nickname}] screen memory: pruned {pruned} rare screen(s) "
                      f"(< {screen_memory.keep_min_seen()} sightings, unseen {screen_memory.prune_after_days()} d)")

    def _model_blocked(self) -> bool:
        return time.time() < self._blocked_until

    def _model_failed(self) -> None:
        """Count one failed call and start / extend the global back-off (used by tests and transport failures)."""
        self._failed_today += 1
        self.day_stats["failed"] += 1
        self._model_failed_global()

    def _model_failed_global(self) -> None:
        self._backoff_s = min(BACKOFF_MAX_S, (self._backoff_s * 2) or BACKOFF_START_S)
        self._blocked_until = time.time() + self._backoff_s

    @staticmethod
    def _is_content_failure(reason: str) -> bool:
        """The model answered but said nothing usable (empty, unparseable): a property of this alert's frame, not of the
        provider. Credits, timeouts and HTTP errors are not: they block every alert and get the global back-off."""
        text = (reason or "").lower()
        return "empty answer" in text or "unparseable" in text

    def _expire_old(self, now: datetime) -> None:
        """Alerts that left the lookback window without a verdict are marked skipped (`[SKIP:expired]`), so they stop
        sitting in the queue as untriaged forever. At most every 10 minutes."""
        if time.time() - self._last_expire < 600:
            return
        self._last_expire = time.time()
        since = (now - timedelta(hours=self.lookback_h)).isoformat()
        res = (self.db.table("alerts").update({
            "check_type": SKIP_CHECK_TYPE, "updated_at": now.isoformat(),
            "discard_comment": f"[SKIP:expired] no verdict within {self.lookback_h} h (model unavailable or alert unreadable)"})
            .is_("check_type", "null").lt("start_time", since).execute())
        if res.data:
            print(f"[{self.nickname}] expired {len(res.data)} alerts older than {self.lookback_h} h without a verdict")

    def _model_ok(self) -> None:
        self._backoff_s = 0
        self._blocked_until = 0.0

    def run_once(self) -> int:
        """One poll cycle. Returns the number of alerts handled (skipped or analysed)."""
        now = datetime.now(timezone.utc)
        self._roll_day(now)
        self._expire_old(now)
        pending = self._pending(now)
        if not pending:
            return 0
        last = self._last_verdicts(now)
        calls_today = self._calls_today(now) + self._failed_today  # failed calls are billable too
        handled = 0
        cycle = {"calls": 0, "avoided": 0, "audit": 0, "failed": 0, "tok_in": 0, "tok_out": 0}
        for alert in pending:
            if self._awaiting_jev_facts(alert, now):
                continue  # next cycle: its host facts are probably still being written
            self._jev_shadow(alert)  # sees every freeze alert with facts, whatever a cost rule does next
            self._stamp_key(alert)
            screen = self._screen_for(alert)
            skip = self.decide(alert, last, calls_today, screen)
            where = f"{alert['id']} {alert['host_name']}/{alert['device_id']} {alert['incident_type']}"
            if (self.screen_mode == "dryrun" and screen_memory.is_trusted_expected(screen)
                    and not screen_memory.should_audit(screen, _metadata(alert).get("screen_seen"))):
                print(f"[{self.nickname}] DRYRUN would discard {where}: screen {screen['id']} judged expected "
                      f"({screen.get('source')}), seen {screen.get('seen_count')}x")
                cycle["avoided"] += 1
            if skip and skip[0] == "fingerprint":
                if self._write(alert["id"], {"checked": True, "check_type": FINGERPRINT_CHECK_TYPE, "discard": True,
                                             "discard_type": "expected", "discard_comment": skip[1][:500]}):
                    cycle["avoided"] += 1
                    handled += 1
                    self._count_avoided(alert, "fingerprint")
                    print(f"[{self.nickname}] discard {where}: fingerprint — {skip[1]}")
                continue
            if skip:
                self._count_avoided(alert, skip[0])
                self._skip(alert, *skip)
                print(f"[{self.nickname}] skip {where}: {skip[0]} — {skip[1]}")
                handled += 1
                continue
            if self._model_blocked():
                continue  # model down: rules keep running, this alert waits for the back-off to end
            if screen_memory.is_trusted_expected(screen) and screen_memory.should_audit(screen, _metadata(alert).get("screen_seen")):
                cycle["audit"] += 1
            result = classify(alert, self._repeats_24h(alert), now)
            if result.get("blank"):
                self._skip_or_probe(alert, "blank_frame", result["reason"], screen, now)
                print(f"[{self.nickname}] skip {where}: blank_frame — {result['reason']}")
                cycle["avoided"] += 1
                handled += 1
                continue
            calls_today += 1
            cycle["calls"] += 1
            tokens = result.get("tokens") or {}
            cycle["tok_in"] += int(tokens.get("prompt_tokens") or tokens.get("input_tokens") or 0)
            cycle["tok_out"] += int(tokens.get("completion_tokens") or tokens.get("output_tokens") or 0)
            if not result["success"]:
                cycle["failed"] += 1
                self._failed_today += 1
                self.day_stats["failed"] += 1
                if self._is_content_failure(result["reason"]):
                    # this alert's frame, not the provider: no global back-off; give up on it after two tries
                    n = self._content_fails[alert["id"]] = self._content_fails.get(alert["id"], 0) + 1
                    print(f"[{self.nickname}] model gave no usable answer for {alert['id']} ({n}/2): {result['reason']}")
                    if n >= 2:
                        self._skip_or_probe(alert, "model_empty",
                                            f"model gave no usable answer twice: {result['reason']}"[:300], screen, now)
                        self._content_fails.pop(alert["id"], None)
                        handled += 1
                    continue
                # transport / credits: leave it unchecked; every alert waits for the back-off to end
                self._model_failed_global()
                print(f"[{self.nickname}] model failed for {alert['id']}: {result['reason']} "
                      f"(model calls blocked {self._backoff_s}s)")
                continue
            self._model_ok()
            discard = VERDICT_DISCARD[result["verdict"]]
            if self._write(alert["id"], {"checked": True, "check_type": AI_CHECK_TYPE, "discard": discard,
                                         "discard_type": result["verdict"],
                                         "discard_comment": result["reason"]}):
                last[(alert["host_name"], alert["device_id"], alert["incident_type"])] = {
                    "id": alert["id"], "start_time": alert["start_time"], "discard": discard}
                self._learn(screen, result["verdict"])
            print(f"[{self.nickname}] {where}: {result['verdict']} ({result['ms']} ms, model={result['model']}) "
                  f"— {result['reason']}")
            handled += 1
        for key, value in cycle.items():
            self.day_stats[key] += value if key != "failed" else 0
        if any(cycle.values()):
            print(f"[{self.nickname}] cycle calls={cycle['calls']} avoided={cycle['avoided']} audit={cycle['audit']} "
                  f"failed={cycle['failed']} tokens={cycle['tok_in']}/{cycle['tok_out']} mode={self.screen_mode}")
            d = self.day_stats
            print(f"[{self.nickname}] day {self._day} calls={d['calls']} avoided={d['avoided']} audit={d['audit']} "
                  f"failed={d['failed']} tokens={d['tok_in']}/{d['tok_out']} cap={self.daily_max}")
        return handled
