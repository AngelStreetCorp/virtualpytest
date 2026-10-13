"""
tests/backend_server/test_mcp_navigate_timeout.py — navigate_to_node waits as long as the
navigation route can take (BUG-0389).

/server/navigation/execute answers when the navigation is over and populates a cold cache first,
so it can take up to 5 + 30 + 5 + 120 s. The MCP client's default 30 s timed out on every cold
navigation while it kept running on the host.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.tools import navigation_tools  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


class _Api:
    def __init__(self):
        self.posts = []

    def resolve_userinterface_name(self, name, team_id):
        return 'tree-1', 'ui-1', 'model', None

    def post(self, endpoint, data=None, params=None, timeout=None):
        self.posts.append((endpoint, timeout))
        return {'success': True, 'message': 'Already at target'}

    def get(self, endpoint, params=None):
        return {'success': True}


def test_execute_uses_long_timeout():
    api = _Api()
    tools = navigation_tools.NavigationTools(api)
    tools.navigate_to_node({'host_name': 'h', 'device_id': 'device1', 'userinterface_name': 'yt',
                            'target_node_label': 'home', 'team_id': 't'})
    execute = [t for e, t in api.posts if e.startswith('/server/navigation/execute/')]
    assert execute == [navigation_tools.NAVIGATION_EXECUTE_TIMEOUT_S]
    assert navigation_tools.NAVIGATION_EXECUTE_TIMEOUT_S >= 160
