"""
Page Interaction Tools for AI Agent

Provides generic tools for AI to interact with any page element
based on the page schema, without hard-coding each action.
"""

import logging
import re
from urllib.parse import quote
import requests
from typing import Dict, Any, Optional, List
from shared.src.lib.utils.build_url_utils import server_auth_headers
from ..socket_manager import socket_manager

logger = logging.getLogger(__name__)

# The model sometimes echoes the companion context line into its answer; the server removes it.
COMPANION_ECHO = re.compile(r'^[ \t]*Companion:[^\n]*\n?', re.I | re.M)

# Backend API base URL (same server)
BACKEND_API_BASE = "http://localhost:5109"

# Atlas Companion catalogue (TASK-126): every page Atlas can show beside the chat.
# `path` must be a route in frontend/src/App.tsx and every key in `params` must be read by the
# page from its URL (tests/backend/test_companion_pages.py checks both).
#   params[name] = {'from': <tool that resolves the exact value>} | {'enum': [...]}
#   `file` is the page component that reads the params; `{x}` in `path` is a path segment.
_HOST = {'from': 'list_hosts'}
COMPANION_PAGES = {
    'dashboard': {
        'path': '/', 'name': 'Dashboard', 'file': 'pages/Dashboard.tsx',
        'answers': 'system overview', 'params': {}, 'data_tool': None,
    },
    'device_control': {
        'path': '/device-control', 'name': 'Device Control', 'file': 'pages/Rec.tsx',
        'answers': 'live device streams and control', 'params': {}, 'data_tool': 'list_hosts',
    },
    'test_reports': {
        'path': '/test-results/reports', 'name': 'Test Reports', 'file': 'pages/TestReports.tsx',
        'answers': 'LIST of runs for a device, script or period: results, pass rate, trends. NOT for why one run failed (use run_summary)',
        'params': {
            'host': _HOST,
            'device': _HOST,
            'script': {'from': 'get_execution_results'},
            'status': {'enum': ['passed', 'failed']},
            'range': {'enum': ['24h', '7d', '30d']},
            'tab': {'enum': ['tests', 'campaigns']},
        },
        'data_tool': 'get_execution_results',
    },
    'run_summary': {
        'path': '/test-results/runs/{kind}/{id}', 'name': 'Run Summary', 'file': 'pages/RunSummary.tsx',
        'answers': 'ONE run in detail: why it failed, which step and check missed. Use for "why did run X / the last run fail". Needs path_args kind=script and id = the `id` of a get_execution_results row',
        'params': {'status': {'enum': ['passed', 'failed']}},
        'data_tool': 'get_execution_results',
    },
    'run_live': {
        'path': '/test-results/live/{taskId}', 'name': 'Live Run', 'file': 'pages/RunLivePanel.tsx',
        'answers': 'a run that is executing now', 'params': {}, 'data_tool': 'get_execution_status',
    },
    'model_reports': {
        'path': '/test-results/model-reports', 'name': 'Model Reports', 'file': 'pages/ModelReports.tsx',
        'answers': 'pass rate per AI model', 'params': {}, 'data_tool': None,
    },
    'milestone': {
        'path': '/test-results/milestones/{milestoneId}', 'name': 'Milestone', 'file': 'pages/MilestoneDetail.tsx',
        'answers': 'progress and blockers of one milestone', 'params': {}, 'data_tool': None,
    },
    'defects': {
        'path': '/test-results/run-management', 'name': 'Defects', 'file': 'pages/RunManagement.tsx',
        'answers': 'open defects, groups, milestones and labels',
        'params': {'tab': {'enum': ['groups', 'milestones', 'labels', 'defects', 'manual']}},
        'data_tool': None,
    },
    'coverage': {
        'path': '/test-plan/coverage', 'name': 'Coverage', 'file': 'pages/Coverage.tsx',
        'answers': 'requirements NOT covered / without a test case, and coverage percent. Use for "which requirements are not covered"', 'params': {},
        'data_tool': 'get_uncovered_requirements',
    },
    'incidents': {
        'path': '/monitoring/incidents', 'name': 'Incidents', 'file': 'pages/MonitoringIncidents.tsx',
        'answers': 'freezes, black screens and other incidents on a device',
        'params': {'host': _HOST, 'device': _HOST}, 'data_tool': 'get_alerts',
    },
    'heatmap': {
        'path': '/monitoring/heatmap', 'name': 'Heatmap', 'file': 'pages/Heatmap.tsx',
        'answers': 'which devices have problems now',
        'params': {'host': _HOST, 'device': _HOST}, 'data_tool': 'get_alerts',
    },
    'ai_usage': {
        'path': '/monitoring/ai-usage', 'name': 'AI Usage', 'file': 'pages/MonitoringAiUsage.tsx',
        'answers': 'AI cost and tokens per model', 'params': {}, 'data_tool': None,
    },
    'analytics': {
        'path': '/monitoring/analytics', 'name': 'Analytics', 'file': 'pages/MonitoringAnalytics.tsx',
        'answers': 'stream quality and other KPIs', 'params': {'section': {'from': 'list_analytics_sources'}},
        'data_tool': 'query_analytics_data',
    },
    'deployments': {
        'path': '/test-execution/deployments', 'name': 'Deployments', 'file': None,
        'answers': 'what is deployed on the fleet', 'params': {}, 'data_tool': 'list_deployments',
    },
    'test_cases': {
        'path': '/test-plan/test-cases', 'name': 'Test Cases', 'file': 'pages/TestCaseEditor.tsx',
        'answers': 'the list of test cases', 'params': {}, 'data_tool': 'list_testcases',
    },
    'requirements': {
        'path': '/test-plan/requirements', 'name': 'Requirements', 'file': 'pages/Requirements.tsx',
        'answers': 'browse or edit the requirement list itself (not coverage gaps: use coverage)', 'params': {}, 'data_tool': 'list_requirements',
    },
    'ai_queue': {
        'path': '/monitoring/ai-queue', 'name': 'AI Queue', 'file': 'pages/AIQueueMonitor.tsx',
        'answers': 'the AI analysis queue', 'params': {}, 'data_tool': 'get_analysis_queue_status',
    },
}

