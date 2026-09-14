"""
Unified Selector Scoring - SINGLE SOURCE OF TRUTH

Extracted from dump_analyzer.py with platform-specific enhancements.
Used by: dump_analyzer.py, screen_analyzer.py, MCP tools

Priority Order:
- Mobile: ID > CONTENT_DESC > XPATH > TEXT
- Web: ID > XPATH > TEXT
- STB/TV: Use screenshot_analyzer.py instead (visual scoring)
"""

from typing import Tuple, Set, Optional, Dict, List
import re


# ============================================================================
# PLATFORM-SPECIFIC PRIORITIES
# ============================================================================

class SelectorPriority:
    """Selector type priority scores (higher = better)"""
    ID = 1000              # resource_id (mobile), #id (web) - Always unique by design
    CONTENT_DESC = 600     # Mobile only - Accessibility label (above XPath!)
    XPATH = 500            # Structural path - Usually unique
    TEXT = 200             # Weakest - Can be duplicate/dynamic


PLATFORM_PRIORITY_ORDER = {
    'mobile': ['id', 'content_desc', 'xpath', 'text'],
    'web': ['id', 'xpath', 'text'],
    # STB/TV not included - use screenshot_analyzer.py
}


# ============================================================================
# WEAK WORDS - Extracted from dump_analyzer.py (lines 45-70)
# Can only be used as secondary verification, not primary
# ============================================================================

WEAK_VERIFICATION_WORDS = {
    # Navigation/Actions (too common alone, but OK as secondary)
    'back', 'next', 'previous', 'prev', 'forward', 'close', 'exit',
    'cancel', 'ok', 'confirm', 'yes', 'no', 'done', 'finish',
    
    # Search/Filter (appear everywhere)
    'search', 'filter', 'sort', 'order', 'show all', 'view all',
    
    # Media controls
    'play', 'pause', 'stop', 'watch', 'listen',
    
    # Generic content words
    'more', 'less', 'info', 'details', 'description',
    'title', 'name', 'delete', 'remove', 'add', 'edit',
    
    # Time/Date (dynamic but can be used as secondary)
    'today', 'yesterday', 'tomorrow', 'now',
    
    # Generic UI elements
    'menu', 'options', 'settings',  # Settings as standalone word
    'button', 'tab', 'icon', 'image',
    
    # Content-specific weak words
    'popular', 'trending', 'new', 'featured', 'recommended',
    'movies', 'shows', 'series', 'videos', 'channels'
}


# ============================================================================
# CORE FUNCTIONS - Extracted from dump_analyzer.py
# ============================================================================

def is_weak_word(text: str) -> bool:
    """
    EXACT COPY from dump_analyzer.py lines 73-91
    Check if text is a weak verification candidate.
    Weak = Can be used as secondary/complementary verification only.
    Returns True if the text should not be used as primary verification.
    """
    text_lower = text.lower().strip()
    
    # Check if text is ONLY a weak word (single word)
    words = text_lower.split()
    if len(words) == 1 and words[0] in WEAK_VERIFICATION_WORDS:
        return True
    
    # Also check if it's a simple 2-word phrase with weak words
    # e.g., "Popular Movies" = weak + weak
    if len(words) == 2 and all(w in WEAK_VERIFICATION_WORDS for w in words):
        return True
    
    return False


