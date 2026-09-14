"""
Playwright Web Controller - Verification Methods

This module contains all verification-related methods for Playwright web controller:
- waitForElementToAppear
- waitForElementToDisappear
- checkElementExists
- waitForTitleToAppear
- getMenuInfo
- execute_verification
- get_available_verifications
"""

import time
import asyncio
from typing import Dict, Any, List, Tuple


# We cannot import ensure_controller_loop here due to circular import
# (playwright.py imports this mixin). Instead, we define it locally.
# The implementation is identical in both files since the decorator
# relies on methods (_ensure_loop, _submit_to_controller_loop) that
# exist on the controller class.
def ensure_controller_loop(func):
    """Ensure async method executes on the controller's dedicated event loop."""
    async def wrapper(self, *args, **kwargs):
        import asyncio
        self._ensure_loop()
        controller_loop = self.__class__._loop
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is controller_loop:
            return await func(self, *args, **kwargs)
        fut = self._submit_to_controller_loop(func(self, *args, **kwargs))
        if current_loop is None:
            return fut.result()
        return await asyncio.wrap_future(fut)
    return wrapper


class PlaywrightVerificationsMixin:
    """Mixin class containing all verification methods for Playwright web controller."""
    
    @ensure_controller_loop
    async def waitForElementToAppear(self, search_term: str, timeout: float = 10.0, check_interval: float = 1.0) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Wait for element to appear (polls find_element with timeout).
        Supports pipe-separated fallback: "Submit|OK|Confirm"
        
        Args:
            search_term: Element text, selector, or aria-label to search for (same as ADB parameter name)
            timeout: Maximum time to wait in seconds
            check_interval: Time between checks in seconds
        """
        print(f"[@controller:Playwright:waitForElementToAppear] Waiting for '{search_term}' (timeout: {timeout}s)")
        
        # Parse pipe-separated terms
        terms = [t.strip() for t in search_term.split('|')] if '|' in search_term else [search_term]
        start_time = time.time()
        
        # For timeout=0, do at least one check (single-shot mode)
        while True:
            elapsed = time.time() - start_time
            remaining_timeout = max(timeout - elapsed, 0.0) if timeout > 0 else None
            if timeout > 0 and remaining_timeout <= 0:
                break

            # Try each term until one succeeds
            for term in terms:
                try:
                    if remaining_timeout is not None:
                        result = await asyncio.wait_for(self.find_element(term), timeout=remaining_timeout)
                    else:
                        result = await self.find_element(term)
                except asyncio.TimeoutError:
                    # Hard timeout reached during a single find operation.
                    elapsed = time.time() - start_time
                    return False, f"Element not found after {elapsed:.1f}s", {
                        'search_term': search_term,
                        'wait_time': elapsed,
                        'timeout_reached': True,
                    }
                if result.get('success'):
                    elapsed = time.time() - start_time
                    return True, f"Element found after {elapsed:.1f}s", {
                        'search_term': search_term,
                        'successful_term': term,
                        'wait_time': elapsed,
                        'element_info': result.get('element_info', {})
                    }
            
            # Check if we should continue polling
            elapsed = time.time() - start_time
            if timeout == 0 or elapsed >= timeout:
                break  # Single check mode or timeout reached
            
            if check_interval > 0:
                sleep_for = min(check_interval, max(timeout - elapsed, 0.0)) if timeout > 0 else check_interval
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            else:
                break  # Single check mode
        
        # Timeout
        elapsed = time.time() - start_time
        return False, f"Element not found after {elapsed:.1f}s", {'search_term': search_term, 'wait_time': elapsed}
    
    @ensure_controller_loop
    async def waitForElementToDisappear(self, search_term: str, timeout: float = 10.0, check_interval: float = 1.0) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Wait for element to disappear (polls find_element until fails).
        
        Args:
            search_term: Element text, selector, or aria-label to search for (same as ADB parameter name)
            timeout: Maximum time to wait in seconds
            check_interval: Time between checks in seconds
        """
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            remaining_timeout = max(timeout - elapsed, 0.0) if timeout > 0 else None
            if timeout > 0 and remaining_timeout <= 0:
                break

            try:
                if remaining_timeout is not None:
                    result = await asyncio.wait_for(self.find_element(search_term), timeout=remaining_timeout)
                else:
                    result = await self.find_element(search_term)
            except asyncio.TimeoutError:
                break
            if not result.get('success'):
                elapsed = time.time() - start_time
                return True, f"Element disappeared after {elapsed:.1f}s", {'search_term': search_term, 'wait_time': elapsed}
            
            if check_interval > 0:
                sleep_for = min(check_interval, max(timeout - elapsed, 0.0)) if timeout > 0 else check_interval
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            else:
                break
        
        elapsed = time.time() - start_time
        return False, f"Element still present after {elapsed:.1f}s", {'search_term': search_term, 'wait_time': elapsed}
    
    @ensure_controller_loop
    async def checkElementExists(self, search_term: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check if element exists (single find_element call, no polling).
        
        Args:
            search_term: Element text, selector, or aria-label to search for (same as ADB parameter name)
        """
        result = await self.find_element(search_term)
        if result.get('success'):
            return True, f"Element '{search_term}' exists", {'search_term': search_term, 'element_info': result.get('element_info', {})}
        else:
            return False, f"Element '{search_term}' not found", {'search_term': search_term, 'error': result.get('error', '')}

    @ensure_controller_loop
    async def waitForTitleToAppear(self, title: str, timeout: float = 10.0, check_interval: float = 1.0) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Wait for document.title to contain the expected string (case-insensitive).
        Polls page.title() with timeout — lighter than element search for confirming page loads.

        Args:
            title: Expected text that should appear in the page title
            timeout: Maximum time to wait in seconds
            check_interval: Time between checks in seconds
        """
        print(f"[@controller:Playwright:waitForTitleToAppear] Waiting for title containing '{title}' (timeout: {timeout}s)")

        start_time = time.time()
        title_lower = title.lower()

        async def _read_title_once() -> str:
            page = await self._get_persistent_page()
            if not page:
                return ''
            return await page.title()

        while True:
            elapsed = time.time() - start_time
            remaining_timeout = max(timeout - elapsed, 0.0) if timeout > 0 else None
            if timeout > 0 and remaining_timeout <= 0:
                break

            try:
                if remaining_timeout is not None:
                    current_title = await asyncio.wait_for(_read_title_once(), timeout=remaining_timeout)
                else:
                    current_title = await _read_title_once()
                if current_title and title_lower in current_title.lower():
                    elapsed = time.time() - start_time
                    return True, f"Title matched after {elapsed:.1f}s", {
                        'title': title,
                        'current_title': current_title,
                        'wait_time': elapsed
                    }
            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"[@controller:Playwright:waitForTitleToAppear] Error reading title: {e}")

            elapsed = time.time() - start_time
            if timeout == 0 or elapsed >= timeout:
                break

            if check_interval > 0:
                sleep_for = min(check_interval, max(timeout - elapsed, 0.0)) if timeout > 0 else check_interval
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            else:
                break

        # Timeout — report last seen title
        last_title = ''
        try:
            page = await self._get_persistent_page()
            if page:
                last_title = await page.title()
        except Exception:
            pass

        elapsed = time.time() - start_time
        return False, f"Title '{title}' not found after {elapsed:.1f}s (current: '{last_title}')", {
            'title': title,
            'current_title': last_title,
            'wait_time': elapsed
        }

    @ensure_controller_loop
    async def getMenuInfo(self, area: dict = None, context = None) -> Dict[str, Any]:
        """
        Extract menu info from web elements (Playwright-based alternative to OCR getMenuInfo)
        Same interface as text.getMenuInfo but uses dump_elements instead of OCR
        
        Args:
            area: Optional area to filter elements (x, y, width, height)
            context: Execution context for metadata storage
            
        Returns:
            Same format as text.getMenuInfo:
            {
                success: bool,
                output_data: {
                    parsed_data: dict,
                    raw_output: str
                },
                message: str
            }
        """
        print(f"[@controller:PlaywrightWeb:getMenuInfo] Params: area={area}, context={context is not None}")
        
        try:
            # 1. Dump web elements (already exists)
            print(f"[@controller:PlaywrightWeb:getMenuInfo] Dumping web elements...")
            dump_result = await self.dump_elements(element_types='all', include_hidden=False)
            
            if not dump_result.get('success'):
                error = dump_result.get('error', 'Unknown error')
                print(f"[@controller:PlaywrightWeb:getMenuInfo] FAIL: Element dump failed: {error}")
                return {
                    'success': False,
                    'output_data': {},
                    'message': f'Failed to dump elements: {error}'
                }
            
            elements = dump_result.get('elements', [])
            print(f"[@controller:PlaywrightWeb:getMenuInfo] Dumped {len(elements)} web elements")
            
            # 2. Filter by area if specified
            filtered_elements = elements
            if area:
                filtered_elements = []
                for elem in elements:
                    pos = elem.get('position', {})
                    elem_x = pos.get('x', 0)
                    elem_y = pos.get('y', 0)
                    elem_width = pos.get('width', 0)
                    elem_height = pos.get('height', 0)
                    
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
                
                print(f"[@controller:PlaywrightWeb:getMenuInfo] Filtered to {len(filtered_elements)} elements in area")
            
            # 3. Parse key-value pairs from element text
            parsed_data = {}
            for elem in filtered_elements:
                text = elem.get('textContent', '').strip()
                
                # Skip empty text
                if not text or len(text) < 2:
                    continue
                
                # Parse key-value pairs
                # Pattern 1: "Key: Value" (colon separator)
                if ':' in text and len(text) < 100:  # Reasonable length for key-value
                    parts = text.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().replace(' ', '_').replace('-', '_')
                        value = parts[1].strip()
                        if key and value:  # Both must be non-empty
                            parsed_data[key] = value
                            print(f"  • {key} = {value}")
                
                # Pattern 2: "Key\nValue" (newline separator)
                elif '\n' in text:
                    lines = text.split('\n')
                    if len(lines) >= 2:
                        key = lines[0].strip().replace(' ', '_').replace('-', '_')
                        value = '\n'.join(lines[1:]).strip()
                        if key and value:  # Both must be non-empty
                            parsed_data[key] = value
                            print(f"  • {key} = {value}")
            
            print(f"[@controller:PlaywrightWeb:getMenuInfo] Parsed {len(parsed_data)} key-value pairs")
            
            if not parsed_data:
                print(f"[@controller:PlaywrightWeb:getMenuInfo] WARNING: No key-value pairs found in web elements")
            
            # 4. Auto-store to context.metadata (same as OCR version)
            if context:
                from datetime import datetime
                
                # Initialize metadata if not exists
                if not hasattr(context, 'metadata'):
                    context.metadata = {}
                
                # Append parsed data directly to metadata (flat structure)
                for key, value in parsed_data.items():
                    context.metadata[key] = value
                
                # Add extraction metadata
                context.metadata['extraction_method'] = 'web_elements'
                context.metadata['extraction_timestamp'] = datetime.now().isoformat()
                context.metadata['element_count'] = len(filtered_elements)
                
                # Add page info
                summary = dump_result.get('summary', {})
                context.metadata['page_title'] = summary.get('page_title', '')
                context.metadata['page_url'] = summary.get('page_url', '')
                
                if area:
                    context.metadata['extraction_area'] = str(area)
                
                print(f"[@controller:PlaywrightWeb:getMenuInfo] ✅ AUTO-APPENDED to context.metadata (FLAT)")
                print(f"[@controller:PlaywrightWeb:getMenuInfo] Metadata keys: {list(context.metadata.keys())}")
                print(f"[@controller:PlaywrightWeb:getMenuInfo] New fields added: {list(parsed_data.keys())}")
            else:
                print(f"[@controller:PlaywrightWeb:getMenuInfo] WARNING: No context provided, metadata not stored")
            
            # 5. Prepare output data with FULL raw dump for debugging
            raw_dump = []
            for elem in filtered_elements:
                raw_dump.append({
                    'index': elem.get('index'),
                    'tagName': elem.get('tagName'),
                    'selector': elem.get('selector'),
                    'textContent': elem.get('textContent'),
                    'className': elem.get('className'),
                    'id': elem.get('id'),
                    'attributes': elem.get('attributes', {}),
                    'position': elem.get('position', {}),
                    'isVisible': elem.get('isVisible'),
                    'aria-label': elem.get('attributes', {}).get('aria-label'),
                    'role': elem.get('attributes', {}).get('role'),
                    'href': elem.get('attributes', {}).get('href'),
                    'title': elem.get('attributes', {}).get('title')
                })
            
            output_data = {
                'parsed_data': parsed_data,
                'raw_dump': raw_dump,  # Full structured dump for debugging
                'element_count': len(filtered_elements)
            }
            
            print(f"[@controller:PlaywrightWeb:getMenuInfo] 📤 RETURNING output_data with {len(parsed_data)} parsed_data entries")
            print(f"[@controller:PlaywrightWeb:getMenuInfo] 📤 output_data keys: {list(output_data.keys())}")
            
            # 6. Return same format as text.getMenuInfo
            message = f'Parsed {len(parsed_data)} fields from {len(filtered_elements)} web elements'
            
            print(f"[@controller:PlaywrightWeb:getMenuInfo] ✅ SUCCESS: {message}")
            
            return {
                'success': True,
                'output_data': output_data,
                'message': message
            }
            
        except Exception as e:
            error_msg = f"Error extracting menu info from web elements: {str(e)}"
            print(f"[@controller:PlaywrightWeb:getMenuInfo] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            
            return {
                'success': False,
                'output_data': {},
                'message': error_msg
            }
    
    def get_available_verifications(self) -> List[Dict[str, Any]]:
        """Get available verifications for Playwright with typed parameters - ALL verifications combined."""
        from shared.src.lib.schemas.param_types import create_param, create_output, ParamType, OutputType
        
        return [
            {
                'command': 'waitForElementToAppear',
                'label': 'Wait for Element to Appear',
                'description': 'Wait for web element to appear (by text, selector, or aria-label)',
                'params': {
                    'search_term': create_param(
                        ParamType.STRING,
                        required=True,
                        default='',
                        description="Element search term (text, selector, aria-label)",
                        placeholder="Enter element identifier"
                    ),
                    'timeout': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10.0,
                        description="Maximum time to wait (seconds)"
                    ),
                    'check_interval': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=1.0,
                        description="Interval between checks (seconds)",
                        min=0.1,
                        max=10.0
                    )
                },
                'verification_type': 'web'
            },
            {
                'command': 'waitForElementToDisappear',
                'label': 'Wait for Element to Disappear',
                'description': 'Wait for web element to disappear',
                'params': {
                    'search_term': create_param(
                        ParamType.STRING,
                        required=True,
                        default='',
                        description="Element search term (text, selector, aria-label)",
                        placeholder="Enter element identifier"
                    ),
                    'timeout': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10.0,
                        description="Maximum time to wait (seconds)"
                    ),
                    'check_interval': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=1.0,
                        description="Interval between checks (seconds)",
                        min=0.1,
                        max=10.0
                    )
                },
                'verification_type': 'web'
            },
            {
                'command': 'waitForTitleToAppear',
                'label': 'Wait for Page Title',
                'description': 'Wait for document.title to contain expected text (case-insensitive)',
                'params': {
                    'title': create_param(
                        ParamType.STRING,
                        required=True,
                        default='',
                        description="Expected text in page title (case-insensitive match)",
                        placeholder="Enter expected page title"
                    ),
                    'timeout': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10.0,
                        description="Maximum time to wait (seconds)"
                    ),
                    'check_interval': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=1.0,
                        description="Interval between checks (seconds)",
                        min=0.1,
                        max=10.0
                    )
                },
                'verification_type': 'web'
            },
            {
                "command": "getMenuInfo",
                "label": "Get Menu Info Web",
                "description": "Extract key-value pairs from menu/info screen using web element dump and parse automatically",
                "params": {
                    "area": create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Screen area to extract menu information from"
                    )
                },
                "outputs": [
                    create_output(
                        "parsed_data",
                        OutputType.OBJECT,
                        description="Parsed key-value pairs from web elements"
                    ),
                    create_output(
                        "raw_dump",
                        OutputType.ARRAY,
                        description="Full raw web element dump for debugging"
                    ),
                    create_output(
                        "element_count",
                        OutputType.NUMBER,
                        description="Number of web elements extracted"
                    )
                ],
                "verification_type": "web"
            }
        ]
    
    @ensure_controller_loop
    async def execute_verification(self, verification_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute verification and return frontend-expected format (consistent with ADB/image/text).
        Handles ALL verification commands: getMenuInfo, waitForElementToAppear, waitForElementToDisappear, waitForTitleToAppear.
        
        Args:
            verification_config: {
                'command': 'waitForElementToAppear' | 'waitForTitleToAppear' | 'getMenuInfo',
                'params': {...},
                'context': ...
            }
            
        Returns:
            Frontend-expected format matching ADB verification
        """
        try:
            # Extract parameters
            params = verification_config.get('params', {})
            command = verification_config.get('command', 'waitForElementToAppear')
            context = verification_config.get('context')
            
            print(f"[@controller:PlaywrightWeb:execute_verification] Executing {command}")
            
            # Handle getMenuInfo separately (different params and return format)
            if command == 'getMenuInfo':
                area = params.get('area')
                result = await self.getMenuInfo(area=area, context=context)
                return result

            # Handle waitForTitleToAppear separately (uses 'title' param, not 'search_term')
            if command == 'waitForTitleToAppear':
                title = params.get('title', '')
                if not title:
                    return {
                        'success': False,
                        'message': 'No title specified for waitForTitleToAppear',
                        'matching_result': 0.0,
                        'user_threshold': 0.8,
                        'image_filter': 'none',
                        'searchedText': '',
                        'extractedText': '',
                        'details': {'error': 'Missing title parameter'}
                    }
                timeout = float(params.get('timeout', 10.0))
                check_interval = float(params.get('check_interval', 1.0))
                if timeout < 0:
                    timeout = 0.0
                if timeout > 60:
                    timeout = 60.0
                if check_interval <= 0:
                    check_interval = 0.0
                elif check_interval < 0.1:
                    check_interval = 0.1
                elif check_interval > 10.0:
                    check_interval = 10.0

                print(f"[@controller:PlaywrightWeb] Executing waitForTitleToAppear with title: '{title}'")
                success, message, details = await self.waitForTitleToAppear(
                    title=title,
                    timeout=timeout,
                    check_interval=check_interval
                )
                return {
                    'success': success,
                    'message': message,
                    'matching_result': 1.0 if success else 0.0,
                    'user_threshold': 0.8,
                    'image_filter': 'none',
                    'searchedText': title,
                    'extractedText': details.get('current_title', ''),
                    'search_term': title,
                    'wait_time': details.get('wait_time', 0.0),
                    'details': details
                }

            # Handle wait commands (require search_term)
            search_term = params.get('search_term', '')
            if not search_term:
                return {
                    'success': False,
                    'message': 'No search term specified for web verification',
                    'matching_result': 0.0,
                    'user_threshold': 0.8,
                    'image_filter': 'none',
                    'searchedText': search_term,
                    'extractedText': '',
                    'details': {'error': 'Missing search_term parameter'}
                }
            
            # Optional parameters with defaults (SECONDS)
            # Align units with other controllers (Text/Image/ADB use seconds)
            timeout = float(params.get('timeout', 10.0))
            check_interval = float(params.get('check_interval', 1.0))

            # Normalize bounds
            if timeout < 0:
                timeout = 0.0
            if timeout > 60:
                print(f"[@controller:PlaywrightWeb] WARNING: Large timeout value {timeout}s detected, capping at 60s")
                timeout = 60.0
            # Allow 0 for single-shot; otherwise clamp to [0.1, 10]
            if check_interval <= 0:
                check_interval = 0.0
            else:
                if check_interval < 0.1:
                    check_interval = 0.1
                if check_interval > 10.0:
                    check_interval = 10.0
            
            print(f"[@controller:PlaywrightWeb] Executing {command} with search term: '{search_term}'")
            print(f"[@controller:PlaywrightWeb] Parameters: timeout={timeout}, check_interval={check_interval}")
            
            # Execute verification based on command
            if command == 'waitForElementToAppear':
                success, message, details = await self.waitForElementToAppear(
                    search_term=search_term,
                    timeout=timeout,
                    check_interval=check_interval
                )
            elif command == 'waitForElementToDisappear':
                success, message, details = await self.waitForElementToDisappear(
                    search_term=search_term,
                    timeout=timeout,
                    check_interval=check_interval
                )
            else:
                return {
                    'success': False,
                    'message': f'Unknown web verification command: {command}',
                    'matching_result': 0.0,
                    'user_threshold': 0.8,
                    'image_filter': 'none',
                    'searchedText': search_term,
                    'extractedText': '',
                    'details': {'error': f'Unsupported command: {command}'}
                }
            
            # Return frontend-expected format (consistent with ADB verification)
            response = {
                'success': success,
                'message': message,
                'matching_result': 1.0 if success else 0.0,  # Binary for web (found/not found)
                'user_threshold': 0.8,                       # Default for consistency
                'image_filter': 'none',                      # Not applicable for web
                'searchedText': search_term,                 # What we searched for
                'extractedText': message,                    # Verification result message
                
                # Web-specific properties for frontend compatibility
                'search_term': search_term,                  # Frontend expects this
                'wait_time': details.get('wait_time', 0.0),  # Frontend expects this
                
                'details': details  # Keep for route processing, will be removed by route
            }
            
            return response
            
        except Exception as e:
            print(f"[@controller:PlaywrightWeb] Execution error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Web verification execution error: {str(e)}',
                'matching_result': 0.0,
                'user_threshold': 0.8,
                'image_filter': 'none',
                'searchedText': params.get('search_term', '') if 'params' in locals() else '',
                'extractedText': '',
                'details': {'error': str(e)}
            }