# Pages that navigate_to_page can reach (no filters, not shown in the companion).
PAGE_SCHEMAS = {
    '/ai-agent': {'name': 'AI Agent'},
    '/agent-dashboard': {'name': 'Agent Dashboard'},
    '/pages': {'name': 'Pages'},
    '/builder/test-builder': {'name': 'Test Builder'},
    '/builder/campaign-builder': {'name': 'Campaign Builder'},
    '/test-plan/campaigns': {'name': 'Campaigns'},
    '/test-execution/run-tests': {'name': 'Run Tests'},
    '/monitoring/system': {'name': 'System Monitoring'},
    '/test-results/dependency-report': {'name': 'Dependency Report'},
}
PAGE_SCHEMAS.update({e['path']: {'name': e['name']} for e in COMPANION_PAGES.values()
                     if '{' not in e['path']})

NAVIGATION_ALIASES = {
    'dashboard': '/', 'home': '/', 'main': '/', 'overview': '/',
    'device control': '/device-control', 'device-control': '/device-control',
    'devices': '/device-control', 'device': '/device-control', 'rec': '/device-control',
    'appareils': '/device-control', 'appareil': '/device-control', 'geräte': '/device-control',
    'geraete': '/device-control',
    'streams': '/device-control', 'live': '/device-control',
    'ai agent': '/ai-agent', 'agent': '/ai-agent', 'chat': '/ai-agent', 'atlas': '/ai-agent',
    'agent dashboard': '/agent-dashboard', 'agents': '/agent-dashboard', 'multi agent': '/agent-dashboard',
    'test builder': '/builder/test-builder', 'builder': '/builder/test-builder',
    'build test': '/builder/test-builder',
    'campaign builder': '/builder/campaign-builder', 'campaign-builder': '/builder/campaign-builder',
    'build campaign': '/builder/campaign-builder',
    'test cases': '/test-plan/test-cases', 'testcases': '/test-plan/test-cases',
    'tests': '/test-plan/test-cases',
    'campaigns': '/test-plan/campaigns', 'campaign': '/test-plan/campaigns',
    'requirements': '/test-plan/requirements', 'reqs': '/test-plan/requirements',
    'coverage': '/test-plan/coverage',
    'run tests': '/test-execution/run-tests', 'run test': '/test-execution/run-tests',
    'execute tests': '/test-execution/run-tests',
    'deployments': '/test-execution/deployments', 'deploy': '/test-execution/deployments',
    'incidents': '/monitoring/incidents', 'alerts': '/monitoring/incidents',
    'issues': '/monitoring/incidents',
    'heatmap': '/monitoring/heatmap', 'heat map': '/monitoring/heatmap',
    'monitoring': '/monitoring/heatmap',
    'ai queue': '/monitoring/ai-queue', 'queue': '/monitoring/ai-queue',
    'ai status': '/monitoring/ai-queue',
    'system monitoring': '/monitoring/system', 'system': '/monitoring/system',
    'grafana': '/monitoring/system',
    'test reports': '/test-results/reports', 'reports': '/test-results/reports',
    'test results': '/test-results/reports', 'results': '/test-results/reports',
    'model reports': '/test-results/model-reports', 'models': '/test-results/model-reports',
    'model results': '/test-results/model-reports',
    'dependency report': '/test-results/dependency-report',
    'dependencies': '/test-results/dependency-report', 'dependency': '/test-results/dependency-report',
}


