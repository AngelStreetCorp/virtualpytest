"""
AI usage resolver (TASK-30 §3.4).

``resolve(usage, team_id, context)`` answers "which model serves this call":

1. Walk the usage key from most to least specific (``vision.banner`` → ``vision``).
2. At each key, look at the team's overrides first, then the server default. Within a
   layer the route matching the most scope columns (host / device model /
   userinterface) wins, then the lowest ``priority``. The first key with a match wins,
   so a specific key beats a broad one whichever layer set it.
3. An A/B split sends ``split_percent``% of calls (by request id hash) to the split
   profile; the arm is reported so stats and TASK-27 evals can compare them.
4. The chosen profile's fallback chain (max 3 hops, no cycles) is returned for the
   caller to try in order.

Calls without a team use the server default only. The server default always routes
the root usages (the DB refuses to delete them), so resolution only fails when the
tables are missing or every candidate is disabled.

The working set (all endpoints/profiles/routes) is cached for ``CACHE_TTL_S`` and
dropped in-process by ``invalidate()`` after a settings write; other processes pick
changes up within the TTL.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from . import usages
from .config import get_preset
from .secrets_store import get_secret

CACHE_TTL_S = 30
MAX_CHAIN = 3
# A stored fallback chain may be longer than MAX_CHAIN: disabled hops are stepped over, and the router keeps the
# first MAX_CHAIN usable ones (e.g. AngelStreet key -> Individual key (off) -> MiniMax M3 -> MiniMax on OpenRouter).
MAX_STORED_CHAIN = 6

# An Anthropic user key (``sk-ant-usr…``) is either scoped to one workspace (works as is) or to the whole organisation
# (every request then needs the ``anthropic-workspace-id`` header, stored as the secret ``<endpoint secret_name>-workspace``).
# Which one cannot be read from the key, so the header is sent when that secret exists and the API's answer decides.
WORKSPACE_SECRET_SUFFIX = "-workspace"


def needs_workspace(key: Optional[str]) -> bool:
    """Kept for callers: an organisation-scoped user key needs the header, a workspace-scoped one does not, and the
    key text does not say which. Credentials are therefore never refused for a missing workspace id."""
    return False
# After a connection failure an endpoint is skipped for this long (its fallback serves
# instead), then tried again. Per process: the server and the discard worker each learn it.
DOWN_FOR_S = 60
# After an HTTP 402 (no credit) an endpoint is not called at all, by any usage. The pause ends by a free
# credit check (OpenRouter /credits) when the wait is over; when credit cannot be read, the wait grows
# 5 -> 15 -> 60 min and a non-shadow call is the probe (BUG-0492, BUG-0497). Per process, like DOWN_FOR_S.
NO_CREDIT_STEPS_S = (300, 900, 3600)
NO_CREDIT_START_S, NO_CREDIT_MAX_S = NO_CREDIT_STEPS_S[0], NO_CREDIT_STEPS_S[-1]
DOWN_REASON = "endpoint_down"  # stop_reason of a call skipped because its endpoint is unreachable
BREAKER_REASON = "empty_breaker"  # stop_reason of a best-effort call skipped: its endpoint keeps answering empty
RATE_LIMIT_REASON = "rate_limited_no_paid_fallback"  # a best-effort usage never pays for the hop after a 429
BREAKER_EMPTY_TRIP = 3  # consecutive empty (billed) answers of a usage on an endpoint that open the breaker
BREAKER_COOLDOWN_S = 900
PAUSED_REASON = "provider_paused"  # stop_reason of a call skipped because its provider is paused
_SCOPE_COLUMNS = ("host_name", "device_model", "userinterface_name")


class AIRoutingError(RuntimeError):
    pass


@dataclass
class Hop:
    """One profile on its endpoint — a concrete (model, server) to call."""
    profile: dict
    endpoint: dict

    @property
    def preset(self) -> str:
        return self.endpoint["preset"]

    @property
    def model(self) -> str:
        return self.profile["model"]

    @property
    def profile_name(self) -> str:
        return self.profile["name"]

    @property
    def endpoint_name(self) -> str:
        return self.endpoint["name"]

    @property
    def reach(self) -> str:
        return self.endpoint.get("reach") or "server"

    @property
    def timeout(self) -> int:
        return int(self.endpoint.get("timeout_s") or 120)

    @property
    def base_url(self) -> Optional[str]:
        return self.endpoint.get("base_url") or get_preset(self.preset).base_url

    @property
    def supports_prompt_caching(self) -> bool:
        return get_preset(self.preset).supports_prompt_caching

    def has_credentials(self) -> bool:
        if not get_preset(self.preset).needs_key:
            return True
        key = get_secret(self.endpoint.get("secret_name"))
        return bool(key) and (not needs_workspace(key) or bool(self.workspace_id))

    @property
    def workspace_id(self) -> Optional[str]:
        """Anthropic workspace of a user key (``sk-ant-usr…``): secret ``<secret_name>-workspace``."""
        name = self.endpoint.get("secret_name")
        return get_secret(f"{name}{WORKSPACE_SECRET_SUFFIX}") if name else None

    def client(self, timeout: Optional[int] = None):
        """Provider client; ``timeout`` (a caller's budget) can only shorten the endpoint's."""
        from .provider_client import create_client
        workspace = self.workspace_id if self.preset == "anthropic" else None
        return create_client(self.preset, get_secret(self.endpoint.get("secret_name")),
                             base_url=self.endpoint.get("base_url"),
                             timeout=min(self.timeout, timeout) if timeout else self.timeout,
                             headers={"anthropic-workspace-id": workspace} if workspace else None)

    # --- per-call parameters -------------------------------------------------------
    def max_tokens(self, requested: int) -> int:
        cap = self.profile.get("max_tokens_cap")
        return min(requested, int(cap)) if cap else requested

    def temperature(self, requested: Optional[float]) -> Optional[float]:
        configured = self.profile.get("temperature")
        return float(configured) if configured is not None else requested

    def thinking(self, usage_key: str) -> str:
        configured = self.profile.get("thinking") or "auto"
        return configured if configured != "auto" else usages.effective(usage_key, "thinking")

    def effort(self, usage_key: str) -> str:
        """What the profile asks of the model: Claude's ``output_config.effort`` when set, else the thinking mode."""
        effort = ((self.profile.get("extra") or {}).get("output_config") or {}).get("effort")
        return str(effort) if effort else self.thinking(usage_key)

    def extra_body(self, usage_key: str) -> dict[str, Any]:
        extra = dict(self.profile.get("extra") or {})
        # OpenRouter reasoning models (MiniMax M3) spend the whole max_tokens on thinking and answer empty
        # (2026-10-22: 1999 of 2000 tokens reasoning): best-effort usages (caption translation) ask OpenRouter for none.
        if self.preset == "openrouter" and usages.is_best_effort(usage_key):
            extra.setdefault("reasoning", {"enabled": False})
        # Qwen3 hybrids and other chat-template reasoning models on vLLM / LM Studio /
        # llama.cpp: switch thinking off where the caller parses raw JSON.
        if self.preset == "openai_compatible" and self.thinking(usage_key) == "off":
            kwargs = dict(extra.get("chat_template_kwargs") or {})
            kwargs.setdefault("enable_thinking", False)
            extra["chat_template_kwargs"] = kwargs
        return extra

    @property
    def image_max_edge(self) -> Optional[int]:
        value = self.profile.get("image_max_edge")
        return int(value) if value else None

    def describe(self) -> dict:
        """Public description (no secret) — used for direct host calls and the UI."""
        return {
            "profile": self.profile_name,
            "endpoint": self.endpoint_name,
            "preset": self.preset,
            "model": self.model,
            "reach": self.reach,
            "base_url": self.base_url,
            "timeout_s": self.timeout,
            "temperature": self.profile.get("temperature"),
        }


@dataclass
class Resolution:
    usage: str
    via_key: str
    layer: str  # "team" | "default"
    route_id: str
    team_id: Optional[str]
    split_arm: str  # "" (no split) | "a" | "b"
    hops: list[Hop] = field(default_factory=list)
    request_id: str = ""
    # Profile the route picked (before a down endpoint was moved behind its fallbacks).
    route_profile_id: str = ""
    # Name used for stats and traces; differs from ``usage`` only for scoring calls
    # (``eval:<usage>``) so they never mix with production numbers.
    label: str = ""
    # Routing context of the call (host_name, device_model, userinterface_name): the call log keeps it.
    context: dict = field(default_factory=dict)

    @property
    def stats_label(self) -> str:
        return self.label or self.usage

    def is_fallback(self, hop: Hop) -> bool:
        return str(hop.profile["id"]) != self.route_profile_id

    def hop_index(self, hop: Hop) -> int:
        """Position of ``hop`` in the chain (0 = the route's profile): ai_calls.hop_index says which hop served."""
        for i, h in enumerate(self.hops):
            if h.profile.get("id") == hop.profile.get("id"):
                return i
        return 0

    @property
    def primary(self) -> Hop:
        return self.hops[0]

    def summary(self) -> dict:
        return {
            "usage": self.usage,
            "via": self.via_key,
            "layer": self.layer,
            "split_arm": self.split_arm,
            "chain": [h.describe() for h in self.hops],
        }


class _Snapshot:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Optional[dict] = None
        self._loaded_at = 0.0

    def get(self) -> dict:
        with self._lock:
            if self._data is not None and time.time() - self._loaded_at < CACHE_TTL_S:
                return self._data
            try:
                from shared.src.lib.database import ai_routing_db
                raw = ai_routing_db.load_snapshot()
            except Exception as e:
                if self._data is not None:
                    print(f"[AI_ROUTER] ⚠️ reload failed, serving cached routing ({e})")
                    self._loaded_at = time.time()
                    return self._data
                raise AIRoutingError(f"AI routing tables unavailable: {e}") from e
            self._data = {
                "endpoints": {e["id"]: e for e in raw.get("endpoints", [])},
                "profiles": {p["id"]: p for p in raw.get("profiles", [])},
                "routes": list(raw.get("routes", [])),
            }
            self._loaded_at = time.time()
            return self._data

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = 0.0

    def set_for_tests(self, data: Optional[dict]) -> None:
        with self._lock:
            self._data = data
            self._loaded_at = time.time() if data is not None else 0.0


_snapshot = _Snapshot()


def invalidate() -> None:
    """Drop the cached routing (call after any settings write)."""
    _snapshot.invalidate()


def _scope_match(route: dict, context: dict) -> Optional[int]:
    """Number of scope columns matched, or None if a set column does not match."""
    matched = 0
    for column in _SCOPE_COLUMNS:
        wanted = route.get(column)
        if wanted is None:
            continue
        if context.get(column) != wanted:
            return None
        matched += 1
    return matched


def _endpoint_allowed(endpoint: dict, team_id: Optional[str]) -> bool:
    allowed = endpoint.get("allowed_team_ids")
    return not allowed or (team_id is not None and team_id in allowed)


def is_claude_model(model: Optional[str]) -> bool:
    """A Claude model id, in Anthropic (``claude-…``) or OpenRouter (``anthropic/…``) spelling."""
    m = (model or "").strip().lower()
    return m.startswith("claude") or m.startswith("anthropic/") or "/claude" in m


def claude_off_anthropic(profile: dict, endpoint: dict) -> bool:
    """Claude runs only on the owner's Anthropic keys (owner rule 2026-10-20): never through OpenRouter or any
    other reseller. Such a profile is treated as disabled, so no call can reach it."""
    return is_claude_model(profile.get("model")) and endpoint.get("preset") != "anthropic"


def _usable_hop(data: dict, profile_id: Optional[str], team_id: Optional[str]) -> Optional[Hop]:
    profile = data["profiles"].get(profile_id) if profile_id else None
    if not profile or not profile.get("enabled", True):
        return None
    endpoint = data["endpoints"].get(profile["endpoint_id"])
    if not endpoint or not endpoint.get("enabled", True) or not _endpoint_allowed(endpoint, team_id):
        return None
    if claude_off_anthropic(profile, endpoint):
        return None
    return Hop(profile=profile, endpoint=endpoint)


def _chain(data: dict, first: Hop, team_id: Optional[str]) -> list[Hop]:
    """``first`` and its fallbacks. A disabled hop (profile, endpoint, team not allowed) is stepped over, not the
    end of the chain: AngelStreet key -> Individual key (disabled until its workspace id is set) -> MiniMax M3 still
    reaches MiniMax. At most ``MAX_CHAIN`` usable hops; cycles are cut."""
    hops = [first]
    seen = {first.profile["id"]}
    next_id = first.profile.get("fallback_profile_id")
    while next_id and len(hops) < MAX_CHAIN and next_id not in seen:
        seen.add(next_id)
        hop = _usable_hop(data, next_id, team_id)
        if hop is not None:
            hops.append(hop)
        profile = data["profiles"].get(next_id) or {}
        next_id = profile.get("fallback_profile_id")
    return hops


_down_until: dict[str, float] = {}
_down_lock = threading.Lock()


def mark_down(hop: Hop, seconds: int = DOWN_FOR_S) -> None:
    """Skip ``hop``'s endpoint for ``seconds`` after it could not be reached."""
    with _down_lock:
        _down_until[str(hop.endpoint["id"])] = time.time() + seconds
    print(f"[AI_ROUTER] endpoint {hop.endpoint_name} unreachable — skipped for {seconds}s")


def mark_up(hop: Hop) -> None:
    with _down_lock:
        _down_until.pop(str(hop.endpoint["id"]), None)


def endpoint_down_for(endpoint_id: str) -> int:
    """Seconds left before an endpoint marked down is tried again (0 = considered up)."""
    with _down_lock:
        remaining = _down_until.get(str(endpoint_id), 0) - time.time()
    return max(0, int(remaining))


_no_credit: dict[str, tuple[float, int]] = {}  # endpoint id -> (paused until, current back-off s)
_no_credit_since: dict[str, float] = {}  # endpoint id -> when this pause started

# The pause is shared by every process on the machine (server, discard worker, monitor...) through this file,
# so each process does not have to find out by its own paid 402 (BUG-0514). ``None`` = memory only.
_PAUSE_FILE: Optional[str] = os.environ.get("VPT_AI_PAUSE_FILE") or os.path.join(tempfile.gettempdir(), "vpt_ai_no_credit.json")
_pause_file_stamp = 0


def _sync_pause() -> None:
    """Adopt the pause state another process wrote (call with ``_down_lock`` held)."""
    global _pause_file_stamp
    if not _PAUSE_FILE:
        return
    try:
        stamp = os.stat(_PAUSE_FILE).st_mtime_ns
        if stamp == _pause_file_stamp:
            return
        with open(_PAUSE_FILE) as handle:
            data = json.load(handle)
        entries = {str(k): (float(v[0]), int(v[1])) for k, v in (data.get("paused") or {}).items()}
        since = {str(k): float(v) for k, v in (data.get("since") or {}).items()}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return  # no file / unreadable: keep what this process knows
    _no_credit.clear()
    _no_credit.update(entries)
    _no_credit_since.clear()
    _no_credit_since.update(since)
    _pause_file_stamp = stamp


def _save_pause() -> None:
    """Publish this process' pause state to the others (call with ``_down_lock`` held). Never raises."""
    global _pause_file_stamp
    if not _PAUSE_FILE:
        return
    tmp = f"{_PAUSE_FILE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as handle:
            json.dump({"paused": {k: list(v) for k, v in _no_credit.items()}, "since": _no_credit_since}, handle)
        os.replace(tmp, _PAUSE_FILE)
        _pause_file_stamp = os.stat(_PAUSE_FILE).st_mtime_ns
    except OSError as e:
        print(f"[AI_ROUTER] pause state not shared: {e}")


def _next_backoff(current: int) -> int:
    return next((step for step in NO_CREDIT_STEPS_S if step > current), NO_CREDIT_STEPS_S[-1])


def _note_credit(hop: Hop, ok: bool, error_type: Optional[str]) -> None:
    """A 402 pauses ``hop``'s endpoint (growing back-off); an answered call ends the pause."""
    endpoint_id = str(hop.endpoint.get("id"))
    with _down_lock:
        _sync_pause()
        if ok:
            _no_credit_since.pop(endpoint_id, None)
            if _no_credit.pop(endpoint_id, None):
                _save_pause()
                print(f"[AI_ROUTER] endpoint {hop.endpoint_name} has credit again: calls resume")
            return
        if error_type != "no_credit":
            return
        backoff = _next_backoff(_no_credit.get(endpoint_id, (0, 0))[1])
        _no_credit[endpoint_id] = (time.time() + backoff, backoff)
        _no_credit_since.setdefault(endpoint_id, time.time())
        _save_pause()
    print(f"[AI_ROUTER] endpoint {hop.endpoint_name} has no credit (HTTP 402): no call to it for {backoff}s")


def no_credit_for(endpoint_id: str) -> int:
    """Seconds left in an endpoint's no-credit pause (0 = it may be called)."""
    with _down_lock:
        _sync_pause()
        remaining = _no_credit.get(str(endpoint_id), (0, 0))[0] - time.time()
    return max(0, int(remaining))


def credit_available(hop: Hop) -> Optional[bool]:
    """Free credit check: True / False for an OpenRouter endpoint whose balance can be read, else None.
    Spends nothing (``GET /api/v1/credits``)."""
    if hop.preset != "openrouter":
        return None
    key = get_secret(hop.endpoint.get("secret_name"))
    if not key:
        return None
    try:
        import requests
        data = (requests.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"},
                             timeout=5).json() or {}).get("data") or {}
        return float(data["total_credits"]) - float(data["total_usage"]) > 0
    except Exception:  # noqa: BLE001 - an unreadable balance is "unknown", never an outage
        return None


