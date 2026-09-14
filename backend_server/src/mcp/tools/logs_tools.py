"""
Logs Tools - System logs and service monitoring

Provides access to systemd service logs via journalctl.
"""

from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import APP_CONFIG


class LogsTools:
    """System logs and service monitoring tools"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
    
    def view_logs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        View systemd service logs via journalctl
        
        Access logs from backend_server, backend_host, or other services.
        Supports follow mode, filtering by time, and limiting lines.
        
        Args:
            params: {
                'service': str (REQUIRED) - Service name (e.g., 'vpt-server', 'vpt-host', 'vpt-frontend'),
                'lines': int (OPTIONAL) - Number of recent lines (default: 50),
                'follow': bool (OPTIONAL) - Follow mode (default: False),
                'since': str (OPTIONAL) - Show logs since time (e.g., '1h', '30min', '2024-01-04 12:00'),
                'level': str (OPTIONAL) - Filter by log level ('emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug'),
                'grep': str (OPTIONAL) - Filter logs by pattern
            }
            
        Returns:
            MCP-formatted response with log output
        """
        service = params.get('service')
        lines = params.get('lines', 50)
        follow = params.get('follow', False)
        since = params.get('since')
        level = params.get('level')
        grep = params.get('grep')
        
        # Validate required parameters
        if not service:
            return {"content": [{"type": "text", "text": "Error: service is required (e.g., vpt-server, vpt-host, vpt-frontend)"}], "isError": True}
        
        # Build request
        data = {
            'service': service,
            'lines': lines,
            'follow': follow
        }
        
        if since:
            data['since'] = since
        if level:
            data['level'] = level
        if grep:
            data['grep'] = grep
        
        # Call API
        result = self.api.post('/server/logs/view', data=data)
        
        return result
    
    def list_services(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available systemd services for monitoring.
        
        Example: list_services()
        
        Args:
            params: {}
            
        Returns:
            MCP-formatted response with available services
        """
        # Call API
        result = self.api.get('/server/logs/services')
        
        return result