def score_text_candidate(text: str, node_label: str) -> Tuple[int, bool]:
    """
    EXACT COPY from dump_analyzer.py lines 252-309
    Score a text candidate for how good it is as a verification point.
    
    Args:
        text: Text to score
        node_label: Node label for relevance matching
    
    Returns:
        (score, is_weak): 
            - score: Higher = better candidate
            - is_weak: True if this should only be used as secondary verification
    """
    score = 0
    text_lower = text.lower()
    label_lower = node_label.lower()
    
    # 0. CHECK IF WEAK (can only be secondary verification)
    is_weak = is_weak_word(text)
    
    # ✅ Normalize both for comparison (remove _, spaces)
    text_normalized = text_lower.replace('_', '').replace(' ', '')
    label_normalized = label_lower.replace('_', '').replace(' ', '')
    
    # 1. EXACT MATCH to Node Label (Highest Priority)
    # "Settings" == "Settings" → 1000
    # "TV Guide" == "tv_guide" → 1000 (after normalization)
    # "Guide TV" == "tv_guide" → NO (word order matters for exact)
    if text_lower == label_lower or text_normalized == label_normalized:
        return (1000, False)  # Always strong if exact match
    
    # 2. Partial Match to Node Label (case-insensitive, normalized)
    # "TV Guide" vs "tv_guide" → "tvguide" in "tvguide" → 500 ✅
    # "Guide TV" vs "tv_guide" → "guidetv" has all words ["tv","guide"] → 500 ✅
    # "Guide" vs "tv_guide" → "guide" in "tvguide" → 500 ✅
    if label_normalized in text_normalized or text_normalized in label_normalized:
        score += 500
    # Also check if all words from label are in text (handles "Guide TV" vs "tv_guide")
    # Split label by underscore/space to get words: "tv_guide" → ["tv", "guide"]
    else:
        label_words = [w for w in label_lower.replace('_', ' ').split() if w]
        if label_words and all(word in text_normalized for word in label_words):
            score += 500  # All label words present in text (any order)
    
    # 3. Length Heuristics
    length = len(text)
    words = text.split()
    
    # Boost single words (Concise labels are usually better navigation targets)
    if len(words) == 1:
        score += 30
        
    if length < 3:
        score -= 50  # Too short (e.g., "ok", "en")
    elif 4 <= length <= 25:
        score += 20  # Sweet spot for titles/labels
    elif length > 40:
        score -= 20  # Likely a description/paragraph
        
    # 4. Content Analysis
    
    # Boost "Selected/Active" state (Strongest indicator of current screen)
    if 'selected' in text_lower or 'focused' in text_lower or 'current' in text_lower:
        score += 500

    # Penalize potential dynamic content (digits, time, prices)
    if re.search(r'\d', text): 
        score -= 30  # Contains numbers (risk of dynamic ID/Time)
    if re.search(r'\d{1,2}:\d{2}', text):
        score -= 100 # Looks like time
    if re.search(r'[\$\€\£]', text):
        score -= 100 # Looks like price
        
    # Penalize common low-value words
    bad_words = {'ok', 'cancel', 'back', 'next', 'done', 'yes', 'no', 'on', 'off'}
    if text_lower in bad_words:
        score -= 50
        
    # Boost Title Case (likely a proper UI label)
    if text[0].isupper() and ' ' in text:
        score += 10
        
    return (score, is_weak)


# ============================================================================
# PLATFORM-SPECIFIC SELECTOR EXTRACTION
# ============================================================================

def get_selector_value(element: Dict, selector_type: str, platform: str) -> Optional[str]:
    """
    Extract selector value from element based on type and platform.
    
    Args:
        element: Element dict with platform-specific fields
        selector_type: 'id', 'content_desc', 'xpath', 'text'
        platform: 'mobile' or 'web'
    
    Returns:
        Selector value string or None
    """
    if selector_type == 'id':
        if platform == 'mobile':
            value = element.get('resource_id', '')
        else:  # web
            value = element.get('id', '')
        
        # Filter invalid values
        if value and value.strip() and value not in ['<no resource-id>', 'null', '']:
            return value.strip()
    
    elif selector_type == 'content_desc' and platform == 'mobile':
        value = element.get('content_desc', '')
        if value and value.strip() and value not in ['<no content-desc>', '']:
            return value.strip()
    
    elif selector_type == 'xpath':
        value = element.get('xpath', '')
        if value and value.strip():
            return value.strip()
    
    elif selector_type == 'text':
        if platform == 'mobile':
            value = element.get('text', '')
        else:  # web
            value = element.get('textContent', '')
        
        if value and value.strip() and value not in ['<no text>', '']:
            return value.strip()
    
    return None


def score_selector(
    element: Dict,
    selector_type: str,
    platform: str,
    context_label: str = '',
    all_elements: List[Dict] = None
) -> Tuple[int, Dict]:
    """
    Score a specific selector for an element.
    
    Args:
        element: Element dict
        selector_type: Type to score ('id', 'content_desc', 'xpath', 'text')
        platform: 'mobile' or 'web'
        context_label: Node label for relevance boost
        all_elements: All elements for uniqueness check (required)
    
    Returns:
        (score, details)
    """
    value = get_selector_value(element, selector_type, platform)
    
    if not value:
        return (0, {'error': f'No {selector_type} found'})
    
    # Base score from priority
    if selector_type == 'id':
        score = SelectorPriority.ID
    elif selector_type == 'content_desc':
        score = SelectorPriority.CONTENT_DESC
    elif selector_type == 'xpath':
        score = SelectorPriority.XPATH
    else:  # text
        score = SelectorPriority.TEXT
    
    details = {
        'selector_type': selector_type,
        'value': value,
        'base_score': score,
        'modifiers': []
    }
    
    # Apply text quality scoring if text-based
    if selector_type in ['text', 'content_desc']:
        text_score, is_weak = score_text_candidate(value, context_label)
        score += text_score - 200  # Subtract base TEXT score to avoid double counting
        details['text_quality_score'] = text_score
        details['is_weak'] = is_weak
        
        if is_weak:
            details['modifiers'].append('weak_word')
    
    # Context matching bonus (for all types)
    if context_label:
        if value.lower() == context_label.lower():
            score += 500
            details['modifiers'].append('exact_context_match')
        elif context_label.lower() in value.lower():
            score += 200
            details['modifiers'].append('partial_context_match')
    
    # CRITICAL: Check uniqueness (mandatory)
    if all_elements:
        matching_count = sum(
            1 for e in all_elements
            if get_selector_value(e, selector_type, platform) == value
        )
        
        details['matching_count'] = matching_count
        
        if matching_count > 1:
            # NOT UNIQUE - Heavy penalty
            penalty = -500 if selector_type in ['id', 'xpath'] else -200
            score += penalty
            details['unique'] = False
            details['modifiers'].append(f'not_unique({matching_count})')
        else:
            # UNIQUE - Bonus
            score += 100
            details['unique'] = True
            details['modifiers'].append('unique')
    else:
        # No uniqueness check - penalize
        score -= 300
        details['unique'] = None
        details['modifiers'].append('uniqueness_not_checked')
    
    details['final_score'] = score
    
    return (score, details)


