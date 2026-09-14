"""
Requirements Management Database Operations

Manages requirements and their linkage to testcases and scripts for coverage tracking.
Follows the same patterns as testcase_db.py for consistency.
"""

import json
from typing import Dict, List, Optional, Any
from shared.src.lib.utils.supabase_utils import get_supabase_client

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


# ================================================
# Requirements CRUD Operations
# ================================================

def create_requirement(
    team_id: str,
    requirement_code: str,
    requirement_name: str,
    category: str = None,
    priority: str = 'P2',
    description: str = None,
    acceptance_criteria: List[str] = None,
    app_type: str = 'all',
    device_model: str = 'all',
    status: str = 'active',
    source_document: str = None,
    created_by: str = None
) -> Optional[str]:
    """
    Create a new requirement.
    
    Args:
        team_id: Team ID
        requirement_code: Unique code (e.g., "REQ_PLAYBACK_001")
        requirement_name: Human-readable name
        category: Category (e.g., "playback", "auth", "navigation")
        priority: P1 (Critical), P2 (High), P3 (Medium)
        description: Full requirement description
        acceptance_criteria: List of acceptance criteria strings
        app_type: "streaming", "social", "news", or "all"
        device_model: "android_mobile", "android_tv", "web", or "all"
        status: "active", "deprecated", or "draft"
        source_document: Link to original spec
        created_by: Username
    
    Returns:
        requirement_id (UUID) or None on failure
    """
    supabase = get_supabase()
    if not supabase:
        print("[@requirements_db] ERROR: Failed to get Supabase client")
        return None
    
    try:
        data = {
            'team_id': team_id,
            'requirement_code': requirement_code,
            'requirement_name': requirement_name,
            'category': category,
            'priority': priority,
            'description': description,
            'acceptance_criteria': acceptance_criteria,
            'app_type': app_type,
            'device_model': device_model,
            'status': status,
            'source_document': source_document,
            'created_by': created_by
        }
        
        result = supabase.table('requirements').insert(data).execute()
        
        if result.data and len(result.data) > 0:
            requirement_id = result.data[0]['requirement_id']
            print(f"[@requirements_db] Created requirement: {requirement_code} - {requirement_name} (ID: {requirement_id})")
            return str(requirement_id)
        else:
            print(f"[@requirements_db] ERROR: No data returned after insert")
            return None
        
    except Exception as e:
        error_msg = str(e)
        if 'duplicate key' in error_msg.lower() or 'unique constraint' in error_msg.lower():
            print(f"[@requirements_db] ERROR: Requirement code already exists: {requirement_code}")
            return 'DUPLICATE_CODE'
        else:
            print(f"[@requirements_db] ERROR creating requirement: {e}")
        return None


def get_requirement(requirement_id: str, team_id: str = None) -> Optional[Dict[str, Any]]:
    """Get requirement by ID."""
    supabase = get_supabase()
    if not supabase:
        return None
    
    try:
        query = supabase.table('requirements').select('*').eq('requirement_id', requirement_id)
        
        if team_id:
            query = query.eq('team_id', team_id)
        
        result = query.execute()
        
        if result.data and len(result.data) > 0:
            requirement = result.data[0]
            requirement['requirement_id'] = str(requirement['requirement_id'])
            requirement['team_id'] = str(requirement['team_id'])
            return requirement
        
        return None
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting requirement: {e}")
        return None


def get_requirement_by_code(requirement_code: str, team_id: str) -> Optional[Dict[str, Any]]:
    """Get requirement by code."""
    supabase = get_supabase()
    if not supabase:
        return None
    
    try:
        result = supabase.table('requirements')\
            .select('*')\
            .eq('requirement_code', requirement_code)\
            .eq('team_id', team_id)\
            .execute()
        
        if result.data and len(result.data) > 0:
            requirement = result.data[0]
            requirement['requirement_id'] = str(requirement['requirement_id'])
            requirement['team_id'] = str(requirement['team_id'])
            return requirement
        
        return None
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting requirement by code: {e}")
        return None


