"""AGENT_SOURCES — the one table mapping an agent to where its work is recorded (TASK-54 §8).

A new worker is one entry here. ``usage_prefixes`` match ``ai_usage_stats.usage_key`` and
``ai_decisions.usage_key`` on a key boundary (``agent.atlas`` matches ``agent.atlas.route`` and
``agent.atlas.skill.x`` but not ``agent.atlasx``); a prefix ending in ``_`` is a plain prefix.
``eval:*`` keys (evaluation runs, the TASK-44 manager) always fall under ``other``.
"""

from typing import Any, Dict, List, Optional

OTHER = 'other'

# part keys are the values of the `part` filter / row field of GET /server/agents/<id>/logs.
# decision_prefixes: ai_decisions usage keys that produce rows of that part.
AGENT_SOURCES: Dict[str, Dict[str, Any]] = {
    'atlas': {
        'name': 'Atlas', 'role': 'QA Assistant', 'registry_id': 'assistant',
        'usage_prefixes': ['agent.atlas', 'text.plan', 'vision.explore'],
        'sources': ['agent_turns', 'agent_execution_history', 'test_prompt_executions', 'ai_decisions'],
        'parts': [
            {'key': 'chat', 'label': 'Chat'},
            {'key': 'testprompt', 'label': 'Test Prompt runs'},
            {'key': 'decision', 'label': 'Routing decisions',
             'decision_prefixes': ['agent.atlas.route', 'text.decision.testprompt_on_failure']},
        ],
        'links': [{'label': 'Langfuse traces', 'to': '/langfuse-dashboard'}],
    },
    'forge': {
        'name': 'Forge', 'role': 'Script Builder', 'registry_id': 'scripter',
        'usage_prefixes': ['agent.forge'],
        'sources': ['agent_turns', 'agent_execution_history'],
        'parts': [{'key': 'chat', 'label': 'Chat'}],
        'links': [{'label': 'Virtual scripts', 'to': '/builder/virtual-scripts'}],
    },
    'sherlock': {
        'name': 'Sherlock', 'role': 'Result Analyzer', 'registry_id': 'analyzer',
        'usage_prefixes': ['agent.sherlock', 'analyzer.sherlock', 'text.decision.sherlock'],
        'sources': ['agent_turns', 'agent_execution_history', 'script_results', 'ai_decisions'],
        'parts': [
            {'key': 'chat', 'label': 'Chat'},
            {'key': 'triage', 'label': 'Script triage'},
            {'key': 'decision', 'label': 'Decisions', 'decision_prefixes': ['text.decision.sherlock']},
        ],
        'links': [{'label': 'Script results', 'to': '/test-results/reports'},
                  {'label': 'AI queue', 'to': '/monitoring/ai-queue'}],
    },
    'nightwatch': {
        'name': 'Nightwatch', 'role': 'QA Monitor', 'registry_id': 'monitor',
        'usage_prefixes': ['agent.nightwatch', 'vision.alert_triage'],
        'sources': ['agent_turns', 'agent_execution_history', 'alerts'],
        'parts': [
            {'key': 'chat', 'label': 'Chat'},
            {'key': 'triage', 'label': 'Alert triage'},
        ],
        'links': [{'label': 'Incidents', 'to': '/monitoring/incidents'},
                  {'label': 'AI queue', 'to': '/monitoring/ai-queue'}],
    },
    'companion': {
        'name': 'Companion (Jev)', 'role': 'Game and web companion', 'registry_id': None,
        'usage_prefixes': ['vision.companion', 'text.decision.companion', 'text.companion',
                           'text.web.companion', 'text.game_'],
        'sources': ['ai_decisions'],
        'parts': [{'key': 'decision', 'label': 'Decisions',
                   'decision_prefixes': ['vision.companion', 'text.decision.companion', 'text.companion',
                                         'text.web.companion', 'text.game_']}],
        'links': [],
    },
    'screen_review': {
        'name': 'Screen review', 'role': 'Screen reviewer', 'registry_id': None,
        'usage_prefixes': ['text.decision.screen_review'],
        'sources': ['ai_decisions'],
        'parts': [{'key': 'decision', 'label': 'Decisions',
                   'decision_prefixes': ['text.decision.screen_review']}],
        'links': [],
    },
    'public_ask': {
        'name': 'Public Ask', 'role': 'Website assistant', 'registry_id': None,
        'usage_prefixes': ['public.ask'], 'sources': [], 'parts': [], 'links': [],
    },
    'browser': {
        'name': 'Browser agent', 'role': 'Web browsing agent', 'registry_id': None,
        'usage_prefixes': ['agent.browser'], 'sources': [], 'parts': [], 'links': [],
    },
    'mcp': {
        'name': 'MCP', 'role': 'MCP prompts', 'registry_id': None,
        'usage_prefixes': ['agent.mcp_prompt'], 'sources': [], 'parts': [], 'links': [],
    },
    OTHER: {
        'name': 'Other AI', 'role': 'Everything else (admin only)', 'registry_id': None,
        'usage_prefixes': [], 'sources': [], 'parts': [], 'links': [], 'admin_only': True,
    },
}

# agent_execution_history / agent_turns store the registry id of the chat agent.
_BY_REGISTRY = {v['registry_id']: k for k, v in AGENT_SOURCES.items() if v.get('registry_id')}


def agent_for_registry_id(registry_id: Optional[str]) -> str:
    return _BY_REGISTRY.get(registry_id or '', OTHER)


def _prefix_match(key: str, prefix: str) -> bool:
    if not key.startswith(prefix):
        return False
    if len(key) == len(prefix) or prefix.endswith('_'):
        return True
    return key[len(prefix)] in '._:-'


def matches_prefixes(key: Optional[str], prefixes: List[str]) -> bool:
    return bool(key) and any(_prefix_match(key, p) for p in prefixes)


def agent_for_usage_key(usage_key: Optional[str]) -> str:
    """The agent a usage key belongs to; ``other`` when nothing matches (``eval:*`` always ``other``)."""
    key = (usage_key or '').strip()
    if not key or key.startswith('eval:'):
        return OTHER
    for agent_id, spec in AGENT_SOURCES.items():
        if matches_prefixes(key, spec['usage_prefixes']):
            return agent_id
    return OTHER


def part_for_usage_key(agent_id: str, usage_key: Optional[str]) -> Optional[str]:
    """The log part an ai_decisions/usage key feeds for this agent (None = no part, stats only)."""
    for part in AGENT_SOURCES.get(agent_id, {}).get('parts', []):
        if matches_prefixes(usage_key, part.get('decision_prefixes', [])):
            return part['key']
    return None


def decision_prefixes(agent_id: str) -> List[str]:
    out: List[str] = []
    for part in AGENT_SOURCES.get(agent_id, {}).get('parts', []):
        out.extend(part.get('decision_prefixes', []))
    return out
