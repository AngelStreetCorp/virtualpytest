"""
Unified Executable Routes - Scripts and Testcases
Provides a unified API for listing and organizing both scripts and testcases
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.response_cache import get_cached_response, set_cached_response, invalidate_cached_responses
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database.testcase_db import list_testcases
from shared.src.lib.config.constants import CACHE_CONFIG
from shared.src.lib.database.folder_tag_db import (
    list_all_folders,
    list_all_tags,
    get_executable_tags_bulk,
)
from shared.src.lib.database.library_visibility_db import list_hidden_library_keys
from shared.src.lib.database.virtual_scripts_db import list_virtual_scripts
from backend_server.src.lib.utils.script_utils import (
    list_available_scripts, extract_script_target_rules, extract_script_description,
    is_discoverable_script_ref,
)

server_executable_bp = Blueprint('server_executable', __name__, url_prefix='/server/executable')


@server_executable_bp.route('/list', methods=['GET'])
@handle_route_exceptions('executable:list_executables')
def list_executables():
    """
    Unified endpoint to list both scripts and testcases organized by folders.
    
    Query params:
        - team_id: Team identifier (automatically added by frontend buildServerUrl)
        - folder: Filter by folder name
        - tags: Comma-separated tag names to filter by
        - search: Search query for name/description
    
    Note: This endpoint does NOT require host_name since it only lists available
    executables, not executing them. Execution requires host_name separately.
    
    Returns:
        {
            "success": true,
            "folders": [
                {
                    "id": 1,
                    "name": "Navigation",
                    "items": [
                        {
                            "type": "script",
                            "id": "goto.py",
                            "name": "Go to channel",
                            "description": "...",
                            "tags": []
                        },
                        {
                            "type": "testcase",
                            "id": "tc_uuid",
                            "name": "Navigate EPG grid",
                            "tags": ["smoke"],
                            "userinterface": "android_tv"
                        }
                    ]
                }
            ],
            "all_tags": [{tag_id, name, color}, ...],
            "all_folders": ["(Root)", "Navigation", ...]
        }
    """
    # Get team_id from query params (automatically added by buildServerUrl)
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    cache_key = ':'.join([
        'server_executable:list',
        team_id,
        request.args.get('include_hidden', 'false').lower(),
        request.args.get('folder', ''),
        request.args.get('tags', ''),
        request.args.get('search', '').lower(),
    ])
    cached_response = get_cached_response(cache_key, CACHE_CONFIG['SHORT_TTL'])
    if cached_response is not None:
        return jsonify(cached_response)
    
    # Get filter parameters
    filter_folder = request.args.get('folder')
    filter_tags = request.args.get('tags', '').split(',') if request.args.get('tags') else []
    search_query = request.args.get('search', '').lower()
    include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'
    
    # Get all folders and tags from database (for test cases)
    all_folders = list_all_folders()
    all_tags = list_all_tags()
    
    # Get scripts from filesystem (includes subfolder paths like "gw/superping")
    available_scripts = list_available_scripts()
    hidden_script_keys = set()
    hidden_testcase_ids = set()
    if not include_hidden:
        hidden_script_keys = list_hidden_library_keys(team_id, 'script')
        hidden_testcase_ids = list_hidden_library_keys(team_id, 'testcase')
    
    # Get testcases from database
    testcases = list_testcases(team_id)

    # Batch-fetch tags for all scripts and testcases in two queries instead of N+1
    script_display_ids = [f"{script}.py" for script in available_scripts]
    script_tags_map = get_executable_tags_bulk('script', script_display_ids)
    testcase_ids = [tc['testcase_id'] for tc in testcases if tc.get('testcase_id')]
    testcase_tags_map = get_executable_tags_bulk('testcase', testcase_ids)

    # Build folder structure
    # Use a dict with folder name as key for easy lookup
    folder_map = {}
    
    # Initialize folders from database (for test cases)
    for folder in all_folders:
        folder_map[folder['name']] = {
            'id': folder['folder_id'],
            'name': folder['name'],
            'items': []
        }
    
    # Process scripts - extract folder from filesystem path
    for script in available_scripts:
        script_display = f"{script}.py"
        if script_display in hidden_script_keys:
            continue

        # Parse folder from script path (e.g., "gw/superping" -> folder="gw", name="superping")
        if '/' in script:
            folder_name, script_name = script.rsplit('/', 1)
            display_name = script_name.replace('_', ' ').title()
        else:
            folder_name = 'Root'
            script_name = script
            display_name = script.replace('_', ' ').title()
        
        # Get tags for this script (from pre-fetched bulk map)
        script_tags = script_tags_map.get(script_display, [])
        tag_names = [tag['name'] for tag in script_tags]
        
        # Apply filters
        if filter_folder and filter_folder != folder_name:
            continue
        
        if filter_tags and not any(tag in tag_names for tag in filter_tags):
            continue
        
        if search_query and search_query not in script_display.lower() and search_query not in display_name.lower():
            continue
        
        # Create script item
        script_item = {
            'type': 'script',
            'id': script_display,
            'name': display_name,
            'description': extract_script_description(script) or f'Execute {script_name}',
            'tags': tag_names,
            'target_rules': extract_script_target_rules(script),
        }
        
        # Ensure folder exists in map
        if folder_name not in folder_map:
            # Create dynamic folder for filesystem folders not in database
            folder_id = hash(folder_name) % 10000  # Simple hash for ID
            folder_map[folder_name] = {
                'id': folder_id,
                'name': folder_name,
                'items': []
            }
        
        folder_map[folder_name]['items'].append(script_item)
    
    # Process testcases - use database folder_id
    for testcase in testcases:
        if testcase.get('testcase_id') in hidden_testcase_ids:
            continue

        folder_id = testcase.get('folder_id', 0)
        
        # Get folder name from database
        folder_name = next((f['name'] for f in all_folders if f['folder_id'] == folder_id), 'Root')
        
        # Get tags for this testcase (from pre-fetched bulk map)
        tc_tags = testcase_tags_map.get(testcase['testcase_id'], [])
        tag_names = [tag['name'] for tag in tc_tags]
        
        # Apply filters
        if filter_folder and folder_name != filter_folder:
            continue
        
        if filter_tags and not any(tag in tag_names for tag in filter_tags):
            continue
        
        if search_query and search_query not in testcase['testcase_name'].lower():
            continue
        
        # Create testcase item
        testcase_item = {
            'type': 'testcase',
            'id': testcase['testcase_id'],
            'name': testcase['testcase_name'],
            'description': testcase.get('description', ''),
            'tags': tag_names,
            'userinterface': testcase.get('userinterface_name'),
            'created_at': testcase.get('created_at')
        }
        
        # Ensure folder exists in map
        if folder_name not in folder_map:
            folder_map[folder_name] = {
                'id': folder_id,
                'name': folder_name,
                'items': []
            }
        
        folder_map[folder_name]['items'].append(testcase_item)
    
    # Process virtual scripts (DB-stored Python). They're scripts too — same
    # execution path — but carry is_virtual + virtual_script_id so the run passes
    # the id (the host materializes the source). Grouped by their own folder_id
    # (same shared taxonomy as testcases/disk scripts, see TASK-11), tagged with a
    # "VS" badge in the UI via is_virtual. See docs/agent/execution/VIRTUAL_SCRIPTS.md.
    for vs in list_virtual_scripts(team_id):
        vs_name = vs.get('name')
        if not vs_name:
            continue
        # A virtual script named utils_/lib_/common_/_ is a library pulled in via
        # _script_libs, not something to run — same rule disk discovery applies.
        # Listing it offers a run that dies on the missing @script entry point.
        # The editor's own list keeps them (flagged is_library) so they stay editable.
        if not is_discoverable_script_ref(vs_name):
            continue
        display_id = f'{vs_name}.py'
        if not include_hidden and display_id in hidden_script_keys:
            continue
        # Disk scripts group under 'Root' but the shared folders table names row 0
        # '(Root)' — without this a converted root-level script lands in a second,
        # sibling group with the same meaning.
        folder_name = vs.get('folder') or 'Root'
        if folder_name == '(Root)':
            folder_name = 'Root'
        if filter_folder and filter_folder != folder_name:
            continue
        if search_query and search_query not in vs_name.lower():
            continue

        vs_item = {
            'type': 'script',
            'id': vs_name,
            'name': vs_name,
            'description': vs.get('description') or '',
            'tags': [],
            'target_rules': vs.get('target_rules'),
            'is_virtual': True,
            'virtual_script_id': vs.get('id'),  # dev row id (default target)
            # Per-environment row ids so the run resolves dev/test/prod to a
            # specific row; a dev and a prod run can target the same name on two
            # devices in parallel. prod_version surfaces the current prod counter.
            'virtual_script_env_ids': vs.get('environments') or {'dev': vs.get('id'), 'test': None, 'prod': None},
            'prod_version': vs.get('prod_version'),
        }
        if filter_tags:  # virtual scripts carry no tags yet
            continue
        folder_id = vs.get('folder_id') or 0
        folder_map.setdefault(folder_name, {'id': folder_id, 'name': folder_name, 'items': []})
        folder_map[folder_name]['items'].append(vs_item)

    # Convert to list and filter out empty folders
    folders = [folder for folder in folder_map.values() if len(folder['items']) > 0]
    
    # Sort folders by name (Root first, then alphabetical)
    folders.sort(key=lambda f: (f['name'] != 'Root', f['name'].lower()))
    
    # Get all unique folder names for the filter dropdown
    all_folder_names = sorted(set(folder_map.keys()))
    # Ensure Root is first
    if 'Root' in all_folder_names:
        all_folder_names.remove('Root')
        all_folder_names = ['Root'] + all_folder_names
    
    response_payload = {
        'success': True,
        'folders': folders,
        'all_tags': all_tags,
        'all_folders': all_folder_names
    }
    set_cached_response(cache_key, response_payload)
    return jsonify(response_payload)


def invalidate_executable_list_cache() -> None:
    invalidate_cached_responses('server_executable:list:')
    
