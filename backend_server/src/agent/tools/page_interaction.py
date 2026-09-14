"""
Page Interaction Tools for AI Agent

Provides generic tools for AI to interact with any page element
based on the page schema, without hard-coding each action.
"""

import logging
import requests
from typing import Dict, Any, Optional, List
from shared.src.lib.utils.build_url_utils import server_auth_headers
from ..socket_manager import socket_manager

logger = logging.getLogger(__name__)

# Backend API base URL (same server)
BACKEND_API_BASE = "http://localhost:5109"

# Mirror of frontend PAGE_SCHEMAS - all navigable pages
# This should stay in sync with frontend/src/App.tsx routes
PAGE_SCHEMAS = {
    '/': {
        'name': 'Dashboard',
        'description': 'Main dashboard with system overview',
        'elements': ['system-status', 'quick-actions', 'recent-activity'],
    },
    '/device-control': {
        'name': 'Device Control',
        'description': 'View and control connected devices with live streams',
        'elements': ['device-grid', 'host-filter', 'model-filter', 'stream-modal'],
    },
    '/ai-agent': {
        'name': 'AI Agent',
        'description': 'Chat with AI agent for QA automation',
        'elements': ['chat-input', 'message-list', 'agent-selector'],
    },
    '/agent-dashboard': {
        'name': 'Agent Dashboard',
        'description': 'Multi-agent control panel',
        'elements': ['agent-grid', 'activity-monitor'],
    },
    '/builder/test-builder': {
        'name': 'Test Builder',
        'description': 'Visual test case builder',
        'elements': ['step-canvas', 'action-palette', 'save-btn', 'device-preview'],
    },
    '/builder/campaign-builder': {
        'name': 'Campaign Builder',
        'description': 'Create and manage test campaigns',
        'elements': ['campaign-canvas', 'script-sequence', 'device-selector', 'save-campaign-btn'],
    },
    '/builder/mcp-playground': {
        'name': 'MCP Playground',
        'description': 'Test and experiment with MCP tools',
        'elements': ['tool-selector', 'input-form', 'result-display'],
    },
    '/builder/navigation-editor': {
        'name': 'Navigation Editor',
        'description': 'Edit and manage navigation trees',
        'elements': ['tree-canvas', 'node-editor', 'edge-editor', 'save-navigation-btn'],
    },
    '/test-plan/test-cases': {
        'name': 'Test Cases',
        'description': 'Manage test cases',
        'elements': ['test-cases-table', 'filter-bar', 'create-btn'],
    },
    '/test-plan/campaigns': {
        'name': 'Campaigns',
        'description': 'Manage test campaigns',
        'elements': ['campaigns-table', 'filter-bar', 'create-btn'],
    },
    '/test-plan/requirements': {
        'name': 'Requirements',
        'description': 'Manage requirements and coverage',
        'elements': ['requirements-table', 'coverage-chart', 'link-btn'],
    },
    '/test-plan/coverage': {
        'name': 'Coverage',
        'description': 'View test coverage metrics',
        'elements': ['coverage-summary', 'coverage-chart', 'filter-bar'],
    },
    '/test-execution/run-tests': {
        'name': 'Run Tests',
        'description': 'Execute individual test cases',
        'elements': ['test-selector', 'device-selector', 'run-btn'],
    },
    '/test-execution/run-campaigns': {
        'name': 'Run Campaigns',
        'description': 'Execute test campaigns',
        'elements': ['campaign-selector', 'device-selector', 'run-btn'],
    },
    '/test-execution/deployments': {
        'name': 'Deployments',
        'description': 'Manage test deployments',
        'elements': ['deployments-table', 'deploy-btn'],
    },
    '/monitoring/incidents': {
        'name': 'Incidents',
        'description': 'Monitor and manage incidents',
        'elements': ['incidents-table', 'status-filter', 'severity-filter'],
    },
    '/monitoring/heatmap': {
        'name': 'Heatmap',
        'description': 'Real-time device health monitoring',
        'elements': ['mosaic-player', 'timeline-slider', 'status-filter', 'analysis-table'],
    },
    '/monitoring/ai-queue': {
        'name': 'AI Queue',
        'description': 'Monitor AI analysis queue status',
        'elements': ['queue-status', 'processing-table', 'stats-chart'],
    },
    '/monitoring/system': {
        'name': 'System Monitoring',
        'description': 'Grafana system monitoring dashboard',
        'elements': ['grafana-iframe'],
    },
    '/test-results/reports': {
        'name': 'Test Reports',
        'description': 'View test execution reports',
        'elements': ['reports-table', 'filter-bar', 'export-btn'],
    },
    '/test-results/model-reports': {
        'name': 'Model Reports',
        'description': 'View reports grouped by device model',
        'elements': ['model-table', 'filter-bar', 'chart-view'],
    },
    '/test-results/dependency-report': {
        'name': 'Dependency Report',
        'description': 'View test dependencies and relationships',
        'elements': ['dependency-graph', 'table-view'],
    },
}