def no_credit_error(hop: Hop, probe: bool = True) -> Optional[str]:
    """The skip reason for a hop whose endpoint is paused for no credit, else None.

    When the wait is over the pause ends by a free credit check: still no credit -> the wait grows with no
    request sent. Otherwise (credit back, or the balance unreadable) ONE call is let through as the probe: the
    pause is re-armed for the same back-off before it goes out, so concurrent callers and other processes
    skip, and only a 402 grows the wait while only an answer ends the pause (the balance can read positive
    while a call still 402s: account positive, key limit or ``max_tokens`` unaffordable). A balance that cannot
    be read gives no probe to a shadow / background usage: it waits for the pause to end (``probe`` false)."""
    endpoint_id = str(hop.endpoint.get("id"))
    with _down_lock:
        _sync_pause()
        entry = _no_credit.get(endpoint_id)
    if entry is None:
        return None
    left = no_credit_for(endpoint_id)
    if not left:
        credit = credit_available(hop)
        if credit is False:
            with _down_lock:
                backoff = _next_backoff(entry[1])
                _no_credit[endpoint_id] = (time.time() + backoff, backoff)
                _save_pause()
            left = backoff
        elif credit is None and not probe:
            return f"{hop.endpoint_name}: no credit (HTTP 402), waiting for the account to be topped up"
        else:
            with _down_lock:
                _sync_pause()
                current = _no_credit.get(endpoint_id)
                if current is None:
                    return None
                if current[0] <= time.time():  # nobody claimed the probe first
                    _no_credit[endpoint_id] = (time.time() + current[1], current[1])
                    _save_pause()
                    return None
            left = no_credit_for(endpoint_id)
    return f"{hop.endpoint_name}: no credit (HTTP 402), paused {left}s more"


