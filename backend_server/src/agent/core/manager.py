"""
QA Manager Agent - Skill-Based Architecture with Prompt Caching

The orchestrator dynamically loads skills based on user requests:
- Router mode: Safe direct tools for simple read-only questions
- Skill mode: Full tool access from loaded skill
- Prompt Caching: System prompt and tools are cached for 90% cost reduction
- Queue Worker: Background thread for processing Redis queue items

Skills are defined in YAML files and provide focused capabilities.
"""

import re
import logging
import time
import threading
import asyncio
import json
import os
from typing import Dict, Any, AsyncGenerator, Optional, List

from shared.src.lib.ai.config import LANGFUSE_ENABLED, get_active_ai_settings, get_provider_api_key
from ..observability import track_generation, track_tool_call, flush
from shared.src.lib.ai.provider_client import create_provider_client
from .session import Session, SessionManager
from .tool_bridge import ToolBridge
from .message_types import EventType, AgentEvent
from .sherlock_handler import SherlockHandler
from .nightwatch_handler import NightwatchHandler
from backend_server.src.mcp.tool_definitions.build_definitions import get_builder

# Import shared Redis queue processor (supports both local and Upstash Redis)
from shared.src.lib.utils.redis_queue import get_queue_processor


class QAManagerAgent:
    """
    QA Manager - Skill-Based Orchestrator with Prompt Caching
    
    Operates in two modes:
    1. Router Mode: Uses minimal tools, decides which skill to load
    2. Skill Mode: Uses tools from the loaded skill
    
    Uses provider-aware tool calling while preserving Anthropic prompt caching when selected.
    
    Background Worker Configuration:
    - Alert processing filters are handled by agent-specific handlers (e.g., NightwatchHandler)
    - Each handler implements its own filtering logic (duration, rate limiting, etc.)
    """

    _ATLAS_DIRECT_BLOCKED_CATEGORIES = {'admin', 'ai'}
    # ai_userinterface WRITES are intentionally router-blocked: writes require the
    # READ-BEFORE-WRITE discipline baked into the `ai-userinterface` skill prompt.
    # Router mode keeps the reads (resolve, get, list, history) and the revert/
    # supersede tools; any mutation-style write must trigger `LOAD SKILL [ai-userinterface]`.
    _ATLAS_DIRECT_BLOCKED_EXACT: set[str] = {
        'create_ai_userinterface',
        'update_ai_userinterface',
        'add_ai_userinterface_screen',
        'add_ai_userinterface_transition',
        'add_ai_userinterface_verification',
        'add_ai_userinterface_task',
        'add_ai_userinterface_quirk',
        'add_ai_userinterface_known_hardware',
        'add_ai_userinterface_fingerprint',
    }
    _ATLAS_DIRECT_BLOCKED_PREFIXES = ('delete_',)
    _ATLAS_ROUTER_FALLBACK_TOOLS = (
        'list_hosts',
        'get_device_info',
        'list_userinterfaces',
        'list_testcases',
        'list_campaigns',
        'list_requirements',
        'search_docs',
        # AI UserInterface knowledge base — read tools always in scope so any
        # add_ai_userinterface_* write surfaced by query scoring has its corresponding
        # read available too. Prevents Atlas from writing without first reading
        # (root cause of the 2026-04-22 RIGHT x 8 hallucination — see CONTRACTS.md §18a).
        'resolve_ai_userinterface',
        'get_ai_userinterface',
        'list_ai_userinterfaces',
        # Visual verification — Atlas needs this when navigating any device.
        'capture_screenshot',
    )
    _ATLAS_ROUTER_CATEGORY_HINTS = {
        'device': {'device', 'devices', 'host', 'hosts', 'status'},
        'testcase': {'test', 'tests', 'testcase', 'testcases', 'case', 'cases'},
        'campaign': {'campaign', 'campaigns'},
        'requirements': {'requirement', 'requirements', 'coverage'},
        'userinterface': {'interface', 'interfaces', 'ui', 'uis', 'userinterface', 'userinterfaces'},
        # Distinct from `userinterface` above: this is the AI-learned narrative knowledge
        # base (ai_userinterfaces tables), not the production navigation_trees system.
        # Token "navigate" intentionally appears here AND in 'navigation' — both can be
        # right depending on context; scoring picks the better fit.
        'ai_userinterface': {'ai', 'learned', 'knowledge', 'verified', 'flow', 'flows', 'quirk',
                             'quirks', 'fingerprint', 'fingerprints', 'firmware', 'about',
                             'navigate', 'screen', 'example', 'v2', 'variant'},
        'tree': {'node', 'nodes', 'edge', 'edges', 'tree', 'screen'},
        'navigation': {'navigate', 'navigation', 'node', 'screen'},
        'docs': {'doc', 'docs', 'document', 'documentation', 'read', 'search'},
        'script': {'script', 'scripts'},
        'analysis': {'analysis', 'result', 'results', 'report', 'reports', 'alert', 'alerts'},
        'logs': {'log', 'logs', 'service', 'services'},
        'verification': {'verify', 'verification', 'verify_node', 'ui', 'screen'},
        'screenshot': {'screenshot', 'capture', 'image'},
        'action': {'action', 'actions'},
        'control': {'control', 'take', 'release'},
    }

    def __init__(self, api_key: Optional[str] = None, user_identifier: Optional[str] = None, agent_id: Optional[str] = None, session: Optional[any] = None, is_background: bool = False):
        self.logger = logging.getLogger(__name__)
        self.user_identifier = user_identifier
        self._api_key = api_key
        self._client = None
        self._session = session  # Store session reference
        self._is_background = is_background
        self.tool_bridge = ToolBridge(session=session, is_background=is_background)
        
        # Load from YAML
        self.agent_id = agent_id or 'assistant'
        self.agent_config = self._load_agent_config(self.agent_id)
        
        # Active skill (None = router mode)
        self._active_skill = None
        
        # Queue worker state
        self._queue_worker_running = False
        self._queue_worker_thread: Optional[threading.Thread] = None
        self._session_manager = SessionManager()
        
        # Agent-specific handlers (lazy init based on agent_id)
        self._sherlock_handler: Optional[SherlockHandler] = None
        self._nightwatch_handler: Optional[NightwatchHandler] = None
        
        # Load skills on startup
        from ..skills import SkillLoader
        SkillLoader.load_all_skills()
        
        self.logger.info(f"Manager initialized as {self.agent_config['nickname']} ({self.agent_id})")
    
    def _load_agent_config(self, agent_id: str) -> Dict[str, Any]:
        """Load agent config from YAML registry"""
        from ..registry import get_agent_registry
        
        registry = get_agent_registry()
        agent_def = registry.get(agent_id)
        
        if not agent_def:
            raise ValueError(f"Agent '{agent_id}' not found in registry.")
        
        metadata = agent_def.metadata
        config = agent_def.config
        platform = config.platform_filter if config else None
        
        # Get background queues from config
        background_queues = []
        if config and hasattr(config, 'background_queues'):
            background_queues = config.background_queues or []
        
        # Get dry_run flag from config
        dry_run = False
        if config and hasattr(config, 'dry_run'):
            dry_run = config.dry_run or False

        # Get prompt presets from metadata
        prompt_presets = []
        if metadata and hasattr(metadata, 'prompt_presets'):
            prompt_presets = metadata.prompt_presets or []

        return {
            'name': metadata.name,
            'nickname': metadata.nickname or metadata.name,
            'specialty': metadata.description,
            'platform': platform or 'all',
            'skills': agent_def.skills or [],
            'available_skills': getattr(agent_def, 'available_skills', []) or [],
            'subagents': [s.id for s in (agent_def.subagents or [])],
            'background_queues': background_queues,
            'dry_run': dry_run,
            'prompt_presets': prompt_presets,
        }
    
    @property
    def nickname(self) -> str:
        return self.agent_config['nickname']

    @property
    def prompt_presets(self) -> List[Dict[str, Any]]:
        """Get prompt presets with categories for this agent"""
        return self.agent_config.get('prompt_presets', [])

    @property
    def active_skill(self):
        """Currently loaded skill (None if in router mode)"""
        return self._active_skill
    
    def load_skill(self, skill_name: str) -> bool:
        """Load a skill by name"""
        from ..skills import SkillLoader
        
        available = self.agent_config.get('available_skills', [])
        if skill_name not in available:
            self.logger.warning(f"Skill '{skill_name}' not in available_skills: {available}")
            return False
        
        skill = SkillLoader.get_skill(skill_name)
        if not skill:
            self.logger.error(f"Skill '{skill_name}' not found in definitions")
            return False
        
        self._active_skill = skill
        self.logger.info(f"Loaded skill: {skill_name} ({len(skill.tools)} tools)")
        return True
    
    def unload_skill(self) -> None:
        """Unload current skill and return to router mode"""
        if self._active_skill:
            self.logger.info(f"Unloaded skill: {self._active_skill.name}")
        self._active_skill = None
    
    def _parse_skill_command(self, text: str) -> Optional[str]:
        """Parse 'LOAD SKILL [skill-name]' from Claude's response"""
        match = re.search(r'LOAD\s+SKILL\s+([\w-]+)', text, re.IGNORECASE)
        return match.group(1).lower() if match else None
    
    def get_system_prompt(self, context: Dict[str, Any] = None, message: str = "", router_tools: Optional[List[str]] = None) -> str:
        """Build system prompt based on current mode"""
        if self._active_skill:
            return self._build_skill_prompt(context)
        return self._build_router_prompt(context, message, router_tools)
    
    def _build_context_section(self, ctx: Dict[str, Any], skill: Optional[Any] = None) -> str:
        """Build context section for system prompt"""
        ctx = ctx or {}

        # If no skill specified (router mode), include all context
        if skill is None or not hasattr(skill, 'required_context') or not skill.required_context:
            return self._build_full_context_section(ctx)

        # Filter context based on skill's required_context
        required_keys = set(skill.required_context)
        filtered_ctx = {k: v for k, v in ctx.items() if k in required_keys}

        # Build context section with filtered data
        return self._build_full_context_section(filtered_ctx)

    def _build_full_context_section(self, ctx: Dict[str, Any]) -> str:
        """Build complete context section (used by router and when no filtering needed)"""
        # Extract navigation context
        host_name = ctx.get('host_name', '')
        device_id = ctx.get('device_id', '')
        userinterface_name = ctx.get('userinterface_name', '')
        tree_id = ctx.get('tree_id', '')
        testcase_id = ctx.get('testcase_id', '')
        campaign_id = ctx.get('campaign_id', '')
        available_devices = ctx.get('available_devices', [])
        available_userinterfaces = ctx.get('available_userinterfaces', [])
        available_testcases = ctx.get('available_testcases', [])
        available_campaigns = ctx.get('available_campaigns', [])

        context_parts = []

        if host_name or device_id:
            context_parts.append(f"**Current Device:** host_name='{host_name}', device_id='{device_id}'")

        if userinterface_name:
            interface_info = f"**Current Interface:** userinterface_name='{userinterface_name}'"
            if tree_id:
                interface_info += f", tree_id='{tree_id}'"
            context_parts.append(interface_info)

        if testcase_id:
            context_parts.append(f"**Current Test Case:** testcase_id='{testcase_id}'")

        if campaign_id:
            context_parts.append(f"**Current Campaign:** campaign_id='{campaign_id}'")

        if available_devices:
            device_list = [f"{d.get('device_name', 'unknown')} (host_name='{d.get('host_name', 'unknown')}', device_id='{d.get('device_id', 'unknown')}')" for d in available_devices[:10]]
            if len(available_devices) > 10:
                device_list.append(f"... and {len(available_devices) - 10} more")
            context_parts.append(f"**Available Devices:** {', '.join(device_list)}")
            context_parts.append("device_id is scoped per host: always pass both host_name and device_id exactly as listed above (never the device name). The same device_id on different hosts refers to different physical devices — this is normal, not a duplicate.")

        if available_userinterfaces:
            interface_list = [ui.get('name', ui.get('userinterface_name', 'unknown')) for ui in available_userinterfaces[:10]]
            if len(available_userinterfaces) > 10:
                interface_list.append(f"... and {len(available_userinterfaces) - 10} more")
            context_parts.append(f"**Available Interfaces:** {', '.join(interface_list)}")

        if available_testcases:
            testcase_list = [tc.get('name', tc.get('testcase_name', 'unknown')) for tc in available_testcases[:10]]
            if len(available_testcases) > 10:
                testcase_list.append(f"... and {len(available_testcases) - 10} more")
            context_parts.append(f"**Available Test Cases:** {', '.join(testcase_list)}")

        if available_campaigns:
            campaign_list = [c.get('name', c.get('campaign_name', 'unknown')) for c in available_campaigns[:10]]
            if len(available_campaigns) > 10:
                campaign_list.append(f"... and {len(available_campaigns) - 10} more")
            context_parts.append(f"**Available Campaigns:** {', '.join(campaign_list)}")

        if context_parts:
            return "\n".join(context_parts) + "\n\n"

        return ""
    
    def _detect_device_platform(self, ctx: Dict[str, Any]) -> Optional[str]:
        """Detect device platform from context for skill filtering"""
        # Check device info first
        available_devices = ctx.get('available_devices', [])
        if available_devices:
            # Get the first device (assuming single device context)
            device = available_devices[0] if available_devices else {}
            device_model = device.get('device_model', '').lower()

            # Map device models to platforms
            if 'android' in device_model or 'mobile' in device_model:
                return 'mobile'
            elif 'stb' in device_model or 'set-top' in device_model:
                return 'stb'
            elif 'web' in device_model or device_model == 'web':
                return 'web'

        # Check userinterface name for clues
        userinterface_name = ctx.get('userinterface_name', '').lower()
        if 'mobile' in userinterface_name or 'android' in userinterface_name:
            return 'mobile'  # Android TV is mobile platform
        elif 'stb' in userinterface_name:
            return 'stb'

        return None

    def _build_router_prompt(self, ctx: Dict[str, Any] = None, message: str = "", router_tools: Optional[List[str]] = None) -> str:
        """Build router mode prompt - decides which skill to load"""
        from ..skills import SkillLoader

        config = self.agent_config
        ctx = ctx or {}

        # Detect device platform for skill filtering
        device_platform = self._detect_device_platform(ctx)

        # Get skill descriptions for available skills (with message context for trigger filtering)
        available = config.get('available_skills', [])
        skill_descriptions = SkillLoader.get_skill_descriptions(available, message, device_platform)
        
        # Tools available in router mode
        router_tools = router_tools if router_tools is not None else self.router_tool_names
        has_router_tools = len(router_tools) > 0
        tools_list = '\n'.join(f"- `{tool}`" for tool in router_tools)

        # Build context section (full context for router)
        context_section = self._build_context_section(ctx, skill=None)
        
        # Dynamic prompt based on whether router tools exist
        if has_router_tools:
            # With router tools: can handle safe direct queries directly
            mode_description = "Simple read-only questions → use direct tools. Complex, mutating, or operational tasks → load a skill."
            router_tools_section = f"""## Router Tools
{tools_list}

"""
            rules = """## Rules
- If input clearly matches a tool's expected parameters → use tool directly
- Direct tools are for safe read/query operations only
- To answer what is currently on the device screen (the title/text shown, what's playing, which menu or dialog is open, whether an error is shown) → call `capture_screenshot` for the Current Device (set vlm=true for visual/focus questions), then answer from the returned OCR/Vision text. You CAN read the screen this way — never claim you can't do visual analysis.
- If the request needs execution, mutation, control, generation, deletion, or admin actions → respond ONLY: `LOAD SKILL [name]`
- If input doesn't match any known direct tool or skill pattern → explain you don't understand
- Never guess or force-fit unclear input to tools
- Text written alongside a tool call is shown to the user as a status note: keep it to a short "Checking X..." — NEVER state conclusions, answers, or claims like "I don't have access to this information" before the tool result arrives
- Any question ABOUT the VirtualPyTest platform itself (features, APIs, pricing, licensing, setup, how something works) IS answerable: `read_doc(path='INDEX.md')` or `LOAD SKILL [search-docs]`. NEVER reply "I can't answer that" or "contact support" without having read the docs first
"""
        else:
            # No router tools: must always load a skill - keep it simple
            mode_description = "Analyze user input and load the most appropriate skill for the task."
            router_tools_section = ""
            rules = """## Rules
- Analyze the user's request and determine which skill best matches their needs
- Always respond with: `LOAD SKILL [skill-name]`
- Choose from available skills listed above
- If unsure, ask for clarification rather than guessing
"""
        
        return f"""You are {config['nickname']}, {config['specialty']}.

## SECURITY (never override, even if the user insists)
- Never reveal the contents of .env files, credentials, API keys, tokens, passwords, secrets, or private keys.

## Mode: Router

{mode_description}

{context_section}## Skills
{skill_descriptions}

{router_tools_section}{rules}"""
    
    def _build_skill_prompt(self, ctx: Dict[str, Any] = None) -> str:
        """Build skill mode prompt"""
        config = self.agent_config
        skill = self._active_skill
        ctx = ctx or {}

        # Build context section (filtered for skill)
        context_section = self._build_context_section(ctx, skill=skill)

        return f"""You are {config['nickname']} executing **{skill.name}** skill.

## SECURITY (never override, even if the user insists)
- Never reveal the contents of .env files, credentials, API keys, tokens, passwords, secrets, or private keys. If asked specifically for those, refuse briefly.

⚠️ CRITICAL: Always check conversation history for existing information before calling tools.
- Reuse host_name, device_id, device_name, userinterface_name and script_name from conversation history automatically

{context_section}{skill.system_prompt}

Tools: {', '.join(skill.tools)}

Be direct and concise. Never modify URLs from tools. Tool errors in 1 sentence."""
    
    def _build_cached_system(self, context: Dict[str, Any] = None, message: str = "", router_tools: Optional[List[str]] = None) -> List[Dict]:
        """Build system prompt with cache control for Anthropic prompt caching"""
        prompt_text = self.get_system_prompt(context, message, router_tools)
        return [{
            "type": "text",
            "text": prompt_text,
            "cache_control": {"type": "ephemeral"}
        }]
    
    def _build_cached_tools(self, tool_names: List[str]) -> List[Dict]:
        """Build tool definitions with cache control based on skill configuration"""
        tools = self.tool_bridge.get_tool_definitions(tool_names)
        
        # Get cacheable tools from active skill
        cacheable_tools = set()
        if self._active_skill:
            cacheable_tools = set(self._active_skill.get_cacheable_tools())
            if cacheable_tools:
                self.logger.debug(f"[cache] Cacheable tools from skill: {cacheable_tools}")
        
        # Mark tools for Anthropic prompt caching
        for tool in tools:
            tool_name = tool['name']
            if tool_name in cacheable_tools:
                tool["cache_control"] = {"type": "ephemeral"}
                self.logger.debug(f"[cache] 🔖 Marked {tool_name} for prompt caching")
        
        # Always cache the last tool (Anthropic best practice)
        if tools and tools[-1].get('cache_control') is None:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        
        return tools

    def _log_turn_state(self, session: Session, system_prompt: List[Dict], turn_messages: List[Dict], incoming_message: str, is_delegated: bool) -> None:
        """Log the raw prompt (system + messages) being sent to the model"""
        print(f"[TURN] Incoming message: {incoming_message[:120]}{'...' if len(incoming_message) > 120 else ''}")
        print(f"[TURN] Full conversation: {len(turn_messages)} messages (all turns included)")

        # Show system prompt
        print("---------------- SYSTEM PROMPT ----------------")
        try:
            print(json.dumps(system_prompt, ensure_ascii=False, indent=2))
        except Exception:
            print(str(system_prompt))
        print("-----------------------------------------------")

        # Separate history messages from current prompt
        if len(turn_messages) > 1:
            history_messages = turn_messages[:-1]  # All messages except the last one
            current_prompt = turn_messages[-1]     # The last message (current user input)

            print("---------------- HISTORY MESSAGES ----------------")
            try:
                print(json.dumps(history_messages, ensure_ascii=False, indent=2))
            except Exception:
                print(str(history_messages))
            print("--------------------------------------------------")

            print("---------------- CURRENT PROMPT ----------------")
            try:
                print(json.dumps(current_prompt, ensure_ascii=False, indent=2))
            except Exception:
                print(str(current_prompt))
            print("-----------------------------------------------")
        else:
            # Only one message (current prompt)
            print("---------------- CURRENT PROMPT ----------------")
            try:
                print(json.dumps(turn_messages, ensure_ascii=False, indent=2))
            except Exception:
                print(str(turn_messages))
            print("-----------------------------------------------")
    
    def _update_conversation_summary(self, session: Session, user_msg: str, ai_response: str, tool_calls: List[Dict]):
        """
        Update rolling 3-line conversation summary after each turn.
        Summary captures key actions/context from the conversation.
        """
        # Get existing summary
        existing_summary = session.get_context('conversation_summary', '')
        
        # Build this turn's summary line
        # Extract key action from tools or response
        action_summary = ""
        if tool_calls:
            # Summarize main tool action
            main_tool = tool_calls[0]['tool_name']
            params = tool_calls[0].get('params', {})
            
            # Extract key info based on tool type
            if 'navigate' in main_tool.lower():
                target = params.get('target_node_label', params.get('node_id', ''))
                ui = params.get('userinterface_name', '')
                action_summary = f"Navigated to '{target}'" + (f" on {ui}" if ui else "")
            elif 'take_control' in main_tool.lower():
                host = params.get('host_name', '')
                device = params.get('device_id', '')
                action_summary = f"Took control of {device} on {host}"
            elif 'click' in main_tool.lower() or 'execute' in main_tool.lower():
                action = params.get('action_type', params.get('command', 'action'))
                action_summary = f"Executed {action}"
            else:
                action_summary = f"Used {main_tool}"
        else:
            # No tools - use truncated response
            action_summary = ai_response[:50] + "..." if len(ai_response) > 50 else ai_response
        
        # Build new summary line: "User asked X → AI did Y"
        user_brief = user_msg[:30] + "..." if len(user_msg) > 30 else user_msg
        new_line = f"• {user_brief} → {action_summary}"
        
        # Combine with existing, keep only last 3 lines
        if existing_summary:
            lines = existing_summary.strip().split('\n')
            lines.append(new_line)
            # Keep only last 3
            lines = lines[-3:]
            new_summary = '\n'.join(lines)
        else:
            new_summary = new_line
        
        session.set_context('conversation_summary', new_summary)
        print(f"[SUMMARY] Updated: {new_summary}")
    
    @property
    def router_tool_names(self) -> list[str]:
        """Get router-mode tool names."""
        if self.agent_id != 'assistant':
            return self.agent_config.get('skills', [])

        builder = get_builder()
        category_by_tool = {}
        for category, definitions in builder._definitions.items():
            for definition in definitions:
                category_by_tool[definition['name']] = category

        safe_tools: list[str] = []
        for tool_name in sorted(category_by_tool):
            category = category_by_tool[tool_name]

            if category in self._ATLAS_DIRECT_BLOCKED_CATEGORIES:
                continue
            if tool_name in self._ATLAS_DIRECT_BLOCKED_EXACT:
                continue
            if tool_name.startswith(self._ATLAS_DIRECT_BLOCKED_PREFIXES):
                continue

            safe_tools.append(tool_name)

        return safe_tools

    def _tokenize_router_query(self, message: str) -> set[str]:
        """Tokenize and lightly normalize a router query for tool matching."""
        raw_tokens = {token for token in re.split(r'[^a-z0-9_]+', message.lower()) if token}
        expanded_tokens = set(raw_tokens)

        for token in list(raw_tokens):
            if token.endswith('s') and len(token) > 3:
                expanded_tokens.add(token[:-1])
            if token.endswith('es') and len(token) > 4:
                expanded_tokens.add(token[:-2])

        return expanded_tokens

    def _select_router_tools_for_message(self, message: str) -> list[str]:
        """Select a query-relevant subset of Atlas direct tools for this turn.

        Atlas keeps a broad direct allowlist, but sending every safe tool schema in
        router mode creates excessive latency and poor model routing. This narrows
        the tool payload per turn while preserving the broader security policy.
        """
        safe_tools = self.router_tool_names
        if len(safe_tools) <= 16:
            return safe_tools

        builder = get_builder()
        category_by_tool = {}
        description_by_tool = {}
        for category, definitions in builder._definitions.items():
            for definition in definitions:
                category_by_tool[definition['name']] = category
                description_by_tool[definition['name']] = definition.get('description', '')

        query_tokens = self._tokenize_router_query(message)
        scored: list[tuple[int, str]] = []

        for tool_name in safe_tools:
            score = 0
            name_tokens = self._tokenize_router_query(tool_name.replace('_', ' '))
            category = category_by_tool.get(tool_name, '')
            description_tokens = self._tokenize_router_query(description_by_tool.get(tool_name, ''))

            overlap = query_tokens & name_tokens
            if overlap:
                score += 8 + len(overlap) * 3

            description_overlap = query_tokens & description_tokens
            if description_overlap:
                score += len(description_overlap) * 2

            category_hints = self._ATLAS_ROUTER_CATEGORY_HINTS.get(category, set())
            if query_tokens & category_hints:
                score += 5

            if 'list' in query_tokens and tool_name.startswith('list_'):
                score += 2
            if any(token in query_tokens for token in ('get', 'show', 'status')) and tool_name.startswith('get_'):
                score += 2

            if score > 0:
                scored.append((score, tool_name))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [tool_name for _, tool_name in scored[:12]]

        if not selected:
            selected = [tool for tool in self._ATLAS_ROUTER_FALLBACK_TOOLS if tool in safe_tools]

        for tool in self._ATLAS_ROUTER_FALLBACK_TOOLS:
            if tool in safe_tools and tool not in selected and len(selected) < 12:
                selected.append(tool)

        # The router rules name read_doc(path='INDEX.md') as the answer path
        # for ANY platform question, so the docs tools must always be offered
        # — even when 12 higher-scoring tools fill the quota. Observed: "what
        # is a navigation tree" scored only navigation tools, and the model,
        # told to read_doc but not given it, flailed into crawl_app /
        # list_navigation_nodes and errored the chat.
        needed = [t for t in ('read_doc', 'search_docs')
                  if t in safe_tools and t not in selected]
        if needed:
            if len(selected) + len(needed) > 12:
                selected = selected[:12 - len(needed)]
            selected.extend(needed)

        return selected

    @property
    def tool_names(self) -> list[str]:
        """Get current tool names based on mode"""
        if self._active_skill:
            return self._active_skill.tools
        return self.router_tool_names
    
    def _get_api_key_safe(self) -> Optional[str]:
        try:
            return self._api_key or get_provider_api_key(identifier=self.user_identifier)
        except ValueError:
            return None

    @property
    def ai_settings(self) -> dict[str, Any]:
        return get_active_ai_settings(self.user_identifier)

    @property
    def provider(self) -> str:
        return self.ai_settings["provider"]

    @property
    def model(self) -> str:
        return self.ai_settings["model"]
    
    @property
    def client(self):
        if self._client is None:
            key = self._get_api_key_safe()
            if not key:
                raise ValueError(f"{self.ai_settings['api_key_env']} not configured.")
            self._client = create_provider_client(self.provider, key)
        return self._client
    
    @property
    def api_key_configured(self) -> bool:
        return self._get_api_key_safe() is not None
    
    async def process_message(self, message: str, session: Session, _is_delegated: bool = False) -> AsyncGenerator[AgentEvent, None]:
        """Process user message with skill-based routing and prompt caching"""
        print(f"\n{'='*60}")
        print(f"[AGENT] {self.nickname} | skill={self._active_skill.name if self._active_skill else 'router'}")
        print(f"[AGENT] message={message[:50]}...")
        print(f"{'='*60}")
        self.logger.info(f"[{self.nickname}] Processing: {message[:100]}...")
        
        if not self.api_key_configured:
            yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content="API key not configured.")
            if not _is_delegated:
                yield AgentEvent(type=EventType.SESSION_ENDED, agent=self.nickname, content="Session ended")
            return
        
        # Context window compaction (only for root agent)
        if not _is_delegated and session.needs_compaction(threshold=50):
            yield AgentEvent(type=EventType.THINKING, agent="System", content="Compacting history...")
            msgs = session.get_messages_for_summary()
            if msgs:
                try:
                    api_msgs = [{"role": m["role"], "content": m["content"]} for m in msgs]
                    resp = self.client.messages.create(
                        model=self.model,
                        max_tokens=1024,
                        system=[],
                        messages=[*api_msgs, {"role": "user", "content": "Summarize key actions/results concisely."}],
                        tools=[],
                        tool_choice={"type": "auto"},
                        extra_headers=None,
                    )
                    session.apply_summary(resp.content[0].text)
                except Exception as e:
                    self.logger.error(f"Compaction failed: {e}")
        
        # Only add message if not delegated
        if not _is_delegated:
            session.add_message("user", message)
        
        if session.pending_approval:
            yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content="Respond to pending approval first.")
            return
        
        # Check for explicit unload command
        if "unload skill" in message.lower():
            if self._active_skill:
                skill_name = self._active_skill.name
                self.unload_skill()
                yield AgentEvent(type=EventType.MESSAGE, agent=self.nickname, content=f"Unloaded {skill_name}. Back in router mode.")
            else:
                yield AgentEvent(type=EventType.MESSAGE, agent=self.nickname, content="Already in router mode.")
            if not _is_delegated:
                yield AgentEvent(type=EventType.SESSION_ENDED, agent=self.nickname, content="Done")
            return
        
        # Auto-load skill on strong trigger match — bypass LLM judgment for the
        # routing step. Background: in router mode the system prompt highlights
        # matching skill triggers in **bold** but the LLM still has to *choose*
        # to emit `LOAD SKILL [...]`. We measured Atlas in router mode reaching
        # for direct tools (preview_userinterface / navigate_to_node) instead of
        # loading the ai-userinterface skill even when 3 triggers matched the
        # prompt verbatim — and then ignoring the skill prompt's "copy
        # flow.actions verbatim" rule. Threshold 2+ trigger matches is
        # conservative enough that a single accidental keyword (e.g. "ui" in a
        # generic question) will NOT yank the user into a skill, but specific
        # enough that an explicit "ai userinterface knowledge base" prompt
        # always loads the right skill.
        if not self._active_skill:
            from ..skills import SkillLoader
            available_skills = self.agent_config.get('available_skills', [])
            device_platform = self._detect_device_platform(session.context)
            matched = SkillLoader.match_skill(message, available_skills, device_platform)
            if matched:
                message_lower = message.lower()
                trigger_hits = sum(1 for t in matched.triggers if t.lower() in message_lower)
                if trigger_hits >= 2:
                    print(f"[AGENT] Router auto-load: {matched.name} ({trigger_hits} triggers matched)")
                    if self.load_skill(matched.name):
                        yield AgentEvent(
                            type=EventType.THINKING,
                            agent=self.nickname,
                            content=f"Auto-loaded skill: {matched.name} ({trigger_hits} triggers)",
                        )

        mode_str = f"[{self._active_skill.name}]" if self._active_skill else "[router]"
        yield AgentEvent(type=EventType.THINKING, agent=self.nickname, content=f"Analyzing... {mode_str}")

        # Build message history: FULL conversation (no truncation, no summary)
        turn_messages = []
        
        if _is_delegated:
            turn_messages = [{"role": "user", "content": message}]
        else:
            # Include ALL messages from session - full conversation context
            for msg in session.messages:
                turn_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        # Build cached system prompt and tools. In router mode, select a relevant
        # subset per turn to avoid sending the full direct-tool catalog on every query.
        current_tool_names = self.tool_names if self._active_skill else self._select_router_tools_for_message(message)
        cached_system = self._build_cached_system(session.context, message, current_tool_names if not self._active_skill else None)
        cached_tools = self._build_cached_tools(current_tool_names)
        
        # Log raw prompt only for root calls (avoid duplicate logs on delegated runs)
        if not _is_delegated:
            self._log_turn_state(session, cached_system, turn_messages, message, _is_delegated)
        
        print(f"[AGENT] Tools: {len(cached_tools)} | System: {len(cached_system[0]['text'])} chars")
        print(f"[AGENT] Tool names: {current_tool_names}")
        
        if "session_id" not in session.context:
            session.set_context("session_id", session.id)
        
        response_text = ""

        # Track tool calls for summary
        tool_calls_this_turn = []
        # One-shot flag for require_tool_use enforcement (see final-answer check)
        require_tool_nudged = False
        # Bounded retries for thinking-only/empty-text responses (MiniMax glitch)
        empty_retries = 0

        # Track if we've sent debug events for this turn
        debug_events_sent = False

        # Tool loop
        while True:
            # Check for cancellation at the start of each iteration
            if session.cancelled:
                print(f"[AGENT] ⚠️ Processing cancelled for session {session.id}")
                yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content="🛑 Generation stopped by user")
                break

            start = time.time()

            try:
                # Use prompt caching via extra_headers
                # disable_parallel_tool_use ensures sequential tool execution (one at a time)
                # For Minimax: cap thinking budget. The model always produces <think> tokens
                # (cannot be fully disabled — see github.com/can1357/oh-my-pi/issues/626), but
                # budget_tokens=256 measurably reduces per-turn latency (~5.7s vs ~6.9s default
                # on MiniMax-M2.7-highspeed, ~17% faster per turn). Over 5-7 agent turns that
                # compounds to ~10-20s saved end-to-end.
                _create_kwargs = dict(
                    model=self.model,
                    max_tokens=4096,
                    system=cached_system,
                    messages=turn_messages,
                    tools=cached_tools,
                    tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                    extra_headers={
                        "anthropic-beta": "prompt-caching-2024-07-31"
                    } if self.provider == "anthropic" else None
                )
                if self.provider == "minimax":
                    _create_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 256}
                response = self.client.messages.create(**_create_kwargs)
            except Exception as e:
                error_msg = f"{self.provider} API call failed: {str(e)}"
                self.logger.error(f"[AGENT] {error_msg}", exc_info=True)
                print(f"[AGENT] ❌ {error_msg}")

                # Provide specific error messages based on exception type
                if "rate_limit" in str(e).lower():
                    user_error = "Rate limit exceeded. Please wait a moment and try again."
                elif "authentication" in str(e).lower() or "api key" in str(e).lower():
                    user_error = "Authentication failed. Please check your API key configuration."
                elif "network" in str(e).lower() or "connection" in str(e).lower():
                    user_error = "Network error. Please check your internet connection and try again."
                elif "tokens" in str(e).lower():
                    user_error = "Message too long. Please try a shorter message."
                else:
                    user_error = f"AI service error: {str(e)}"

                yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content=user_error, error=str(e))
                break

            # Check for cancellation immediately after API call (before processing response)
            # This prevents processing interrupted/empty responses when user stops generation
            if session.cancelled:
                print(f"[AGENT] ⚠️ Processing cancelled after API call for session {session.id}")
                yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content="🛑 Generation stopped by user")
                break

            # Extract cache metrics if available
            cache_creation = getattr(response.usage, 'cache_creation_input_tokens', 0)
            cache_read = getattr(response.usage, 'cache_read_input_tokens', 0)
            
            metrics = {
                "duration_ms": int((time.time() - start) * 1000),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "cache_creation_tokens": cache_creation,
                "cache_read_tokens": cache_read,
            }
            
            # Log cache performance
            if cache_read > 0:
                print(f"[CACHE] Read {cache_read} tokens from cache (90% cheaper)")
            if cache_creation > 0:
                print(f"[CACHE] Created cache with {cache_creation} tokens")

            # Track generation (with error handling)
            if LANGFUSE_ENABLED:
                try:
                    track_generation(self.nickname, self.model, turn_messages, response, session.id, session.context.get("user_id"), duration_ms=metrics["duration_ms"])
                except Exception as e:
                    self.logger.warning(f"Langfuse tracking failed: {e}")
                    print(f"[AGENT] ⚠️ Langfuse tracking error (non-critical): {e}")
            
            # Providers that ignore Anthropic's disable_parallel_tool_use flag
            # (e.g. MiniMax) can emit SEVERAL tool_use blocks in one turn. We
            # execute exactly one tool per round, so record only the FIRST
            # tool_use in the assistant turn — otherwise the history carries
            # tool_use ids with no matching tool_result and the next request
            # fails ("tool call and result not match", MiniMax error 2013).
            # The model re-issues the dropped call next round if still needed.
            _recorded_content = []
            _seen_tool_use = False
            for _b in response.content:
                if getattr(_b, "type", None) == "tool_use":
                    if _seen_tool_use:
                        continue
                    _seen_tool_use = True
                _recorded_content.append(_b)
            turn_messages.append({"role": "assistant", "content": _recorded_content})

            try:
                tool_use = next((b for b in response.content if b.type == "tool_use"), None)
                text_content = next((b.text for b in response.content if b.type == "text"), "")
                # Minimax (and Claude extended-thinking) emit `thinking` content blocks.
                # Capture them so the per-turn reasoning lands in the event stream /
                # JSONL logs instead of being thrown away with the response object.
                thinking_content = next(
                    (getattr(b, "thinking", "") for b in response.content if b.type == "thinking"),
                    ""
                )
            except Exception as e:
                error_msg = f"Failed to parse Claude response: {str(e)}"
                self.logger.error(f"[AGENT] {error_msg}", exc_info=True)
                print(f"[AGENT] ❌ {error_msg}")

                # Provide more specific error information
                if hasattr(response, 'content') and response.content:
                    content_types = [getattr(b, 'type', 'unknown') for b in response.content]
                    error_details = f"Response contained blocks of types: {content_types}"
                else:
                    error_details = "Response content was empty or malformed"

                user_error = f"AI response parsing failed. {error_details}. Please try again."
                yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content=user_error, error=str(e))
                break
            
            # Some models (observed: MiniMax) emit `LOAD SKILL` as a tool_use
            # block instead of the text command the router prompt specifies.
            # Honor it as a skill load — executing it as a tool would fail and
            # send the model flailing into unrelated tools.
            if tool_use and tool_use.name.strip().lower().replace('_', ' ').replace('-', ' ') in ('load skill', 'loadskill'):
                _skill_arg = ''
                if isinstance(tool_use.input, dict):
                    for _v in tool_use.input.values():
                        if isinstance(_v, str) and _v.strip():
                            _skill_arg = _v.strip().strip('[]')
                            break
                if not _skill_arg and text_content:
                    _skill_arg = (self._parse_skill_command(text_content) or '')
                _loaded = bool(_skill_arg) and self.load_skill(_skill_arg)
                turn_messages.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": f"Skill '{_skill_arg}' loaded." if _loaded
                               else f"Could not load skill '{_skill_arg}'. Available: {', '.join(self.agent_config.get('available_skills', []))}",
                    **({} if _loaded else {"is_error": True}),
                }]})
                if _loaded:
                    print(f"[AGENT] Loading skill (via tool_use): {_skill_arg}")
                    yield AgentEvent(type=EventType.SKILL_LOADED, agent=self.nickname, content=_skill_arg)
                    current_tool_names = self.tool_names
                    cached_system = self._build_cached_system(session.context, message)
                    cached_tools = self._build_cached_tools(current_tool_names)
                continue

            if tool_use:
                # Send debug events before first tool call
                if not debug_events_sent:
                    # Send system prompt
                    system_prompt_text = ""
                    if cached_system and len(cached_system) > 0:
                        try:
                            system_prompt_text = json.dumps(cached_system, ensure_ascii=False, indent=2)
                        except:
                            system_prompt_text = str(cached_system)

                    yield AgentEvent(type=EventType.SYSTEM_PROMPT, agent=self.nickname, content=system_prompt_text)

                    try:
                        tool_definitions_text = json.dumps(cached_tools, ensure_ascii=False, indent=2)
                    except Exception:
                        tool_definitions_text = str(cached_tools)

                    yield AgentEvent(type=EventType.TOOL_DEFINITIONS, agent=self.nickname, content=tool_definitions_text)

                    # Send runtime/debug metadata only. Prompt content already appears
                    # in SYSTEM_PROMPT and TOOL_DEFINITIONS, so don't duplicate it here.
                    runtime_context = {
                        "team_id": session.context.get("team_id"),
                        "agent_id": session.context.get("agent_id"),
                        "allow_auto_navigation": session.context.get("allow_auto_navigation"),
                        "current_page": session.context.get("current_page"),
                        "testcase_id": session.context.get("testcase_id"),
                        "campaign_id": session.context.get("campaign_id"),
                    }
                    context_info = {
                        "session_id": session.id,
                        "active_skill": self._active_skill.name if self._active_skill else None,
                        "runtime_context": runtime_context,
                        "conversation_summary": session.get_context('conversation_summary', ''),
                        "total_messages": len(turn_messages),
                    }

                    try:
                        context_text = json.dumps(context_info, ensure_ascii=False, indent=2)
                    except:
                        context_text = str(context_info)

                    yield AgentEvent(type=EventType.CONVERSATION_CONTEXT, agent=self.nickname, content=context_text)

                    debug_events_sent = True

                # Emit the model's per-turn reasoning BEFORE the tool call so the
                # JSONL trace shows why each action was chosen. `thinking_content`
                # is Minimax / extended-thinking internal reasoning; `text_content`
                # is the narration the model wrote alongside the tool_use block.
                if thinking_content:
                    yield AgentEvent(
                        type=EventType.THINKING,
                        agent=self.nickname,
                        content=thinking_content,
                    )
                if text_content:
                    yield AgentEvent(
                        type=EventType.MESSAGE,
                        agent=self.nickname,
                        content=text_content,
                    )

                yield AgentEvent(type=EventType.TOOL_CALL, agent=self.nickname, content=f"Calling: {tool_use.name}", tool_name=tool_use.name, tool_params=tool_use.input, metrics=metrics)
                
                try:
                    # Check for cancellation before executing the tool
                    if session.cancelled:
                        print(f"[AGENT] ⚠️ Tool execution cancelled for session {session.id}")
                        yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content="🛑 Generation stopped by user")
                        break

                    # Get cache config for this tool (if in active skill)
                    cache_config = None
                    if self._active_skill:
                        cache_config = self._active_skill.get_tool_cache_config(tool_use.name)
                        if cache_config:
                            print(f"[cache] 🔧 {tool_use.name} config: enabled={cache_config.enabled}, ttl={cache_config.ttl_seconds}s")

                    # Trace: log every tool call BEFORE invocation with session + args
                    # (short-circuit path when atlas_chat / UI doesn't surface agent events).
                    try:
                        _args_preview = json.dumps(tool_use.input, default=str)[:300]
                    except Exception:
                        _args_preview = repr(tool_use.input)[:300]
                    print(
                        f"[AGENT:tool_call] session={getattr(session, 'id', '?')} "
                        f"agent={self.nickname} tool={tool_use.name} args={_args_preview}"
                    )

                    result = self.tool_bridge.execute(
                        tool_use.name,
                        tool_use.input,
                        allowed_tools=current_tool_names,
                        cache_config=cache_config
                    )

                    # Check for cancellation after tool execution (in case it was cancelled during execution)
                    if session.cancelled:
                        print(f"[AGENT] ⚠️ Processing cancelled after tool execution for session {session.id}")
                        yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content="🛑 Generation stopped by user")
                        break
                    if LANGFUSE_ENABLED:
                        try:
                            track_tool_call(self.nickname, tool_use.name, tool_use.input, result, True, session.id)
                        except Exception as e:
                            self.logger.warning(f"Langfuse tool tracking failed: {e}")
                            print(f"[AGENT] ⚠️ Langfuse tool tracking error (non-critical): {e}")
                    yield AgentEvent(type=EventType.TOOL_RESULT, agent=self.nickname, content="Success", tool_name=tool_use.name, tool_result=result, success=True)
                    
                    # Track tool call for summary
                    tool_calls_this_turn.append({
                        'tool_name': tool_use.name,
                        'params': tool_use.input,
                        'success': True
                    })
                    
                    # Forward the MCP tool result back to the LLM. Anthropic's API
                    # accepts tool_result.content as EITHER a string OR an array of
                    # content blocks — but the Minimax provider's validation (error
                    # 2013 "tool call and result not match") only accepts a string.
                    # So we compromise: tool_result.content stays a string (text only),
                    # AND we attach any image blocks as SIBLING content in the same
                    # user turn. The image still reaches the model on the next call.
                    _user_content = []
                    _image_blocks = []
                    if isinstance(result, dict) and isinstance(result.get('content'), list):
                        _text_parts = []
                        for _blk in result['content']:
                            if isinstance(_blk, dict) and _blk.get('type') == 'image':
                                _image_blocks.append(_blk)
                            elif isinstance(_blk, dict) and _blk.get('type') == 'text':
                                _text_parts.append(_blk.get('text', ''))
                        _tool_result_str = '\n'.join(_text_parts) if _text_parts else json.dumps(
                            {k: v for k, v in result.items() if k != 'content'}
                        )
                    else:
                        _tool_result_str = json.dumps(result)
                    _user_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": _tool_result_str,
                    })
                    # Append image blocks (if any) as sibling content AFTER the tool_result.
                    # Normalise to Anthropic image source shape: {"type":"base64","media_type":"image/jpeg","data":"..."}
                    for _img in _image_blocks:
                        _src = _img.get('source')
                        if not _src and 'data' in _img:
                            _src = {
                                "type": "base64",
                                "media_type": _img.get('mimeType') or _img.get('media_type') or 'image/jpeg',
                                "data": _img['data'],
                            }
                        if _src:
                            _user_content.append({"type": "image", "source": _src})
                    turn_messages.append({"role": "user", "content": _user_content})
                except Exception as e:
                    if LANGFUSE_ENABLED:
                        try:
                            track_tool_call(self.nickname, tool_use.name, tool_use.input, str(e), False, session.id)
                        except Exception as track_e:
                            self.logger.warning(f"Langfuse failed tool tracking failed: {track_e}")
                            print(f"[AGENT] ⚠️ Langfuse failed tool tracking error (non-critical): {track_e}")

                    # Categorize tool execution errors for better user experience
                    error_type = type(e).__name__
                    tool_name = tool_use.name
                    error_str = str(e)

                    # If the error already looks like a properly formatted tool response (starts with emoji or contains formatting),
                    # don't add generic wrapper - just use the tool's error message as-is
                    if error_str.startswith(('❌', '✅', '⚠️', 'ℹ️')) or ('\n   ' in error_str):
                        user_error = error_str
                    elif "timeout" in error_str.lower() or "time" in error_type.lower():
                        user_error = f"Tool '{tool_name}' timed out. The operation took too long to complete."
                    elif "connection" in error_str.lower() or "network" in error_str.lower():
                        user_error = f"Tool '{tool_name}' failed due to network issues. Please check your connection."
                    elif "permission" in error_str.lower() or "access" in error_str.lower():
                        user_error = f"Tool '{tool_name}' failed due to permission issues. Access may be denied."
                    elif "not found" in error_str.lower() or "404" in error_str:
                        user_error = f"Tool '{tool_name}' could not find the requested resource."
                    else:
                        user_error = f"Tool '{tool_name}' encountered an error: {error_str}"

                    self.logger.error(f"[AGENT] Tool execution failed: {tool_name} - {str(e)}", exc_info=True)
                    print(f"[AGENT] ❌ Tool '{tool_name}' failed: {str(e)}")

                    yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content=user_error, error=str(e), tool_name=tool_name)
                    
                    turn_messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": f"Error: {e}", "is_error": True}]})
            else:
                response_text = text_content

                # Strip <think> tags from providers that wrap reasoning (e.g., MiniMax)
                import re as _re
                stripped = _re.sub(r'<think>[\s\S]*?</think>\s*', '', response_text).strip()
                if stripped:
                    response_text = stripped
                elif '<think>' in response_text:
                    # Entire response is inside think tags — extract content from inside
                    inner = _re.sub(r'</?think>', '', response_text).strip()
                    if inner:
                        response_text = inner

                # Check for empty response
                if not response_text or not response_text.strip():
                    input_tokens = metrics.get('input_tokens', 0)
                    output_tokens = metrics.get('output_tokens', 0)
                    stop_reason = getattr(response, 'stop_reason', 'unknown')

                    # If session was cancelled, provide a more user-friendly message
                    if session.cancelled:
                        error_msg = "🛑 Generation stopped by user"
                        error_type = "cancelled"
                    else:
                        # MiniMax intermittently spends the whole turn inside a
                        # `thinking` block and ends with no user-visible text.
                        # That's a retryable glitch, not a dead conversation.
                        if empty_retries < 2:
                            empty_retries += 1
                            turn_messages.append({"role": "user", "content": (
                                "(Your previous response contained no user-visible text. "
                                "Respond now with your final answer text or a tool call.)"
                            )})
                            print(f"[AGENT] Empty text response (stop={stop_reason}, out={output_tokens}) — retry {empty_retries}/2")
                            yield AgentEvent(type=EventType.THINKING, agent=self.nickname, content="Model returned no text — retrying")
                            continue
                        error_msg = f"Empty response (stop: {stop_reason}, in: {input_tokens}, out: {output_tokens})"
                        error_type = "empty_response"

                    yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content=error_msg, error=error_type, metrics=metrics)
                    break
                
                # Check for skill load command
                skill_to_load = self._parse_skill_command(response_text)
                if skill_to_load:
                    print(f"[AGENT] Loading skill: {skill_to_load}")
                    yield AgentEvent(type=EventType.SKILL_LOADED, agent=self.nickname, content=skill_to_load)

                    if self.load_skill(skill_to_load):
                        # Rebuild system prompt and tools for the loaded skill
                        current_tool_names = self.tool_names
                        cached_system = self._build_cached_system(session.context, message)
                        cached_tools = self._build_cached_tools(current_tool_names)
                        print(f"[AGENT] Tools: {len(cached_tools)} | System: {len(cached_system[0]['text'])} chars")
                        continue  # Continue processing with loaded skill in same loop
                    else:
                        available_skills = self.agent_config.get('available_skills', [])
                        error_msg = f"Skill '{skill_to_load}' is not available. Available skills: {', '.join(available_skills)}"
                        self.logger.error(f"[AGENT] Failed to load skill '{skill_to_load}'. Available: {available_skills}")
                        print(f"[AGENT] ❌ Failed to load skill: {skill_to_load}")
                        yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content=error_msg, error=f"skill_not_available:{skill_to_load}")
                    break
                
                # Check for unload command in response
                if "unload skill" in response_text.lower():
                    if self._active_skill:
                        skill_name = self._active_skill.name
                        self.unload_skill()
                        display_text = response_text.replace("UNLOAD SKILL", f"Unloaded {skill_name}")
                        yield AgentEvent(type=EventType.MESSAGE, agent=self.nickname, content=display_text, metrics=metrics)
                    else:
                        yield AgentEvent(type=EventType.MESSAGE, agent=self.nickname, content=response_text, metrics=metrics)
                    break
                
                # require_tool_use skills: a final answer with zero tool calls
                # means the model skipped its research step (observed: qwen3
                # answers "pricing is not covered in the docs" without a single
                # read_doc call). Push back exactly once, then accept.
                if (self._active_skill
                        and getattr(self._active_skill, 'require_tool_use', False)
                        and not tool_calls_this_turn
                        and not require_tool_nudged):
                    require_tool_nudged = True
                    turn_messages.append({"role": "user", "content": (
                        "You answered without consulting any tool. This skill requires "
                        "reading the documentation before answering: call "
                        "read_doc(path='INDEX.md') now, follow where it points, and "
                        "answer only from what you actually read."
                    )})
                    print(f"[AGENT] require_tool_use: rejecting toolless answer, nudging model to read docs")
                    yield AgentEvent(type=EventType.THINKING, agent=self.nickname, content="Answer skipped the doc lookup — retrying with a forced doc read")
                    continue

                # Normal response
                yield AgentEvent(type=EventType.MESSAGE, agent=self.nickname, content=response_text, metrics=metrics)
                break
        
        # Save assistant response to session history (clean, no tool details)
        if response_text:
            session.add_message("assistant", response_text, agent=self.nickname)
        
        if LANGFUSE_ENABLED:
            try:
                flush()
            except Exception as e:
                self.logger.warning(f"Langfuse flush failed: {e}")
                print(f"[AGENT] ⚠️ Langfuse flush error (non-critical): {e}")
        
        # Only root agent emits SESSION_ENDED
        if not _is_delegated:
            yield AgentEvent(type=EventType.SESSION_ENDED, agent=self.nickname, content="Done")
    
    async def handle_approval(self, session: Session, approved: bool, modifications: Dict[str, Any] = None) -> AsyncGenerator[AgentEvent, None]:
        """Handle approval response"""
        if not session.pending_approval:
            yield AgentEvent(type=EventType.ERROR, agent=self.nickname, content="No pending approval")
            return
        
        approval = session.pending_approval
        session.clear_approval()
        
        yield AgentEvent(type=EventType.APPROVAL_RECEIVED, agent=self.nickname, content=f"Approval {'granted' if approved else 'rejected'}")
        
        if approved:
            if modifications:
                for k, v in modifications.items():
                    session.set_context(k, v)
            
            async for event in self.process_message(f"Continue: {approval.action}", session, _is_delegated=True):
                yield event
        else:
            yield AgentEvent(type=EventType.MESSAGE, agent=self.nickname, content="Cancelled. What next?")
        
        yield AgentEvent(type=EventType.SESSION_ENDED, agent=self.nickname, content="Done")
    
    # =========================================================================
    # BACKGROUND WORKER - Processes items from configured Redis queues
    # =========================================================================
    
    def start_background(self) -> bool:
        """
        Start background thread to process items from configured queues.
        
        Returns:
            True if started, False if no queues configured or already running
        """
        queues = self.agent_config.get('background_queues', [])
        if not queues:
            self.logger.info(f"[{self.nickname}] No background_queues configured")
            return False
        
        if self._queue_worker_running:
            self.logger.warning(f"[{self.nickname}] Background worker already running")
            return False
        
        self._queue_worker_running = True
        self._queue_worker_thread = threading.Thread(
            target=self._background_loop,
            daemon=True,
            name=f"agent-{self.agent_id}-background"
        )
        self._queue_worker_thread.start()
        self.logger.info(f"[{self.nickname}] 🚀 Background worker started, queues: {queues}")
        return True
    
    def stop_background(self):
        """Stop background worker thread"""
        if not self._queue_worker_running:
            return
        
        self._queue_worker_running = False
        if self._queue_worker_thread:
            self._queue_worker_thread.join(timeout=5)
        self.logger.info(f"[{self.nickname}] 🛑 Background worker stopped")
    
    @property
    def background_running(self) -> bool:
        """Check if background worker is running"""
        return self._queue_worker_running
    
    def _setup_redis_queue_processor(self):
        """Setup Redis queue processor (supports both local and Upstash Redis)"""
        try:
            import os
            redis_url = os.getenv('REDIS_URL')
            
            # Mask sensitive information in Redis URL for logging
            masked_url = redis_url
            if redis_url and ':' in redis_url and '@' in redis_url:
                # Mask password in redis://:password@host:port format
                parts = redis_url.split('@')
                if len(parts) == 2 and parts[0].startswith('redis://:'):
                    masked_url = f"redis://:***@{parts[1]}"

            redis_processor = get_queue_processor()

            # Test connection
            if redis_processor.health_check():
                self.logger.info(f"[{self.nickname}] Redis queue processor connected successfully ({redis_processor.redis_mode})")
                self.logger.info(f"[{self.nickname}] Redis URL: {masked_url}")
                return redis_processor
            else:
                self.logger.error(f"[{self.nickname}] Redis health check failed")
                return None

        except Exception as e:
            self.logger.error(f"[{self.nickname}] Failed to setup Redis queue processor: {e}")
            return None
    
    def _background_loop(self):
        """Background loop - monitors queues and processes items"""
        try:
            queues = self.agent_config.get('background_queues', [])
            
            redis_processor = self._setup_redis_queue_processor()
            
            if not redis_processor:
                self.logger.error(f"[{self.nickname}] Cannot start background loop - no Redis")
                self._queue_worker_running = False
                return
            
            self.logger.info(f"[{self.nickname}] 🔄 Background loop started, monitoring: {queues}")
        except Exception as e:
            self.logger.error(f"[{self.nickname}] FATAL ERROR in background loop startup: {e}")
            import traceback
            traceback.print_exc()
            self._queue_worker_running = False
            return
        
        # Check queue status on startup
        try:
            self.logger.debug(f"[{self.nickname}] Checking queue status...")
            for queue in queues:
                self.logger.debug(f"[{self.nickname}] Checking queue '{queue}'...")
                length = redis_processor.get_queue_length(queue)
                self.logger.info(f"[{self.nickname}] 📊 Queue '{queue}' has {length} pending items")
        except Exception as e:
            self.logger.warning(f"[{self.nickname}] Could not check queue status: {e}")
        
        try:
            while self._queue_worker_running:
                try:
                    # Poll queues in priority order
                    task_found = False
                    
                    for queue in queues:
                        # Use LPOP to get and remove item from queue
                        result = redis_processor._redis_command(['LPOP', queue])
                        
                        # Always log when we get something from queue
                        if result and result.get('result'):
                            task_json = result['result']
                            
                            task = json.loads(task_json) if isinstance(task_json, str) else task_json
                            task_found = True
                            
                            task_type = task.get('type', 'unknown')
                            task_id = task.get('id', 'unknown')
                            self.logger.info(f"[{self.nickname}] 📥 Task from {queue}: {task_type}")
                            self._process_background_task(task, queue)
                            self.logger.info(f"[{self.nickname}] ✅ Task {task_id} processed")
                            break  # Process one task then restart loop
                    
                    # If no task found, sleep before next poll
                    if not task_found:
                        time.sleep(5)  # Poll every 5 seconds
                        
                except Exception as e:
                    if self._queue_worker_running:
                        print(f"[{self.nickname}] Background loop error: {e}")
                        self.logger.error(f"[{self.nickname}] Background loop error: {e}")
                        import traceback
                        traceback.print_exc()
                        time.sleep(5)
        except Exception as fatal_error:
            self.logger.error(f"[{self.nickname}] FATAL ERROR in background loop: {fatal_error}")
            import traceback
            traceback.print_exc()
        finally:
            self.logger.info(f"[{self.nickname}] 👋 Background loop ended")
    
    def _get_handler(self):
        """Get the appropriate handler based on agent type"""
        if self.agent_id == 'analyzer':
            if not self._sherlock_handler:
                self._sherlock_handler = SherlockHandler(self.nickname)
            return self._sherlock_handler
        elif self.agent_id == 'monitor':
            if not self._nightwatch_handler:
                self._nightwatch_handler = NightwatchHandler(self.nickname)
            return self._nightwatch_handler
        return None
    
    def _process_background_task(self, task: Dict[str, Any], queue_name: str):
        """Process a single background task with Socket.IO and Slack notifications"""
        task_id = 'unknown'
        is_dry_run = self.agent_config.get('dry_run', False)
        handler = self._get_handler()
        
        try:
            self.logger.debug(f"[{self.nickname}] 🔧 _process_background_task START (dry_run={is_dry_run})")
            self.logger.debug(f"[{self.nickname}] 🔧 Task keys: {list(task.keys())}")
            
            task_type = task.get('type', 'unknown')
            task_id = task.get('id', 'unknown')
            task_data = task.get('data', {})
            
            self.logger.debug(f"[{self.nickname}] 🔧 task_type={task_type}, task_id={task_id}")
            self.logger.debug(f"[{self.nickname}] 🔧 task_data keys: {list(task_data.keys())}")
            
            # DRY RUN MODE: Use Nightwatch handler
            if is_dry_run:
                if not self._nightwatch_handler:
                    self._nightwatch_handler = NightwatchHandler(self.nickname)
                self._nightwatch_handler.handle_dry_run_task(task_type, task_id, task_data, queue_name)
                return
            
            # Build message using appropriate handler
            if not handler:
                self.logger.warning(f"[{self.nickname}] ⚠️  No handler for agent_id={self.agent_id}")
                return
            
            # Check if handler wants to process with AI (filters: duration, rate limit, etc.)
            if hasattr(handler, 'should_process_with_ai'):
                if not handler.should_process_with_ai(task_id, task_data):
                    # Handler decided to skip AI processing (already marked in DB)
                    return

            # Optional direct processing path (no agent chat loop).
            if hasattr(handler, 'process_task_direct'):
                try:
                    if handler.process_task_direct(task_type, task_id, task_data):
                        self.logger.info(f"[{self.nickname}] ✅ Task {task_id} processed via direct handler")
                        return
                except Exception as direct_error:
                    self.logger.error(f"[{self.nickname}] Direct handler failed, falling back to agent loop: {direct_error}")
            
            print(f"[{self.nickname}] 🔧 Building task message...")
            message = handler.build_task_message(task_type, task_id, task_data)
            print(f"[{self.nickname}] 🔧 Message built: {message[:100]}...")
            
            # Create session for this task
            print(f"[{self.nickname}] 🔧 Creating session...")
            session = self._session_manager.create_session()
            session.set_context('task_id', task_id)
            session.set_context('task_type', task_type)
            session.set_context('queue_name', queue_name)
            session.set_context('is_background', True)
            print(f"[{self.nickname}] 🔧 Session created: {session.id}")
            
            # Get Socket.IO manager
            try:
                from ..socket_manager import socket_manager
            except Exception as import_error:
                print(f"[{self.nickname}] ⚠️  Failed to import socket_manager: {import_error}")
                self.logger.error(f"[{self.nickname}] Socket.IO import failed: {import_error}")
                socket_manager = None
            
            # Process with agent
            print(f"[{self.nickname}] 🔧 Starting async processing...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                responses = []
                
                async def process():
                    async for event in self.process_message(message, session):
                        if event.type == EventType.MESSAGE:
                            responses.append(event.content)
                        
                        # Emit event to Socket.IO
                        if socket_manager:
                            try:
                                event_dict = event.to_dict()
                                socket_manager.emit_to_room(
                                    room='background_tasks',
                                    event='agent_event',
                                    data=event_dict,
                                    namespace='/agent'
                                )
                                print(f"[{self.nickname}] 📡 Emitted event: {event.type} to background_tasks room")
                            except Exception as emit_error:
                                print(f"[{self.nickname}] ⚠️  Socket.IO emission failed: {emit_error}")
                                self.logger.error(f"[{self.nickname}] Socket.IO emission failed for event {event.type}: {emit_error}", exc_info=True)
                                # Continue processing even if Socket.IO fails - don't let it break the task
                        else:
                            print(f"[{self.nickname}] 📡 Socket.IO not available - skipping event emission for {event.type}")
                
                loop.run_until_complete(process())
                
                result = '\n'.join(responses)
                print(f"[{self.nickname}] ✅ Task {task_id} completed successfully")
                self.logger.info(f"[{self.nickname}] ✅ Task {task_id} complete")
                
                # Update handler state after successful AI processing (e.g., rate limits)
                if hasattr(handler, 'update_rate_limit'):
                    handler.update_rate_limit(task_data)
                
                # Send result to Slack via handler
                handler.send_to_slack(task_type, task_id, task_data, result)
                
            finally:
                loop.close()
                print(f"[{self.nickname}] 🔧 Event loop closed")
                
        except Exception as e:
            print(f"[{self.nickname}] ❌❌❌ TASK PROCESSING FAILED for task {task_id}")
            print(f"[{self.nickname}] ❌ Error: {e}")
            self.logger.error(f"[{self.nickname}] ❌ Task processing error: {e}")
            import traceback
            traceback.print_exc()
            print(f"[{self.nickname}] ❌❌❌ END OF ERROR")

            # Emit error event to frontend
            if socket_manager:
                try:
                    error_event = AgentEvent(
                        type=EventType.ERROR,
                        agent=self.nickname,
                        content=f"Background task {task_id} failed: {str(e)}",
                        error=str(e)
                    )
                    event_dict = error_event.to_dict()
                    socket_manager.emit_to_room(
                        room='background_tasks',
                        event='agent_event',
                        data=event_dict,
                        namespace='/agent'
                    )
                    print(f"[{self.nickname}] 📡 Emitted error event for failed task {task_id}")
                except Exception as emit_error:
                    print(f"[{self.nickname}] ⚠️  Failed to emit error event: {emit_error}")
                    self.logger.error(f"[{self.nickname}] Failed to emit error event: {emit_error}")
            else:
                print(f"[{self.nickname}] 📡 Socket.IO not available - could not emit error event for failed task {task_id}")
    
