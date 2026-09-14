"""
Campaign Tools - Campaign management operations

Create, read, update, and delete test campaigns.
"""

import time
from typing import Dict, Any, List
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import APP_CONFIG, get_team_id

class CampaignTools:
    """Campaign management tools"""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()

    def list_campaigns(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all campaigns for a team. Team is automatically inferred from server configuration (TEAM_ID env var).

        Args:
            params: {}

        Returns:
            MCP-formatted response with list of campaigns
        """
        team_id = get_team_id()

        print(f"[@MCP:list_campaigns] Listing campaigns for team: {team_id}")

        result = self.api.get('/server/campaigns/getAllCampaigns', params={'team_id': team_id})

        if not result.get('success'):
            error_msg = result.get('error', 'Failed to list campaigns')
            return {"content": [{"type": "text", "text": f"❌ Failed to list campaigns: {error_msg}"}], "isError": True}

        campaigns = result.get('campaigns', [])
        count = len(campaigns)

        # Format response
        response_text = f"📋 Found {count} campaigns:\n\n"
        if campaigns:
            for campaign in campaigns:
                response_text += f"• **{campaign.get('campaign_name', 'Unnamed')}**\n"
                response_text += f"  ID: `{campaign.get('campaign_id', 'N/A')}`\n"
                if campaign.get('campaign_description'):
                    response_text += f"  Description: {campaign.get('campaign_description')}\n"
                response_text += "\n"
        else:
            response_text += "No campaigns found. Create your first campaign with create_campaign()."

        return {
            "content": [{"type": "text", "text": response_text}],
            "campaigns": campaigns
        }

    def get_campaign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get details of a specific campaign

        Args:
            params: {
                'campaign_name': str (REQUIRED) - Campaign name
            }

        Returns:
            MCP-formatted response with campaign details
        """
        campaign_name = params.get('campaign_name')
        team_id = get_team_id()

        if not campaign_name:
            return {"content": [{"type": "text", "text": "Error: campaign_name is required"}], "isError": True}

        # Look up campaign by name to get its ID
        print(f"[@MCP:get_campaign] Looking up campaign by name: {campaign_name}")

        list_result = self.list_campaigns({})

        if list_result.get('isError'):
            return {"content": [{"type": "text", "text": f"❌ Failed to lookup campaign: {list_result['content'][0]['text']}"}], "isError": True}

        # Find campaign by name
        campaigns = list_result.get('campaigns', [])
        matching_campaign = None
        for camp in campaigns:
            if camp.get('campaign_name') == campaign_name:
                matching_campaign = camp
                break

        if not matching_campaign:
            return {"content": [{"type": "text", "text": f"❌ Campaign '{campaign_name}' not found. Use list_campaigns() to see available campaigns."}], "isError": True}

        campaign_id = matching_campaign.get('campaign_id')
        print(f"[@MCP:get_campaign] Found campaign with ID: {campaign_id}")

        result = self.api.get(f'/server/campaigns/getCampaign/{campaign_id}', params={'team_id': team_id})

        if not result.get('success'):
            error_msg = result.get('error', 'Failed to get campaign')
            return {"content": [{"type": "text", "text": f"❌ Failed to get campaign: {error_msg}"}], "isError": True}

        campaign = result.get('campaign', {})

        # Format response
        response_text = f"📄 Campaign Details:\n\n"
        response_text += f"**Name:** {campaign.get('campaign_name', 'Unnamed')}\n"
        response_text += f"**ID:** `{campaign.get('campaign_id', 'N/A')}`\n"
        if campaign.get('campaign_description'):
            response_text += f"**Description:** {campaign.get('campaign_description')}\n"
        if campaign.get('userinterface_name'):
            response_text += f"**UI:** {campaign.get('userinterface_name')}\n"

        script_configs = campaign.get('script_configurations', [])
        if script_configs:
            response_text += f"\n**Scripts ({len(script_configs)}):**\n"
            for i, script in enumerate(script_configs, 1):
                script_name = script.get('script_name', 'Unnamed')
                parameters = script.get('parameters', '')
                response_text += f"  {i}. `{script_name}`"
                if parameters:
                    response_text += f" (params: {parameters})"
                response_text += "\n"

        execution_config = campaign.get('execution_config', {})
        if execution_config:
            response_text += f"\n**Execution Config:**\n"
            for key, value in execution_config.items():
                response_text += f"  • {key}: {value}\n"

        return {
            "content": [{"type": "text", "text": response_text}],
            "campaign": campaign
        }

    def create_campaign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new test campaign

        Args:
            params: {
                'campaign_name': str (REQUIRED) - Campaign name,
                'campaign_description': str (OPTIONAL) - Campaign description,
                'userinterface_name': str (OPTIONAL) - User interface name,
                'script_configurations': List[Dict] (REQUIRED) - List of scripts with parameters,
                'execution_config': Dict (OPTIONAL) - Execution configuration
            }

        Returns:
            MCP-formatted response with created campaign details
        """
        campaign_name = params.get('campaign_name')
        campaign_description = params.get('campaign_description', '')
        userinterface_name = params.get('userinterface_name', '')
        script_configurations = params.get('script_configurations', [])
        execution_config = params.get('execution_config', {})
        team_id = get_team_id()

        # Validate required parameters
        if not campaign_name:
            return {"content": [{"type": "text", "text": "Error: campaign_name is required"}], "isError": True}
        if not script_configurations:
            return {"content": [{"type": "text", "text": "Error: script_configurations is required (list of scripts to run)"}], "isError": True}

        # Check if campaign with this name already exists (avoid duplicates)
        print(f"[@MCP:create_campaign] Checking if campaign '{campaign_name}' already exists")
        list_result = self.list_campaigns({'team_id': team_id})

        if list_result.get('isError'):
            return {"content": [{"type": "text", "text": f"❌ Failed to check existing campaigns: {list_result['content'][0]['text']}"}], "isError": True}

        # Extract campaigns from the list response
        existing_campaigns = list_result.get('campaigns', [])
        for camp in existing_campaigns:
            if camp.get('campaign_name') == campaign_name:
                return {"content": [{"type": "text", "text": f"❌ Campaign '{campaign_name}' already exists. Use a different name or update the existing campaign with update_campaign()."}], "isError": True}

        print(f"[@MCP:create_campaign] Creating campaign: {campaign_name}")

        # Prepare campaign data
        campaign_data = {
            'name': campaign_name,
            'campaign_description': campaign_description,
            'userinterface_name': userinterface_name,
            'script_configurations': script_configurations,
            'execution_config': execution_config
        }

        result = self.api.post('/server/campaigns/createCampaign',
                              data=campaign_data,
                              params={'team_id': team_id})

        if not result.get('success'):
            error_msg = result.get('error', 'Failed to create campaign')
            return {"content": [{"type": "text", "text": f"❌ Failed to create campaign: {error_msg}"}], "isError": True}

        campaign = result.get('campaign', {})

        # Format response
        response_text = f"✅ Campaign created successfully!\n\n"
        response_text += f"**Name:** {campaign.get('campaign_name', campaign_name)}\n"
        response_text += f"**ID:** `{campaign.get('campaign_id', 'N/A')}`\n"
        if campaign.get('campaign_description'):
            response_text += f"**Description:** {campaign.get('campaign_description')}\n"

        script_configs = campaign.get('script_configurations', script_configurations)
        response_text += f"**Scripts:** {len(script_configs)} configured\n"

        return {"content": [{"type": "text", "text": response_text}]}

    def update_campaign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing campaign

        Args:
            params: {
                'campaign_name': str (REQUIRED) - Current campaign name to update,
                'new_campaign_name': str (OPTIONAL) - New campaign name,
                'campaign_description': str (OPTIONAL) - New campaign description,
                'userinterface_name': str (OPTIONAL) - New user interface name,
                'script_configurations': List[Dict] (OPTIONAL) - Updated script configurations,
                'execution_config': Dict (OPTIONAL) - Updated execution configuration
            }

        Returns:
            MCP-formatted response with updated campaign details
        """
        campaign_name = params.get('campaign_name')
        team_id = get_team_id()

        if not campaign_name:
            return {"content": [{"type": "text", "text": "Error: campaign_name is required"}], "isError": True}

        # Look up campaign by name to get its ID
        print(f"[@MCP:update_campaign] Looking up campaign by name: {campaign_name}")

        list_result = self.list_campaigns({})

        if list_result.get('isError'):
            return {"content": [{"type": "text", "text": f"❌ Failed to lookup campaign: {list_result['content'][0]['text']}"}], "isError": True}

        # Find campaign by name
        campaigns = list_result.get('campaigns', [])
        matching_campaign = None
        for camp in campaigns:
            if camp.get('campaign_name') == campaign_name:
                matching_campaign = camp
                break

        if not matching_campaign:
            return {"content": [{"type": "text", "text": f"❌ Campaign '{campaign_name}' not found. Use list_campaigns() to see available campaigns."}], "isError": True}

        campaign_id = matching_campaign.get('campaign_id')
        print(f"[@MCP:update_campaign] Found campaign with ID: {campaign_id}")

        print(f"[@MCP:update_campaign] Updating campaign: {campaign_id}")

        # Prepare update data (only include provided fields)
        update_data = {}
        field_mapping = {
            'new_campaign_name': 'campaign_name',
            'campaign_description': 'campaign_description',
            'userinterface_name': 'userinterface_name',
            'script_configurations': 'script_configurations',
            'execution_config': 'execution_config'
        }

        for param_field, api_field in field_mapping.items():
            if param_field in params:
                update_data[api_field] = params[param_field]

        if not update_data:
            return {"content": [{"type": "text", "text": "Error: At least one field to update must be provided"}], "isError": True}

        result = self.api.put(f'/server/campaigns/updateCampaign/{campaign_id}',
                             data=update_data,
                             params={'team_id': team_id})

        if not result.get('success'):
            error_msg = result.get('error', 'Failed to update campaign')
            return {"content": [{"type": "text", "text": f"❌ Failed to update campaign: {error_msg}"}], "isError": True}

        campaign = result.get('campaign', {})

        # Format response
        response_text = f"✅ Campaign updated successfully!\n\n"
        response_text += f"**Name:** {campaign.get('campaign_name', 'Unnamed')}\n"
        response_text += f"**ID:** `{campaign.get('campaign_id', campaign_id)}`\n"
        if campaign.get('campaign_description'):
            response_text += f"**Description:** {campaign.get('campaign_description')}\n"

        return {"content": [{"type": "text", "text": response_text}]}

    def delete_campaign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete a campaign

        Args:
            params: {
                'campaign_name': str (REQUIRED) - Campaign name
            }

        Returns:
            MCP-formatted response confirming deletion
        """
        campaign_name = params.get('campaign_name')
        team_id = get_team_id()

        if not campaign_name:
            return {"content": [{"type": "text", "text": "Error: campaign_name is required"}], "isError": True}

        # Look up campaign by name to get its ID
        print(f"[@MCP:delete_campaign] Looking up campaign by name: {campaign_name}")

        list_result = self.list_campaigns({})

        if list_result.get('isError'):
            return {"content": [{"type": "text", "text": f"❌ Failed to lookup campaign: {list_result['content'][0]['text']}"}], "isError": True}

        # Find campaign by name
        campaigns = list_result.get('campaigns', [])
        matching_campaign = None
        for camp in campaigns:
            if camp.get('campaign_name') == campaign_name:
                matching_campaign = camp
                break

        if not matching_campaign:
            return {"content": [{"type": "text", "text": f"❌ Campaign '{campaign_name}' not found. Use list_campaigns() to see available campaigns."}], "isError": True}

        campaign_id = matching_campaign.get('campaign_id')
        print(f"[@MCP:delete_campaign] Found campaign with ID: {campaign_id}")
        print(f"[@MCP:delete_campaign] Deleting campaign: {campaign_id}")

        result = self.api.delete(f'/server/campaigns/deleteCampaign/{campaign_id}',
                                params={'team_id': team_id})

        if not result.get('success'):
            error_msg = result.get('error', 'Failed to delete campaign')
            return {"content": [{"type": "text", "text": f"❌ Failed to delete campaign: {error_msg}"}], "isError": True}

        return {"content": [{"type": "text", "text": f"✅ Campaign `{campaign_id}` deleted successfully!"}]}

    def execute_campaign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a test campaign

        Args:
            params: {
                'campaign_name': str (REQUIRED) - Campaign name to execute,
                'host_name': str (REQUIRED) - Host name where devices are located,
                'device_name': str (REQUIRED) - Device name for execution
            }

        Returns:
            MCP-formatted response with execution status
        """
        campaign_name = params.get('campaign_name')
        host_name = params.get('host_name')
        device_name = params.get('device_name')
        # Use team_id from params if provided, otherwise fall back to env/config
        team_id = params.get('team_id') or get_team_id()

        # Validate required parameters
        if not campaign_name:
            return {"content": [{"type": "text", "text": "Error: campaign_name is required"}], "isError": True}
        if not host_name:
            return {"content": [{"type": "text", "text": "Error: host_name is required"}], "isError": True}
        if not device_name:
            return {"content": [{"type": "text", "text": "Error: device_name is required"}], "isError": True}

        # Look up campaign by name to get its ID
        print(f"[@MCP:execute_campaign] Looking up campaign by name: {campaign_name}")

        list_result = self.list_campaigns({'team_id': team_id})

        if list_result.get('isError'):
            return {"content": [{"type": "text", "text": f"❌ Failed to lookup campaign: {list_result['content'][0]['text']}"}], "isError": True}

        # Find campaign by name
        campaigns = list_result.get('campaigns', [])
        matching_campaign = None
        for camp in campaigns:
            if camp.get('campaign_name') == campaign_name:
                matching_campaign = camp
                break

        if not matching_campaign:
            return {"content": [{"type": "text", "text": f"❌ Campaign '{campaign_name}' not found. Use list_campaigns() to see available campaigns."}], "isError": True}

        campaign_id = matching_campaign.get('campaign_id')
        print(f"[@MCP:execute_campaign] Found campaign with ID: {campaign_id}")
        print(f"[@MCP:execute_campaign] Executing campaign: {campaign_id} on host: {host_name}")

        # First, get the campaign details to get the script configurations
        campaign_result = self.api.get(f'/server/campaigns/getCampaign/{campaign_id}', params={'team_id': team_id})

        if not campaign_result.get('success'):
            error_msg = campaign_result.get('error', 'Failed to get campaign details')
            return {"content": [{"type": "text", "text": f"❌ Failed to get campaign details: {error_msg}"}], "isError": True}

        campaign = campaign_result.get('campaign', {})

        # Prepare execution data
        execution_data = {
            'campaign_id': campaign_id,
            'name': campaign.get('campaign_name', f'Campaign_{campaign_id}'),
            'script_configurations': campaign.get('script_configurations', []),
            'host_name': host_name,
            'device_name': device_name,
            'userinterface_name': campaign.get('userinterface_name', ''),
            'execution_config': campaign.get('execution_config', {}),
            'team_id': team_id,  # Include team_id in body
        }

        # Execute the campaign
        result = self.api.post('/server/campaigns/execute', data=execution_data, params={'team_id': team_id})

        if not result.get('success'):
            error_msg = result.get('error', 'Failed to execute campaign')
            return {"content": [{"type": "text", "text": f"❌ Failed to execute campaign: {error_msg}"}], "isError": True}

        execution_id = result.get('execution_id', 'unknown')

        # Format response
        response_text = f"✅ Campaign execution started!\n\n"
        response_text += f"**Campaign:** {campaign.get('campaign_name', 'Unnamed')}\n"
        response_text += f"**Execution ID:** `{execution_id}`\n"
        response_text += f"**Host:** {host_name}\n"
        response_text += f"**Device:** {device_name}\n"

        script_configs = campaign.get('script_configurations', [])
        response_text += f"**Scripts to execute:** {len(script_configs)}\n"

        for i, script in enumerate(script_configs, 1):
            script_name = script.get('script_name', 'Unknown')
            parameters = script.get('parameters', '')
            response_text += f"  {i}. `{script_name}`"
            if parameters:
                response_text += f" ({parameters})"
            response_text += "\n"

        response_text += f"\n**Status:** Check execution status with execution ID: `{execution_id}`"

        return {"content": [{"type": "text", "text": response_text}]}