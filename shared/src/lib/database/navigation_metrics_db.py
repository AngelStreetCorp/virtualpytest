"""
Navigation Metrics Database Functions

This module implements the navigation metrics architecture as specified in:
docs/architecture/navigation_metrics.md

Provides functions for:
- Recording individual action/verification executions
- Querying aggregated metrics from node_metrics and edge_metrics tables
- Getting detailed execution history
- Updating metrics based on embedded data analysis

The metrics are automatically updated via PostgreSQL triggers when executions are recorded.
"""

from typing import List, Dict, Optional
from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def get_tree_metrics(team_id: str, node_ids: List[str], edge_ids: List[str]) -> Dict:
    """
    Get aggregated metrics for trees matching the frontend API interface.
    
    Args:
        team_id: Team identifier
        node_ids: List of node IDs to get metrics for
        edge_ids: List of edge IDs to get metrics for
        
    Returns:
        Dict with format: {nodes: {node_id: metrics}, edges: {edge_id: metrics}}
        Where metrics = {volume: int, success_rate: float, avg_execution_time: int}
    """
    try:
        supabase = get_supabase()
        
        # Get node metrics from aggregated table
        node_metrics = {}
        if node_ids:
            node_result = supabase.table('node_metrics').select(
                'node_id, total_executions, success_rate, avg_execution_time_ms'
            ).eq('team_id', team_id).in_('node_id', node_ids).execute()
            
            for metric in node_result.data:
                node_metrics[metric['node_id']] = {
                    'volume': metric['total_executions'],
                    'success_rate': float(metric['success_rate']),
                    'avg_execution_time': metric['avg_execution_time_ms']
                }
        
        # Get edge metrics from aggregated table - NOW WITH ACTION_SET_ID
        edge_metrics = {}
        if edge_ids:
            edge_result = supabase.table('edge_metrics').select(
                'edge_id, action_set_id, total_executions, success_rate, avg_execution_time_ms'
            ).eq('team_id', team_id).in_('edge_id', edge_ids).execute()
            
            for metric in edge_result.data:
                # Create unique key for edge + action_set combination
                action_set_id = metric.get('action_set_id')
                if action_set_id:
                    # Direction-specific metrics: edge_id + action_set_id
                    metric_key = f"{metric['edge_id']}#{action_set_id}"
                else:
                    # Legacy metrics without action_set_id (should not exist after cleanup)
                    metric_key = metric['edge_id']
                
                edge_metrics[metric_key] = {
                    'volume': metric['total_executions'],
                    'success_rate': float(metric['success_rate']),
                    'avg_execution_time': metric['avg_execution_time_ms'],
                    'action_set_id': action_set_id
                }
        
        # Fill in defaults for missing metrics (nodes/edges without execution history)
        default_metrics = {'volume': 0, 'success_rate': 0.0, 'avg_execution_time': 0}
        
        for node_id in node_ids:
            if node_id not in node_metrics:
                node_metrics[node_id] = default_metrics.copy()
        
        # For edges, we no longer fill defaults since we need action_set_id context
        # The frontend will need to request specific edge+action_set combinations
        
        return {
            'nodes': node_metrics,
            'edges': edge_metrics
        }
        
    except Exception as e:
        print(f"[@db:navigation_metrics:get_tree_metrics] Error: {str(e)}")
        # Return defaults for all requested IDs on error
        default_metrics = {'volume': 0, 'success_rate': 0.0, 'avg_execution_time': 0}
        return {
            'nodes': {node_id: default_metrics.copy() for node_id in node_ids},
            'edges': {}  # Empty edges on error since we need action_set_id context
        }


def get_edge_direction_metrics(team_id: str, edge_id: str, action_set_id: str) -> Dict:
    """
    Get metrics for a specific edge direction (edge_id + action_set_id combination).
    
    Args:
        team_id: Team identifier
        edge_id: Edge identifier
        action_set_id: Action set identifier (direction)
        
    Returns:
        Dict with metrics: {volume: int, success_rate: float, avg_execution_time: int, confidence: float}
    """
    try:
        supabase = get_supabase()
        
        # Get direction-specific metrics
        result = supabase.table('edge_metrics').select(
            'total_executions, success_rate, avg_execution_time_ms'
        ).eq('team_id', team_id).eq('edge_id', edge_id).eq('action_set_id', action_set_id).execute()
        
        if result.data:
            metric = result.data[0]
            return {
                'volume': metric['total_executions'],
                'success_rate': float(metric['success_rate']),
                'avg_execution_time': metric['avg_execution_time_ms'],
                'confidence': float(metric['success_rate'])  # Use success_rate as confidence for now
            }
        else:
            # No metrics found for this direction
            return {
                'volume': 0,
                'success_rate': 0.0,
                'avg_execution_time': 0,
                'confidence': 0.0
            }
            
    except Exception as e:
        print(f"[@db:navigation_metrics:get_edge_direction_metrics] Error: {str(e)}")
        return {
            'volume': 0,
            'success_rate': 0.0,
            'avg_execution_time': 0,
            'confidence': 0.0
        }


