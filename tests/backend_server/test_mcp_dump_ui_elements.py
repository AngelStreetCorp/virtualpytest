"""
dump_ui_elements routes by platform and shows the elements to the model (BUG-0172).

A web device has no remote controller, so /server/remote/dumpUi always failed for it
("No remote controller found for device host"). Its dump is Playwright's dump_elements
through /server/web/executeCommand. And the agent forwards only the text part of a tool
result, so the elements must be in that text for the model to pass them on.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.tools.verification_tools import VerificationTools  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


class FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def post(self, path, data=None, **_):
        self.calls.append((path, data))
        return self.responses[path]


WEB_DUMP = {
    'success': True,
    'elements': [
        {'index': 0, 'tagName': 'input', 'selector': 'input[name="search_query"]',
         'textContent': '', 'attributes': {'name': 'search_query', 'placeholder': 'Search'},
         'isVisible': True, 'id': None},
        {'index': 1, 'tagName': 'div', 'selector': '#hidden', 'textContent': 'hidden',
         'attributes': {}, 'isVisible': False, 'id': 'hidden'},
    ],
    'output_data': {'page_title': 'YouTube', 'page_url': 'https://www.youtube.com/'},
}


def test_web_dump_uses_playwright_and_lists_elements():
    api = FakeApi({'/server/web/executeCommand': WEB_DUMP})
    tools = VerificationTools(api)

    result = tools.dump_ui_elements({'host_name': 'host-clone-1', 'device_id': 'host',
                                     'team_id': 't', 'platform': 'web'})

    assert result['isError'] is False
    path, body = api.calls[0]
    assert path == '/server/web/executeCommand'
    assert body['command'] == 'dump_elements'
    assert body['host_name'] == 'host-clone-1'

    assert [e['selector'] for e in result['elements']] == ['input[name="search_query"]']
    listed = json.loads(result['content'][0]['text'].split('Elements:\n', 1)[1])
    assert listed == [{'id': None, 'selector': 'input[name="search_query"]', 'tagName': 'input',
                       'textContent': '', 'name': 'search_query', 'placeholder': 'Search'}]


def test_mobile_dump_still_uses_remote_and_lists_elements():
    api = FakeApi({'/server/remote/dumpUi': {'success': True, 'elements': [
        {'id': 3, 'text': 'Search', 'contentDesc': '', 'clickable': True, 'bounds': {}},
    ]}})
    tools = VerificationTools(api)

    result = tools.dump_ui_elements({'host_name': 'h', 'device_id': 'device1', 'team_id': 't'})

    assert api.calls[0][0] == '/server/remote/dumpUi'
    text = result['content'][0]['text']
    assert text.startswith('1 elements (1 clickable)')
    listed = json.loads(text.split('Elements:\n', 1)[1])
    assert listed[0]['text'] == 'Search'
