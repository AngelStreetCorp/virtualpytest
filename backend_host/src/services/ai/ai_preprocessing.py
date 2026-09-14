"""
AI Prompt Preprocessing

SMART preprocessing before AI generation:
1. Intent extraction (keywords, patterns, structure)
2. Context filtering (semantic search to reduce noise)
3. Learned mappings (from database)
4. Disambiguation (auto-correct or ask user)
5. Exact match detection (skip AI if simple)

Goal: Preprocessing is smart enough that AI just assembles the graph

Adapted from old shared/src/lib/executors/ai_prompt_validation.py
Now lives in backend_host/src/services/ai/ (host-specific, not shared)
"""

import re
from difflib import get_close_matches
from typing import Dict, List, Optional

from shared.src.lib.database.ai_prompt_disambiguation_db import (
    get_learned_mapping,
    get_learned_mappings_batch,
    save_disambiguation
)

from backend_host.src.services.ai.ai_intent_parser import IntentParser, build_structure_hints_for_ai
from backend_host.src.services.ai.ai_context_filter import ContextFilter, format_filtered_context_for_ai


# =============================================================================
# STOPWORDS & FILTERS
# =============================================================================

# Common English words that should NOT be treated as navigation nodes
# These are filtered out to prevent false positive ambiguities
STOPWORDS = {
    # Articles & prepositions
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'or', 'that',
    'the', 'was', 'will', 'with', 'she', 'they', 'we', 'you',
    
    # Navigation/action verbs (not node names)
    'go',  'goto', 'to', 'navigate', 'open', 'close', 'press', 'click', 'tap',
    'select', 'exit', 'move', 'change', 'switch', 'set', 'get',
    
    # Temporal/sequential words
    'then', 'now', 'next', 'after', 'before', 'first', 'last', 'again',
    'back', 'forward', 'up', 'down',
    
    # Common actions
    'do', 'make', 'take', 'show', 'see', 'look', 'find', 'use',
}


def is_valid_potential_node(phrase: str) -> bool:
    """
    Check if a phrase could potentially be a navigation node reference.
    
    Rules:
    1. Must be at least 3 characters total (filters: "go", "to", "in", "up")
    2. Must not be a stopword
    3. Individual words in phrase must be >= 3 chars (unless contains digits/special chars)
    
    Args:
        phrase: Potential node name or phrase
    
    Returns:
        True if phrase could be a valid node reference
    
    Examples:
        >>> is_valid_potential_node("live_fullscreen")
        True
        >>> is_valid_potential_node("home")
        True
        >>> is_valid_potential_node("to")
        False
        >>> is_valid_potential_node("go")
        False
        >>> is_valid_potential_node("to_live")  # "to" is < 3 chars
        False
        >>> is_valid_potential_node("ch+")  # Has special char, might be valid
        True
    """
    phrase = phrase.strip().lower()
    
    # Must be at least 3 characters total
    if len(phrase) < 3:
        return False
    
    # Check if entire phrase is a stopword
    if phrase in STOPWORDS:
        return False
    
    # For multi-word or underscore-separated phrases, check each part
    # Split on spaces and underscores
    parts = re.split(r'[\s_]+', phrase)
    
    for part in parts:
        # Allow parts with digits or special characters (e.g., "ch+", "5", "360")
        if any(c.isdigit() or not c.isalnum() for c in part):
            continue
        
        # Alphabetic parts must be >= 3 chars AND not be stopwords
        # Reject if part is too short OR is a stopword
        if len(part) < 3:
            return False
        if part in STOPWORDS:
            return False
    
    return True


def find_fuzzy_matches(target: str, available_nodes: List[str], 
                      max_results: int = 3, cutoff: float = 0.4) -> List[str]:
    """
    Find fuzzy string matches using difflib.
    
    Args:
        target: The string to match
        available_nodes: List of valid node names
        max_results: Maximum number of matches to return
        cutoff: Similarity threshold (0.0-1.0)
    
    Returns:
        List of matching nodes, best matches first
    """
    # Try exact match first (case-insensitive)
    for node in available_nodes:
        if node.lower() == target.lower():
            return [node]
    
    # Fuzzy match
    target_lower = target.lower()
    nodes_lower = [n.lower() for n in available_nodes]
    
    matches = get_close_matches(target_lower, nodes_lower, n=max_results, cutoff=cutoff)
    
    # Return original-cased nodes
    return [n for n in available_nodes if n.lower() in matches]


