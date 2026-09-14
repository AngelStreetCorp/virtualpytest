"""Deployment tools for scheduled script execution management"""

from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter


class DeploymentTools:
    """Tools for managing scheduled deployments"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
    
    def create_deployment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a scheduled deployment for automated test execution.
        
        Example: create_deployment(name='nightly_test', host_name='host1', device_id='device1', script_name='test.py', cron_expression='0 2 * * *')
        
        Args:
            params: {
                'name': str (REQUIRED - deployment name),
                'host_name': str (REQUIRED - host where device is connected),
                'device_id': str (REQUIRED - device identifier),
                'script_name': str (REQUIRED - script to execute),
                'cron_expression': str (REQUIRED - cron schedule),
                'userinterface_name': str (OPTIONAL - interface name),
                'parameters': str (OPTIONAL - script parameters),
                'start_date': str (OPTIONAL - start date),
                'end_date': str (OPTIONAL - end date),
                'max_executions': int (OPTIONAL - max execution count)
            }
        
        Returns:
            Created deployment details
        """
        team_id = params.get('team_id', 'default')
        
        deployment_data = {
            'name': params['name'],
            'host_name': params['host_name'],
            'device_id': params['device_id'],
            'script_name': params['script_name'],
            'userinterface_name': params.get('userinterface_name', ''),
            'parameters': params.get('parameters', ''),
            'cron_expression': params['cron_expression']
        }
        
        # Optional constraints
        if 'start_date' in params:
            deployment_data['start_date'] = params['start_date']
        if 'end_date' in params:
            deployment_data['end_date'] = params['end_date']
        if 'max_executions' in params:
            deployment_data['max_executions'] = params['max_executions']
        
        result = self.api.post('/server/deployment/create', deployment_data, {'team_id': team_id})
        
        if result.get('success'):
            deployment = result['deployment']
            response_text = "✅ Deployment created successfully\n\n"
            response_text += f"Name: {deployment['name']}\n"
            response_text += f"Script: {deployment['script_name']}\n"
            response_text += f"Device: {deployment['host_name']}:{deployment['device_id']}\n"
            response_text += f"Schedule: {deployment['cron_expression']}\n"
            if deployment.get('start_date'):
                response_text += f"Start: {deployment['start_date']}\n"
            if deployment.get('end_date'):
                response_text += f"End: {deployment['end_date']}\n"
            if deployment.get('max_executions'):
                response_text += f"Max runs: {deployment['max_executions']}\n"
            response_text += f"\nID: {deployment['id']}"
            
            return MCPFormatter.format_success(response_text)
        else:
            return MCPFormatter.format_error(f"Failed to create deployment: {result.get('error', 'Unknown error')}")
    
    def list_deployments(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all scheduled deployments.
        
        Example: list_deployments()
        
        Args:
            params: {}
        
        Returns:
            List of deployments with status and schedules
        """
        team_id = params.get('team_id', 'default')
        
        result = self.api.get('/server/deployment/list', {'team_id': team_id})
        
        if result.get('success'):
            deployments = result['deployments']
            if not deployments:
                return MCPFormatter.format_success("No deployments found")
            
            response_text = f"📅 Found {len(deployments)} deployment(s)\n\n"
            for dep in deployments:
                status_emoji = "▶️" if dep['status'] == 'active' else "⏸️"
                response_text += f"{status_emoji} {dep['name']}\n"
                response_text += f"  Script: {dep['script_name']}\n"
                response_text += f"  Device: {dep['host_name']}:{dep['device_id']}\n"
                response_text += f"  Schedule: {dep['cron_expression']}\n"
                response_text += f"  Status: {dep['status']}\n"
                response_text += f"  Runs: {dep.get('execution_count', 0)}"
                if dep.get('max_executions'):
                    response_text += f"/{dep['max_executions']}"
                response_text += f"\n  ID: {dep['id']}\n\n"
            
            return MCPFormatter.format_success(response_text)
        else:
            return MCPFormatter.format_error(f"Failed to list deployments: {result.get('error', 'Unknown error')}")
    
    def pause_deployment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Pause a running deployment.
        
        Example: pause_deployment(deployment_id='abc123')
        
        Args:
            params: {
                'deployment_id': str (REQUIRED - deployment ID to pause)
            }
        
        Returns:
            Success confirmation
        """
        deployment_id = params['deployment_id']
        
        result = self.api.post(f'/server/deployment/pause/{deployment_id}', {})
        
        if result.get('success'):
            return MCPFormatter.format_success(f"⏸️ Deployment paused: {deployment_id}")
        else:
            return MCPFormatter.format_error(f"Failed to pause deployment: {result.get('error', 'Unknown error')}")
    
    def resume_deployment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resume a paused deployment.
        
        Example: resume_deployment(deployment_id='abc123')
        
        Args:
            params: {
                'deployment_id': str (REQUIRED - deployment ID to resume)
            }
        
        Returns:
            Success confirmation
        """
        deployment_id = params['deployment_id']
        
        result = self.api.post(f'/server/deployment/resume/{deployment_id}', {})
        
        if result.get('success'):
            return MCPFormatter.format_success(f"▶️ Deployment resumed: {deployment_id}")
        else:
            return MCPFormatter.format_error(f"Failed to resume deployment: {result.get('error', 'Unknown error')}")
    
    def update_deployment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a deployment's configuration.
        
        Example: update_deployment(deployment_id='abc123', cron_expression='0 3 * * *')
        
        Args:
            params: {
                'deployment_id': str (REQUIRED - deployment ID to update),
                'name': str (OPTIONAL - new deployment name),
                'cron_expression': str (OPTIONAL - new cron schedule),
                'userinterface_name': str (OPTIONAL - new interface name),
                'parameters': str (OPTIONAL - new script parameters)
            }
        
        Returns:
            Updated deployment details
        """
        deployment_id = params['deployment_id']
        
        update_data = {}
        if 'cron_expression' in params:
            update_data['cron_expression'] = params['cron_expression']
        if 'start_date' in params:
            update_data['start_date'] = params['start_date']
        if 'end_date' in params:
            update_data['end_date'] = params['end_date']
        if 'max_executions' in params:
            update_data['max_executions'] = params['max_executions']
        
        result = self.api.put(f'/server/deployment/update/{deployment_id}', update_data)
        
        if result.get('success'):
            deployment = result['deployment']
            response_text = "✅ Deployment updated successfully\n\n"
            response_text += f"Schedule: {deployment['cron_expression']}\n"
            if deployment.get('start_date'):
                response_text += f"Start: {deployment['start_date']}\n"
            if deployment.get('end_date'):
                response_text += f"End: {deployment['end_date']}\n"
            if deployment.get('max_executions'):
                response_text += f"Max runs: {deployment['max_executions']}\n"
            
            return MCPFormatter.format_success(response_text)
        else:
            return MCPFormatter.format_error(f"Failed to update deployment: {result.get('error', 'Unknown error')}")
    
    def delete_deployment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delete a deployment.
        
        Example: delete_deployment(deployment_id='abc123')
        
        Args:
            params: {
                'deployment_id': str (REQUIRED - deployment ID to delete)
            }
        
        Returns:
            Success confirmation
        """
        deployment_id = params['deployment_id']
        
        result = self.api.delete(f'/server/deployment/delete/{deployment_id}', {})
        
        if result.get('success'):
            return MCPFormatter.format_success(f"🗑️ Deployment deleted: {deployment_id}")
        else:
            return MCPFormatter.format_error(f"Failed to delete deployment: {result.get('error', 'Unknown error')}")
    
    def get_deployment_history(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get execution history for a deployment.
        
        Example: get_deployment_history(deployment_id='abc123', limit=10)
        
        Args:
            params: {
                'deployment_id': str (REQUIRED - deployment ID),
                'limit': int (OPTIONAL - max results default 50)
            }
        
        Returns:
            Execution history with results
        """
        deployment_id = params['deployment_id']
        
        result = self.api.get(f'/server/deployment/history/{deployment_id}', {})
        
        if result.get('success'):
            executions = result['executions']
            if not executions:
                return MCPFormatter.format_success(f"No execution history for deployment: {deployment_id}")
            
            response_text = f"📊 Execution history for deployment: {deployment_id}\n"
            response_text += f"Total executions: {len(executions)}\n\n"
            
            for exec in executions[:10]:  # Show last 10
                status = "✅" if exec.get('success') else "❌"
                response_text += f"{status} {exec['started_at']}\n"
                if exec.get('completed_at'):
                    response_text += f"  Duration: {exec.get('duration', 'N/A')}s\n"
                if exec.get('report_url'):
                    response_text += f"  Report: {exec['report_url']}\n"
                response_text += "\n"
            
            if len(executions) > 10:
                response_text += f"... and {len(executions) - 10} more executions\n"
            
            return MCPFormatter.format_success(response_text)
        else:
            return MCPFormatter.format_error(f"Failed to get deployment history: {result.get('error', 'Unknown error')}")