# Navigation aliases for natural language - maps common terms to routes
# Handles variations like "goto X", "navigate to X", "go to X", "show me X"
NAVIGATION_ALIASES = {
    # Dashboard
    'dashboard': '/',
    'home': '/',
    'main': '/',
    'overview': '/',
    
    # Device Control
    'device control': '/device-control',
    'device-control': '/device-control',
    'devices': '/device-control',
    'device': '/device-control',
    'rec': '/device-control',
    'streams': '/device-control',
    'live': '/device-control',
    
    # AI Agent
    'ai agent': '/ai-agent',
    'agent': '/ai-agent',
    'chat': '/ai-agent',
    'atlas': '/ai-agent',
    
    # Agent Dashboard
    'agent dashboard': '/agent-dashboard',
    'agents': '/agent-dashboard',
    'multi agent': '/agent-dashboard',
    
    # Test Builder
    'test builder': '/builder/test-builder',
    'builder': '/builder/test-builder',
    'build test': '/builder/test-builder',
    
    # Campaign Builder
    'campaign builder': '/builder/campaign-builder',
    'campaign-builder': '/builder/campaign-builder',
    'build campaign': '/builder/campaign-builder',
    
    # MCP Playground
    'mcp playground': '/builder/mcp-playground',
    'playground': '/builder/mcp-playground',
    'mcp': '/builder/mcp-playground',
    
    # Navigation Editor
    'navigation editor': '/builder/navigation-editor',
    'navigation-editor': '/builder/navigation-editor',
    'nav editor': '/builder/navigation-editor',
    'tree editor': '/builder/navigation-editor',
    
    # Test Cases
    'test cases': '/test-plan/test-cases',
    'testcases': '/test-plan/test-cases',
    'tests': '/test-plan/test-cases',
    
    # Campaigns
    'campaigns': '/test-plan/campaigns',
    'campaign': '/test-plan/campaigns',
    
    # Requirements
    'requirements': '/test-plan/requirements',
    'reqs': '/test-plan/requirements',
    
    # Coverage
    'coverage': '/test-plan/coverage',
    
    # Run Tests
    'run tests': '/test-execution/run-tests',
    'run test': '/test-execution/run-tests',
    'execute tests': '/test-execution/run-tests',
    
    # Run Campaigns
    'run campaigns': '/test-execution/run-campaigns',
    'run campaign': '/test-execution/run-campaigns',
    'execute campaigns': '/test-execution/run-campaigns',
    
    # Deployments
    'deployments': '/test-execution/deployments',
    'deploy': '/test-execution/deployments',
    
    # Incidents
    'incidents': '/monitoring/incidents',
    'alerts': '/monitoring/incidents',
    'issues': '/monitoring/incidents',
    
    # Heatmap
    'heatmap': '/monitoring/heatmap',
    'heat map': '/monitoring/heatmap',
    'monitoring': '/monitoring/heatmap',
    
    # AI Queue
    'ai queue': '/monitoring/ai-queue',
    'queue': '/monitoring/ai-queue',
    'ai status': '/monitoring/ai-queue',
    
    # System Monitoring
    'system monitoring': '/monitoring/system',
    'system': '/monitoring/system',
    'grafana': '/monitoring/system',
    
    # Test Reports
    'test reports': '/test-results/reports',
    'reports': '/test-results/reports',
    'test results': '/test-results/reports',
    'results': '/test-results/reports',
    
    # Model Reports
    'model reports': '/test-results/model-reports',
    'models': '/test-results/model-reports',
    'model results': '/test-results/model-reports',
    
    # Dependency Report
    'dependency report': '/test-results/dependency-report',
    'dependencies': '/test-results/dependency-report',
    'dependency': '/test-results/dependency-report',
}


