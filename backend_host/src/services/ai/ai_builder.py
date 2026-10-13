"""
AI Graph Builder - Complete AI-driven test case graph generation

Single-file implementation of the full AI pipeline:
1. Preprocessing: Cache check, exact matches, disambiguation
2. Generation: AI API call, JSON parsing
3. Post-processing: Validation, label enforcement, transition pre-fetching
4. Caching: Store successful graphs

NO legacy code, NO backward compatibility
Clean architecture following backend_host conventions
"""

import time
import re
import hashlib
import json
import traceback
import threading
from typing import Dict, List, Optional, Any, Tuple
from difflib import get_close_matches, SequenceMatcher
from dataclasses import dataclass, asdict
from datetime import datetime

# Imports
from shared.src.lib.utils.ai_utils import call_text_ai
from shared.src.lib.config.constants import AI_CONFIG, CACHE_CONFIG
from shared.src.lib.database.ai_graph_cache_db import (
    store_graph,
    get_graph_by_fingerprint,
    _generate_fingerprint
)
from backend_host.src.services.ai.ai_step_list import (
    NotAStepList,
    graph_to_steps,
    parse_step_list,
    step_to_line,
)
from backend_host.src.services.ai.ai_preprocessing import (
    preprocess_prompt,
    check_exact_match,
    smart_preprocess  # NEW: Smart preprocessing with filtering
)


# =====================================================
# COMMAND SIGNATURES (action / verification params)
# =====================================================

def _signature(entry: Dict) -> str:
    """'press_key(key=OK)' / 'waitForTextToAppear(text=<Text to search for>)'.

    A catalog param is either a concrete value (remote keys) or a typed schema
    (create_param). A schema becomes a <placeholder> the AI fills; area params
    are left out — the AI cannot know screen coordinates.
    """
    parts = []
    for name, value in (entry.get('params') or {}).items():
        if isinstance(value, dict) and 'type' in value:
            if value.get('type') == 'area':
                continue
            hint = value.get('description') or value.get('type')
            parts.append(f"{name}=<{hint}{'' if value.get('required') else ', optional'}>")
        elif value not in (None, ''):
            parts.append(f"{name}={value}")
    return f"{entry.get('command')}({', '.join(parts)})"


def _block_item(command: str, params: Dict[str, Any], catalog: List[Dict]) -> Dict[str, Any]:
    """One item of an action/verification container block, typed from the catalog.

    Schema defaults fill the params the AI left out; concrete catalog values
    (press_key's key=UP) are examples, never defaults.
    """
    entry = next((e for e in catalog if e.get('command') == command), {})
    merged: Dict[str, Any] = {}
    for name, value in (entry.get('params') or {}).items():
        if isinstance(value, dict) and 'type' in value and value.get('default') not in (None, ''):
            merged[name] = value['default']
    merged.update(params)
    return {'command': command, 'action_type': entry.get('action_type'), 'params': merged}


def _check_commands(steps: List[Dict], context: Dict) -> None:
    """Every action/verification command must exist on the device. An invented one (e.g.
    "DetectMotion") fails the generation instead of becoming a block that cannot run."""
    for step_type, key in (('action', 'actions_raw'), ('verification', 'verifications_raw')):
        known = {e.get('command') for e in context.get(key) or []}
        if not known:
            continue  # no catalog (nodes given by the caller): nothing to check against
        for step in steps:
            if step['type'] != step_type:
                continue
            unknown = [it['command'] for it in step['items'] if it['command'] not in known]
            if unknown:
                raise ValueError(f"Unknown {step_type} command(s) on this device: {', '.join(unknown)}")


def _block_command(node: Dict) -> str:
    """First command of an action/verification container block."""
    data = node.get('data', {})
    items = data.get('actions') or data.get('verifications') or []
    return (items[0].get('command') or '') if items else ''


# =====================================================
# PROMPT TEMPLATES & VERSIONING
# =====================================================

PROMPT_TEMPLATES = {
    'v1': {
        'version': '1.0.0',
        'description': 'Original prompt template',
        'template': '''Task: {task}

{available_nodes}

{available_actions}

{available_verifications}

Generate a test case graph in JSON format with nodes and edges.'''
    },
    'v2': {
        'version': '2.0.0',
        'description': 'Simple text-based output that we parse ourselves',
        'template': '''CONTEXT:
You are generating automated test scripts for devices (mobile, STB, TV) to test apps like Netflix, YouTube, etc.
Your goal is to provide steps that simulate what a user manually does on the device.

KEY CONCEPTS:
- Navigation nodes are PRE-CODED and AUTONOMOUS - they automatically navigate to target screens without manual steps
- Actions represent user interactions (press button, enter text, swipe, etc.)
- Verifications check that something is visible or correct on screen

IMPORTANT:
- The nodes, actions, and verifications below are PRE-FILTERED for this specific task
- ONLY use items from the lists below - DO NOT invent new ones
- Navigation nodes are self-sufficient - they don't need actions or verifications unless the task explicitly requires user interaction AFTER navigation
- For simple navigation tasks, ONLY use Navigate steps

Task: {task}

FILTERED CONTEXT (pre-selected for this task):
Available Navigation Nodes:
{available_nodes}

Available Actions:
{available_actions}

Available Verifications:
{available_verifications}

Respond in this format:

GOAL: [One sentence: What is the user trying to achieve?]

REASONING: [Brief explanation: How do you translate the user's intent into these steps? Why did you choose this sequence?]

STEPS:
1. Navigate to: [node_name]
2. Action: [command](param=value, ...)
3. Verify: [command](param=value, ...)
... or include Action/Verify ONLY if the task explicitly requires them

Guidelines:
- For navigation-only tasks: Use ONLY Navigate steps
- Add Action steps ONLY if task requires user interaction (press, tap, enter text, swipe)
- Add Verify steps ONLY if task requires checking something specific
- Write every Action and Verify with its parameters, as listed: press_key(key=OK), waitForTextToAppear(text="Live TV")
- Replace each <placeholder> with a real value; leave out optional parameters you don't need
- Keep it simple and direct

DON'T DO THIS (common mistakes):
✗ Navigate to: Navigate to home  ← WRONG! Remove duplicate "Navigate to"
✗ Navigation: Navigate to home   ← WRONG! Use "Navigate to:" format only
✗ Verify: None                   ← WRONG! Skip verification entirely if not needed
✗ Action: press_key              ← WRONG! Say which key: press_key(key=OK)'''
    }
}

DEFAULT_PROMPT_VERSION = 'v2'  # Current production version

