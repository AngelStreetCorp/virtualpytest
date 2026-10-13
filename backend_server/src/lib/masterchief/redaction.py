"""Redaction for masterchief params and result summaries.

TASK-71. The audit table records params_redacted and result_summary, and the
hard rule is "no secret-leaking outputs" — enforced here in code, not in prompt
text. Anything that looks sensitive is dropped, and every string is capped.

The redaction is deliberately lossy: the audit row is for *accountability*, not
debugging. To debug a masterchief op, run it by hand; the audit row tells you
who, what, when, and roughly what happened.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

# Keys whose values are dropped wholesale from params_redacted.
REDACT_KEYS = {
    'password', 'passwd', 'secret', 'token', 'api_key', 'apikey',
    'authorization', 'auth', 'cookie', 'session', 'jwt', 'bearer',
    'private_key', 'private-key', 'ssh_key', 'ssh-key', 'keystore',
    'env', 'env_vars', 'envvars', 'envfile', 'env_file',
}

# Suspicious string patterns (PEM, JWT-ish, env=value with secret-like key).
# A PEM block is a BEGIN line, anything until the matching END line. The whole
# block is replaced — keeping the BEGIN/END markers but stripping the body is
# not safe (PEM metadata alone is a footgun in some setups).
_PEM_RE = re.compile(
    r'-----BEGIN [A-Z0-9 ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]+PRIVATE KEY-----',
    re.MULTILINE,
)
_JWT_RE = re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b')
_KV_SECRET_RE = re.compile(
    r'(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\s*=\s*\S+'
)

# String caps. These are deliberately small — the audit is a digest, not a log.
MAX_STRING = 200
MAX_PARAMS_JSON = 4_000  # bytes once serialised
MAX_SUMMARY_CHARS = 500


def _redact_string(value: str) -> str:
    if not isinstance(value, str):
        return value
    s = value
    s = _PEM_RE.sub('-----REDACTED PRIVATE KEY BLOCK-----', s)
    s = _JWT_RE.sub('REDACTED-JWT', s)
    s = _KV_SECRET_RE.sub(lambda m: m.group(0).split('=')[0] + '=REDACTED', s)
    if len(s) > MAX_STRING:
        s = s[:MAX_STRING] + '...<truncated>'
    return s


def _redact_value(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return '<max depth>'
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in REDACT_KEYS:
                out[k] = 'REDACTED'
            else:
                out[k] = _redact_value(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact_value(v, depth + 1) for v in value[:50]]
    return _redact_string(str(value))


def redact_params(params: Any) -> Dict[str, Any]:
    """Return a JSON-safe, size-capped, secret-stripped digest of op params."""
    if params is None:
        return {}
    redacted = _redact_value(params)
    try:
        encoded = json.dumps(redacted, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return {'_unserialisable': True}
    if len(encoded) > MAX_PARAMS_JSON:
        # Drop nested detail; keep top-level keys with short markers.
        if isinstance(redacted, dict):
            shrunk = {k: ('<too long>' if not isinstance(v, (bool, int, float, str)) or len(str(v)) > 80 else v)
                      for k, v in list(redacted.items())[:30]}
            return shrunk
        return {'_oversize': True, 'approx_chars': len(encoded)}
    return redacted


def redact_result(text: str) -> str:
    """Cap and strip secrets from a result_summary string."""
    if not isinstance(text, str):
        text = str(text)
    text = _redact_string(text)
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[:MAX_SUMMARY_CHARS] + '...<truncated>'
    return text
