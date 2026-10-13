"""
System Ops Tools - Read-only host health checks

Exposes two small read-only ops that the system-ops skill uses:
- check_storage: disk usage, df -h equivalent
- ping_host: TCP liveness check on the host's backend port

Both are wrappers around /host/system/* routes on the backend_host
service. They share the API client + formatter pattern with the rest of
the MCP tools and auto-register via the TOOL_REGISTRY in
backend_server/src/mcp/tool_definitions/.

NOTE: list_services and restart_service were removed from this module
in the de-dupe pass — they overlap with masterchief (TASK-71), which
is the authoritative surface for service list/status/restart. Atlas
should call propose_masterchief_op for those, not direct MCP tools.
See commit `fix/system-ops-dedupe` and the Handover block in
docs/tasks/TASK-73-atlas-testing-progressive.md.
"""
from typing import Dict, Any, List
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter


class SystemOpsTools:
    """Small host-level operations used by the system-ops skill."""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()

    def check_storage(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Disk usage on a host, df -h equivalent.

        Returns a row per filesystem with size / used / available / use_pct
        and the mountpoint. Bounded to 1 s on the host.

        Args:
            params: {
                'host_name': str (REQUIRED)
            }

        Example: check_storage(host_name='vpt-pi3')
        """
        host_name = params.get('host_name')
        if not host_name:
            return {
                "content": [{"type": "text", "text": "❌ host_name is required"}],
                "isError": True,
            }
        result = self.api.get(f'/host/system/checkStorage', params={'host_name': host_name})
        if not isinstance(result, dict) or not result.get('success'):
            err = (result or {}).get('error', 'unknown error') if isinstance(result, dict) else 'invalid response'
            return self.formatter.format_error(
                f'❌ check_storage failed: {err}', category='backend'
            )
        rows = result.get('rows') or []
        host = result.get('host', host_name)
        lines = [f"💾 Storage on {host} ({len(rows)} filesystem{'s' if len(rows) != 1 else ''}):"]
        for r in rows:
            pct = r.get('use_pct', 0.0)
            used_gb = round(r.get('used', 0) / 1024**3, 1)
            total_gb = round(r.get('size', 0) / 1024**3, 1)
            avail_gb = round(r.get('available', 0) / 1024**3, 1)
            icon = '🔴' if pct >= 90 else '⚠️' if pct >= 75 else '✅'
            lines.append(
                f"  {icon} {r.get('mountpoint', '?'):20s} "
                f"{used_gb:6.1f}G / {total_gb:6.1f}G "
                f"({avail_gb:6.1f}G free, {pct}%)"
            )
        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
        }

    def ping_host(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Lightweight liveness check on a host (TCP probe to backend port).

        Returns the round-trip time in milliseconds, the host name and the
        boot time (when psutil is available). Bounded to 200 ms on the host.

        Args:
            params: {
                'host_name': str (REQUIRED)
            }

        Example: ping_host(host_name='vpt-pi3')
        """
        host_name = params.get('host_name')
        if not host_name:
            return {
                "content": [{"type": "text", "text": "❌ host_name is required"}],
                "isError": True,
            }
        result = self.api.get(f'/host/system/pingHost', params={'host_name': host_name})
        if not isinstance(result, dict):
            return self.formatter.format_error(
                'ping_host got an invalid response', category='backend'
            )
        if not result.get('success'):
            err = result.get('error', 'TCP connect failed')
            return {
                "content": [{
                    "type": "text",
                    "text": f"🔴 {host_name} is NOT reachable ({err})",
                }],
                "isError": False,  # not an exception — just a negative answer
            }
        rtt = result.get('rtt_ms', '?')
        boot = result.get('boot_time', 'unknown')
        return {
            "content": [{
                "type": "text",
                "text": f"✅ {host_name} is up (TCP RTT {rtt} ms, boot {boot})",
            }],
            "isError": False,
        }
