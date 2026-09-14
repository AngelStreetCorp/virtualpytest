"""
Verification Service

Handles verification-related business logic that was previously in routes.
This service layer separates business logic from HTTP handling.
"""

from typing import Dict, Any, List, Optional

class VerificationService:
    """Service for handling verification business logic"""
    
    def get_verification_types(self, device_model: str = 'android_mobile') -> Dict[str, Any]:
        """
        Get available verification types for a device model.
        
        Args:
            device_model: The device model to get verifications for
            
        Returns:
            Dict containing success status and verification types
        """
        try:
            # Business logic for verification types
            verifications = [
                {
                    'id': 'waitForElementToAppear',
                    'name': 'waitForElementToAppear',
                    'command': 'waitForElementToAppear',
                    'device_model': device_model,
                    'verification_type': 'adb',
                    'params': {
                        'search_term': '',
                        'timeout': 10,
                        'check_interval': 1
                    }
                },
                {
                    'id': 'image_verification',
                    'name': 'image_verification',
                    'command': 'image_verification',
                    'device_model': device_model,
                    'verification_type': 'image',
                    'params': {
                        'reference_image': '',
                        'confidence_threshold': 0.8
                    }
                }
            ]
            
            return {
                'success': True,
                'verifications': verifications
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to get verification types: {str(e)}'
            }
    
    def get_all_references(self, team_id: str, userinterface_name: str = None, device_model: str = None, bust_cache: bool = False) -> Dict[str, Any]:
        """
        Get all reference images/data for a team.

        OPTIMAL: Pass userinterface_name directly (e.g., from NavigationEditor) - most efficient.
        FALLBACK: Pass device_model to filter compatible userinterfaces - less efficient.

        Args:
            team_id: The team ID to get references for
            userinterface_name: Optional specific userinterface name (most efficient - direct DB filter)
            device_model: Optional device model to filter compatible userinterfaces (fallback)
            bust_cache: Skip the process-local references cache and read fresh from
                the DB. The editor passes this on a reload-after-save because the
                write happened on the backend_host and never invalidated this
                (backend_server) process's cache. See get_references docstring.

        Returns:
            Dict containing success status and references
        """
        try:
            if not team_id:
                return {
                    'success': False,
                    'error': 'team_id is required',
                    'status_code': 400
                }
            
            from shared.src.lib.database.verifications_references_db import get_references
            from shared.src.lib.database.userinterface_db import get_all_userinterfaces

            # OPTIMAL PATH: Direct userinterface name filter (e.g., from NavigationEditor).
            # We additionally pull in shared refs whose origin UI shares at least one
            # entry in models[] with the active UI.
            if userinterface_name:
                print(f'[VerificationService] ✅ Direct filter by userinterface: {userinterface_name}')

                team_uis = get_all_userinterfaces(team_id) or []
                active_ui = next((ui for ui in team_uis if ui.get('name') == userinterface_name), None)
                active_models = set(active_ui.get('models', []) if active_ui else [])
                compatible_ui_names = [
                    ui['name'] for ui in team_uis
                    if active_models.intersection(set(ui.get('models', []) or []))
                ] if active_models else [userinterface_name]
                # Always include the active UI so its own shared refs are visible too.
                if userinterface_name not in compatible_ui_names:
                    compatible_ui_names.append(userinterface_name)
                print(f'[VerificationService] Shared-ref compatibility set for {userinterface_name} (models={sorted(active_models)}): {compatible_ui_names}')

                result = get_references(
                    team_id=team_id,
                    userinterface_names=[userinterface_name],
                    compatible_ui_names=compatible_ui_names,
                    bust_cache=bust_cache,
                )

                if not result['success']:
                    print(f'[VerificationService] Error getting references: {result.get("error")}')
                    return {
                        'success': False,
                        'error': result.get('error', 'Failed to get references'),
                        'status_code': 500
                    }

                print(f'[VerificationService] Found {len(result["references"])} references for userinterface: {userinterface_name}')
                return {
                    'success': True,
                    'references': result['references']
                }

            # FALLBACK PATH: device_model filter requires resolving compatible userinterfaces
            if device_model:
                userinterfaces = get_all_userinterfaces(team_id)

                if not userinterfaces:
                    print(f'[VerificationService] No userinterfaces found for team')
                    return {
                        'success': True,
                        'references': []
                    }

                compatible_uis = [
                    ui for ui in userinterfaces
                    if device_model in ui.get('models', [])
                ]
                print(f'[VerificationService] Filtered {len(userinterfaces)} userinterfaces to {len(compatible_uis)} compatible with device_model: {device_model}')

                if not compatible_uis:
                    print(f'[VerificationService] No compatible userinterfaces found')
                    return {
                        'success': True,
                        'references': []
                    }

                valid_ui_names = [ui['name'] for ui in compatible_uis]
                print(f'[VerificationService] Valid userinterface names: {valid_ui_names}')

                # In the device_model path every compatible UI is also a candidate for
                # shared-ref visibility — pass the same list as compatible_ui_names so
                # shared refs from any of them get surfaced.
                result = get_references(
                    team_id=team_id,
                    userinterface_names=valid_ui_names,
                    compatible_ui_names=valid_ui_names,
                    bust_cache=bust_cache,
                )
                
                if not result['success']:
                    print(f'[VerificationService] Error getting references: {result.get("error")}')
                    return {
                        'success': False,
                        'error': result.get('error', 'Failed to get references'),
                        'status_code': 500
                    }
                
                print(f'[VerificationService] Found {len(result["references"])} references for compatible userinterfaces')
                return {
                    'success': True,
                    'references': result['references']
                }
            
            # NO FILTER: Return all references for the team
            print(f'[VerificationService] ⚠️ No filter specified - getting all references for team')
            result = get_references(team_id=team_id, bust_cache=bust_cache)
            
            if not result['success']:
                print(f'[VerificationService] Error getting references: {result.get("error")}')
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to get references'),
                    'status_code': 500
                }
            
            print(f'[VerificationService] Found {len(result["references"])} references (no filter)')
            return {
                'success': True,
                'references': result['references']
            }
                
        except Exception as e:
            print(f'[VerificationService] ERROR: {e}')
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }

# Singleton instance
verification_service = VerificationService()
