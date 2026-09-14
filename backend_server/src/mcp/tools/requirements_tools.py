from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import APP_CONFIG, get_team_id


class RequirementsTools:
    """Requirements management and coverage tracking tools"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
    
    def create_requirement(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new requirement
        
        Args:
            params: {
                'requirement_code': str (REQUIRED) - e.g., 'REQ_PLAYBACK_001'
                'requirement_name': str (REQUIRED) - e.g., 'User can play video'
                'description': str (OPTIONAL)
                'priority': str (OPTIONAL) - P1, P2, P3 (default: P2)
                'category': str (OPTIONAL) - e.g., 'playback', 'navigation'
                'team_id': str (OPTIONAL)
            }
            
        Returns:
            MCP-formatted response with requirement_id
        """
        team_id = params.get('team_id', get_team_id())
        
        body = {
            'team_id': team_id,
            'requirement_code': params.get('requirement_code'),
            'requirement_name': params.get('requirement_name'),
            'description': params.get('description'),
            'priority': params.get('priority', 'P2'),
            'category': params.get('category'),
            'app_type': params.get('app_type', 'all'),
            'device_model': params.get('device_model', 'all'),
            'status': params.get('status', 'active'),
            'source_document': params.get('source_document'),
            'acceptance_criteria': params.get('acceptance_criteria'),
            'created_by': params.get('created_by', 'mcp_user')
        }
        
        print(f"[@MCP:create_requirement] Creating requirement: {body['requirement_code']}")
        result = self.api.post('/server/requirements/create', data=body)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to create requirement')
            return {"content": [{"type": "text", "text": f"❌ Create failed: {error_msg}"}], "isError": True}
        
        requirement_id = result.get('requirement_id')
        response_text = f"✅ Requirement created: {body['requirement_code']}\n   ID: {requirement_id}\n   Priority: {body['priority']}\n   Category: {body['category']}"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def list_requirements(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all requirements.
        
        Example: list_requirements()
        
        Args:
            params: {}
        
        Returns:
            List of requirements with codes and names
        """
        team_id = params.get('team_id', get_team_id())
        
        result = self.api.get('/server/requirements/list', params={
            'team_id': team_id,
            'status': 'active'
        })
        
        if not result.get('success'):
            return {"content": [{"type": "text", "text": f"Error: {result.get('error')}"}], "isError": True}
        
        requirements = result.get('requirements', [])
        
        if not requirements:
            return {"content": [{"type": "text", "text": "No requirements found"}], "isError": False}
        
        # Minimal output
        lines = [f"{len(requirements)} requirements:"]
        for req in requirements:
            lines.append(f"- [{req.get('priority', '?')}] {req.get('requirement_code')}: {req.get('requirement_name', '')[:40]}")
        
        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
            "requirements": [{"id": req.get('requirement_id'), "code": req.get('requirement_code')} for req in requirements]
        }
    
    def update_requirement(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing requirement.
        
        Example: update_requirement(requirement_id='123', priority='high', status='in_progress')
        
        Args:
            params: {
                'requirement_id': str (REQUIRED - requirement ID to update),
                'requirement_name': str (OPTIONAL - new name),
                'requirement_code': str (OPTIONAL - new code),
                'description': str (OPTIONAL - new description),
                'priority': str (OPTIONAL - new priority),
                'status': str (OPTIONAL - new status)
            }
            
        Returns:
            Updated requirement details
        """
        team_id = params.get('team_id', get_team_id())
        requirement_id = params.get('requirement_id')
        
        if not requirement_id:
            return {"content": [{"type": "text", "text": "❌ Error: requirement_id is required"}], "isError": True}
        
        # Build update body - only include fields that are provided
        body = {'team_id': team_id}
        
        if params.get('requirement_name'):
            body['requirement_name'] = params.get('requirement_name')
        if params.get('requirement_code'):
            body['requirement_code'] = params.get('requirement_code')
        if params.get('description'):
            body['description'] = params.get('description')
        if params.get('priority'):
            body['priority'] = params.get('priority')
        if params.get('category'):
            body['category'] = params.get('category')
        if params.get('app_type'):
            body['app_type'] = params.get('app_type')
        if params.get('device_model'):
            body['device_model'] = params.get('device_model')
        if params.get('status'):
            body['status'] = params.get('status')
        if params.get('acceptance_criteria'):
            body['acceptance_criteria'] = params.get('acceptance_criteria')
        
        if len(body) == 1:  # Only team_id
            return {"content": [{"type": "text", "text": "❌ Error: No fields to update"}], "isError": True}
        
        print(f"[@MCP:update_requirement] Updating requirement: {requirement_id}")
        result = self.api.put(f'/server/requirements/{requirement_id}', data=body)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to update requirement')
            return {"content": [{"type": "text", "text": f"❌ Update failed: {error_msg}"}], "isError": True}
        
        response_text = f"✅ Requirement updated: {requirement_id}"
        if body.get('requirement_code'):
            response_text += f"\n   Code: {body['requirement_code']}"
        if body.get('app_type'):
            response_text += f"\n   App Type: {body['app_type']}"
        if body.get('device_model'):
            response_text += f"\n   Device Model: {body['device_model']}"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def get_requirement(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get requirement by ID.
        
        Example: get_requirement(requirement_id='REQ-001')
        
        Args:
            params: {
                'requirement_id': str (REQUIRED - requirement ID to fetch)
            }
            
        Returns:
            Requirement details with linked test cases
        """
        team_id = params.get('team_id', get_team_id())
        requirement_id = params.get('requirement_id')
        
        query_params = {'team_id': team_id}
        
        print(f"[@MCP:get_requirement] Fetching requirement: {requirement_id}")
        result = self.api.get(f'/server/requirements/{requirement_id}', params=query_params)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Requirement not found')
            return {"content": [{"type": "text", "text": f"❌ Get failed: {error_msg}"}], "isError": True}
        
        req = result.get('requirement', {})
        
        response_text = f"📋 Requirement Details:\n\n"
        response_text += f"Code: {req['requirement_code']}\n"
        response_text += f"Name: {req['requirement_name']}\n"
        response_text += f"Priority: {req.get('priority', 'N/A')}\n"
        response_text += f"Category: {req.get('category', 'N/A')}\n"
        response_text += f"Status: {req.get('status', 'N/A')}\n"
        if req.get('description'):
            response_text += f"\nDescription:\n{req['description']}\n"
        if req.get('acceptance_criteria'):
            response_text += f"\nAcceptance Criteria:\n{req['acceptance_criteria']}\n"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def link_testcase_to_requirement(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Link testcase to requirement for coverage tracking
        
        Args:
            params: {
                'testcase_id': str (REQUIRED)
                'requirement_id': str (REQUIRED)
                'coverage_type': str (OPTIONAL) - 'full', 'partial' (default: 'full')
                'coverage_notes': str (OPTIONAL)
            }
            
        Returns:
            MCP-formatted response
        """
        body = {
            'testcase_id': params.get('testcase_id'),
            'requirement_id': params.get('requirement_id'),
            'coverage_type': params.get('coverage_type', 'full'),
            'coverage_notes': params.get('coverage_notes'),
            'created_by': params.get('created_by', 'mcp_user')
        }
        
        print(f"[@MCP:link_testcase_to_requirement] Linking testcase {body['testcase_id']} to requirement {body['requirement_id']}")
        result = self.api.post('/server/requirements/link-testcase', data=body)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to link testcase')
            return {"content": [{"type": "text", "text": f"❌ Link failed: {error_msg}"}], "isError": True}
        
        response_text = f"✅ Testcase linked successfully\n   Testcase: {body['testcase_id']}\n   Requirement: {body['requirement_id']}\n   Coverage: {body['coverage_type']}"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def unlink_testcase_from_requirement(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Unlink testcase from requirement.
        
        Example: unlink_testcase_from_requirement(testcase_id='tc1', requirement_id='req1')
        
        Args:
            params: {
                'testcase_id': str (REQUIRED - test case ID),
                'requirement_id': str (REQUIRED - requirement ID)
            }
            
        Returns:
            Success confirmation
        """
        body = {
            'testcase_id': params.get('testcase_id'),
            'requirement_id': params.get('requirement_id')
        }
        
        print(f"[@MCP:unlink_testcase_from_requirement] Unlinking testcase {body['testcase_id']} from requirement {body['requirement_id']}")
        result = self.api.post('/server/requirements/unlink-testcase', data=body)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to unlink testcase')
            return {"content": [{"type": "text", "text": f"❌ Unlink failed: {error_msg}"}], "isError": True}
        
        response_text = f"✅ Testcase unlinked successfully"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def get_testcase_requirements(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get all requirements linked to a testcase.
        
        Example: get_testcase_requirements(testcase_id='tc123')
        
        Args:
            params: {
                'testcase_id': str (REQUIRED - test case ID)
            }
            
        Returns:
            List of requirements linked to the test case
        """
        testcase_id = params.get('testcase_id')
        
        print(f"[@MCP:get_testcase_requirements] Fetching requirements for testcase: {testcase_id}")
        result = self.api.get(f'/server/requirements/testcase/{testcase_id}/requirements')
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to get requirements')
            return {"content": [{"type": "text", "text": f"❌ Get failed: {error_msg}"}], "isError": True}
        
        requirements = result.get('requirements', [])
        count = result.get('count', len(requirements))
        
        if not requirements:
            return {"content": [{"type": "text", "text": f"No requirements linked to testcase: {testcase_id}"}], "isError": False}
        
        response_text = f"📋 Requirements for testcase {testcase_id} ({count} total):\n\n"
        
        for req in requirements:
            response_text += f"• {req['requirement_code']} - {req['requirement_name']}\n"
            response_text += f"  Coverage: {req.get('coverage_type', 'full')}\n"
            if req.get('coverage_notes'):
                response_text += f"  Notes: {req['coverage_notes']}\n"
            response_text += "\n"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def get_requirement_coverage(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get detailed coverage for a requirement showing linked test cases and executions.
        
        Example: get_requirement_coverage(requirement_id='REQ-001')
        
        Args:
            params: {
                'requirement_id': str (REQUIRED - requirement ID to check coverage)
            }
            
        Returns:
            Coverage details with test cases and execution stats
        """
        team_id = params.get('team_id', get_team_id())
        requirement_id = params.get('requirement_id')
        
        query_params = {'team_id': team_id}
        
        print(f"[@MCP:get_requirement_coverage] Fetching coverage for requirement: {requirement_id}")
        result = self.api.get(f'/server/requirements/{requirement_id}/coverage', params=query_params)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to get coverage')
            return {"content": [{"type": "text", "text": f"❌ Get failed: {error_msg}"}], "isError": True}
        
        coverage = result.get('coverage', {})
        
        response_text = f"📊 Coverage for {coverage.get('requirement_code', 'N/A')}:\n\n"
        response_text += f"Testcases: {coverage.get('testcase_count', 0)}\n"
        response_text += f"Scripts: {coverage.get('script_count', 0)}\n"
        response_text += f"Executions: {coverage.get('execution_count', 0)}\n"
        response_text += f"Last Execution: {coverage.get('last_execution_date', 'Never')}\n"
        
        if coverage.get('testcases'):
            response_text += f"\nLinked Testcases:\n"
            for tc in coverage['testcases'][:10]:
                response_text += f"  • {tc['testcase_name']} ({tc.get('coverage_type', 'full')})\n"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def get_coverage_summary(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get coverage summary across all requirements with breakdowns by priority and category.
        
        Example: get_coverage_summary()
        
        Args:
            params: {
                'category': str (OPTIONAL - filter by category),
                'priority': str (OPTIONAL - filter by priority)
            }
            
        Returns:
            Coverage metrics and percentages
        """
        team_id = params.get('team_id', get_team_id())
        
        query_params = {
            'team_id': team_id,
            'category': params.get('category'),
            'priority': params.get('priority')
        }
        
        # Remove None values
        query_params = {k: v for k, v in query_params.items() if v is not None}
        
        print(f"[@MCP:get_coverage_summary] Fetching coverage summary")
        result = self.api.get('/server/requirements/coverage/summary', params=query_params)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to get coverage summary')
            return {"content": [{"type": "text", "text": f"❌ Get failed: {error_msg}"}], "isError": True}
        
        summary = result.get('summary', {})
        
        response_text = f"📊 Requirements Coverage Summary:\n\n"
        response_text += f"Total Requirements: {summary.get('total_requirements', 0)}\n"
        response_text += f"Covered: {summary.get('covered_requirements', 0)}\n"
        response_text += f"Uncovered: {summary.get('uncovered_requirements', 0)}\n"
        response_text += f"Coverage Rate: {summary.get('coverage_percentage', 0):.1f}%\n\n"
        
        if summary.get('by_priority'):
            response_text += "By Priority:\n"
            for priority, stats in summary['by_priority'].items():
                response_text += f"  {priority}: {stats.get('covered', 0)}/{stats.get('total', 0)} ({stats.get('percentage', 0):.1f}%)\n"
        
        if summary.get('by_category'):
            response_text += "\nBy Category:\n"
            for category, stats in summary['by_category'].items():
                response_text += f"  {category}: {stats.get('covered', 0)}/{stats.get('total', 0)} ({stats.get('percentage', 0):.1f}%)\n"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}
    
    def get_uncovered_requirements(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get all requirements without test coverage.
        
        Example: get_uncovered_requirements()
        
        Args:
            params: {}
            
        Returns:
            List of uncovered requirements
        """
        team_id = params.get('team_id', get_team_id())
        
        query_params = {'team_id': team_id}
        
        print(f"[@MCP:get_uncovered_requirements] Fetching uncovered requirements")
        result = self.api.get('/server/requirements/uncovered', params=query_params)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Failed to get uncovered requirements')
            return {"content": [{"type": "text", "text": f"❌ Get failed: {error_msg}"}], "isError": True}
        
        requirements = result.get('requirements', [])
        count = result.get('count', len(requirements))
        
        if not requirements:
            return {"content": [{"type": "text", "text": "✅ All requirements have test coverage!"}], "isError": False}
        
        response_text = f"⚠️  Uncovered Requirements ({count} total):\n\n"
        
        for req in requirements[:50]:
            response_text += f"• {req['requirement_code']} - {req['requirement_name']}\n"
            response_text += f"  Priority: {req.get('priority', 'N/A')} | Category: {req.get('category', 'N/A')}\n\n"
        
        if count > 50:
            response_text += f"\n... and {count - 50} more uncovered requirements"
        
        return {"content": [{"type": "text", "text": response_text}], "isError": False}