def get_available_pages() -> str:
    """
    Returns a list of all navigable pages with their descriptions.
    Use this to understand what pages exist in the application.
    """
    logger.info("🔍 get_available_pages called")
    
    lines = ["📄 Available Pages:\n"]
    for path, info in PAGE_SCHEMAS.items():
        lines.append(f"- **{info['name']}** ({path})")
        lines.append(f"  {info['description']}")
        lines.append(f"  Elements: {', '.join(info['elements'][:4])}{'...' if len(info['elements']) > 4 else ''}")
        lines.append("")
    
    return "\n".join(lines)


def get_page_schema(page_path: str) -> str:
    """
    Returns the interactive elements available on a specific page.
    
    Args:
        page_path: The page path (e.g., '/device-control', '/test-results/reports')
    """
    logger.info(f"🔍 get_page_schema called: page_path={page_path}")
    
    schema = PAGE_SCHEMAS.get(page_path)
    if not schema:
        # Try to find by name
        for path, info in PAGE_SCHEMAS.items():
            if info['name'].lower() == page_path.lower():
                schema = info
                page_path = path
                break
    
    if not schema:
        return f"❌ Page '{page_path}' not found. Use get_available_pages() to see available pages."
    
    lines = [
        f"📄 **{schema['name']}** ({page_path})",
        f"Description: {schema['description']}",
        "",
        "Interactive Elements:",
    ]
    
    for elem_id in schema['elements']:
        lines.append(f"  - {elem_id}")
    
    return "\n".join(lines)


