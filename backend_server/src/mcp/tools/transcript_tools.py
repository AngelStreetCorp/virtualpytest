"""
Transcript Tools - Audio transcript retrieval

Fetch and translate audio transcripts from devices.
"""

from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import APP_CONFIG, get_team_id


class TranscriptTools:
    """Audio transcript retrieval tools"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
    
    def get_transcript(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get audio transcript from device
        
        Fetches Whisper-generated transcripts with optional translation.
        
        Args:
            params: {
                'device_id': str (REQUIRED),
                'team_id': str (REQUIRED),
                'chunk_url': str (REQUIRED if no hour/chunk_index),
                'hour': int (REQUIRED if no chunk_url),
                'chunk_index': int (REQUIRED if no chunk_url),
                'target_language': str (OPTIONAL) - For translation (e.g., 'fr', 'es')
            }
            
        Returns:
            MCP-formatted response with transcript segments and timestamps
        """
        device_id = params.get('device_id')
        team_id = params.get('team_id', get_team_id())
        chunk_url = params.get('chunk_url')
        hour = params.get('hour')
        chunk_index = params.get('chunk_index')
        target_language = params.get('target_language')
        
        # Validate required parameters
        if not chunk_url and (hour is None or chunk_index is None):
            return {"content": [{"type": "text", "text": "Error: Either chunk_url or (hour + chunk_index) is required"}], "isError": True}
        
        # Build request
        data = {
            'device_id': device_id
        }
        
        if chunk_url:
            data['chunk_url'] = chunk_url
        else:
            data['hour'] = hour
            data['chunk_index'] = chunk_index
        
        if target_language:
            data['language'] = target_language
        
        # Call API
        result = self.api.post('/host/transcript/translate-chunk', data=data)
        
        return result