def update_requirement(
    requirement_id: str,
    team_id: str,
    requirement_code: str = None,
    requirement_name: str = None,
    category: str = None,
    description: str = None,
    priority: str = None,
    status: str = None,
    acceptance_criteria: List[str] = None,
    app_type: str = None,
    device_model: str = None
) -> bool:
    """Update requirement."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        update_data = {}
        
        if requirement_code is not None:
            update_data['requirement_code'] = requirement_code
        if requirement_name is not None:
            update_data['requirement_name'] = requirement_name
        if category is not None:
            update_data['category'] = category
        if description is not None:
            update_data['description'] = description
        if priority is not None:
            update_data['priority'] = priority
        if status is not None:
            update_data['status'] = status
        if acceptance_criteria is not None:
            update_data['acceptance_criteria'] = acceptance_criteria
        if app_type is not None:
            update_data['app_type'] = app_type
        if device_model is not None:
            update_data['device_model'] = device_model
        
        if not update_data:
            print("[@requirements_db] WARNING: No fields to update")
            return True
        
        result = supabase.table('requirements')\
            .update(update_data)\
            .eq('requirement_id', requirement_id)\
            .eq('team_id', team_id)\
            .execute()
        
        if result.data and len(result.data) > 0:
            print(f"[@requirements_db] Updated requirement: {requirement_id}")
            return True
        else:
            print(f"[@requirements_db] WARNING: No requirement updated")
            return False
        
    except Exception as e:
        print(f"[@requirements_db] ERROR updating requirement: {e}")
        return False


def list_requirements(
    team_id: str,
    category: str = None,
    priority: str = None,
    app_type: str = None,
    device_model: str = None,
    status: str = 'active'
) -> List[Dict[str, Any]]:
    """List requirements with optional filters."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    try:
        query = supabase.table('requirements')\
            .select('*')\
            .eq('team_id', team_id)
        
        if category:
            query = query.eq('category', category)
        if priority:
            query = query.eq('priority', priority)
        if app_type:
            query = query.eq('app_type', app_type)
        if device_model:
            query = query.eq('device_model', device_model)
        if status:
            query = query.eq('status', status)
        
        query = query.order('priority').order('category').order('requirement_code')
        
        result = query.execute()
        
        requirements = []
        for req in result.data:
            req['requirement_id'] = str(req['requirement_id'])
            req['team_id'] = str(req['team_id'])
            requirements.append(req)
        
        return requirements
        
    except Exception as e:
        print(f"[@requirements_db] ERROR listing requirements: {e}")
        return []


# ================================================
# TestCase-Requirement Linkage
# ================================================

def link_testcase_to_requirement(
    testcase_id: str,
    requirement_id: str,
    coverage_type: str = 'full',
    coverage_notes: str = None,
    created_by: str = None
) -> bool:
    """Link testcase to requirement."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        data = {
            'testcase_id': testcase_id,
            'requirement_id': requirement_id,
            'coverage_type': coverage_type,
            'coverage_notes': coverage_notes,
            'created_by': created_by
        }
        
        result = supabase.table('testcase_requirements').insert(data).execute()
        
        if result.data and len(result.data) > 0:
            print(f"[@requirements_db] Linked testcase {testcase_id} to requirement {requirement_id}")
            return True
        else:
            print(f"[@requirements_db] ERROR: Failed to link testcase to requirement")
            return False
        
    except Exception as e:
        error_msg = str(e)
        if 'duplicate key' in error_msg.lower():
            print(f"[@requirements_db] WARNING: Testcase already linked to requirement")
            return True  # Already linked is OK
        else:
            print(f"[@requirements_db] ERROR linking testcase to requirement: {e}")
        return False


def unlink_testcase_from_requirement(testcase_id: str, requirement_id: str) -> bool:
    """Unlink testcase from requirement."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        result = supabase.table('testcase_requirements')\
            .delete()\
            .eq('testcase_id', testcase_id)\
            .eq('requirement_id', requirement_id)\
            .execute()
        
        if result.data:
            print(f"[@requirements_db] Unlinked testcase {testcase_id} from requirement {requirement_id}")
            return True
        return False
        
    except Exception as e:
        print(f"[@requirements_db] ERROR unlinking testcase: {e}")
        return False