def record_action_execution(
    team_id: str,
    tree_id: str,
    edge_id: str,
    action_command: str,
    action_params: Dict,
    action_index: int,
    is_retry_action: bool,
    success: bool,
    execution_time_ms: int,
    device_model: str,
    device_id: str,
    host_name: str,
    device_name: Optional[str] = None,
    execution_id: Optional[str] = None,
    error_message: Optional[str] = None
) -> Optional[str]:
    """
    Record individual action execution with full parameters.
    
    This will automatically trigger the update_edge_metrics_on_action_execution()
    PostgreSQL function to update the aggregated edge_metrics table.
    
    Returns:
        str: The ID of the created record, or None if failed
    """
    try:
        supabase = get_supabase()
        
        record_data = {
            'team_id': team_id,
            'tree_id': tree_id,
            'edge_id': edge_id,
            'action_command': action_command,
            'action_params': action_params,
            'action_index': action_index,
            'is_retry_action': is_retry_action,
            'success': success,
            'execution_time_ms': execution_time_ms,
            'device_model': device_model,
            'device_name': device_name,
            'host_name': host_name
        }
        
        if execution_id:
            record_data['execution_id'] = execution_id
        if error_message:
            record_data['error_message'] = error_message
        
        result = supabase.table('action_execution_history').insert(record_data).execute()
        
        if result.data:
            print(f"[@db:navigation_metrics:record_action_execution] Recorded action execution: {edge_id}")
            return result.data[0]['id']
        
        return None
        
    except Exception as e:
        print(f"[@db:navigation_metrics:record_action_execution] Error: {str(e)}")
        return None


def record_verification_execution(
    team_id: str,
    tree_id: str,
    node_id: str,
    verification_type: str,
    verification_command: str,
    verification_params: Dict,
    verification_index: int,
    success: bool,
    execution_time_ms: int,
    device_model: str,
    host_name: str,
    device_name: Optional[str] = None,
    execution_id: Optional[str] = None,
    confidence_score: Optional[float] = None,
    threshold_used: Optional[float] = None,
    source_image_url: Optional[str] = None,
    reference_image_url: Optional[str] = None,
    extracted_text: Optional[str] = None,
    error_message: Optional[str] = None
) -> Optional[str]:
    """
    Record individual verification execution with results.
    
    This will automatically trigger the update_node_metrics_on_verification_execution()
    PostgreSQL function to update the aggregated node_metrics table.
    
    Returns:
        str: The ID of the created record, or None if failed
    """
    try:
        supabase = get_supabase()
        
        record_data = {
            'team_id': team_id,
            'tree_id': tree_id,
            'node_id': node_id,
            'verification_type': verification_type,
            'verification_command': verification_command,
            'verification_params': verification_params,
            'verification_index': verification_index,
            'success': success,
            'execution_time_ms': execution_time_ms,
            'device_model': device_model,
            'device_name': device_name,
            'host_name': host_name
        }
        
        # Add optional fields
        if execution_id:
            record_data['execution_id'] = execution_id
        if confidence_score is not None:
            record_data['confidence_score'] = confidence_score
        if threshold_used is not None:
            record_data['threshold_used'] = threshold_used
        if source_image_url:
            record_data['source_image_url'] = source_image_url
        if reference_image_url:
            record_data['reference_image_url'] = reference_image_url
        if extracted_text:
            record_data['extracted_text'] = extracted_text
        if error_message:
            record_data['error_message'] = error_message
        
        result = supabase.table('verification_execution_history').insert(record_data).execute()
        
        if result.data:
            print(f"[@db:navigation_metrics:record_verification_execution] Recorded verification execution: {node_id}")
            return result.data[0]['id']
        
        return None
        
    except Exception as e:
        print(f"[@db:navigation_metrics:record_verification_execution] Error: {str(e)}")
        return None


