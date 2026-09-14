"""
Test Prompt Database Operations

Manages AI test prompts with versioning, execution tracking, and human feedback loop.
Prompts follow a dev → prod lifecycle with optional conversion to TestCase graphs.
"""

from typing import Dict, List, Optional
from uuid import uuid4
from datetime import datetime, timezone
from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    return get_supabase_client()


# ============================================================================
# CRUD
# ============================================================================

def create_test_prompt(
    team_id: str,
    name: str,
    prompt: str,
    acceptance_criteria: str,
    userinterface_name: str,
    target_screen_node_id: Optional[str] = None,
    target_screen_label: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Dict:
    try:
        supabase = get_supabase()
        data = {
            'id': str(uuid4()),
            'team_id': team_id,
            'name': name,
            'prompt': prompt,
            'acceptance_criteria': acceptance_criteria,
            'userinterface_name': userinterface_name,
            'target_screen_node_id': target_screen_node_id,
            'target_screen_label': target_screen_label,
            'version': 1,
            'mode': 'dev',
            'created_by': created_by,
        }
        result = supabase.table('test_prompts').insert(data).execute()
        if result.data:
            return {'success': True, 'test_prompt': result.data[0]}
        return {'success': False, 'message': 'Failed to create test prompt'}
    except Exception as e:
        print(f"[@db:test_prompts:create] Error: {e}")
        return {'success': False, 'message': str(e)}


def get_test_prompt(prompt_id: str, team_id: str) -> Optional[Dict]:
    try:
        supabase = get_supabase()
        result = supabase.table('test_prompts') \
            .select('*') \
            .eq('id', prompt_id) \
            .eq('team_id', team_id) \
            .execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"[@db:test_prompts:get] Error: {e}")
        return None


def list_test_prompts(team_id: str, mode: Optional[str] = None) -> List[Dict]:
    try:
        supabase = get_supabase()
        query = supabase.table('test_prompts') \
            .select('*') \
            .eq('team_id', team_id) \
            .order('updated_at', desc=True)
        if mode:
            query = query.eq('mode', mode)
        result = query.execute()
        return result.data or []
    except Exception as e:
        print(f"[@db:test_prompts:list] Error: {e}")
        return []


def update_test_prompt(prompt_id: str, team_id: str, **fields) -> Dict:
    try:
        supabase = get_supabase()
        # Include all fields — even None values for target_screen fields (to allow clearing)
        update_data = {}
        for k, v in fields.items():
            if v is not None:
                update_data[k] = v
            elif k in ('target_screen_node_id', 'target_screen_label'):
                update_data[k] = ''  # Allow clearing target screen
        update_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        result = supabase.table('test_prompts') \
            .update(update_data) \
            .eq('id', prompt_id) \
            .eq('team_id', team_id) \
            .execute()
        if result.data:
            return {'success': True, 'test_prompt': result.data[0]}
        return {'success': False, 'message': 'Test prompt not found'}
    except Exception as e:
        print(f"[@db:test_prompts:update] Error: {e}")
        return {'success': False, 'message': str(e)}


def delete_test_prompt(prompt_id: str, team_id: str) -> bool:
    try:
        supabase = get_supabase()
        result = supabase.table('test_prompts') \
            .delete() \
            .eq('id', prompt_id) \
            .eq('team_id', team_id) \
            .execute()
        return bool(result.data)
    except Exception as e:
        print(f"[@db:test_prompts:delete] Error: {e}")
        return False


# ============================================================================
# VERSIONING
# ============================================================================

def create_new_version(
    parent_id: str,
    team_id: str,
    prompt: str,
    acceptance_criteria: str,
    created_by: Optional[str] = None,
) -> Dict:
    """Create vN+1 from an existing prompt. Copies name/UI, increments version."""
    try:
        parent = get_test_prompt(parent_id, team_id)
        if not parent:
            return {'success': False, 'message': 'Parent prompt not found'}

        supabase = get_supabase()
        new_version = parent['version'] + 1
        data = {
            'id': str(uuid4()),
            'team_id': team_id,
            'name': parent['name'],
            'prompt': prompt,
            'acceptance_criteria': acceptance_criteria,
            'userinterface_name': parent['userinterface_name'],
            'target_screen_node_id': parent.get('target_screen_node_id'),
            'target_screen_label': parent.get('target_screen_label'),
            'version': new_version,
            'parent_id': parent_id,
            'mode': 'dev',
            'created_by': created_by,
        }
        result = supabase.table('test_prompts').insert(data).execute()
        if result.data:
            return {'success': True, 'test_prompt': result.data[0]}
        return {'success': False, 'message': 'Failed to create new version'}
    except Exception as e:
        print(f"[@db:test_prompts:new_version] Error: {e}")
        return {'success': False, 'message': str(e)}


