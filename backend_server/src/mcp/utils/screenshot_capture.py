"""
Screenshot Capture Helper

Captures a device screenshot and returns it as an MCP image content block (base64 PNG),
so execution tools (goto / action / verification) can embed the resulting screen state
inline in their responses.

Server-side HTTP fetch is the only path: the MCP server (backend_server VM) and the host
that holds the screenshot file do not share a filesystem.
"""

import base64
import os
import requests
from typing import Dict, Any, Optional
from flask import request, has_request_context

from shared.src.lib.config.constants import get_team_id


def _absolutize_url(url: str) -> str:
    """Turn a server-relative host path (e.g. /host/<name>/stream/...) into an absolute URL.

    The host serves screenshots via the same public base the MCP client used to reach us,
    so we derive the base from the inbound request (honoring proxy headers). MCP clients are
    external HTTP callers, not same-origin browsers, so they need an absolute URL to fetch it.
    """
    if not url or url.startswith(('http://', 'https://')) or not has_request_context():
        return url
    proto = request.headers.get('X-Forwarded-Proto', request.scheme)
    host = request.headers.get('X-Forwarded-Host') or request.headers.get('Host') or request.host
    # Host/X-Forwarded-Host are caller-controlled: only trust a host we are configured to be,
    # otherwise the server would fetch an attacker-chosen URL (SSRF). Fall back to our own base.
    if not host or host.split(':')[0].lower() not in _own_hostnames():
        server_base = os.getenv('SERVER_URL', 'http://localhost:5109').rstrip('/')
        return f"{server_base}/{url.lstrip('/')}"
    from urllib.parse import quote
    return f"{proto}://{quote(host, safe='.:[]-')}/{quote(url.lstrip('/'), safe='/?=&%+,:@')}"


def _own_hostnames() -> set:
    """Hostnames this server answers as: SERVER_URL, MCP_PUBLIC_HOSTS (comma list), loopback."""
    from urllib.parse import urlparse
    names = {'localhost', '127.0.0.1', '::1'}
    server_host = urlparse(os.getenv('SERVER_URL', 'http://localhost:5109')).hostname
    if server_host:
        names.add(server_host.lower())
    for extra in os.getenv('MCP_PUBLIC_HOSTS', '').split(','):
        extra = extra.strip().lower()
        if extra:
            names.add(extra.split(':')[0])
    return names


def image_block_from_url(screenshot_url: str) -> Optional[Dict[str, Any]]:
    """Fetch a screenshot URL and return it as an MCP image content block (base64 PNG).

    Returns None on any failure so callers can skip the image without breaking their result.
    """
    try:
        url = _absolutize_url(screenshot_url or '')
        if not url:
            return None

        # /host/<name>/stream/... screenshots are served as static files (auth-exempt).
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200 or not resp.content:
            print(f"[@MCP:image_block_from_url] Screenshot fetch HTTP {resp.status_code}")
            return None

        b64 = base64.b64encode(resp.content).decode()
        return {"type": "image", "data": b64, "mimeType": "image/png"}

    except Exception as e:
        print(f"[@MCP:image_block_from_url] Screenshot fetch error: {e}")
        return None


def capture_image_block(
    api_client,
    device_id: str,
    host_name: Optional[str] = None,
    team_id: Optional[str] = None,
    fast: bool = False,
) -> Optional[Dict[str, Any]]:
    """Capture a screenshot and return it as an MCP image content block.

    Returns a dict {"type": "image", "data": <base64>, "mimeType": "image/png"} on success,
    or None on any failure (so callers can skip the image without breaking their primary
    result). The device lock is expected to still be held by the caller at this point.

    fast=True: caller computes its own fingerprint (the auto-builder), so the host skips the
    ~1-3s cv2/OCR fingerprint + 0.5s settle — the inline screenshot then costs ~sub-second.
    """
    try:
        team_id = team_id or get_team_id()
        data = {'device_id': device_id}
        if fast:
            data['fast'] = True
        if host_name:
            data['host_name'] = host_name

        result = api_client.post(
            '/server/av/takeScreenshot',
            data=data,
            params={'team_id': team_id},
        )

        if not result.get('success'):
            print(f"[@MCP:capture_image_block] Screenshot capture failed: {result.get('error')}")
            return None

        return image_block_from_url(result.get('screenshot_url', ''))

    except Exception as e:
        print(f"[@MCP:capture_image_block] Screenshot capture error: {e}")
        return None
