"""
Folder and Tag Management - Helper Functions
Supports unified test organization for scripts and testcases
User-controlled: select existing or type new folder/tag on save
"""

import random
from typing import Dict, List, Optional, Any
from shared.src.lib.utils.supabase_utils import get_supabase_client

# Fixed Material Design color palette for tags
TAG_COLORS = [
    '#f44336',  # Red
    '#e91e63',  # Pink
    '#9c27b0',  # Purple
    '#673ab7',  # Deep Purple
    '#3f51b5',  # Indigo
    '#2196f3',  # Blue
    '#00bcd4',  # Cyan
    '#009688',  # Teal
    '#4caf50',  # Green
    '#8bc34a',  # Light Green
    '#ff9800',  # Orange
    '#ff5722',  # Deep Orange
]


def get_or_create_folder(name: str) -> int:
    """
    Get existing folder by name or create new one.
    Root folder is always ID 0.
    
    Args:
        name: Folder name (from user selection or typed input)
    
    Returns:
        folder_id (integer)
    """
    supabase = get_supabase_client()
    if not supabase:
        print("[@folder_tag] ERROR: Failed to get Supabase client")
        return 0  # Default to root
    
    try:
        # Root folder special case
        if not name or name.strip() in ['', '(Root)']:
            return 0
        
        name = name.strip()
        
        # Check if folder exists
        result = supabase.table('folders')\
            .select('folder_id')\
            .eq('name', name)\
            .execute()
        
        if result.data and len(result.data) > 0:
            folder_id = result.data[0]['folder_id']
            print(f"[@folder_tag] Found existing folder: {name} (ID: {folder_id})")
            return folder_id
        
        # Create new folder
        insert_result = supabase.table('folders')\
            .insert({'name': name})\
            .execute()
        
        if insert_result.data and len(insert_result.data) > 0:
            folder_id = insert_result.data[0]['folder_id']
            print(f"[@folder_tag] Created new folder: {name} (ID: {folder_id})")
            return folder_id
        else:
            print(f"[@folder_tag] ERROR: Failed to create folder: {name}")
            return 0
            
    except Exception as e:
        print(f"[@folder_tag] ERROR in get_or_create_folder: {e}")
        return 0  # Default to root on error


def get_or_create_tag(name: str) -> Optional[Dict[str, Any]]:
    """
    Get existing tag by name or create new one with random color.
    Tag names are stored lowercase for consistency.
    
    Args:
        name: Tag name (from user selection or typed input)
    
    Returns:
        Tag dict with {tag_id, name, color} or None on error
    """
    supabase = get_supabase_client()
    if not supabase:
        print("[@folder_tag] ERROR: Failed to get Supabase client")
        return None
    
    try:
        name = name.strip().lower()
        
        if not name:
            print("[@folder_tag] WARNING: Empty tag name")
            return None
        
        # Check if tag exists
        result = supabase.table('tags')\
            .select('*')\
            .eq('name', name)\
            .execute()
        
        if result.data and len(result.data) > 0:
            tag = result.data[0]
            print(f"[@folder_tag] Found existing tag: {name} (ID: {tag['tag_id']}, Color: {tag['color']})")
            return tag
        
        # Create new tag with random color from palette
        color = random.choice(TAG_COLORS)
        
        insert_result = supabase.table('tags')\
            .insert({'name': name, 'color': color})\
            .execute()
        
        if insert_result.data and len(insert_result.data) > 0:
            tag = insert_result.data[0]
            print(f"[@folder_tag] Created new tag: {name} (ID: {tag['tag_id']}, Color: {color})")
            return tag
        else:
            print(f"[@folder_tag] ERROR: Failed to create tag: {name}")
            return None
            
    except Exception as e:
        print(f"[@folder_tag] ERROR in get_or_create_tag: {e}")
        return None


