"""
Execution Results Database Operations

This module provides functions for managing execution results in the database.
Execution results track edge actions and node verifications with metrics.
Now aligned with embedded actions/verifications architecture.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()

def get_execution_results(
    team_id: str,
    execution_type: Optional[str] = None,
    tree_id: Optional[str] = None,
    limit: int = 100,
    userinterface_name: Optional[str] = None
) -> Dict:
    """Get execution results with filtering and enriched with tree/node/edge names."""
    try:
        print(f"[@db:execution_results:get_execution_results] Getting execution results:")
        print(f"  - team_id: {team_id}")
        print(f"  - execution_type: {execution_type}")
        print(f"  - tree_id: {tree_id}")
        print(f"  - limit: {limit}")
        
        supabase = get_supabase()
        query = supabase.table('execution_results').select('*').eq('team_id', team_id)
        
        # Add filters
        if execution_type:
            query = query.eq('execution_type', execution_type)
        if tree_id:
            query = query.eq('tree_id', tree_id)
        
        # Execute query with ordering and limit
        result = query.order('executed_at', desc=True).limit(limit).execute()
        
        print(f"[@db:execution_results:get_execution_results] Found {len(result.data)} execution results")
        
        # Enrich results with tree names and node/edge names using BATCH queries to avoid timeouts
        enriched_results = []
        
        # Collect all unique IDs for batch queries
        tree_ids = list(set([execution.get('tree_id') for execution in result.data if execution.get('tree_id')]))
        edge_ids = list(set([execution.get('edge_id') for execution in result.data if execution.get('edge_id')]))
        node_ids = list(set([execution.get('node_id') for execution in result.data if execution.get('node_id')]))
        script_result_ids = list(set([execution.get('script_result_id') for execution in result.data if execution.get('script_result_id')]))
        
        print(f"[@db:execution_results:get_execution_results] Batch fetching: {len(tree_ids)} trees, {len(edge_ids)} edges, {len(node_ids)} nodes, {len(script_result_ids)} script reports")
        
        # Batch fetch all trees, edges, nodes, and script reports
        tree_cache = {}
        edge_cache = {}
        node_cache = {}
        script_cache = {}
        
        # Batch fetch trees
        if tree_ids:
            trees_result = supabase.table('navigation_trees').select('id, name').eq('team_id', team_id).in_('id', tree_ids).execute()
            for tree in trees_result.data:
                tree_cache[tree['id']] = tree
        
        # Batch fetch edges with their node info
        if edge_ids:
            edges_result = supabase.table('navigation_edges').select(
                'edge_id, tree_id, label, source_node_id, target_node_id, action_sets'
            ).in_('edge_id', edge_ids).execute()
            for edge in edges_result.data:
                edge_cache[edge['edge_id']] = edge
                # Also collect source/target node IDs for batch fetching
                if edge.get('source_node_id'):
                    node_ids.append(edge['source_node_id'])
                if edge.get('target_node_id'):
                    node_ids.append(edge['target_node_id'])
        
        # Batch fetch all nodes (including source/target nodes from edges)
        node_ids = list(set(node_ids))  # Remove duplicates
        if node_ids:
            nodes_result = supabase.table('navigation_nodes').select('node_id, tree_id, label').in_('node_id', node_ids).execute()
            for node in nodes_result.data:
                node_cache[node['node_id']] = node
        
        # Batch fetch script reports for report URLs
        if script_result_ids:
            scripts_result = supabase.table('script_results').select('id, html_report_r2_url').in_('id', script_result_ids).execute()
            for script in scripts_result.data:
                script_cache[script['id']] = script
        
        print(f"[@db:execution_results:get_execution_results] Cached: {len(tree_cache)} trees, {len(edge_cache)} edges, {len(node_cache)} nodes, {len(script_cache)} script reports")
        
        # Now process each execution result using cached data (no more database calls)
        for execution in result.data:
            enriched_execution = execution.copy()
            
            # Get tree information from cache
            tree_id = execution.get('tree_id')
            tree_data = tree_cache.get(tree_id)
            if tree_data:
                enriched_execution['tree_name'] = tree_data.get('name', userinterface_name or 'Unknown Tree')
                
                if execution.get('execution_type') == 'action' and execution.get('edge_id'):
                    # For edge actions, prefer the action set's own human label
                    # (always "from → to"), then the edge's source/target node
                    # labels. Only fall back to splitting the action_set_id on
                    # "_to_" — that heuristic mangles node-id-based ids minted by
                    # the conditional-unlink path (e.g. node-..._to_node-..._<ts>).
                    action_set_id = execution.get('action_set_id')
                    edge_data = edge_cache.get(execution.get('edge_id')) or {}

                    action_set_label = None
                    if action_set_id:
                        for action_set in (edge_data.get('action_sets') or []):
                            if action_set.get('id') == action_set_id:
                                action_set_label = action_set.get('label')
                                break

                    source_node = node_cache.get(edge_data.get('source_node_id'))
                    target_node = node_cache.get(edge_data.get('target_node_id'))

                    if action_set_label and '→' in action_set_label:
                        enriched_execution['element_name'] = action_set_label
                    elif source_node and target_node:
                        enriched_execution['element_name'] = (
                            f"{source_node.get('label')} → {target_node.get('label')}"
                        )
                    elif action_set_id and '_to_' in action_set_id:
                        # Legacy fallback: "home_to_live" becomes "home → live"
                        parts = action_set_id.split('_to_')
                        from_part = parts[0].replace('_', ' ')
                        to_part = parts[1].replace('_', ' ')
                        enriched_execution['element_name'] = f"{from_part} → {to_part}"
                    elif action_set_id:
                        # For action_set_id without _to_, just replace underscores
                        enriched_execution['element_name'] = action_set_id.replace('_', ' ')
                    else:
                        # Fallback for old records without action_set_id
                        edge_id = execution.get('edge_id')
                        enriched_execution['element_name'] = f"Edge {edge_id[:8]}"
                    
                elif execution.get('execution_type') == 'verification' and execution.get('node_id'):
                    # Get node information from cache
                    node_id = execution.get('node_id')
                    node_data = node_cache.get(node_id)
                    
                    if node_data:
                        enriched_execution['element_name'] = node_data.get('label', f"Node {node_id[:8]}")
                    else:
                        enriched_execution['element_name'] = f"Node {node_id[:8]}"
            else:
                enriched_execution['tree_name'] = userinterface_name or 'Unknown Tree'
            
            # Add script report URL if available
            script_result_id = execution.get('script_result_id')
            if script_result_id and script_result_id in script_cache:
                enriched_execution['script_report_url'] = script_cache[script_result_id].get('html_report_r2_url')
            
            enriched_results.append(enriched_execution)
        
        return {
            'success': True,
            'execution_results': enriched_results,
            'count': len(enriched_results)
        }
        
    except Exception as e:
        print(f"[@db:execution_results:get_execution_results] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'execution_results': [],
            'count': 0
        }

def record_edge_execution(
    team_id: str,
    tree_id: str,
    edge_id: str,
    host_name: str,
    device_model: str,
    success: bool,
    execution_time_ms: int,
    message: str = "",
    error_details: Optional[Dict] = None,
    script_result_id: Optional[str] = None,
    script_context: str = 'direct',
    action_set_id: Optional[str] = None,
    device_name: Optional[str] = None,
    variant: Optional[str] = None,
    is_test: bool = False,
) -> Optional[str]:
    """Record edge action execution directly to database.

    `variant` is the run scope (lowercase variant name registered in
    userinterface_variants, or None for a base run). The metrics trigger keys
    edge_metrics on (edge_id, tree_id, action_set_id, variant), so this is the
    column that splits per-scope KPIs apart.

    `is_test=True` flags the row as an interactive Editor run (Run / Goto /
    Edge Run from the frontend); the trigger excludes those from
    edge_metrics. Default False is for CLI / pipeline runs.
    """
    try:
        execution_id = str(uuid4())

        execution_data = {
            'id': execution_id,
            'team_id': team_id,
            'tree_id': tree_id,
            'edge_id': edge_id,
            'execution_type': 'action',
            'host_name': host_name,
            'device_model': device_model,
            'device_name': device_name,
            'success': success,
            'execution_time_ms': execution_time_ms,
            'message': message,
            'error_details': error_details,
            'executed_at': datetime.now(timezone.utc).isoformat(),
            'script_result_id': script_result_id,
            'script_context': script_context,
            'action_set_id': action_set_id,
            'variant': variant.lower() if variant else None,
            'is_test': bool(is_test),
        }
        
        print(f"[@db:execution_results:record_edge_execution] {execution_id[:8]} | {action_set_id or 'N/A'} | {host_name}:{device_model} | {'✓' if success else '✗'} {execution_time_ms}ms | {message}")
        
        supabase = get_supabase()
        result = supabase.table('execution_results').insert(execution_data).execute()
        
        if result.data:
            print(f"[@db:execution_results:record_edge_execution] ✓ Recorded: {execution_id[:8]}")
            return execution_id
        else:
            print(f"[@db:execution_results:record_edge_execution] ✗ Failed: No data returned")
            return None
            
    except Exception as e:
        print(f"[@db:execution_results:record_edge_execution] Error: {str(e)}")
        return None

def record_node_execution(
    team_id: str,
    tree_id: str,
    node_id: str,
    host_name: str,
    device_model: str,
    success: bool,
    execution_time_ms: int,
    message: str = "",
    error_details: Optional[Dict] = None,
    script_result_id: Optional[str] = None,
    script_context: str = 'direct',
    device_name: Optional[str] = None,
    variant: Optional[str] = None,
    is_test: bool = False,
) -> Optional[str]:
    """Record node verification execution directly to database.

    `variant` is the run scope (lowercase variant name or None for base).
    `is_test=True` flags the row as an interactive Editor run; trigger
    excludes those from node_metrics. See record_edge_execution.
    """
    try:
        execution_id = str(uuid4())

        execution_data = {
            'id': execution_id,
            'team_id': team_id,
            'tree_id': tree_id,
            'node_id': node_id,
            'execution_type': 'verification',
            'host_name': host_name,
            'device_model': device_model,
            'device_name': device_name,
            'success': success,
            'execution_time_ms': execution_time_ms,
            'message': message,
            'error_details': error_details,
            'executed_at': datetime.now(timezone.utc).isoformat(),
            'script_result_id': script_result_id,
            'script_context': script_context,
            'variant': variant.lower() if variant else None,
            'is_test': bool(is_test),
        }
        
        # Safe string slicing for logging
        execution_id_short = execution_id[:8] if execution_id else 'unknown'
        node_id_short = node_id[:8] if node_id else 'none'
        print(f"[@db:execution_results:record_node_execution] {execution_id_short} | node:{node_id_short} | {host_name}:{device_model} | {'✓' if success else '✗'} {execution_time_ms}ms | {message}")
        
        supabase = get_supabase()
        result = supabase.table('execution_results').insert(execution_data).execute()
        
        if result.data:
            print(f"[@db:execution_results:record_node_execution] ✓ Recorded: {execution_id[:8]}")
            return execution_id
        else:
            print(f"[@db:execution_results:record_node_execution] ✗ Failed: No data returned")
            return None
            
    except Exception as e:
        print(f"[@db:execution_results:record_node_execution] Error: {str(e)}")
        return None

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
    host_name: str,
    execution_id: Optional[str] = None,
    error_message: Optional[str] = None,
    error_details: Optional[Dict] = None,
    device_name: Optional[str] = None,
    device_model: Optional[str] = None
) -> Optional[str]:
    """Record individual action execution to history table."""
    try:
        action_execution_id = execution_id or str(uuid4())
        
        action_data = {
            'id': action_execution_id,
            'team_id': team_id,
            'tree_id': tree_id,
            'edge_id': edge_id,
            'action_command': action_command,
            'action_params': action_params,
            'action_index': action_index,
            'is_retry_action': is_retry_action,

            'success': success,
            'execution_time_ms': execution_time_ms,
            'host_name': host_name,
            'device_name': device_name,
            'device_model': device_model,
            'error_message': error_message,
            'error_details': error_details,
            'executed_at': datetime.now(timezone.utc).isoformat()
        }
        
        print(f"[@db:execution_results:record_action_execution] Recording action execution:")
        print(f"  - action_execution_id: {action_execution_id}")
        print(f"  - edge_id: {edge_id}")
        print(f"  - action_command: {action_command}")
        print(f"  - success: {success}")
        print(f"  - execution_time_ms: {execution_time_ms}")
        
        supabase = get_supabase()
        result = supabase.table('action_execution_history').insert(action_data).execute()
        
        if result.data:
            print(f"[@db:execution_results:record_action_execution] Success: {action_execution_id}")
            return action_execution_id
        else:
            print(f"[@db:execution_results:record_action_execution] Failed")
            return None
            
    except Exception as e:
        print(f"[@db:execution_results:record_action_execution] Error: {str(e)}")
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
    host_name: str,
    execution_id: Optional[str] = None,
    error_message: Optional[str] = None,
    error_details: Optional[Dict] = None,
    confidence_score: Optional[float] = None,
    result_data: Optional[Dict] = None,
    device_name: Optional[str] = None,
    device_model: Optional[str] = None
) -> Optional[str]:
    """Record individual verification execution to history table."""
    try:
        verification_execution_id = execution_id or str(uuid4())
        
        verification_data = {
            'id': verification_execution_id,
            'team_id': team_id,
            'tree_id': tree_id,
            'node_id': node_id,
            'verification_type': verification_type,
            'verification_command': verification_command,
            'verification_params': verification_params,
            'verification_index': verification_index,
            'success': success,
            'execution_time_ms': execution_time_ms,
            'host_name': host_name,
            'device_name': device_name,
            'device_model': device_model,
            'error_message': error_message,
            'error_details': error_details,
            'confidence_score': confidence_score,
            'result_data': result_data,
            'executed_at': datetime.now(timezone.utc).isoformat()
        }
        
        print(f"[@db:execution_results:record_verification_execution] Recording verification execution:")
        print(f"  - verification_execution_id: {verification_execution_id}")
        print(f"  - node_id: {node_id}")
        print(f"  - verification_command: {verification_command}")
        print(f"  - success: {success}")
        print(f"  - execution_time_ms: {execution_time_ms}")
        
        supabase = get_supabase()
        result = supabase.table('verification_execution_history').insert(verification_data).execute()
        
        if result.data:
            print(f"[@db:execution_results:record_verification_execution] Success: {verification_execution_id}")
            return verification_execution_id
        else:
            print(f"[@db:execution_results:record_verification_execution] Failed")
            return None
            
    except Exception as e:
        print(f"[@db:execution_results:record_verification_execution] Error: {str(e)}")
        return None

def get_tree_metrics(team_id: str, node_ids: List[str], edge_ids: List[str]) -> Dict:
    """Get all metrics for a tree in a single bulk query with defaults for missing metrics."""
    try:
        supabase = get_supabase()
        
        # Get all node metrics in one query using new aggregated structure
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
        
        # Get all edge metrics in one query using new aggregated structure
        edge_metrics = {}
        if edge_ids:
            edge_result = supabase.table('edge_metrics').select(
                'edge_id, total_executions, success_rate, avg_execution_time_ms'
            ).eq('team_id', team_id).in_('edge_id', edge_ids).execute()
            
            for metric in edge_result.data:
                edge_metrics[metric['edge_id']] = {
                    'volume': metric['total_executions'],
                    'success_rate': float(metric['success_rate']),
                    'avg_execution_time': metric['avg_execution_time_ms']
                }
        
        # Fill in defaults for missing metrics
        default_metrics = {'volume': 0, 'success_rate': 0.0, 'avg_execution_time': 0}
        
        for node_id in node_ids:
            if node_id not in node_metrics:
                node_metrics[node_id] = default_metrics
        
        for edge_id in edge_ids:
            if edge_id not in edge_metrics:
                edge_metrics[edge_id] = default_metrics
        
        return {
            'nodes': node_metrics,
            'edges': edge_metrics
        }
        
    except Exception as e:
        print(f"[@db:execution_results:get_tree_metrics] Error: {str(e)}")
        # Return defaults for all requested IDs on error
        default_metrics = {'volume': 0, 'success_rate': 0.0, 'avg_execution_time': 0}
        return {
            'nodes': {node_id: default_metrics for node_id in node_ids},
            'edges': {edge_id: default_metrics for edge_id in edge_ids}
        }

def get_raw_tree_metrics(team_id: str, tree_id: str, node_ids: List[str], edge_ids: List[str]) -> Dict:
    """Get complete raw metrics for a tree matching the frontend API interface."""
    try:
        supabase = get_supabase()
        
        # Get all node metrics with full data including timestamps
        node_metrics = []
        if node_ids:
            node_result = supabase.table('node_metrics').select(
                'node_id, tree_id, team_id, total_executions, successful_executions, success_rate, avg_execution_time_ms, created_at'
            ).eq('team_id', team_id).eq('tree_id', tree_id).in_('node_id', node_ids).execute()
            
            node_metrics = node_result.data or []
            # Add updated_at as created_at since the table doesn't have updated_at yet
            for metric in node_metrics:
                metric['updated_at'] = metric['created_at']
        
        # Get all edge metrics with full data including timestamps
        edge_metrics = []
        if edge_ids:
            edge_result = supabase.table('edge_metrics').select(
                'edge_id, tree_id, team_id, total_executions, successful_executions, success_rate, avg_execution_time_ms, created_at'
            ).eq('team_id', team_id).eq('tree_id', tree_id).in_('edge_id', edge_ids).execute()
            
            edge_metrics = edge_result.data or []
            # Add updated_at as created_at since the table doesn't have updated_at yet
            for metric in edge_metrics:
                metric['updated_at'] = metric['created_at']
        
        return {
            'success': True,
            'node_metrics': node_metrics,
            'edge_metrics': edge_metrics
        }
        
    except Exception as e:
        print(f"[@db:execution_results:get_raw_tree_metrics] Error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'node_metrics': [],
            'edge_metrics': []
        }

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
        print(f"[@db:execution_results:get_action_execution_history] Error: {str(e)}")
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
        print(f"[@db:execution_results:get_verification_execution_history] Error: {str(e)}")
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
    """Update node metrics by analyzing embedded verifications count and types."""
    try:
        verification_types = []
        for verification in verifications:
            v_type = verification.get('verification_type') or verification.get('type')
            if v_type and v_type not in verification_types:
                verification_types.append(v_type)
        
        supabase = get_supabase()
        
        # Upsert node metrics with verification metadata
        upsert_data = {
            'node_id': node_id,
            'tree_id': tree_id,
            'team_id': team_id,
            'verification_count': len(verifications),
            'verification_types': verification_types,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        result = supabase.table('node_metrics').upsert(
            upsert_data,
            on_conflict='node_id,tree_id,team_id'
        ).execute()
        
        return bool(result.data)
        
    except Exception as e:
        print(f"[@db:execution_results:update_node_metrics_from_embedded_verifications] Error: {str(e)}")
        return False

def update_edge_metrics_from_embedded_actions(
    team_id: str,
    tree_id: str,
    edge_id: str,
    actions: List[Dict],
    retry_actions: List[Dict] = None,

    final_wait_time: int = 0
) -> bool:
    """Update edge metrics by analyzing embedded actions count and types."""
    try:
        retry_actions = retry_actions or []

        
        action_types = []
        for action in actions:
            a_type = action.get('command') or action.get('action_type')
            if a_type and a_type not in action_types:
                action_types.append(a_type)
        
        for retry_action in retry_actions:
            a_type = retry_action.get('command') or retry_action.get('action_type')
            if a_type and a_type not in action_types:
                action_types.append(a_type)
        
        supabase = get_supabase()
        
        # Upsert edge metrics with action metadata
        upsert_data = {
            'edge_id': edge_id,
            'tree_id': tree_id,
            'team_id': team_id,
            'action_count': len(actions),
            'retry_action_count': len(retry_actions),

            'action_types': action_types,
            'final_wait_time': final_wait_time,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        result = supabase.table('edge_metrics').upsert(
            upsert_data,
            on_conflict='edge_id,tree_id,team_id'
        ).execute()
        
        return bool(result.data)
        
    except Exception as e:
        print(f"[@db:execution_results:update_edge_metrics_from_embedded_actions] Error: {str(e)}")
        return False

def update_execution_result_with_kpi(
    execution_result_id: str,
    team_id: str,
    kpi_measurement_success: bool,
    kpi_measurement_ms: Optional[int] = None,
    kpi_measurement_error: Optional[str] = None,
    kpi_report_url: Optional[str] = None,
    kpi_display_label: Optional[str] = None,
    kpi_measurement_meta: Optional[dict] = None
) -> bool:
    """Update execution_result with KPI measurement results.

    `kpi_measurement_meta` is the confidence block (shared/src/lib/utils/kpi_confidence.py):
    effective fps over the action->match window, frames missed, which storage served the
    frames, and the interval the transition is provably inside. It is stored because the
    frames themselves are gone within minutes — without it a past measurement can never be
    audited, which is what made the numbers arguable.
    """
    try:
        update_data = {
            'kpi_measurement_success': kpi_measurement_success
        }
        
        if kpi_measurement_ms is not None:
            update_data['kpi_measurement_ms'] = kpi_measurement_ms
        if kpi_measurement_error is not None:
            update_data['kpi_measurement_error'] = kpi_measurement_error
        if kpi_report_url is not None:
            update_data['kpi_report_url'] = kpi_report_url
        # Run-level friendly name — the KPI dashboard prefers it over the edge's
        # action_set kpi_name/label, and groups on it so measurements sharing one
        # edge (e.g. the standby modes over the single wake edge) stay separate.
        if kpi_display_label:
            update_data['kpi_display_label'] = kpi_display_label
        if kpi_measurement_meta:
            update_data['kpi_measurement_meta'] = kpi_measurement_meta

        kpi_status = f"✓ {kpi_measurement_ms}ms" if kpi_measurement_success else f"✗ {kpi_measurement_error}"
        report_status = f" | Report: {kpi_report_url}" if kpi_report_url else ""
        print(f"[@db:execution_results:update_kpi] {execution_result_id[:8]} | KPI: {kpi_status}{report_status}")
        
        supabase = get_supabase()
        result = supabase.table('execution_results').update(update_data).eq(
            'id', execution_result_id
        ).eq('team_id', team_id).execute()
        
        if result.data:
            print(f"[@db:execution_results:update_kpi] ✓ Updated: {execution_result_id[:8]}")
            return True
        else:
            print(f"[@db:execution_results:update_kpi] ✗ Failed: No data returned")
            return False
            
    except Exception as e:
        print(f"[@db:execution_results:update_kpi] Error: {str(e)}")
        return False 