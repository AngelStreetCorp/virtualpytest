"""Map builder tool (auto_discover_screen): rule-based mapping of the current screen into nodes/edges.

Not an AI agent. On Android/web it reads the UI dump with no model call; only TV/STB menus are read
by a vision model. Agents (Atlas build-tree-*, QualiAI) call it as one step of their own plan.
"""

import json
from typing import Dict, Any
from ..utils.mcp_formatter import MCPFormatter, ErrorCategory
from ..utils.api_client import MCPAPIClient

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'


class ExplorationTools:
    """Map builder: rule-based screen mapping (vision model on TV/STB only)"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api_client = api_client
        self.formatter = MCPFormatter()
    
    def auto_discover_screen(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a map of the device's current screen: one node per screen reachable from it, one edge
        each, every edge validated on the device. A rule-based mapping step, not an AI agent: on
        Android and web it reads the UI dump (tappable elements of the app's own window, tab bar and
        toolbar before list items) with no model call; only on TV/STB does a vision model read the
        menu from the screenshot. It accepts every proposal (no review), then taps each target and
        tries its way back (tap Home, BACK, BACK x2). It does not add node verifications or rename
        the _temp labels; the editor's Build Map does both. Use it as one tool inside an agent's
        plan (Atlas build-tree-*, QualiAI): the agent picks the start screen and fixes failed edges.
        
        Example: auto_discover_screen(tree_id='abc', host_name='host1', userinterface_name='google_tv')
        
        Args:
            params: {
                'tree_id': str (REQUIRED - navigation tree ID),
                'host_name': str (REQUIRED - host name where device is connected),
                'userinterface_name': str (REQUIRED - UI interface name),
                'device_id': str (OPTIONAL - device identifier),
                'parent_node_id': str (OPTIONAL - parent node for discovered elements)
            }
            
        Returns:
            MCP-formatted response with discovered nodes, edges, and validation results
        """
        tree_id = params.get('tree_id')
        host_name = params.get('host_name')
        userinterface_name = params.get('userinterface_name')
        device_id = params.get('device_id', 'device1')
        parent_node_id = params.get('parent_node_id', 'home')
        team_id = params.get('team_id', DEFAULT_TEAM_ID)
        
        if not all([tree_id, host_name, userinterface_name]):
            return self.formatter.format_error("tree_id, host_name and userinterface_name are required")
        
        try:
            response = self.api_client.post(
                '/server/ai-generation/auto-discover-screen',
                data={
                    'tree_id': tree_id,
                    'userinterface_name': userinterface_name,
                    'device_id': device_id,
                    'parent_node_id': parent_node_id
                },
                params={'host_name': host_name, 'team_id': team_id}
            )
            
            if not response.get('success'):
                return self.formatter.format_error(
                    f"Auto-discover failed: {response.get('error')}",
                    ErrorCategory.BACKEND
                )
            
            nodes = response.get('nodes', [])
            edges = response.get('edges', [])
            validation_results = response.get('validation_results', [])
            
            # Format output - just show raw data, no extra processing
            result_text = f"🗺️ EXPLORATION + VALIDATION COMPLETE\n{'='*50}\n\n"
            result_text += f"📦 CREATED: {len(nodes)} nodes, {len(edges)} edges\n\n"
            
            if nodes:
                result_text += f"Nodes: {', '.join(nodes)}\n\n"
            
            # Show validation results (raw format from validate_next_item)
            result_text += f"🧪 VALIDATION: {len(validation_results)} items tested\n\n"

            # failed_items: structured list the skill prompt tells the agent to check
            # ("Check the 'failed_items' in auto_discover_screen response") — derived
            # here because the executor returns raw per-item results only.
            failed_items = []
            for r in validation_results:
                item = r.get('item', '')
                # Mobile/Web format
                if 'click_result' in r:
                    fwd = r.get('click_result', '?')
                    bck = r.get('back_result', '?')
                    ok = fwd == 'success' and bck == 'success'
                    if not ok:
                        failed_items.append({'item': item, 'forward': fwd, 'back': bck})
                    result_text += f"{'✅' if ok else '❌'} {item}: forward={fwd}, back={bck}\n"
                # TV format
                elif 'edges' in r:
                    for edge in r.get('edges', []):
                        et = edge.get('edge_type', '')
                        fwd = edge.get('action_sets', {}).get('forward', {}).get('result', '?')
                        bck = edge.get('action_sets', {}).get('reverse', {}).get('result', '?')
                        ok = fwd == 'success' and bck == 'success'
                        if not ok:
                            failed_items.append({'item': item, 'edge_type': et,
                                                 'forward': fwd, 'back': bck})
                        result_text += f"{'✅' if ok else '❌'} {item} ({et}): forward={fwd}, back={bck}\n"

            if failed_items:
                result_text += f"\n❌ failed_items ({len(failed_items)}):\n"
                result_text += json.dumps(failed_items, indent=2) + "\n"
                result_text += "\nFix each failed edge (analyze_screen_for_action for wrong selectors, update_edge to correct), then re-verify.\n"
            else:
                result_text += "\nfailed_items: [] — all validated edges passed.\n"

            return {"content": [{"type": "text", "text": result_text}], "isError": False}
            
        except Exception as e:
            return self.formatter.format_error(f"Auto-discover failed: {str(e)}", ErrorCategory.BACKEND)