def extract_potential_node_phrases(prompt: str) -> List[str]:
    """
    Extract phrases from prompt that could be node references.
    
    IMPROVED with stopword and length filtering to reduce false positives.
    
    Patterns:
    - Quoted strings: "live fullscreen"
    - After navigation keywords: "navigate to live" → extracts "live"
    - Individual words (filtered by stopwords and length)
    - Multi-word combinations (2-word phrases)
    
    Args:
        prompt: User's natural language prompt
    
    Returns:
        List of potential node phrases (filtered)
    
    Examples:
        >>> extract_potential_node_phrases("go to live fullscreen")
        ['live fullscreen', 'live', 'fullscreen']
        # Filtered: "go", "to" (stopwords < 3 chars)
    """
    phrases = []
    prompt_lower = prompt.lower()
    
    # Pattern 1: Quoted strings (high priority - user explicitly marked)
    quoted = re.findall(r'["\']([^"\']+)["\']', prompt)
    for q in quoted:
        if is_valid_potential_node(q):
            phrases.append(q.lower())
    
    # Pattern 2: After navigation keywords
    # Extract content after "go to", "navigate to", "open", etc.
    navigation_pattern = r'(?:go\s+to|navigate\s+to|open|goto)\s+([a-zA-Z0-9_\s]+?)(?:\s+and|\s+then|$|,|\.|;)'
    nav_matches = re.findall(navigation_pattern, prompt_lower)
    for match in nav_matches:
        clean_match = match.strip()
        if is_valid_potential_node(clean_match):
            phrases.append(clean_match)
    
    # Pattern 3: Individual words (filtered by stopwords and length)
    words = re.findall(r'\b[a-zA-Z0-9_]+\b', prompt_lower)
    for word in words:
        if is_valid_potential_node(word):
            phrases.append(word)
    
    # Pattern 4: Multi-word combinations (2-word phrases)
    words_list = prompt_lower.split()
    for i in range(len(words_list) - 1):
        two_word = f"{words_list[i]} {words_list[i+1]}"
        if is_valid_potential_node(two_word):
            phrases.append(two_word)
        
        # Also try with underscore
        two_word_underscore = f"{words_list[i]}_{words_list[i+1]}"
        if is_valid_potential_node(two_word_underscore):
            phrases.append(two_word_underscore)
    
    # Deduplicate while preserving order
    seen = set()
    unique_phrases = []
    for phrase in phrases:
        phrase = phrase.strip()
        if phrase and phrase not in seen:
            seen.add(phrase)
            unique_phrases.append(phrase)
    
    print(f"[@ai_preprocessing] Extracted and filtered {len(unique_phrases)} valid phrases from prompt")
    if unique_phrases:
        print(f"[@ai_preprocessing]   Valid phrases: {unique_phrases[:10]}")  # Show first 10
    
    return unique_phrases


