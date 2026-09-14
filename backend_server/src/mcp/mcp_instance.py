"""
MCP Server Singleton Instance

Single shared instance of VirtualPyTestMCPServer to avoid multiple instantiations.
"""

from .mcp_server import VirtualPyTestMCPServer

# Singleton instance - created once, shared across all routes
_mcp_server_instance = None


def get_mcp_server() -> VirtualPyTestMCPServer:
    """Get the singleton MCP server instance."""
    global _mcp_server_instance
    if _mcp_server_instance is None:
        _mcp_server_instance = VirtualPyTestMCPServer()
        # Log once on first creation
        tool_count = len(_mcp_server_instance.tool_handlers)
        print(f"[MCP] ✅ Initialized with {tool_count} tools")
    return _mcp_server_instance