def get_testcase_requirements(testcase_id: str) -> List[Dict[str, Any]]:
    """Get all requirements linked to a testcase."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    try:
        result = supabase.table('testcase_requirements')\
            .select('requirement_id, coverage_type, coverage_notes, requirements(*)')\
            .eq('testcase_id', testcase_id)\
            .execute()
        
        requirements = []
        for row in result.data:
            if row.get('requirements'):
                req = row['requirements']
                req['coverage_type'] = row['coverage_type']
                req['coverage_notes'] = row['coverage_notes']
                requirements.append(req)
        
        return requirements
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting testcase requirements: {e}")
        return []


# ================================================
# Script-Requirement Linkage
# ================================================

def link_script_to_requirement(
    script_name: str,
    requirement_id: str,
    coverage_type: str = 'full',
    coverage_notes: str = None,
    created_by: str = None
) -> bool:
    """Link script to requirement."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        data = {
            'script_name': script_name,
            'requirement_id': requirement_id,
            'coverage_type': coverage_type,
            'coverage_notes': coverage_notes,
            'created_by': created_by
        }
        
        result = supabase.table('script_requirements').insert(data).execute()
        
        if result.data and len(result.data) > 0:
            print(f"[@requirements_db] Linked script {script_name} to requirement {requirement_id}")
            return True
        else:
            print(f"[@requirements_db] ERROR: Failed to link script to requirement")
            return False
        
    except Exception as e:
        error_msg = str(e)
        if 'duplicate key' in error_msg.lower():
            print(f"[@requirements_db] WARNING: Script already linked to requirement")
            return True  # Already linked is OK
        else:
            print(f"[@requirements_db] ERROR linking script to requirement: {e}")
        return False


def unlink_script_from_requirement(script_name: str, requirement_id: str) -> bool:
    """Unlink script from requirement."""
    supabase = get_supabase()
    if not supabase:
        return False
    
    try:
        result = supabase.table('script_requirements')\
            .delete()\
            .eq('script_name', script_name)\
            .eq('requirement_id', requirement_id)\
            .execute()
        
        if result.data:
            print(f"[@requirements_db] Unlinked script {script_name} from requirement {requirement_id}")
            return True
        return False
        
    except Exception as e:
        print(f"[@requirements_db] ERROR unlinking script: {e}")
        return False