def preprocess_prompt(prompt: str, available_nodes: List[str], 
                     team_id: str, userinterface_name: str) -> Dict:
    """
    Pre-process prompt: apply learned mappings and check for ambiguities.
    
    This runs BEFORE AI generation to:
    1. Apply learned mappings automatically
    2. Detect ambiguous phrases that need user input
    3. Auto-correct high-confidence single matches
    
    Args:
        prompt: User's natural language prompt
        available_nodes: List of valid navigation nodes
        team_id: Team ID for database lookup
        userinterface_name: UI context (e.g., "example_mobile")
    
    Returns:
        {
            'status': 'clear' | 'auto_corrected' | 'needs_disambiguation',
            'corrected_prompt': str (if auto_corrected),
            'corrections': [...] (if auto_corrected),
            'ambiguities': [...] (if needs_disambiguation)
        }
    """
    # Extract potential node phrases from prompt
    phrases = extract_potential_node_phrases(prompt)
    print(f"[@ai_preprocessing] Extracted {len(phrases)} potential phrases from prompt")
    print(f"[@ai_preprocessing] Phrases: {phrases[:10]}")  # Show first 10
    
    # Get learned mappings from database (batch query for efficiency)
    learned = get_learned_mappings_batch(team_id, userinterface_name, phrases)
    
    # Track what we corrected vs what needs user input
    auto_corrections = []
    needs_disambiguation = []
    
    for phrase in phrases:
        # Skip if exact match exists
        if phrase in available_nodes:
            continue
        
        # Check learned mapping (HIGHEST PRIORITY)
        if phrase in learned:
            learned_node = learned[phrase]
            # Validate learned mapping is still valid (node might have been deleted)
            if learned_node in available_nodes:
                auto_corrections.append({
                    'from': phrase,
                    'to': learned_node,
                    'source': 'learned'
                })
                print(f"[@ai_preprocessing] ✅ Learned mapping: '{phrase}' → '{learned_node}'")
                continue
        
        # Find fuzzy matches
        matches = find_fuzzy_matches(phrase, available_nodes, max_results=3, cutoff=0.4)
        
        if len(matches) == 1:
            # Single high-confidence match → auto-correct
            auto_corrections.append({
                'from': phrase,
                'to': matches[0],
                'source': 'fuzzy'
            })
            print(f"[@ai_preprocessing] ✅ Fuzzy auto-correct: '{phrase}' → '{matches[0]}'")
        elif len(matches) > 1:
            # Multiple matches → needs user disambiguation
            needs_disambiguation.append({
                'phrase': phrase,  # Frontend expects 'phrase', not 'original'
                'suggestions': matches
            })
            print(f"[@ai_preprocessing] ⚠️  Ambiguous: '{phrase}' → {matches}")
    
    # Determine status and return appropriate response
    if not auto_corrections and not needs_disambiguation:
        print(f"[@ai_preprocessing] ✅ Prompt is clear - no changes needed")
        return {'status': 'clear', 'prompt': prompt}
    
    if needs_disambiguation:
        print(f"[@ai_preprocessing] ⚠️  DISAMBIGUATION REQUIRED")
        print(f"[@ai_preprocessing]   Ambiguous phrases: {len(needs_disambiguation)}")
        print(f"[@ai_preprocessing]   Auto-corrections: {len(auto_corrections)}")
        
        # Log structure being returned
        response = {
            'status': 'needs_disambiguation',
            'original_prompt': prompt,
            'ambiguities': needs_disambiguation,
            'auto_corrections': auto_corrections  # Show what was auto-corrected
        }
        
        print(f"[@ai_preprocessing] 📤 Returning disambiguation data structure:")
        print(f"[@ai_preprocessing]   Keys: {list(response.keys())}")
        
        return response
    
    # Auto-corrected only (apply corrections to prompt)
    print(f"[@ai_preprocessing] ✅ Auto-correcting {len(auto_corrections)} phrases")
    corrected_prompt = prompt
    for correction in auto_corrections:
        # Use word boundaries to avoid partial replacements
        corrected_prompt = re.sub(
            r'\b' + re.escape(correction['from']) + r'\b',
            correction['to'],
            corrected_prompt,
            flags=re.IGNORECASE
        )
    
    return {
        'status': 'auto_corrected',
        'original_prompt': prompt,
        'corrected_prompt': corrected_prompt,
        'corrections': auto_corrections
    }