def get_action_execution_history(
    team_id: str,
    edge_id: Optional[str] = None,
    tree_id: Optional[str] = None,
    limit: int = 100
) -> Dict:
    """Get detailed action execution history."""
    try:
        supabase = get_supabase()
        query = supabase.table('action_execution_history').select('*').eq('team_id', team_id)
        
        if edge_id:
            query = query.eq('edge_id', edge_id)
        if tree_id:
            query = query.eq('tree_id', tree_id)
        
        result = query.order('executed_at', desc=True).limit(limit).execute()

        return {
            'success': True,
            'action_executions': result.data,
            'count': len(result.data)
        }

    except Exception as e:
        # PGRST205: 'action_execution_history' was deliberately dropped from the schema
        # (see setup/db/schema/005_monitoring_analytics.sql) but this read path was never
        # updated — treat "table doesn't exist" as "no history" rather than an error
        # (discovered 2026-09-07 backfilling non-regression tests).
        if 'PGRST205' in str(e):
            return {'success': True, 'action_executions': [], 'count': 0}
        print(f"[@db:navigation_metrics:get_action_execution_history] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'action_executions': [],
            'count': 0
        }


def get_verification_execution_history(
    team_id: str,
    node_id: Optional[str] = None,
    tree_id: Optional[str] = None,
    limit: int = 100
) -> Dict:
    """Get detailed verification execution history."""
    try:
        supabase = get_supabase()
        query = supabase.table('verification_execution_history').select('*').eq('team_id', team_id)
        
        if node_id:
            query = query.eq('node_id', node_id)
        if tree_id:
            query = query.eq('tree_id', tree_id)
        
        result = query.order('executed_at', desc=True).limit(limit).execute()
        
        return {
            'success': True,
            'verification_executions': result.data,
            'count': len(result.data)
        }
        
    except Exception as e:
        # See matching PGRST205 handling in get_action_execution_history above.
        if 'PGRST205' in str(e):
            return {'success': True, 'verification_executions': [], 'count': 0}
        print(f"[@db:navigation_metrics:get_verification_execution_history] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'verification_executions': [],
            'count': 0
        }


def update_node_metrics_from_embedded_verifications(
    team_id: str,
    tree_id: str,
    node_id: str,
    verifications: List[Dict]
) -> bool:
    """
    Update node metrics based on embedded verification data analysis.
    
    This function analyzes the embedded verifications in a node and updates
    the node_metrics table with verification count and types information.
    """
    try:
        supabase = get_supabase()
        
        verification_count = len(verifications)
        verification_types = list(set(v.get('type', 'unknown') for v in verifications))
        
        # Upsert node metrics record with embedded data
        upsert_data = {
            'node_id': node_id,
            'tree_id': tree_id,
            'team_id': team_id,
            'verification_count': verification_count,
            'verification_types': verification_types
        }
        
        result = supabase.table('node_metrics').upsert(
            upsert_data,
            on_conflict='node_id,tree_id,team_id'
        ).execute()
        
        print(f"[@db:navigation_metrics:update_node_metrics_from_embedded] Updated node {node_id} with {verification_count} verifications")
        return True
        
    except Exception as e:
        print(f"[@db:navigation_metrics:update_node_metrics_from_embedded] Error: {str(e)}")
        return False


def update_edge_metrics_from_embedded_actions(
    team_id: str,
    tree_id: str,
    edge_id: str,
    actions: List[Dict],
    retry_actions: List[Dict] = None
) -> bool:
    """
    Update edge metrics based on embedded action data analysis.
    
    This function analyzes the embedded actions in an edge and updates
    the edge_metrics table with action count, types, and retry information.
    """
    try:
        supabase = get_supabase()
        
        action_count = len(actions)
        retry_action_count = len(retry_actions) if retry_actions else 0
        action_types = list(set(a.get('command', 'unknown') for a in actions))
        
        # Extract final_wait_time from actions (typically from the last action)
        final_wait_time = 0  # default — match DB column default
        if actions:
            last_action = actions[-1]
            if 'wait_time' in last_action:
                final_wait_time = last_action['wait_time']
        
        # Upsert edge metrics record with embedded data
        upsert_data = {
            'edge_id': edge_id,
            'tree_id': tree_id,
            'team_id': team_id,
            'action_count': action_count,
            'retry_action_count': retry_action_count,
            'action_types': action_types,
            'final_wait_time': final_wait_time
        }
        
        result = supabase.table('edge_metrics').upsert(
            upsert_data,
            on_conflict='edge_id,tree_id,team_id'
        ).execute()
        
        print(f"[@db:navigation_metrics:update_edge_metrics_from_embedded] Updated edge {edge_id} with {action_count} actions, {retry_action_count} retry actions")
        return True
        
    except Exception as e:
        print(f"[@db:navigation_metrics:update_edge_metrics_from_embedded] Error: {str(e)}")
        return False