def get_script_requirements(script_name: str) -> List[Dict[str, Any]]:
    """Get all requirements linked to a script."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    try:
        result = supabase.table('script_requirements')\
            .select('requirement_id, coverage_type, coverage_notes, requirements(*)')\
            .eq('script_name', script_name)\
            .execute()
        
        requirements = []
        for row in result.data:
            if row.get('requirements'):
                req = row['requirements']
                req['coverage_type'] = row['coverage_type']
                req['coverage_notes'] = row['coverage_notes']
                requirements.append(req)
        
        return requirements
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting script requirements: {e}")
        return []


# ================================================
# Coverage Reporting
# ================================================

def get_requirement_coverage(team_id: str, requirement_id: str) -> Dict[str, Any]:
    """
    Get detailed coverage for a requirement with testcases grouped by userinterface.
    
    Returns:
        {
            'requirement': {...},
            'testcases_by_ui': {
                'netflix_mobile': [testcase1, testcase2],
                'youtube_tv': [testcase3]
            },
            'scripts': [...],
            'coverage_summary': {
                'total_testcases': 5,
                'total_scripts': 2,
                'pass_rate': 0.92,
                'execution_count': 247
            }
        }
    """
    supabase = get_supabase()
    if not supabase:
        return {}
    
    try:
        # Get requirement
        requirement = get_requirement(requirement_id, team_id)
        if not requirement:
            return {}
        
        # Get linked testcase IDs
        tc_links = supabase.table('testcase_requirements')\
            .select('testcase_id, coverage_type')\
            .eq('requirement_id', requirement_id)\
            .execute()

        # Fetch testcase definitions separately (PostgREST schema cache may not know the FK)
        tc_defs: dict = {}
        if tc_links.data:
            tc_ids = [row['testcase_id'] for row in tc_links.data]
            tc_def_rows = supabase.table('testcase_definitions')\
                .select('testcase_id, testcase_name, description, userinterface_name')\
                .in_('testcase_id', tc_ids)\
                .execute()
            tc_defs = {str(row['testcase_id']): row for row in (tc_def_rows.data or [])}

        # Merge coverage_type back in
        testcases_merged = [
            {**tc_defs[str(row['testcase_id'])], 'coverage_type': row['coverage_type']}
            for row in tc_links.data
            if str(row['testcase_id']) in tc_defs
        ]

        # Get linked scripts
        scripts = supabase.table('script_requirements')\
            .select('script_name, coverage_type')\
            .eq('requirement_id', requirement_id)\
            .execute()

        # Group testcases by UI and get execution stats
        testcases_by_ui = {}
        total_passes = 0
        total_executions = 0

        for tc in testcases_merged:
            testcase_name = tc.get('testcase_name')
            userinterface_name = tc.get('userinterface_name') or 'unknown'

            # Get recent executions
            executions = supabase.table('script_results')\
                .select('success, started_at')\
                .eq('script_name', testcase_name)\
                .eq('team_id', team_id)\
                .order('started_at', desc=True)\
                .limit(10)\
                .execute()

            pass_count = sum(1 for e in executions.data if e.get('success'))
            execution_count = len(executions.data)
            total_passes += pass_count
            total_executions += execution_count

            testcase_data = {
                'testcase_id': tc['testcase_id'],
                'testcase_name': testcase_name,
                'description': tc.get('description'),
                'coverage_type': tc.get('coverage_type'),
                'execution_count': execution_count,
                'pass_count': pass_count,
                'pass_rate': (pass_count / execution_count) if execution_count > 0 else 0,
                'last_execution': executions.data[0] if executions.data else None
            }

            if userinterface_name not in testcases_by_ui:
                testcases_by_ui[userinterface_name] = []
            testcases_by_ui[userinterface_name].append(testcase_data)
        
        # Get execution stats for scripts
        script_coverage = []
        for sc in scripts.data:
            executions = supabase.table('script_results')\
                .select('success, started_at')\
                .eq('script_name', sc['script_name'])\
                .eq('team_id', team_id)\
                .order('started_at', desc=True)\
                .limit(10)\
                .execute()
            
            pass_count = sum(1 for e in executions.data if e.get('success'))
            execution_count = len(executions.data)
            total_passes += pass_count
            total_executions += execution_count
            
            script_coverage.append({
                'script_name': sc['script_name'],
                'coverage_type': sc['coverage_type'],
                'execution_count': execution_count,
                'pass_count': pass_count,
                'pass_rate': (pass_count / execution_count) if execution_count > 0 else 0,
                'last_execution': executions.data[0] if executions.data else None
            })
        
        total_testcases = sum(len(tcs) for tcs in testcases_by_ui.values())
        
        return {
            'requirement': requirement,
            'testcases_by_ui': testcases_by_ui,
            'scripts': script_coverage,
            'coverage_summary': {
                'total_testcases': total_testcases,
                'total_scripts': len(script_coverage),
                'total_coverage': total_testcases + len(script_coverage),
                'pass_rate': (total_passes / total_executions) if total_executions > 0 else 0,
                'execution_count': total_executions
            }
        }
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting requirement coverage: {e}")
        return {}


def get_coverage_summary(team_id: str, category: str = None, priority: str = None) -> Dict[str, Any]:
    """Get coverage summary across all requirements."""
    supabase = get_supabase()
    if not supabase:
        return {}
    
    try:
        # Use the coverage summary view
        query = supabase.table('requirements_coverage_summary')\
            .select('*')\
            .eq('team_id', team_id)
        
        if category:
            query = query.eq('category', category)
        if priority:
            query = query.eq('priority', priority)
        
        result = query.execute()
        
        # Group by category
        by_category = {}
        total_requirements = 0
        total_covered = 0
        
        for req in result.data:
            cat = req['category'] or 'uncategorized'
            if cat not in by_category:
                by_category[cat] = {
                    'total': 0,
                    'covered': 0,
                    'testcase_count': 0,
                    'script_count': 0
                }
            
            by_category[cat]['total'] += 1
            total_requirements += 1
            
            if req['total_coverage_count'] > 0:
                by_category[cat]['covered'] += 1
                total_covered += 1
            
            by_category[cat]['testcase_count'] += req['testcase_count']
            by_category[cat]['script_count'] += req['script_count']
        
        # Calculate coverage percentages
        for cat in by_category:
            total = by_category[cat]['total']
            covered = by_category[cat]['covered']
            by_category[cat]['coverage_percentage'] = (covered / total * 100) if total > 0 else 0
        
        return {
            'by_category': by_category,
            'total_requirements': total_requirements,
            'total_covered': total_covered,
            'coverage_percentage': (total_covered / total_requirements * 100) if total_requirements > 0 else 0
        }
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting coverage summary: {e}")
        return {}


def get_uncovered_requirements(team_id: str) -> List[Dict[str, Any]]:
    """Get all active requirements without coverage."""
    supabase = get_supabase()
    if not supabase:
        return []
    
    try:
        # Use the uncovered requirements view
        result = supabase.table('uncovered_requirements')\
            .select('*')\
            .eq('team_id', team_id)\
            .order('priority')\
            .order('category')\
            .execute()
        
        uncovered = []
        for req in result.data:
            req['requirement_id'] = str(req['requirement_id'])
            req['team_id'] = str(req['team_id'])
            uncovered.append(req)
        
        return uncovered
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting uncovered requirements: {e}")
        return []


def get_available_testcases_for_requirement(
    team_id: str, 
    requirement_id: str, 
    userinterface_name: str = None
) -> List[Dict[str, Any]]:
    """
    Get all testcases with their link status for a requirement.
    Used by the link picker modal.
    
    Args:
        team_id: Team ID
        requirement_id: Requirement ID to check linkage against
        userinterface_name: Optional filter by UI
    
    Returns:
        List of testcases with 'is_linked' flag
    """
    supabase = get_supabase()
    if not supabase:
        return []
    
    try:
        # Get all testcases for the team
        query = supabase.table('testcase_definitions')\
            .select('testcase_id, testcase_name, description, userinterface_name, created_at')\
            .eq('team_id', team_id)\
            .eq('is_active', True)
        
        if userinterface_name:
            query = query.eq('userinterface_name', userinterface_name)
        
        query = query.order('testcase_name')
        testcases_result = query.execute()
        
        # Get currently linked testcases
        linked_result = supabase.table('testcase_requirements')\
            .select('testcase_id')\
            .eq('requirement_id', requirement_id)\
            .execute()
        
        linked_ids = {row['testcase_id'] for row in linked_result.data}
        
        # Mark testcases as linked or not
        testcases = []
        for tc in testcases_result.data:
            tc_id = str(tc['testcase_id'])
            testcases.append({
                'testcase_id': tc_id,
                'testcase_name': tc['testcase_name'],
                'description': tc.get('description'),
                'userinterface_name': tc.get('userinterface_name'),
                'is_linked': tc_id in linked_ids,
                'created_at': tc.get('created_at')
            })
        
        return testcases
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting available testcases: {e}")
        return []


def get_requirement_coverage_counts(team_id: str) -> Dict[str, Dict[str, int]]:
    """
    Get test coverage counts for all requirements.
    Used for showing coverage badges in the requirements list.
    
    Returns:
        {
            'requirement_id': {
                'testcase_count': 3,
                'script_count': 1,
                'total_count': 4
            }
        }
    """
    supabase = get_supabase()
    if not supabase:
        return {}
    
    try:
        # Get all requirements for team
        reqs_result = supabase.table('requirements')\
            .select('requirement_id')\
            .eq('team_id', team_id)\
            .eq('status', 'active')\
            .execute()
        
        coverage_counts = {}
        
        for req in reqs_result.data:
            req_id = str(req['requirement_id'])
            
            # Count linked testcases
            tc_count = supabase.table('testcase_requirements')\
                .select('testcase_id', count='exact')\
                .eq('requirement_id', req_id)\
                .execute()
            
            # Count linked scripts
            sc_count = supabase.table('script_requirements')\
                .select('script_name', count='exact')\
                .eq('requirement_id', req_id)\
                .execute()
            
            testcase_count = tc_count.count or 0
            script_count = sc_count.count or 0
            
            coverage_counts[req_id] = {
                'testcase_count': testcase_count,
                'script_count': script_count,
                'total_count': testcase_count + script_count
            }
        
        return coverage_counts
        
    except Exception as e:
        print(f"[@requirements_db] ERROR getting coverage counts: {e}")
        return {}

