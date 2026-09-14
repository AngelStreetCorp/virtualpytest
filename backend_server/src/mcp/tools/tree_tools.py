"""
Tree Management Tools for MCP

Provides CRUD operations for navigation tree nodes, edges, and subtrees.
These are atomic primitives that can be composed for any workflow:
- AI exploration
- Manual tree building
- Tree refactoring
- Quality assurance
"""

from typing import Dict, Any, List
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter, ErrorCategory
from ..utils.verification_validator import VerificationValidator
from backend_server.src.lib.utils.action_validator import ActionValidator


class TreeTools:
    """Navigation tree CRUD operations"""

    def __init__(self, api_client: MCPAPIClient):
        self.api_client = api_client
        self.formatter = MCPFormatter()
        self.logger = get_mcp_logger()
        self.verification_validator = VerificationValidator(api_client)
        self.action_validator = ActionValidator()

    
    def _invalidate_host_cache(self, tree_id: str, team_id: str):
        """Invalidate server AND host-side navigation caches after an MCP tree write.

        The REST endpoints MCP calls internally use ``propagate_to_hosts=False`` and
        rely on the FRONTEND sending a follow-up ``/server/cache/update-node|edge`` to
        patch host graphs in place — a follow-up MCP never sends. Without this call the
        host's unified graph stays stale and ``navigate_to_node`` runs on a graph
        missing the nodes/edges the agent just created (the known stale-per-host-cache
        failure class). Full invalidate-and-rebuild is heavier than the frontend's
        surgical patch but correct for agent sessions, where writes are bursty.
        """
        try:
            # Lazy import: routes module owns the canonical invalidation helper.
            from routes.server_navigation_trees_routes import invalidate_cached_tree
            invalidate_cached_tree(tree_id, team_id, propagate_to_hosts=True)
            self.logger.info(f"Invalidated server+host nav caches for tree {tree_id}")
        except Exception as e:
            # Never fail the write over cache hygiene, but say so loudly — a stale
            # host graph is the likely consequence.
            self.logger.warning(
                f"Host cache invalidation failed for tree {tree_id}: {e} — "
                f"host navigation may run on a stale graph until next rebuild"
            )

    def _normalize_action_params(self, action_sets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize action parameter names to canonical format before saving to DB.
        
        Conversions:
        - click_element: text/selector → element_id
        - hover_element: text/element_id → selector
        - find_element: text/element_id → selector
        - input_text: element_id → selector
        
        This ensures DB only stores canonical parameter names.
        """
        if not action_sets:
            return action_sets
        
        normalized = []
        for action_set in action_sets:
            normalized_set = action_set.copy()
            
            # Normalize actions
            if 'actions' in normalized_set:
                normalized_set['actions'] = self._normalize_action_list(normalized_set['actions'])
            
            # Normalize retry_actions
            if 'retry_actions' in normalized_set:
                normalized_set['retry_actions'] = self._normalize_action_list(normalized_set['retry_actions'])
            
            # Normalize failure_actions
            if 'failure_actions' in normalized_set:
                normalized_set['failure_actions'] = self._normalize_action_list(normalized_set['failure_actions'])
            
            normalized.append(normalized_set)
        
        return normalized
    
    def _normalize_action_list(self, actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize parameter names in an action list"""
        normalized = []
        for action in actions:
            # Deep copy to avoid modifying original
            import copy
            normalized_action = copy.deepcopy(action)
            command = normalized_action.get('command')
            params = normalized_action.get('params', {})
            
            # Normalize based on command
            if command == 'click_element':
                # Standardize to element_id
                if 'text' in params or 'selector' in params:
                    element_id = params.get('element_id') or params.get('selector') or params.get('text')
                    # Remove old keys
                    params.pop('text', None)
                    params.pop('selector', None)
                    params['element_id'] = element_id
            
            elif command in ['hover_element', 'find_element']:
                # Standardize to selector
                if 'text' in params or 'element_id' in params:
                    selector = params.get('selector') or params.get('element_id') or params.get('text')
                    # Remove old keys
                    params.pop('text', None)
                    params.pop('element_id', None)
                    params['selector'] = selector
            
            elif command == 'input_text':
                # Standardize to selector (text param is for input content, not selector)
                if 'element_id' in params:
                    selector = params.get('selector') or params.get('element_id')
                    # Remove old key
                    params.pop('element_id', None)
                    params['selector'] = selector
            
            normalized_action['params'] = params
            normalized.append(normalized_action)
        
        return normalized
    
    def create_node(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a node in navigation tree. Accepts userinterface_name for auto-resolving tree_id.
        IMPORTANT: Add verifications AFTER creation using update_node - they will be validated against device controllers.

        Example: create_node(userinterface_name='example_mobile', node_id='home', label='Home Screen')

        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'node_id': str (OPTIONAL - node identifier auto-generated if omitted),
                'label': str (REQUIRED - node label or name),
                'type': str (OPTIONAL - node type default screen),
                'position': dict (OPTIONAL - x y coordinates),
                'data': dict (OPTIONAL - custom metadata)
            }

        Returns:
            Created node object
        """
        try:
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not params.get('label'):
                return self.formatter.format_error("label is required", ErrorCategory.VALIDATION)

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            # Build node payload - backend expects: label, node_type, data, node_id
            node_data = {
                'label': params['label'],
                'node_id': params['label'],  # node_id is always the label
                'node_type': params.get('type', 'screen'),
                'data': params.get('data', {})
            }
            
            # Add position to data if provided
            if 'position' in params:
                pos = params['position']
                node_data['data']['position'] = pos
                # Also set position_x and position_y for database columns
                node_data['position_x'] = pos.get('x', 0)
                node_data['position_y'] = pos.get('y', 0)
            
            self.logger.info(f"Creating node in tree {tree_id}: {node_data.get('label')}")
            
            # Call backend
            result = self.api_client.post(
                f'/server/navigationTrees/{tree_id}/nodes',
                data=node_data,
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                node = result.get('node', {})
                node_id_str = node.get('node_id') or node_data.get('node_id')
                self._invalidate_host_cache(tree_id, team_id)
                return {"content": [{"type": "text", "text": f"created node:{node_id_str}"}], "isError": False}
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to create node: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error creating node: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def update_node(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing node with full node object (same pattern as frontend).
        Use get_node first to fetch the node, modify it locally, then pass the full modified node here.
        Verifications MUST be validated against available device controllers - saves will FAIL if invalid.

        Example workflow:
            1. node = get_node(userinterface_name='example_mobile', node_id='home')
            2. node['label'] = 'Home Screen New'
            3. node['verifications'].append({'command': 'waitForElementToAppear', 'verification_type': 'adb', 'params': {'search_term': 'Home'}})
            4. update_node(userinterface_name='example_mobile', node=node)

        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'node': dict (REQUIRED - full node object from get_node with modifications)
            }

        Returns:
            Updated node confirmation
        """
        try:
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            node = params.get('node')
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not node:
                return self.formatter.format_error("node is required - use get_node first, modify it, then pass full node here", ErrorCategory.VALIDATION)

            node_id = node.get('node_id')
            if not node_id:
                return self.formatter.format_error("node.node_id is required", ErrorCategory.VALIDATION)

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, userinterface_id, device_model_resolved, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            print(f"[@MCP:tree_tools:update_node] Updating node {node_id} in tree {tree_id}")
            
            # VALIDATE VERIFICATIONS if provided (REQUIRED - no longer optional)
            verifications = node.get('verifications', [])
            if verifications:
                # Use device_model from resolve_userinterface_name if available, otherwise get it
                if 'device_model_resolved' in locals() and device_model_resolved != 'unknown':
                    device_model = device_model_resolved
                else:
                    # Fallback: get device_model if tree_id was provided directly
                    userinterface_result = self.api_client.get(
                        f'/server/navigationTrees/{tree_id}',
                        params={'team_id': team_id}
                    )

                    if not userinterface_result.get('success'):
                        return self.formatter.format_error(
                            f"❌ Cannot validate verifications: Failed to fetch navigation tree.\n"
                            f"Error: {userinterface_result.get('error', 'Unknown error')}\n\n"
                            f"💡 Try: Use a valid userinterface_name or ensure the navigation tree exists.",
                            ErrorCategory.VALIDATION
                        )

                    tree_data = userinterface_result.get('tree', {})
                    userinterface_id = tree_data.get('userinterface_id')

                    if not userinterface_id:
                        return self.formatter.format_error(
                            f"❌ Cannot validate verifications: Navigation tree has no userinterface_id.\n"
                            f"Tree data: {tree_data}\n\n"
                            f"💡 This navigation tree is not properly configured with a device interface.",
                            ErrorCategory.VALIDATION
                        )

                    # Get device model from userinterface using helper
                    device_model, error = self.api_client.get_device_model_from_userinterface(userinterface_id, team_id)
                    if error:
                        return self.formatter.format_error(
                            f"❌ Cannot validate verifications: {error}\n\n"
                            f"💡 The userinterface '{userinterface_id}' may not exist or be accessible.",
                            ErrorCategory.VALIDATION
                        )

                if device_model == 'unknown':
                    return self.formatter.format_error(
                        f"❌ Cannot validate verifications: Userinterface has unknown device_model.\n\n"
                        f"💡 The userinterface is not properly configured with a device type.",
                        ErrorCategory.VALIDATION
                    )

                # Validate verifications
                is_valid, errors, warnings = self.verification_validator.validate_verifications(
                    verifications,
                    device_model
                )

                if not is_valid:
                    # Build error message with helpful info
                    error_msg = "❌ Invalid verification command(s):\n\n"
                    error_msg += "\n".join(errors)
                    error_msg += "\n\n" + self.verification_validator.get_valid_commands_for_display(device_model)

                    return self.formatter.format_error(
                        error_msg,
                        ErrorCategory.VALIDATION
                    )

                # Show warnings if any
                if warnings:
                    self.logger.warning(f"Verification warnings for node {node_id}:")
                    for warning in warnings:
                        self.logger.warning(f"  {warning}")
            
            # Build node data for backend (same format as frontend saveNodeWithStateUpdate)
            # Uses same endpoint as frontend: POST /server/navigationTrees/{treeId}/nodes
            node_data = {
                'node_id': node_id,
                'label': node.get('label'),
                'node_type': node.get('type', 'screen'),
                'position_x': node.get('position_x', 0),
                'position_y': node.get('position_y', 0),
                'verifications': verifications,
                'data': node.get('data', {}),
                'style': node.get('style', {})
            }
            
            # Ensure verifications not duplicated in data
            node_data['data'].pop('verifications', None)
            
            # Call same endpoint as frontend (POST /nodes - upsert behavior)
            result = self.api_client.post(
                f'/server/navigationTrees/{tree_id}/nodes',
                data=node_data,
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                self._invalidate_host_cache(tree_id, team_id)
                return {"content": [{"type": "text", "text": f"updated node:{node_id}"}], "isError": False}
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to update node: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error updating node: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def delete_node(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete a node from navigation tree. Accepts userinterface_name for auto-resolving tree_id.

        Example: delete_node(userinterface_name='example_mobile', node_id='home')

        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'node_id': str (REQUIRED - node identifier to delete)
            }

        Returns:
            Success confirmation
        """
        try:
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            node_id = params['node_id']
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not node_id:
                return self.formatter.format_error("node_id is required", ErrorCategory.VALIDATION)

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            self.logger.info(f"Deleting node {node_id} from tree {tree_id}")
            
            # Call backend
            result = self.api_client.delete(
                f'/server/navigationTrees/{tree_id}/nodes/{node_id}',
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                self._invalidate_host_cache(tree_id, team_id)
                return {"content": [{"type": "text", "text": f"deleted node:{node_id}"}], "isError": False}
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to delete node: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error deleting node: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def create_edge(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create an edge between two nodes. Accepts userinterface_name for auto-resolving tree_id.

        Example: create_edge(userinterface_name='example_mobile', source_node_id='home', target_node_id='settings', source_label='home', target_label='settings', action_sets=[...])

        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'source_node_id': str (REQUIRED - source node ID),
                'target_node_id': str (REQUIRED - target node ID),
                'source_label': str (REQUIRED - source node label),
                'target_label': str (REQUIRED - target node label),
                'action_sets': list (REQUIRED - array of action sets with bidirectional actions)
            }

        Returns:
            Created edge object
        """
        try:
            import uuid
            import re
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            source_label = params['source_label']  # REQUIRED - no fetch
            target_label = params['target_label']  # REQUIRED - no fetch
            
            # ✅ VALIDATION: Ensure source_node_id and target_node_id are node_id strings, not database UUIDs
            source_node_id = params['source_node_id']
            target_node_id = params['target_node_id']
            
            # Check if user provided UUID instead of node_id (UUID format: 8-4-4-4-12 hex digits)
            uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            
            if re.match(uuid_pattern, source_node_id):
                raise ValueError(
                    f"source_node_id must be the node_id string (e.g., 'home'), not database UUID '{source_node_id}'. "
                    f"Use the 'node_id' field from list_navigation_nodes, not the 'id' field."
                )
            
            if re.match(uuid_pattern, target_node_id):
                raise ValueError(
                    f"target_node_id must be the node_id string (e.g., 'tv_guide'), not database UUID '{target_node_id}'. "
                    f"Use the 'node_id' field from list_navigation_nodes, not the 'id' field."
                )
            
            # Build edge payload - backend expects: edge_id, source_node_id, target_node_id, action_sets, default_action_set_id
            action_sets = params.get('action_sets', [])
            
            # ✅ NORMALIZE: Convert parameter names to canonical format before saving
            action_sets = self._normalize_action_params(action_sets)
            
            # ✅ VALIDATION: Validate action commands if action_sets provided
            if action_sets:
                # Get userinterface to determine device_model
                userinterface_result = self.api_client.get(
                    f'/server/navigationTrees/{tree_id}',
                    params={'team_id': team_id}
                )
                
                if userinterface_result.get('success'):
                    tree_data = userinterface_result.get('tree', {})
                    userinterface_id = tree_data.get('userinterface_id')
                    
                    if userinterface_id:
                        ui_result = self.api_client.get(
                            f'/server/userinterfaces/{userinterface_id}',
                            params={'team_id': team_id}
                        )
                        
                        if ui_result.get('success'):
                            device_model = ui_result.get('userinterface', {}).get('device_model', 'unknown')
                            
                            # Validate action commands
                            is_valid, errors, warnings = self.action_validator.validate_action_sets(
                                action_sets,
                                device_model
                            )
                            
                            if not is_valid:
                                # Build error message with helpful info
                                error_msg = "❌ Invalid action command(s):\n\n"
                                error_msg += "\n".join(errors)
                                error_msg += "\n\n" + self.action_validator.get_valid_commands_for_display(device_model)
                                
                                return self.formatter.format_error(
                                    error_msg,
                                    ErrorCategory.VALIDATION
                                )
                            
                            # Show warnings if any
                            if warnings:
                                self.logger.warning(f"Action warnings for edge {source_node_id} → {target_node_id}:")
                                for warning in warnings:
                                    self.logger.warning(f"  {warning}")
            
            # Clean labels for ID format (matches frontend useNavigationEditor.ts line 300-301)
            clean_source = re.sub(r'[^a-z0-9]', '_', source_label.lower())
            clean_target = re.sub(r'[^a-z0-9]', '_', target_label.lower())
            
            # Auto-generate action_set id, label, and empty arrays if missing (matches frontend useNavigationEditor.ts line 310-322)
            for i, action_set in enumerate(action_sets):
                if i == 0:
                    # Forward direction
                    if 'id' not in action_set or not action_set['id']:
                        action_set['id'] = f"{clean_source}_to_{clean_target}"
                    if 'label' not in action_set or not action_set['label']:
                        action_set['label'] = f"{source_label} → {target_label}"
                elif i == 1:
                    # Backward direction
                    if 'id' not in action_set or not action_set['id']:
                        action_set['id'] = f"{clean_target}_to_{clean_source}"
                    if 'label' not in action_set or not action_set['label']:
                        action_set['label'] = f"{target_label} → {source_label}"
                
                # Always ensure retry_actions and failure_actions exist (frontend always includes these)
                if 'retry_actions' not in action_set:
                    action_set['retry_actions'] = []
                if 'failure_actions' not in action_set:
                    action_set['failure_actions'] = []
            
            # Determine default_action_set_id (first action set by default)
            default_action_set_id = action_sets[0]['id'] if action_sets else 'forward'
            
            # Auto-generate top-level edge label (matches frontend useNavigationEditor.ts line 307)
            label = params.get('label') or f"{source_label}→{target_label}"
            
            # Per-direction final_wait_time + threshold ride along inside each
            # action_set entry. Stamp the param onto every action_set if provided
            # so MCP-created edges still carry sensible defaults per direction.
            mcp_final_wait_time = params.get('final_wait_time', 0)
            for _as in action_sets:
                if isinstance(_as, dict) and 'final_wait_time' not in _as:
                    _as['final_wait_time'] = mcp_final_wait_time

            edge_data = {
                'source_node_id': source_node_id,  # ✅ Use validated node_id
                'target_node_id': target_node_id,  # ✅ Use validated node_id
                'action_sets': action_sets,
                'default_action_set_id': default_action_set_id,
                'label': label or '',  # ✅ TOP-LEVEL label field (matches frontend)
                'data': {
                    # ✅ FIXED handles - only menu handles supported
                    'sourceHandle': 'bottom-right-menu-source',  # Fixed: menu handle from bottom-right
                    'targetHandle': 'top-right-menu-target',     # Fixed: menu handle to top-right
                    'priority': params.get('priority', 'p3'),  # Default priority p3
                    'is_conditional': params.get('is_conditional', False),
                    'is_conditional_primary': params.get('is_conditional_primary', False),
                    'enable_sibling_shortcuts': params.get('enable_sibling_shortcuts', False)  # Sibling shortcuts for bottom nav/tab bars
                }
            }
            
            # edge_id is required by database - generate UUID if not provided
            if 'edge_id' in params:
                edge_data['edge_id'] = params['edge_id']
            else:
                # Generate UUID for edge_id field
                edge_data['edge_id'] = str(uuid.uuid4())
            
            self.logger.info(
                f"Creating edge in tree {tree_id}: "
                f"{source_node_id} → {target_node_id}"
            )
            
            # Call backend
            result = self.api_client.post(
                f'/server/navigationTrees/{tree_id}/edges',
                data=edge_data,
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                edge = result.get('edge', {})
                # Return permanent database IDs for both source and target nodes
                permanent_edge_id = edge.get('edge_id') or edge.get('id')
                
                self._invalidate_host_cache(tree_id, team_id)
                return {"content": [{"type": "text", "text": f"created edge:{permanent_edge_id} {edge.get('source_node_id')}→{edge.get('target_node_id')}"}], "isError": False}
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to create edge: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error creating edge: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def update_edge(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing edge with full edge object (same pattern as frontend).
        Use get_edge first to fetch the edge, modify it locally, then pass the full modified edge here.
        Action commands will be validated against available device controllers.

        Example workflow:
            1. result = get_edge(userinterface_name='example_mobile', edge_id='edge1')
            2. edge = result['edge']
            3. edge['action_sets'][0]['actions'].append({'command': 'press_key', 'params': {'key': 'OK'}})
            4. update_edge(userinterface_name='example_mobile', edge=edge)

        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'edge': dict (REQUIRED - full edge object from get_edge with modifications)
            }

        Returns:
            Updated edge confirmation
        """
        try:
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            edge = params.get('edge')
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not edge:
                return self.formatter.format_error("edge is required - use get_edge first, modify it, then pass full edge here", ErrorCategory.VALIDATION)
            
            edge_id = edge.get('edge_id')
            if not edge_id:
                return self.formatter.format_error("edge.edge_id is required", ErrorCategory.VALIDATION)

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            self.logger.info(f"Updating edge {edge_id} in tree {tree_id}")
            
            # VALIDATE ACTION COMMANDS if action_sets provided
            action_sets = edge.get('action_sets', [])
            
            # ✅ NORMALIZE: Convert parameter names to canonical format before saving
            action_sets = self._normalize_action_params(action_sets)
            
            if action_sets:
                # Get userinterface to determine device_model
                userinterface_result = self.api_client.get(
                    f'/server/navigationTrees/{tree_id}',
                    params={'team_id': team_id}
                )
                
                if userinterface_result.get('success'):
                    tree_data = userinterface_result.get('tree', {})
                    userinterface_id = tree_data.get('userinterface_id')
                    
                    if userinterface_id:
                        ui_result = self.api_client.get(
                            f'/server/userinterfaces/{userinterface_id}',
                            params={'team_id': team_id}
                        )
                        
                        if ui_result.get('success'):
                            device_model = ui_result.get('userinterface', {}).get('device_model', 'unknown')
                            
                            # Validate action commands
                            is_valid, errors, warnings = self.action_validator.validate_action_sets(
                                action_sets,
                                device_model
                            )
                            
                            if not is_valid:
                                # Build error message with helpful info
                                error_msg = "❌ Invalid action command(s):\n\n"
                                error_msg += "\n".join(errors)
                                error_msg += "\n\n" + self.action_validator.get_valid_commands_for_display(device_model)
                                
                                return self.formatter.format_error(
                                    error_msg,
                                    ErrorCategory.VALIDATION
                                )
                            
                            # Show warnings if any
                            if warnings:
                                self.logger.warning(f"Action warnings for edge {edge_id}:")
                                for warning in warnings:
                                    self.logger.warning(f"  {warning}")
            
            # Build edge data for backend (same format as frontend saveEdge)
            # Uses same endpoint as frontend: POST /server/navigationTrees/{treeId}/edges
            edge_data = edge.get('data', {})
            normalized_edge = {
                'edge_id': edge_id,
                'source_node_id': edge.get('source_node_id'),
                'target_node_id': edge.get('target_node_id'),
                'label': edge.get('label', ''),
                # final_wait_time + threshold live per-direction inside action_sets.
                'action_sets': action_sets,
                'default_action_set_id': edge.get('default_action_set_id', action_sets[0]['id'] if action_sets else ''),
                'data': {
                    'priority': edge_data.get('priority', 'p3'),
                    'sourceHandle': edge_data.get('sourceHandle', 'bottom-right-menu-source'),
                    'targetHandle': edge_data.get('targetHandle', 'top-right-menu-target'),
                    'is_conditional': edge_data.get('is_conditional', False),
                    'is_conditional_primary': edge_data.get('is_conditional_primary', False),
                    'enable_sibling_shortcuts': edge_data.get('enable_sibling_shortcuts', False)
                }
            }
            
            # Call same endpoint as frontend (POST /edges - upsert behavior)
            result = self.api_client.post(
                f'/server/navigationTrees/{tree_id}/edges',
                data=normalized_edge,
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                result_edge = result.get('edge', {})
                self._invalidate_host_cache(tree_id, team_id)
                return {"content": [{"type": "text", "text": f"updated edge:{result_edge.get('edge_id')}"}], "isError": False}
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to update edge: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error updating edge: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def delete_edge(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete an edge from navigation tree. Accepts userinterface_name for auto-resolving tree_id.

        Example: delete_edge(userinterface_name='example_mobile', edge_id='edge1')

        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'edge_id': str (REQUIRED - edge identifier to delete)
            }

        Returns:
            Success confirmation
        """
        try:
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            edge_id = params['edge_id']
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not edge_id:
                return self.formatter.format_error("edge_id is required", ErrorCategory.VALIDATION)

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            self.logger.info(f"Deleting edge {edge_id} from tree {tree_id}")
            
            # Call backend
            result = self.api_client.delete(
                f'/server/navigationTrees/{tree_id}/edges/{edge_id}',
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                self._invalidate_host_cache(tree_id, team_id)
                return {"content": [{"type": "text", "text": f"deleted edge:{edge_id}"}], "isError": False}
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to delete edge: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error deleting edge: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def create_subtree(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a subtree for a parent node. Accepts userinterface_name for auto-resolving parent_tree_id.

        Example: create_subtree(userinterface_name='example_mobile', parent_node_id='menu', subtree_name='Menu Options')

        Args:
            params: {
                'parent_tree_id': str (OPTIONAL - parent tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving parent_tree_id),
                'parent_node_id': str (REQUIRED - parent node ID to attach subtree),
                'subtree_name': str (REQUIRED - name for the subtree)
            }

        Returns:
            Created subtree with new tree_id
        """
        try:
            parent_tree_id = params.get('parent_tree_id')
            userinterface_name = params.get('userinterface_name')
            parent_node_id = params['parent_node_id']
            subtree_name = params['subtree_name']
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not parent_node_id:
                return self.formatter.format_error("parent_node_id is required", ErrorCategory.VALIDATION)
            if not subtree_name:
                return self.formatter.format_error("subtree_name is required", ErrorCategory.VALIDATION)

            # Resolve parent_tree_id from userinterface_name using api_client helper
            if not parent_tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either parent_tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                # resolve_userinterface_name returns (tree_id, userinterface_id, device_model, error)
                parent_tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            self.logger.info(
                f"Creating subtree '{subtree_name}' for node {parent_node_id} "
                f"in tree {parent_tree_id}"
            )
            
            # Build subtree payload
            subtree_data = {
                'name': subtree_name
            }
            
            # Call backend
            result = self.api_client.post(
                f'/server/navigationTrees/{parent_tree_id}/nodes/{parent_node_id}/subtrees',
                data=subtree_data,
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                subtree = result.get('tree', {})
                subtree_id = subtree.get('id')
                self._invalidate_host_cache(parent_tree_id, team_id)
                return {"content": [{"type": "text", "text": f"created subtree:{subtree_id}"}], "isError": False}
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to create subtree: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error creating subtree: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def get_node(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get a specific node by ID. Returns full node object that can be modified and passed to update_node.
        
        Example workflow:
            1. result = get_node(userinterface_name='example_mobile', node_id='home')
            2. node = result['node']
            3. node['label'] = 'Home Screen New'
            4. update_node(userinterface_name='example_mobile', node=node)
        
        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'node_id': str (REQUIRED - node identifier)
            }
        
        Returns:
            Full node object with all fields ready for modification and update_node
        """
        try:
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            node_id = params.get('node_id')
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not node_id:
                return self.formatter.format_error("node_id is required", ErrorCategory.VALIDATION)

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            result = self.api_client.get(
                f'/server/navigationTrees/{tree_id}/nodes/{node_id}',
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                node = result.get('node', {})
                # Return full node object matching update_node expected format
                return {
                    "content": [{"type": "text", "text": f"node:{node.get('node_id')}"}],
                    "isError": False,
                    "node": {
                        'node_id': node.get('node_id'),
                        'label': node.get('label'),
                        'type': node.get('node_type', 'screen'),
                        'position_x': node.get('position_x', 0),
                        'position_y': node.get('position_y', 0),
                        'data': node.get('data', {}),
                        'style': node.get('style', {}),
                        'verifications': node.get('verifications', [])
                    }
                }
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to get node: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error getting node: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def get_edge(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get a specific edge by ID. Returns full edge object that can be modified and passed to update_edge.
        
        Example workflow:
            1. result = get_edge(userinterface_name='example_mobile', edge_id='edge1')
            2. edge = result['edge']
            3. edge['action_sets'][0]['actions'].append({'command': 'press_key', 'params': {'key': 'OK'}})
            4. update_edge(userinterface_name='example_mobile', edge=edge)
        
        Args:
            params: {
                'tree_id': str (OPTIONAL - navigation tree ID, auto-resolved from userinterface_name),
                'userinterface_name': str (OPTIONAL - UI name for auto-resolving tree_id),
                'edge_id': str (REQUIRED - edge identifier)
            }
        
        Returns:
            Full edge object with all fields ready for modification and update_edge
        """
        try:
            tree_id = params.get('tree_id')
            userinterface_name = params.get('userinterface_name')
            edge_id = params.get('edge_id')
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

            if not edge_id:
                return self.formatter.format_error("edge_id is required", ErrorCategory.VALIDATION)

            # Resolve tree_id from userinterface_name using api_client helper
            if not tree_id:
                if not userinterface_name:
                    return self.formatter.format_error("Either tree_id or userinterface_name is required", ErrorCategory.VALIDATION)
                tree_id, _, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error:
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
            
            result = self.api_client.get(
                f'/server/navigationTrees/{tree_id}/edges/{edge_id}',
                params={'team_id': team_id}
            )
            
            if result.get('success'):
                edge = result.get('edge', {})
                edge_data = edge.get('data', {})
                # Return full edge object matching update_edge expected format
                return {
                    "content": [{"type": "text", "text": f"edge:{edge.get('source_node_id')}→{edge.get('target_node_id')}"}],
                    "isError": False,
                    "edge": {
                        'edge_id': edge.get('edge_id'),
                        'source_node_id': edge.get('source_node_id'),
                        'target_node_id': edge.get('target_node_id'),
                        'label': edge.get('label', ''),
                        # final_wait_time + threshold live per-direction inside action_sets.
                        'action_sets': edge.get('action_sets', []),
                        'default_action_set_id': edge.get('default_action_set_id', ''),
                        'data': {
                            'priority': edge_data.get('priority', 'p3'),
                            'sourceHandle': edge_data.get('sourceHandle', 'bottom-right-menu-source'),
                            'targetHandle': edge_data.get('targetHandle', 'top-right-menu-target'),
                            'is_conditional': edge_data.get('is_conditional', False),
                            'is_conditional_primary': edge_data.get('is_conditional_primary', False),
                            'enable_sibling_shortcuts': edge_data.get('enable_sibling_shortcuts', False)
                        }
                    }
                }
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to get edge: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error getting edge: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def save_node_screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Take screenshot and save it to a specific node. Wraps screenshot capture and node update into single operation.
        
        Example: save_node_screenshot(tree_id='abc', node_id='home', label='Home Screen', host_name='host1', device_id='device1', userinterface_name='google_tv')
        
        Args:
            params: {
                'tree_id': str (REQUIRED - navigation tree ID),
                'node_id': str (REQUIRED - node identifier to attach screenshot),
                'label': str (REQUIRED - node label used as filename),
                'host_name': str (REQUIRED - host where device is connected),
                'device_id': str (REQUIRED - device identifier),
                'userinterface_name': str (REQUIRED - interface name for organizing screenshots)
            }
        
        Returns:
            Success with screenshot URL and node ID
        """
        try:
            import re
            import time
            
            tree_id = params['tree_id']
            node_id = params['node_id']
            label = params['label']
            host_name = params['host_name']
            device_id = params['device_id']
            userinterface_name = params['userinterface_name']
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
            
            self.logger.info(f"Saving screenshot for node {node_id} ({label}) in tree {tree_id}")
            
            # STEP 1: Sanitize filename (same as frontend - useNode.ts line 124)
            # Remove spaces and special characters
            sanitized_filename = re.sub(r'\s+', '_', label)
            sanitized_filename = re.sub(r'[^a-zA-Z0-9_-]', '', sanitized_filename)
            
            # STEP 2: Take and save screenshot (same as frontend - useNode.ts line 126-137)
            screenshot_result = self.api_client.post(
                '/server/av/saveScreenshot',
                data={
                    'host_name': host_name,
                    'device_id': device_id,
                    'filename': sanitized_filename,
                    'userinterface_name': userinterface_name
                }
            )
            
            if not screenshot_result.get('success'):
                error_msg = screenshot_result.get('message', 'Failed to save screenshot')
                return self.formatter.format_error(
                    f"Screenshot capture failed: {error_msg}",
                    ErrorCategory.BACKEND
                )
            
            screenshot_url = screenshot_result.get('screenshot_url')
            if not screenshot_url:
                return self.formatter.format_error(
                    "Screenshot saved but no URL returned",
                    ErrorCategory.BACKEND
                )
            
            # STEP 3: Read current node to get existing data (avoid overwriting other fields)
            node_result = self.api_client.get(
                f'/server/navigationTrees/{tree_id}/nodes/{node_id}',
                params={'team_id': team_id}
            )
            
            if not node_result.get('success'):
                return self.formatter.format_error(
                    f"Screenshot saved but failed to read node for update: {node_result.get('error', 'Unknown error')}\n"
                    f"Screenshot URL: {screenshot_url}\n"
                    f"You may need to manually update the node.",
                    ErrorCategory.BACKEND
                )
            
            # STEP 4: Merge screenshot into existing data and update node
            # Screenshot must be in data object, not top-level (database schema: data jsonb column)
            current_data = node_result.get('node', {}).get('data', {})
            current_data['screenshot'] = screenshot_url
            current_data['screenshot_timestamp'] = int(time.time() * 1000)  # Force cache bust
            
            update_result = self.api_client.put(
                f'/server/navigationTrees/{tree_id}/nodes/{node_id}',
                data={
                    'data': current_data
                },
                params={'team_id': team_id}
            )
            
            if update_result.get('success'):
                self._invalidate_host_cache(tree_id, team_id)
                return {"content": [{"type": "text", "text": f"screenshot saved:{node_id}"}], "isError": False}
            else:
                error_msg = update_result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Screenshot saved but node update failed: {error_msg}\n"
                    f"Screenshot URL: {screenshot_url}\n"
                    f"You may need to manually update the node.",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error saving node screenshot: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

