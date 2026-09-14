"""
Campaign Definition Database Operations

Manages campaign definitions (collections of testcases/scripts) created in Campaign Builder.
Campaign executions are tracked in campaign_executions table.
Clean implementation with no backward compatibility.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.database.folder_tag_db import (
    get_or_create_tag,
    set_executable_tags,
    get_executable_tags
)

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _build_campaign_snapshot(campaign: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'campaign_name': campaign.get('campaign_name'),
        'description': campaign.get('description'),
        'userinterface_name': campaign.get('userinterface_name'),
        'host_name': campaign.get('host_name'),
        'device_name': campaign.get('device_name'),
        'execution_config': campaign.get('execution_config') or {},
        'script_configurations': campaign.get('script_configurations') or [],
    }


def _save_campaign_to_history(
    campaign_id: str,
    team_id: str,
    modification_type: str,
    modified_by: str = None,
    changes_summary: str = None,
    restored_from_version: int = None,
    campaign: Dict[str, Any] = None,
) -> Optional[int]:
    supabase = get_supabase()
    if not supabase:
        return None

    try:
        current_campaign = campaign or get_campaign(campaign_id, team_id)
        if not current_campaign:
            print(f"[@campaign_db:_save_campaign_to_history] ERROR: Campaign not found: {campaign_id}")
            return None

        version_result = supabase.table('campaigns_history')\
            .select('version_number')\
            .eq('campaign_id', campaign_id)\
            .eq('team_id', team_id)\
            .order('version_number', desc=True)\
            .limit(1)\
            .execute()

        next_version = 1
        if version_result.data:
            next_version = version_result.data[0]['version_number'] + 1

        history_record = {
            'campaign_id': campaign_id,
            'team_id': team_id,
            'version_number': next_version,
            'campaign_name': current_campaign.get('campaign_name'),
            'modification_type': modification_type,
            'modified_by': modified_by,
            'modified_at': datetime.now(timezone.utc).isoformat(),
            'changes_summary': changes_summary or modification_type.title(),
            'restored_from_version': restored_from_version,
            'campaign_data': _build_campaign_snapshot(current_campaign),
        }
        supabase.table('campaigns_history').insert(history_record).execute()
        print(f"[@campaign_db:_save_campaign_to_history] Saved v{next_version} for campaign {campaign_id}")
        return next_version
    except Exception as e:
        print(f"[@campaign_db:_save_campaign_to_history] ERROR: {e}")
        return None


def create_campaign(
    team_id: str,
    campaign_name: str,
    description: str = None,
    userinterface_name: str = None,
    host_name: str = None,
    device_name: str = None,
    execution_config: Dict[str, Any] = None,
    script_configurations: List[Dict[str, Any]] = None,
    created_by: str = None,
    overwrite: bool = False,
    auto_increment_if_exists: bool = True,
    tags: List[str] = None
) -> Optional[str]:
    """
    Create a new campaign definition, or update if it exists and overwrite=True.

    Args:
        team_id: Team ID
        campaign_name: Unique name for the campaign (used as identifier)
        description: Optional description
        userinterface_name: Navigation tree to use
        host_name: Host where campaign will run
        device_name: Device where campaign will run
        execution_config: Execution configuration (timeout, parallel, etc.)
        script_configurations: List of scripts/testcases to run
        created_by: Username who created it
        overwrite: If True, update existing campaign with same name (DEPRECATED)
        auto_increment_if_exists: If True, append _2, _3, etc. if name exists
        folder: Folder name (user-selected or typed)
        tags: List of tag names (existing or new)

    Returns:
        campaign_id (UUID) or None on failure
    """
    supabase = get_supabase()
    if not supabase:
        print("[@campaign_db] ERROR: Failed to get Supabase client")
        return None

    try:
        # 🔄 AUTO-INCREMENT: Check for name conflicts and increment if needed
        final_campaign_name = campaign_name
        if not overwrite and auto_increment_if_exists:
            existing = get_campaign_by_name(campaign_name, team_id)
            if existing:
                # Name exists - find next available increment
                counter = 2
                while True:
                    candidate_name = f"{campaign_name}_{counter}"
                    if not get_campaign_by_name(candidate_name, team_id):
                        final_campaign_name = candidate_name
                        print(f"[@campaign_db] ⚠️  '{campaign_name}' exists → auto-renamed to '{final_campaign_name}'")
                        break
                    counter += 1
                    if counter > 100:  # Safety limit
                        print(f"[@campaign_db] ❌ Too many duplicates (>100), aborting")
                        return None

        # Check if campaign with this name already exists
        if overwrite:
            existing = get_campaign_by_name(campaign_name, team_id)
            if existing:
                # Update existing campaign
                success = update_campaign(
                    campaign_id=existing['campaign_id'],
                    campaign_name=campaign_name,
                    description=description,
                    userinterface_name=userinterface_name,
                    host_name=host_name,
                    device_name=device_name,
                    execution_config=execution_config,
                    script_configurations=script_configurations,
                    team_id=team_id
                )
                if success:
                    print(f"[@campaign_db] Updated campaign: {campaign_name} (overwrite mode)")
                    return existing['campaign_id']
                else:
                    return None

        data = {
            'team_id': team_id,
            'campaign_name': final_campaign_name,
            'description': description,
            'userinterface_name': userinterface_name,
            'host_name': host_name,
            'device_name': device_name,
            'execution_config': execution_config or {},
            'script_configurations': script_configurations or [],
            'created_by': created_by
        }

        result = supabase.table('campaigns').insert(data).execute()

        if result.data and len(result.data) > 0:
            campaign_id = result.data[0]['campaign_id']

            # Set tags if provided
            if tags:
                set_executable_tags('campaign', str(campaign_id), tags)

            created_campaign = result.data[0]
            created_campaign['campaign_id'] = str(created_campaign['campaign_id'])
            created_campaign['team_id'] = str(created_campaign['team_id'])
            _save_campaign_to_history(
                campaign_id=str(campaign_id),
                team_id=team_id,
                modification_type='create',
                modified_by=created_by,
                changes_summary='Created',
                campaign=created_campaign,
            )

            print(f"[@campaign_db] Created campaign: {final_campaign_name} (ID: {campaign_id}, tags: {len(tags) if tags else 0})")

            # Return dict with campaign_id and actual name used (may be auto-incremented)
            return {
                'campaign_id': str(campaign_id),
                'campaign_name': final_campaign_name,
                'success': True
            }
        else:
            print(f"[@campaign_db] ERROR: No data returned after insert")
            return None

    except Exception as e:
        error_msg = str(e)
        if 'duplicate key' in error_msg.lower() or 'unique constraint' in error_msg.lower():
            print(f"[@campaign_db] ERROR: Campaign name already exists: {campaign_name}")
            return 'DUPLICATE_NAME'  # Return special value to indicate duplicate
        else:
            print(f"[@campaign_db] ERROR creating campaign: {e}")
        return None


def get_campaign(campaign_id: str, team_id: str = None) -> Optional[Dict[str, Any]]:
    """
    Get campaign definition by ID.

    Args:
        campaign_id: Campaign UUID
        team_id: Optional team ID for security check

    Returns:
        Campaign dict or None
    """
    supabase = get_supabase()
    if not supabase:
        return None

    try:
        query = supabase.table('campaigns').select('*').eq('campaign_id', campaign_id)

        if team_id:
            query = query.eq('team_id', team_id)

        result = query.execute()

        if result.data and len(result.data) > 0:
            campaign = result.data[0]
            # Ensure IDs are strings
            campaign['campaign_id'] = str(campaign['campaign_id'])
            campaign['team_id'] = str(campaign['team_id'])
            # Parse JSON fields if they're strings
            if isinstance(campaign.get('execution_config'), str):
                campaign['execution_config'] = json.loads(campaign['execution_config'])
            if isinstance(campaign.get('script_configurations'), str):
                campaign['script_configurations'] = json.loads(campaign['script_configurations'])
            return campaign

        return None

    except Exception as e:
        print(f"[@campaign_db] ERROR getting campaign: {e}")
        return None


def get_campaign_by_name(campaign_name: str, team_id: str) -> Optional[Dict[str, Any]]:
    """
    Get campaign definition by name.

    Args:
        campaign_name: Campaign name
        team_id: Team ID

    Returns:
        Campaign dict or None
    """
    supabase = get_supabase()
    if not supabase:
        return None

    try:
        result = supabase.table('campaigns')\
            .select('*')\
            .eq('campaign_name', campaign_name)\
            .eq('team_id', team_id)\
            .execute()

        if result.data and len(result.data) > 0:
            campaign = result.data[0]
            campaign['campaign_id'] = str(campaign['campaign_id'])
            campaign['team_id'] = str(campaign['team_id'])
            # Parse JSON fields if they're strings
            if isinstance(campaign.get('execution_config'), str):
                campaign['execution_config'] = json.loads(campaign['execution_config'])
            if isinstance(campaign.get('script_configurations'), str):
                campaign['script_configurations'] = json.loads(campaign['script_configurations'])
            return campaign

        return None

    except Exception as e:
        print(f"[@campaign_db] ERROR getting campaign by name: {e}")
        return None


def update_campaign(
    campaign_id: str,
    campaign_name: str = None,
    description: str = None,
    userinterface_name: str = None,
    host_name: str = None,
    device_name: str = None,
    execution_config: Dict[str, Any] = None,
    script_configurations: List[Dict[str, Any]] = None,
    team_id: str = None,
    tags: List[str] = None,
    modified_by: str = None,
) -> bool:
    """
    Update campaign definition.

    Args:
        campaign_id: Campaign UUID
        campaign_name: Updated campaign name
        description: Updated description
        userinterface_name: Updated navigation tree
        host_name: Updated host name
        device_name: Updated device name
        execution_config: Updated execution configuration
        script_configurations: Updated script configurations
        team_id: Team ID for security check
        tags: Updated list of tag names

    Returns:
        True on success, False on failure
    """
    supabase = get_supabase()
    if not supabase:
        return False

    try:
        # Build update data
        update_data = {}

        if campaign_name is not None:
            update_data['campaign_name'] = campaign_name

        if description is not None:
            update_data['description'] = description

        if userinterface_name is not None:
            update_data['userinterface_name'] = userinterface_name

        if host_name is not None:
            update_data['host_name'] = host_name

        if device_name is not None:
            update_data['device_name'] = device_name

        if execution_config is not None:
            update_data['execution_config'] = execution_config

        if script_configurations is not None:
            update_data['script_configurations'] = script_configurations

        if not update_data and tags is None:
            print("[@campaign_db] WARNING: No fields to update")
            return True

        # Update campaign record if there's data
        updated_campaign = None
        if update_data:
            query = supabase.table('campaigns').update(update_data).eq('campaign_id', campaign_id)

            if team_id:
                query = query.eq('team_id', team_id)

            result = query.execute()

            if not result.data or len(result.data) == 0:
                print(f"[@campaign_db] WARNING: No campaign updated (ID: {campaign_id})")
                return False
            updated_campaign = result.data[0]
            updated_campaign['campaign_id'] = str(updated_campaign['campaign_id'])
            updated_campaign['team_id'] = str(updated_campaign['team_id'])

        # Update tags if provided
        if tags is not None:
            set_executable_tags('campaign', campaign_id, tags)

        if update_data:
            _save_campaign_to_history(
                campaign_id=campaign_id,
                team_id=team_id,
                modification_type='update',
                modified_by=modified_by,
                changes_summary='Updated',
                campaign=updated_campaign,
            )

        name_info = f" -> {campaign_name}" if campaign_name else ""
        print(f"[@campaign_db] Updated campaign: {campaign_id}{name_info}")
        return True

    except Exception as e:
        error_msg = str(e)
        if campaign_name and ('duplicate key' in error_msg.lower() or 'unique constraint' in error_msg.lower()):
            print(f"[@campaign_db] ERROR: Campaign name already exists: {campaign_name}")
        else:
            print(f"[@campaign_db] ERROR updating campaign: {e}")
        return False


def get_campaign_history(campaign_id: str, team_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    supabase = get_supabase()
    if not supabase:
        return []

    try:
        result = supabase.table('campaigns_history')\
            .select('*')\
            .eq('campaign_id', campaign_id)\
            .eq('team_id', team_id)\
            .order('version_number', desc=True)\
            .limit(limit)\
            .execute()
        return result.data or []
    except Exception as e:
        print(f"[@campaign_db:get_campaign_history] ERROR: {e}")
        return []


def restore_campaign_from_history(campaign_id: str, version_number: int, team_id: str, restored_by: str = None) -> Dict[str, Any]:
    supabase = get_supabase()
    if not supabase:
        return {'success': False, 'error': 'Supabase client unavailable'}

    try:
        history_result = supabase.table('campaigns_history')\
            .select('*')\
            .eq('campaign_id', campaign_id)\
            .eq('team_id', team_id)\
            .eq('version_number', version_number)\
            .limit(1)\
            .execute()

        if not history_result.data:
            return {'success': False, 'error': f'Version {version_number} not found'}

        snapshot = history_result.data[0].get('campaign_data') or {}
        update_data = {
            'campaign_name': snapshot.get('campaign_name'),
            'description': snapshot.get('description'),
            'userinterface_name': snapshot.get('userinterface_name'),
            'host_name': snapshot.get('host_name'),
            'device_name': snapshot.get('device_name'),
            'execution_config': snapshot.get('execution_config') or {},
            'script_configurations': snapshot.get('script_configurations') or [],
        }

        result = supabase.table('campaigns').update(update_data)\
            .eq('campaign_id', campaign_id)\
            .eq('team_id', team_id)\
            .execute()

        if not result.data:
            return {'success': False, 'error': 'Campaign not found during restore'}

        restored_campaign = result.data[0]
        restored_campaign['campaign_id'] = str(restored_campaign['campaign_id'])
        restored_campaign['team_id'] = str(restored_campaign['team_id'])
        new_version = _save_campaign_to_history(
            campaign_id=campaign_id,
            team_id=team_id,
            modification_type='restore',
            modified_by=restored_by,
            changes_summary=f'Restored from version {version_number}',
            restored_from_version=version_number,
            campaign=restored_campaign,
        )

        return {
            'success': True,
            'new_version': new_version,
            'restored_from_version': version_number,
            'campaign': restored_campaign,
        }
    except Exception as e:
        print(f"[@campaign_db:restore_campaign_from_history] ERROR: {e}")
        return {'success': False, 'error': str(e)}


def delete_campaign(campaign_id: str, team_id: str = None) -> bool:
    """
    Delete campaign permanently.

    Args:
        campaign_id: Campaign UUID
        team_id: Team ID for security check

    Returns:
        True on success, False on failure
    """
    supabase = get_supabase()
    if not supabase:
        print(f"[@campaign_db:delete] ERROR: Failed to get Supabase client")
        return False

    try:
        # First check if campaign exists
        check_query = supabase.table('campaigns')\
            .select('campaign_id,team_id,campaign_name')\
            .eq('campaign_id', campaign_id)

        if team_id:
            check_query = check_query.eq('team_id', team_id)

        check_result = check_query.execute()

        if not check_result.data or len(check_result.data) == 0:
            print(f"[@campaign_db:delete] WARNING: Campaign not found (ID: {campaign_id}, team_id: {team_id})")
            return False

        campaign_name = check_result.data[0].get('campaign_name', 'unknown')
        print(f"[@campaign_db:delete] Found campaign to delete: {campaign_name} (ID: {campaign_id})")

        # Now delete it
        delete_query = supabase.table('campaigns')\
            .delete()\
            .eq('campaign_id', campaign_id)

        if team_id:
            delete_query = delete_query.eq('team_id', team_id)

        result = delete_query.execute()

        if result.data and len(result.data) > 0:
            print(f"[@campaign_db:delete] ✅ Deleted campaign: {campaign_name} (ID: {campaign_id})")
            return True
        else:
            print(f"[@campaign_db:delete] ⚠️ Delete executed but no rows affected (ID: {campaign_id})")
            return False

    except Exception as e:
        print(f"[@campaign_db:delete] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def list_campaigns(team_id: str, include_config: bool = False) -> List[Dict[str, Any]]:
    """
    List all campaigns for a team.

    Args:
        team_id: Team ID
        include_config: If True, includes execution_config and script_configurations (slower)

    Returns:
        List of campaign dicts
    """
    supabase = get_supabase()
    if not supabase:
        return []

    try:
        # OPTIMIZED: Select fields based on need
        # By default, exclude large JSON fields for performance
        if include_config:
            select_fields = 'campaign_id,team_id,campaign_name,description,userinterface_name,host_name,device_name,execution_config,script_configurations,created_at,updated_at,created_by'
        else:
            select_fields = 'campaign_id,team_id,campaign_name,description,userinterface_name,host_name,device_name,created_at,updated_at,created_by'

        query = supabase.table('campaigns')\
            .select(select_fields)\
            .eq('team_id', team_id)

        query = query.order('updated_at', desc=True)

        result = query.execute()

        if not result.data:
            return []

        # OPTIMIZED: Batch fetch execution stats for ALL campaigns in a single query
        campaign_names = [c['campaign_name'] for c in result.data]
        exec_map = {}

        if campaign_names:
            try:
                # Fetch all execution records for these campaigns
                exec_result = supabase.table('campaign_executions')\
                    .select('campaign_name,success,started_at')\
                    .eq('team_id', team_id)\
                    .in_('campaign_name', campaign_names)\
                    .order('started_at', desc=True)\
                    .execute()

                # Build execution map (campaign_name -> {count, last_success})
                for record in exec_result.data:
                    name = record['campaign_name']
                    if name not in exec_map:
                        exec_map[name] = {
                            'count': 0,
                            'last_success': record.get('success')
                        }
                    exec_map[name]['count'] += 1
            except Exception as e:
                print(f"[@campaign_db] Warning: Failed to fetch execution stats: {e}")

        # Build final campaign list with all metadata
        campaigns = []
        for campaign in result.data:
            campaign['campaign_id'] = str(campaign['campaign_id'])
            campaign['team_id'] = str(campaign['team_id'])

            # Add execution stats from batch-fetched map
            exec_info = exec_map.get(campaign['campaign_name'], {})
            campaign['execution_count'] = exec_info.get('count', 0)
            campaign['last_execution_success'] = exec_info.get('last_success')

            campaigns.append(campaign)

        return campaigns

    except Exception as e:
        print(f"[@campaign_db] ERROR listing campaigns: {e}")
        return []


def get_campaign_execution_history(campaign_name: str, team_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get execution history for a campaign from campaign_executions table.

    Args:
        campaign_name: Campaign name
        team_id: Team ID
        limit: Max number of results

    Returns:
        List of execution records
    """
    supabase = get_supabase()
    if not supabase:
        return []

    try:
        result = supabase.table('campaign_executions')\
            .select('id,campaign_name,campaign_execution_id,status,started_at,completed_at,execution_time_ms,success,error_message,host_name,device_name,script_configurations,html_report_r2_url,logs_r2_url')\
            .eq('campaign_name', campaign_name)\
            .eq('team_id', team_id)\
            .order('started_at', desc=True)\
            .limit(limit)\
            .execute()

        executions = []
        for execution in result.data:
            execution['id'] = str(execution['id'])
            executions.append(execution)

        return executions

    except Exception as e:
        print(f"[@campaign_db] ERROR getting execution history: {e}")
        return []


