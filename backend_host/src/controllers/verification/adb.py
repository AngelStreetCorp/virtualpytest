"""
ADB Verification Controller Implementation

This controller provides ADB-based verification functionality using direct ADB connections.
It uses adbUtils for element verification.
"""

import time
from typing import Dict, Any, List, Optional, Tuple

# Use absolute import from shared library
import sys
import os
# Get path to shared/lib/utils (go up to project root)
# Import local utilities

from  backend_host.src.lib.utils.adb_utils import ADBUtils, AndroidElement
from ..base_controller import VerificationControllerInterface


class ADBVerificationController(VerificationControllerInterface):
    """ADB verification controller that uses direct ADB commands to verify UI elements."""
    
    def __init__(self, av_controller=None, device_ip: str = None, device_port: int = 5555, **kwargs):
        """
        Initialize the ADB Verification controller.
        
        Args:
            av_controller: AV controller for capturing screenshots (optional, not used by ADB)
            device_ip: Android device IP address (required for ADB connection)
            device_port: ADB port (default: 5555)
        """
        super().__init__("ADB Verification", "adb")
        
        # Store device connection parameters
        self.device_ip = device_ip
        self.device_port = device_port
        self.verification_type = 'adb'
        self.device_id = f"{self.device_ip}:{self.device_port}"
        
        self.adb_utils = ADBUtils()
        self.is_connected = True  # Assume connected since we're using direct ADB
        
        print(f"[@controller:ADBVerification] Initialized for device {self.device_id}")

    def connect(self) -> bool:
        """Connect to the ADB device if device_ip is provided."""
        if not self.device_ip:
            print(f"[@controller:ADBVerification] No device IP provided, skipping ADB connection")
            return True  # Return True for fallback mode
        
        try:
            print(f"[@controller:ADBVerification] Connecting to ADB device {self.device_id}")
            success = self.adb_utils.connect_device(self.device_id)
            if success:
                print(f"[@controller:ADBVerification] Successfully connected to {self.device_id}")
                self.is_connected = True
            else:
                print(f"[@controller:ADBVerification] Failed to connect to {self.device_id}")
                self.is_connected = False
            return success
        except Exception as e:
            print(f"[@controller:ADBVerification] Connection error: {e}")
            self.is_connected = False
            return False

    def getElementLists(self) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Get list of all UI elements from ADB UI dump.
        
        Returns:
            Tuple of (success, element_list, error_message)
        """
        try:
            print(f"[@controller:ADBVerification:getElementLists] Getting elements for device {self.device_id}")
            
            # Use existing adbUtils to dump UI elements
            success, elements, error = self.adb_utils.dump_elements(self.device_id)
            
            if not success:
                print(f"[@controller:ADBVerification:getElementLists] Failed: {error}")
                return False, [], error
            
            # Convert AndroidElement objects to dictionaries
            element_list = [element.to_dict() for element in elements]
            
            print(f"[@controller:ADBVerification:getElementLists] Success: {len(element_list)} elements")
            return True, element_list, ""
            
        except Exception as e:
            error_msg = f"Element listing error: {e}"
            print(f"[@controller:ADBVerification:getElementLists] ERROR: {error_msg}")
            return False, [], error_msg

    def getElementListsWithSmartSearch(self, search_term: str = None) -> Tuple[bool, Dict[str, Any], str]:
        """
        Get enhanced element listing with optional smart search capabilities. Supports pipe-separated terms for fallback (e.g., "BBC ONE|SRF 1|RTS 1").
        
        Args:
            search_term: Optional search term for filtering elements (case-insensitive)
                        Can use pipe-separated terms: "text1|text2|text3"
            
        Returns:
            Tuple of (success, enhanced_element_data, error_message)
        """
        try:
            print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Getting enhanced element list for device {self.device_id}")
            if search_term:
                print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] With smart search for: '{search_term}'")
            
            # Get all UI elements
            success, elements, error = self.adb_utils.dump_elements(self.device_id)
            
            if not success:
                print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Failed: {error}")
                return False, {}, error
            
            # Convert AndroidElement objects to dictionaries
            element_list = [element.to_dict() for element in elements]
            
            # Build enhanced response
            enhanced_data = {
                "total_elements": len(element_list),
                "elements": element_list,
                "device_info": {
                    "device_id": self.device_id,
                    "device_name": "adb_verification"
                }
            }
            
            # Add smart search results if search term provided
            if search_term and search_term.strip():
                search_term_clean = search_term.strip()
                print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Performing smart search for '{search_term_clean}'")
                
                # Check if we have pipe-separated terms
                if '|' in search_term_clean:
                    terms = [term.strip() for term in search_term_clean.split('|') if term.strip()]
                    print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Using fallback strategy with {len(terms)} terms: {terms}")
                    
                    # Try each term until one succeeds
                    search_success = False
                    matches = []
                    search_error = None
                    successful_term = None
                    
                    for i, term in enumerate(terms):
                        print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Attempt {i+1}/{len(terms)}: Searching for '{term}'")
                        
                        term_success, term_matches, term_error = self.adb_utils.smart_element_search(self.device_id, term)
                        
                        if term_success and term_matches:
                            search_success = True
                            matches = term_matches
                            successful_term = term
                            print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] SUCCESS: Found matches using term '{term}'")
                            break
                        elif term_error:
                            search_error = term_error
                            print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Search failed for term '{term}': {term_error}")
                    
                    enhanced_data["search_results"] = {
                        "search_term": search_term_clean,
                        "attempted_terms": terms,
                        "successful_term": successful_term,
                        "search_performed": True,
                        "search_success": search_success,
                        "total_matches": len(matches) if search_success else 0,
                        "matches": matches if search_success else [],
                        "search_error": search_error if not search_success else None,
                        "search_details": {
                            "case_sensitive": False,
                            "search_method": "contains_any_attribute",
                            "searched_attributes": ["text", "content_desc", "resource_id", "class_name"],
                            "fallback_strategy": True
                        }
                    }
                else:
                    # Single term - original logic
                    terms = [search_term_clean]
                    search_success, matches, search_error = self.adb_utils.smart_element_search(self.device_id, search_term_clean)
                    
                    enhanced_data["search_results"] = {
                        "search_term": search_term_clean,
                        "attempted_terms": terms,
                        "successful_term": search_term_clean if search_success else None,
                        "search_performed": True,
                        "search_success": search_success,
                        "total_matches": len(matches) if search_success else 0,
                        "matches": matches if search_success else [],
                        "search_error": search_error if not search_success else None,
                        "search_details": {
                            "case_sensitive": False,
                            "search_method": "contains_any_attribute",
                            "searched_attributes": ["text", "content_desc", "resource_id", "class_name"],
                            "fallback_strategy": False
                        }
                    }
                
                if search_success and matches:
                    print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Smart search found {len(matches)} matches")
                    for i, match in enumerate(matches, 1):
                        print(f"[@controller:ADBVerification:getElementListsWithSmartSearch]   {i}. Element {match['element_id']}: {match['match_reason']}")
                elif search_success:
                    print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Smart search completed - no matches found")
                else:
                    print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Smart search failed: {search_error}")
            else:
                enhanced_data["search_results"] = {
                    "search_performed": False,
                    "message": "No search term provided"
                }
            
            print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] Success: {len(element_list)} total elements")
            return True, enhanced_data, ""
            
        except Exception as e:
            error_msg = f"Enhanced element listing error: {e}"
            print(f"[@controller:ADBVerification:getElementListsWithSmartSearch] ERROR: {error_msg}")
            return False, {}, error_msg

    def waitForElementToAppear(self, search_term: str, timeout: float = 0.0) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Wait for an element matching search_term to appear. Supports pipe-separated terms for fallback (e.g., "BBC ONE|SRF 1|RTS 1").
        
        Args:
            search_term: The term to search for (case-insensitive, searches all attributes)
                        Can use pipe-separated terms: "text1|text2|text3"
            timeout: Maximum time to wait in seconds (default: 0.0 = check only once, no polling)
        
        Returns:
            Tuple of (success, message, result_data)
        """
        try:
            print(f"[@controller:ADBVerification:waitForElementToAppear] Waiting for '{search_term}' (timeout: {timeout}s)")
            
            # Check if we have pipe-separated terms
            if '|' in search_term:
                terms = [term.strip() for term in search_term.split('|') if term.strip()]
                print(f"[@controller:ADBVerification:waitForElementToAppear] Using fallback strategy with {len(terms)} terms: {terms}")
            else:
                terms = [search_term]
                print(f"[@controller:ADBVerification:waitForElementToAppear] Using single search term: '{search_term}'")
            
            start_time = time.time()
            
            # Always do at least one check, then continue if timeout > 0
            while True:
                # Try each term in sequence until one succeeds
                found_match = False
                successful_term = None
                final_matches = []
                final_error = None
                
                for i, term in enumerate(terms):
                    if len(terms) > 1:
                        print(f"[@controller:ADBVerification:waitForElementToAppear] Attempt {i+1}/{len(terms)}: Searching for '{term}'")
                    
                    success, matches, error = self.adb_utils.smart_element_search(self.device_id, term)
                    
                    if error:
                        print(f"[@controller:ADBVerification:waitForElementToAppear] Search failed for term '{term}': {error}")
                        final_error = error
                    else:
                        if success and matches:
                            found_match = True
                            successful_term = term
                            final_matches = matches
                            print(f"[@controller:ADBVerification:waitForElementToAppear] SUCCESS: Found element using term '{term}'")
                            break  # Found a match, no need to try other terms
                
                if found_match:
                    elapsed = time.time() - start_time
                    message = f"Element found after {elapsed:.1f}s using term '{successful_term}'"
                    print(f"[@controller:ADBVerification:waitForElementToAppear] SUCCESS: {message}")
                    
                    result_data = {
                        'search_term': search_term,
                        'successful_term': successful_term,
                        'attempted_terms': terms,
                        'wait_time': elapsed,
                        'total_matches': len(final_matches),
                        'matches': final_matches,
                        'search_details': {
                            'case_sensitive': False,
                            'search_method': 'contains_any_attribute',
                            'searched_attributes': ['text', 'content_desc', 'resource_id', 'class_name'],
                            'fallback_strategy': len(terms) > 1
                        }
                    }
                    
                    print(f"[@controller:ADBVerification:waitForElementToAppear] Found {len(final_matches)} matching elements:")
                    for i, match in enumerate(final_matches, 1):
                        print(f"[@controller:ADBVerification:waitForElementToAppear]   {i}. Element {match['element_id']}: {match['match_reason']}")
                    
                    return True, message, result_data
                
                # Check if we should continue polling
                elapsed = time.time() - start_time
                if timeout <= 0 or elapsed >= timeout:
                    break
                
                # Sleep before next check
                time.sleep(1.0)
            
            elapsed = time.time() - start_time
            message = f"Element '{search_term}' not found after {elapsed:.1f}s"
            print(f"[@controller:ADBVerification:waitForElementToAppear] FAILED: {message}")
            
            result_data = {
                'search_term': search_term,
                'attempted_terms': terms,
                'wait_time': elapsed,
                'timeout_reached': True,
                'search_details': {
                    'case_sensitive': False,
                    'search_method': 'contains_any_attribute',
                    'searched_attributes': ['text', 'content_desc', 'resource_id', 'class_name'],
                    'fallback_strategy': len(terms) > 1
                },
                'last_error': final_error
            }
            
            return False, message, result_data
            
        except Exception as e:
            error_msg = f"Wait for element appear error: {e}"
            print(f"[@controller:ADBVerification:waitForElementToAppear] ERROR: {error_msg}")
            
            result_data = {
                'search_term': search_term,
                'error_details': str(e)
            }
            
            return False, error_msg, result_data

    def waitForElementToDisappear(self, search_term: str, timeout: float = 0.0) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Wait for an element matching search_term to disappear. Supports pipe-separated terms for fallback (e.g., "BBC ONE|SRF 1|RTS 1").
        
        Args:
            search_term: The term to search for (case-insensitive, searches all attributes)
                        Can use pipe-separated terms: "text1|text2|text3"
            timeout: Maximum time to wait in seconds (default: 0.0 = check only once, no polling)
        
        Returns:
            Tuple of (success, message, result_data)
        """
        try:
            print(f"[@controller:ADBVerification:waitForElementToDisappear] Waiting for '{search_term}' to disappear (timeout: {timeout}s)")
            
            # Check if we have pipe-separated terms
            if '|' in search_term:
                terms = [term.strip() for term in search_term.split('|') if term.strip()]
                print(f"[@controller:ADBVerification:waitForElementToDisappear] Using fallback strategy with {len(terms)} terms: {terms}")
            else:
                terms = [search_term]
                print(f"[@controller:ADBVerification:waitForElementToDisappear] Using single search term: '{search_term}'")
            
            start_time = time.time()
            
            # Always do at least one check, then continue if timeout > 0
            while True:
                # Check if ANY of the terms still exist (element disappears when NONE are found)
                any_term_found = False
                successful_term = None
                final_matches = []
                final_error = None
                
                for i, term in enumerate(terms):
                    if len(terms) > 1:
                        print(f"[@controller:ADBVerification:waitForElementToDisappear] Checking {i+1}/{len(terms)}: Searching for '{term}'")
                    
                    success, matches, error = self.adb_utils.smart_element_search(self.device_id, term)
                    
                    if error:
                        print(f"[@controller:ADBVerification:waitForElementToDisappear] Search failed for term '{term}': {error}")
                        final_error = error
                    else:
                        if success and matches:
                            any_term_found = True
                            successful_term = term
                            final_matches.extend(matches)  # Collect all matches from all terms
                            print(f"[@controller:ADBVerification:waitForElementToDisappear] Element still present using term '{term}'")
                            # Continue checking other terms to get complete picture
                
                # Element has disappeared if NO terms were found
                if not any_term_found:
                    elapsed = time.time() - start_time
                    message = f"Element '{search_term}' disappeared after {elapsed:.1f}s"
                    print(f"[@controller:ADBVerification:waitForElementToDisappear] SUCCESS: {message}")
                    
                    result_data = {
                        'search_term': search_term,
                        'attempted_terms': terms,
                        'wait_time': elapsed,
                        'search_details': {
                            'case_sensitive': False,
                            'search_method': 'contains_any_attribute',
                            'searched_attributes': ['text', 'content_desc', 'resource_id', 'class_name'],
                            'fallback_strategy': len(terms) > 1
                        }
                    }
                    
                    return True, message, result_data
                
                # Check if we should continue polling
                elapsed = time.time() - start_time
                if timeout <= 0 or elapsed >= timeout:
                    break
                
                # Sleep before next check
                time.sleep(1.0)
            
            elapsed = time.time() - start_time
            message = f"Element '{search_term}' still present after {elapsed:.1f}s"
            print(f"[@controller:ADBVerification:waitForElementToDisappear] FAILED: {message}")
            
            result_data = {
                'search_term': search_term,
                'attempted_terms': terms,
                'wait_time': elapsed,
                'timeout_reached': True,
                'element_still_present': True,
                'search_details': {
                    'case_sensitive': False,
                    'search_method': 'contains_any_attribute',
                    'searched_attributes': ['text', 'content_desc', 'resource_id', 'class_name'],
                    'fallback_strategy': len(terms) > 1
                },
                'last_error': final_error
            }
            
            # Include details of still present elements in failure response
            if successful_term and final_matches:
                result_data['still_present_elements'] = final_matches
                result_data['total_still_present'] = len(final_matches)
                result_data['successful_term'] = successful_term
                print(f"[@controller:ADBVerification:waitForElementToDisappear] {len(final_matches)} elements still present using term '{successful_term}'")
                for match in final_matches:
                    print(f"[@controller:ADBVerification:waitForElementToDisappear] Still present: Element {match['element_id']} - {match['match_reason']}")
            
            return False, message, result_data
            
        except Exception as e:
            error_msg = f"Wait for element disappear error: {e}"
            print(f"[@controller:ADBVerification:waitForElementToDisappear] ERROR: {error_msg}")
            
            result_data = {
                'search_term': search_term,
                'error_details': str(e)
            }
            
            return False, error_msg, result_data
    
    def getMenuInfo(self, area: dict = None, context = None) -> Dict[str, Any]:
        """
        Extract menu info from UI dump (ADB-based alternative to OCR getMenuInfo).
        Same interface as text.getMenuInfo but uses UI dump instead of OCR.
        
        Args:
            area: Optional area to filter elements (x, y, width, height)
            context: Execution context for metadata storage
            
        Returns:
            Same format as text.getMenuInfo:
            {
                success: bool,
                output_data: {
                    parsed_data: dict,
                    raw_output: str,
                    element_count: int
                },
                message: str
            }
        """
        print(f"[@controller:ADBVerification:getMenuInfo] Params: area={area}, context={context is not None}")
        
        try:
            # 1. Dump UI elements using adb_utils (REUSE EXISTING LOGIC)
            print(f"[@controller:ADBVerification:getMenuInfo] Dumping UI elements...")
            success, elements, error = self.adb_utils.dump_elements(self.device_id)
            
            if not success:
                print(f"[@controller:ADBVerification:getMenuInfo] FAIL: UI dump failed: {error}")
                return {
                    'success': False,
                    'output_data': {},
                    'message': f'Failed to dump UI: {error}'
                }
            
            print(f"[@controller:ADBVerification:getMenuInfo] Dumped {len(elements)} UI elements")
            
            # 2. Filter by area if specified
            filtered_elements = elements
            if area:
                filtered_elements = []
                import re
                for elem in elements:
                    # Parse bounds to get x, y, width, height (elem is AndroidElement object)
                    if hasattr(elem, 'bounds') and isinstance(elem.bounds, str) and elem.bounds:
                        bounds_match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', elem.bounds)
                        if bounds_match:
                            x1, y1, x2, y2 = map(int, bounds_match.groups())
                            elem_x, elem_y = x1, y1
                            elem_width, elem_height = x2 - x1, y2 - y1
                            
                            # Check if element overlaps with area
                            area_x = area.get('x', 0)
                            area_y = area.get('y', 0)
                            area_width = area.get('width', 99999)
                            area_height = area.get('height', 99999)
                            
                            # Element is in area if it overlaps
                            if (elem_x < area_x + area_width and
                                elem_x + elem_width > area_x and
                                elem_y < area_y + area_height and
                                elem_y + elem_height > area_y):
                                filtered_elements.append(elem)
                
                print(f"[@controller:ADBVerification:getMenuInfo] Filtered to {len(filtered_elements)} elements in area")
            
            # 3. Parse key-value pairs from element text OR content_desc (check both!)
            # Handle multiple separator patterns common in mobile settings/info screens:
            # - "Key\nValue" or "Key&#10;Value" (newline, HTML-encoded)
            # - "Key: Value" (colon + space)
            # - "Key - Value" (dash)
            # - "Key\tValue" (tab)
            import html
            
            parsed_data = {}
            for elem in filtered_elements:
                # Get text from either text or content_desc field
                text = ''
                if hasattr(elem, 'text') and elem.text and elem.text != '<no text>':
                    text = elem.text.strip()
                elif hasattr(elem, 'content_desc') and elem.content_desc and elem.content_desc != '<no content-desc>':
                    text = elem.content_desc.strip()
                
                # Skip if no useful text
                if not text:
                    continue
                
                # Decode HTML entities (e.g., &#10; -> \n)
                text = html.unescape(text)
                
                # Try different separator patterns
                key = None
                value = None
                
                # Pattern 1: "Key\nValue" (newline - most common in Android)
                if '\n' in text:
                    lines = text.split('\n')
                    if len(lines) >= 2:
                        key = lines[0].strip()
                        value = '\n'.join(lines[1:]).strip()
                
                # Pattern 2: "Key: Value" (colon + space)
                elif ': ' in text and len(text) < 200:  # Reasonable length
                    parts = text.split(': ', 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                
                # Pattern 3: "Key - Value" (dash separator)
                elif ' - ' in text and len(text) < 200:
                    parts = text.split(' - ', 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                
                # Pattern 4: "Key\tValue" (tab)
                elif '\t' in text:
                    parts = text.split('\t')
                    if len(parts) >= 2:
                        key = parts[0].strip()
                        value = '\t'.join(parts[1:]).strip()
                
                # Store if we found a valid key-value pair
                if key and value:
                    # Normalize key: replace spaces and special chars with underscore
                    normalized_key = key.replace(' ', '_').replace('-', '_').replace(':', '')
                    parsed_data[normalized_key] = value
                    print(f"  • {normalized_key} = {value}")
            
            print(f"[@controller:ADBVerification:getMenuInfo] Parsed {len(parsed_data)} key-value pairs")
            
            # ALWAYS log this summary - even if empty
            print(f"[@controller:ADBVerification:getMenuInfo] === PARSED DATA SUMMARY ===")
            print(f"[@controller:ADBVerification:getMenuInfo] Total pairs parsed: {len(parsed_data)}")
            print(f"[@controller:ADBVerification:getMenuInfo] Keys: {list(parsed_data.keys())}")
            print(f"[@controller:ADBVerification:getMenuInfo] =============================")
            
            if not parsed_data:
                print(f"[@controller:ADBVerification:getMenuInfo] WARNING: No key-value pairs found in UI dump")
            else:
                # Log all parsed key-value pairs for visibility
                print(f"[@controller:ADBVerification:getMenuInfo] === PARSED DATA START ===")
                for key, value in parsed_data.items():
                    # Truncate long values for readability
                    display_value = value if len(value) <= 100 else f"{value[:100]}..."
                    print(f"[@controller:ADBVerification:getMenuInfo]   {key} = {display_value}")
                print(f"[@controller:ADBVerification:getMenuInfo] === PARSED DATA END ===")
            
            # 4. Prepare output data with FULL raw dump for debugging
            # NOTE: Controller does NOT store to context - that's the caller's responsibility
            raw_dump = []
            for elem in filtered_elements:
                raw_dump.append({
                    'index': elem.id,
                    'tag': elem.tag,
                    'text': elem.text,
                    'resource_id': elem.resource_id,
                    'content_desc': elem.content_desc,
                    'class_name': elem.class_name,
                    'bounds': elem.bounds,
                    'clickable': elem.clickable,
                    'enabled': elem.enabled
                })
            
            output_data = {
                'parsed_data': parsed_data,
                'raw_dump': raw_dump,  # Full structured dump for debugging
                'element_count': len(filtered_elements)
            }
            
            # Print raw dump for debugging
            print(f"[@controller:ADBVerification:getMenuInfo] Full raw dump available with {len(raw_dump)} elements")
            print(f"[@controller:ADBVerification:getMenuInfo] === RAW DUMP START ===")
            for i, elem_data in enumerate(raw_dump, 1):
                print(f"[@controller:ADBVerification:getMenuInfo]   Element {i}/{len(raw_dump)}:")
                print(f"[@controller:ADBVerification:getMenuInfo]     Index: {elem_data['index']}")
                print(f"[@controller:ADBVerification:getMenuInfo]     Tag: {elem_data['tag']}")
                print(f"[@controller:ADBVerification:getMenuInfo]     Text: {repr(elem_data['text'])}")
                print(f"[@controller:ADBVerification:getMenuInfo]     Resource ID: {elem_data['resource_id']}")
                print(f"[@controller:ADBVerification:getMenuInfo]     Content Desc: {elem_data['content_desc']}")
                print(f"[@controller:ADBVerification:getMenuInfo]     Class: {elem_data['class_name']}")
                print(f"[@controller:ADBVerification:getMenuInfo]     Bounds: {elem_data['bounds']}")
                print(f"[@controller:ADBVerification:getMenuInfo]     Clickable: {elem_data['clickable']}, Enabled: {elem_data['enabled']}")
            print(f"[@controller:ADBVerification:getMenuInfo] === RAW DUMP END ===")
            
            # 6. Return same format as text.getMenuInfo
            message = f'Parsed {len(parsed_data)} fields from {len(filtered_elements)} UI elements'
            
            print(f"[@controller:ADBVerification:getMenuInfo] ✅ SUCCESS: {message}")
            print(f"[@controller:ADBVerification:getMenuInfo] 📤 RETURNING output_data with {len(parsed_data)} parsed_data entries")
            print(f"[@controller:ADBVerification:getMenuInfo] 📤 output_data keys: {list(output_data.keys())}")
            
            return {
                'success': True,
                'output_data': output_data,
                'message': message
            }
            
        except Exception as e:
            error_msg = f"Error extracting menu info from UI dump: {str(e)}"
            print(f"[@controller:ADBVerification:getMenuInfo] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'output_data': {},
                'message': error_msg
            }
    
    def get_available_verifications(self) -> List[Dict[str, Any]]:
        """Get available verifications for ADB controller with typed parameters."""
        from shared.src.lib.schemas.param_types import create_param, create_output, ParamType, OutputType
        
        return [
            {
                'command': 'waitForElementToAppear',
                'label': 'Wait for Element to Appear',
                'description': 'Wait for UI element to appear using ADB UI dump',
                'params': {
                    'search_term': create_param(
                        ParamType.STRING,
                        required=True,
                        default='',
                        description="Element search term (text, id, xpath)",
                        placeholder="Enter element identifier"
                    ),
                    'timeout': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=0.0,
                        description="Maximum time to wait (seconds)"
                    )
                },
                'verification_type': 'adb'
            },
            {
                'command': 'waitForElementToDisappear',
                'label': 'Wait for Element to Disappear',
                'description': 'Wait for UI element to disappear using ADB UI dump',
                'params': {
                    'search_term': create_param(
                        ParamType.STRING,
                        required=True,
                        default='',
                        description="Element search term (text, id, xpath)",
                        placeholder="Enter element identifier"
                    ),
                    'timeout': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=0.0,
                        description="Maximum time to wait (seconds)"
                    )
                },
                'verification_type': 'adb'
            },
            {
                'command': 'getMenuInfo',
                'label': 'Get Menu Info',
                'description': 'Extract key-value pairs from menu/info screen using ADB UI dump and parse automatically',
                'params': {
                    'area': create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Screen area to extract menu information from"
                    )
                },
                'outputs': [
                    create_output(
                        'parsed_data',
                        OutputType.OBJECT,
                        description="Parsed key-value pairs from UI elements"
                    ),
                    create_output(
                        'raw_dump',
                        OutputType.ARRAY,
                        description="Full raw UI element dump for debugging"
                    ),
                    create_output(
                        'element_count',
                        OutputType.NUMBER,
                        description="Number of UI elements extracted"
                    )
                ],
                'verification_type': 'adb'
            }
        ]

    def execute_verification(self, verification_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute verification and return frontend-expected format (consistent with image/text).
        
        Args:
            verification_config: {
                'command': 'waitForElementToAppear' | 'getMenuInfo',
                'params': {...}
            }
            
        Returns:
            Frontend-expected format matching image/text verification
        """
        try:
            # Extract parameters
            params = verification_config.get('params', {})
            command = verification_config.get('command', 'waitForElementToAppear')
            
            print(f"[@controller:ADBVerification] Executing {command}")
            
            # Handle getMenuInfo separately (different params)
            if command == 'getMenuInfo':
                area = params.get('area')
                context = verification_config.get('context')
                menu_result = self.getMenuInfo(area=area, context=context)
                
                # Convert to standard verification format for consistent logging
                return {
                    'success': menu_result['success'],
                    'message': menu_result['message'],
                    'output_data': menu_result.get('output_data', {}),
                    'details': menu_result.get('output_data', {})  # For route processing
                }
            
            # Handle wait commands (require search_term)
            search_term = params.get('search_term', '')
            if not search_term:
                return {
                    'success': False,
                    'message': 'No search term specified for ADB verification',
                    'matching_result': 0.0,
                    'user_threshold': 0.8,
                    'image_filter': 'none',
                    'searchedText': search_term,
                    'extractedText': '',
                    'details': {'error': 'Missing search_term parameter'}
                }
            
            # Optional parameters with defaults
            timeout_ms = float(params.get('timeout', 0))
            
            # Convert milliseconds to seconds (system passes timeout in ms)
            timeout = timeout_ms / 1000.0
            
            print(f"[@controller:ADBVerification] Timeout conversion: {timeout_ms}ms -> {timeout}s")
            
            # Validate timeout (prevent unreasonably large values)
            if timeout > 60:  # 1 minute max
                print(f"[@controller:ADBVerification] WARNING: Large timeout value {timeout}s detected, capping at 60s")
                timeout = 60
            
            print(f"[@controller:ADBVerification] Executing {command} with search term: '{search_term}'")
            print(f"[@controller:ADBVerification] Parameters: timeout={timeout}")
            
            # Execute verification based on command
            if command == 'waitForElementToAppear':
                success, message, details = self.waitForElementToAppear(
                    search_term=search_term,
                    timeout=timeout
                )
            elif command == 'waitForElementToDisappear':
                success, message, details = self.waitForElementToDisappear(
                    search_term=search_term,
                    timeout=timeout
                )
            else:
                return {
                    'success': False,
                    'message': f'Unknown ADB verification command: {command}',
                    'matching_result': 0.0,
                    'user_threshold': 0.8,
                    'image_filter': 'none',
                    'searchedText': search_term,
                    'extractedText': '',
                    'details': {'error': f'Unsupported command: {command}'}
                }
            
            # Return frontend-expected format (consistent with image/text verification + ADB-specific properties)
            response = {
                'success': success,
                'message': message,
                'matching_result': 1.0 if success else 0.0,  # Binary for ADB (found/not found)
                'user_threshold': 0.8,                       # Default for consistency
                'image_filter': 'none',                      # Not applicable for ADB
                'searchedText': search_term,                 # What we searched for
                'extractedText': f"Found {details.get('total_matches', 0)} matches" if success else "No matches found",
                
                # ADB-specific properties for frontend compatibility
                'search_term': search_term,                  # Frontend expects this
                'wait_time': details.get('wait_time', 0.0),  # Frontend expects this
                'total_matches': details.get('total_matches', 0),  # Frontend expects this
                'matches': details.get('matches', []),       # Frontend expects this
                
                'details': details  # Keep for route processing, will be removed by route
            }
            
            return response
            
        except Exception as e:
            print(f"[@controller:ADBVerification] Execution error: {e}")
            return {
                'success': False,
                'message': f'ADB verification execution error: {str(e)}',
                'matching_result': 0.0,
                'user_threshold': 0.8,
                'image_filter': 'none',
                'searchedText': search_term if 'search_term' in locals() else '',
                'extractedText': '',
                'search_term': search_term if 'search_term' in locals() else '',
                'wait_time': 0.0,
                'total_matches': 0,
                'matches': [],
                'details': {'error': str(e)}
            }
    