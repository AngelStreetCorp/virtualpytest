"""Crawl Tools — BFS app crawling for site map generation (web + Android)"""

from typing import Dict, Any
from backend_server.src.mcp.utils.mcp_formatter import MCPFormatter, ErrorCategory
from backend_server.src.mcp.utils.api_client import MCPAPIClient

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'


class CrawlTools:
    """BFS app crawling tools for automated site mapping"""

    def __init__(self, api_client: MCPAPIClient):
        self.api_client = api_client
        self.formatter = MCPFormatter()

    def crawl_app(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        BFS crawl an app (web or Android) and return a structured site map with all screens and elements.

        ✅ START HERE: Use this tool first to discover the app structure before building test cases.
        Returns a site map with screens, elements, and links that you can use to build test graphs.

        AI Agent Workflow:
          1. crawl_app(url, host_name) -> understand app structure
          2. create_requirement(code, name) -> define what to test
          3. Build graph_json yourself (see save_testcase for format)
          4. save_testcase(name, graph_json) -> store in VPT
          5. execute_testcase(name, host_name, device_id) -> run tests
          6. capture_screenshot(host_name, device_id) -> grab results

        Example: crawl_app(host_name='host-clone-1', device_id='host', url='https://example.com', max_depth=2, max_pages=10)

        Args:
            params: {
                'host_name': str (REQUIRED - host name where device is connected),
                'device_id': str (OPTIONAL - device identifier, defaults to host for web or device1 for Android),
                'url': str (OPTIONAL - starting URL for web crawl, omit for Android native apps),
                'app_package': str (OPTIONAL - Android app package name for context),
                'username': str (OPTIONAL - login username or email, if app requires login),
                'password': str (OPTIONAL - login password, if app requires login),
                'browser_engine': str (OPTIONAL - chromium or webkit, use chromium for login-required sites),
                'max_depth': int (OPTIONAL - how many levels deep to crawl default 2),
                'max_pages': int (OPTIONAL - maximum number of screens to visit default 10),
                'skip_patterns': list (OPTIONAL - patterns to skip)
            }

        Returns:
            MCP-formatted response with site map tree showing all discovered screens and elements
        """
        host_name = params.get('host_name')

        if not host_name:
            return self.formatter.format_error("host_name is required")

        try:
            original_timeout = self.api_client.timeout
            self.api_client.timeout = 120

            try:
                response = self.api_client.post(
                    '/server/crawl/app',
                    data={
                        'host_name': host_name,
                        'device_id': params.get('device_id'),
                        'url': params.get('url'),
                        'app_package': params.get('app_package'),
                        'username': params.get('username'),
                        'password': params.get('password'),
                        'browser_engine': params.get('browser_engine'),
                        'max_depth': params.get('max_depth', 2),
                        'max_pages': params.get('max_pages', 10),
                        'skip_patterns': params.get('skip_patterns', []),
                    },
                    params={'host_name': host_name}
                )
            finally:
                self.api_client.timeout = original_timeout

            if not response.get('success'):
                return self.formatter.format_error(
                    f"Crawl failed: {response.get('error', 'unknown')}",
                    ErrorCategory.BACKEND
                )

            site_map = response.get('site_map', {})
            tree_view = response.get('tree_view', '')
            platform = response.get('platform', 'unknown')
            explored = response.get('screens_explored', 0)
            skipped = response.get('screens_skipped', 0)
            crawl_time = response.get('crawl_time_ms', 0)

            result_text = f"APP MAP — {platform} ({explored} screens explored, {skipped} skipped, {crawl_time}ms)\n"
            result_text += f"{'='*60}\n\n"

            if tree_view:
                result_text += f"SITE TREE:\n{tree_view}\n\n"

            for screen_id, info in site_map.items():
                title = info.get('title', 'Untitled')
                result_text += f"--- {title} ({screen_id}) ---\n"

                elements = info.get('elements', [])
                if elements:
                    result_text += "Elements:\n"
                    for el in elements:
                        result_text += f"  - {el}\n"

                # Web links
                links = info.get('links', [])
                if links:
                    result_text += f"Links: {len(links)} navigable\n"

                # Android navigable items
                navigable = info.get('navigable', [])
                if navigable:
                    result_text += f"Navigable: {len(navigable)} items\n"
                    for item in navigable[:10]:
                        result_text += f"  → {item.get('text', '')}\n"

                skipped_items = info.get('skipped', [])
                if skipped_items:
                    result_text += f"Skipped: {', '.join(skipped_items)}\n"

                result_text += "\n"

            return {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            }

        except Exception as e:
            return self.formatter.format_error(f"Crawl failed: {str(e)}", ErrorCategory.BACKEND)