def skip_paused(resolution: Resolution, hop: Hop, errors: list, *, fallback: bool, attempt_index: int = 0) -> bool:
    """True when ``hop`` is skipped because its endpoint has no credit (reason appended to ``errors``).
    A shadow / background usage that is skipped is counted as a ``skipped`` call (stop_reason
    ``provider_paused``, never listed); other usages are not logged, the 402 that started the pause was."""
    shadow = usages.is_skippable(resolution.usage)
    paused = no_credit_error(hop, probe=not shadow)
    if not paused:
        return False
    errors.append(paused)
    if shadow:
        record(resolution, hop, ok=False, ms=0, fallback=fallback, outcome="skipped", error_type="no_credit",
               attempt_index=attempt_index, extra={"stop_reason": PAUSED_REASON})
    return True


def skip_down(resolution: Resolution, hop: Hop, errors: list, *, fallback: bool, attempt_index: int = 0) -> bool:
    """True when ``hop``'s endpoint was just found unreachable and its wait is not over: no request is sent
    (a down LAN endpoint cost 5 s per call). The wait ends after ``DOWN_FOR_S``, the next call is the probe."""
    left = endpoint_down_for(hop.endpoint["id"])
    if not left:
        return False
    errors.append(f"{hop.endpoint_name}: unreachable, not tried for {left}s more")
    record(resolution, hop, ok=False, ms=0, fallback=fallback, outcome="skipped", error_type="connection",
           attempt_index=attempt_index, extra={"stop_reason": DOWN_REASON})
    return True