def navigate_to_page(page_name: str, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Navigates the user's browser to a specific page.
    
    Args:
        page_name: Page name or path. Natural language supported.
                   Examples: 'dashboard', 'go to heatmap', 'navigate to test builder', 
                             'show me device control', 'redirect to reports'
        context: Optional parameters (e.g., {'device_id': 's21'})
    
    Available pages: dashboard, device control, ai agent, heatmap, test builder, 
                     campaign builder, test cases, reports, and more
    """
    logger.info(f"🤖 navigate_to_page called: page_name={page_name}, context={context}")
    
    # Normalize input - remove common navigation action words
    normalized = page_name.lower().strip()
    
    # Strip common action phrases that might precede the actual page name
    action_phrases = [
        'navigate to', 'navigate to the', 'navigate',
        'go to', 'go to the', 'goto',
        'redirect to', 'redirect to the', 'redirect',
        'show me', 'show me the', 'show',
        'open', 'open the',
        'take me to', 'take me to the',
        'bring me to', 'bring me to the',
        'display', 'display the',
        'load', 'load the',
    ]
    
    for phrase in action_phrases:
        if normalized.startswith(phrase + ' '):
            normalized = normalized[len(phrase):].strip()
            break
    
    # Remove " page" suffix (but keep " screen" as it might indicate device navigation)
    if normalized.endswith(' page'):
        normalized = normalized[:-5].strip()
    
    logger.info(f"🔍 Normalized page name: '{normalized}'")
    
    # DISAMBIGUATION: Detect if user is asking about device/node navigation instead
    device_keywords = [
        'device', 'node', 'screen', 'app screen', 'userinterface', 'tree',
        'on device', 'on the device', 'device to', 'app to', 'tv to', 'phone to'
    ]
    original_lower = page_name.lower()
    if any(keyword in original_lower for keyword in device_keywords):
        return (
            "❌ It looks like you're asking to navigate a DEVICE or APP SCREEN, not a frontend page.\n\n"
            "For DEVICE navigation, please specify:\n"
            "  • 'navigate device to [node]' (e.g., 'navigate device to home screen')\n"
            "  • 'control device and go to [screen]'\n\n"
            "For FRONTEND PAGE navigation, say:\n"
            "  • 'show me the dashboard page'\n"
            "  • 'go to reports page'\n"
            "  • Just use page names: 'dashboard', 'reports', 'heatmap'"
        )
    
    # 1. Check exact alias match
    path = NAVIGATION_ALIASES.get(normalized)
    
    # 2. If not found, check if it's a direct path
    if not path and normalized.startswith('/'):
        if normalized in PAGE_SCHEMAS:
            path = normalized
    
    # 3. Try partial matching in aliases (fuzzy matching)
    if not path:
        # Split normalized into words for better matching
        words = normalized.split()
        for alias, alias_path in NAVIGATION_ALIASES.items():
            # Check if all words appear in the alias
            if all(word in alias for word in words):
                path = alias_path
                logger.info(f"✅ Fuzzy matched '{normalized}' to alias '{alias}' -> {path}")
                break
        
        # If still no match, try partial word matching
        if not path:
            for alias, alias_path in NAVIGATION_ALIASES.items():
                if normalized in alias or alias in normalized:
                    path = alias_path
                    logger.info(f"✅ Partial matched '{normalized}' to alias '{alias}' -> {path}")
                    break
    
    # 4. Try matching against page display names directly
    if not path:
        for schema_path, schema_info in PAGE_SCHEMAS.items():
            page_display_name = schema_info['name'].lower()
            if normalized == page_display_name or normalized in page_display_name:
                path = schema_path
                logger.info(f"✅ Matched to page name '{schema_info['name']}' -> {path}")
                break
    
    # If no match found, provide helpful error
    if not path:
        # Get unique page names for suggestion
        unique_pages = sorted(set(PAGE_SCHEMAS[p]['name'] for p in PAGE_SCHEMAS))
        return (
            f"❌ Cannot find page '{page_name}'.\n\n"
            f"Available pages:\n" + 
            "\n".join(f"  • {name}" for name in unique_pages[:15]) +
            ("\n  ... and more" if len(unique_pages) > 15 else "")
        )
    
    # Emit navigation event
    if not socket_manager.socketio:
        logger.error("🤖 Socket manager not initialized!")
        return "❌ Backend UI control system not ready."
    
    page_info = PAGE_SCHEMAS.get(path, {})
    page_display_name = page_info.get('name', page_name)
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "navigate",
            "payload": {"path": path, "context": context},
            "agent_message": f"Navigating to {page_display_name}..."
        },
        namespace='/agent'
    )
    
    logger.info(f"🟢 Broadcasting 'ui_action' to navigate to {page_display_name} (path: {path})")
    return f"✅ Navigated to {page_display_name} ({path})"


def interact_with_element(element_id: str, action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Interact with a specific element on the current page.
    
    Args:
        element_id: The element ID from the page schema (e.g., 'reports-table', 'run-btn')
        action: The action to perform (e.g., 'click', 'select', 'filter', 'open')
        params: Optional parameters for the action (e.g., {'value': 'failed'}, {'row_id': '123'})
    
    Common actions:
        - click: Click a button
        - select: Select an item in a dropdown or table row
        - filter: Apply a filter
        - open: Open a modal or expand a section
        - close: Close a modal or collapse a section
        - type: Type text into an input
        - scroll_to: Scroll to make element visible
    """
    logger.info(f"🤖 interact_with_element called: element={element_id}, action={action}, params={params}")
    
    if not socket_manager.socketio:
        logger.error("🤖 Socket manager not initialized!")
        return "❌ Backend UI control system not ready."
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "interact",
            "payload": {
                "element_id": element_id,
                "action": action,
                "params": params or {}
            },
            "agent_message": f"Interacting with {element_id}: {action}"
        },
        namespace='/agent'
    )
    
    logger.info(f"🟢 Broadcasting 'ui_action' for element interaction: {element_id}.{action}")
    return f"✅ Triggered {action} on {element_id}"


def highlight_element(element_id: str, duration_ms: int = 2000) -> str:
    """
    Highlight an element on the page to draw user's attention.
    
    Args:
        element_id: The element ID to highlight
        duration_ms: How long to show the highlight (default 2000ms)
    """
    logger.info(f"🤖 highlight_element called: element={element_id}, duration={duration_ms}ms")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "highlight",
            "payload": {
                "element_id": element_id,
                "duration_ms": duration_ms
            },
            "agent_message": f"Highlighting {element_id}"
        },
        namespace='/agent'
    )
    
    return f"✅ Highlighting {element_id} for {duration_ms}ms"


def show_toast(message: str, severity: str = "info") -> str:
    """
    Show a toast notification to the user.
    
    Args:
        message: The message to display
        severity: One of 'info', 'success', 'warning', 'error'
    """
    logger.info(f"🤖 show_toast called: message={message}, severity={severity}")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "toast",
            "payload": {
                "message": message,
                "severity": severity
            }
        },
        namespace='/agent'
    )
    
    return f"✅ Showed toast: {message}"