def set_executable_tags(executable_type: str, executable_id: str, tag_names: List[str]) -> bool:
    """
    Set tags for an executable (script or testcase).
    Replaces existing tags with new set.
    
    Args:
        executable_type: 'script' or 'testcase'
        executable_id: script name or testcase_id
        tag_names: List of tag names to assign
    
    Returns:
        True on success, False on failure
    """
    supabase = get_supabase_client()
    if not supabase:
        print("[@folder_tag] ERROR: Failed to get Supabase client")
        return False
    
    try:
        # Delete existing tags for this executable
        supabase.table('executable_tags')\
            .delete()\
            .eq('executable_type', executable_type)\
            .eq('executable_id', executable_id)\
            .execute()
        
        # Get or create tags and insert mappings
        for tag_name in tag_names:
            tag = get_or_create_tag(tag_name)
            if tag:
                supabase.table('executable_tags')\
                    .insert({
                        'executable_type': executable_type,
                        'executable_id': executable_id,
                        'tag_id': tag['tag_id']
                    })\
                    .execute()
        
        print(f"[@folder_tag] Set tags for {executable_type}:{executable_id} - {len(tag_names)} tags")
        return True
        
    except Exception as e:
        print(f"[@folder_tag] ERROR in set_executable_tags: {e}")
        return False


def get_executable_tags(executable_type: str, executable_id: str) -> List[Dict[str, Any]]:
    """
    Get all tags for an executable.
    
    Args:
        executable_type: 'script' or 'testcase'
        executable_id: script name or testcase_id
    
    Returns:
        List of tag dicts [{tag_id, name, color}, ...]
    """
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        # Join executable_tags with tags to get full tag info
        result = supabase.table('executable_tags')\
            .select('tag_id, tags(name, color)')\
            .eq('executable_type', executable_type)\
            .eq('executable_id', executable_id)\
            .execute()
        
        if result.data:
            tags = []
            for row in result.data:
                if row.get('tags'):
                    tags.append({
                        'tag_id': row['tag_id'],
                        'name': row['tags']['name'],
                        'color': row['tags']['color']
                    })
            return tags
        
        return []
        
    except Exception as e:
        print(f"[@folder_tag] ERROR in get_executable_tags: {e}")
        return []


def get_executable_tags_bulk(
    executable_type: str,
    executable_ids: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch tags for many executables in a single query.

    Returns mapping {executable_id: [{tag_id, name, color}, ...]} with an entry
    for every requested id (empty list if the executable has no tags).
    """
    tags_by_id: Dict[str, List[Dict[str, Any]]] = {eid: [] for eid in executable_ids}
    if not executable_ids:
        return tags_by_id

    supabase = get_supabase_client()
    if not supabase:
        return tags_by_id

    try:
        result = supabase.table('executable_tags')\
            .select('executable_id, tag_id, tags(name, color)')\
            .eq('executable_type', executable_type)\
            .in_('executable_id', executable_ids)\
            .execute()

        if result.data:
            for row in result.data:
                eid = row.get('executable_id')
                tag_payload = row.get('tags')
                if eid is None or not tag_payload:
                    continue
                tags_by_id.setdefault(eid, []).append({
                    'tag_id': row['tag_id'],
                    'name': tag_payload['name'],
                    'color': tag_payload['color'],
                })

        return tags_by_id

    except Exception as e:
        print(f"[@folder_tag] ERROR in get_executable_tags_bulk: {e}")
        return tags_by_id


def list_all_folders() -> List[Dict[str, Any]]:
    """
    List all folders for dropdown selection.
    
    Returns:
        List of folder dicts [{folder_id, name}, ...]
    """
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        result = supabase.table('folders')\
            .select('folder_id, name')\
            .order('name')\
            .execute()
        
        return result.data if result.data else []
        
    except Exception as e:
        print(f"[@folder_tag] ERROR in list_all_folders: {e}")
        return []


def list_all_tags() -> List[Dict[str, Any]]:
    """
    List all tags for dropdown selection and filtering.
    
    Returns:
        List of tag dicts [{tag_id, name, color}, ...]
    """
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        result = supabase.table('tags')\
            .select('tag_id, name, color')\
            .order('name')\
            .execute()
        
        return result.data if result.data else []
        
    except Exception as e:
        print(f"[@folder_tag] ERROR in list_all_tags: {e}")
        return []

