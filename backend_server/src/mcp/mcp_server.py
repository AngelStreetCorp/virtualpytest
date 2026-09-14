#!/usr/bin/env python3
"""
MCP Server for VirtualPyTest

Model Context Protocol server that exposes VirtualPyTest device control
functionality to external LLMs (Claude, ChatGPT, etc.)

This server provides 75 core tools for device automation organized into domains:
- Control: device locking and session management
- Actions: device command execution
- Navigation: UI tree navigation and pathfinding
- Verification: state verification and UI inspection
- TestCase: test case execution and management
- Campaign: test campaign management (NEW)
- Script: Python script execution
- Deployment: scheduled execution management
- AI: test generation
- Screenshot/Transcript: media capture
- Device: device info and compatibility
- Logs: systemd service logs
- Tree: navigation tree CRUD operations
- UserInterface: app model management
- Requirements: requirements and coverage tracking
- Screen Analysis: unified selector scoring
- Exploration: AI-powered tree building (NEW - RECOMMENDED)
- Admin: user/permission management (list users, get/set permissions, set team permissions)
"""

import logging
import asyncio
import re
from typing import Dict, Any, List, Optional
from pathlib import Path

# Import tool definitions and auto-handler generator
from .tool_definitions import (
    TOOL_REGISTRY,  # Auto-discovered tool classes
    get_tool_handlers,  # Auto-generate tool handlers
    get_builder,  # Get tool definitions builder
)

# Import utilities
from .utils.api_client import MCPAPIClient
from .utils.mcp_formatter import MCPFormatter, ErrorCategory
from .utils.input_validator import InputValidator


# Global security: keywords in tool parameters that indicate secret/credential access
_SENSITIVE_KEYWORDS = re.compile(
    r'\.env|\.aws|\.ssh|\.docker|\.npmrc|\.pypirc|\.pem|\.key|\.p12|\.pfx'
    r'|private_key|secret_key|api_key|access_token|refresh_token'
    r'|credentials\.json|service_account|id_rsa|id_ed25519'
    r'|password|passwd|\.htpasswd|shadow',
    re.IGNORECASE,
)


def _contains_sensitive_request(params: Dict[str, Any]) -> bool:
    """Scan all string values in params for sensitive keywords."""
    for value in params.values():
        if isinstance(value, str) and _SENSITIVE_KEYWORDS.search(value):
            return True
    return False