_breaker: dict[str, tuple[int, float]] = {}  # "usage|endpoint id" -> (consecutive empties, open until)
_BREAKER_FILE: Optional[str] = os.environ.get("VPT_AI_BREAKER_FILE") or os.path.join(tempfile.gettempdir(), "vpt_ai_breaker.json")


def _breaker_load() -> None:
    """Adopt the breaker state other processes wrote (call with ``_down_lock`` held)."""
    if not _BREAKER_FILE:
        return
    try:
        with open(_BREAKER_FILE) as handle:
            data = json.load(handle)
        loaded = {str(k): (int(v[0]), float(v[1])) for k, v in data.items()}
    except (OSError, ValueError, TypeError, IndexError):
        return
    _breaker.clear()
    _breaker.update(loaded)


def _breaker_save() -> None:
    if not _BREAKER_FILE:
        return
    tmp = f"{_BREAKER_FILE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as handle:
            json.dump({k: list(v) for k, v in _breaker.items()}, handle)
        os.replace(tmp, _BREAKER_FILE)
    except OSError as e:
        print(f"[AI_ROUTER] breaker state not shared: {e}")


def note_empty(usage: str, hop: Hop, answered: bool) -> None:
    """Best-effort usages only: count consecutive empty answers of ``usage`` on ``hop``'s endpoint; the
    ``BREAKER_EMPTY_TRIP``-th opens the breaker for ``BREAKER_COOLDOWN_S`` (shared by all processes)."""
    if not usages.is_best_effort(usage):
        return
    key = f"{usage}|{hop.endpoint['id']}"
    with _down_lock:
        _breaker_load()
        count = 0 if answered else _breaker.get(key, (0, 0.0))[0] + 1
        if answered:
            if _breaker.pop(key, None) is None:
                return
        elif count >= BREAKER_EMPTY_TRIP:
            _breaker[key] = (count, time.time() + BREAKER_COOLDOWN_S)
            print(f"[AI_ROUTER] {usage} on {hop.endpoint_name}: {count} empty answers in a row, not tried for {BREAKER_COOLDOWN_S}s")
        else:
            _breaker[key] = (count, 0.0)
        _breaker_save()


