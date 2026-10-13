"""
Screenshot Capture Helper

Captures a device screenshot and returns it as an MCP image content block (base64),
so execution tools (goto / action / verification) can embed the resulting screen state
inline in their responses.

The bytes are fetched from the host that holds the file (call_host): the MCP server and the host
do not share a filesystem.
"""

import base64
from typing import Dict, Any, Optional

from shared.src.lib.config.constants import get_team_id


def image_block_from_url(screenshot_url: str, host_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch a capture and return it as an MCP image content block (base64).

    A relative /host/<name>/stream/... path is fetched from the host that holds it, through
    call_host() (BUG-0388: the server VM has no nginx to route that path, so the old fetch
    through the caller's public URL never delivered the image on navigation/action/verification
    tools). Returns None on any failure so callers can skip the image without breaking their result.
    """
    from ..tools.screenshot_tools import _fetch_screenshot_bytes   # lazy: that module imports this package

    content, reason = _fetch_screenshot_bytes(screenshot_url, host_name)
    if content is None:
        print(f"[@MCP:image_block_from_url] Screenshot fetch failed: {reason}")
        return None
    mime = "image/png" if content[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return {"type": "image", "data": base64.b64encode(content).decode(), "mimeType": mime}


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

        return image_block_from_url(result.get('screenshot_url', ''), host_name)

    except Exception as e:
        print(f"[@MCP:capture_image_block] Screenshot capture error: {e}")
        return None