def _emit(session_id: Optional[str], payload: Dict[str, Any]) -> bool:
    """Send one ui_action to the asking chat's room only (never to every browser)."""
    if not session_id:
        logger.error("ui_action without a session_id: not sent")
        return False
    socket_manager.emit_to_room(session_id, 'ui_action', payload, namespace='/agent')
    return True


_NO_SESSION = "❌ No chat session to send this to."


def companion_page_list() -> str:
    """One line per companion page for the skill prompt: `key — answers (params)`."""
    return "\n".join(
        f"- {key} — {e['answers']}" + (f" [{', '.join(e['params'])}]" if e['params'] else "")
        for key, e in COMPANION_PAGES.items()
    )


def _closest(value: str, options: List[str], n: int = 5) -> List[str]:
    """Options that look like `value`: substring hits first, then difflib matches."""
    import difflib
    low = value.lower()
    hits = [o for o in options if low in o.lower() or o.lower() in low]
    for o in difflib.get_close_matches(value, options, n=n, cutoff=0.4):
        if o not in hits:
            hits.append(o)
    return hits[:n]


def _check_known(params: Dict[str, str], known: Dict[str, Any]) -> Optional[str]:
    """Refuse host / device / script values that are not exact real names. None = all fine.

    `known`: {'host': [names], 'device': {host: [names]}, 'script': [names]} (a missing key is
    not checked). An empty list refuses everything, so a URL is never built from a guess.
    """
    for key in ('host', 'device', 'script'):
        if key not in params or key not in known:
            continue
        value = params[key]
        if key == 'device':
            by_host = known['device'] or {}
            options = by_host.get(params.get('host'), None)
            if options is None:
                options = sorted({d for devs in by_host.values() for d in devs})
        else:
            options = list(known[key] or [])
        if value in options:
            continue
        near = _closest(value, options)
        where = f" on host '{params['host']}'" if key == 'device' and params.get('host') in (known['device'] or {}) else ''
        hint = f" Closest: {', '.join(near)}." if near else (
            f" None known{where}." if not options else f" Known: {', '.join(options[:8])}.")
        return f"❌ {key} '{value}' is not an exact name{where}.{hint} Retry with an exact value."
    return None


_RANGE_WORDS = (('24h', r'today|24\s*h(?:ours?)?|last day'), ('7d', r'this week|last week|week|7\s*d(?:ays?)?'),
                ('30d', r'this month|last month|month|30\s*d(?:ays?)?'))