def get_alerts(
    status: Optional[str] = None,
    host_name: Optional[str] = None,
    device_id: Optional[str] = None,
    incident_type: Optional[str] = None,
    limit: int = 20
) -> str:
    """
    Fetch alerts from the monitoring system.
    
    Args:
        status: Filter by status ('active' or 'resolved'). If not set, returns both.
        host_name: Filter by specific host
        device_id: Filter by specific device
        incident_type: Filter by incident type (e.g., 'freeze', 'blackscreen')
        limit: Maximum number of alerts to return (default 20)
    
    Returns:
        Summary of alerts with counts and details
    """
    logger.info(f"🔍 get_alerts called: status={status}, host={host_name}, device={device_id}, type={incident_type}, limit={limit}")
    
    try:
        # Determine which endpoint to call based on status filter
        if status == 'active':
            url = f"{BACKEND_API_BASE}/server/alerts/getActiveAlerts"
            params = {}
        elif status == 'resolved':
            url = f"{BACKEND_API_BASE}/server/alerts/getClosedAlerts"
            params = {}
        else:
            # Get all alerts (both active and resolved)
            url = f"{BACKEND_API_BASE}/server/alerts/getAllAlerts"
            params = {
                'active_limit': limit,
                'resolved_limit': limit
            }
        
        # Add optional filters
        if host_name:
            params['host_name'] = host_name
        if device_id:
            params['device_id'] = device_id
        if incident_type:
            params['incident_type'] = incident_type
            
        # /server/* is closed by default (TASK-09): send the shared service key.
        response = requests.get(url, params=params, headers=server_auth_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get('success', False):
            return f"❌ Error fetching alerts: {data.get('error', 'Unknown error')}"
        
        # Format the response - handle different endpoint response formats
        alerts = data.get('alerts', [])
        total_count = data.get('count', len(alerts))
        
        # For filtered queries (active/resolved), the count IS the filtered count
        if status == 'active':
            active_count = total_count
            resolved_count = 0
        elif status == 'resolved':
            active_count = 0
            resolved_count = total_count
        else:
            # getAllAlerts returns both counts
            active_count = data.get('active_count', 0)
            resolved_count = data.get('resolved_count', 0)
        
        # Build summary based on what was requested
        lines = [f"📊 **Alert Summary**"]
        if status == 'active':
            lines.append(f"- **Active alerts**: {active_count}")
        elif status == 'resolved':
            lines.append(f"- **Resolved alerts**: {resolved_count}")
        else:
            lines.append(f"- **Active alerts**: {active_count}")
            lines.append(f"- **Resolved alerts**: {resolved_count}")
            lines.append(f"- **Total**: {total_count}")
        
        if alerts:
            lines.append("")
            lines.append("**Recent Alerts:**")
            
            # Show up to 10 alerts with details
            for i, alert in enumerate(alerts[:10]):
                alert_status = alert.get('status', 'unknown')
                status_icon = "🔴" if alert_status == 'active' else "✅"
                incident = alert.get('incident_type', 'unknown')
                host = alert.get('host_name', 'unknown')
                device = alert.get('device_id', 'unknown')
                start = alert.get('start_time', 'unknown')[:19] if alert.get('start_time') else 'unknown'
                
                lines.append(f"{status_icon} **{incident}** on {host}/{device} - Started: {start}")
            
            if len(alerts) > 10:
                lines.append(f"... and {len(alerts) - 10} more alerts")
        
        return "\n".join(lines)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching alerts: {e}")
        return f"❌ Error fetching alerts: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in get_alerts: {e}")
        return f"❌ Error: {str(e)}"


def refresh_navigation_editor() -> str:
    """
    Refresh the navigation editor canvas to show latest changes.
    Useful after creating nodes/edges to ensure proper rendering.
    """
    logger.info("🤖 refresh_navigation_editor called")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "interact",
            "payload": {
                "element_id": "tree-canvas",
                "action": "refresh",
                "params": {}
            },
            "agent_message": "Refreshing navigation editor..."
        },
        namespace='/agent'
    )
    
    return "✅ Navigation editor refreshed"


