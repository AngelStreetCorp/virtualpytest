"""
Dump Analyzer - Find unique elements across multiple UI dumps
Now uses shared/src/lib/utils/selector_scoring.py for unified priority and scoring logic
"""

from typing import List, Dict, Optional, Set, Tuple
import json
import re

# Import unified scoring from shared module
from shared.src.lib.utils.selector_scoring import (
    WEAK_VERIFICATION_WORDS,
    is_weak_word as _is_weak_word,
    score_text_candidate as _score_text_candidate,
    extract_texts_from_dump as _extract_texts_from_dump,
    extract_xpaths_from_dump as _extract_xpaths_from_dump,
    PLATFORM_PRIORITY_ORDER
)


def _get_verification_command_and_type(device_model: str) -> Tuple[str, str, str]:
    """
    Get the correct verification command, type, and param name based on device model.
    Uses verification_executor.py logic - NO reinventing the wheel!
    
    Returns:
        Tuple of (command, verification_type, param_name):
        - ADB/Appium: ('waitForElementToAppear', 'adb', 'search_term')
        - Web: ('waitForElementToAppear', 'web', 'text')
        - Text/OCR fallback: ('waitForTextToAppear', 'text', 'text')
    """
    if not device_model:
        return 'waitForTextToAppear', 'text', 'text'
    
    model_lower = device_model.lower()
    
    # ADB: android_mobile, android_tv
    if 'android' in model_lower or 'mobile' in model_lower:
        return 'waitForElementToAppear', 'adb', 'search_term'
    
    # Appium: (if we support it in the future)
    if 'appium' in model_lower:
        return 'waitForElementToAppear', 'appium', 'search_term'
    
    # Web: example_web, playwright, etc.
    if 'web' in model_lower or 'playwright' in model_lower:
        return 'waitForElementToAppear', 'web', 'text'
    
    # Default: Text/OCR verification (fallback)
    return 'waitForTextToAppear', 'text', 'text'


def _dump_to_string(dump: Dict) -> str:
    """
    Convert dump data to readable string format for frontend display
    
    Args:
        dump: Dump dictionary with 'elements' array
        
    Returns:
        Formatted string representation
    """
    if not dump or not isinstance(dump, dict):
        return "<empty dump>"
    
    elements = dump.get('elements', [])
    
    if not elements:
        return "<no elements found>"
    
    # ✅ Detect dump type
    dump_type = dump.get('dump_type', 'xml')  # Default to xml for backward compatibility
    
    # Build formatted string
    lines = []
    lines.append(f"Total Elements: {len(elements)}")
    
    for i, elem in enumerate(elements, 1):
        lines.append(f"[{i}]")
        
        # Handle both object attributes and dict keys
        if hasattr(elem, '__dict__'):
            # Object (AndroidElement, AppiumElement)
            elem_dict = elem.__dict__
        elif isinstance(elem, dict):
            # Dict (Web elements, OCR elements)
            elem_dict = elem
        else:
            lines.append(f"  <unknown format: {type(elem)}>")
            continue
        
        # ✅ OCR: Show text and area
        if dump_type == 'ocr':
            text = elem_dict.get('text', '')
            area = elem_dict.get('area', {})
            confidence = elem_dict.get('confidence', 0)
            
            lines.append(f"  text: {text}")
            if area:
                lines.append(f"  area: x={area.get('x', 0)}, y={area.get('y', 0)}, w={area.get('width', 0)}, h={area.get('height', 0)}")
            if confidence:
                lines.append(f"  confidence: {confidence}")
        else:
            # XML/ADB: Display key attributes
            for key in ['text', 'content_desc', 'class', 'resource_id', 'xpath', 'bounds']:
                value = elem_dict.get(key)
                if value:
                    lines.append(f"  {key}: {value}")
    
    return "\n".join(lines)


