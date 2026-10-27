"""
``scope=all`` fan-out (TASK-179 P3): ask the same route on every other server of the list, with the caller's login.

``all_servers(path, params)`` runs the calls in parallel with ``gevent.spawn`` + ``gevent.joinall(timeout=…)``: never a
thread pool (BUG-0700, thread-pool waits hang this gevent server). A server that fails is a ``ServerResult`` with
``ok=False`` and a reason (``timeout``, ``unreachable``, ``<http code>``, ``bad response``), never dropped.

Credential: only the incoming ``Authorization: Bearer`` and ``X-Auto-Sign`` headers are copied, so the other server
sees the real user. A caller with only the service ``X-API-Key`` has no user to act as (and the key may differ
between servers): ``NeedsSignedInUser``. Tokens are never logged.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import gevent
import requests
from flask import request

from backend_server.src.lib.servers import registry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 4
# Cloudflare 403s the default python-requests UA on *.angelstreet.io; the suffix keeps the call recognisable in logs.
USER_AGENT = 'Mozilla/5.0 (compatible; VirtualPyTest-server/1.0; +scope-all)'


class NeedsSignedInUser(Exception):
    """The incoming request carries no user credential to forward."""


@dataclass
class ServerResult:
    server: str
    url: str
    ok: bool
    status: Optional[int] = None
    data: Any = None
    error: Optional[str] = None
    latency_ms: int = 0


def credential_headers() -> Dict[str, str]:
    """The caller's own credential, nothing else (X-API-Key is never forwarded)."""
    headers: Dict[str, str] = {}
    auth = (request.headers.get('Authorization') or '').strip()
    if auth.lower().startswith('bearer '):
        headers['Authorization'] = auth
    auto_sign = (request.headers.get('X-Auto-Sign') or '').strip()
    if auto_sign:
        headers['X-Auto-Sign'] = auto_sign
    if not headers:
        raise NeedsSignedInUser()
    return headers


def _get(url: str, params: Dict[str, Any], headers: Dict[str, str], timeout: float) -> requests.Response:
    return requests.get(url, params=params, headers=headers, timeout=timeout)


def _fetch_one(row: Dict[str, Any], path: str, params: Dict[str, Any], headers: Dict[str, str],
               timeout: float) -> ServerResult:
    name, base = row['name'], row['url'].rstrip('/')
    started = time.monotonic()

    def done(**kw) -> ServerResult:
        return ServerResult(server=name, url=base, latency_ms=int((time.monotonic() - started) * 1000), **kw)

    try:
        resp = _get(base + path, params, headers, timeout)
    except requests.Timeout:
        return done(ok=False, error='timeout')
    except requests.RequestException:
        return done(ok=False, error='unreachable')
    except Exception as exc:  # noqa: BLE001 - one server's failure must not break the others
        logger.warning('scope=all call to %s failed: %s', name, type(exc).__name__)
        return done(ok=False, error='unreachable')
    if resp.status_code >= 400:
        return done(ok=False, status=resp.status_code, error=str(resp.status_code))
    try:
        data = resp.json()
    except ValueError:
        return done(ok=False, status=resp.status_code, error='bad response')
    return done(ok=True, status=resp.status_code, data=data)


def all_servers(path: str, params: Optional[Dict[str, Any]] = None, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                headers: Optional[Dict[str, str]] = None) -> List[ServerResult]:
    """GET ``path`` on every other enabled server (``scope=local`` added), in parallel; one result per server."""
    headers = dict(headers) if headers is not None else credential_headers()
    headers['User-Agent'] = USER_AGENT
    headers.setdefault('Accept', 'application/json')
    query = {k: v for k, v in (params or {}).items() if k != 'scope'}
    query['scope'] = 'local'

    rows = registry.others()
    jobs = [gevent.spawn(_fetch_one, row, path, query, headers, timeout) for row in rows]
    gevent.joinall(jobs, timeout=timeout)

    results: List[ServerResult] = []
    for row, job in zip(rows, jobs):
        if job.ready() and job.successful():
            results.append(job.value)
            continue
        job.kill(block=False)
        results.append(ServerResult(server=row['name'], url=row['url'].rstrip('/'), ok=False, error='timeout',
                                    latency_ms=int(timeout * 1000)))
    return results
