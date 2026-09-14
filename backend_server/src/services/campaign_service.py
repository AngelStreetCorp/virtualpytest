"""
Campaign Service

Handles campaign management business logic that was previously in routes.
This service manages campaign CRUD operations and related functionality.
"""

from typing import Dict, Any, List, Optional
from shared.src.lib.database.campaign_executions_db import get_campaign_results
from shared.src.lib.database.campaign_db import (
    create_campaign,
    get_campaign,
    get_campaign_by_name,
    update_campaign,
    delete_campaign,
    list_campaigns,
    get_campaign_execution_history,
    validate_campaign_config,
    get_campaign_history,
    restore_campaign_from_history,
)
from shared.src.lib.database.library_visibility_db import list_hidden_library_keys
from shared.src.lib.utils.app_utils import check_supabase, get_team_id

class CampaignService:
    """Service for handling campaign management business logic"""
    
    def get_all_campaigns(
        self,
        team_id: str,
        user_agent: str = None,
        referer: str = None,
        include_hidden: bool = False,
    ) -> Dict[str, Any]:
        """Get all campaigns for a team"""
        try:
            # Log caller information (moved from route)
            print(f"[CampaignService:get_all_campaigns] 🔍 CALLER INFO:")
            print(f"  - User-Agent: {user_agent or 'Unknown'}")
            print(f"  - Referer: {referer or 'Unknown'}")
            print(f"  - Team ID: {team_id}")

            if not team_id:
                return {
                    'success': False,
                    'error': 'team_id is required',
                    'status_code': 400
                }

            print(f"[CampaignService] Getting all campaigns for team: {team_id}")

            # Check if Supabase is available
            supabase_error = check_supabase()
            if supabase_error:
                return {
                    'success': False,
                    'error': f'Database not available: {supabase_error}',
                    'status_code': 503
                }

            # Business logic: Get campaigns from database
            campaigns = list_campaigns(team_id, include_config=False)
            if not include_hidden:
                hidden_campaign_ids = list_hidden_library_keys(team_id, 'campaign')
                campaigns = [
                    campaign for campaign in campaigns
                    if campaign.get('campaign_id') not in hidden_campaign_ids
                ]

            print(f"[CampaignService] Found {len(campaigns)} campaigns")

            return {
                'success': True,
                'campaigns': campaigns
            }

        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def get_campaign(self, campaign_id: str, team_id: str) -> Dict[str, Any]:
        """Get a specific campaign"""
        try:
            if not campaign_id or not team_id:
                return {
                    'success': False,
                    'error': 'campaign_id and team_id are required',
                    'status_code': 400
                }

            print(f"[CampaignService] Getting campaign: {campaign_id}")

            # Business logic: Get campaign from database
            campaign = get_campaign(campaign_id, team_id)

            if campaign:
                return {
                    'success': True,
                    'campaign': campaign
                }
            else:
                return {
                    'success': False,
                    'error': 'Campaign not found',
                    'status_code': 404
                }

        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def create_campaign(self, campaign_data: Dict[str, Any], team_id: str) -> Dict[str, Any]:
        """Create a new campaign"""
        try:
            if not campaign_data or not team_id:
                return {
                    'success': False,
                    'error': 'campaign_data and team_id are required',
                    'status_code': 400
                }

            campaign_name = campaign_data.get('name') or campaign_data.get('campaign_name')
            if not campaign_name:
                return {
                    'success': False,
                    'error': 'Campaign name is required',
                    'status_code': 400
                }

            print(f"[CampaignService] Creating campaign: {campaign_name}")

            # 🛡️ VALIDATION: Validate script configurations before saving
            script_configurations = campaign_data.get('script_configurations', [])
            execution_config = campaign_data.get('execution_config', {})
            if script_configurations:
                print(f"[CampaignService] 🛡️ Validating campaign scripts...")
                validation_result = validate_campaign_config(script_configurations, team_id, execution_config)

                if not validation_result['success']:
                    errors = validation_result.get('errors', [])
                    print(f"[CampaignService] ❌ Validation FAILED - cannot create campaign")
                    for error in errors:
                        print(f"[CampaignService]   - {error}")
                    return {
                        'success': False,
                        'error': 'Validation failed: ' + ', '.join(errors),
                        'status_code': 400
                    }

                warnings = validation_result.get('warnings', [])
                if warnings:
                    print(f"[CampaignService] ⚠️  Validation passed with warnings:")
                    for warning in warnings:
                        print(f"[CampaignService]   - {warning}")

            # Business logic: Create campaign in database
            result = create_campaign(
                team_id=team_id,
                campaign_name=campaign_name,
                description=campaign_data.get('description') or campaign_data.get('campaign_description'),
                userinterface_name=campaign_data.get('userinterface_name'),
                host_name=campaign_data.get('host_name'),
                device_name=campaign_data.get('device_name'),
                execution_config=campaign_data.get('execution_config', {}),
                script_configurations=script_configurations,
                created_by=campaign_data.get('created_by'),
                tags=campaign_data.get('tags')
            )

            if result and isinstance(result, dict) and result.get('success'):
                return {
                    'success': True,
                    'campaign': {
                        'campaign_id': result['campaign_id'],
                        'campaign_name': result['campaign_name'],
                        'description': campaign_data.get('description'),
                        'userinterface_name': campaign_data.get('userinterface_name'),
                        'host_name': campaign_data.get('host_name'),
                        'device_name': campaign_data.get('device_name'),
                        'execution_config': campaign_data.get('execution_config', {}),
                        'script_configurations': script_configurations,
                        'team_id': team_id
                    },
                    'message': 'Campaign created successfully'
                }
            elif result == 'DUPLICATE_NAME':
                return {
                    'success': False,
                    'error': f'Campaign name "{campaign_name}" already exists',
                    'status_code': 409
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to create campaign',
                    'status_code': 500
                }

        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def update_campaign(self, campaign_id: str, campaign_data: Dict[str, Any], team_id: str) -> Dict[str, Any]:
        """Update an existing campaign"""
        try:
            if not campaign_id or not campaign_data or not team_id:
                return {
                    'success': False,
                    'error': 'campaign_id, campaign_data, and team_id are required',
                    'status_code': 400
                }

            print(f"[CampaignService] Updating campaign: {campaign_id}")

            # 🛡️ VALIDATION: Validate script configurations if provided
            script_configurations = campaign_data.get('script_configurations')
            execution_config = campaign_data.get('execution_config')
            if script_configurations is not None:
                print(f"[CampaignService] 🛡️ Validating updated campaign scripts...")
                validation_result = validate_campaign_config(script_configurations, team_id, execution_config)

                if not validation_result['success']:
                    errors = validation_result.get('errors', [])
                    print(f"[CampaignService] ❌ Validation FAILED - cannot update campaign")
                    for error in errors:
                        print(f"[CampaignService]   - {error}")
                    return {
                        'success': False,
                        'error': 'Validation failed: ' + ', '.join(errors),
                        'status_code': 400
                    }

            # Business logic: Update campaign in database
            success = update_campaign(
                campaign_id=campaign_id,
                campaign_name=campaign_data.get('name') or campaign_data.get('campaign_name'),
                description=campaign_data.get('description'),
                userinterface_name=campaign_data.get('userinterface_name'),
                host_name=campaign_data.get('host_name'),
                device_name=campaign_data.get('device_name'),
                execution_config=campaign_data.get('execution_config'),
                script_configurations=script_configurations,
                team_id=team_id,
                tags=campaign_data.get('tags'),
                modified_by=campaign_data.get('modified_by') or campaign_data.get('created_by')
            )

            if success:
                # Get updated campaign data
                updated_campaign = get_campaign(campaign_id, team_id)
                return {
                    'success': True,
                    'campaign': updated_campaign,
                    'message': 'Campaign updated successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Campaign not found or failed to update',
                    'status_code': 404
                }

        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }

    def get_campaign_history(self, campaign_id: str, team_id: str) -> Dict[str, Any]:
        try:
            if not campaign_id or not team_id:
                return {
                    'success': False,
                    'error': 'campaign_id and team_id are required',
                    'status_code': 400
                }

            versions = get_campaign_history(campaign_id, team_id, limit=10)
            return {
                'success': True,
                'versions': versions,
            }
        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }

    def restore_campaign_version(self, campaign_id: str, version_number: int, team_id: str, restored_by: str = None) -> Dict[str, Any]:
        try:
            if not campaign_id or not team_id:
                return {
                    'success': False,
                    'error': 'campaign_id and team_id are required',
                    'status_code': 400
                }

            versions = get_campaign_history(campaign_id, team_id, limit=50)
            version_record = next((v for v in versions if v.get('version_number') == version_number), None)
            if not version_record:
                return {
                    'success': False,
                    'error': f'Campaign version {version_number} not found',
                    'status_code': 404
                }

            snapshot = version_record.get('campaign_data') or {}
            validation_result = validate_campaign_config(
                snapshot.get('script_configurations', []),
                team_id,
                snapshot.get('execution_config', {}),
            )
            if not validation_result.get('success'):
                return {
                    'success': False,
                    'error': 'Validation failed: ' + ', '.join(validation_result.get('errors', [])),
                    'status_code': 400
                }

            result = restore_campaign_from_history(campaign_id, version_number, team_id, restored_by=restored_by)
            if not result.get('success'):
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to restore campaign'),
                    'status_code': 500
                }

            return result
        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def delete_campaign(self, campaign_id: str, team_id: str) -> Dict[str, Any]:
        """Delete a campaign"""
        try:
            if not campaign_id or not team_id:
                return {
                    'success': False,
                    'error': 'campaign_id and team_id are required',
                    'status_code': 400
                }
            
            print(f"[CampaignService] Deleting campaign: {campaign_id}")
            
            # Business logic: Delete campaign from database
            success = delete_campaign(campaign_id, team_id)
            
            if success:
                return {
                    'success': True,
                    'message': 'Campaign deleted successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Campaign not found or failed to delete',
                    'status_code': 404
                }
                
        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }
    
    def get_campaign_results(self, campaign_id: str, team_id: str) -> Dict[str, Any]:
        """Get results for a campaign"""
        try:
            if not campaign_id or not team_id:
                return {
                    'success': False,
                    'error': 'campaign_id and team_id are required',
                    'status_code': 400
                }
            
            print(f"[CampaignService] Getting results for campaign: {campaign_id}")
            
            # Business logic: Get campaign results from database
            results = get_campaign_results(campaign_id)
            
            if results:
                return {
                    'success': True,
                    'results': results
                }
            else:
                return {
                    'success': False,
                    'error': 'No results found for campaign',
                    'status_code': 404
                }
                
        except Exception as e:
            print(f"[CampaignService] Exception: {e}")
            return {
                'success': False,
                'error': f'Service error: {str(e)}',
                'status_code': 500
            }

# Singleton instance
campaign_service = CampaignService()
