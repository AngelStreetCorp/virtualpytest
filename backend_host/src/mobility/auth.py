"""
Operator authorization for the mobility feature.

R7 of the SafetyGate requires the gate to know who's allowed to command
the rover. This module owns that knowledge:

- a small in-memory set of authorized operators
- HMAC-signed tokens that the gate can validate without a DB roundtrip
- a sliding nonce window so a captured token can't be replayed

Limitations called out explicitly so PR 2+ can replace the in-memory store:

- the nonce window is per-process — multi-host deployments need a shared
  store (Redis or the platform DB)
- the HMAC secret defaults to the platform API key for PR 1; an operator
  who wants a separate secret can set ``VPT_MOBILITY_AUTH_SECRET``
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional


def _default_secret() -> str:
    """Resolve the HMAC secret.

    Order:
        1. ``VPT_MOBILITY_AUTH_SECRET`` — explicit override
        2. ``VPT_HOST_API_KEY`` / ``API_KEY`` — the platform-wide key
        3. empty string — tokens will then always be invalid (fail-closed)
    """
    return (
        os.environ.get("VPT_MOBILITY_AUTH_SECRET")
        or os.environ.get("VPT_HOST_API_KEY")
        or os.environ.get("API_KEY")
        or ""
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class OperatorRecord:
    operator_id: str
    label: str = ""
    authorized_at_ms: int = field(default_factory=_now_ms)


class OperatorRegistry:
    """In-memory list of operators authorized to command the rover.

    Bounded only by available memory; PR 1 doesn't expect more than a
    handful of entries. A real deployment would back this with a DB row
    in role_permissions, but the spec rules out DB changes for PR 1.
    """

    def __init__(self) -> None:
        self._ops: Dict[str, OperatorRecord] = {}

    def authorize(self, operator_id: str, label: str = "") -> OperatorRecord:
        rec = OperatorRecord(operator_id=operator_id, label=label)
        self._ops[operator_id] = rec
        return rec

    def revoke(self, operator_id: str) -> bool:
        return self._ops.pop(operator_id, None) is not None

    def is_authorized(self, operator_id: str) -> bool:
        return operator_id in self._ops

    def all(self) -> Dict[str, OperatorRecord]:
        return dict(self._ops)


class TokenVerifier:
    """Validate HMAC-signed authorization tokens.

    A token is the format ``<operator_id>|<nonce>|<issued_at_ms>`` whose
    HMAC-SHA256 signature (hex) is appended after a ``.`` separator. The
    signature covers the three parts as a single string. Verification:

        1. token parses cleanly into the three parts
        2. signature matches (constant-time compare)
        3. age <= auth_token_max_age_s
        4. nonce hasn't been used recently by the same operator

    Multi-instance deployments will need a shared nonce store; this is
    called out in the PR description.
    """

    def __init__(
        self,
        secret: Optional[str] = None,
        max_age_s: int = 5,
        nonce_window: int = 100,
    ) -> None:
        self._secret = (secret if secret is not None else _default_secret()).encode("utf-8")
        self._max_age_s = max_age_s
        self._nonce_window = nonce_window
        self._seen: Dict[str, Deque[str]] = {}

    # ---- token mint + verify ------------------------------------------------

    def mint(self, operator_id: str, nonce: str, issued_at_ms: Optional[int] = None) -> str:
        if not operator_id:
            raise ValueError("operator_id required to mint a token")
        if not nonce:
            raise ValueError("nonce required to mint a token")
        ts = int(issued_at_ms) if issued_at_ms is not None else _now_ms()
        payload = f"{operator_id}|{nonce}|{ts}"
        sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}.{sig}"

    def verify(self, token: str, now_ms: Optional[int] = None) -> tuple[bool, str]:
        """Verify a token.

        Returns ``(True, "")`` on success, ``(False, reason_code)`` on
        failure. The reason code matches what ``SafetyGate`` reports so
        callers can pass it through.
        """
        if not token:
            return False, "AUTH_TOKEN_INVALID"
        if not self._secret:
            return False, "AUTH_TOKEN_INVALID"

        try:
            payload, sig = token.rsplit(".", 1)
        except ValueError:
            return False, "AUTH_TOKEN_INVALID"
        operator_id, nonce, ts_str = payload.split("|", 2)
        try:
            ts = int(ts_str)
        except ValueError:
            return False, "AUTH_TOKEN_INVALID"

        expected_sig = hmac.new(
            self._secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            return False, "AUTH_TOKEN_INVALID"

        now = int(now_ms) if now_ms is not None else _now_ms()
        if (now - ts) / 1000.0 > self._max_age_s:
            return False, "AUTH_TOKEN_STALE"

        # Sliding nonce window — append, drop the oldest if the queue
        # exceeds ``nonce_window``. ``deque(maxlen=N)`` does this
        # atomically.
        seen = self._seen.setdefault(operator_id, deque(maxlen=self._nonce_window))
        if nonce in seen:
            return False, "AUTH_TOKEN_REPLAYED"
        seen.append(nonce)
        return True, ""