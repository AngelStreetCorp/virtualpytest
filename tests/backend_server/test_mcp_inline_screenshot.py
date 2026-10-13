"""
tests/backend_server/test_mcp_inline_screenshot.py — include_screenshot on navigation / action /
verification tools returns an image block fetched from the host (BUG-0413), and navigate_to_node
includes the screenshot by default.
"""
import base64
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.utils import screenshot_capture  # noqa: E402
    from backend_server.src.mcp.tools import screenshot_tools  # noqa: E402
    from backend_server.src.mcp.tool_definitions.verification_definitions import get_tools  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

URL = '/host/host-clone-1/stream/host/captures/capture_1.jpg'


def test_image_block_comes_from_the_host(monkeypatch):
    jpeg = b'\xff\xd8\xff' + b'x' * 50
    monkeypatch.setattr(screenshot_tools, '_fetch_screenshot_bytes', lambda url, host: (jpeg, None))
    block = screenshot_capture.image_block_from_url(URL, 'host-clone-1')
    assert block == {"type": "image", "data": base64.b64encode(jpeg).decode(), "mimeType": "image/jpeg"}


def test_png_mime_and_failure_returns_none(monkeypatch):
    png = b'\x89PNG\r\n\x1a\n' + b'x' * 10
    monkeypatch.setattr(screenshot_tools, '_fetch_screenshot_bytes', lambda url, host: (png, None))
    assert screenshot_capture.image_block_from_url(URL)['mimeType'] == 'image/png'
    monkeypatch.setattr(screenshot_tools, '_fetch_screenshot_bytes', lambda url, host: (None, 'boom'))
    assert screenshot_capture.image_block_from_url(URL) is None


def test_verify_node_schema_accepts_either_identifier():
    tool = next(t for t in get_tools() if t['name'] == 'verify_node')
    assert 'node_label' not in tool['inputSchema']['required']
    assert 'node_id' in tool['inputSchema']['properties']
