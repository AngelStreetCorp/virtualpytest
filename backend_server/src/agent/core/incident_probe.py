"""
Wake probe for the triage worker (TASK-158).

When Nightwatch cannot conclude on a black / no-signal alert (`blank_frame`: the frame is one flat colour, or
`model_empty`: the model gave no usable answer), and nobody has the device, it sends ONE safe key, looks again and
names what happened. Outcomes:

    woke_from_standby  the alert frame was blank and a picture is there after the key       -> discard (expected)
    splash_to_home     the alert frame was not blank and the picture changed after the key  -> discard (expected)
    no_change          the screen did not change                                            -> stays open ("probe: no change")

Switches (server env, all read at call time; the worker needs no restart for a change of environment only on its own
restart, same as the other ALERT_* knobs):
  ALERT_PROBE_MODE        off (default) | dryrun | on. `off` is the kill switch; `dryrun` only writes what it would send.
  ALERT_PROBE_DEVICES     per-device opt-in: ``host/device_id=KEY,host/device_id=KEY``. A device that is not listed is
                          never probed. KEY must be in SAFE_KEYS (the allow-list); POWER, STANDBY, HOME and every key
                          that toggles state are refused whatever the list says, because a probe must never switch a
                          box off (stb skill: POWER and HOME toggle).
  ALERT_PROBE_COOLDOWN_S  seconds between two probes of one device (3600).
  ALERT_PROBE_MAX_PER_HOUR  probes across all devices per hour (6).
  ALERT_PROBE_SETTLE_S    seconds to wait after the key before the second look (6).

Never when the device is held: an open `device_control_sessions` row (take-control, script run or deployment all
create one) or a deploy-time lease. Every probe is logged: an `audit_events` row (control.probe) and the alert's
discard comment / `metadata.probe`.
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

PROBE_TYPES = ("blackscreen", "no_signal")
PROBE_RULES = ("blank_frame", "model_empty")
SAFE_KEYS = frozenset({"OK", "SELECT", "BACK"})
FORBIDDEN_KEYS = frozenset({"POWER", "STANDBY", "SLEEP", "HOME", "MENU", "TV_POWER", "POWER_OFF", "POWER_TOGGLE"})
CHANGE_THRESHOLD = 12.0  # mean absolute grey-level difference that counts as "the picture changed"
OUTCOMES_DISCARD = ("woke_from_standby", "splash_to_home")


@dataclass
class ProbeConfig:
    mode: str = "off"
    devices: Dict[str, str] = field(default_factory=dict)
    cooldown_s: int = 3600
    max_per_hour: int = 6
    settle_s: int = 6


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def parse_devices(raw: str) -> Dict[str, str]:
    """``host/device=KEY,...`` -> {host/device: KEY}; entries with a missing / unsafe key are dropped."""
    out: Dict[str, str] = {}
    for part in (raw or "").split(","):
        name, _, key = part.strip().partition("=")
        key = key.strip().upper()
        if name.strip() and key in SAFE_KEYS and key not in FORBIDDEN_KEYS:
            out[name.strip()] = key
    return out


def load_config() -> ProbeConfig:
    mode = os.getenv("ALERT_PROBE_MODE", "off").strip().lower()
    if mode not in ("off", "dryrun", "on"):
        mode = "off"
    return ProbeConfig(mode=mode, devices=parse_devices(os.getenv("ALERT_PROBE_DEVICES", "")),
                       cooldown_s=_env_int("ALERT_PROBE_COOLDOWN_S", 3600),
                       max_per_hour=_env_int("ALERT_PROBE_MAX_PER_HOUR", 6),
                       settle_s=_env_int("ALERT_PROBE_SETTLE_S", 6))


def device_ref(alert: Dict[str, Any]) -> str:
    return f"{alert.get('host_name')}/{alert.get('device_id')}"


def candidate(alert: Dict[str, Any], rule: str, cfg: ProbeConfig) -> Optional[str]:
    """The safe key to send when this alert qualifies for a probe, else None (no reason needed: the caller skips)."""
    if cfg.mode == "off" or rule not in PROBE_RULES or alert.get("incident_type") not in PROBE_TYPES:
        return None
    if alert.get("end_time"):  # recovered on its own: nothing to wake
        return None
    return cfg.devices.get(device_ref(alert))


def rate_limited(recent: List[Dict[str, Any]], alert: Dict[str, Any], cfg: ProbeConfig,
                 now: datetime) -> Optional[str]:
    """Reason string when the cooldown or the hourly cap forbids a probe now; ``recent`` = `metadata.probe` dicts
    (with `device`, `at`) of the last hour or more."""
    recent = [p for p in recent if p.get("outcome") != "dryrun"]  # a dry run sent nothing
    ref = device_ref(alert)
    last_hour = [p for p in recent if _age_s(p, now) < 3600]
    if len(last_hour) >= cfg.max_per_hour:
        return f"hourly cap {cfg.max_per_hour} reached"
    for p in recent:
        if p.get("device") == ref and _age_s(p, now) < cfg.cooldown_s:
            return f"cooldown {cfg.cooldown_s}s (last probe {int(_age_s(p, now))}s ago)"
    return None


def _age_s(probe: Dict[str, Any], now: datetime) -> float:
    try:
        at = datetime.fromisoformat(str(probe["at"]).replace("Z", "+00:00"))
        return (now - at).total_seconds()
    except (KeyError, ValueError):
        return float("inf")


def device_busy(sessions: List[Dict[str, Any]]) -> bool:
    """True when any open control session (take-control, script, deployment) holds the device."""
    return any(not s.get("ended_at") for s in sessions)


def frame_change(before: Optional[bytes], after: Optional[bytes]) -> Optional[float]:
    """Mean absolute grey-level difference between two JPEGs (resized alike), None when either is unreadable."""
    try:
        import cv2
        import numpy as np
        a = cv2.imdecode(np.frombuffer(before, np.uint8), cv2.IMREAD_GRAYSCALE)
        b = cv2.imdecode(np.frombuffer(after, np.uint8), cv2.IMREAD_GRAYSCALE)
        if a is None or b is None:
            return None
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
        return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16))))
    except Exception:  # noqa: BLE001
        return None


def outcome_of(before_blank: bool, after_blank: bool, change: Optional[float]) -> str:
    if after_blank:
        return "no_change"
    if before_blank:
        return "woke_from_standby"
    return "splash_to_home" if change is not None and change >= CHANGE_THRESHOLD else "no_change"


@dataclass
class ProbeResult:
    outcome: str                 # woke_from_standby | splash_to_home | no_change | dryrun | send_failed | no_frame
    key: str
    detail: str
    at: str = ""

    @property
    def discards(self) -> bool:
        return self.outcome in OUTCOMES_DISCARD

    def comment(self) -> str:
        return f"probe: {self.outcome} — {self.detail}"[:500]

    def as_metadata(self, device: str) -> Dict[str, Any]:
        return {"device": device, "at": self.at, "key": self.key, "outcome": self.outcome, "detail": self.detail}


def run_probe(alert: Dict[str, Any], key: str, cfg: ProbeConfig, *, before: Optional[bytes],
              is_blank: Callable[[Optional[bytes]], bool],
              send_key: Callable[[str, str, str], Tuple[bool, str]],
              capture: Callable[[str, str], Optional[bytes]],
              sleep: Callable[[float], None] = time.sleep,
              now: Optional[datetime] = None) -> ProbeResult:
    """Send ``key`` once, wait ``cfg.settle_s``, look again. All device I/O comes in as callables (tests inject them)."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    host, device = alert.get("host_name"), alert.get("device_id")
    if key not in SAFE_KEYS or key in FORBIDDEN_KEYS:  # parse_devices already filters; belt and braces
        return ProbeResult("send_failed", key, "key is not on the allow-list", stamp)
    if cfg.mode == "dryrun":
        return ProbeResult("dryrun", key, f"would send {key} to {host}/{device} (dry run, nothing sent)", stamp)
    ok, error = send_key(host, device, key)
    if not ok:
        return ProbeResult("send_failed", key, f"key {key} not delivered: {error}"[:200], stamp)
    sleep(cfg.settle_s)
    after = capture(host, device)
    if after is None:
        return ProbeResult("no_frame", key, f"sent {key}, but no frame could be captured afterwards", stamp)
    before_blank = before is None or is_blank(before)
    after_blank = is_blank(after)
    outcome = outcome_of(before_blank, after_blank, None if before_blank else frame_change(before, after))
    what = {"woke_from_standby": "picture appeared after the key (box was in standby)",
            "splash_to_home": "picture changed after the key (box was on a splash / idle screen)",
            "no_change": "screen unchanged after the key"}[outcome]
    return ProbeResult(outcome, key, f"sent {key}, {what}", stamp)