class VirtualPyTestMCPServer:
    """MCP Server for VirtualPyTest device automation"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.api_client = MCPAPIClient()
        self.formatter = MCPFormatter()
        self.validator = InputValidator()
        
        # Tool schemas cache (for validation)
        self._tool_schemas = None
        
        # AUTO-DISCOVER AND INSTANTIATE ALL TOOL CLASSES
        tool_instances = {}
        for category, tool_class in TOOL_REGISTRY.items():
            try:
                # Tools that need api_client
                if category in ['control', 'action', 'navigation', 'verification', 'testcase',
                               'script', 'ai', 'screenshot', 'transcript', 'device', 'logs',
                               'tree', 'userinterface', 'ai_userinterface', 'requirements', 'exploration',
                               'deployment', 'campaign', 'admin']:
                    tool_instance = tool_class(self.api_client)
                # Tools that don't need api_client
                elif category in ['screen_analysis', 'analysis', 'docs']:
                    tool_instance = tool_class()
                else:
                    # Fallback - try with api_client first, then without
                    try:
                        tool_instance = tool_class(self.api_client)
                    except TypeError:
                        tool_instance = tool_class()

                tool_instances[category] = tool_instance

            except Exception as e:
                print(f"[MCP-SERVER] ⚠️ Failed to instantiate {category}: {e}")
                continue

        self.tool_handlers = get_tool_handlers(tool_instances)
        
        self.logger.info(f"VirtualPyTest MCP Server initialized with {len(self.tool_handlers)} tools")
    
    def handle_tool_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle MCP tool call (synchronous) with input validation
        
        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            
        Returns:
            MCP-formatted response
            
        Raises:
            ValueError: If tool returns an error (isError: True)
        """
        try:
            self.logger.info(f"Handling tool call: {tool_name}")
            self.logger.debug(f"Parameters: {params}")
            
            # Check if tool exists
            if tool_name not in self.tool_handlers:
                error_msg = f"Unknown tool: {tool_name}. Available tools: {list(self.tool_handlers.keys())}"
                error_response = self.formatter.format_error(error_msg, ErrorCategory.NOT_FOUND)
                raise ValueError(error_response['content'][0]['text'])

            # Global security gate: block requests targeting sensitive files/secrets
            if _contains_sensitive_request(params):
                self.logger.warning(f"SECURITY: Blocked sensitive request in {tool_name}: {list(params.keys())}")
                error_response = self.formatter.format_error(
                    "Access denied: requests involving sensitive files, credentials, or secrets are not permitted.",
                    ErrorCategory.VALIDATION,
                )
                raise ValueError(error_response['content'][0]['text'])

            # Validate input parameters against tool schema
            tool_schema = self._get_tool_schema(tool_name)
            if tool_schema:
                is_valid, validation_error = self.validator.validate_arguments(
                    tool_name,
                    params,
                    tool_schema['inputSchema']
                )
                
                if not is_valid:
                    self.logger.warning(f"Validation failed for {tool_name}: {validation_error}")
                    error_response = self.formatter.format_validation_error(tool_name, validation_error)
                    raise ValueError(error_response['content'][0]['text'])
            
            # Execute tool (synchronous)
            handler = self.tool_handlers[tool_name]
            result = handler(params)
            
            # Check if result indicates an error
            if result.get('isError', False):
                error_text = result['content'][0]['text']
                self.logger.error(f"Tool {tool_name} returned error: {error_text}")
                raise ValueError(error_text)
            
            self.logger.info(f"Tool {tool_name} completed successfully")
            return result
            
        except ValueError:
            # Re-raise ValueError as-is (these are our formatted errors)
            raise
        except Exception as e:
            self.logger.error(f"Tool call error for {tool_name}: {e}", exc_info=True)
            error_response = self.formatter.format_error(
                f"Tool execution error: {str(e)}",
                ErrorCategory.BACKEND
            )
            raise ValueError(error_response['content'][0]['text'])
    
    def _get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get schema for a specific tool
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool schema dict or None if not found
        """
        # Cache tool schemas on first access
        if self._tool_schemas is None:
            tools = self.get_available_tools()
            self._tool_schemas = {tool['name']: tool for tool in tools}
        
        return self._tool_schemas.get(tool_name)
    
    # Tools hidden from MCP discovery (used internally by other tools)
    HIDDEN_TOOLS = {'take_control', 'release_control'}

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get list of available MCP tools in proper MCP format with JSON Schema

        Uses auto-discovery - all tools from *_tools.py files are automatically included!
        Tools in HIDDEN_TOOLS are excluded from discovery but remain callable internally.

        Returns:
            List of MCP-formatted tool definitions aggregated from all domains
        """
        # Get the builder and return all discovered tools
        builder = get_builder()
        tools: List[Dict[str, Any]] = []

        # AUTO-DISCOVER ALL TOOL DEFINITIONS
        # Zero manual configuration - all *_tools.py files are automatically included!
        for category in sorted(TOOL_REGISTRY.keys()):
            category_tools = builder.get_tools(category)
            # Filter out hidden tools (e.g., take_control/release_control — locking is automatic)
            category_tools = [t for t in category_tools if t['name'] not in self.HIDDEN_TOOLS]
            tools.extend(category_tools)

        return tools


async def main():
    """Main MCP server entry point"""
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info("Starting VirtualPyTest MCP Server")
    
    # Initialize server
    server = VirtualPyTestMCPServer()
    
    # Print available tools
    tools = server.get_available_tools()
    logger.info(f"Available tools ({len(tools)}):")
    for tool in tools:
        logger.info(f"  - {tool['name']}: {tool['description']}")
    
    # Keep server running
    try:
        logger.info("MCP Server ready and listening...")
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down MCP server")


if __name__ == "__main__":
    asyncio.run(main())

