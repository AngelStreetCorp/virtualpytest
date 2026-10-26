"""
Tool Bridge

Connects Claude Agent SDK to existing MCP tools and UI interaction tools.
"""

import logging
import time
import hashlib
import json
from typing import Dict, Any, List, Optional

from backend_server.src.mcp.mcp_instance import get_mcp_server
from backend_server.src.mcp.tools.analytics_tools import ANALYTICS_TOOL_NAMES
from backend_server.src.mcp.tools.custom_page_tools import CUSTOM_PAGE_TOOL_NAMES
from backend_server.src.mcp.tools.masterchief_tools import MASTERCHIEF_PROPOSE_TOOL_NAMES
from backend_server.src.mcp.utils.lock_ownership import DEVICE_LOCK_TOOL_NAMES
from ..tools.page_interaction import (
    get_available_pages,
    get_page_schema,
    navigate_to_page,
    interact_with_element,
    highlight_element,
    show_toast,
    show_page,
    infer_followup_params,
    _emit as _emit_ui_action,
    get_alerts,
    COMPANION_PAGES,
    PAGE_INTERACTION_TOOLS,
)


class ToolResultCache:
    """Session-based cache for tool call results"""
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)
    
    def _make_key(self, tool_name: str, params: Dict[str, Any]) -> str:
        """Generate cache key from tool name and params"""
        params_str = json.dumps(params, sort_keys=True)
        key_data = f"{tool_name}:{params_str}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]
    
    def get(self, tool_name: str, params: Dict[str, Any], ttl_seconds: int) -> Optional[Dict[str, Any]]:
        """Get cached result if not expired"""
        cache_key = self._make_key(tool_name, params)
        
        if cache_key not in self._cache:
            return None
        
        entry = self._cache[cache_key]
        age = time.time() - entry['timestamp']
        
        # Check TTL (0 = never expire during session)
        if ttl_seconds > 0 and age > ttl_seconds:
            self.logger.debug(f"[cache] {tool_name} expired (age: {age:.1f}s)")
            del self._cache[cache_key]
            return None
        
        self.logger.debug(f"[cache] HIT {tool_name} (age: {age:.1f}s)")
        return entry['result']
    
    def set(self, tool_name: str, params: Dict[str, Any], result: Dict[str, Any]):
        """Store result in cache"""
        cache_key = self._make_key(tool_name, params)
        self._cache[cache_key] = {
            'result': result,
            'timestamp': time.time(),
            'tool_name': tool_name
        }
        self.logger.debug(f"[cache] STORED {tool_name}")
    
    def clear(self):
        """Clear all cached results"""
        self._cache.clear()
        self.logger.debug("[cache] CLEARED")


