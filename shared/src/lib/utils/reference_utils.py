"""
Reference utilities for resolving reference areas from database.

Centralized logic to avoid duplication across frontend and backend.
"""

from typing import Dict, Optional, Any

# (name, team_id) -> stable storage key. Resolved once per process; UI ids never change.
_ui_storage_key_cache: Dict[tuple, str] = {}


def reference_storage_key(userinterface_name: str, team_id: str) -> str:
    """Rename-stable key for reference storage paths and lookups.

    Returns the userinterface UUID `id` (which never changes on rename) when the
    name resolves to a registered userinterface; otherwise falls back to the name
    (orphan/test UIs, shared refs) so legacy rows keep working. Used by both the
    R2 path builders and the DB lookup so a userinterface rename is purely cosmetic.
    """
    if not userinterface_name or not team_id:
        return userinterface_name
    ck = (userinterface_name, team_id)
    cached = _ui_storage_key_cache.get(ck)
    if cached:
        return cached
    key = userinterface_name
    try:
        from shared.src.lib.database.userinterface_db import get_userinterface_by_name
        ui = get_userinterface_by_name(userinterface_name, team_id)
        if ui and ui.get('id'):
            key = ui['id']
    except Exception as e:
        print(f"[@reference_utils:reference_storage_key] resolve failed for "
              f"{userinterface_name}: {e} — falling back to name")
    _ui_storage_key_cache[ck] = key
    return key


def resolve_reference_area_backend(reference_name: str, userinterface_name: str, team_id: str) -> Optional[Dict[str, Any]]:
    """
    Resolve reference area from database (backend version).
    
    Args:
        reference_name: Name of the reference
        userinterface_name: User interface name (e.g., 'example_androidtv')
        team_id: Team ID (required)
        
    Returns:
        Dict with area coordinates or None if not found
    """
    try:
        if not team_id:
            print(f"[@reference_utils:resolve_reference_area_backend] ERROR: team_id is required")
            return None
            
        from shared.src.lib.database.verifications_references_db import get_references
        
        # Try exact name first
        names_to_try = [reference_name]
        
        # Add variations (handle _text suffix logic matching frontend)
        if reference_name.endswith('_text'):
            names_to_try.append(reference_name[:-5])  # Remove _text
        else:
            names_to_try.append(f"{reference_name}_text")  # Add _text
            
        print(f"[@reference_utils] Attempting to resolve reference with variations: {names_to_try}")
            
        # An image and a text reference can share the same name (e.g.
        # 'settings_system_standby_fast' captured both ways). Prefer the TEXT
        # row first: it carries the text-only fields (notably the learned
        # 'focus' accent), so the focus gate keeps working when a text twin
        # exists. Fall back to the IMAGE row when there is no text twin —
        # otherwise plain image-only references resolve to no area at all.
        for ref_type in ('reference_text', 'reference_image'):
            for name_variant in names_to_try:
                result = get_references(team_id, userinterface_name=userinterface_name,
                                        name=name_variant, reference_type=ref_type)
                if result.get('success') and result.get('references'):
                    references = result['references']
                    # Find exact match for this variant
                    reference_data = next((ref for ref in references if ref['name'] == name_variant), None)

                    if reference_data and reference_data.get('area'):
                        print(f"[@reference_utils] ✅ Resolved {ref_type} reference '{reference_name}' as '{name_variant}'")
                        return reference_data['area']

        print(f"[@reference_utils] ❌ Failed to resolve reference '{reference_name}' (tried: {names_to_try})")
        return None
        
    except Exception as e:
        print(f"[@reference_utils:resolve_reference_area_backend] Error: {e}")
        return None