def get_version_history(prompt_id: str, team_id: str) -> List[Dict]:
    """Get all versions by walking the parent chain and finding children."""
    try:
        prompt = get_test_prompt(prompt_id, team_id)
        if not prompt:
            return []

        # Find the root (v1) by walking parent_id up
        root = prompt
        while root.get('parent_id'):
            parent = get_test_prompt(root['parent_id'], team_id)
            if not parent:
                break
            root = parent

        # Get all prompts with same name, ordered by version
        supabase = get_supabase()
        result = supabase.table('test_prompts') \
            .select('*') \
            .eq('team_id', team_id) \
            .eq('name', root['name']) \
            .order('version', desc=False) \
            .execute()
        return result.data or []
    except Exception as e:
        print(f"[@db:test_prompts:version_history] Error: {e}")
        return []


# ============================================================================
# LIFECYCLE
# ============================================================================

def promote_to_prod(prompt_id: str, team_id: str) -> Dict:
    return update_test_prompt(prompt_id, team_id, mode='prod')


def link_testcase(prompt_id: str, team_id: str, testcase_id: str) -> Dict:
    return update_test_prompt(prompt_id, team_id, testcase_id=testcase_id)


# ============================================================================
# EXECUTIONS
# ============================================================================

def record_prompt_execution(
    test_prompt_id: str,
    team_id: str,
    host_name: str,
    device_id: str,
    executed_by: Optional[str] = None,
) -> Optional[str]:
    try:
        supabase = get_supabase()
        execution_id = str(uuid4())
        data = {
            'id': execution_id,
            'test_prompt_id': test_prompt_id,
            'team_id': team_id,
            'host_name': host_name,
            'device_id': device_id,
            'status': 'running',
            'executed_by': executed_by,
        }
        result = supabase.table('test_prompt_executions').insert(data).execute()
        return execution_id if result.data else None
    except Exception as e:
        print(f"[@db:test_prompts:record_execution] Error: {e}")
        return None


def update_prompt_execution(
    execution_id: str,
    team_id: str,
    status: Optional[str] = None,
    script_result_id: Optional[str] = None,
    report_url: Optional[str] = None,
    logs_url: Optional[str] = None,
    execution_time_ms: Optional[int] = None,
) -> bool:
    try:
        supabase = get_supabase()
        update_data = {}
        if status is not None:
            update_data['status'] = status
        if script_result_id is not None:
            update_data['script_result_id'] = script_result_id
        if report_url is not None:
            update_data['report_url'] = report_url
        if logs_url is not None:
            update_data['logs_url'] = logs_url
        if execution_time_ms is not None:
            update_data['execution_time_ms'] = execution_time_ms

        if not update_data:
            return True

        result = supabase.table('test_prompt_executions') \
            .update(update_data) \
            .eq('id', execution_id) \
            .eq('team_id', team_id) \
            .execute()
        return bool(result.data)
    except Exception as e:
        print(f"[@db:test_prompts:update_execution] Error: {e}")
        return False


def add_human_feedback(execution_id: str, team_id: str, feedback: str) -> bool:
    try:
        supabase = get_supabase()
        result = supabase.table('test_prompt_executions') \
            .update({'human_feedback': feedback}) \
            .eq('id', execution_id) \
            .eq('team_id', team_id) \
            .execute()
        return bool(result.data)
    except Exception as e:
        print(f"[@db:test_prompts:add_feedback] Error: {e}")
        return False


def list_prompt_executions(test_prompt_id: str, team_id: str) -> List[Dict]:
    try:
        supabase = get_supabase()
        result = supabase.table('test_prompt_executions') \
            .select('*') \
            .eq('test_prompt_id', test_prompt_id) \
            .eq('team_id', team_id) \
            .order('created_at', desc=True) \
            .execute()
        return result.data or []
    except Exception as e:
        print(f"[@db:test_prompts:list_executions] Error: {e}")
        return []
