"""Push validated Atlas Grafana drafts into a temporary "Atlas drafts" folder.

Kept apart from ``grafana_drafts`` on purpose: that module compiles and validates and
never touches the network.  This one only ever sends a dashboard that
``GrafanaDraftService.validate`` accepted a moment earlier, into one fixed folder, with
an expiry tag, and deletes only expired dashboards it created (``atlas-draft-`` uid
prefix, ``atlas-draft`` tag, that folder).  Credentials come from the existing
``shared.src.lib.utils.grafana_admin`` config (GRAFANA_URL / GRAFANA_ADMIN_*); a push
failure raises ``GrafanaPushError`` and callers must never let it fail a chat answer.

A server without the datasource (a Pi-hosted server) forwards the whole request to the
primary server (``POST /server/atlas-analytics/grafana-draft``), which owns the
Grafana credentials.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote

from .grafana_drafts import UID_PREFIX, GrafanaDraftService
from .service import AnalyticsContext, AnalyticsService, AnalyticsValidationError

logger = logging.getLogger(__name__)

FOLDER_UID = "atlas-drafts"
FOLDER_TITLE = "Atlas drafts"
DRAFT_TAG = "atlas-draft"
EXPIRES_TAG_PREFIX = "atlas-expires-"
TIMEOUT = 10
CANVAS_MIN_PANELS = 2


class GrafanaPushError(RuntimeError):
    """A push problem safe to show to the user (never carries credentials or driver text)."""


class GrafanaClient:
    """Minimal Grafana HTTP API client; config and auth are the ones user provisioning uses."""

    def __init__(self, http: Any = None):
        self._http = http

    def _requests(self):
        if self._http is not None:
            return self._http
        import requests
        return requests

    def _cfg(self):
        from shared.src.lib.utils import grafana_admin
        try:
            return grafana_admin._cfg()
        except RuntimeError as exc:
            raise GrafanaPushError(str(exc)) from exc

    def request(self, method: str, path: str, ok: tuple = (200,), **kwargs: Any):
        base, auth = self._cfg()
        try:
            response = getattr(self._requests(), method)(f"{base}{path}", auth=auth, timeout=TIMEOUT, **kwargs)
        except Exception as exc:  # network error text may contain the internal URL
            raise GrafanaPushError(f"Grafana unreachable ({type(exc).__name__})") from exc
        if response.status_code not in ok:
            raise GrafanaPushError(f"Grafana answered HTTP {response.status_code} on {method.upper()} {path.split('?')[0]}")
        return response

    def ensure_folder(self) -> None:
        """Create the drafts folder once, view-only for Viewer and Editor (admins keep full access)."""
        response = self.request("get", f"/api/folders/{FOLDER_UID}", ok=(200, 404))
        if response.status_code == 200:
            return
        self.request("post", "/api/folders", ok=(200, 409), json={"uid": FOLDER_UID, "title": FOLDER_TITLE})
        self.request("post", f"/api/folders/{FOLDER_UID}/permissions", json={"items": [
            {"role": "Viewer", "permission": 1}, {"role": "Editor", "permission": 1}]})

    def push(self, dashboard: Mapping[str, Any]) -> Dict[str, Any]:
        response = self.request("post", "/api/dashboards/db", json={
            "dashboard": dashboard, "folderUid": FOLDER_UID, "overwrite": True,
            "message": "Atlas analytics draft"})
        return response.json() if response.content else {}

    def list_drafts(self) -> List[Dict[str, Any]]:
        response = self.request("get", "/api/search", params={
            "type": "dash-db", "tag": DRAFT_TAG, "folderUIDs": FOLDER_UID, "limit": 500})
        return response.json() or []

    def delete(self, uid: str) -> None:
        self.request("delete", f"/api/dashboards/uid/{uid}", ok=(200, 404))


GRAFANA_PATH_PREFIX = "/grafana"
# http(s) origin plus an optional plain sub-path: no credentials, query, fragment or odd characters.
_BASE_PATTERN = re.compile(r"^https?://[A-Za-z0-9.\-]{1,200}(:\d{1,5})?(/[A-Za-z0-9._~\-]+)*$")


def dashboard_path(uid: str, workspace_id: str = "") -> str:
    """Server-independent dashboard path. Which host serves Grafana is the web app's business
    (its configured Grafana base), not ``GRAFANA_DOMAIN``, which is the marketing/mirroring domain."""
    path = f"{GRAFANA_PATH_PREFIX}/d/{quote(uid, safe='')}"
    return path + (f"?var-workspace={quote(workspace_id, safe='')}" if workspace_id else "")


def clean_grafana_base(value: Any) -> str:
    """The Grafana base the web app sent (its VITE_GRAFANA_URL), or '' when it is not a plain http(s) URL.

    Used only to write a clickable link into the answer text; never to reach, fetch or trust anything."""
    text = value.strip().rstrip("/") if isinstance(value, str) else ""
    return text if text and _BASE_PATTERN.match(text) else ""


def absolute_url(path: str, grafana_base: Any = "") -> str:
    """``path`` resolved against the app's Grafana base the way the frontend's /grafana redirect does
    (base + path without its /grafana prefix); the path itself (same-origin redirect) when there is no base."""
    base = clean_grafana_base(grafana_base)
    if not base or not path.startswith(GRAFANA_PATH_PREFIX + "/"):
        return path
    return base + path[len(GRAFANA_PATH_PREFIX):]


def link_for_reply(path: str, grafana_base: Any = "") -> str:
    """The link as the model must repeat it. Without the app's Grafana base (a client that does not send
    one: atlas_chat.py, external MCP) only the path is known, and the model once invented a host for it
    ("https://analitics.ai/grafana/..."), so a relative link says so explicitly."""
    url = absolute_url(path, grafana_base)
    if url.startswith(("http://", "https://")):
        return url
    return (f"{url} (a path on the VirtualPyTest web app: give it to the user exactly as written, "
            f"never add or guess a host)")


def _expiry_epoch(item: Mapping[str, Any]) -> Optional[int]:
    for tag in item.get("tags") or []:
        if str(tag).startswith(EXPIRES_TAG_PREFIX):
            try:
                return int(str(tag)[len(EXPIRES_TAG_PREFIX):])
            except ValueError:
                return None
    return None


def cleanup_expired(client: GrafanaClient, now: Optional[datetime] = None) -> int:
    """Delete expired Atlas drafts from the drafts folder; any other dashboard is left alone."""
    now_epoch = int((now or datetime.now(timezone.utc)).timestamp())
    removed = 0
    for item in client.list_drafts():
        uid = str(item.get("uid") or "")
        expires = _expiry_epoch(item)
        if (not uid.startswith(UID_PREFIX) or DRAFT_TAG not in (item.get("tags") or [])
                or item.get("folderUid") != FOLDER_UID or expires is None or expires > now_epoch):
            continue
        client.delete(uid)
        removed += 1
    return removed


def is_canvas(request: Mapping[str, Any]) -> bool:
    panels = request.get("panels")
    return isinstance(panels, list) and len(panels) >= CANVAS_MIN_PANELS


def _leaves(request: Mapping[str, Any]) -> List[Dict[str, Any]]:
    shared = {k: v for k, v in request.items() if k in {"filters", "scope"}}
    return [{**shared, **leaf} for leaf in request.get("panels") or [] if isinstance(leaf, dict)]


def dedupe_id(request: Mapping[str, Any], context: AnalyticsContext) -> str:
    """Same canvas spec, team and person -> same dashboard uid, so a repeat overwrites instead of piling up."""
    canonical = json.dumps({"team": context.team_id, "user": context.user_id, "request": request},
                           sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


class GrafanaDraftPublisher:
    def __init__(self, analytics: AnalyticsService, drafts: Optional[GrafanaDraftService] = None,
                 client: Optional[GrafanaClient] = None, forward: bool = True):
        self.analytics = analytics
        self.drafts = drafts or GrafanaDraftService(analytics)
        self.client = client or GrafanaClient()
        self.forward = forward

    def publish(self, request: Mapping[str, Any], context: AnalyticsContext,
                now: Optional[datetime] = None) -> Dict[str, Any]:
        """Return ``{path, uid, expires_at, reused}``; raises GrafanaPushError / AnalyticsValidationError."""
        if self.forward and self.analytics.remote is not None:
            try:
                return self.analytics.remote.call("grafana-draft", {"context": context.as_dict(), "request": dict(request)})
            except AnalyticsValidationError:
                raise
            except Exception as exc:
                raise GrafanaPushError(f"primary server unreachable ({type(exc).__name__})") from exc
        now = now or datetime.now(timezone.utc)
        reuse = request.get("prefer_existing", True) is not False
        maintained = [self.drafts.find_maintained(leaf) for leaf in _leaves(request)] if request.get("panels") and reuse else []
        if maintained and all(maintained) and len({m["dashboard_uid"] for m in maintained}) == 1:
            uid = maintained[0]["dashboard_uid"]
            return {"path": dashboard_path(uid, context.workspace_id), "uid": uid, "expires_at": None, "reused": True}
        built = self.drafts.build(request, context, now, dedupe_id(request, context))
        dashboard, metadata = copy.deepcopy(built["dashboard"]), built["metadata"]
        expires = datetime.fromisoformat(metadata["expires_at"])
        dashboard["tags"] = [DRAFT_TAG, f"{EXPIRES_TAG_PREFIX}{int(expires.timestamp())}"]
        dashboard["description"] += f" Expires {metadata['expires_at']}."
        # Never push what validate() rejects, including the tags and description added above.
        report = self.drafts.validate(dashboard, metadata, context)
        if report["errors"]:
            raise AnalyticsValidationError("Draft failed validation: " + "; ".join(report["errors"]))
        self.client.ensure_folder()
        try:
            cleanup_expired(self.client, now)
        except GrafanaPushError as exc:
            logger.warning("[grafana_push] expired-draft cleanup failed: %s", exc)
        self.client.push(dashboard)
        return {"path": dashboard_path(dashboard["uid"], context.workspace_id), "uid": dashboard["uid"],
                "expires_at": metadata["expires_at"], "reused": False}
