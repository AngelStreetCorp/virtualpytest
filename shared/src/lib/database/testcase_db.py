"""
TestCase Definition Database Operations

Manages test case definitions (graphs) created in TestCase Builder.
Test cases can be created visually (drag-drop) or via AI (prompt).
Execution results are stored in script_results table (unified tracking).
"""

import json
from typing import Dict, List, Optional, Any
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.database.folder_tag_db import (
    get_or_create_folder,
    get_or_create_tag,
    set_executable_tags,
    get_executable_tags
)

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def validate_testcase_graph(
    graph_json: Dict[str, Any],
    userinterface_name: str,
    team_id: str,
    available_nodes: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Validate testcase graph before saving - checks that all referenced nodes, edges, and actions exist.
    
    This prevents AI-generated or manually created test cases from referencing non-existent resources,
    which would cause runtime failures during execution.
    
    Args:
        graph_json: Test case graph {nodes: [...], edges: [...]}
        userinterface_name: User interface name (e.g., 'sauce-demo')
        team_id: Team ID for database queries
        available_nodes: Pre-fetched nodes to use (skips fetch if provided)
        
    Returns:
        {
            'success': bool,
            'errors': List[str] (if validation fails),
            'warnings': List[str] (non-critical issues)
        }
    """
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    
    errors = []
    warnings = []
    
    try:
        # If nodes provided, use them directly
        if available_nodes is not None:
            print(f"[@testcase_db:validate] Using provided nodes: {available_nodes}")
            valid_node_labels = set(available_nodes)
        else:
            # Fetch fresh from database
            print(f"[@testcase_db:validate] Fetching fresh nodes from database")
            # Get userinterface to find tree_id
            ui_result = get_userinterface_by_name(userinterface_name, team_id)
            if not ui_result:
                return {
                    'success': False,
                    'errors': [f"User interface '{userinterface_name}' not found"]
                }
            
            # Get root tree for the userinterface
            from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface
            root_tree = get_root_tree_for_interface(ui_result['id'], team_id)
            if not root_tree:
                return {
                    'success': False,
                    'errors': [f"No navigation tree found for '{userinterface_name}'"]
                }
            
            tree_id = root_tree['id']
            
            # Get ALL navigation nodes from root + nested subtrees
            from shared.src.lib.database.navigation_trees_db import get_complete_tree_hierarchy
            hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)
            if not hierarchy_result.get('success'):
                errors.append(f"Failed to load navigation tree: {hierarchy_result.get('error')}")
                return {'success': False, 'errors': errors}
            
            # Extract valid node labels from all trees (root + nested)
            valid_node_labels = set()
            for tree_data in hierarchy_result.get('all_trees_data', []):
                for node in tree_data.get('nodes', []):
                    label = node.get('label')
                    if label:
                        valid_node_labels.add(label)
        
        print(f"[@testcase_db:validate] Valid navigation nodes: {valid_node_labels}")
        
        # Validate each node in the graph
        graph_nodes = graph_json.get('nodes', [])
        for idx, graph_node in enumerate(graph_nodes):
            node_id = graph_node.get('id', f'node_{idx}')
            node_type = graph_node.get('type', 'unknown')
            node_data = graph_node.get('data', {})
            
            # Check navigation blocks
            if node_type == 'navigation':
                target_label = node_data.get('target_node_label')
                target_id = node_data.get('target_node_id')
                
                # Validation: Must have at least one target
                if not target_label and not target_id:
                    errors.append(
                        f"Navigation block '{node_id}' missing both target_node_label and target_node_id"
                    )
                    continue
                
                # Validate target_node_label if provided
                if target_label:
                    if target_label not in valid_node_labels:
                        errors.append(
                            f"Navigation block '{node_id}' references non-existent node '{target_label}'. "
                            f"Valid nodes: {sorted(valid_node_labels)}"
                        )
                
                # Validate target_node_id if provided (should match label)
                if target_id and target_id not in valid_node_labels:
                    # target_node_id should also be a label in new architecture
                    warnings.append(
                        f"Navigation block '{node_id}' uses target_node_id='{target_id}' "
                        f"which doesn't match any known label. Consider using target_node_label instead."
                    )
            
            # Check action blocks (future enhancement - would need device context)
            elif node_type == 'action':
                # For now, just warn if action looks suspicious
                action_command = node_data.get('command')
                if not action_command:
                    warnings.append(
                        f"Action block '{node_id}' has no command specified"
                    )
            
            # Check verification blocks (future enhancement)
            elif node_type == 'verification':
                verification_command = node_data.get('command')
                if not verification_command:
                    warnings.append(
                        f"Verification block '{node_id}' has no command specified"
                    )

        # 🔒 FLOW CONTROL VALIDATION: Prevent invalid edge connections
        graph_edges = graph_json.get('edges', [])

        # Track connections by source handle to detect flow control issues
        handle_targets: Dict[str, List[str]] = {}  # "source_id:handle" -> [target_ids]

        for edge in graph_edges:
            source_id = edge.get('source')
            target_id = edge.get('target')
            source_handle = edge.get('sourceHandle', 'success')  # Default to success

            if not source_id or not target_id:
                continue

            handle_key = f"{source_id}:{source_handle}"
            if handle_key not in handle_targets:
                handle_targets[handle_key] = []
            handle_targets[handle_key].append(target_id)

        # Check flow control rules
        for handle_key, targets in handle_targets.items():
            source_id, handle_type = handle_key.split(':', 1)
            unique_targets = set(targets)

            if len(unique_targets) > 1:
                # INVALID: Same handle going to multiple different targets
                errors.append(
                    f"INVALID FLOW: '{source_id}' handle '{handle_type}' connects to multiple targets: {sorted(unique_targets)}. "
                    f"Each handle can only connect to one target."
                )

        # Check for conflicting paths (success and failure to same target)
        source_handle_map: Dict[str, Dict[str, str]] = {}  # source_id -> {target_id: handle}

        for edge in graph_edges:
            source_id = edge.get('source')
            target_id = edge.get('target')
            source_handle = edge.get('sourceHandle', 'success')

            if source_id not in source_handle_map:
                source_handle_map[source_id] = {}

            if target_id in source_handle_map[source_id]:
                existing_handle = source_handle_map[source_id][target_id]
                if existing_handle != source_handle:
                    # INVALID: Different handles from same source going to same target
                    errors.append(
                        f"INVALID FLOW: '{source_id}' has both '{existing_handle}' and '{source_handle}' handles "
                        f"connecting to same target '{target_id}'. This creates uncontrollable execution flow."
                    )

            source_handle_map[source_id][target_id] = source_handle

        # Return validation result
        if errors:
            print(f"[@testcase_db:validate] ❌ Validation FAILED: {len(errors)} error(s)")
            for error in errors:
                print(f"[@testcase_db:validate]   - {error}")
            return {
                'success': False,
                'errors': errors,
                'warnings': warnings
            }
        
        if warnings:
            print(f"[@testcase_db:validate] ⚠️  Validation passed with {len(warnings)} warning(s)")
            for warning in warnings:
                print(f"[@testcase_db:validate]   - {warning}")
        else:
            print(f"[@testcase_db:validate] ✅ Validation passed - all references valid")
        
        return {
            'success': True,
            'warnings': warnings
        }
        
    except Exception as e:
        print(f"[@testcase_db:validate] Exception during validation: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'errors': [f"Validation failed with exception: {str(e)}"]
        }


def create_testcase(
    team_id: str,
    testcase_name: str,
    graph_json: Dict[str, Any],
    description: str = None,
    userinterface_name: str = None,
    created_by: str = None,
    creation_method: str = 'visual',
    ai_prompt: str = None,
    ai_analysis: str = None,
    overwrite: bool = False,
    auto_increment_if_exists: bool = True,
    environment: str = 'dev',
    folder: str = None,
    tags: List[str] = None,
    available_nodes: Optional[List[str]] = None
) -> Optional[str]:
    """
    Create a new test case definition, or update if it exists and overwrite=True.
    
    Args:
        team_id: Team ID
        testcase_name: Unique name for the test case (used as script_name)
        graph_json: React Flow graph structure {nodes: [...], edges: [...]}
        description: Optional description
        userinterface_name: Navigation tree to use
        created_by: Username who created it
        creation_method: 'visual' (drag-drop) or 'ai' (prompt)
        ai_prompt: Original prompt if AI-generated
        ai_analysis: AI reasoning if AI-generated
        overwrite: If True, update existing test case with same name (DEPRECATED - use auto_increment_if_exists instead)
        auto_increment_if_exists: If True, append _2, _3, etc. if name exists (safer than overwrite)
        environment: Environment ('dev', 'test', 'prod') - defaults to 'dev'
        folder: Folder name (user-selected or typed) - defaults to '(Root)'
        tags: List of tag names (existing or new) - auto-created if not exist
        available_nodes: Pre-fetched nodes to use for validation (skips fetch if provided)
        creation_method: 'visual' (drag-drop) or 'ai' (prompt)
        ai_prompt: Original prompt if AI-generated
        ai_analysis: AI reasoning if AI-generated
        overwrite: If True, update existing test case with same name (DEPRECATED - use auto_increment_if_exists instead)
        auto_increment_if_exists: If True, append _2, _3, etc. if name exists (safer than overwrite)
        environment: Environment ('dev', 'test', 'prod') - defaults to 'dev'
        folder: Folder name (user-selected or typed) - defaults to '(Root)'
        tags: List of tag names (existing or new) - auto-created if not exist
    
    Returns:
        testcase_id (UUID) or None on failure
    """
    supabase = get_supabase()
    if not supabase:
        print("[@testcase_db] ERROR: Failed to get Supabase client")
        return None
    
    try:
        # 🛡️ VALIDATION: Validate graph before saving (if userinterface_name provided)
        if userinterface_name and graph_json:
            print(f"[@testcase_db] 🛡️ Validating test case graph...")
            validation_result = validate_testcase_graph(
                graph_json, 
                userinterface_name, 
                team_id,
                available_nodes=available_nodes  # NEW: Pass nodes from AI
            )
            
            if not validation_result['success']:
                errors = validation_result.get('errors', [])
                print(f"[@testcase_db] ❌ Validation FAILED - cannot save test case")
                for error in errors:
                    print(f"[@testcase_db]   - {error}")
                # Return special error code so caller knows why it failed
                return 'VALIDATION_FAILED'
            
            warnings = validation_result.get('warnings', [])
            if warnings:
                print(f"[@testcase_db] ⚠️  Validation passed with warnings:")
                for warning in warnings:
                    print(f"[@testcase_db]   - {warning}")
        
        # 🔄 AUTO-INCREMENT: Check for name conflicts and increment if needed
        final_testcase_name = testcase_name
        if not overwrite and auto_increment_if_exists:
            existing = get_testcase_by_name(testcase_name, team_id, environment)
            if existing:
                # Name exists - find next available increment
                counter = 2
                while True:
                    candidate_name = f"{testcase_name}_{counter}"
                    if not get_testcase_by_name(candidate_name, team_id, environment):
                        final_testcase_name = candidate_name
                        print(f"[@testcase_db] ⚠️  '{testcase_name}' exists → auto-renamed to '{final_testcase_name}'")
                        break
                    counter += 1
                    if counter > 100:  # Safety limit
                        print(f"[@testcase_db] ❌ Too many duplicates (>100), aborting")
                        return None
        
        # Check if test case with this name already exists in this environment
        if overwrite:
            existing = get_testcase_by_name(testcase_name, team_id, environment)
            if existing:
                # Update existing test case
                success = update_testcase(
                    testcase_id=existing['testcase_id'],
                    graph_json=graph_json,
                    description=description,
                    userinterface_name=userinterface_name,
                    team_id=team_id
                )
                if success:
                    print(f"[@testcase_db] Updated test case: {testcase_name} (overwrite mode)")
                    return existing['testcase_id']
                else:
                    return None
        
        # Get or create folder
        folder_id = get_or_create_folder(folder) if folder else 0
        
        data = {
            'team_id': team_id,
            'testcase_name': final_testcase_name,  # Use final name (possibly incremented)
            'graph_json': graph_json,
            'description': description,
            'userinterface_name': userinterface_name,
            'created_by': created_by,
            'creation_method': creation_method,
            'ai_prompt': ai_prompt,
            'ai_analysis': ai_analysis,
            'environment': environment,
            'folder_id': folder_id
        }
        
        result = supabase.table('testcase_definitions').insert(data).execute()
        
        if result.data and len(result.data) > 0:
            testcase_id = result.data[0]['testcase_id']
            
            # Set tags if provided
            if tags:
                set_executable_tags('testcase', str(testcase_id), tags)
            
            print(f"[@testcase_db] Created test case: {final_testcase_name} (ID: {testcase_id}, method: {creation_method}, env: {environment}, folder_id: {folder_id}, tags: {len(tags) if tags else 0})")
            
            # Return dict with testcase_id and actual name used (may be auto-incremented)
            return {
                'testcase_id': str(testcase_id),
                'testcase_name': final_testcase_name,
                'success': True
            }
        else:
            print(f"[@testcase_db] ERROR: No data returned after insert")
            return None
        
    except Exception as e:
        error_msg = str(e)
        if 'duplicate key' in error_msg.lower() or 'unique constraint' in error_msg.lower():
            print(f"[@testcase_db] ERROR: Test case name already exists: {testcase_name} in {environment}")
            return 'DUPLICATE_NAME'  # Return special value to indicate duplicate
        else:
            print(f"[@testcase_db] ERROR creating test case: {e}")
        return None


def get_testcase(testcase_id: str, team_id: str = None) -> Optional[Dict[str, Any]]:
    """
    Get test case definition by ID.
    
    Args:
        testcase_id: Test case UUID
        team_id: Optional team ID for security check
    
    Returns:
        Test case dict or None
    """
    supabase = get_supabase()
    if not supabase:
        return None
    
    try:
        query = supabase.table('testcase_definitions').select('*').eq('testcase_id', testcase_id)
        
        if team_id:
            query = query.eq('team_id', team_id)
        
        result = query.execute()
        
        if result.data and len(result.data) > 0:
            testcase = result.data[0]
            # Ensure IDs are strings
            testcase['testcase_id'] = str(testcase['testcase_id'])
            testcase['team_id'] = str(testcase['team_id'])
            # Parse graph_json if it's a string
            if isinstance(testcase.get('graph_json'), str):
                testcase['graph_json'] = json.loads(testcase['graph_json'])
            return testcase
        
        return None
        
    except Exception as e:
        print(f"[@testcase_db] ERROR getting test case: {e}")
        return None


def get_testcase_by_name(testcase_name: str, team_id: str, environment: str = 'dev') -> Optional[Dict[str, Any]]:
    """
    Get test case definition by name and environment.
    
    Args:
        testcase_name: Test case name
        team_id: Team ID
        environment: Environment ('dev', 'test', 'prod') - defaults to 'dev'
    
    Returns:
        Test case dict or None
    """
    supabase = get_supabase()
    if not supabase:
        return None
    
    try:
        result = supabase.table('testcase_definitions')\
            .select('*')\
            .eq('testcase_name', testcase_name)\
            .eq('team_id', team_id)\
            .eq('environment', environment)\
            .execute()
        
        if result.data and len(result.data) > 0:
            testcase = result.data[0]
            testcase['testcase_id'] = str(testcase['testcase_id'])
            testcase['team_id'] = str(testcase['team_id'])
            # Parse graph_json if it's a string
            if isinstance(testcase.get('graph_json'), str):
                testcase['graph_json'] = json.loads(testcase['graph_json'])
            return testcase
        
        return None

    except Exception as e:
        print(f"[@testcase_db] ERROR getting test case by name: {e}")
        return None


def update_testcase(
    testcase_id: str,
    graph_json: Dict[str, Any] = None,
    description: str = None,
    userinterface_name: str = None,
    team_id: str = None,
    folder: str = None,
    tags: List[str] = None,
    testcase_name: str = None
) -> bool:
    """
    Update test case definition.
    
    Args:
        testcase_id: Test case UUID
        graph_json: Updated graph structure
        description: Updated description
        userinterface_name: Updated navigation tree
        team_id: Team ID for security check
        folder: Updated folder name (user-selected or typed)
        tags: Updated list of tag names
        testcase_name: Updated testcase name (for renaming)
    
    Returns:
        True on success, False on failure
    """
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        # 🛡️ VALIDATION: Validate graph before updating (if graph_json and userinterface_name provided)
        if graph_json is not None and userinterface_name:
            print(f"[@testcase_db:update] 🛡️ Validating updated test case graph...")
            validation_result = validate_testcase_graph(graph_json, userinterface_name, team_id)

            if not validation_result['success']:
                errors = validation_result.get('errors', [])
                print(f"[@testcase_db:update] ❌ Validation FAILED - cannot update test case")
                for error in errors:
                    print(f"[@testcase_db:update]   - {error}")
                return False  # Return False to indicate validation failure

            warnings = validation_result.get('warnings', [])
            if warnings:
                print(f"[@testcase_db:update] ⚠️  Validation passed with warnings:")
                for warning in warnings:
                    print(f"[@testcase_db:update]   - {warning}")

        # Build update data
        update_data = {}
        
        if graph_json is not None:
            update_data['graph_json'] = graph_json
        
        if description is not None:
            update_data['description'] = description
        
        if userinterface_name is not None:
            update_data['userinterface_name'] = userinterface_name
        
        if testcase_name is not None:
            update_data['testcase_name'] = testcase_name
        
        if folder is not None:
            folder_id = get_or_create_folder(folder)
            update_data['folder_id'] = folder_id
        
        if not update_data and tags is None:
            print("[@testcase_db] WARNING: No fields to update")
            return True
        
        # Update testcase record if there's data
        if update_data:
            query = supabase.table('testcase_definitions').update(update_data).eq('testcase_id', testcase_id)
            
            if team_id:
                query = query.eq('team_id', team_id)
            
            result = query.execute()
            
            if not result.data or len(result.data) == 0:
                print(f"[@testcase_db] WARNING: No test case updated (ID: {testcase_id})")
                return False
        
        # Update tags if provided
        if tags is not None:
            set_executable_tags('testcase', testcase_id, tags)
        
        name_info = f" -> {testcase_name}" if testcase_name else ""
        print(f"[@testcase_db] Updated test case: {testcase_id}{name_info}")
        return True
        
    except Exception as e:
        error_msg = str(e)
        if testcase_name and ('duplicate key' in error_msg.lower() or 'unique constraint' in error_msg.lower()):
            print(f"[@testcase_db] ERROR: Testcase name already exists: {testcase_name}")
        else:
            print(f"[@testcase_db] ERROR updating test case: {e}")
        return False


def get_next_version_number(testcase_id: str, team_id: str) -> int:
    """
    Get the next version number for a test case.
    Returns 1 for new test cases (no history), or MAX(version_number) + 1 for existing ones.
    
    Args:
        testcase_id: Test case UUID
        team_id: Team ID for security check
    
    Returns:
        Next version number (1 for new, or incremented from history)
    """
    supabase = get_supabase()
    if not supabase:
        return 1
    
    try:
        # Check if this test case exists and has history
        result = supabase.table('testcase_definitions_history')\
            .select('version_number')\
            .eq('testcase_id', testcase_id)\
            .eq('team_id', team_id)\
            .order('version_number', desc=True)\
            .limit(1)\
            .execute()
        
        if result.data and len(result.data) > 0:
            # Has history, return next version
            return result.data[0]['version_number'] + 1
        else:
            # No history, this will be version 1 (trigger will save current as v1)
            return 1
    except Exception as e:
        print(f"[@testcase_db] ERROR getting next version number: {e}")
        return 1


def get_testcase_versions(testcase_id: str, team_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Return testcase definition versions with the live testcase synthesized as the latest version.
    The history table stores previous snapshots via trigger; the current live definition is added
    on top so the UI can show a Grafana-style Latest row.
    """
    supabase = get_supabase()
    if not supabase:
        return []

    live_testcase = get_testcase(testcase_id, team_id)
    if not live_testcase:
        return []

    try:
        history_limit = max(limit - 1, 0)
        history_result = supabase.table('testcase_definitions_history')\
            .select('*')\
            .eq('testcase_id', testcase_id)\
            .eq('team_id', team_id)\
            .order('version_number', desc=True)\
            .limit(history_limit)\
            .execute()

        history_rows = history_result.data or []
        history_max = history_rows[0]['version_number'] if history_rows else 0
        current_version = history_max + 1

        current_row = {
            'testcase_id': testcase_id,
            'team_id': team_id,
            'version_number': current_version,
            'testcase_name': live_testcase.get('testcase_name'),
            'description': live_testcase.get('description'),
            'userinterface_name': live_testcase.get('userinterface_name'),
            'graph_json': live_testcase.get('graph_json'),
            'created_by': live_testcase.get('created_by'),
            'creation_method': live_testcase.get('creation_method'),
            'ai_prompt': live_testcase.get('ai_prompt'),
            'ai_analysis': live_testcase.get('ai_analysis'),
            'snapshot_timestamp': live_testcase.get('updated_at') or live_testcase.get('created_at'),
            'change_description': 'Latest saved version',
            'is_current': True,
            'modification_type': 'current',
        }

        normalized_history = []
        for row in history_rows:
            normalized_row = dict(row)
            normalized_row['is_current'] = False
            normalized_row['modification_type'] = 'update'
            normalized_history.append(normalized_row)

        return [current_row, *normalized_history][:limit]
    except Exception as e:
        print(f"[@testcase_db:get_testcase_versions] ERROR: {e}")
        return []


def restore_testcase_version(testcase_id: str, version_number: int, team_id: str) -> Dict[str, Any]:
    """
    Restore a previous testcase snapshot into the live testcase row.
    The DB trigger stores the pre-restore live version in history, while the restored
    definition becomes the new synthesized latest version.
    """
    supabase = get_supabase()
    if not supabase:
        return {'success': False, 'error': 'Supabase client unavailable'}

    live_testcase = get_testcase(testcase_id, team_id)
    if not live_testcase:
        return {'success': False, 'error': 'Test case not found'}

    try:
        versions = get_testcase_versions(testcase_id, team_id, limit=100)
        current_version = versions[0]['version_number'] if versions else 1
        if version_number == current_version:
            return {'success': False, 'error': 'Selected version is already the latest'}

        history_result = supabase.table('testcase_definitions_history')\
            .select('*')\
            .eq('testcase_id', testcase_id)\
            .eq('team_id', team_id)\
            .eq('version_number', version_number)\
            .limit(1)\
            .execute()

        if not history_result.data:
            return {'success': False, 'error': f'Version {version_number} not found'}

        snapshot = history_result.data[0]
        update_data = {
            'testcase_name': snapshot.get('testcase_name'),
            'description': snapshot.get('description'),
            'userinterface_name': snapshot.get('userinterface_name'),
            'graph_json': snapshot.get('graph_json'),
            'creation_method': snapshot.get('creation_method'),
            'ai_prompt': snapshot.get('ai_prompt'),
            'ai_analysis': snapshot.get('ai_analysis'),
        }

        result = supabase.table('testcase_definitions').update(update_data)\
            .eq('testcase_id', testcase_id)\
            .eq('team_id', team_id)\
            .execute()

        if not result.data:
            return {'success': False, 'error': 'Failed to restore test case'}

        restored_testcase = get_testcase(testcase_id, team_id)
        return {
            'success': True,
            'restored_from_version': version_number,
            'new_version': current_version + 1,
            'testcase': restored_testcase,
        }
    except Exception as e:
        print(f"[@testcase_db:restore_testcase_version] ERROR: {e}")
        return {'success': False, 'error': str(e)}


def delete_testcase(testcase_id: str, team_id: str = None) -> bool:
    """
    Delete test case permanently.
    
    Args:
        testcase_id: Test case UUID
        team_id: Team ID for security check
    
    Returns:
        True on success, False on failure
    """
    supabase = get_supabase()
    if not supabase:
        print(f"[@testcase_db:delete] ERROR: Failed to get Supabase client")
        return False
    
    try:
        # First check if testcase exists
        check_query = supabase.table('testcase_definitions')\
            .select('testcase_id,team_id,testcase_name')\
            .eq('testcase_id', testcase_id)
        
        if team_id:
            check_query = check_query.eq('team_id', team_id)
        
        check_result = check_query.execute()
        
        if not check_result.data or len(check_result.data) == 0:
            print(f"[@testcase_db:delete] WARNING: Test case not found (ID: {testcase_id}, team_id: {team_id})")
            return False
        
        testcase_name = check_result.data[0].get('testcase_name', 'unknown')
        print(f"[@testcase_db:delete] Found testcase to delete: {testcase_name} (ID: {testcase_id})")
        
        # Now delete it
        delete_query = supabase.table('testcase_definitions')\
            .delete()\
            .eq('testcase_id', testcase_id)
        
        if team_id:
            delete_query = delete_query.eq('team_id', team_id)
        
        result = delete_query.execute()
        
        if result.data and len(result.data) > 0:
            print(f"[@testcase_db:delete] ✅ Deleted test case: {testcase_name} (ID: {testcase_id})")
            return True
        else:
            print(f"[@testcase_db:delete] ⚠️ Delete executed but no rows affected (ID: {testcase_id})")
            return False
            
    except Exception as e:
        print(f"[@testcase_db:delete] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def list_testcases(team_id: str, include_inactive: bool = False, environment: str = None, include_graph: bool = False) -> List[Dict[str, Any]]:
    """
    List all test cases for a team.
    
    Args:
        team_id: Team ID
        include_inactive: (Deprecated - kept for backward compatibility)
        environment: Filter by environment ('dev', 'test', 'prod') - None returns all
        include_graph: If True, includes graph_json field (slower, use only when needed)
    
    Returns:
        List of test case dicts
    """
    supabase = get_supabase()
    if not supabase:
        return []
    
    try:
        # OPTIMIZED: Select fields based on need
        # By default, exclude graph_json for performance (can be 100KB+ per testcase)
        # Only include it when explicitly requested via include_graph=True
        if include_graph:
            select_fields = 'testcase_id,team_id,testcase_name,description,userinterface_name,created_at,updated_at,created_by,environment,graph_json'
        else:
            select_fields = 'testcase_id,team_id,testcase_name,description,userinterface_name,created_at,updated_at,created_by,environment'
        
        query = supabase.table('testcase_definitions')\
            .select(select_fields)\
            .eq('team_id', team_id)
        
        # Filter by environment if specified
        if environment:
            query = query.eq('environment', environment)
        
        query = query.order('updated_at', desc=True)
        
        result = query.execute()
        
        if not result.data:
            return []
        
        # OPTIMIZED: Batch fetch version numbers for ALL testcases in a single query
        testcase_ids = [tc['testcase_id'] for tc in result.data]
        version_map = {}
        
        if testcase_ids:
            try:
                # Get MAX version for each testcase_id using PostgreSQL aggregation
                # Note: Supabase Python client doesn't support GROUP BY directly,
                # so we fetch all and aggregate in Python (still better than N queries)
                version_result = supabase.table('testcase_definitions_history')\
                    .select('testcase_id,version_number')\
                    .eq('team_id', team_id)\
                    .in_('testcase_id', testcase_ids)\
                    .order('version_number', desc=True)\
                    .execute()
                
                # Build version map (testcase_id -> max_version)
                for record in version_result.data:
                    tc_id = str(record['testcase_id'])
                    if tc_id not in version_map:
                        version_map[tc_id] = record['version_number']
            except Exception as e:
                print(f"[@testcase_db] Warning: Failed to fetch versions: {e}")
        
        # OPTIMIZED: Batch fetch execution stats for ALL testcases in a single query
        testcase_names = [tc['testcase_name'] for tc in result.data]
        exec_map = {}
        
        if testcase_names:
            try:
                # Fetch all execution records for these testcases
                exec_result = supabase.table('script_results')\
                    .select('script_name,success,started_at')\
                    .eq('script_type', 'testcase')\
                    .eq('team_id', team_id)\
                    .in_('script_name', testcase_names)\
                    .order('started_at', desc=True)\
                    .execute()
                
                # Build execution map (testcase_name -> {count, last_success})
                for record in exec_result.data:
                    name = record['script_name']
                    if name not in exec_map:
                        exec_map[name] = {
                            'count': 0,
                            'last_success': record.get('success')
                        }
                    exec_map[name]['count'] += 1
            except Exception as e:
                print(f"[@testcase_db] Warning: Failed to fetch execution stats: {e}")
        
        # Build final testcase list with all metadata
        testcases = []
        for testcase in result.data:
            testcase['testcase_id'] = str(testcase['testcase_id'])
            testcase['team_id'] = str(testcase['team_id'])
            
            # Add version from batch-fetched map
            testcase['current_version'] = version_map.get(testcase['testcase_id'], 0) + 1
            
            # Add execution stats from batch-fetched map
            exec_info = exec_map.get(testcase['testcase_name'], {})
            testcase['execution_count'] = exec_info.get('count', 0)
            testcase['last_execution_success'] = exec_info.get('last_success')
            
            testcases.append(testcase)
        
        return testcases
        
    except Exception as e:
        print(f"[@testcase_db] ERROR listing test cases: {e}")
        return []


def get_testcase_execution_history(testcase_name: str, team_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get execution history for a test case from script_results table.
    
    Args:
        testcase_name: Test case name
        team_id: Team ID
        limit: Max number of results
    
    Returns:
        List of execution records
    """
    supabase = get_supabase()
    if not supabase:
        return []
    
    try:
        result = supabase.table('script_results')\
            .select('script_result_id,script_name,started_at,completed_at,execution_time_ms,success,error_msg,host_name,device_name,html_report_r2_url,logs_r2_url')\
            .eq('script_type', 'testcase')\
            .eq('script_name', testcase_name)\
            .eq('team_id', team_id)\
            .order('started_at', desc=True)\
            .limit(limit)\
            .execute()
        
        executions = []
        for execution in result.data:
            execution['script_result_id'] = str(execution['script_result_id'])
            executions.append(execution)
        
        return executions
        
    except Exception as e:
        print(f"[@testcase_db] ERROR getting execution history: {e}")
        return []


def migrate_testcase_environment(testcase_id: str, team_id: str, target_environment: str) -> bool:
    """
    Migrate a testcase to a different environment (dev -> test -> prod).
    
    Args:
        testcase_id: Test case UUID
        team_id: Team ID for security
        target_environment: Target environment ('dev', 'test', 'prod')
    
    Returns:
        True on success, False on failure
    """
    if target_environment not in ['dev', 'test', 'prod']:
        print(f"[@testcase_db] ERROR: Invalid environment: {target_environment}")
        return False
    
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        query = supabase.table('testcase_definitions')\
            .update({'environment': target_environment})\
            .eq('testcase_id', testcase_id)
        
        if team_id:
            query = query.eq('team_id', team_id)
        
        result = query.execute()
        
        if result.data and len(result.data) > 0:
            testcase_name = result.data[0].get('testcase_name', testcase_id)
            print(f"[@testcase_db] Migrated test case '{testcase_name}' to environment: {target_environment}")
            return True
        else:
            print(f"[@testcase_db] WARNING: No test case migrated (ID: {testcase_id})")
            return False
        
    except Exception as e:
        print(f"[@testcase_db] ERROR migrating test case: {e}")
        return False