def breaker_open_for(usage: str, hop: Hop) -> int:
    """Seconds left of the empty-answer breaker for ``usage`` on ``hop``'s endpoint (0 = closed). When the wait is
    over the next call is the probe: one more empty answer opens it again."""
    if not usages.is_best_effort(usage):
        return 0
    key = f"{usage}|{hop.endpoint['id']}"
    with _down_lock:
        _breaker_load()
        count, until = _breaker.get(key, (0, 0.0))
        left = until - time.time()
        if left > 0:
            return int(left) + 1
        if until:  # cool-down over: half-open, a single empty answer trips it again
            _breaker[key] = (BREAKER_EMPTY_TRIP - 1, 0.0)
            _breaker_save()
    return 0


def skip_breaker(resolution: Resolution, hop: Hop, errors: list, *, fallback: bool, attempt_index: int = 0) -> bool:
    """True when a best-effort usage's endpoint keeps answering empty and its cool-down is not over: no request."""
    left = breaker_open_for(resolution.usage, hop)
    if not left:
        return False
    errors.append(f"{hop.endpoint_name}: empty answers in a row, not tried for {left}s more")
    record(resolution, hop, ok=False, ms=0, fallback=fallback, outcome="skipped", error_type="empty_answer",
           attempt_index=attempt_index, extra={"stop_reason": BREAKER_REASON})
    return True


