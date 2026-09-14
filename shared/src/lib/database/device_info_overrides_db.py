"""
Device Info Overrides Database Operations

Manual, per-device value corrections for OCR-extracted device info
(script_results.metadata->'info'). Corrections are applied non-destructively at
read time by the device_info_corrected / device_info_key_status views — raw OCR
in script_results is never mutated.

See setup/db/schema/035_device_info_overrides.sql and docs/agent/.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


# info_source ('device' | 'gateway') selects which info family an operation acts
# on. Device info (OCR, metadata->'info') and gateway info (gw_info, flat metadata)
# share the same override table, distinguished by this column. The per-key status
# views are split per source.
_KEY_STATUS_VIEW = {
    'device': 'device_info_key_status',
    'gateway': 'gateway_info_key_status',
}


def get_key_status(team_id: str, device_name: Optional[str] = None,
                   host_name: Optional[str] = None,
                   info_source: str = 'device') -> List[Dict]:
    """Per-key correction status for the latest scan of each device.

    Reads the {device,gateway}_info_key_status view (raw value, override,
    effective value, stale flag). Optionally narrowed to one device.
    """
    supabase = get_supabase()
    try:
        view = _KEY_STATUS_VIEW.get(info_source, 'device_info_key_status')
        query = supabase.table(view).select('*').eq('team_id', team_id)
        if device_name:
            query = query.eq('device_name', device_name)
        if host_name:
            query = query.eq('host_name', host_name)
        result = query.order('device_name').order('info_key').execute()
        return result.data or []
    except Exception as e:
        print(f"[@db:device_info_overrides:get_key_status] Error: {e}")
        return []


def _get_corrected_map(team_id: str, view: str, log_label: str) -> Dict[tuple, Dict]:
    """Latest corrected info per device, keyed by (device_name, host_name).

    Each value is `{'info': <corrected info object>, 'report_url': <html report
    URL of the scan the info came from>, 'scanned_at': <its started_at>,
    'final_screenshot_url' / 'initial_screenshot_url' / 'video_url': <the scan
    report's presigned R2 artifacts>}`, so the caller can show the values, a link
    back to the scan that produced them, and the captured final-state image. Used
    to embed info into the getAllHosts payload so the frontend tooltip / editor
    needs no separate fetch. Best-effort: returns {} on error.
    """
    supabase = get_supabase()
    try:
        result = supabase.table(view)\
            .select('device_name,host_name,info_corrected,html_report_r2_url,started_at,'
                    'initial_screenshot_url,final_screenshot_url,video_url')\
            .eq('team_id', team_id).execute()
        return {
            (r['device_name'], r['host_name']): {
                'info': r.get('info_corrected') or {},
                'report_url': r.get('html_report_r2_url'),
                'scanned_at': r.get('started_at'),
                'initial_screenshot_url': r.get('initial_screenshot_url'),
                'final_screenshot_url': r.get('final_screenshot_url'),
                'video_url': r.get('video_url'),
            }
            for r in (result.data or [])
        }
    except Exception as e:
        print(f"[@db:device_info_overrides:{log_label}] Error: {e}")
        return {}


def get_corrected_info_map(team_id: str) -> Dict[tuple, Dict]:
    """Latest corrected DEVICE info per device (OCR, metadata->'info')."""
    return _get_corrected_map(team_id, 'device_info_corrected', 'get_corrected_info_map')


def get_corrected_gateway_map(team_id: str) -> Dict[tuple, Dict]:
    """Latest corrected GATEWAY info per device (gw_info, flat metadata)."""
    return _get_corrected_map(team_id, 'gateway_info_corrected', 'get_corrected_gateway_map')


def upsert_override(team_id: str, device_name: str, host_name: str,
                    userinterface_name: Optional[str], info_key: str,
                    corrected_value: str, raw_value_at_edit: Optional[str] = None,
                    note: Optional[str] = None, updated_by: Optional[str] = None,
                    info_source: str = 'device') -> Optional[Dict]:
    """Create or update a per-key override (unique on device+host+ui+source+key)."""
    supabase = get_supabase()
    try:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            'team_id': team_id,
            'device_name': device_name,
            'host_name': host_name,
            'userinterface_name': userinterface_name or '',
            'info_source': info_source,
            'info_key': info_key,
            'corrected_value': corrected_value,
            'raw_value_at_edit': raw_value_at_edit,
            'note': note,
            'updated_by': updated_by,
            'updated_at': now,
        }
        result = supabase.table('device_info_overrides').upsert(
            row,
            on_conflict='team_id,device_name,host_name,userinterface_name,info_source,info_key'
        ).execute()
        if result.data:
            print(f"[@db:device_info_overrides:upsert_override] {device_name}/{info_key} = {corrected_value!r}")
            return result.data[0]
        return None
    except Exception as e:
        print(f"[@db:device_info_overrides:upsert_override] Error: {e}")
        return None


def delete_override(team_id: str, device_name: str, host_name: str,
                    userinterface_name: Optional[str], info_key: str,
                    info_source: str = 'device') -> bool:
    """Remove an override; the corrected views fall back to the raw value."""
    supabase = get_supabase()
    try:
        result = supabase.table('device_info_overrides').delete()\
            .eq('team_id', team_id)\
            .eq('device_name', device_name)\
            .eq('host_name', host_name)\
            .eq('userinterface_name', userinterface_name or '')\
            .eq('info_source', info_source)\
            .eq('info_key', info_key)\
            .execute()
        print(f"[@db:device_info_overrides:delete_override] {device_name}/{info_key}")
        return bool(result.data)
    except Exception as e:
        print(f"[@db:device_info_overrides:delete_override] Error: {e}")
        return False
