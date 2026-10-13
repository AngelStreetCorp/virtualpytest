"""
tests/backend_server/test_mcp_screenshot_fetch.py — capture_screenshot fetches the image from the
host with call_host(), not from https://localhost (BUG-0388).

The server VM has no nginx in production, so the old localhost fetch was always refused and the
MCP response never carried the image. A relative /host/<name>/stream/... URL is now fetched from
the host that serves it.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.tools import screenshot_tools  # noqa: E402
    from backend_server.src.lib.utils import server_utils  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

URL = '/host/host-clone-1/stream/capture1/captures/capture_1.jpg'
HOST = {'host_name': 'host-clone-1', 'host_api_url': 'http://10.0.0.5:6109'}
JPEG = b'\xff\xd8\xff' + b'x' * 100


class _Hosts:
    def __init__(self, hosts):
        self.hosts = hosts

    def get_host(self, name):
        return self.hosts.get(name)


class _Api:
    def __init__(self, reply):
        self.reply = reply

    def post(self, endpoint, data=None, params=None, timeout=None):
        return self.reply


@pytest.fixture
def hosts(monkeypatch):
    monkeypatch.setattr(server_utils, 'get_host_manager', lambda: _Hosts({'host-clone-1': HOST}))


def _capture(monkeypatch, call_host_reply):
    calls = []

    def fake_call_host(host_info, endpoint, **kwargs):
        calls.append((host_info, endpoint, kwargs))
        return call_host_reply

    monkeypatch.setattr(screenshot_tools, 'call_host', fake_call_host)
    monkeypatch.setattr(screenshot_tools, '_ocr_advanced', lambda b: '')
    tools = screenshot_tools.ScreenshotTools(_Api({'success': True, 'screenshot_url': URL, 'device_id': 'device1'}))
    return tools.capture_screenshot({'device_id': 'device1', 'host_name': 'host-clone-1', 'team_id': 't'}), calls


def test_image_fetched_from_host_and_embedded(monkeypatch, hosts):
    result, calls = _capture(monkeypatch, (JPEG, 200))
    assert calls == [(HOST, URL, {'method': 'GET', 'timeout': 10, 'raw_response': True})]
    images = [c for c in result['content'] if c['type'] == 'image']
    assert len(images) == 1 and images[0]['mimeType'] == 'image/jpeg'
    assert 'Image embed failed' not in result['content'][0]['text']


def test_host_error_is_reported(monkeypatch, hosts):
    result, _ = _capture(monkeypatch, ({'success': False, 'error': 'not found'}, 404))
    assert not [c for c in result['content'] if c['type'] == 'image']
    assert 'HTTP 404 from host host-clone-1: not found' in result['content'][0]['text']


def test_oversized_image_not_embedded(monkeypatch, hosts):
    big = b'x' * (screenshot_tools._MAX_EMBED_BYTES + 1)
    result, _ = _capture(monkeypatch, (big, 200))
    assert not [c for c in result['content'] if c['type'] == 'image']
    assert 'image too large to embed' in result['content'][0]['text']


def test_unregistered_host(monkeypatch):
    monkeypatch.setattr(server_utils, 'get_host_manager', lambda: _Hosts({}))
    data, err = screenshot_tools._fetch_screenshot_bytes(URL)
    assert data is None and 'host-clone-1 is not registered' in err


def test_host_name_parsed_from_url():
    assert screenshot_tools._host_name_from_url(URL) == 'host-clone-1'
    assert screenshot_tools._host_name_from_url('/stream/capture1/x.jpg') is None