# Prompt editing (TASK-36 §3): the open graph as a step list + the requested change.
EDIT_TEMPLATE = '''CONTEXT:
You are editing an existing automated device test. The test is a numbered list of steps that run in order.

CURRENT STEPS:
{current_steps}

REQUESTED CHANGE:
{request}

Available Navigation Nodes:
{available_nodes}

{available_actions}

{available_verifications}

RULES:
- Return the COMPLETE new list, not only the changed steps.
- Copy every step the change does not concern EXACTLY as it is written above, in the same order.
- Use only navigation nodes, actions and verifications from the lists above, written with their parameters.
- Step formats:
  Navigate to: <node>
  Action: <command>(param=value, ...)
  Verify: <command>(param=value, ...)
  Wait: <milliseconds>
  Several commands in one step are joined with " + ". A step that must not stop the test when it fails ends with " [on fail: continue]".

Respond in this format:

GOAL: [One sentence: what the edited test checks]

REASONING: [What you changed and why]

STEPS:
1. ...'''


# =====================================================
# METRICS & OBSERVABILITY
# =====================================================

@dataclass
class GenerationMetrics:
    """Structured metrics for graph generation tracking"""
    fingerprint: str
    device_id: str
    team_id: str
    userinterface_name: str
    
    # Performance
    cached: bool
    preprocessing_method: str  # 'exact'|'learned'|'fuzzy'|'ai'|'none'
    duration_ms: int
    
    # AI usage (if applicable)
    ai_called: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    ai_cost_estimate: float  # Rough estimate in USD
    
    # Graph stats
    node_count: int
    edge_count: int
    
    # Preprocessing confidence (if applicable)
    preprocessing_confidence: Optional[float]
    auto_corrections_count: int
    
    # Timestamp
    timestamp: str
    
    def to_dict(self) -> Dict:
        """Convert to dict for logging"""
        return asdict(self)