def skip_after_rate_limit(resolution: Resolution, hop: Hop, errors: list, *, fallback: bool, limited: bool,
                          attempt_index: int = 0) -> bool:
    """True when a best-effort usage's earlier hop was rate limited (HTTP 429): the fallback hop is a paid one, the
    answer is not worth it, the caller keeps its source text. Recorded ``skipped``, nothing billed."""
    if not (limited and fallback and usages.is_best_effort(resolution.usage)):
        return False
    errors.append(f"{hop.endpoint_name}: not tried, the flat-rate hop is rate limited")
    record(resolution, hop, ok=False, ms=0, fallback=fallback, outcome="skipped", error_type="rate_limit",
           attempt_index=attempt_index, extra={"stop_reason": RATE_LIMIT_REASON})
    return True


def _order_by_health(hops: list[Hop]) -> list[Hop]:
    """Move hops whose endpoint is marked down behind the healthy ones (never drop them:
    if everything is down, the call still tries in chain order)."""
    healthy = [h for h in hops if not endpoint_down_for(h.endpoint["id"])]
    down = [h for h in hops if endpoint_down_for(h.endpoint["id"])]
    return healthy + down


def split_arm_for(request_id: str, percent: int) -> str:
    """Deterministic A/B arm: the same request id always lands in the same arm."""
    bucket = int(hashlib.sha1(request_id.encode()).hexdigest()[:8], 16) % 100
    return "b" if bucket < percent else "a"