def check_exact_match(prompt: str, available_nodes: List[str]) -> Optional[str]:
    """
    Check if prompt is a simple exact node match (skip AI entirely).
    
    Examples that should match:
    - "home" → node "home"
    - "navigate to live" → node "live"
    - "go to settings" → node "settings"
    
    Args:
        prompt: User prompt
        available_nodes: List of available nodes
        
    Returns:
        Node name if exact match found, None otherwise
    """
    prompt_lower = prompt.lower().strip()
    
    # Direct match
    if prompt_lower in [n.lower() for n in available_nodes]:
        for node in available_nodes:
            if node.lower() == prompt_lower:
                print(f"[@ai_preprocessing] 🎯 Exact match (direct): '{prompt}' → '{node}'")
                return node
    
    # Extract after navigation keywords
    patterns = [
        r'(?:navigate to|go to|open)\s+([a-zA-Z0-9_\s]+)$',
        r'to\s+([a-zA-Z0-9_\s]+)$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, prompt_lower)
        if match:
            extracted = match.group(1).strip()
            if extracted in [n.lower() for n in available_nodes]:
                for node in available_nodes:
                    if node.lower() == extracted:
                        print(f"[@ai_preprocessing] 🎯 Exact match (extracted): '{prompt}' → '{node}'")
                        return node
    
    return None


def smart_preprocess(
    prompt: str,
    all_nodes: List[str],
    all_actions: List[str],
    all_verifications: List[str],
    team_id: str,
    userinterface_name: str
) -> Dict:
    """
    SMART preprocessing with intent extraction and context filtering
    
    This is the main entry point for preprocessing. It:
    1. Extracts user intent (keywords, patterns, structure)
    2. Filters context by relevance (15 nodes instead of 100)
    3. Checks for exact matches (skip AI if simple)
    4. Applies learned mappings and disambiguation
    5. Returns filtered context ready for AI
    
    Args:
        prompt: User's natural language prompt
        all_nodes: ALL available navigation nodes (will be filtered)
        all_actions: ALL available actions (will be filtered)
        all_verifications: ALL available verifications (will be filtered)
        team_id: Team ID for database lookup
        userinterface_name: UI context
    
    Returns:
        Either:
        - {status: 'ready', filtered_context: {...}} → Send to AI
        - {status: 'needs_disambiguation', ...} → Show modal
        - {status: 'exact_match', node: ...} → Skip AI entirely
        - {status: 'impossible', reason: ...} → Fail early
    """
    print(f"[@smart_preprocess] Starting smart preprocessing")
    print(f"[@smart_preprocess]   Input context: {len(all_nodes)} nodes, {len(all_actions)} actions, {len(all_verifications)} verifications")
    
    # Step 1: Parse intent (keywords, patterns, structure)
    intent_parser = IntentParser()
    intent = intent_parser.parse_prompt(prompt)
    
    keywords = intent['keywords']
    patterns = intent['patterns']
    all_keywords = intent['all_keywords']
    
    # Step 2: Check for exact match (skip AI entirely)
    if not patterns['has_loop'] and not patterns['has_sequence']:
        # Simple prompt → might be exact match
        exact_node = check_exact_match(prompt, all_nodes)
        if exact_node:
            print(f"[@smart_preprocess] ✅ Exact match found - skipping AI")
            return {
                'status': 'exact_match',
                'node': exact_node,
                'intent': intent
            }
    
    # Step 3: Filter context by relevance (semantic search)
    context_filter = ContextFilter()
    filtered_context = context_filter.filter_context(
        prompt=prompt,
        keywords=keywords,
        all_nodes=all_nodes,
        all_actions=all_actions,
        all_verifications=all_verifications
    )
    
    # RESPECT INTENT: Remove actions/verifications independently based on keywords
    # Actions and verifications are INDEPENDENT - check separately
    
    if not keywords.get('actions'):
        # User didn't mention actions → remove them
        actions_removed = len(filtered_context['actions'])
        if actions_removed > 0:
            print(f"[@smart_preprocess] No action keywords detected → removing {actions_removed} actions")
        filtered_context['actions'] = []
    
    if not keywords.get('verifications'):
        # User didn't mention verifications → remove them
        verifications_removed = len(filtered_context['verifications'])
        if verifications_removed > 0:
            print(f"[@smart_preprocess] No verification keywords detected → removing {verifications_removed} verifications")
        filtered_context['verifications'] = []
    
    # Extract just the item names (not scores) for disambiguation
    filtered_node_names = [item['item'] for item in filtered_context['nodes']]
    filtered_action_names = [item['item'] for item in filtered_context['actions']]
    filtered_verification_names = [item['item'] for item in filtered_context['verifications']]
    
    # VALIDATE intent keywords against filtered context
    # Remove keywords that don't exist in filtered context (e.g., "saved" if not in nodes)
    validated_intent = intent.copy()
    original_nav_count = len(validated_intent['keywords']['navigation'])
    validated_intent['keywords']['navigation'] = [
        n for n in intent['keywords']['navigation'] 
        if n in filtered_node_names
    ]
    removed_nav = original_nav_count - len(validated_intent['keywords']['navigation'])
    if removed_nav > 0:
        print(f"[@smart_preprocess] ✅ Filtered out {removed_nav} invalid navigation keywords from intent")
    
    original_action_count = len(validated_intent['keywords']['actions'])
    validated_intent['keywords']['actions'] = [
        a for a in intent['keywords']['actions']
        if a in filtered_action_names
    ]
    removed_actions = original_action_count - len(validated_intent['keywords']['actions'])
    if removed_actions > 0:
        print(f"[@smart_preprocess] ✅ Filtered out {removed_actions} invalid action keywords from intent")
    
    original_verify_count = len(validated_intent['keywords']['verifications'])
    validated_intent['keywords']['verifications'] = [
        v for v in intent['keywords']['verifications']
        if v in filtered_verification_names
    ]
    removed_verify = original_verify_count - len(validated_intent['keywords']['verifications'])
    if removed_verify > 0:
        print(f"[@smart_preprocess] ✅ Filtered out {removed_verify} invalid verification keywords from intent")
    
    # Use validated intent going forward
    intent = validated_intent
    keywords = intent['keywords']
    
    # Step 4: Validate - do we have relevant context?
    if not filtered_node_names and keywords['navigation']:
        return {
            'status': 'impossible',
            'reason': f'No navigation nodes found for: {", ".join(keywords["navigation"])}',
            'intent': intent
        }
    
    if not filtered_action_names and keywords['actions']:
        return {
            'status': 'impossible',
            'reason': f'No actions found for: {", ".join(keywords["actions"])}',
            'intent': intent
        }
    
    if not filtered_verification_names and keywords['verifications']:
        return {
            'status': 'impossible',
            'reason': f'No verifications found for: {", ".join(keywords["verifications"])}',
            'intent': intent
        }
    
    # Step 5: Apply learned mappings and check for ambiguities
    # Run disambiguation on FILTERED context (not full catalog!)
    preprocessed = preprocess_prompt(
        prompt,
        available_nodes=filtered_node_names,  # FILTERED!
        team_id=team_id,
        userinterface_name=userinterface_name
    )
    
    if preprocessed['status'] == 'needs_disambiguation':
        print(f"[@smart_preprocess] ⚠️  Needs disambiguation")
        
        try:
            ambiguities = preprocessed.get('ambiguities', [])
            auto_corrections = preprocessed.get('auto_corrections', [])
            
            print(f"[@smart_preprocess]   Ambiguities: {len(ambiguities)}")
            print(f"[@smart_preprocess]   Auto-corrections: {len(auto_corrections)}")
            
            # Log ambiguous phrases
            for amb in ambiguities:
                phrase = amb.get('phrase', 'UNKNOWN')
                suggestions = amb.get('suggestions', [])
                print(f"[@smart_preprocess]     '{phrase}' → {suggestions}")
            
            return {
                'status': 'needs_disambiguation',
                'ambiguities': ambiguities,
                'auto_corrections': auto_corrections,
                'intent': intent
            }
            
        except Exception as e:
            print(f"[@smart_preprocess] ❌ ERROR processing disambiguation: {e}")
            import traceback
            traceback.print_exc()
            return {
                'status': 'impossible',
                'reason': f'Disambiguation processing error: {str(e)}',
                'intent': intent
            }
    
    # Step 6: Build structure hints for AI
    structure_hints = build_structure_hints_for_ai(intent)
    
    # Step 7: Format filtered context for AI prompt
    formatted_context = format_filtered_context_for_ai(filtered_context)
    
    # Use corrected prompt if available
    final_prompt = preprocessed.get('corrected_prompt', prompt)
    
    print(f"[@smart_preprocess] ✅ Preprocessing complete - ready for AI")
    if preprocessed['status'] == 'auto_corrected':
        print(f"[@smart_preprocess]   Applied {len(preprocessed['corrections'])} auto-corrections")
    
    return {
        'status': 'ready',
        'original_prompt': prompt,
        'corrected_prompt': final_prompt,
        'filtered_context': {
            'nodes': filtered_context['nodes'],
            'actions': filtered_context['actions'],
            'verifications': filtered_context['verifications']
        },
        'formatted_context': formatted_context,  # String for AI prompt
        'structure_hints': structure_hints,      # String for AI prompt
        'intent': intent,
        'stats': filtered_context['stats']
    }