def find_best_selector(
    elements: List[Dict],
    platform: str,
    context_label: str = '',
    require_unique: bool = True
) -> Optional[Dict]:
    """
    Find the best selector from a list of elements using platform-specific priorities.
    
    Args:
        elements: List of element dicts
        platform: 'mobile' or 'web'
        context_label: Node label for relevance matching
        require_unique: If True, requires uniqueness check (default: True)
    
    Returns:
        {
            'selector_type': 'id',
            'selector_value': '#search-field',
            'score': 1200,
            'element': <original element>,
            'details': {...}
        }
        or None if no good selector found
    """
    if not elements:
        return None
    
    if platform not in PLATFORM_PRIORITY_ORDER:
        raise ValueError(f"Unsupported platform: {platform}. Use 'mobile' or 'web'.")
    
    priority_order = PLATFORM_PRIORITY_ORDER[platform]
    best_result = None
    best_score = -9999
    
    # Try each element
    for element in elements:
        # Try each selector type in priority order
        for selector_type in priority_order:
            score, details = score_selector(
                element=element,
                selector_type=selector_type,
                platform=platform,
                context_label=context_label,
                all_elements=elements if require_unique else None
            )
            
            if score > best_score:
                best_score = score
                best_result = {
                    'selector_type': selector_type,
                    'selector_value': details.get('value'),
                    'score': score,
                    'element': element,
                    'details': details
                }
    
    # Return best if it's above minimum threshold
    if best_result and best_result['score'] > 0:
        return best_result
    
    return None


# ============================================================================
# DUMP ANALYZER COMPATIBILITY FUNCTIONS
# Keep dump_analyzer.py working exactly as before
# ============================================================================

def extract_texts_from_dump(dump: Dict) -> Set[str]:
    """Extract all text values from dump (mobile or web) - from dump_analyzer.py"""
    texts = set()
    
    if not dump or not isinstance(dump, dict):
        return texts
    
    elements = dump.get('elements', [])
    
    for elem in elements:
        # Mobile dump (AndroidElement)
        if hasattr(elem, 'text') or hasattr(elem, 'content_desc'):
            text = getattr(elem, 'text', '')
            content_desc = getattr(elem, 'content_desc', '')
            
            # Clean up placeholder values
            if str(text) == '<no text>': text = ''
            if str(content_desc) == '<no content-desc>': content_desc = ''
            
            val = str(text).strip() or str(content_desc).strip()
            
            if val:
                texts.add(val)
        
        # Web dump (dict)
        elif isinstance(elem, dict):
            text = elem.get('text', '') or elem.get('content_desc', '')
            if text and str(text).strip():
                texts.add(str(text).strip())
    
    return texts


def extract_xpaths_from_dump(dump: Dict) -> Set[str]:
    """Extract all xpath values from dump (mobile or web) - from dump_analyzer.py"""
    xpaths = set()
    
    if not dump or not isinstance(dump, dict):
        return xpaths
    
    elements = dump.get('elements', [])
    
    for elem in elements:
        # Mobile dump (AndroidElement)
        if hasattr(elem, 'xpath'):
            xpath = elem.xpath
            if xpath and xpath.strip():
                xpaths.add(xpath.strip())
        
        # Web dump (dict)
        elif isinstance(elem, dict):
            xpath = elem.get('xpath', '') or elem.get('selector', '')
            if xpath and xpath.strip():
                xpaths.add(xpath.strip())
    
    return xpaths