def resolve(usage_key: str, team_id: Optional[str] = None, context: Optional[dict] = None,
            request_id: Optional[str] = None) -> Resolution:
    """Resolve ``usage_key`` to its profile chain. Raises AIRoutingError / UnknownUsageError."""
    keys = usages.lineage(usage_key)
    context = {k: v for k, v in (context or {}).items() if v}
    request_id = request_id or uuid.uuid4().hex
    data = _snapshot.get()
    layers: list[tuple[str, Optional[str]]] = [("team", team_id)] if team_id else []
    layers.append(("default", None))

    for key in keys:
        for layer_name, layer_team in layers:
            candidates = []
            for route in data["routes"]:
                if route.get("usage_key") != key or route.get("team_id") != layer_team:
                    continue
                if not route.get("enabled", True):
                    continue
                matched = _scope_match(route, context)
                if matched is None:
                    continue
                hop = _usable_hop(data, route.get("profile_id"), team_id)
                if hop is None:
                    continue
                candidates.append((-matched, route.get("priority", 100), str(route.get("id")), route, hop))
            if not candidates:
                continue
            candidates.sort(key=lambda c: c[:3])
            route, hop = candidates[0][3], candidates[0][4]
            arm = ""
            if route.get("split_profile_id") and route.get("split_percent"):
                arm = split_arm_for(request_id, int(route["split_percent"]))
                if arm == "b":
                    split_hop = _usable_hop(data, route["split_profile_id"], team_id)
                    if split_hop is not None:
                        hop = split_hop
                    else:
                        arm = "a"
            return Resolution(
                usage=usage_key,
                via_key=key,
                layer=layer_name,
                route_id=str(route.get("id")),
                team_id=team_id,
                split_arm=arm,
                hops=_order_by_health(_chain(data, hop, team_id)),
                request_id=request_id,
                route_profile_id=str(hop.profile["id"]),
                context=context,
            )

    raise AIRoutingError(f"No AI route for '{usage_key}'")


def resolve_profile(profile: str, usage_key: str, team_id: Optional[str] = None,
                    request_id: Optional[str] = None) -> Resolution:
    """Pin one profile (by id or name) for ``usage_key``: a single hop, **no fallback**.

    For evaluation (TASK-27 step 5): the scored model must be exactly the profile asked
    for, never its fallback, so an offline endpoint fails loudly instead of silently
    scoring another model. Routes are not consulted; the profile's and its endpoint's
    ``enabled`` and ``allowed_team_ids`` still apply. Pass the result to
    ``gateway.execute``. Raises AIRoutingError / UnknownUsageError.
    """
    usages.lineage(usage_key)  # validates the key
    data = _snapshot.get()
    wanted = (profile or "").strip()
    profile_id = wanted if wanted in data["profiles"] else next(
        (pid for pid, p in data["profiles"].items() if p.get("name") == wanted), None)
    if profile_id is None:
        raise AIRoutingError(f"No AI profile '{wanted}'")
    hop = _usable_hop(data, profile_id, team_id)
    if hop is None:
        raise AIRoutingError(f"AI profile '{wanted}' is disabled, its endpoint is disabled, "
                             f"or the endpoint is not allowed for this team")
    return Resolution(
        usage=usage_key,
        via_key=f"profile:{hop.profile_name}",
        layer="pinned",
        route_id="",
        team_id=team_id,
        split_arm="",
        hops=[hop],
        request_id=request_id or uuid.uuid4().hex,
        route_profile_id=str(hop.profile["id"]),
        # Scoring calls are counted and traced as eval:<usage>, apart from production numbers.
        label=f"eval:{usage_key}",
    )


def test_resolution(hop: Hop, kind: str, team_id: Optional[str] = None) -> Resolution:
    """One-hop Resolution for a Settings → AI **Test** button, so the billed call is counted as
    ``test:<kind>`` (never mixed with production usages)."""
    return Resolution(usage="text", via_key=f"test:{kind}", layer="test", route_id="", team_id=team_id,
                      split_arm="", hops=[hop], request_id=uuid.uuid4().hex,
                      route_profile_id=str(hop.profile.get("id", "")), label=f"test:{kind}")