def analyze_unique_elements(node_verification_data: List[Dict], device_model: str = None) -> List[Dict]:
    """
    Analyze dumps to find unique element per node
    
    Args:
        node_verification_data: List of {node_id, node_label, dump, screenshot_url}
        device_model: Device model name to determine verification command (e.g., 'android_mobile', 'example_web')
    
    Returns:
        List of {node_id, node_label, screenshot_url, dump, suggested_verification}
    """
    print(f"\n{'='*100}")
    print(f"[@dump_analyzer] 🔍 STARTING ANALYSIS: {len(node_verification_data)} nodes to analyze")
    print(f"[@dump_analyzer] 🎮 Device model: {device_model}")
    print(f"{'='*100}")
    
    print(f"\n{'='*100}")
    print(f"📥 [DUMP ANALYZER] Input mapping (node_id -> screenshot)")
    print(f"{'='*100}")
    for idx, item in enumerate(node_verification_data):
        print(f"  IN[{idx}] {item.get('node_id'):20} -> {item.get('screenshot_url', 'NO SCREENSHOT')}")
    print(f"{'='*100}\n")
    
    # Determine verification command, type, and param name based on device type
    verification_command, verification_type, param_name = _get_verification_command_and_type(device_model)
    print(f"[@dump_analyzer] ✅ Using verification command: {verification_command}")
    print(f"[@dump_analyzer] ✅ Using verification type: {verification_type}")
    print(f"[@dump_analyzer] ✅ Using param name: {param_name}")
    
    results = []
    
    # Extract all dumps
    all_dumps = {item['node_id']: item['dump'] for item in node_verification_data}
    
    for item in node_verification_data:
        node_id = item['node_id']
        node_label = item['node_label']
        screenshot_url = item['screenshot_url']
        current_dump = item['dump']
        
        # Convert dump to string for frontend display
        dump_string = _dump_to_string(current_dump)
        
        print(f"\n{'='*100}")
        print(f"[@dump_analyzer] 🎯 ANALYZING NODE: '{node_label}' ({node_id})")
        print(f"{'='*100}")
        
        # Skip nodes without dumps (focus nodes with only screenshots)
        if not current_dump or not current_dump.get('elements'):
            print(f"[@dump_analyzer] ⏭️  SKIPPED: No dump available (screenshot-only node)")
            results.append({
                'node_id': node_id,
                'node_label': node_label,
                'screenshot_url': screenshot_url,
                'dump': dump_string,
                'suggested_verification': {
                    'found': False,
                    'skipped': True,  # ← Flag to distinguish from "analyzed but not found"
                    'reason': 'No dump available'
                }
            })
            continue
        
        # ✅ Detect OCR dump (TV)
        is_ocr_dump = current_dump and current_dump.get('dump_type') == 'ocr'
        
        # Try text first (using smart scoring with primary/secondary support)
        unique_text_result = _find_unique_text_for_node(node_id, node_label, current_dump, all_dumps)
        if unique_text_result:
            primary = unique_text_result['primary']
            secondary = unique_text_result.get('secondary')
            
            if secondary:
                print(f"[@dump_analyzer] ✅ SUCCESS: Primary='{primary}', Secondary='{secondary}'")
            else:
                print(f"[@dump_analyzer] ✅ SUCCESS: Primary='{primary}' (no secondary needed)")
            
            # ✅ TV OCR: Return in format that approve_node_verifications expects
            if is_ocr_dump:
                print(f"[@dump_analyzer] 📺 OCR dump detected - extracting area data for TV verification")
                
                # Find the area for the primary text in OCR elements
                primary_area = None
                elements = current_dump.get('elements', [])
                for elem in elements:
                    if elem.get('text') == primary:
                        primary_area = elem.get('area')
                        print(f"[@dump_analyzer]    Found area for '{primary}': {primary_area}")
                        break
                
                if primary_area:
                    # Return TV format: {text: '...', area: {...}}
                    results.append({
                        'node_id': node_id,
                        'node_label': node_label,
                        'screenshot_url': screenshot_url,
                        'dump': dump_string,
                        'suggested_verification': {
                            'text': primary,  # ← Root level for TV path
                            'area': primary_area,  # ← Root level for TV path
                            'found': True
                        }
                    })
                    continue
                else:
                    print(f"[@dump_analyzer]    ⚠️ Area not found for primary text - falling back to mobile format")
            
            # Mobile/Web: Store verifications in params format
            verifications = []
            verifications.append({param_name: primary})
            if secondary:
                verifications.append({param_name: secondary})
            
            results.append({
                'node_id': node_id,
                'node_label': node_label,
                'screenshot_url': screenshot_url,
                'dump': dump_string,
                'suggested_verification': {
                    'method': verification_command,
                    'params': verifications[0],  # Frontend expects single params for now
                    'params_all': verifications,  # Store all for future use
                    'found': True,
                    'type': verification_type,
                    'has_secondary': len(verifications) > 1
                }
            })
            continue
        
        print(f"[@dump_analyzer] ⚠️  No unique text found, trying xpath...")
        
        # Fallback to xpath (only for non-OCR dumps - OCR has no xpath)
        if not is_ocr_dump:
            unique_xpath = _find_unique_xpath_for_node(node_id, current_dump, all_dumps)
            if unique_xpath:
                print(f"[@dump_analyzer] ✅ SUCCESS: Found unique xpath: '{unique_xpath}'")
                results.append({
                    'node_id': node_id,
                    'node_label': node_label,
                    'screenshot_url': screenshot_url,
                    'dump': dump_string,
                    'suggested_verification': {
                        'method': verification_command,
                        'params': {'xpath': unique_xpath},
                        'found': True,
                        'type': verification_type
                    }
                })
                continue
        
        # No unique element found
        print(f"[@dump_analyzer] ❌ FAILURE: No unique element found for '{node_label}'")
        print(f"[@dump_analyzer]    → This node has no text or xpath that's unique to it")
        
        # ✅ TV OCR: Return TV format even when no unique element found
        if is_ocr_dump:
            print(f"[@dump_analyzer] 📺 OCR dump - returning TV format with found=False")
            results.append({
                'node_id': node_id,
                'node_label': node_label,
                'screenshot_url': screenshot_url,
                'dump': dump_string,
                'suggested_verification': {
                    'text': None,  # ← TV format: no unique text found
                    'area': None,  # ← TV format: no area
                    'found': False
                }
            })
        else:
            # Mobile/Web: Return params format
            results.append({
                'node_id': node_id,
                'node_label': node_label,
                'screenshot_url': screenshot_url,
                'dump': dump_string,
                'suggested_verification': {
                    'method': verification_command,
                    'params': {},
                    'found': False,
                    'type': verification_type
                }
            })
    
    print(f"\n{'='*100}")
    print(f"📤 [DUMP ANALYZER] Output suggestions (node_id -> screenshot)")
    print(f"{'='*100}")
    for idx, suggestion in enumerate(results):
        print(f"  OUT[{idx}] {suggestion.get('node_id'):20} -> {suggestion.get('screenshot_url', 'NO SCREENSHOT')}")
    print(f"{'='*100}\n")
    
    return results


