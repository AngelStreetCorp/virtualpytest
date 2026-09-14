"""
Device Service

Handles device management business logic.
Queries device_flags table which contains devices auto-registered from hosts.
"""

from typing import Dict, Any, List, Optional
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.utils.app_utils import check_supabase


class DeviceService:
    """Service for handling device management business logic"""
    
    def get_all_devices(self, team_id: str = None) -> Dict[str, Any]:
        """Get all devices from device_flags table"""
        try:
            print(f"[DeviceService] Getting all devices")
            
            # Check if Supabase is available
            supabase_error = check_supabase()
            if supabase_error:
                return {
                    'success': False,
                    'error': f'Database not available: {supabase_error}',
                    'status_code': 503
                }
            
            supabase = get_supabase_client()
            result = supabase.table('device_flags').select('*').execute()
            
            devices = result.data or []
            print(f"[DeviceService] Found {len(devices)} devices")
            
            return {
                'success': True,
                'devices': devices,
                'count': len(devices)
            }
            
        except Exception as e:
            print(f"[DeviceService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def get_device(self, device_id: str, host_name: str = None) -> Dict[str, Any]:
        """Get a specific device from device_flags table"""
        try:
            if not device_id:
                return {
                    'success': False,
                    'error': 'device_id is required',
                    'status_code': 400
                }
            
            print(f"[DeviceService] Getting device: {device_id}")
            
            supabase = get_supabase_client()
            query = supabase.table('device_flags').select('*').eq('device_id', device_id)
            
            if host_name:
                query = query.eq('host_name', host_name)
            
            result = query.execute()
            
            if result.data and len(result.data) > 0:
                return {
                    'success': True,
                    'device': result.data[0]
                }
            else:
                return {
                    'success': False,
                    'error': 'Device not found',
                    'status_code': 404
                }
                
        except Exception as e:
            print(f"[DeviceService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def save_device(self, device_data: Dict[str, Any], team_id: str = None) -> Dict[str, Any]:
        """Create or update a device in device_flags table"""
        try:
            if not device_data:
                return {
                    'success': False,
                    'error': 'device_data is required',
                    'status_code': 400
                }
            
            host_name = device_data.get('host_name')
            device_id = device_data.get('device_id')
            device_name = device_data.get('device_name', device_id)
            flags = device_data.get('flags', [])
            
            if not host_name or not device_id:
                return {
                    'success': False,
                    'error': 'host_name and device_id are required',
                    'status_code': 400
                }
            
            print(f"[DeviceService] Saving device: {host_name}/{device_id}")
            
            supabase = get_supabase_client()
            
            # Upsert device
            result = supabase.table('device_flags').upsert({
                'host_name': host_name,
                'device_id': device_id,
                'device_name': device_name,
                'flags': flags
            }, on_conflict='host_name,device_id').execute()
            
            if result.data and len(result.data) > 0:
                return {
                    'success': True,
                    'device': result.data[0],
                    'message': 'Device saved successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to save device',
                    'status_code': 500
                }
                
        except Exception as e:
            print(f"[DeviceService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def delete_device(self, device_id: str, host_name: str = None) -> Dict[str, Any]:
        """Delete a device from device_flags table"""
        try:
            if not device_id:
                return {
                    'success': False,
                    'error': 'device_id is required',
                    'status_code': 400
                }
            
            print(f"[DeviceService] Deleting device: {device_id}")
            
            supabase = get_supabase_client()
            query = supabase.table('device_flags').delete().eq('device_id', device_id)
            
            if host_name:
                query = query.eq('host_name', host_name)
            
            result = query.execute()
            
            if result.data and len(result.data) > 0:
                return {
                    'success': True,
                    'message': 'Device deleted successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Device not found',
                    'status_code': 404
                }
                
        except Exception as e:
            print(f"[DeviceService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }


# Singleton instance
device_service = DeviceService()
