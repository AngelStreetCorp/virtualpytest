"""
Navigation Service

Handles all navigation tree business logic that was previously in routes.
This service manages tree metadata, nodes, edges, and complex tree operations.
"""

from typing import Dict, Any, List, Optional
from shared.src.lib.database.navigation_trees_db import (
    # Tree metadata operations
    get_all_trees, get_tree_metadata, save_tree_metadata, delete_tree,
    # Node operations
    get_tree_nodes, get_node_by_id, save_node, delete_node,
    # Edge operations
    get_tree_edges, get_edge_by_id, save_edge, delete_edge,
    # Batch operations
    save_tree_data, get_full_tree,
    # Interface operations
    get_root_tree_for_interface,
    # Nested tree operations
    get_node_sub_trees, create_sub_tree, get_tree_hierarchy, 
    get_tree_breadcrumb, delete_tree_cascade, move_subtree
)
from shared.src.lib.database.userinterface_db import get_all_userinterfaces
from shared.src.lib.utils.app_utils import DEFAULT_USER_ID, check_supabase

class NavigationService:
    """Service for handling navigation tree business logic"""
    
    def get_all_navigation_trees(self, team_id: str, user_agent: str = None, referer: str = None) -> Dict[str, Any]:
        """Get all navigation trees metadata for a team"""
        try:
            # Log caller information (moved from route)
            print(f"[NavigationService:get_all_navigation_trees] 🔍 CALLER INFO:")
            print(f"  - User-Agent: {user_agent or 'Unknown'}")
            print(f"  - Referer: {referer or 'Unknown'}")
            print(f"  - Team ID: {team_id}")
            
            if not team_id:
                return {
                    'success': False,
                    'error': 'team_id is required',
                    'status_code': 400
                }
            
            print(f"[NavigationService] Getting all navigation trees for team: {team_id}")
            
            # Business logic: Get trees from database
            result = get_all_trees(team_id=team_id)
            
            if result.get('success'):
                trees = result.get('trees', [])
                print(f"[NavigationService] Found {len(trees)} trees")
                
                return {
                    'success': True,
                    'trees': trees,
                    'count': len(trees)
                }
            else:
                error_msg = result.get('error', 'Failed to get trees')
                print(f"[NavigationService] Error: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'status_code': 500
                }
                
        except Exception as e:
            print(f"[NavigationService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def get_tree_metadata(self, tree_id: str, team_id: str) -> Dict[str, Any]:
        """Get metadata for a specific tree"""
        try:
            if not tree_id or not team_id:
                return {
                    'success': False,
                    'error': 'tree_id and team_id are required',
                    'status_code': 400
                }
            
            print(f"[NavigationService] Getting tree metadata for tree: {tree_id}")
            
            result = get_tree_metadata(tree_id, team_id)
            
            if result.get('success'):
                return {
                    'success': True,
                    'tree': result.get('tree')
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to get tree metadata'),
                    'status_code': 404 if 'not found' in str(result.get('error', '')).lower() else 500
                }
                
        except Exception as e:
            print(f"[NavigationService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def save_tree_metadata(self, tree_data: Dict[str, Any], team_id: str) -> Dict[str, Any]:
        """Save tree metadata"""
        try:
            if not tree_data or not team_id:
                return {
                    'success': False,
                    'error': 'tree_data and team_id are required',
                    'status_code': 400
                }
            
            # Add team_id to tree data
            tree_data['team_id'] = team_id
            
            print(f"[NavigationService] Saving tree metadata: {tree_data.get('name', 'Unknown')}")
            
            result = save_tree_metadata(tree_data)
            
            if result.get('success'):
                return {
                    'success': True,
                    'tree': result.get('tree'),
                    'message': 'Tree metadata saved successfully'
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to save tree metadata'),
                    'status_code': 500
                }
                
        except Exception as e:
            print(f"[NavigationService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def delete_tree(self, tree_id: str, team_id: str) -> Dict[str, Any]:
        """Delete a tree"""
        try:
            if not tree_id or not team_id:
                return {
                    'success': False,
                    'error': 'tree_id and team_id are required',
                    'status_code': 400
                }
            
            print(f"[NavigationService] Deleting tree: {tree_id}")
            
            result = delete_tree(tree_id, team_id)
            
            if result.get('success'):
                return {
                    'success': True,
                    'message': 'Tree deleted successfully'
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to delete tree'),
                    'status_code': 500
                }
                
        except Exception as e:
            print(f"[NavigationService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def get_tree_nodes(self, tree_id: str, team_id: str) -> Dict[str, Any]:
        """Get all nodes for a tree"""
        try:
            if not tree_id or not team_id:
                return {
                    'success': False,
                    'error': 'tree_id and team_id are required',
                    'status_code': 400
                }
            
            print(f"[NavigationService] Getting nodes for tree: {tree_id}")
            
            result = get_tree_nodes(tree_id, team_id)
            
            if result.get('success'):
                nodes = result.get('nodes', [])
                return {
                    'success': True,
                    'nodes': nodes,
                    'count': len(nodes)
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to get tree nodes'),
                    'status_code': 500
                }
                
        except Exception as e:
            print(f"[NavigationService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def save_node(self, node_data: Dict[str, Any], team_id: str) -> Dict[str, Any]:
        """Save a node"""
        try:
            if not node_data or not team_id:
                return {
                    'success': False,
                    'error': 'node_data and team_id are required',
                    'status_code': 400
                }
            
            # Add team_id to node data
            node_data['team_id'] = team_id
            
            print(f"[NavigationService] Saving node: {node_data.get('name', 'Unknown')}")
            
            result = save_node(node_data)
            
            if result.get('success'):
                return {
                    'success': True,
                    'node': result.get('node'),
                    'message': 'Node saved successfully'
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to save node'),
                    'status_code': 500
                }
                
        except Exception as e:
            print(f"[NavigationService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def get_full_tree(self, tree_id: str, team_id: str) -> Dict[str, Any]:
        """Get complete tree data (nodes + edges)"""
        try:
            if not tree_id or not team_id:
                return {
                    'success': False,
                    'error': 'tree_id and team_id are required',
                    'status_code': 400
                }
            
            print(f"[NavigationService] Getting full tree data for: {tree_id}")
            
            result = get_full_tree(tree_id, team_id)
            
            if result.get('success'):
                return {
                    'success': True,
                    'tree_data': result.get('tree_data'),
                    'nodes': result.get('nodes', []),
                    'edges': result.get('edges', [])
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to get full tree'),
                    'status_code': 500
                }
                
        except Exception as e:
            print(f"[NavigationService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }

# Singleton instance
navigation_service = NavigationService()
