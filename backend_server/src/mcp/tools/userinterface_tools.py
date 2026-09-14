"""
User Interface Management Tools for MCP

Provides CRUD operations for userinterface models (app structures).
These tools manage the top-level app models like Netflix, YouTube, etc.
"""

import json
from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter, ErrorCategory
from ..utils.mcp_logger import get_mcp_logger


class UserInterfaceTools:
    """User interface model management"""

    def __init__(self, api_client: MCPAPIClient):
        self.api_client = api_client
        self.formatter = MCPFormatter()
        self.logger = get_mcp_logger()
    
    def create_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new userinterface (app model).
        
        Example: create_userinterface(name='netflix_android', device_model='android_tv')
        
        Args:
            params: {
                'name': str (REQUIRED - interface name like netflix_android),
                'device_model': str (REQUIRED - device model like android_tv or web),
                'description': str (OPTIONAL - optional description)
            }
        
        Returns:
            Created userinterface with root tree info
        """
        try:
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
            device_model = params['device_model']
            
            # STEP 1: Validate device_model by fetching valid models from database
            # Uses SAME endpoint as frontend (UserInterface.tsx line 86)
            self.logger.info(f"Fetching valid device models for validation")
            
            models_result = self.api_client.get(
                '/server/devicemodel/getAllModels',
                params={'team_id': team_id}
            )
            
            # Extract model names from response
            if isinstance(models_result, list):
                valid_model_names = [model.get('name') for model in models_result if model.get('name')]
            else:
                valid_model_names = []
            
            if not valid_model_names:
                self.logger.warning("No device models found in database - proceeding without validation")
            elif device_model not in valid_model_names:
                # Validation failed - return helpful error
                return self.formatter.format_error(
                    f"Invalid device_model: '{device_model}'\n\n"
                    f"Valid models for your team:\n"
                    f"  • {chr(10).join('  • '.join(valid_model_names[i:i+3]) for i in range(0, len(valid_model_names), 3))}\n\n"
                    f"💡 Use one of these model names, or create a custom model first.",
                    ErrorCategory.VALIDATION
                )
            else:
                self.logger.info(f"✅ Device model '{device_model}' validated successfully")
            
            # STEP 2: Build payload following backend API
            interface_data = {
                'name': params['name'],
                'models': [device_model],
                'description': params.get('description', f"UI model for {params['name']}"),
                'team_id': team_id
            }
            
            self.logger.info(f"Creating userinterface: {interface_data['name']}")
            
            # STEP 3: Call backend - EXISTING ENDPOINT
            result = self.api_client.post(
                '/server/userinterface/createUserInterface',
                data=interface_data,
                params={'team_id': team_id}
            )
            
            # Handle different response formats from backend
            if result.get('status') == 'success' and result.get('userinterface'):
                interface = result['userinterface']
            elif result.get('success') or result.get('id'):
                interface = result if result.get('id') else result.get('interface', {})
            else:
                error_msg = result.get('error', 'Unknown error')
                return self.formatter.format_error(
                    f"Failed to create userinterface: {error_msg}",
                    ErrorCategory.BACKEND
                )
            
            self.logger.info(f"Userinterface created, now creating navigation tree...")
            
            # STEP 4: Create empty navigation config (SAME AS FRONTEND - line 381-434)
            # This creates the navigation tree with entry and home nodes automatically
            # NOTE: team_id MUST be in query params, not body (see line 107 in server_navigation_routes.py)
            try:
                config_result = self.api_client.post(
                    f'/server/navigation/config/createEmpty/{interface.get("name")}',
                    data={
                        'userinterface_data': {
                            'id': interface.get('id'),
                            'name': interface.get('name'),
                            'models': interface.get('models', [device_model]),
                            'min_version': interface.get('min_version', ''),
                            'max_version': interface.get('max_version', '')
                        },
                        'commit_message': f"Create empty navigation config: {interface.get('name')}"
                    },
                    params={'team_id': team_id}  # ✅ Query param, not body
                )
                
                if config_result.get('success'):
                    self.logger.info(f"✅ Navigation tree created with entry/home nodes")
                else:
                    self.logger.warning(f"⚠️  Navigation config creation failed: {config_result.get('error')}")
                    return self.formatter.format_error(
                        f"Userinterface created, but navigation tree creation failed: {config_result.get('error', 'Unknown error')}\n"
                        f"You can still use the navigation editor to create it manually.",
                        ErrorCategory.BACKEND
                    )
            except Exception as config_error:
                self.logger.error(f"Error creating navigation config: {config_error}")
                return self.formatter.format_error(
                    f"Userinterface created, but navigation tree creation failed: {str(config_error)}\n"
                    f"You can still use the navigation editor to create it manually.",
                    ErrorCategory.BACKEND
                )
            
            return self.formatter.format_success(
                f"✅ Userinterface created: {interface.get('name')}\n"
                f"   ID: {interface.get('id')}\n"
                f"   Device Model: {device_model}\n"
                f"   ✅ Navigation tree created with entry/home nodes\n"
                f"\n💡 Use get_userinterface_complete(userinterface_id='{interface.get('id')}') to get full tree data"
            )
        
        except Exception as e:
            self.logger.error(f"Error creating userinterface: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def list_userinterfaces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all userinterfaces.
        
        Example: list_userinterfaces()
        
        Args:
            params: {}
        
        Returns:
            MCP-formatted response with list of interfaces
        """
        try:
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
            
            result = self.api_client.get(
                '/server/userinterface/getAllUserInterfaces',
                params={'team_id': team_id}
            )
            
            interfaces = result if isinstance(result, list) else result.get('interfaces', [])
            
            if not interfaces:
                return {"content": [{"type": "text", "text": "No userinterfaces found"}], "isError": False}
            
            # Text output with IDs for AI to use
            lines = [f"{len(interfaces)} interfaces:"]
            for ui in interfaces:
                lines.append(f"- {ui.get('name')} (id:{ui.get('id')}) [{', '.join(ui.get('models', []))}]")
            
            return {
                "content": [{"type": "text", "text": "\n".join(lines)}],
                "isError": False,
                "interfaces": [{"name": ui.get('name'), "id": ui.get('id')} for ui in interfaces]
            }
        
        except Exception as e:
            self.logger.error(f"Error listing userinterfaces: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def get_userinterface_complete(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get complete userinterface with ALL nodes, edges, subtrees, and metrics. Accepts EITHER userinterface_id OR userinterface_name.
        
        Example: get_userinterface_complete(userinterface_name='google_tv')
        
        Args:
            params: {
                'userinterface_id': str (OPTIONAL - UUID if not using name),
                'userinterface_name': str (OPTIONAL - name if not using ID),
                'include_metrics': bool (OPTIONAL - include metrics data default true)
            }
        
        Returns:
            Complete tree structure with nodes, edges, subtrees, metrics
        """
        try:
            userinterface_id = params.get('userinterface_id')
            userinterface_name = params.get('userinterface_name')
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
            include_metrics = params.get('include_metrics', True)
            
            # Validate: at least one required
            if not userinterface_id and not userinterface_name:
                return self.formatter.format_error(
                    "Error: Either userinterface_id or userinterface_name is required",
                    ErrorCategory.VALIDATION
                )
            
            # If name provided, convert to ID using api_client helper
            if userinterface_name and not userinterface_id:
                _, userinterface_id, _, error = self.api_client.resolve_userinterface_name(userinterface_name, team_id)
                if error and "No navigation tree" not in error:
                    # Only fail if userinterface itself not found (ignore tree not found for this case)
                    return self.formatter.format_error(error, ErrorCategory.NOT_FOUND)
                # If we got userinterface_id but no tree, that's OK for get_userinterface_complete
                if not userinterface_id:
                    return self.formatter.format_error(f"User interface '{userinterface_name}' not found", ErrorCategory.NOT_FOUND)
            
            self.logger.info(f"Getting complete tree for userinterface {userinterface_id}")
            
            # Call backend - EXISTING ENDPOINT with include_nested=true
            result = self.api_client.get(
                f'/server/navigationTrees/getTreeByUserInterfaceId/{userinterface_id}',
                params={
                    'team_id': team_id,
                    'include_nested': 'true',  # Get ALL subtrees
                    'include_metrics': 'true' if include_metrics else 'false'
                }
            )
            
            if not result.get('success'):
                return self.formatter.format_error(
                    f"Failed to get userinterface: {result.get('error', 'Unknown error')}",
                    ErrorCategory.BACKEND
                )
            
            tree = result.get('tree', {})
            metadata = tree.get('metadata', {})
            nodes = metadata.get('nodes', [])
            edges = metadata.get('edges', [])
            
            # Minimal nodes: only essential fields
            # Exclude "Entry" node - it's internal-only, use navigate_to_home instead
            minimal_nodes = []
            for n in nodes:
                if n.get('label') == 'Entry':
                    continue  # Skip Entry node - not navigable directly
                minimal_nodes.append({
                    'node_id': n.get('node_id'),
                    'label': n.get('label'),
                    'type': n.get('node_type'),
                    'verifications': n.get('verifications', [])
                })
            
            # Minimal edges: only essential fields
            minimal_edges = []
            for e in edges:
                minimal_edges.append({
                    'edge_id': e.get('edge_id'),
                    'source': e.get('source_node_id'),
                    'target': e.get('target_node_id'),
                    'action_sets': e.get('action_sets', [])
                })
            
            response_text = f"tree_id:{tree.get('id')} nodes:{len(nodes)} edges:{len(edges)}"
            
            payload = {
                "userinterface_name": userinterface_name,
                "userinterface_id": userinterface_id,
                "tree_id": tree.get('id'),
                "nodes": minimal_nodes,
                "edges": minimal_edges,
            }
            
            return {
                "content": [
                    {"type": "text", "text": response_text},
                    {"type": "text", "text": json.dumps(payload)}
                ],
                "isError": False,
                "tree_id": tree.get('id'),
                "nodes": minimal_nodes,
                "edges": minimal_edges
            }
        
        except Exception as e:
            self.logger.error(f"Error getting complete userinterface: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def list_nodes(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all nodes in a navigation tree.
        
        Example: list_nodes(tree_id='abc123')
        
        Args:
            params: {
                'tree_id': str (REQUIRED - navigation tree ID),
                'page': int (OPTIONAL - page number default 0),
                'limit': int (OPTIONAL - results per page default 100)
            }
        
        Returns:
            List of nodes with details
        """
        try:
            tree_id = params['tree_id']
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
            page = params.get('page', 0)
            limit = params.get('limit', 100)
            
            self.logger.info(f"Listing nodes for tree {tree_id}")
            
            # Call backend - EXISTING ENDPOINT
            result = self.api_client.get(
                f'/server/navigationTrees/{tree_id}/nodes',
                params={
                    'team_id': team_id,
                    'page': page,
                    'limit': limit
                }
            )
            
            if not result.get('success'):
                return self.formatter.format_error(
                    f"Failed to list nodes: {result.get('error', 'Unknown error')}",
                    ErrorCategory.BACKEND
                )
            
            nodes = result.get('nodes', [])
            
            # Minimal nodes: only essential fields
            # Exclude "Entry" node - it's internal-only, use navigate_to_home instead
            minimal_nodes = []
            for n in nodes:
                if n.get('label') == 'Entry':
                    continue  # Skip Entry node - not navigable directly
                minimal_nodes.append({
                    'node_id': n.get('node_id'),
                    'label': n.get('label'),
                    'type': n.get('node_type'),
                    'verifications': n.get('verifications', [])
                })
            
            node_ids = [n.get('node_id', '?') for n in minimal_nodes]
            response_text = f"{len(nodes)} nodes: {' '.join(node_ids)}"
            
            return {
                "content": [{"type": "text", "text": response_text}],
                "isError": False,
                "nodes": minimal_nodes
            }
        
        except Exception as e:
            self.logger.error(f"Error listing nodes: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def list_edges(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all edges in a navigation tree.

        Example: list_edges(tree_id='abc123')

        Args:
            params: {
                'tree_id': str (REQUIRED - navigation tree ID),
                'node_ids': list (OPTIONAL - filter by node IDs)
            }

        Returns:
            List of edges with action sets
        """
        try:
            tree_id = params['tree_id']
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
            node_ids = params.get('node_ids')

            self.logger.info(f"Listing edges for tree {tree_id}")

            # Get complete tree data (same source as preview_userinterface)
            result = self.api_client.get(
                f'/server/navigationTrees/{tree_id}/full',
                params={'team_id': team_id}
            )

            if not result.get('success'):
                return self.formatter.format_error(
                    f"Failed to get tree data: {result.get('error', 'Unknown error')}",
                    ErrorCategory.BACKEND
                )

            edges = result.get('edges', [])

            # Filter by node_ids if provided
            if node_ids:
                filtered_edges = []
                for edge in edges:
                    source_id = edge.get('source_node_id')
                    target_id = edge.get('target_node_id')
                    if source_id in node_ids or target_id in node_ids:
                        filtered_edges.append(edge)
                edges = filtered_edges

            # Minimal edges: only essential fields
            minimal_edges = []
            for e in edges:
                minimal_edges.append({
                    'edge_id': e.get('edge_id'),
                    'source': e.get('source_node_id'),
                    'target': e.get('target_node_id'),
                    'action_sets': e.get('action_sets', [])
                })
            
            edge_list = [f"{e.get('source_node_id')}→{e.get('target_node_id')}" for e in edges]
            response_text = f"{len(edges)} edges: {' '.join(edge_list)}"
            
            return {
                "content": [{"type": "text", "text": response_text}],
                "isError": False,
                "edges": minimal_edges
            }
        
        except Exception as e:
            self.logger.error(f"Error listing edges: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)
    
    def delete_userinterface(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete a userinterface (soft delete). DESTRUCTIVE OPERATION - requires explicit confirmation.
        
        Example: delete_userinterface(userinterface_id='abc123', confirm=true)
        
        Args:
            params: {
                'userinterface_id': str (REQUIRED - UUID to delete),
                'confirm': bool (REQUIRED - must be true to proceed as safety check)
            }
        
        Returns:
            Success confirmation
        """
        try:
            userinterface_id = params['userinterface_id']
            confirm = params.get('confirm', False)
            team_id = params.get('team_id', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')
            
            # SAFETY CHECK: Require explicit confirmation
            if not confirm:
                return self.formatter.format_error(
                    f"⚠️  DESTRUCTIVE OPERATION - Confirmation Required\n\n"
                    f"You are about to delete userinterface: {userinterface_id}\n"
                    f"This will remove the app model and may affect related navigation trees.\n\n"
                    f"To proceed, call again with 'confirm: true':\n"
                    f"  delete_userinterface({{\n"
                    f"    'userinterface_id': '{userinterface_id}',\n"
                    f"    'confirm': true\n"
                    f"  }})\n\n"
                    f"💡 Use list_userinterfaces() first to verify you're deleting the correct one.",
                    ErrorCategory.VALIDATION
                )
            
            self.logger.info(f"Deleting userinterface {userinterface_id} (confirmed)")
            
            # Call backend - EXISTING ENDPOINT
            result = self.api_client.delete(
                f'/server/userinterface/deleteUserInterface/{userinterface_id}',
                params={'team_id': team_id}
            )
            
            if result.get('status') == 'success' or result.get('success'):
                return self.formatter.format_success(
                    f"✅ Userinterface deleted: {userinterface_id}\n\n"
                    f"💡 Use list_userinterfaces() to verify deletion"
                )
            else:
                error_msg = result.get('error', 'User interface not found or failed to delete')
                return self.formatter.format_error(
                    f"Failed to delete userinterface: {error_msg}",
                    ErrorCategory.BACKEND
                )
        
        except Exception as e:
            self.logger.error(f"Error deleting userinterface: {e}", exc_info=True)
            return self.formatter.format_error(str(e), ErrorCategory.BACKEND)

