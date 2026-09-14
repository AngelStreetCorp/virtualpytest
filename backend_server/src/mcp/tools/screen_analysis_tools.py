"""
Screen Analysis Tools - Unified selector analysis for actions and verifications

Provides LLMs with direct access to the same selector scoring logic used by exploration.
No more guessing - get analyzed selectors ready for create_edge or verify_node.
"""

import json
from typing import Dict, Any
from ..utils.mcp_formatter import MCPFormatter

from shared.src.lib.utils.selector_scoring import find_best_selector


class ScreenAnalysisTools:
    """Screen analysis tools for finding best selectors"""
    
    def __init__(self):
        self.formatter = MCPFormatter()
    
    def analyze_screen_for_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze screen elements to find best selector for clicking/interacting. Returns ready-to-use action parameters.
        
        Example: analyze_screen_for_action(elements=[...], intent='search button', platform='web')
        
        Args:
            params: {
                'elements': list (REQUIRED - elements from dump_ui_elements),
                'intent': str (REQUIRED - what to click like search field or login button),
                'platform': str (REQUIRED - mobile or web)
            }
        
        Returns:
            MCP-formatted response with selector and action params
        """
        elements = params.get('elements', [])
        intent = params.get('intent', '')
        platform = params.get('platform', 'web')
        
        # Parse elements if they come as a JSON string
        if isinstance(elements, str):
            try:
                elements = json.loads(elements)
            except json.JSONDecodeError as e:
                return self.formatter.format_error(f"Invalid elements JSON: {str(e)}")
        
        # Validate
        if not elements:
            return self.formatter.format_error("No elements provided. Call dump_ui_elements first.")
        
        if not isinstance(elements, list):
            return self.formatter.format_error(f"Elements must be a list, got {type(elements).__name__}")
        
        if platform not in ['mobile', 'web']:
            return self.formatter.format_error(f"Invalid platform: {platform}. Use 'mobile' or 'web'.")
        
        # Find best selector using unified scoring
        try:
            result = find_best_selector(
                elements=elements,
                platform=platform,
                context_label=intent,
                require_unique=True  # Always require uniqueness
            )
            
            if not result:
                return self.formatter.format_error(
                    f"No unique selector found for '{intent}'.\n"
                    f"This usually means:\n"
                    f"1. Element doesn't exist on screen\n"
                    f"2. All selectors are ambiguous (multiple matches)\n"
                    f"Try: dump_ui_elements to see what's available"
                )
            
            # Build action command based on platform and selector type
            selector_type = result['selector_type']
            selector_value = result['selector_value']
            
            # MOBILE: Always use click_element (text-based) - IDs are unreliable on mobile ADB
            # WEB: Can use click_element_by_id for stable element IDs
            if platform == 'mobile':
                # Mobile always uses click_element with text/xpath - never by ID
                command = 'click_element'
                action_params = {'text': selector_value, 'wait_time': 1000}
            else:
                # Web platform
                if selector_type == 'id':
                    command = 'click_element_by_id'
                    action_params = {'element_id': selector_value, 'wait_time': 1000}
                elif selector_type == 'xpath':
                    command = 'click_element'
                    action_params = {'xpath': selector_value, 'wait_time': 1000}
                else:  # text or content_desc
                    command = 'click_element'
                    action_params = {'text': selector_value, 'wait_time': 1000}
            
            # Determine confidence
            score = result['score']
            if score >= 1000:
                confidence = 'high'
            elif score >= 500:
                confidence = 'medium'
            else:
                confidence = 'low'
            
            return {
                "content": [{"type": "text", "text": f"selector:{selector_type}={selector_value}"}],
                "isError": False,
                "command": command,
                "params": action_params,
                "score": score
            }
            
        except Exception as e:
            return self.formatter.format_error(f"Analysis failed: {str(e)}")
    
    def analyze_screen_for_verification(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze screen elements to find best verification for node detection. Returns ready-to-use verification parameters.
        
        Example: analyze_screen_for_verification(elements=[...], node_label='home', platform='web')
        
        Args:
            params: {
                'elements': list (REQUIRED - elements from dump_ui_elements),
                'node_label': str (REQUIRED - node name like home or login),
                'platform': str (REQUIRED - mobile or web)
            }
        
        Returns:
            MCP-formatted response with verification params
        """
        elements = params.get('elements', [])
        node_label = params.get('node_label', '')
        platform = params.get('platform', 'web')
        
        # Parse elements if they come as a JSON string
        if isinstance(elements, str):
            try:
                elements = json.loads(elements)
            except json.JSONDecodeError as e:
                return self.formatter.format_error(f"Invalid elements JSON: {str(e)}")
        
        # Validate
        if not elements:
            return self.formatter.format_error("No elements provided. Call dump_ui_elements first.")
        
        if not isinstance(elements, list):
            return self.formatter.format_error(f"Elements must be a list, got {type(elements).__name__}")
        
        if not node_label:
            return self.formatter.format_error("node_label is required (e.g., 'home', 'login')")
        
        if platform not in ['mobile', 'web']:
            return self.formatter.format_error(f"Invalid platform: {platform}. Use 'mobile' or 'web'.")
        
        # Find best selector
        try:
            result = find_best_selector(
                elements=elements,
                platform=platform,
                context_label=node_label,
                require_unique=True
            )
            
            if not result:
                return self.formatter.format_error(
                    f"No unique verification found for node '{node_label}'.\n"
                    f"Try: Navigate to the screen first, then dump_ui_elements"
                )
            
            # Build verification command based on platform
            selector_type = result['selector_type']
            selector_value = result['selector_value']
            
            # Verification command name varies by platform
            if platform == 'mobile':
                verification_command = 'waitForElementToAppear'
                param_name = 'search_term'
            else:  # web
                verification_command = 'waitForElementToAppear'
                param_name = 'text'
            
            verification_params = {param_name: selector_value}
            
            # Determine confidence
            score = result['score']
            if score >= 1000:
                confidence = 'high'
            elif score >= 500:
                confidence = 'medium'
            else:
                confidence = 'low'
            
            return {
                "content": [{"type": "text", "text": f"verification:{selector_type}={selector_value}"}],
                "isError": False,
                "command": verification_command,
                "verification_type": 'adb' if platform == 'mobile' else 'web',
                "params": verification_params,
                "score": score
            }
            
        except Exception as e:
            return self.formatter.format_error(f"Analysis failed: {str(e)}")

