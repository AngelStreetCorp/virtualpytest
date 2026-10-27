"""
Navigation Tools - UI navigation execution

Navigate through UI trees using pathfinding and action execution.
"""

import time
from typing import Dict, Any, Optional
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from ..utils.lock_ownership import auto_lock
from ..utils.screenshot_capture import capture_image_block
from shared.src.lib.config.constants import APP_CONFIG, get_team_id
from backend_server.src.lib.servers import turn


# Upper bound of /server/navigation/execute: 5 + 30 + 5 + 120 s (see execute_navigation), plus slack.
NAVIGATION_EXECUTE_TIMEOUT_S = 180
# Localize = three frames 0.3 s apart + the matcher (+ a cold tree load on the first call).
LOCALIZE_TIMEOUT_S = 60
# Verdict kinds navigate_to_node starts from (TASK-104). Only a fingerprint match: 'live' is
# full-frame motion, which a menu over a moving background also shows, and starting a path
# from the wrong node costs more than starting from the remembered one.
LOCALIZE_POSITION_KINDS = ('node',)


class NavigationTools:
    """UI navigation execution tools"""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
        # Track active control sessions per device for auto-lock
        self._control_sessions: Dict[str, str] = {}

    def _auto_lock(self, params: Dict[str, Any], host_name: str, device_id: str, team_id: str,
                   force_unlock: bool = False) -> Optional[Dict[str, Any]]:
        """Lock the device for this call, or run under the caller's own lock. Returns an error dict
        when someone else holds it (never taken over), None to proceed. See lock_ownership."""
        return auto_lock(self.api, self._control_sessions, params, host_name, device_id, team_id,
                         force_unlock, 'nav')

    def _auto_unlock(self, host_name: str, device_id: str, team_id: str) -> None:
        """Release device lock acquired by auto-lock."""
        device_key = f"{host_name}:{device_id}"
        session_id = self._control_sessions.pop(device_key, None)
        if not session_id:
            return
        data = {
            'host_name': host_name,
            'device_id': device_id,
            'session_id': session_id,
        }
        self.api.post('/server/control/releaseControl', data=data, params={'team_id': team_id})
    
    def list_navigation_nodes(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List navigation nodes available in a tree
        
        Can accept EITHER tree_id OR userinterface_name (same approach as frontend)
        
        Args:
            params: {
                'tree_id': str (OPTIONAL) - Direct tree ID,
                'userinterface_name': str (OPTIONAL) - Convert to tree_id first,
                'team_id': str (OPTIONAL),
                'page': int (OPTIONAL) - Page number (default: 0),
                'limit': int (OPTIONAL) - Results per page (default: 100)
            }
            
        Returns:
            MCP-formatted response with list of navigation nodes and their properties
        """
        tree_id = params.get('tree_id')
        userinterface_name = params.get('userinterface_name')
        team_id = params.get('team_id', get_team_id())
        page = params.get('page', 0)
        limit = params.get('limit', 100)
        
        # OPTION 1: If userinterface_name provided, convert to tree_id using api_client helper
        if userinterface_name and not tree_id:
            tree_id, userinterface_id, _, error = self.api.resolve_userinterface_name(userinterface_name, team_id)
            if error:
                return {"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True}
            
            # Get tree with nodes for this specific case (needs metadata.nodes)
            tree_result = self.api.get(f'/server/navigationTrees/getTreeByUserInterfaceId/{userinterface_id}', params={'include_nested': 'true', 'team_id': team_id})
            if not tree_result.get('success') or not tree_result.get('tree'):
                return {"content": [{"type": "text", "text": f"Error: No navigation tree found for '{userinterface_name}'"}], "isError": True}
            
            nodes = tree_result['tree'].get('metadata', {}).get('nodes', [])
            
            print(f"[@MCP:list_navigation_nodes] Got tree_id: {tree_id} with {len(nodes)} nodes")
            
            # Filter out ENTRY nodes (same as frontend)
            filtered_nodes = [node for node in nodes if node.get('id') != 'ENTRY' and node.get('type') != 'entry' and node.get('label', '').lower() != 'entry']
            
            if not filtered_nodes:
                return {"content": [{"type": "text", "text": f"No navigation nodes found for '{userinterface_name}'"}], "isError": False}
            
            response_text = f"📋 Navigation nodes for '{userinterface_name}' (tree: {tree_id}, {len(filtered_nodes)} nodes):\n\n"
            response_text += "  ⚠️  CRITICAL: Use the node_id STRING shown below (e.g., 'home'), NOT the database UUID!\n"
            response_text += "      For create_edge: source_node_id='home' ✅  NOT source_node_id='ce97c317-...' ❌\n\n"
            
            for node in filtered_nodes[:50]:  # Limit display to first 50
                # CRITICAL: Show node_id (the string identifier), not id (the UUID)
                node_id = node.get('node_id', 'unknown')  # This is the actual node_id string (e.g., 'home')
                db_uuid = node.get('id')  # This is the database UUID (primary key)
                label = node.get('label', 'unnamed')
                node_type = node.get('type', 'unknown')
                
                # Show the string identifier prominently
                response_text += f"  • {label}\n"
                response_text += f"      → node_id: '{node_id}' ← USE THIS in create_edge()\n"
                if db_uuid:
                    response_text += f"      (DB UUID: {db_uuid}... - internal only)\n"
                response_text += f"      type: {node_type}\n"
            
            if len(filtered_nodes) > 50:
                response_text += f"\n... and {len(filtered_nodes) - 50} more nodes\n"
            
            return {
                "content": [{"type": "text", "text": response_text}],
                "isError": False,
                "nodes": filtered_nodes,
                "total": len(filtered_nodes),
                "tree_id": tree_id  # Include tree_id for reference
            }
        
        # OPTION 2: Direct tree_id lookup (backward compatible)
        if not tree_id:
            return {"content": [{"type": "text", "text": "Error: Either tree_id or userinterface_name is required"}], "isError": True}
        
        query_params = {
            'team_id': team_id,
            'page': page,
            'limit': limit
        }
        
        # Call EXISTING endpoint
        print(f"[@MCP:list_navigation_nodes] Calling /server/navigationTrees/{tree_id}/nodes")
        result = self.api.get(f'/server/navigationTrees/{tree_id}/nodes', params=query_params)
        
        # Check for errors
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to list navigation nodes')
            return {"content": [{"type": "text", "text": f"❌ List failed: {error_msg}"}], "isError": True}
        
        # Format response
        nodes = result.get('nodes', [])
        total = result.get('total', len(nodes))
        
        if not nodes:
            # Distinguish a genuinely-empty tree from a tree_id that isn't a navigation tree at
            # all (common mistake: passing a userinterface id as tree_id — they are different UUIDs).
            tree_check = self.api.get(f'/server/navigationTrees/{tree_id}', params={'team_id': team_id})
            if not tree_check.get('success') or not tree_check.get('tree'):
                return {"content": [{"type": "text", "text": (
                    f"❌ No navigation tree with id '{tree_id}'. "
                    f"If this is a userinterface id, pass userinterface_name instead — "
                    f"the navigation tree_id is a different UUID."
                )}], "isError": True}
            return {"content": [{"type": "text", "text": f"No navigation nodes found in tree {tree_id}"}], "isError": False}

        response_text = f"📋 Navigation nodes in tree {tree_id} (showing {len(nodes)} of {total}):\n\n"
        response_text += "  ⚠️  CRITICAL: Use the node_id STRING shown below (e.g., 'home'), NOT the database UUID!\n"
        response_text += "      For create_edge: source_node_id='home' ✅  NOT source_node_id='ce97c317-...' ❌\n\n"
        
        for node in nodes[:50]:  # Limit display to first 50
            # CRITICAL: Show node_id (the string identifier), not id (the UUID)
            node_id = node.get('node_id', 'unknown')  # This is the actual node_id string (e.g., 'home')
            db_uuid = node.get('id')  # This is the database UUID (primary key)
            label = node.get('label', 'unnamed')
            node_type = node.get('type', 'unknown')
            
            response_text += f"  • {label}\n"
            response_text += f"      → node_id: '{node_id}' ← USE THIS in create_edge()\n"
            if db_uuid:
                response_text += f"      (DB UUID: {db_uuid}... - internal only)\n"
            response_text += f"      type: {node_type}\n"
            
            # Show position if available
            position = node.get('position')
            if position:
                x = position.get('x', 0)
                y = position.get('y', 0)
                response_text += f"      position: ({x}, {y})\n"
        
        if len(nodes) > 50:
            response_text += f"\n... and {len(nodes) - 50} more nodes\n"
        
        return {
            "content": [{"type": "text", "text": response_text}],
            "isError": False,
            "nodes": nodes,  # Include full data for programmatic use
            "total": total
        }
    
    @staticmethod
    def _localize_off(host_name: str, device_id: str) -> Optional[str]:
        """Why Localize is off for this device, from the host's last ping, or None. No image monitor, no
        Localize (owner, 2026-10-14): `monitoring_off` lists the devices whose profile runs no vpt-monitor-img,
        the same list the frontend reads. An unknown host is not refused here: the host refuses it itself."""
        try:
            if turn.target_url():
                # The device belongs to another server: read that server's row, not this registry (TASK-179 section 6)
                reply = turn.get_json('/server/system/getAllHosts', {'scope': 'local'}) or {}
                host = next((h for h in reply.get('hosts') or [] if h.get('host_name') == host_name), {})
            else:
                from backend_server.src.lib.utils.server_utils import get_host_manager
                host = get_host_manager().get_host(host_name) or {}
        except Exception:
            return None
        if device_id in ((host.get('system_stats') or {}).get('monitoring_off') or []):
            return (f"Localize is off for {device_id} on {host_name}: its monitoring profile does not run "
                    f"the image monitor (vpt-monitor-img)")
        return None

    def _localize(self, host_name: str, device_id: str, userinterface_name: str, team_id: str) -> Dict[str, Any]:
        """POST the host's Localize (auto-proxied to /host/navigation/localize); the raw result."""
        return self.api.post('/server/navigation/localize',
                             data={'host_name': host_name, 'device_id': device_id,
                                   'userinterface_name': userinterface_name},
                             params={'team_id': team_id}, timeout=LOCALIZE_TIMEOUT_S)

    def localize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Where is the device now? One verdict from the live screen, the same answer as the
        Localize button: kind = signal (black / no signal), live (video playing; node_id = the
        tree's live node when one is flagged), node (a saved screen), overlay (popup / keyboard /
        notification, node_id = the screen under it), known_screen (screen memory), or unknown.

        Example: localize(host_name='host1', device_id='device1', userinterface_name='stb-<operator>')

        Args:
            params: {
                'host_name': str (REQUIRED), 'device_id': str (REQUIRED),
                'userinterface_name': str (REQUIRED - the tree to localize in)
            }

        Returns:
            MCP-formatted response: the verdict as text plus {verdict, frame_url}
        """
        host_name = params.get('host_name')
        device_id = params.get('device_id')
        userinterface_name = params.get('userinterface_name')
        team_id = params.get('team_id', get_team_id())
        if not host_name or not device_id or not userinterface_name:
            return {"content": [{"type": "text", "text": "Error: host_name, device_id and userinterface_name are required"}],
                    "isError": True}
        off = self._localize_off(host_name, device_id)
        if off:
            return {"content": [{"type": "text", "text": off}], "isError": True}
        result = self._localize(host_name, device_id, userinterface_name, team_id)
        if not result.get('success'):
            return {"content": [{"type": "text", "text": f"Localize failed: {result.get('error', 'unknown error')}"}],
                    "isError": True}
        verdict = result.get('verdict') or {}
        node = f" node_id={verdict['node_id']}" if verdict.get('node_id') else ''
        text = (f"kind={verdict.get('kind')} label={verdict.get('label')}{node} "
                f"confidence={verdict.get('confidence')}\nevidence={verdict.get('evidence')}\n"
                f"frame={result.get('frame_url')}")
        return {"content": [{"type": "text", "text": text}],
                "verdict": verdict, "frame_url": result.get('frame_url')}

    def localize_coverage(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        How much of each tree can Localize name? Per userinterface: screen nodes, % with a pixel
        fingerprint, % with a device identity (android activity / web URL), the live node (or
        none), fingerprint age in days, active "Wrong screen?" corrections (TASK-107 goal 3).

        Example: localize_coverage(userinterface_name='stb-<operator>')

        Args:
            params: {'userinterface_name': str (optional - one interface; all when omitted)}

        Returns:
            MCP-formatted response: one line per interface plus {userinterfaces: [...]}
        """
        team_id = params.get('team_id', get_team_id())
        query = {'team_id': team_id}
        if params.get('userinterface_name'):
            query['userinterface_name'] = params['userinterface_name']
        result = self.api.get('/server/navigation/localize/coverage', params=query)
        if not result.get('success'):
            return {"content": [{"type": "text", "text": f"Coverage failed: {result.get('error', 'unknown error')}"}],
                    "isError": True}
        rows = result.get('userinterfaces') or []
        lines = []
        for r in rows:
            age = r.get('fingerprint_age_days') or {}
            live = (r.get('live_node') or {}).get('label') or 'none'
            lines.append(f"{r['userinterface_name']}: {r['fingerprinted']}/{r['screens']} fingerprinted "
                         f"({r['fingerprinted_pct']}%), identity {r['identity_pct']}%, live node {live}, "
                         f"median age {age.get('median', '-')} d, corrections {r.get('corrections', 0)}")
        return {"content": [{"type": "text", "text": "\n".join(lines) or "No userinterface found"}],
                "userinterfaces": rows}

    def navigate_to_node(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Navigate to target node using pathfinding. Automatically acquires and releases device lock.
        Navigation cache is populated automatically if needed. tree_id auto-resolved from userinterface_name.

        Example: navigate_to_node(host_name='host1', device_id='device1', userinterface_name='google_tv', target_node_label='shop')

        Args:
            params: {
                'host_name': str (REQUIRED - host where device is connected),
                'device_id': str (REQUIRED - device identifier),
                'userinterface_name': str (REQUIRED - UI name for auto-resolving tree_id),
                'target_node_label': str (REQUIRED - target screen like shop or home),
                'force_unlock': bool (OPTIONAL - clears a STALE lock or your own only; never aborts another caller's live run (device_busy: wait/queue) nor another user's take-control),
                'session_id': str (OPTIONAL - session_id from take_control; runs under that lock),
                'include_screenshot': bool (OPTIONAL - true: always attach a screenshot; false: never;
                                        omitted: only when Localize cannot confirm the target, TASK-107)
            }

        After the goto (done or failed) Localize reads where the device is and the response says it
        (`📍 Localize: ...`, and `localize` = the verdict), so an agent re-plans from the real
        position without a screenshot. An image is attached when Localize does not confirm the
        target (unknown / overlay / another node), or when the device has no Localize (lite).

        Returns:
            MCP-formatted response with navigation result
        """
        tree_id = params.get('tree_id')
        userinterface_name = params.get('userinterface_name')
        target_node_id = params.get('target_node_id')
        target_node_label = params.get('target_node_label')
        device_id = params.get('device_id')
        team_id = params.get('team_id', get_team_id())
        current_node_id = params.get('current_node_id')
        host_name = params.get('host_name')
        force_unlock = bool(params.get('force_unlock', False))
        include_screenshot = params.get('include_screenshot', 'auto')
        # Private: the Atlas session's "was Stop pressed" check (TASK-140 G7). Never forwarded.
        should_cancel = params.pop('_should_cancel', None)

        # Validate required parameters
        if not userinterface_name:
            return {"content": [{"type": "text", "text": "Error: userinterface_name is required"}], "isError": True}
        if not host_name:
            return {"content": [{"type": "text", "text": "Error: host_name is required"}], "isError": True}
        if not device_id:
            return {"content": [{"type": "text", "text": "Error: device_id is required"}], "isError": True}
        if not target_node_id and not target_node_label:
            return {"content": [{"type": "text", "text": "Error: target_node_label is required"}], "isError": True}

        # Auto-lock device
        lock_error = self._auto_lock(params, host_name, device_id, team_id, force_unlock)
        if lock_error:
            return lock_error

        try:
            # Auto-resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                tree_id, _, _, error = self.api.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return {"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True}

            # Build request - SAME format as frontend (navigationExecutionUtils.ts line 58-65)
            data = {
                'userinterface_name': userinterface_name,
                'device_id': device_id,
                'host_name': host_name
            }

            if target_node_id:
                data['target_node_id'] = target_node_id
            if target_node_label:
                data['target_node_label'] = target_node_label
            # No position given: start from the screen the fingerprints recognise (TASK-104),
            # not from the executor's memory of the last run. Any other kind keeps the old behaviour.
            if not current_node_id and not self._localize_off(host_name, device_id):
                verdict = self._localize(host_name, device_id, userinterface_name, team_id).get('verdict') or {}
                if verdict.get('kind') in LOCALIZE_POSITION_KINDS and verdict.get('node_id'):
                    current_node_id = verdict['node_id']
                print(f"[@MCP:navigate_to_node] localize kind={verdict.get('kind')} start={current_node_id}")
            if current_node_id:
                data['current_node_id'] = current_node_id

            query_params = {'team_id': team_id}

            # Call EXISTING endpoint - SAME as frontend (navigationExecutionUtils.ts line 53)
            print(f"[@MCP:navigate_to_node] Calling /server/navigation/execute/{tree_id}")
            # The route populates a cold cache first (cache check 5 s + populate 30 s + re-check 5 s),
            # then starts the navigation on the host, which answers with an execution_id at once;
            # the poll below waits for the end (BUG-0389, BUG-0411).
            result = self.api.post(
                f'/server/navigation/execute/{tree_id}',
                data=data,
                params=query_params,
                timeout=NAVIGATION_EXECUTE_TIMEOUT_S,
            )

            # Check for errors
            if not result.get('success'):
                error_msg = result.get('error', 'Navigation failed')
                return self._report_position(
                    {"content": [{"type": "text", "text": f"Navigation failed: {error_msg}"}], "isError": True},
                    include_screenshot, host_name, device_id, userinterface_name, team_id,
                    target_node_id, target_node_label)

            # Check if async (returns execution_id) - SAME as frontend (navigationExecutionUtils.ts line 75)
            if result.get('execution_id'):
                execution_id = result['execution_id']
                print(f"[@MCP:navigate_to_node] Async execution started: {execution_id}")

                # POLL for completion - SAME pattern as frontend (navigationExecutionUtils.ts line 84-142)
                response = self._poll_navigation_completion(execution_id, device_id, host_name, team_id,
                                                            target_node_label or target_node_id,
                                                            should_cancel=should_cancel)
            else:
                print(f"[@MCP:navigate_to_node] Sync execution completed")
                response = self.formatter.format_api_response(result)
            return self._report_position(response, include_screenshot, host_name, device_id, userinterface_name,
                                         team_id, target_node_id, target_node_label)
        finally:
            # Auto-unlock device
            self._auto_unlock(host_name, device_id, team_id)
    
    @staticmethod
    def _confirms(verdict: Optional[Dict[str, Any]], target_id: Optional[str], target_label: Optional[str]) -> bool:
        """The verdict names the target: a node (or the live node) whose id or label is the target's."""
        if not verdict or verdict.get('kind') not in ('node', 'live') or not verdict.get('node_id'):
            return False
        norm = lambda v: str(v or '').strip().lower()
        return (bool(target_id) and verdict['node_id'] == target_id) or \
            (bool(target_label) and norm(verdict.get('label')) == norm(target_label))

    def _report_position(self, response: Dict[str, Any], include_screenshot, host_name: str, device_id: str,
                         userinterface_name: str, team_id: str, target_id: Optional[str],
                         target_label: Optional[str]) -> Dict[str, Any]:
        """After a goto: say where the device is (Localize), and attach a screenshot only when asked
        (True) or when Localize cannot confirm the target ('auto'). TASK-107 goal 5: the agent reads a
        one-line verdict instead of an image on every step."""
        verdict = None
        if include_screenshot is not False and not self._localize_off(host_name, device_id):
            try:
                verdict = self._localize(host_name, device_id, userinterface_name, team_id).get('verdict')
            except Exception as e:
                print(f"[@MCP:navigate_to_node] localize after goto failed: {e}")
        confirmed = self._confirms(verdict, target_id, target_label)
        if verdict:
            node = f" node_id={verdict['node_id']}" if verdict.get('node_id') else ''
            note = 'confirms the target' if confirmed else f"NOT the target ({target_label or target_id})"
            response.setdefault('content', []).append({'type': 'text', 'text': (
                f"📍 Localize: kind={verdict.get('kind')} label={verdict.get('label')}{node} "
                f"confidence={verdict.get('confidence')} — {note}")})
            response['localize'] = verdict
        attach = include_screenshot is True or (include_screenshot == 'auto' and not confirmed)
        print(f"[@MCP:navigate_to_node] position kind={(verdict or {}).get('kind')} confirmed={confirmed} "
              f"screenshot={'attached' if attach else 'skipped'}")
        if attach:
            self._attach_screenshot(response, device_id, host_name, team_id)
        return response

    def _attach_screenshot(self, response: Dict[str, Any], device_id: str, host_name: str, team_id: str) -> None:
        """Append a device screenshot (base64 image block) to an MCP response, in place.

        No-op if the capture fails — never breaks the primary navigation result.
        """
        image_block = capture_image_block(self.api, device_id, host_name, team_id)
        if image_block:
            response.setdefault('content', []).append(image_block)

    def _poll_navigation_completion(self, execution_id: str, device_id: str, host_name: str, team_id: str, target_label: str, max_wait: int = 120, include_screenshot: bool = False,
                                    should_cancel=None) -> Dict[str, Any]:
        """
        Poll navigation execution until complete
        
        REUSES existing /server/navigation/execution/<id>/status API (same as frontend)
        Pattern from navigationExecutionUtils.ts lines 84-142
        """
        poll_interval = 1  # 1 second (same as frontend line 93)
        elapsed = 0
        
        print(f"[@MCP:poll_navigation] Polling for execution {execution_id} (max {max_wait}s)")
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            if should_cancel is not None and should_cancel():
                return self._cancel_navigation(execution_id, device_id, host_name, team_id, target_label)

            # Poll status endpoint - SAME as frontend (navigationExecutionUtils.ts line 85-86)
            status = self.api.get(
                f'/server/navigation/execution/{execution_id}/status',
                params={'device_id': device_id, 'host_name': host_name, 'team_id': team_id}
            )
            
            current_status = status.get('status')
            
            if current_status == 'completed':
                print(f"[@MCP:poll_navigation] Navigation completed successfully after {elapsed}s")
                result = status.get('result', {})
                
                # Format detailed navigation summary
                formatted_result = self._format_navigation_result(result, target_label)
                response = {"content": [{"type": "text", "text": formatted_result}], "isError": False}
                if include_screenshot:
                    self._attach_screenshot(response, device_id, host_name, team_id)
                return response
            
            elif current_status == 'error':
                print(f"[@MCP:poll_navigation] Navigation failed after {elapsed}s")
                error = status.get('error', 'Navigation failed')
                return {"content": [{"type": "text", "text": f"❌ Navigation failed: {error}"}], "isError": True}
            
            elif current_status == 'cancelled':
                return {"content": [{"type": "text", "text": f"Navigation stopped: {status.get('message') or 'cancelled'}"}],
                        "isError": False}

            elif current_status == 'running':
                progress = status.get('progress', 0)
                message = status.get('message', 'Running...')
                print(f"[@MCP:poll_navigation] Status: {message} ({progress}%) - {elapsed}s elapsed")
        
        print(f"[@MCP:poll_navigation] Navigation timed out after {max_wait}s")
        return {"content": [{"type": "text", "text": f"⏱️ Navigation timed out after {max_wait}s"}], "isError": True}
    
    def _cancel_navigation(self, execution_id: str, device_id: str, host_name: str, team_id: str,
                           target_label: str) -> Dict[str, Any]:
        """The user pressed Stop: ask the host to stop before its next edge, and say where it got to."""
        params = {'device_id': device_id, 'host_name': host_name, 'team_id': team_id}
        step = ''
        try:
            self.api.post(f'/server/navigation/execution/{execution_id}/cancel', data={}, params=params, timeout=5)
            status = self.api.get(f'/server/navigation/execution/{execution_id}/status', params=params)
            step = status.get('message') or ''
        except Exception as e:
            print(f"[@MCP:poll_navigation] cancel call failed: {e}")
        text = f"Navigation to {target_label} stopped by the user" + (f" at: {step}" if step else "")
        return {"content": [{"type": "text", "text": text}], "isError": False}

    def _format_navigation_result(self, result: Dict[str, Any], target_label: str) -> str:
        """
        Format navigation result with detailed step information
        
        Args:
            result: Navigation execution result from backend
            target_label: Target node label for reference
            
        Returns:
            Formatted string with navigation summary
        """
        message = result.get('message', f'Navigation to {target_label} completed')
        already_at_target = result.get('already_at_target', False)
        
        # Case 1: Already at target - simple message
        if already_at_target:
            return f"✅ {message}"
        
        # Case 2: Navigation with steps - detailed summary
        navigation_path = result.get('navigation_path', [])
        transitions_executed = result.get('transitions_executed', 0)
        actions_executed = result.get('actions_executed', 0)
        execution_time = result.get('execution_time', 0)
        
        # Build detailed output
        output = f"✅ {message}\n"
        output += f"📊 Summary: {transitions_executed} transitions, {actions_executed} actions, {execution_time:.1f}s\n"
        
        # Show navigation path if available
        if navigation_path and len(navigation_path) > 0:
            output += f"\n🗺️  Navigation Path ({len(navigation_path)} steps):\n"
            for i, step in enumerate(navigation_path):
                step_num = i + 1
                from_node = step.get('from_node_label', 'unknown')
                to_node = step.get('to_node_label', 'unknown')
                
                # Get action summary for this step
                actions = step.get('actions', [])
                action_summary = self._format_step_actions(actions)
                
                output += f"  {step_num}. {from_node} → {to_node}"
                if action_summary:
                    output += f" ({action_summary})"
                output += "\n"
        
        return output
    
    def _format_step_actions(self, actions: list) -> str:
        """Format actions for a single navigation step"""
        if not actions:
            return "no actions"
        
        if len(actions) == 1:
            action = actions[0]
            cmd = action.get('command', 'unknown')
            
            # Format based on command type
            if cmd == 'click_element_by_id':
                element_id = action.get('params', {}).get('element_id', '')
                return f"click {element_id}" if element_id else "click"
            elif cmd == 'press_key':
                key = action.get('params', {}).get('key', '')
                return f"press {key}" if key else "press key"
            elif cmd == 'launch_app':
                return "launch app"
            elif cmd == 'tap_coordinates':
                return "tap"
            else:
                return cmd
        else:
            # Multiple actions - just show count
            return f"{len(actions)} actions"
    
    def preview_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get compact text preview of userinterface navigation tree

        Shows all nodes, edges (with edge_ids for execute_edge), actions, and verifications in compact format.
        Perfect for quick overview: "What do we test and how?"

        Use this first to see available transitions, then use execute_edge with the edge_id shown.

        Args:
            params: {
                'userinterface_name': str (REQUIRED) - e.g., 'netflix_mobile'
                'team_id': str (OPTIONAL)
            }

        Returns:
            MCP-formatted response with:
            - Compact text showing all transitions with edge_ids
            - userinterface_name: requested interface name
            - userinterface_id: internal UUID for the interface
            - tree_id: navigation tree UUID (use this for execute_edge, navigate_to_node, etc.)
            - nodes_count: number of navigation nodes
            - edges_count: number of navigation edges

        Example output:
            netflix_mobile (7 nodes, 13 transitions)

            Entry→home: launch_app + tap(540,1645) [✓ Startseite]
              edge_id: edge-123
            home⟷search: click(Suchen) ⟷ click(Nach oben navigieren) [✓ Suchen]
              edge_id: edge-456
            home⟷content_detail: click(The Witcher) ⟷ BACK [✓ abspielen]
              edge_id: edge-789
            ...
        """
        userinterface_name = params.get('userinterface_name')
        team_id = params.get('team_id', get_team_id())
        
        if not userinterface_name:
            return {"content": [{"type": "text", "text": "Error: userinterface_name is required"}], "isError": True}
        
        # Get complete userinterface data using api_client helper
        try:
            tree_id, userinterface_id, _, error = self.api.resolve_userinterface_name(userinterface_name, team_id)
            if error:
                return {"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True}
            
            # Get complete tree data with metrics
            tree_result = self.api.get(
                f'/server/navigationTrees/getTreeByUserInterfaceId/{userinterface_id}',
                params={
                    'team_id': team_id,
                    'include_nested': 'true',
                    'include_metrics': 'true'
                }
            )
            
            if not tree_result.get('success') or not tree_result.get('tree'):
                return {"content": [{"type": "text", "text": f"Error: No navigation data found for '{userinterface_name}'"}], "isError": True}
            
            complete_data = tree_result['tree'].get('metadata', {})

            # Format compact preview
            output = self._format_compact_preview(userinterface_name, complete_data)

            return {
                "content": [{"type": "text", "text": output}],
                "isError": False,
                "userinterface_name": userinterface_name,
                "userinterface_id": userinterface_id,
                "tree_id": tree_id,
                "nodes_count": len(complete_data.get('nodes', [])),
                "edges_count": len(complete_data.get('edges', []))
            }
            
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}
    
    def _format_compact_preview(self, ui_name: str, data: Dict[str, Any]) -> str:
        """Format navigation tree as compact text with nodes and transitions"""
        nodes = data.get('nodes', [])
        edges = data.get('edges', [])
        
        # Create node lookup (by node_id, not id)
        node_lookup = {node.get('node_id', node.get('id')): node for node in nodes}
        
        # Count transitions (edges * 2 for bidirectional)
        transition_count = sum(2 if len(edge.get('action_sets', [])) > 1 else 1 for edge in edges)
        
        output = f"{ui_name} ({len(nodes)} nodes, {transition_count} transitions)\n\n"
        
        # === NODES SECTION ===
        output += "=== NODES ===\n"
        for node in nodes:
            node_id = node.get('node_id', node.get('id', 'unknown'))
            label = node.get('label', node_id)
            
            # Skip entry-node (technical node, not a real screen)
            if node_id == 'entry-node' or label == 'Entry':
                continue
            
            # Show only label (for human readability)
            output += f"• {label}\n"
            
            # Get verifications from ROOT level (single source of truth)
            verifications = node.get('verifications', [])
            if verifications:
                for verif in verifications:
                    method = verif.get('method', '')
                    expected = verif.get('expected', True)
                    params = verif.get('params', {})
                    text = params.get('text', '')
                    timeout = params.get('timeout', 5000)
                    symbol = '✓' if expected else '✗'
                    if expected:
                        output += f"  Verifications: {symbol} {text} appears ({timeout}ms)\n"
                    else:
                        output += f"  Verifications: {symbol} {text} NOT present ({timeout}ms)\n"
            else:
                output += f"  Verifications: none\n"
            output += "\n"
        
        # === TRANSITIONS SECTION ===
        output += "=== TRANSITIONS ===\n"
        for edge in edges:
            # Get source and target labels
            source_node_id = edge.get('source_node_id', edge.get('source'))
            target_node_id = edge.get('target_node_id', edge.get('target'))
            
            source_label = edge.get('source_label')
            target_label = edge.get('target_label')
            
            if not source_label:
                source_node = node_lookup.get(source_node_id)
                source_label = source_node.get('label', source_node_id) if source_node else source_node_id
            
            if not target_label:
                target_node = node_lookup.get(target_node_id)
                target_label = target_node.get('label', target_node_id) if target_node else target_node_id
            
            action_sets = edge.get('action_sets', [])
            
            if not action_sets:
                continue
            
            # Get edge_id for execute_edge tool
            edge_id = edge.get('edge_id', edge.get('id', 'unknown'))

            # Check if bidirectional
            is_bidirectional = len(action_sets) > 1 and action_sets[1].get('actions')

            if is_bidirectional:
                output += f"{source_label} ⟷ {target_label}\n"
                output += f"  edge_id: {edge_id}\n"  # Show edge_id for execute_edge
                # Forward actions
                forward_actions = action_sets[0].get('actions', [])
                output += f"  Forward: {self._format_actions_with_delay(forward_actions)}\n"
                # Backward actions
                backward_actions = action_sets[1].get('actions', [])
                output += f"  Backward: {self._format_actions_with_delay(backward_actions)}\n"
            else:
                output += f"{source_label} → {target_label}\n"
                output += f"  edge_id: {edge_id}\n"  # Show edge_id for execute_edge
                forward_actions = action_sets[0].get('actions', [])
                output += f"  Actions: {self._format_actions_with_delay(forward_actions)}\n"

            output += "\n"
        
        return output
    
    def _format_actions(self, actions: list) -> str:
        """Format action list to compact string"""
        if not actions:
            return "none"
        
        formatted = []
        for action in actions[:3]:  # Limit to first 3 actions
            cmd = action.get('command', 'unknown')
            params = action.get('params', {})
            
            if cmd == 'launch_app':
                formatted.append('launch_app')
            elif cmd == 'tap_coordinates':
                x = params.get('x', 0)
                y = params.get('y', 0)
                formatted.append(f'tap({x},{y})')
            elif cmd == 'click_element':
                element_id = params.get('element_id', 'unknown')
                # Truncate long element names
                if len(element_id) > 20:
                    element_id = element_id[:17] + '...'
                formatted.append(f'click({element_id})')
            elif cmd == 'press_key':
                key = params.get('key', 'unknown')
                formatted.append(key)
            elif cmd == 'type_text':
                text = params.get('text', '')
                if len(text) > 15:
                    text = text[:12] + '...'
                formatted.append(f'type({text})')
            else:
                formatted.append(cmd)
        
        if len(actions) > 3:
            formatted.append(f'+{len(actions)-3}more')
        
        return ' + '.join(formatted)
    
    def _format_actions_with_delay(self, actions: list) -> str:
        """Format action list with delay information for detailed view"""
        if not actions:
            return "none [delay: 0ms]"
        
        formatted = []
        for action in actions:
            cmd = action.get('command', 'unknown')
            params = action.get('params', {})
            
            if cmd == 'launch_app':
                package = params.get('package', '')
                formatted.append(f'launch_app({package})')
            elif cmd == 'tap_coordinates':
                x = params.get('x', 0)
                y = params.get('y', 0)
                formatted.append(f'tap({x},{y})')
            elif cmd == 'click_element':
                element_id = params.get('element_id', 'unknown')
                if len(element_id) > 30:
                    element_id = element_id[:27] + '...'
                formatted.append(f'click({element_id})')
            elif cmd == 'press_key':
                key = params.get('key', 'unknown')
                formatted.append(key)
            elif cmd == 'type_text':
                text = params.get('text', '')
                if len(text) > 20:
                    text = text[:17] + '...'
                formatted.append(f'type({text})')
            else:
                formatted.append(cmd)
        
        # Get delay/wait_time from last action
        delay = 0
        if actions:
            last_action = actions[-1]
            delay = last_action.get('params', {}).get('wait_time', 0)
            if not delay:
                delay = last_action.get('params', {}).get('delay', 0)
        
        action_str = ' + '.join(formatted)
        return f"{action_str} [delay: {delay}ms]"
    
    def _get_verification_summary(self, node: Dict[str, Any]) -> str:
        """Extract verification summary from node"""
        if not node:
            return ""
        
        # Get verifications from ROOT level (single source of truth)
        verifications = node.get('verifications', [])
        if not verifications:
            return ""
        
        # Get first verification only for compact view
        verif = verifications[0]
        method = verif.get('method', '')
        expected = verif.get('expected', True)
        params = verif.get('params', {})
        
        # Format based on method
        if 'Element' in method:
            text = params.get('text', '')
            if len(text) > 15:
                text = text[:12] + '...'
            symbol = '✓' if expected else '✗'
            return f"[{symbol} {text}]"
        
        return ""

    def _parse_edge_label_and_find_edge_id(self, tree_id: str, edge_label: str, team_id: str) -> Optional[str]:
        """
        Parse an edge label in various formats and find the corresponding edge_id.

        Supported formats:
        - "home ⟷ home_movies" (with arrows)
        - "home to home_movies" (natural language)
        - "home_to_home_movies" (underscore)
        - "home-home_movies" (dash)
        - "home -> home_replay" (arrow notation)

        Args:
            tree_id: Navigation tree ID
            edge_label: Edge label in various formats
            team_id: Team ID

        Returns:
            edge_id string if found, None otherwise
        """
        import re

        # Try different parsing strategies
        strategies = [
            # Strategy 1: Strict separators only (arrows, dashes) - for explicit edge labels
            lambda label: re.findall(r'\b(\w+)\b\s*[→⟷\-\_\>]+\s*\b(\w+)\b', label.strip()),
            # Strategy 2: Natural language parsing (handles "to", "from", etc.)
            lambda label: self._extract_nodes_from_separated(label),
        ]

        source_label = None
        target_label = None

        for strategy in strategies:
            try:
                result = strategy(edge_label)
                if result and len(result) >= 1:
                    if isinstance(result[0], tuple) and len(result[0]) == 2:
                        source_label, target_label = result[0]
                    elif isinstance(result, tuple) and len(result) == 2:
                        source_label, target_label = result
                    break
            except:
                continue

        if not source_label or not target_label:
            print(f"[@MCP:parse_edge_label] Could not parse edge label: {edge_label}")
            return None

        print(f"[@MCP:parse_edge_label] Parsed '{edge_label}' -> source: '{source_label}', target: '{target_label}'")

        # Get all edges and nodes for this tree
        tree_result = self.api.get(
            f'/server/navigationTrees/{tree_id}/full',
            params={'team_id': team_id}
        )

        if not tree_result.get('success'):
            print(f"[@MCP:parse_edge_label] Failed to get tree data: {tree_result.get('error')}")
            return None

        edges = tree_result.get('edges', [])
        nodes = tree_result.get('nodes', [])

        # Create mapping from human-readable labels to internal node_ids
        label_to_node_id = {}
        for node in nodes:
            node_id = node.get('node_id') or node.get('id')
            label = node.get('label', node_id)
            label_to_node_id[label.lower()] = node_id  # Case-insensitive lookup

            # Also map the node_id itself (for backward compatibility)
            if node_id:
                label_to_node_id[node_id.lower()] = node_id

        # Convert parsed labels to actual node_ids
        source_node_id_lookup = label_to_node_id.get(source_label.lower())
        target_node_id_lookup = label_to_node_id.get(target_label.lower())

        if not source_node_id_lookup or not target_node_id_lookup:
            print(f"[@MCP:parse_edge_label] Could not map labels to node_ids: '{source_label}' -> {source_node_id_lookup}, '{target_label}' -> {target_node_id_lookup}")
            return None

        print(f"[@MCP:parse_edge_label] Mapped '{source_label}' -> '{source_node_id_lookup}', '{target_label}' -> '{target_node_id_lookup}'")

        # Find edge matching the resolved node_ids
        for edge in edges:
            edge_source_id = edge.get('source_node_id')
            edge_target_id = edge.get('target_node_id')

            # Check if this edge matches (compare resolved node_ids)
            if edge_source_id == source_node_id_lookup and edge_target_id == target_node_id_lookup:
                edge_id = edge.get('edge_id') or edge.get('id')
                print(f"[@MCP:parse_edge_label] Found matching edge: {edge_id}")
                return edge_id

        print(f"[@MCP:parse_edge_label] No edge found for transition: {source_label} -> {target_label}")
        return None

    def _extract_nodes_from_separated(self, edge_label: str) -> tuple[str, str]:
        """Extract source and target node names from edge labels with various separators."""
        import re

        # Clean the label
        label = edge_label.strip()

        # Remove common transition words
        label = re.sub(r'\bto\b', '', label, flags=re.IGNORECASE)
        label = re.sub(r'\bfrom\b', '', label, flags=re.IGNORECASE)

        # Replace separators with common delimiter, but DON'T split on underscores
        # since underscores are part of node names (e.g., home_replay)
        label = re.sub(r'[→⟷\-\>\|\s]+', '|', label)

        # Split and clean
        parts = [p.strip() for p in label.split('|') if p.strip()]

        # Find the two main node names (skip empty parts)
        nodes = [p for p in parts if p and not re.match(r'^[\s\|\-\>→⟷]*$', p)]

        if len(nodes) >= 2:
            return nodes[0], nodes[-1]  # First and last should be the nodes

        return None, None

    def execute_edge(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute actions defined in a specific navigation edge.

        This tool directly executes the device actions stored in an edge, similar to how
        navigate_to_node() automatically executes edge actions during navigation.

        Examples:
        - execute_edge(userinterface_name='netflix', edge_id='edge1', device_id='device1', host_name='host1')
        - execute_edge(userinterface_name='netflix', edge_label='home -> home_replay', device_id='device1', host_name='host1')
        - execute_edge(userinterface_name='netflix', edge_label='home to home_movies', device_id='device1', host_name='host1')

        Args:
            params: {
                'userinterface_name': str (REQUIRED - UI name for auto-resolving tree_id),
                'edge_id': str (OPTIONAL - edge identifier),
                'edge_label': str (OPTIONAL - transition like 'home -> home_replay' or 'home ⟷ home_replay'),
                'device_id': str (REQUIRED - device identifier),
                'host_name': str (REQUIRED - host where device is connected),
                'team_id': str (OPTIONAL)
            }

        Returns:
            MCP-formatted response with execution results
        """
        tree_id = params.get('tree_id')
        userinterface_name = params.get('userinterface_name')
        edge_id = params.get('edge_id')
        edge_label = params.get('edge_label')
        device_id = params.get('device_id')
        host_name = params.get('host_name')
        team_id = params.get('team_id', get_team_id())

        # Auto-resolve tree_id from userinterface_name using api_client helper
        if not tree_id:
            if not userinterface_name:
                return {"content": [{"type": "text", "text": "Error: userinterface_name is required for auto-resolving tree_id"}], "isError": True}

            tree_id, _, _, error = self.api.resolve_userinterface_name(userinterface_name, team_id)
            if error:
                return {"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True}
        if not edge_id and not edge_label:
            return {"content": [{"type": "text", "text": "Error: Either edge_id or edge_label is required"}], "isError": True}
        if edge_id and edge_label:
            return {"content": [{"type": "text", "text": "Error: Provide either edge_id OR edge_label, not both"}], "isError": True}
        if not device_id:
            return {"content": [{"type": "text", "text": "Error: device_id is required"}], "isError": True}
        if not host_name:
            return {"content": [{"type": "text", "text": "Error: host_name is required"}], "isError": True}

        # If edge_label provided, parse it and find the edge_id
        if edge_label:
            edge_id = self._parse_edge_label_and_find_edge_id(tree_id, edge_label, team_id)
            if not edge_id:
                return {"content": [{"type": "text", "text": f"Error: Could not find edge for transition '{edge_label}'"}], "isError": True}

        try:
            # Step 1: Get edge data
            print(f"[@MCP:execute_edge] Getting edge {edge_id} from tree {tree_id}")
            edge_result = self.api.get(
                f'/server/navigationTrees/{tree_id}/edges/{edge_id}',
                params={'team_id': team_id}
            )

            if not edge_result.get('success'):
                error_msg = edge_result.get('error', 'Failed to get edge')
                return {"content": [{"type": "text", "text": f"❌ Failed to get edge: {error_msg}"}], "isError": True}

            edge = edge_result.get('edge', {})
            action_sets = edge.get('action_sets', [])

            if not action_sets or not action_sets[0].get('actions'):
                return {"content": [{"type": "text", "text": "❌ Edge has no actions to execute"}], "isError": True}

            # Step 2: Extract actions from the first action set (forward direction)
            actions = action_sets[0].get('actions', [])
            if not actions:
                return {"content": [{"type": "text", "text": "❌ Edge has no actions in the forward direction"}], "isError": True}

            # Step 3: Execute the actions using device-control skill
            print(f"[@MCP:execute_edge] Executing {len(actions)} actions from edge {edge_id}")

            # Import ActionTools to execute the actions
            from .action_tools import ActionTools
            action_tools = ActionTools(self.api)

            execution_params = {
                'device_id': device_id,
                'host_name': host_name,
                'actions': actions,
                'team_id': team_id
            }

            # Call execute_device_action
            result = action_tools.execute_device_action(execution_params)

            # Add edge context to the result
            if result.get('content') and len(result['content']) > 0:
                original_text = result['content'][0].get('text', '')
                enhanced_text = f"Edge {edge_id} ({edge.get('source_node_id')}→{edge.get('target_node_id')}): {original_text}"
                result['content'][0]['text'] = enhanced_text

            return result

        except Exception as e:
            print(f"[@MCP:execute_edge] Error executing edge: {e}")
            return {"content": [{"type": "text", "text": f"❌ Edge execution failed: {str(e)}"}], "isError": True}