def show_content_panel(
    content_type: str,
    content_data: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None
) -> str:
    """
    Display content in the AgentChat content viewer panel.
    This minimizes the chat and shows the content above it.
    
    Args:
        content_type: Type of content to display. Options:
            - 'navigation-tree': Show navigation tree (optionally pass tree_id, node_id, userinterface_name)
            - 'testcase-flow': Show test case flow (optionally pass testcase_id, editable)
            - 'device-preview': Show device streams (optionally pass device_ids)
            - 'report-chart': Show chart (optionally pass chart_type, chart_data)
            - 'data-table': Show table (pass columns and rows)
            - 'execution-log': Show log entries (pass log_entries)
        content_data: Data for the content type (varies by type)
        title: Optional title for the panel header
    
    Examples:
        show_content_panel('navigation-tree', {'userinterface_name': 'Disney+'}, 'Navigation: Disney+')
        show_content_panel('testcase-flow', {'testcase_id': 'tc_123', 'editable': True})
        show_content_panel('data-table', {
            'columns': [{'field': 'name', 'header': 'Name'}, {'field': 'status', 'header': 'Status'}],
            'rows': [{'name': 'Test 1', 'status': 'PASSED'}]
        }, 'Test Results')
    """
    logger.info(f"🤖 show_content_panel called: type={content_type}, title={title}")
    
    valid_types = ['navigation-tree', 'testcase-flow', 'device-preview', 'report-chart', 'data-table', 'execution-log']
    if content_type not in valid_types:
        return f"❌ Invalid content_type '{content_type}'. Valid types: {', '.join(valid_types)}"
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "show_content",
            "payload": {
                "content_type": content_type,
                "content_data": content_data or {},
                "title": title
            },
            "agent_message": f"Showing {content_type} panel..."
        },
        namespace='/agent'
    )
    
    display_title = title or content_type.replace('-', ' ').title()
    return f"✅ Showing {display_title} in content panel"


def hide_content_panel() -> str:
    """
    Hide the content panel and restore full chat view.
    Use this when done showing content to the user.
    """
    logger.info("🤖 hide_content_panel called")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "hide_content",
            "payload": {},
            "agent_message": "Hiding content panel..."
        },
        namespace='/agent'
    )
    
    return "✅ Content panel hidden, chat restored"


def sync_ui_context(
    device_id: Optional[str] = None,
    host_name: Optional[str] = None,
    userinterface_name: Optional[str] = None,
    testcase_id: Optional[str] = None,
    campaign_id: Optional[str] = None
) -> str:
    """
    Sync the AgentChat UI dropdowns with the agent's current execution context.
    Call this when starting to work with a specific device, interface, test case, or campaign
    so the UI stays in sync with what the agent is doing.

    Args:
        device_id: The device ID to select in the Device dropdown
        host_name: The host name (for reference, device_id is used for selection)
        userinterface_name: The user interface name to select in the Interface dropdown
        testcase_id: The test case ID to select in the TestCase dropdown
        campaign_id: The campaign ID to select in the Campaign dropdown

    Example:
        sync_ui_context(device_id='s21', userinterface_name='Netflix', testcase_id='tc_login')
    """
    logger.info(f"🤖 sync_ui_context called: device={device_id}, host={host_name}, interface={userinterface_name}, testcase={testcase_id}")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    payload = {}
    if device_id:
        payload['device_id'] = device_id
    if host_name:
        payload['host_name'] = host_name
    if userinterface_name:
        payload['userinterface_name'] = userinterface_name
    if testcase_id:
        payload['testcase_id'] = testcase_id
    if campaign_id:
        payload['campaign_id'] = campaign_id
    
    socket_manager.broadcast(
        'ui_action',
        {
            "action": "sync_context",
            "payload": payload,
            "agent_message": "Syncing UI context..."
        },
        namespace='/agent'
    )
    
    synced_items = [k for k in payload.keys()]
    return f"✅ UI context synced: {', '.join(synced_items)}"


# Export all tools
PAGE_INTERACTION_TOOLS = [
    "get_available_pages",
    "get_page_schema", 
    "navigate_to_page",
    "interact_with_element",
    "highlight_element",
    "show_toast",
    "get_alerts",
    "show_content_panel",
    "hide_content_panel",
    "sync_ui_context",
]