def is_available(usage_key: str, team_id: Optional[str] = None, context: Optional[dict] = None) -> bool:
    """True if ``usage_key`` resolves to a hop that has its credentials (no network)."""
    try:
        return any(h.has_credentials() for h in resolve(usage_key, team_id, context).hops)
    except (AIRoutingError, usages.UnknownUsageError):
        return False


def record(resolution: Resolution, hop: Hop, *, ok: bool, ms: int, tokens_in: int = 0, tokens_out: int = 0,
           fallback: bool = False, usage: Any = None, error_type: Optional[str] = None,
           attempt_index: int = 0, outcome: str = "served", extra: Optional[dict] = None,
           caller: Optional[dict] = None) -> None:
    """Log one billed request and queue its ``ai_calls`` row (the sink also bumps the hourly rollup).
    Never raises.

    ``usage`` is a ``provider_client.CallUsage`` (cache / reasoning / web-search / cost detail);
    ``tokens_in`` / ``tokens_out`` stay the headline numbers. Exactly one call per billed request:
    an empty-answer retry is its own request and its own ``attempt_index``. ``outcome`` is ``served``
    (a request was made, ok or not), ``skipped`` (hop never tried) or ``avoided`` (a cache or rule made
    the call unnecessary). ``caller`` overrides the bound ``ai_caller`` context field by field (agent
    sessions pass theirs explicitly); ``extra`` carries ``turn_index``, ``tool_calls``, ``stop_reason``,
    ``images``, ``image_bytes``, ``parse_ok``.
    """
    detail = ""
    if usage is not None:
        detail = (f" cache={usage.cache_read}/{usage.cache_write} reasoning={usage.reasoning} "
                  f"web={usage.web_searches} cost={usage.cost}")
    print(f"[AI] usage={resolution.stats_label} via={resolution.via_key}/{resolution.layer} "
          f"profile={hop.profile_name} endpoint={hop.endpoint_name} model={hop.model} "
          f"arm={resolution.split_arm or '-'} ok={ok} fallback={fallback} ms={ms} "
          f"tokens={tokens_in}/{tokens_out}{detail}" + (f" error={error_type}" if error_type else "")
          + (f" outcome={outcome}" if outcome != "served" else ""))
    if outcome == "served":
        _note_credit(hop, ok, error_type)
    try:
        from . import call_log, tracing
        call_log.submit(call_log.build_row(
            resolution, hop, ok=ok, ms=ms, tokens_in=tokens_in, tokens_out=tokens_out, fallback=fallback,
            usage=usage, error_type=error_type, attempt_index=attempt_index, outcome=outcome, extra=extra,
            caller=caller, server=tracing.deployment_context().get("server")))
    except Exception as e:  # noqa: BLE001
        print(f"[AI] call log failed: {e}")


def record_avoided(usage_key: str, team_id: Optional[str] = None, context: Optional[dict] = None,
                   reason: str = "") -> None:
    """Count a call a cache or rule made unnecessary (screen memory, public-Ask cache, triage skip rules):
    an ``avoided`` row with the profile that would have answered and zero tokens. The page prices the saving
    from the average cost of that usage's real calls. Never raises, never calls a model."""
    try:
        resolution = resolve(usage_key, team_id, context)
        record(resolution, resolution.primary, ok=True, ms=0, outcome="avoided", extra={"stop_reason": reason[:60] or None})
    except Exception as e:  # noqa: BLE001
        print(f"[AI] avoided call not recorded for {usage_key}: {e}")


def reset_health_for_tests() -> None:
    global _PAUSE_FILE, _BREAKER_FILE
    with _down_lock:
        _down_until.clear()
        _no_credit.clear()
        _no_credit_since.clear()
        _breaker.clear()
    _BREAKER_FILE = None
    _PAUSE_FILE = None  # tests never share a pause with a real process on the machine


def set_snapshot_for_tests(data: Optional[dict]) -> None:
    """Install a fixed working set (``{"endpoints": {id: row}, "profiles": {...}, "routes": [...]}``)."""
    _snapshot.set_for_tests(data)


def share_pause_for_tests(path: str) -> None:
    global _PAUSE_FILE, _pause_file_stamp
    _PAUSE_FILE, _pause_file_stamp = path, 0