# _score_text_candidate now imported from shared.src.selector_scoring


def _find_unique_text_for_node(target_node_id: str, target_node_label: str, target_dump: Dict, all_dumps: Dict[str, Dict]) -> Optional[Dict]:
    """
    Find text that appears only in target node, using scoring.
    
    Returns:
        Dict with 'primary' and optionally 'secondary' verification, or None
        {
            'primary': 'Home Tab currently selected',
            'secondary': 'Popular Movies'  # Optional
        }
    """
    
    # Extract text elements from target dump
    target_texts = _extract_texts_from_dump(target_dump)
    
    if not target_texts:
        return None
    
    # Extract texts from all OTHER nodes
    other_texts = set()
    for node_id, dump in all_dumps.items():
        if node_id != target_node_id:
            node_texts = _extract_texts_from_dump(dump)
            other_texts.update(node_texts)
    
    # Find texts unique to target
    unique_texts = target_texts - other_texts
    
    if not unique_texts:
        return None
    
    # Score all candidates and separate strong vs weak
    strong_candidates = []  # Can be used as primary
    weak_candidates = []    # Can only be used as secondary
    
    print(f"[@dump_analyzer]   📊 Scoring {len(unique_texts)} unique candidates for '{target_node_label}':")
    
    # ⚡️ OPTIMIZATION: Build text->element map ONCE for fast lookup (avoids O(N*M) loop)
    text_map = {}
    if target_dump and 'elements' in target_dump:
        for elem in target_dump['elements']:
            e_dict = elem.__dict__ if hasattr(elem, '__dict__') else elem
            
            # Extract text matching _extract_texts_from_dump logic
            t = str(e_dict.get('text', '') or '').strip()
            if t == '<no text>': t = ''
            
            cd = str(e_dict.get('content_desc', '') or '').strip()
            if cd == '<no content-desc>': cd = ''
            
            val = t or cd
            if val:
                text_map[val] = e_dict

    for text in unique_texts:
        score, is_weak = _score_text_candidate(text, target_node_label)
        
        # 📍 POSITION BOOST: Prefer Top/Left elements (Menus/Headers)
        if text in text_map:
            area = text_map[text].get('area') # OCR/Vision dump
            if area:
                y = area.get('y', 9999)
                x = area.get('x', 9999)
                
                # Boost Top (Header/Nav)
                if y < 100: 
                    score += 30
                    print(f"      -> Boost: Top element (y={y}) +30")
                    
                # Boost Left (Side Menu)
                if x < 100: 
                    score += 30
                    print(f"      -> Boost: Left element (x={x}) +30")
        
        if is_weak:
            weak_candidates.append((score, text))
            if score > 0:  # Only log relevant weak candidates
                print(f"      • '{text}' = {score} (weak)")
        else:
            strong_candidates.append((score, text))
            if score > 0:  # Only log positive/relevant scores
                print(f"      • '{text}' = {score}")
    
    # Sort both lists by score
    strong_candidates.sort(key=lambda x: x[0], reverse=True)
    weak_candidates.sort(key=lambda x: x[0], reverse=True)
    
    # Strategy: Use best strong candidate as primary, best weak as secondary (if available)
    primary_verification = None
    secondary_verification = None
    
    if strong_candidates and strong_candidates[0][0] > -20:
        # We have a good strong candidate
        primary_verification = strong_candidates[0][1]
        print(f"[@dump_analyzer]   ✅ Primary: '{primary_verification}' (score: {strong_candidates[0][0]})")
        
        # Try to add a secondary (another strong OR a weak)
        if len(strong_candidates) > 1 and strong_candidates[1][0] > 0:
            secondary_verification = strong_candidates[1][1]
            print(f"[@dump_analyzer]   ➕ Secondary: '{secondary_verification}' (score: {strong_candidates[1][0]})")
        elif weak_candidates and weak_candidates[0][0] > 0:
            secondary_verification = weak_candidates[0][1]
            print(f"[@dump_analyzer]   ➕ Secondary: '{secondary_verification}' (score: {weak_candidates[0][0]}, weak)")
    
    elif weak_candidates and weak_candidates[0][0] > -20:
        # No strong candidates, but we have a decent weak one
        # In this case, we MUST have a secondary to make it reliable
        if len(weak_candidates) >= 2 and weak_candidates[1][0] > 0:
            primary_verification = weak_candidates[0][1]
            secondary_verification = weak_candidates[1][1]
            print(f"[@dump_analyzer]   ⚠️  Only weak candidates available:")
            print(f"[@dump_analyzer]      Primary (weak): '{primary_verification}' (score: {weak_candidates[0][0]})")
            print(f"[@dump_analyzer]      Secondary (weak): '{secondary_verification}' (score: {weak_candidates[1][0]})")
        else:
            print(f"[@dump_analyzer]   ❌ Only one weak candidate, not reliable enough without secondary")
            return None
    else:
        print(f"[@dump_analyzer]   ❌ All candidates had low scores")
        return None
    
    # Return result
    if primary_verification:
        result = {'primary': primary_verification}
        if secondary_verification:
            result['secondary'] = secondary_verification
        return result
    
    return None


def _find_unique_xpath_for_node(target_node_id: str, target_dump: Dict, all_dumps: Dict[str, Dict]) -> Optional[str]:
    """Find xpath that appears only in target node"""
    
    # Extract xpaths from target dump
    target_xpaths = _extract_xpaths_from_dump(target_dump)
    
    if not target_xpaths:
        return None
    
    # Extract xpaths from all OTHER nodes
    other_xpaths = set()
    for node_id, dump in all_dumps.items():
        if node_id != target_node_id:
            node_xpaths = _extract_xpaths_from_dump(dump)
            other_xpaths.update(node_xpaths)
    
    # Find xpaths unique to target
    unique_xpaths = target_xpaths - other_xpaths
    
    if not unique_xpaths:
        return None
    
    # Pick shortest unique xpath (usually most specific)
    shortest = min(unique_xpaths, key=len)
    return shortest


# _extract_texts_from_dump and _extract_xpaths_from_dump now imported from shared.src.selector_scoring