class ToolBridge:
    """Bridge between agents and MCP tools"""
    
    def __init__(self, session=None, is_background: bool = False):
        self.logger = logging.getLogger(__name__)
        self.mcp_server = get_mcp_server()  # Use singleton
        self._tool_cache = None
        self.session = session
        self.is_background = is_background
        
        # Use session-scoped cache if available, otherwise create new
        # Background agents intentionally don't persist cache across tasks
        if session and '_tool_result_cache' in session.context:
            self._result_cache = session.context['_tool_result_cache']
        else:
            self._result_cache = ToolResultCache()
            if session:
                session.context['_tool_result_cache'] = self._result_cache
        
        self.logger.debug(f"ToolBridge initialized (background={is_background})")
    
    def _get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all available MCP tools (cached)"""
        if self._tool_cache is None:
            self._tool_cache = self.mcp_server.get_available_tools()
            self.logger.info(f"Cached {len(self._tool_cache)} MCP tools")
        return self._tool_cache
    
    def get_tool_definitions(self, tool_names: List[str]) -> List[Dict[str, Any]]:
        """
        Get tool definitions for specified tools in Claude format
        
        Args:
            tool_names: List of tool names to get
            
        Returns:
            List of tool definitions in Claude's expected format
        """
        all_tools = self._get_all_tools()
        tools_by_name = {t['name']: t for t in all_tools}
        
        result = []
        for name in tool_names:
            # UI Interaction tools - manual definitions
            if name == "get_available_pages":
                result.append({
                    "name": "get_available_pages",
                    "description": "Returns a list of all navigable pages in the application with their descriptions. Use this to understand what pages exist.",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                })
                continue
                
            if name == "get_page_schema":
                result.append({
                    "name": "get_page_schema",
                    "description": "Returns the interactive elements available on a specific page. Use this to understand what actions can be performed on a page.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "page_path": {
                                "type": "string",
                                "description": "The page path (e.g., '/device-control', '/test-results/reports')"
                            }
                        },
                        "required": ["page_path"]
                    }
                })
                continue
                
            if name == "navigate_to_page":
                result.append({
                    "name": "navigate_to_page",
                    "description": "Navigates the user's browser to a specific page. Understands natural language like 'go to dashboard', 'navigate to reports', 'show me heatmap'. Available pages: dashboard, device control, ai agent, test builder, campaign builder, test cases, campaigns, requirements, coverage, run tests, run campaigns, deployments, incidents, heatmap, ai queue, test reports, campaign reports, model reports, dependency report, and more.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "page_name": {
                                "type": "string",
                                "description": "Page name or natural language request (e.g., 'dashboard', 'go to heatmap', 'navigate to test builder', 'show me reports')"
                            },
                            "context": {
                                "type": "object",
                                "description": "Optional parameters (e.g., {'device_id': 's21'})"
                            }
                        },
                        "required": ["page_name"]
                    }
                })
                continue
                
            if name == "show_page":
                result.append({
                    "name": "show_page",
                    "description": "Show a real app page, already filtered, in the companion beside the chat. Answer in the chat first (numbers first), then call this. Pick `page` from get_available_pages; resolve names to exact values with the tool named in the page's params (list_hosts, get_execution_results for script names). Set open_now only when the user asked to open the page. If a companion page is shown (see \"Page shown beside the chat\" in your context), a follow-up edits its params: pass the same page with the changed params.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "page": {"type": "string", "enum": list(COMPANION_PAGES)},
                            "params": {"type": "object", "description": "URL filters allowed by the page"},
                            "path_args": {"type": "object", "description": "Values for {kind}/{id} path segments, e.g. {\"kind\": \"script\", \"id\": \"...\"}"},
                            "title": {"type": "string"},
                            "open_now": {"type": "boolean"}
                        },
                        "required": ["page"]
                    }
                })
                continue

            if name == "interact_with_element":
                result.append({
                    "name": "interact_with_element",
                    "description": "Interact with a specific element on the current page. Actions: click, select, filter, open, close, type, scroll_to",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "element_id": {
                                "type": "string",
                                "description": "The element ID from the page schema (e.g., 'reports-table', 'run-btn')"
                            },
                            "action": {
                                "type": "string",
                                "description": "The action to perform (click, select, filter, open, close, type, scroll_to)"
                            },
                            "params": {
                                "type": "object",
                                "description": "Optional parameters for the action (e.g., {'value': 'failed'})"
                            }
                        },
                        "required": ["element_id", "action"]
                    }
                })
                continue
                
            if name == "highlight_element":
                result.append({
                    "name": "highlight_element",
                    "description": "Highlight an element on the page to draw user's attention",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "element_id": {
                                "type": "string",
                                "description": "The element ID to highlight"
                            },
                            "duration_ms": {
                                "type": "integer",
                                "description": "How long to show the highlight (default 2000ms)"
                            }
                        },
                        "required": ["element_id"]
                    }
                })
                continue
                
            if name == "show_toast":
                result.append({
                    "name": "show_toast",
                    "description": "Show a toast notification to the user",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "The message to display"
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["info", "success", "warning", "error"],
                                "description": "Toast severity level"
                            }
                        },
                        "required": ["message"]
                    }
                })
                continue
            
            if name == "get_alerts":
                result.append({
                    "name": "get_alerts",
                    "description": "Fetch alerts from the monitoring system. Returns count and details of active and resolved alerts. Use this to answer questions about alerts/incidents.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["active", "resolved"],
                                "description": "Filter by alert status. Omit to get both active and resolved."
                            },
                            "host_name": {
                                "type": "string",
                                "description": "Filter by host name"
                            },
                            "device_id": {
                                "type": "string",
                                "description": "Filter by device ID"
                            },
                            "incident_type": {
                                "type": "string",
                                "description": "Filter by incident type (e.g., 'freeze', 'blackscreen')"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max alerts to return (default 20)"
                            }
                        },
                        "required": []
                    }
                })
                continue

            # MCP tools
            if name in tools_by_name:
                mcp_tool = tools_by_name[name]
                # Convert MCP format to Claude format
                claude_tool = {
                    "name": mcp_tool['name'],
                    "description": mcp_tool['description'],
                    "input_schema": mcp_tool['inputSchema'],
                }
                result.append(claude_tool)
            elif name in getattr(self.mcp_server, 'HIDDEN_TOOLS', ()):
                # Hidden from discovery, but a skill that lists take_control / release_control by name offers them:
                # "take control of X" is a request the model must be able to answer (TASK-163).
                from backend_server.src.mcp.tool_definitions.build_definitions import get_builder
                hidden = get_builder().get_tool(name) or {}
                result.append({"name": name, "description": hidden.get('description', name),
                               "input_schema": hidden.get('inputSchema') or {"type": "object", "properties": {}}})
            else:
                self.logger.warning(f"Tool not found: {name}")
        
        return result
    
    def execute(self, tool_name: str, params: Dict[str, Any], allowed_tools: List[str] = None, 
                cache_config: Optional[Any] = None) -> Dict[str, Any]:
        """
        Execute an MCP tool or UI interaction tool with result caching
        
        Args:
            tool_name: Name of the tool
            params: Tool parameters
            allowed_tools: Optional list of tools the agent is allowed to use
            cache_config: Optional ToolCacheConfig for this tool
            
        Returns:
            Tool result
            
        Raises:
            ValueError: If tool fails or doesn't exist
        """
        self.logger.info(f"Executing tool: {tool_name}")
        self.logger.debug(f"Params: {params}")

        # Analytics identity and scope are trusted runtime context, never model-provided
        # arguments. Keeping the keys private also keeps credentials/tenant mechanics out
        # of the public tool schema while making cache entries tenant-specific.
        params = dict(params or {})
        self._fill_device_context(tool_name, params)
        # BUG-0914: the page's devices, drones, host desktops and shell commands are a boundary, not a hint.
        if self.session is not None and not self.is_background:
            from agent import device_scope
            reason = device_scope.refusal(tool_name, params, self.session.context,
                                          device_scope.last_user_message(getattr(self.session, "messages", [])))
            if reason:
                self.logger.warning(f"[device-scope] refused {tool_name}: {reason}")
                return {"content": [{"type": "text", "text": f"Refused (device scope): {reason}"}], "isError": True}
        self._note_turn_tool(tool_name, params)
        if tool_name in ANALYTICS_TOOL_NAMES and self.session:
            params.update({
                "_context_team_id": self.session.context.get("team_id"),
                "_context_user_id": self.session.context.get("user_id"),
                "_context_user_email": self.session.context.get("user_email"),
                "_context_user_role": self.session.context.get("user_role"),
                "_context_workspace_id": self.session.context.get("workspace_id"),
                "_context_selected_server": self.session.context.get("selected_server"),
                "_context_selected_server_name": self.session.context.get("selected_server_name"),
                "_context_selected_server_hosts": self.session.context.get("selected_server_hosts"),
                "_context_host_name": self.session.context.get("host_name"),
                "_context_device_id": self.session.context.get("device_id"),
                "_context_userinterface_name": self.session.context.get("userinterface_name"),
                "_context_grafana_base_url": self.session.context.get("grafana_base_url"),
                "_context_named_devices": self.session.context.get("named_devices"),
                "_context_refers_to_selected_device": bool(self.session.context.get("refers_to_selected_device")),
                "_context_selected_device": self.session.context.get("selected_device"),
                "_context_selected_device_foreign": bool(self.session.context.get("selected_device_foreign")),
                "_context_known_device_names": [d.get("device_name") for d in
                                                (self.session.context.get("available_devices") or [])
                                                if isinstance(d, dict) and d.get("device_name")],
            })

        # Who wrote a virtual script is the agent of this session (Forge since TASK-175), never a model
        # argument: the save tool used to stamp every script "atlas".
        if tool_name == "save_virtual_script" and self.session:
            params["_context_agent_id"] = self.session.context.get("agent_id")

        # Custom pages (TASK-139): the caller's identity decides which blocks they may use, so it is
        # always the runtime's, never a model argument.
        if tool_name in CUSTOM_PAGE_TOOL_NAMES and self.session:
            params.update({
                "_context_team_id": self.session.context.get("team_id"),
                "_context_user_id": self.session.context.get("user_id"),
                "_context_user_role": self.session.context.get("user_role"),
            })

        # Masterchief identity: the propose tool writes the audit row directly
        # (the HTTP routes reject the service key, by design). We need the
        # caller's team + identity to write the row, so the bridge injects the
        # same trusted runtime context for propose_masterchief_op.
        if tool_name in MASTERCHIEF_PROPOSE_TOOL_NAMES and self.session:
            params.update({
                "_context_team_id": self.session.context.get("team_id"),
                "_context_user_id": self.session.context.get("user_id"),
                "_context_user_email": self.session.context.get("user_email"),
                "_context_user_role": self.session.context.get("user_role"),
                "_context_workspace_id": self.session.context.get("workspace_id"),
                "_context_selected_server": self.session.context.get("selected_server"),
                "_context_selected_server_name": self.session.context.get("selected_server_name"),
                "_context_selected_server_hosts": self.session.context.get("selected_server_hosts"),
                "_context_host_name": self.session.context.get("host_name"),
                "_context_device_id": self.session.context.get("device_id"),
                "_context_userinterface_name": self.session.context.get("userinterface_name"),
                "_context_grafana_base_url": self.session.context.get("grafana_base_url"),
                "_context_named_devices": self.session.context.get("named_devices"),
                "_context_refers_to_selected_device": bool(self.session.context.get("refers_to_selected_device")),
                "_context_selected_device": self.session.context.get("selected_device"),
                "_context_selected_device_foreign": bool(self.session.context.get("selected_device_foreign")),
                "_context_known_device_names": [d.get("device_name") for d in
                                                (self.session.context.get("available_devices") or [])
                                                if isinstance(d, dict) and d.get("device_name")],
            })

        # Device-lock identity (BUG-0402): this chat's session, the browser tab it was sent from,
        # and its signed-in user, so device tools run only under this caller's own Take Control.
        # Always the runtime's values, never the model's - it cannot claim someone else's lock.
        if tool_name in DEVICE_LOCK_TOOL_NAMES and self.session:
            ctx = self.session.context
            params.update({
                "session_id": self.session.id,
                "_caller_browser_session_id": ctx.get("browser_session_id"),
                "_caller_user_id": None if ctx.get("user_shared") else ctx.get("user_id"),
            })
        
        # Check result cache if enabled
        if cache_config and cache_config.enabled:
            cached_result = self._result_cache.get(tool_name, params, cache_config.ttl_seconds)
            if cached_result is not None:
                print(f"[@ToolBridge] ⚡ {tool_name} (CACHED - no API call)")
                return cached_result
        
        # Log when actually calling the tool
        if cache_config and cache_config.enabled:
            print(f"[@ToolBridge] 🔄 {tool_name} (cache miss - calling API)")
        
        # VALIDATION: Check if tool exists in the system
        # Hidden MCP tools (take_control / release_control) are left out of the model's listing but stay callable.
        all_available = self.get_available_tool_names() + sorted(getattr(self.mcp_server, 'HIDDEN_TOOLS', ()))
        if tool_name not in all_available:
            error_msg = f"❌ Tool '{tool_name}' does not exist. "
            # Suggest similar tools
            similar = [t for t in all_available if tool_name.split('_')[0] in t or t.split('_')[0] in tool_name]
            if similar:
                error_msg += f"Did you mean: {', '.join(similar[:5])}?"
            else:
                error_msg += "Use list_userinterfaces to get tree IDs, then list_navigation_nodes to get nodes."
            self.logger.error(f"Tool not found: {tool_name}")
            return {
                "content": [{"type": "text", "text": error_msg}],
                "isError": True
            }
        
        # VALIDATION: Check if tool is allowed for this agent
        if allowed_tools and tool_name not in allowed_tools:
            error_msg = f"❌ Tool '{tool_name}' is not in your allowed tools list. Use only these tools: {', '.join(allowed_tools[:10])}..."
            self.logger.warning(f"Tool not allowed: {tool_name}")
            return {
                "content": [{"type": "text", "text": error_msg}],
                "isError": True
            }
        
        # UI Interaction tools
        if tool_name == "get_available_pages":
            result = get_available_pages()
            return {"result": result}
            
        sid = self.session.id if self.session else None

        if tool_name == "show_page":
            result = show_page(
                page=params.get("page", ""),
                params=params.get("params"),
                title=params.get("title"),
                open_now=bool(params.get("open_now")) and self._user_asked_to_open(),
                path_args=params.get("path_args"),
                session_id=sid,
                known=self._companion_known(),
                run_exists=self._companion_run_exists,
                defer=self.session.context.setdefault("_turn_offers", []) if self.session else None,
            )
            return {"result": result}

        if tool_name == "get_page_schema":
            result = get_page_schema(params.get("page_path", ""))
            return {"result": result}
            
        if tool_name == "navigate_to_page":
            result = navigate_to_page(
                page_name=params.get("page_name", ""), 
                context=params.get("context"),
                session_id=sid,
            )
            return {"result": result}
            
        if tool_name == "interact_with_element":
            result = interact_with_element(
                element_id=params.get("element_id", ""),
                action=params.get("action", ""),
                params=params.get("params"),
                session_id=sid,
            )
            return {"result": result}
            
        if tool_name == "highlight_element":
            result = highlight_element(
                element_id=params.get("element_id", ""),
                duration_ms=params.get("duration_ms", 2000),
                session_id=sid,
            )
            return {"result": result}
            
        if tool_name == "show_toast":
            result = show_toast(
                message=params.get("message", ""),
                severity=params.get("severity", "info"),
                session_id=sid,
            )
            return {"result": result}
        
        if tool_name == "get_alerts":
            result = get_alerts(
                status=params.get("status"),
                host_name=params.get("host_name"),
                device_id=params.get("device_id"),
                incident_type=params.get("incident_type"),
                limit=params.get("limit", 20)
            )
            return {"result": result}

        # MCP tools
        call_params = params
        if tool_name == "navigate_to_node" and self.session:
            # Stop cancels a running goto (TASK-140 G7): the tool polls this; it never reaches the host
            # or the tool schema, and is not part of the cache key above.
            session = self.session
            call_params = {**params, "_should_cancel": lambda: bool(session.cancelled)}
        result = self.mcp_server.handle_tool_call(tool_name, call_params)
        if tool_name == "execute_script" and self.session and isinstance(result, dict):
            calls = self.session.context.get("_turn_tools") or []
            task = (result.get("structuredContent") or {}).get("execution_id")
            if calls and calls[-1][0] == tool_name and task:
                calls[-1][1]["_task"] = task
        if tool_name == "get_execution_results" and self.session and isinstance(result, dict):
            calls = self.session.context.get("_turn_tools") or []
            if calls and calls[-1][0] == tool_name:
                calls[-1][1]["_ids"] = [r.get("id") for r in (result.get("results") or []) if r.get("id")]
        
        # Store in cache if enabled
        if cache_config and cache_config.enabled:
            self._result_cache.set(tool_name, params, result)
        
        self.logger.info(f"Tool {tool_name} completed")
        return result
    
    # Device tools that act on one device: an omitted host_name/device_id is this chat's device. The system
    # prompt names it, yet the model drops it now and then (TASK-135: "host_name required" from
    # dump_ui_elements). A value the model gives is kept, so it can still name another device.
    DEVICE_CONTEXT_TOOL_NAMES = DEVICE_LOCK_TOOL_NAMES | {
        "dump_ui_elements", "capture_screenshot", "list_actions", "list_verifications", "verify_node",
        "save_node_screenshot", "execute_edge", "analyze_screen_for_action", "analyze_screen_for_verification"}

    def _fill_device_context(self, tool_name: str, params: Dict[str, Any]) -> None:
        if self.session is None or tool_name not in self.DEVICE_CONTEXT_TOOL_NAMES or params.get("host_name"):
            return
        ctx = self.session.context
        if ctx.get("host_name"):
            params["host_name"] = ctx["host_name"]
            if not params.get("device_id") and ctx.get("device_id"):
                params["device_id"] = ctx["device_id"]

    # Tool-call argument -> catalogue param, for the end-of-turn companion offer.
    _FALLBACK_ARGS = {"host_name": "host", "device_name": "device", "device_id": "device", "script_name": "script"}
    _FALLBACK_SKIP = {"list_hosts", "list_testcases", "show_page"}

    def _note_turn_tool(self, tool_name: str, params: Dict[str, Any]) -> None:
        if self.session is None:
            return
        calls = self.session.context.setdefault("_turn_tools", [])
        calls.append((tool_name, {k: v for k, v in params.items() if not k.startswith("_")}))

    def companion_fallback(self) -> Optional[str]:
        """End of an Atlas turn: if show_page was not called but a catalogue page's data tool was,
        offer that page ourselves. Params come from the tool call's arguments and pass the same
        show_page checks; anything that fails sends nothing."""
        offers = (self.session.context.get("_turn_offers") if self.session else None) or []
        if offers:
            last = offers[-1]
            self.session.context["_turn_offers"] = []
            _emit_ui_action(self.session.id, last)
            return "sent"
        calls = (self.session.context.get("_turn_tools") if self.session else None) or []
        if any(name == "show_page" for name, _ in calls):
            return None
        if not any(name not in self._FALLBACK_SKIP for name, _ in calls):
            return self._followup_from_message()
        for tool_name, args in reversed(calls):
            if tool_name in self._FALLBACK_SKIP:
                continue
            if tool_name == "execute_script" and args.get("_task"):
                # a run was started: its live page is the companion
                out = show_page("run_live", {}, path_args={"taskId": args["_task"]}, session_id=self.session.id)
                self.logger.info(f"companion fallback run_live {args['_task']}: {out}")
                return out if out.startswith("✅") else None
            page = next((k for k, e in COMPANION_PAGES.items() if e["data_tool"] == tool_name), None)
            if not page:
                continue
            allowed = COMPANION_PAGES[page]["params"]
            params = {self._FALLBACK_ARGS[k]: v for k, v in args.items() if k in self._FALLBACK_ARGS and v}
            if args.get("success") in (True, False):
                params["status"] = "passed" if args["success"] else "failed"
            params = {k: v for k, v in params.items() if k in allowed}
            ids = args.get("_ids") or []
            if page == "test_reports" and args.get("limit") == 1 and len(ids) == 1:
                # one run asked for, one run found: its summary is the page
                out = show_page("run_summary", {}, path_args={"kind": "script", "id": ids[0]},
                                session_id=self.session.id, run_exists=self._companion_run_exists)
                self.logger.info(f"companion fallback run_summary {ids[0]}: {out}")
                return out if out.startswith("✅") else None
            out = show_page(page, params, session_id=self.session.id, known=self._companion_known())
            self.logger.info(f"companion fallback {page} {params}: {out}")
            return out if out.startswith("✅") else None
        return None

    def _followup_from_message(self) -> Optional[str]:
        """No data tool and no show_page this turn, a companion page is shown: work out the changed
        filters from the user's own message and offer the same page again. No re-query."""
        if self.session is None:
            return None
        shown = str(self.session.context.get("companion") or "")
        name, _, rest = shown.partition(" — ")
        page = next((k for k, e in COMPANION_PAGES.items() if e["name"] == name.strip()), None)
        msgs = [m for m in self.session.messages if m.get("role") == "user"]
        if not page or not msgs or "{" in COMPANION_PAGES[page]["path"]:
            return None
        current = dict(p.split("=", 1) for p in rest.split(", ") if "=" in p)
        known = self._companion_known()
        params = infer_followup_params(str(msgs[-1].get("content", "")), page, current, known)
        if not params:
            return None
        out = show_page(page, params, session_id=self.session.id, known=known)
        self.logger.info(f"companion follow-up {page} {params}: {out}")
        return out if out.startswith("✅") else None

    def _user_asked_to_open(self) -> bool:
        """open_now is honoured only when the user's last message asks to open/show a page."""
        import re
        msgs = [m for m in (self.session.messages if self.session else []) if m.get("role") == "user"]
        text = str(msgs[-1].get("content", "")) if msgs else ""
        return bool(re.search(r"\b(open|show|display|pull up|bring up)\b", text.split("Companion:")[0], re.I))

    def _companion_known(self) -> Dict[str, Any]:
        """Real host / device / script names for show_page to check against (never a guess)."""
        ctx = self.session.context if self.session else {}
        devices: Dict[str, List[str]] = {}
        for d in ctx.get("available_devices") or []:
            if isinstance(d, dict) and d.get("host_name"):
                names = devices.setdefault(d["host_name"], [])
                names.extend(n for n in (d.get("device_name"), d.get("device_id")) if n and n not in names)
        hosts = sorted(set(devices) | set(ctx.get("selected_server_hosts") or []))
        known: Dict[str, Any] = {"host": hosts, "device": devices}
        try:
            from shared.src.lib.utils.supabase_utils import get_supabase_client
            rows = (get_supabase_client().table("script_results").select("script_name")
                    .eq("team_id", ctx.get("team_id")).order("created_at", desc=True).limit(2000).execute().data)
            known["script"] = sorted({r["script_name"] for r in rows if r.get("script_name")})
        except Exception as e:
            self.logger.warning(f"show_page: script names unavailable: {e}")
        return known

    def _companion_run_exists(self, kind: str, run_id: str) -> bool:
        """Does this team have a script/campaign run with this id?"""
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        table, col = ("script_results", "id") if kind == "script" else ("campaign_executions", "id")
        team_id = self.session.context.get("team_id") if self.session else None
        try:
            rows = get_supabase_client().table(table).select(col).eq(col, run_id).eq("team_id", team_id).limit(1).execute().data
            return bool(rows)
        except Exception as e:
            self.logger.warning(f"show_page: run lookup failed: {e}")
            return False

    def get_available_tool_names(self) -> List[str]:
        """Get list of all available tool names"""
        base_tools = [t['name'] for t in self._get_all_tools()]
        return base_tools + PAGE_INTERACTION_TOOLS