def infer_followup_params(text: str, page: str, current: Dict[str, str],
                          known: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Follow-up filters worded in the user's own message, merged into the shown page's params.
    Rules only: failed/passed -> status, today/week/month -> range (page enum), an exact known
    host, device or script name -> that param. None when nothing changes."""
    allowed = COMPANION_PAGES.get(page, {}).get('params', {})
    text = text or ''
    found: Dict[str, str] = {}
    m = re.search(r'\b(failed|failing|failures?|fail|passed|passing|pass)\b', text, re.I)
    if m and 'status' in allowed:
        found['status'] = 'failed' if m.group(1).lower().startswith('fail') else 'passed'
    if 'range' in allowed:
        for value, pat in _RANGE_WORDS:
            if value in allowed['range'].get('enum', []) and re.search(r'\b(?:%s)\b' % pat, text, re.I):
                found['range'] = value
                break
    tokens = {t.strip(' \t.,;:!?()[]"\'').lower() for t in text.split()}
    devices = {d for ds in (known.get('device') or {}).values() for d in ds}
    for param, names in (('host', known.get('host') or []), ('device', devices), ('script', known.get('script') or [])):
        if param not in allowed:
            continue
        hit = [n for n in names if n.lower() in tokens]
        if len(hit) == 1:
            found[param] = hit[0]
    merged = dict(current)
    merged.update(found)
    if 'host' in found and found['host'] != current.get('host') and 'device' not in found:
        merged.pop('device', None)
    return merged if merged != current else None


def show_page(
    page: str,
    params: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
    open_now: bool = False,
    path_args: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    known: Optional[Dict[str, Any]] = None,
    run_exists: Optional[Any] = None,
    defer: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Offer (or open) a real app page, already filtered, in the companion beside the chat.

    Args:
        defer: collect the event here instead of sending it
        page: key from COMPANION_PAGES (e.g. 'test_reports')
        params: URL filters; only names and values allowed by the catalogue entry
        title: optional label for the offer
        open_now: True when the user asked for the page in so many words
        path_args: values for `{kind}`/`{id}` style path segments
    """
    entry = COMPANION_PAGES.get(page)
    if not entry:
        return f"❌ Unknown page '{page}'. Allowed: {', '.join(COMPANION_PAGES)}"
    params = {k: str(v) for k, v in (params or {}).items() if v not in (None, '')}
    allowed = entry['params']
    for k, v in params.items():
        spec = allowed.get(k)
        if spec is None:
            return (f"❌ Page '{page}' has no param '{k}'. Allowed: "
                    f"{', '.join(allowed) or 'none'}")
        if 'enum' in spec and v not in spec['enum']:
            return f"❌ Param '{k}' takes {', '.join(spec['enum'])} (got '{v}')."
    err = _check_known(params, known or {})
    if err:
        return err
    path = entry['path']
    for seg in [s for s in path.split('/') if s.startswith('{')]:
        name = seg[1:-1]
        val = (path_args or {}).get(name)
        if not val:
            return f"❌ Page '{page}' needs path_args.{name}."
        if name in ('id', 'taskId') and not re.fullmatch(r'[A-Za-z0-9_-]+', str(val)):
            return f"❌ path_args.{name} may only contain letters, digits, '-' and '_'."
        path = path.replace(seg, quote(str(val), safe=''))
    if page == 'run_summary' and run_exists is not None:
        if (path_args or {}).get('kind') not in ('script', 'campaign'):
            return "❌ run_summary needs path_args.kind = script or campaign."
        if not run_exists(path_args['kind'], str(path_args['id'])):
            return f"❌ No {path_args['kind']} run with id '{path_args['id']}'. Use the `id` of a get_execution_results row."
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    action = 'companion_open' if open_now else 'companion_offer'
    event = {
        "action": action,
        "payload": {"page": page, "name": entry['name'], "path": path,
                    "params": params, "title": title or entry['name']},
    }
    if defer is not None:
        # a turn may call show_page again after a refused value: only the last valid one is sent (turn end)
        defer.append(event)
    elif not _emit(session_id, event):
        return _NO_SESSION
    query = '&'.join(f"{k}={v}" for k, v in params.items())
    url = path + (f"?{query}" if query else '')
    logger.info(f"🟢 show_page {action} -> session {session_id}: {url}")
    return f"✅ {'Opened' if open_now else 'Offered'} {entry['name']} in the companion: {url}"


def get_available_pages() -> str:
    """List the pages Atlas can show in the companion, with their URL filters."""
    logger.info("🔍 get_available_pages called")
    return "📄 Companion pages (show with show_page):\n" + companion_page_list()


def get_page_schema(page_path: str) -> str:
    """
    Returns the URL filters a companion page accepts.

    Args:
        page_path: catalogue key (e.g. 'test_reports') or the page path
    """
    logger.info(f"🔍 get_page_schema called: page_path={page_path}")
    entry = COMPANION_PAGES.get(page_path) or next(
        (e for e in COMPANION_PAGES.values() if e['path'] == page_path or e['name'].lower() == page_path.lower()),
        None)
    if not entry:
        return f"❌ Page '{page_path}' not found. Use get_available_pages() to see available pages."
    lines = [f"📄 **{entry['name']}** ({entry['path']})", f"Answers: {entry['answers']}", "Params:"]
    for k, spec in entry['params'].items():
        lines.append(f"  - {k}: " + (', '.join(spec['enum']) if 'enum' in spec else f"exact value from {spec['from']}"))
    if entry['data_tool']:
        lines.append(f"Data tool: {entry['data_tool']}")
    return "\n".join(lines)


def navigate_to_page(page_name: str, context: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> str:
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
    # A page name itself ("devices", "device control") is a page, not a device screen.
    if normalized not in NAVIGATION_ALIASES and any(keyword in original_lower for keyword in device_keywords):
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
    
    if not _emit(session_id, {
            "action": "navigate",
            "payload": {"path": path, "context": context},
            "agent_message": f"Navigating to {page_display_name}..."
        }):
        return _NO_SESSION
    
    logger.info(f"🟢 Sending 'ui_action' to navigate to {page_display_name} (path: {path})")
    return f"✅ Navigated to {page_display_name} ({path})"


def interact_with_element(element_id: str, action: str, params: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> str:
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
    
    if not _emit(session_id, {
            "action": "interact",
            "payload": {
                "element_id": element_id,
                "action": action,
                "params": params or {}
            },
            "agent_message": f"Interacting with {element_id}: {action}"
        }):
        return _NO_SESSION
    
    logger.info(f"🟢 Broadcasting 'ui_action' for element interaction: {element_id}.{action}")
    return f"✅ Triggered {action} on {element_id}"


def highlight_element(element_id: str, duration_ms: int = 2000, session_id: Optional[str] = None) -> str:
    """
    Highlight an element on the page to draw user's attention.
    
    Args:
        element_id: The element ID to highlight
        duration_ms: How long to show the highlight (default 2000ms)
    """
    logger.info(f"🤖 highlight_element called: element={element_id}, duration={duration_ms}ms")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    if not _emit(session_id, {
            "action": "highlight",
            "payload": {
                "element_id": element_id,
                "duration_ms": duration_ms
            },
            "agent_message": f"Highlighting {element_id}"
        }):
        return _NO_SESSION
    
    return f"✅ Highlighting {element_id} for {duration_ms}ms"


def show_toast(message: str, severity: str = "info", session_id: Optional[str] = None) -> str:
    """
    Show a toast notification to the user.
    
    Args:
        message: The message to display
        severity: One of 'info', 'success', 'warning', 'error'
    """
    logger.info(f"🤖 show_toast called: message={message}, severity={severity}")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    if not _emit(session_id, {
            "action": "toast",
            "payload": {
                "message": message,
                "severity": severity
            }
        }):
        return _NO_SESSION
    
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


def refresh_navigation_editor(session_id: Optional[str] = None) -> str:
    """
    Refresh the navigation editor canvas to show latest changes.
    Useful after creating nodes/edges to ensure proper rendering.
    """
    logger.info("🤖 refresh_navigation_editor called")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    if not _emit(session_id, {
            "action": "interact",
            "payload": {
                "element_id": "tree-canvas",
                "action": "refresh",
                "params": {}
            },
            "agent_message": "Refreshing navigation editor..."
        }):
        return _NO_SESSION
    
    return "✅ Navigation editor refreshed"


def show_content_panel(
    content_type: str,
    content_data: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
    session_id: Optional[str] = None
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
    
    if not _emit(session_id, {
            "action": "show_content",
            "payload": {
                "content_type": content_type,
                "content_data": content_data or {},
                "title": title
            },
            "agent_message": f"Showing {content_type} panel..."
        }):
        return _NO_SESSION
    
    display_title = title or content_type.replace('-', ' ').title()
    return f"✅ Showing {display_title} in content panel"


def hide_content_panel(session_id: Optional[str] = None) -> str:
    """
    Hide the content panel and restore full chat view.
    Use this when done showing content to the user.
    """
    logger.info("🤖 hide_content_panel called")
    
    if not socket_manager.socketio:
        return "❌ Backend UI control system not ready."
    
    if not _emit(session_id, {
            "action": "hide_content",
            "payload": {},
            "agent_message": "Hiding content panel..."
        }):
        return _NO_SESSION
    
    return "✅ Content panel hidden, chat restored"


def sync_ui_context(
    device_id: Optional[str] = None,
    host_name: Optional[str] = None,
    userinterface_name: Optional[str] = None,
    testcase_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    session_id: Optional[str] = None
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
    
    if not _emit(session_id, {
            "action": "sync_context",
            "payload": payload,
            "agent_message": "Syncing UI context..."
        }):
        return _NO_SESSION
    
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
    "show_page",
]