def validate_campaign_config(
    script_configurations: List[Dict[str, Any]],
    team_id: str,
    execution_config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Validate campaign configuration before saving.

    Args:
        script_configurations: List of script configurations
        team_id: Team ID for validation

    Returns:
        {
            'success': bool,
            'errors': List[str] (if validation fails),
            'warnings': List[str] (non-critical issues)
        }
    """
    from shared.src.lib.database.testcase_db import get_testcase_by_name
    from shared.src.lib.utils.script_identity_utils import resolve_script_source_path

    errors = []
    warnings = []

    try:
        for i, script_config in enumerate(script_configurations):
            script_name = script_config.get('script_name', '').strip()
            script_type = (script_config.get('script_type') or '').strip().lower()
            testcase_id = (script_config.get('testcase_id') or '').strip()

            if not script_name:
                errors.append(f"Script configuration {i+1}: script_name is required")
                continue

            if script_type == 'testcase' or testcase_id:
                testcase = get_testcase_by_name(script_name, team_id)
                if not testcase:
                    errors.append(f"Script '{script_name}' not found as a testcase")
            else:
                script_path = resolve_script_source_path(script_name)
                if not script_path:
                    errors.append(f"Script '{script_name}' not found")

            # Validate script parameters if provided
            parameters = script_config.get('parameters', {})
            if not isinstance(parameters, dict):
                warnings.append(f"Script '{script_name}': parameters should be a dictionary")

        # 🔒 CAMPAIGN FLOW CONTROL VALIDATION

        # Check for duplicate scripts in the campaign
        script_names = []
        for i, script_config in enumerate(script_configurations):
            script_name = script_config.get('script_name', '').strip()
            if script_name:
                if script_name in script_names:
                    errors.append(f"INVALID CAMPAIGN: Script '{script_name}' appears multiple times in the campaign. Each script can only be executed once.")
                script_names.append(script_name)

        # Check for execution config flow control issues
        if execution_config:
            parallel_execution = execution_config.get('parallel', False)

            if parallel_execution:
                # Check for device conflicts in parallel execution
                device_assignments = {}
                for i, script_config in enumerate(script_configurations):
                    script_name = script_config.get('script_name', '').strip()
                    device_name = script_config.get('device_name') or execution_config.get('device_name')

                    if device_name:
                        if device_name in device_assignments:
                            existing_script = device_assignments[device_name]
                            errors.append(
                                f"INVALID PARALLEL EXECUTION: Both '{existing_script}' and '{script_name}' "
                                f"are configured to run on device '{device_name}'. Parallel execution requires unique device assignments."
                            )
                        else:
                            device_assignments[device_name] = script_name

                # Check for scripts that might have resource conflicts
                # This is a basic check - could be extended based on known resource requirements
                exclusive_resources = ['adb', 'scrcpy', 'video_capture']  # Scripts that need exclusive access
                resource_usage = {}

                for script_config in script_configurations:
                    script_name = script_config.get('script_name', '').strip()
                    # Check if script uses exclusive resources (this could be enhanced with script metadata)
                    if any(resource in script_name.lower() for resource in exclusive_resources):
                        resource_key = 'exclusive_device_access'
                        if resource_key in resource_usage and parallel_execution:
                            existing_script = resource_usage[resource_key]
                            warnings.append(
                                f"POTENTIAL RESOURCE CONFLICT: Both '{existing_script}' and '{script_name}' "
                                f"may require exclusive device access. Consider sequential execution."
                            )
                        resource_usage[resource_key] = script_name

        # Return validation result
        if errors:
            print(f"[@campaign_db:validate] ❌ Validation FAILED: {len(errors)} error(s)")
            for error in errors:
                print(f"[@campaign_db:validate]   - {error}")
            return {
                'success': False,
                'errors': errors,
                'warnings': warnings
            }

        if warnings:
            print(f"[@campaign_db:validate] ⚠️  Validation passed with {len(warnings)} warning(s)")
            for warning in warnings:
                print(f"[@campaign_db:validate]   - {warning}")
        else:
            print(f"[@campaign_db:validate] ✅ Validation passed - all scripts valid")

        return {
            'success': True,
            'warnings': warnings
        }

    except Exception as e:
        print(f"[@campaign_db:validate] Exception during validation: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'errors': [f"Validation failed with exception: {str(e)}"]
        }