class AIGraphBuilder:
    """
    AI Graph Builder - Orchestrates complete AI graph generation pipeline
    
    Architecture:
    - Preprocessing: Smart prompt analysis before AI
    - Generation: AI API call with optimized context
    - Post-processing: Graph validation and enhancement
    - Caching: Intelligent caching for performance
    """
    
    def __init__(self, device, prompt_version: str = DEFAULT_PROMPT_VERSION):
        """
        Initialize AIGraphBuilder for a device
        
        Args:
            device: Device instance with navigation_executor, testcase_executor
            prompt_version: AI prompt template version ('v1', 'v2', etc.)
        """
        self.device = device
        self._context_cache = {}
        # Use MEDIUM_TTL (5 minutes) - navigation changes frequently
        self._cache_ttl = CACHE_CONFIG['MEDIUM_TTL']
        
        # Prompt versioning
        if prompt_version not in PROMPT_TEMPLATES:
            print(f"[@ai_builder] ⚠️  Unknown prompt version '{prompt_version}', using '{DEFAULT_PROMPT_VERSION}'")
            prompt_version = DEFAULT_PROMPT_VERSION
        self.prompt_version = prompt_version
        template_info = PROMPT_TEMPLATES[prompt_version]
        print(f"[@ai_builder] Using prompt template: {template_info['version']} - {template_info['description']}")
        
        # Metrics collection
        self._metrics_buffer = []  # Store recent metrics
        self._metrics_max_buffer = 100  # Keep last 100 generations
        
        # Race condition prevention (cache locking)
        self._generation_locks = {}  # fingerprint → Lock
        self._lock_manager = threading.Lock()  # Protects _generation_locks dict
        
        print(f"[@ai_builder] Initialized for device: {device.device_id}")
        print(f"[@ai_builder] Context cache TTL: {self._cache_ttl}s ({self._cache_ttl/60:.1f} minutes)")
    
    def _record_metric(self, metric: GenerationMetrics):
        """
        Record generation metrics for observability
        
        Args:
            metric: GenerationMetrics instance
        """
        # Add to buffer
        self._metrics_buffer.append(metric)
        
        # Keep buffer size limited
        if len(self._metrics_buffer) > self._metrics_max_buffer:
            self._metrics_buffer.pop(0)
        
        # Log structured metrics
        print(f"[@ai_builder:metrics] {metric.preprocessing_method.upper()} generation")
        print(f"[@ai_builder:metrics]   Duration: {metric.duration_ms}ms")
        print(f"[@ai_builder:metrics]   Cached: {metric.cached}")
        if metric.ai_called:
            print(f"[@ai_builder:metrics]   AI tokens: {metric.total_tokens} (~${metric.ai_cost_estimate:.4f})")
        print(f"[@ai_builder:metrics]   Graph: {metric.node_count} nodes, {metric.edge_count} edges")
    
    def get_metrics_summary(self) -> Dict:
        """
        Get metrics summary for monitoring
        
        Returns:
            Dict with aggregated metrics
        """
        if not self._metrics_buffer:
            return {'total_generations': 0}
        
        total = len(self._metrics_buffer)
        cached = sum(1 for m in self._metrics_buffer if m.cached)
        ai_called = sum(1 for m in self._metrics_buffer if m.ai_called)
        total_tokens = sum(m.total_tokens for m in self._metrics_buffer)
        total_cost = sum(m.ai_cost_estimate for m in self._metrics_buffer)
        avg_duration = sum(m.duration_ms for m in self._metrics_buffer) / total
        
        # Count preprocessing methods
        methods = {}
        for m in self._metrics_buffer:
            methods[m.preprocessing_method] = methods.get(m.preprocessing_method, 0) + 1
        
        return {
            'total_generations': total,
            'cache_hit_rate': cached / total if total > 0 else 0,
            'ai_call_rate': ai_called / total if total > 0 else 0,
            'total_tokens_used': total_tokens,
            'total_cost_estimate': total_cost,
            'avg_duration_ms': avg_duration,
            'preprocessing_methods': methods,
            'device_id': self.device.device_id
        }
    
    def _create_metric(self, fingerprint: str, team_id: str, userinterface_name: str,
                      graph: Dict, cached: bool, preprocessing_method: str, 
                      duration_ms: int, ai_usage: Optional[Dict] = None,
                      preprocessing_confidence: Optional[float] = None,
                      auto_corrections_count: int = 0) -> GenerationMetrics:
        """
        Create a GenerationMetrics instance
        
        Args:
            fingerprint: Graph fingerprint
            team_id: Team ID
            userinterface_name: Interface name
            graph: Generated graph
            cached: Whether loaded from cache
            preprocessing_method: 'exact'|'learned'|'fuzzy'|'ai'|'none'
            duration_ms: Generation duration in milliseconds
            ai_usage: AI token usage dict (if AI was called)
            preprocessing_confidence: Confidence score for preprocessing
            auto_corrections_count: Number of auto-corrections applied
            
        Returns:
            GenerationMetrics instance
        """
        ai_called = ai_usage is not None
        prompt_tokens = ai_usage.get('prompt_tokens', 0) if ai_usage else 0
        completion_tokens = ai_usage.get('completion_tokens', 0) if ai_usage else 0
        total_tokens = ai_usage.get('total_tokens', 0) if ai_usage else 0
        
        # Rough cost estimate (OpenRouter pricing varies, using ~$0.01 per 1K tokens as average)
        ai_cost_estimate = (total_tokens / 1000) * 0.01 if ai_called else 0.0
        
        return GenerationMetrics(
            fingerprint=fingerprint,
            device_id=self.device.device_id,
            team_id=team_id,
            userinterface_name=userinterface_name,
            cached=cached,
            preprocessing_method=preprocessing_method,
            duration_ms=duration_ms,
            ai_called=ai_called,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            ai_cost_estimate=ai_cost_estimate,
            node_count=len(graph.get('nodes', [])),
            edge_count=len(graph.get('edges', [])),
            preprocessing_confidence=preprocessing_confidence,
            auto_corrections_count=auto_corrections_count,
            timestamp=datetime.now().isoformat()
        )
    
    # ========================================
    # PUBLIC API
    # ========================================
    
    def generate_graph(self,
                      prompt: str,
                      userinterface_name: str,
                      team_id: str,
                      current_node_id: Optional[str] = None,
                      available_nodes: Optional[List[str]] = None,
                      notes: Optional[str] = None) -> Dict[str, Any]:
        """
        notes: what the interface's nodes do (e.g. Test Prompt's action nodes: "live_chup: zap
        channel up, repeatable"). Given to the AI as context after preprocessing, never parsed
        as part of the prompt (its words are not screen names to disambiguate).

        Generate test case graph from natural language prompt
        
        Complete pipeline:
        1. Load context (available nodes/actions/verifications)
        2. Check cache
        3. Preprocess prompt (exact match, disambiguation)
        4. Call AI if needed
        5. Parse & validate response
        6. Enforce label conventions
        7. Pre-fetch navigation transitions
        8. Return graph + stats
        
        Args:
            prompt: Natural language test case description
            userinterface_name: Interface context (e.g., "example_mobile")
            team_id: Team ID for database operations
            current_node_id: Optional current navigation position
            available_nodes: Pre-fetched nodes to use (skips cache if provided)
            
        Returns:
            {
                'success': bool,
                'graph': {'nodes': [...], 'edges': [...]},
                'analysis': str,
                'execution_time': float,
                'generation_stats': {
                    'prompt_tokens': int,
                    'completion_tokens': int,
                    'block_counts': {...}
                }
            }
        """
        start_time = time.time()
        
        try:
            print(f"[@ai_builder] 🎨 Starting graph generation")
            print(f"[@ai_builder]   Prompt: {prompt[:100]}...")
            print(f"[@ai_builder]   Interface: {userinterface_name}")
            
            # Step 1: Load context (or use provided nodes)
            context = dict(self._load_context(userinterface_name, current_node_id, team_id, available_nodes))
            context['notes'] = (notes or '').strip()
            
            # Step 2: Generate fingerprint for this request
            fingerprint = _generate_fingerprint(f"{prompt}\n{context['notes']}", context)
            
            # Step 3: Get or create lock for this fingerprint (prevent duplicate AI calls)
            with self._lock_manager:
                if fingerprint not in self._generation_locks:
                    self._generation_locks[fingerprint] = threading.Lock()
                generation_lock = self._generation_locks[fingerprint]
            
            # Step 4: Acquire lock (only ONE request per fingerprint generates)
            with generation_lock:
                # Check cache AGAIN (another request might have just completed)
                cached = get_graph_by_fingerprint(fingerprint, team_id)
                
                if cached:
                    print(f"[@ai_builder] ✅ CACHE HIT (after lock) - returning immediately")
                    return {
                        'success': True,
                        'graph': cached['graph'],
                        'analysis': cached['analysis'],
                        'execution_time': time.time() - start_time,
                        'message': 'Graph loaded from cache',
                        'cached': True,
                        'available_nodes': context.get('nodes_raw', [])  # Include nodes used
                    }
                
                # Step 5: SMART PREPROCESSING with context filtering
                # nodes_raw is already a list of strings, actions_raw and verifications_raw are lists of dicts
                node_list = context.get('nodes_raw', [])  # Already strings: ['home', 'live', ...]
                action_list = [action.get('command', action.get('action_type', '')) 
                              for action in context.get('actions_raw', [])]
                verification_list = [v.get('command', v.get('verification_type', ''))
                                    for v in context.get('verifications_raw', [])]
                
                # Run smart preprocessing (intent extraction + context filtering)
                preprocessed = smart_preprocess(
                    prompt=prompt,
                    all_nodes=node_list,
                    all_actions=action_list,
                    all_verifications=verification_list,
                    team_id=team_id,
                    userinterface_name=userinterface_name
                )
                
                # Handle different preprocessing outcomes
                if preprocessed['status'] == 'exact_match':
                    # Simple prompt with exact match - skip AI entirely
                    exact_node = preprocessed['node']
                    print(f"[@ai_builder] 🎯 Exact match - generating simple graph (no AI)")
                    graph = self._create_simple_navigation_graph(exact_node)
                    
                    # Post-process to ensure terminal blocks
                    graph = self._postprocess_graph(graph, context)
                    
                    analysis = f"🎯 Direct Match Found\n\nNo AI needed - '{exact_node}' was found as an exact match in available nodes. Created simple navigation path directly."
                    
                    # Store in cache
                    store_graph(
                        fingerprint=fingerprint,
                        original_prompt=prompt,
                        device_model=self.device.device_model,
                        userinterface_name=userinterface_name,
                        available_nodes=node_list,
                        graph=graph,
                        analysis=analysis,
                        team_id=team_id
                    )
                    
                    return {
                        'success': True,
                        'graph': graph,
                        'analysis': analysis,
                        'execution_time': time.time() - start_time,
                        'message': 'Simple navigation generated (exact match)',
                        'cached': False,
                        'exact_match': True,
                        'available_nodes': context.get('nodes_raw', [])  # Include nodes used
                    }
                
                elif preprocessed['status'] == 'needs_disambiguation':
                    # Return disambiguation request to frontend
                    print(f"[@ai_builder] ⚠️  Disambiguation needed")
                    
                    try:
                        ambiguities = preprocessed.get('ambiguities', [])
                        auto_corrections = preprocessed.get('auto_corrections', [])
                        
                        # Validate disambiguation data
                        if not ambiguities:
                            print(f"[@ai_builder] ❌ ERROR: Ambiguities list is empty!")
                            return {
                                'success': False,
                                'error': 'Preprocessing returned needs_disambiguation but no ambiguities provided',
                                'execution_time': time.time() - start_time
                            }
                        
                        print(f"[@ai_builder]   Ambiguities count: {len(ambiguities)}")
                        print(f"[@ai_builder]   Auto-corrections count: {len(auto_corrections)}")
                        
                        # Log each ambiguity for debugging
                        for idx, amb in enumerate(ambiguities, 1):
                            phrase = amb.get('phrase', 'UNKNOWN')
                            suggestions = amb.get('suggestions', [])
                            print(f"[@ai_builder]   Ambiguity {idx}: '{phrase}' → {len(suggestions)} options")
                        
                        # Build disambiguation response
                        response = {
                            'success': False,
                            'needs_disambiguation': True,
                            'ambiguities': ambiguities,
                            'auto_corrections': auto_corrections,
                            'available_nodes': node_list,  # Full list for frontend reference
                            'original_prompt': prompt,
                            'execution_time': time.time() - start_time
                        }
                        
                        print(f"[@ai_builder] 📤 Returning disambiguation response to frontend")
                        return response
                        
                    except Exception as e:
                        print(f"[@ai_builder] ❌ ERROR building disambiguation response: {e}")
                        import traceback
                        traceback.print_exc()
                        return {
                            'success': False,
                            'error': f'Failed to build disambiguation response: {str(e)}',
                            'execution_time': time.time() - start_time
                        }
                
                elif preprocessed['status'] == 'impossible':
                    # Task cannot be completed (missing required context)
                    return {
                        'success': False,
                        'error': preprocessed['reason'],
                        'execution_time': time.time() - start_time
                    }
                
                elif preprocessed['status'] == 'ready':
                    # Ready for AI generation with filtered context
                    final_prompt = preprocessed['corrected_prompt']
                    filtered_context = preprocessed['filtered_context']
                    structure_hints = preprocessed['structure_hints']
                    formatted_context = preprocessed['formatted_context']
                    
                    print(f"[@ai_builder] ✅ Preprocessing complete")
                    print(f"[@ai_builder]   Context reduction: {preprocessed['stats']['reduction_percent']}")
                    
                    # Update context with filtered data for AI
                    # Replace full catalog with filtered items
                    context['available_nodes'] = formatted_context
                    # The notes name nodes the prompt's words don't (e.g. "zap" → live_chup); the
                    # relevance filter drops those, and the AI may only use listed nodes.
                    noted = [n for n in context.get('nodes_raw', [])
                             if context.get('notes') and re.search(rf'(?<![\w-]){re.escape(n)}(?![\w-])', context['notes'])]
                    if noted:
                        context['available_nodes'] += (
                            "\nNavigation nodes from the interface notes (also usable):\n"
                            + "\n".join(f"- {n}" for n in noted))
                    context['structure_hints'] = structure_hints
                    context['intent'] = preprocessed['intent']
                    
                    # 📋 DEBUG: Log what nodes/actions/verifications are being sent to AI
                    print(f"[@ai_builder] 📋 Context being sent to AI:")
                    print(f"[@ai_builder]   Nodes (raw): {context.get('nodes_raw', [])}")
                    print(f"[@ai_builder]   Actions count: {len(context.get('actions_raw', []))}")
                    print(f"[@ai_builder]   Verifications count: {len(context.get('verifications_raw', []))}")
                    if filtered_context and 'Navigation' in formatted_context:
                        # Extract node list from formatted context for debugging
                        node_matches = re.findall(r'- (\w+)', formatted_context)
                        if node_matches:
                            print(f"[@ai_builder]   Filtered nodes for AI: {node_matches}")
                else:
                    # Unknown status
                    return {
                        'success': False,
                        'error': f"Unknown preprocessing status: {preprocessed['status']}",
                        'execution_time': time.time() - start_time
                    }
                
                # Step 6: Generate with AI (inside lock to prevent duplicate calls)
                ai_response = self._generate_with_ai(final_prompt, context, current_node_id)
                
                # Step 7: Check feasibility
                if not ai_response.get('feasible', True):
                    return {
                        'success': False,
                        'error': 'Task not feasible',
                        'analysis': ai_response.get('analysis', ''),
                        'execution_time': time.time() - start_time
                    }
                
                # Step 8: Extract graph
                graph = ai_response.get('graph', {})
                if not graph or not graph.get('nodes'):
                    return {
                        'success': False,
                        'error': 'AI returned empty graph',
                        'execution_time': time.time() - start_time
                    }
                
                # Step 9: Post-process graph
                graph = self._postprocess_graph(graph, context)
                
                # 📋 DEBUG: Log what nodes the AI generated
                print(f"[@ai_builder] 📋 AI Generated Graph:")
                print(f"[@ai_builder]   Total blocks: {len(graph.get('nodes', []))}")
                for idx, node in enumerate(graph.get('nodes', [])[:10]):  # Show first 10
                    node_type = node.get('type', 'unknown')
                    node_id = node.get('id', f'node_{idx}')
                    if node_type == 'navigation':
                        target = node.get('data', {}).get('target_node_label') or node.get('data', {}).get('target_node_id')
                        print(f"[@ai_builder]     {idx+1}. Navigation → {target}")
                    elif node_type == 'action':
                        print(f"[@ai_builder]     {idx+1}. Action: {_block_command(node)}")
                    elif node_type == 'verification':
                        print(f"[@ai_builder]     {idx+1}. Verify: {_block_command(node)}")
                    else:
                        print(f"[@ai_builder]     {idx+1}. {node_type}")
                
                # Step 10: Calculate stats
                stats = self._calculate_stats(graph, ai_response.get('_usage', {}))
                
                # Step 11: Store in cache for future use (still inside lock)
                store_graph(
                    fingerprint=fingerprint,
                    original_prompt=prompt,
                    device_model=context['device_model'],
                    userinterface_name=userinterface_name,
                    available_nodes=list(context.get('available_nodes', [])),
                    graph=graph,
                    analysis=ai_response.get('analysis', ''),
                    team_id=team_id
                )
                
                print(f"[@ai_builder] ✅ Graph generated successfully")
                print(f"[@ai_builder]   Nodes: {len(graph.get('nodes', []))}, Edges: {len(graph.get('edges', []))}")
                
                return {
                    'success': True,
                    'graph': graph,
                    'analysis': ai_response.get('analysis', ''),
                    'plan_id': ai_response.get('id'),
                    'execution_time': time.time() - start_time,
                    'message': 'Graph generated successfully',
                    'generation_stats': stats,
                    'available_nodes': context.get('nodes_raw', [])  # Include nodes used
                }
            # Lock released here - subsequent requests can now use cached result
            
        except Exception as e:
            print(f"[@ai_builder] ❌ Graph generation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': f'Graph generation error: {str(e)}',
                'execution_time': time.time() - start_time
            }
    
    def edit_graph(self,
                   prompt: str,
                   current_graph: Dict[str, Any],
                   userinterface_name: str,
                   team_id: str) -> Dict[str, Any]:
        """
        Change an open step-list graph by prompt (TASK-36 §3).
        
        The graph is written as a numbered step list (ai_step_list), the LLM returns the
        complete edited list, and it is turned back into a graph. Blocks the edit did not
        change are copied from the original. Not cached: an edit depends on the graph.
        
        Returns {'success', 'graph', 'analysis', 'steps_before', 'steps_after'}, or
        {'success': False, 'error', 'not_a_step_list'?}.
        """
        start_time = time.time()
        try:
            original = graph_to_steps(current_graph)
        except NotAStepList as e:
            return {
                'success': False,
                'not_a_step_list': True,
                'error': f'Prompt editing needs a step-list graph: {e}',
            }
        steps_before = [step_to_line(step) for step, _ in original]
        reuse_blocks = {line: node.get('data') or {} for line, (_, node) in zip(steps_before, original)}
        
        try:
            context = dict(self._load_context(userinterface_name, None, team_id))
            ai_prompt = EDIT_TEMPLATE.format(
                current_steps='\n'.join(f'{i}. {line}' for i, line in enumerate(steps_before, 1)) or '(no steps yet)',
                request=prompt,
                available_nodes='\n'.join(f'- {n}' for n in context.get('nodes_raw', [])[:80]),
                available_actions=context.get('available_actions', ''),
                available_verifications=context.get('available_verifications', ''),
            )
            print(f"[@ai_builder:edit] Editing a {len(steps_before)}-step graph: {prompt[:100]}")
            result = call_text_ai(
                prompt=ai_prompt,
                usage='text.plan',
                max_tokens=AI_CONFIG['MAX_TOKENS'],
                temperature=AI_CONFIG['TEMPERATURE'],
            )
            if not result.get('success'):
                raise Exception(f"AI call failed: {result.get('error')}")
            context['reuse_blocks'] = reuse_blocks
            parsed = self._parse_ai_response(result['content'], context)
            graph = self._postprocess_graph(parsed['graph'], context)
            steps_after = [step_to_line(step) for step, _ in graph_to_steps(graph)]
            return {
                'success': True,
                'graph': graph,
                'analysis': parsed.get('analysis', ''),
                'steps_before': steps_before,
                'steps_after': steps_after,
                'execution_time': time.time() - start_time,
            }
        except Exception as e:
            print(f"[@ai_builder:edit] ❌ Edit failed: {e}")
            return {'success': False, 'error': f'Graph edit error: {e}', 'execution_time': time.time() - start_time}
    
    # ========================================
    # CONTEXT LOADING
    # ========================================
    
    def _load_context(self, 
                      userinterface_name: str, 
                      current_node_id: Optional[str], 
                      team_id: str,
                      available_nodes: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Load execution context: available nodes, actions, verifications
        
        Uses caching to avoid repeated database queries.
        If available_nodes provided, uses them directly (skips cache).
        
        Args:
            available_nodes: Pre-fetched nodes to use (skips cache/fetch if provided)
        """
        # If nodes provided, use directly and skip cache
        if available_nodes is not None:
            print(f"[@ai_builder:context] Using provided nodes: {len(available_nodes)} nodes")
            return {
                'device_model': self.device.device_model,
                'userinterface_name': userinterface_name,
                'team_id': team_id,
                'current_node_id': current_node_id,
                'nodes_raw': available_nodes,
                'available_nodes': self._format_navigation_nodes(available_nodes),
                'actions_raw': [],
                'available_actions': [],
                'verifications_raw': [],
                'available_verifications': [],
                'source': 'provided'
            }
        
        # Check cache
        cache_key = f"{self.device.device_id}_{userinterface_name}_{team_id}"
        cached_data, cache_time = self._context_cache.get(cache_key, (None, None))
        
        if cached_data and cache_time:
            current_time = time.time()
            if current_time - cache_time < self._cache_ttl:
                print(f"[@ai_builder:context] ✅ Cache HIT (age: {current_time - cache_time:.1f}s)")
                cached_data['current_node_id'] = current_node_id
                return cached_data
        
        print(f"[@ai_builder:context] Loading fresh context...")
        
        # Load from device services
        context = {
            'device_model': self.device.device_model,
            'userinterface_name': userinterface_name,
            'team_id': team_id,
            'current_node_id': current_node_id,
        }
        
        # Get navigation nodes
        nav_context = self.device.navigation_executor.get_available_context(userinterface_name, team_id)
        nav_nodes = nav_context.get('available_nodes', [])  # List of strings: ['home', 'live', ...]
        
        # Store as strings directly - preprocessing works with strings
        context['nodes_raw'] = nav_nodes
        # Store FORMATTED strings for AI prompt
        context['available_nodes'] = self._format_navigation_nodes(nav_nodes)
        
        # Get actions
        action_context = self.device.action_executor.get_available_context(userinterface_name)
        actions = action_context.get('available_actions', [])
        context['actions_raw'] = actions
        context['available_actions'] = self._format_action_context(actions)
        
        # Get verifications
        verification_context = self.device.verification_executor.get_available_context(userinterface_name)
        verifications = verification_context.get('available_verifications', [])
        context['verifications_raw'] = verifications
        context['available_verifications'] = self._format_verification_context(verifications)
        
        # Cache it
        self._context_cache[cache_key] = (context, time.time())
        
        print(f"[@ai_builder:context] Loaded: {len(nav_nodes)} nodes, {len(actions)} actions, {len(verifications)} verifications")
        print(f"[@ai_builder:context] 📋 Available navigation nodes: {nav_nodes}")
        
        return context
    
    def _format_navigation_nodes(self, nodes: List[str]) -> str:
        """Format navigation node labels for AI prompt"""
        if not nodes:
            return "Available Navigation Nodes: []"
        
        node_list = [f"- {node}" for node in nodes[:50]]  # Limit to 50
        return f"Available Navigation Nodes:\n" + "\n".join(node_list)
    
    def _format_action_context(self, actions: List[Dict]) -> str:
        """Format actions for AI prompt"""
        if not actions:
            return "Available Actions: []"
        
        action_list = []
        for action in actions[:40]:  # Limit to 40
            sig = _signature(action)
            desc = action.get('description', '')
            line = f"- {sig}: {desc}" if desc else f"- {sig}"
            if line not in action_list:
                action_list.append(line)
        
        return f"Available Actions:\n" + "\n".join(action_list)
    
    def _format_verification_context(self, verifications: List[Dict]) -> str:
        """Format verifications for AI prompt"""
        if not verifications:
            return "Available Verifications: []"
        
        verify_list = []
        for verify in verifications[:40]:  # Limit to 40
            sig = _signature(verify)
            desc = verify.get('description', '')
            line = f"- {sig}: {desc}" if desc else f"- {sig}"
            if line not in verify_list:
                verify_list.append(line)
        
        return f"Available Verifications:\n" + "\n".join(verify_list)
    
    # ========================================
    # AI GENERATION
    # ========================================
    
    def _generate_with_ai(self, prompt: str, context: Dict, current_node_id: Optional[str]) -> Dict:
        """
        Generate graph using AI
        
        Builds optimized prompt, calls API, parses response
        """
        # Build AI prompt
        ai_prompt = self._build_ai_prompt(prompt, context)
        
        # Call AI
        print(f"[@ai_builder:ai] Calling AI (prompt length: {len(ai_prompt)} chars)...")
        result = call_text_ai(
            prompt=ai_prompt,
            usage='text.plan',
            max_tokens=AI_CONFIG['MAX_TOKENS'],
            temperature=AI_CONFIG['TEMPERATURE'],
        )
        
        if not result.get('success'):
            raise Exception(f"AI call failed: {result.get('error')}")
        
        print(f"[@ai_builder:ai] ✅ AI response received ({len(result.get('content', ''))} chars)")
        
        # Log raw AI response for debugging
        print(f"[@ai_builder:ai] Raw AI response:")
        print("="*80)
        print(result.get('content', ''))
        print("="*80)
        
        # Parse JSON
        parsed = self._parse_ai_response(result['content'], context)
        
        # Attach usage stats
        if 'usage' in result:
            parsed['_usage'] = result['usage']
        
        return parsed
    
    def _build_ai_prompt(self, prompt: str, context: Dict) -> str:
        """
        Build AI prompt using versioned template
        
        Uses self.prompt_version to select template, allowing A/B testing
        and gradual rollout of prompt improvements.
        
        Context-aware: Includes current device state and structure hints
        """
        template_config = PROMPT_TEMPLATES[self.prompt_version]
        template = template_config['template']
        
        # Get current node context (context-aware generation)
        current_node_id = context.get('current_node_id')
        current_context = ""
        if current_node_id and current_node_id != 'unknown':
            current_context = f"\n\nCURRENT DEVICE STATE:\n- Currently at node: {current_node_id}\n- If already at target node, skip navigation\n- Optimize path from current position"
        
        # Get structure hints from smart preprocessing
        structure_hints = context.get('structure_hints', '')
        if structure_hints:
            current_context += f"\n\n{structure_hints}"
        
        # Format template with context
        ai_prompt = template.format(
            task=prompt,
            available_nodes=context.get('available_nodes', ''),
            available_actions=context.get('available_actions', ''),
            available_verifications=context.get('available_verifications', '')
        ) + current_context
        if context.get('notes'):
            ai_prompt += f"\n\nINTERFACE NOTES (what these screens and actions do; use them):\n{context['notes']}"
        
        print(f"[@ai_builder:prompt] Using template {self.prompt_version} ({template_config['version']})")
        if current_node_id:
            print(f"[@ai_builder:prompt] Context-aware: current node = {current_node_id}")
        if structure_hints:
            print(f"[@ai_builder:prompt] Structure hints included")
        
        return ai_prompt
    
    def _parse_ai_response(self, content: str, context: Dict) -> Dict[str, Any]:
        """
        Parse AI text response and convert to graph structure
        
        Expected format:
        GOAL: ...
        REASONING: ...
        STEPS:
        1. Navigate to: node_name
        2. Action: command(param=value)
        3. Verify: command(param=value)
        """
        try:
            print(f"[@ai_builder:parse] Parsing AI text response...")
            
            # Extract GOAL (optional)
            goal_match = re.search(r'GOAL:\s*(.+?)(?:\n\n|\n(?=[A-Z]+:)|$)', content, re.DOTALL)
            goal = goal_match.group(1).strip() if goal_match else None
            
            # Extract REASONING (optional)
            reasoning_match = re.search(r'REASONING:\s*(.+?)(?:\n\n|\n(?=STEPS:)|$)', content, re.DOTALL)
            reasoning = reasoning_match.group(1).strip() if reasoning_match else None
            
            # Build analysis from GOAL + REASONING (fallback to legacy ANALYSIS field)
            if goal and reasoning:
                analysis = f"{goal}\n\n{reasoning}"
            elif goal:
                analysis = goal
            elif reasoning:
                analysis = reasoning
            else:
                # Fallback: try old ANALYSIS field for backward compatibility
                analysis_match = re.search(r'ANALYSIS:\s*(.+?)(?:\n\nSTEPS:|$)', content, re.DOTALL)
                analysis = analysis_match.group(1).strip() if analysis_match else "AI-generated test case"
            
            # Extract steps
            steps_match = re.search(r'STEPS:\s*(.+)', content, re.DOTALL)
            if not steps_match:
                raise Exception("AI response missing STEPS section")
            
            steps = parse_step_list(steps_match.group(1))
            _check_commands(steps, context)
            
            if not steps:
                raise Exception("No valid steps found in AI response")
            
            print(f"[@ai_builder:parse] ✅ Parsed {len(steps)} steps from AI")
            print(f"[@ai_builder:parse] Steps breakdown:")
            for i, step in enumerate(steps, 1):
                print(f"[@ai_builder:parse]   {i}. {step_to_line(step)}")
            
            # Convert steps to graph structure (an edit reuses the blocks it did not change)
            graph = self._steps_to_graph(steps, context, context.get('reuse_blocks'))
            
            print(f"[@ai_builder:parse] Analysis: {analysis[:100]}...")
            
            return {
                'analysis': analysis,
                'feasible': True,
                'graph': graph
            }
            
        except Exception as e:
            print(f"[@ai_builder:parse] ❌ Parsing error: {e}")
            print(f"[@ai_builder:parse] Content preview:")
            print("="*80)
            print(content[:500])
            print("="*80)
            raise Exception(f"Failed to parse AI response: {str(e)}")
    
    def _steps_to_graph(self, steps: List[Dict], context: Dict,
                        reuse_blocks: Optional[Dict[str, Dict]] = None) -> Dict:
        """
        Convert a step list (ai_step_list.parse_step_line) to a testcase graph.
        
        Action and verification steps become the container blocks the testcase
        executor runs and the builders edit: data.actions / data.verifications.
        A step whose canonical line is in reuse_blocks (an edit's unchanged block)
        keeps that block's data as is, so fields the step text does not carry
        (references, thresholds, areas) survive the edit.
        
        Args:
            steps: step dicts in run order
            context: Loaded context; its actions_raw / verifications_raw type each command
            reuse_blocks: canonical line -> original block data (prompt edit only)
        """
        nodes = [{'id': 'start', 'type': 'start', 'position': {'x': 250, 'y': 100}, 'data': {'label': 'START'}}]
        edges = []
        y_position = 200
        y_increment = 100
        prefix = {'navigation': 'nav', 'action': 'act', 'verification': 'ver', 'wait': 'wait'}
        counter = {k: 0 for k in prefix}
        ids = []
        
        for step in steps:
            step_type = step['type']
            counter[step_type] += 1
            node_id = f"{prefix[step_type]}{counter[step_type]}"
            ids.append(node_id)
            reused = (reuse_blocks or {}).get(step_to_line(step))
            if reused is not None:
                node_type = 'sleep' if step_type == 'wait' else step_type
                data = dict(reused)
            elif step_type == 'navigation':
                node_type = 'navigation'
                data = {
                    'target_node_label': step['target'],
                    'target_node_id': step['target'],
                    'action_type': 'navigation',
                    'transitions': [],  # Empty - navigation is autonomous at runtime
                }
            elif step_type == 'wait':
                # Same block QuickTest writes for a wait: the 'sleep' standard block (ms).
                node_type = 'sleep'
                data = {'command': 'sleep', 'params': {'duration': step['ms']}}
            elif step_type == 'action':
                node_type = 'action'
                data = {'actions': [_block_item(it['command'], it['params'], context.get('actions_raw', []))
                                    for it in step['items']]}
            else:
                node_type = 'verification'
                items = []
                for it in step['items']:
                    item = _block_item(it['command'], it['params'], context.get('verifications_raw', []))
                    # The verification context types each command as 'verification_<type>'.
                    item['verification_type'] = (item.pop('action_type') or 'verification_text').replace('verification_', '')
                    items.append(item)
                data = {'verifications': items, 'verification_pass_condition': 'all'}
            nodes.append({'id': node_id, 'type': node_type, 'position': {'x': 250, 'y': y_position}, 'data': data})
            y_position += y_increment
        
        nodes.append({'id': 'success', 'type': 'success', 'position': {'x': 250, 'y': y_position}, 'data': {'label': 'SUCCESS'}})
        chain = ['start'] + ids + ['success']
        for source, target in zip(chain, chain[1:]):
            edges.append({'id': f'e_{source}_{target}', 'source': source, 'target': target,
                          'sourceHandle': 'success', 'type': 'success'})
        # "[on fail: continue]": the failure edge goes on to the next block too. Every other
        # block has no failure edge, which the executor treats as a failed run.
        for step, source, target in zip(steps, ids, chain[2:]):
            if step.get('continue_on_fail'):
                edges.append({'id': f'e_{source}_{target}_failure', 'source': source, 'target': target,
                              'sourceHandle': 'failure', 'type': 'failure'})
        
        return {'nodes': nodes, 'edges': edges}
    
    def _sanitize_json_string(self, json_str: str) -> str:
        """Remove/escape control characters that break JSON parsing"""
        # Replace literal newlines in strings with \n
        sanitized = re.sub(r'(?<!\\)\n(?=[^{}\[\]:,]*["\'])', r'\\n', json_str)
        # Replace tabs
        sanitized = re.sub(r'(?<!\\)\t', r'\\t', sanitized)
        # Remove other control characters
        sanitized = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', sanitized)
        return sanitized
    
    # ========================================
    # POST-PROCESSING
    # ========================================
    
    def _postprocess_graph(self, graph: Dict, context: Dict) -> Dict:
        """
        Post-process graph after AI generation
        
        Steps:
        1. Ensure terminal blocks exist (START, SUCCESS, FAILURE)
        2. Validate structure
        3. Enforce label conventions
        4. Filter out invalid nodes (e.g., "None" verifications)
        """
        print(f"[@ai_builder:postprocess] Processing graph...")
        
        # Step 1: Ensure terminal blocks exist
        graph = self._ensure_terminal_blocks(graph)
        
        # Step 2: Enforce labels
        graph = self._enforce_labels(graph)
        
        # Step 3: Filter out invalid nodes
        graph = self._filter_invalid_nodes(graph)
        
        print(f"[@ai_builder:postprocess] ✅ Post-processing complete")
        
        return graph
    
    def _ensure_terminal_blocks(self, graph: Dict) -> Dict:
        """
        Ensure START, SUCCESS, and FAILURE terminal blocks exist
        
        If any are missing, add them with default positions
        """
        nodes = graph.get('nodes', [])
        node_types = {node.get('type') for node in nodes}
        
        # Check which terminal blocks exist
        has_start = 'start' in node_types
        has_success = 'success' in node_types
        has_failure = 'failure' in node_types
        
        if not has_start:
            print(f"[@ai_builder:postprocess] ⚠️  Missing START block - adding it")
            nodes.insert(0, {
                'id': 'start',
                'type': 'start',
                'position': {'x': 400, 'y': 50},
                'data': {'label': 'START'}
            })
        
        if not has_success:
            print(f"[@ai_builder:postprocess] ⚠️  Missing SUCCESS block - adding it")
            nodes.append({
                'id': 'success',
                'type': 'success',
                'position': {'x': 400, 'y': 600},
                'data': {'label': 'SUCCESS'}
            })
        
        if not has_failure:
            print(f"[@ai_builder:postprocess] ⚠️  Missing FAILURE block - adding it")
            nodes.append({
                'id': 'failure',
                'type': 'failure',
                'position': {'x': 700, 'y': 600},
                'data': {'label': 'FAILURE'}
            })
        
        graph['nodes'] = nodes
        return graph
    
    def _enforce_labels(self, graph: Dict) -> Dict:
        """
        Enforce label naming conventions
        
        - navigation: navigation_N:target_node
        - action: action_N:command
        - verification: verification_N:type
        - start/success/failure: uppercase
        """
        nodes = graph.get('nodes', [])
        
        nav_counter = 0
        action_counter = 0
        verify_counter = 0
        
        for node in nodes:
            node_type = node.get('type')
            data = node.get('data', {})
            
            if node_type == 'start':
                data['label'] = 'START'
            elif node_type == 'success':
                data['label'] = 'SUCCESS'
            elif node_type == 'failure':
                data['label'] = 'FAILURE'
            elif node_type == 'navigation':
                nav_counter += 1
                target = data.get('target_node_label') or data.get('target_node') or data.get('target_node_id') or 'unknown'
                data['label'] = f"navigation_{nav_counter}:{target}"
            elif node_type == 'action':
                action_counter += 1
                data['label'] = f"action_{action_counter}:{_block_command(node) or 'action'}"
            elif node_type == 'verification':
                verify_counter += 1
                data['label'] = f"verification_{verify_counter}:{_block_command(node) or 'verify'}"
            elif node_type == 'sleep':
                data['label'] = f"wait:{(data.get('params') or {}).get('duration', '')}ms"
        
        print(f"[@ai_builder:labels] Enforced labels: {nav_counter} nav, {action_counter} action, {verify_counter} verify")
        
        return graph
    
    def _filter_invalid_nodes(self, graph: Dict) -> Dict:
        """
        Filter out invalid nodes from the graph
        
        Removes:
        - Verification nodes with type "None"
        - Action nodes with command "None"
        - Empty or placeholder nodes
        
        Also removes edges connected to removed nodes
        """
        nodes = graph.get('nodes', [])
        edges = graph.get('edges', [])
        
        # Track nodes to remove
        nodes_to_remove = set()
        
        for node in nodes:
            node_id = node.get('id')
            node_type = node.get('type')
            data = node.get('data', {})
            
            # Check action / verification nodes for a "None" command
            if node_type in ('action', 'verification'):
                command = _block_command(node).strip()
                if not command or command.lower() in ['none', 'null', '']:
                    print(f"[@ai_builder:filter] ❌ Removing invalid {node_type} node: {node_id} (command: '{command}')")
                    nodes_to_remove.add(node_id)
        
        if not nodes_to_remove:
            return graph
        
        # Remove invalid nodes
        filtered_nodes = [n for n in nodes if n.get('id') not in nodes_to_remove]
        
        # Remove edges connected to removed nodes
        filtered_edges = [
            e for e in edges 
            if e.get('source') not in nodes_to_remove and e.get('target') not in nodes_to_remove
        ]
        
        # Reconnect the graph: if we removed nodes, connect previous valid node to next valid node
        # Build adjacency map from remaining edges
        edge_map = {}  # source -> target
        for edge in filtered_edges:
            edge_map[edge['source']] = edge['target']
        
        # For each removed node, find its predecessor and successor, then connect them
        for removed_id in nodes_to_remove:
            # Find edge pointing TO this node
            predecessor = None
            for edge in edges:
                if edge.get('target') == removed_id:
                    predecessor = edge.get('source')
                    break
            
            # Find edge starting FROM this node
            successor = None
            for edge in edges:
                if edge.get('source') == removed_id:
                    successor = edge.get('target')
                    break
            
            # If both exist, reconnect
            if predecessor and successor and predecessor not in nodes_to_remove and successor not in nodes_to_remove:
                # Check if edge doesn't already exist
                edge_exists = any(
                    e.get('source') == predecessor and e.get('target') == successor
                    for e in filtered_edges
                )
                if not edge_exists:
                    new_edge = {
                        'id': f'e_{predecessor}_{successor}',
                        'source': predecessor,
                        'target': successor,
                        'sourceHandle': 'success',
                        'type': 'success'
                    }
                    filtered_edges.append(new_edge)
                    print(f"[@ai_builder:filter] ✅ Reconnected: {predecessor} → {successor}")
        
        print(f"[@ai_builder:filter] Removed {len(nodes_to_remove)} invalid nodes, reconnected graph")
        
        graph['nodes'] = filtered_nodes
        graph['edges'] = filtered_edges
        
        return graph
    
    # ========================================
    # STATS CALCULATION
    # ========================================
    
    def _calculate_stats(self, graph: Dict, usage: Dict) -> Dict:
        """Calculate generation statistics"""
        nodes = graph.get('nodes', [])
        
        block_counts = {
            'navigation': len([n for n in nodes if n.get('type') == 'navigation']),
            'action': len([n for n in nodes if n.get('type') == 'action']),
            'verification': len([n for n in nodes if n.get('type') == 'verification']),
            'other': len([n for n in nodes if n.get('type') not in ['start', 'success', 'failure', 'navigation', 'action', 'verification']]),
            'total': len(nodes),
        }
        
        blocks_generated = [
            {
                'type': node.get('type'),
                'label': node.get('data', {}).get('label') or node.get('type'),
                'id': node.get('id'),
            }
            for node in nodes
        ]
        
        return {
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'total_tokens': usage.get('total_tokens', 0),
            'block_counts': block_counts,
            'blocks_generated': blocks_generated,
        }
    
    # ========================================
    # CACHE MANAGEMENT
    # ========================================
    
    def clear_context_cache(self):
        """Clear context cache (manual)"""
        self._context_cache.clear()
        print(f"[@ai_builder] Context cache cleared manually")
    
    def invalidate_context_cache(self, reason: str = "Navigation tree updated"):
        """
        Invalidate context cache when navigation graph changes
        
        This should be called when:
        - Navigation nodes are added/removed
        - Node properties are updated
        - User interface structure changes
        
        Args:
            reason: Why cache is being invalidated (for logging)
        """
        self._context_cache.clear()
        print(f"[@ai_builder] 🔄 Context cache invalidated: {reason}")
        print(f"[@ai_builder]    Reason: Ensure fresh data for AI generation")
    
    # ========================================
    # SIMPLE GRAPH GENERATION (No AI)
    # ========================================
    
    def _create_simple_navigation_graph(self, target_node: str) -> Dict:
        """
        Create a simple START → navigation → SUCCESS graph without AI
        
        Used for exact match preprocessing
        
        Args:
            target_node: Node to navigate to
            
        Returns:
            Graph dict with nodes and edges
        """
        return {
            'nodes': [
                {
                    'id': 'start',
                    'type': 'start',
                    'position': {'x': 100, 'y': 100},
                    'data': {'label': 'START'}
                },
                {
                    'id': 'nav1',
                    'type': 'navigation',
                    'position': {'x': 100, 'y': 200},
                    'data': {
                        'label': f'navigation_1:{target_node}',
                        'target_node_label': target_node,  # ✅ FIX: Frontend expects target_node_label
                        'target_node_id': target_node,
                        'action_type': 'navigation',
                        'transitions': []  # Empty - navigation is autonomous at runtime
                    }
                },
                {
                    'id': 'success',
                    'type': 'success',
                    'position': {'x': 100, 'y': 300},
                    'data': {'label': 'SUCCESS'}
                }
            ],
            'edges': [
                {
                    'id': 'e_start_nav1',
                    'source': 'start',
                    'target': 'nav1',
                    'sourceHandle': 'success',
                    'type': 'success'
                },
                {
                    'id': 'e_nav1_success',
                    'source': 'nav1',
                    'target': 'success',
                    'sourceHandle': 'success',
                    'type': 'success'
                }
            ]
        }

