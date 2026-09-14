"""
Screen Analyzer - AI vision analysis using VideoAIHelpers
Analyzes screenshots to understand menu structure and detect screen changes
"""

from typing import Dict, Optional
import json


class ScreenAnalyzer:
    """AI vision analysis using existing VideoAIHelpers"""
    
    def __init__(self, device, controller=None, ai_model: str = 'qwen'):
        """
        Initialize with device context
        
        Args:
            device: Device instance (from ExplorationEngine)
            controller: Remote controller instance (for android_mobile native screenshots)
            ai_model: 'qwen' (default), later: user-selectable
        """
        self.device = device
        self.device_id = device.device_id
        self.host_name = device.host_name
        self.device_model_name = device.device_model
        self.controller = controller
        self.ai_model = ai_model
        
    def anticipate_tree(self, screenshot_path: str = None) -> Dict:
        """
        Phase 1: Analyze first screenshot and identify all interactive elements
        
        For mobile/web: Use UI dump to extract interactive elements (screenshot optional)
        For TV/STB: Use AI vision to identify menu items (screenshot required)
        
        Args:
            screenshot_path: Path to screenshot image (optional for mobile/web)
            
        Returns:
            {
                'menu_type': 'horizontal',
                'items': ['home', 'settings', 'profile'],
                'lines': [['home', 'settings'], ['profile']],
                'predicted_depth': 2,
                'strategy': 'click_elements' or 'test_dpad_directions'
            }
        """
        # Determine if device uses click (mobile/web) or DPAD (TV/STB)
        # ✅ FIX: Include 'host' in detection (host = web browser)
        is_mobile_or_web = self.device_model_name and (
            'mobile' in self.device_model_name.lower() or 
            'web' in self.device_model_name.lower() or 
            'host' in self.device_model_name.lower()
        )
        
        print(f"\n{'='*80}")
        print(f"[@screen_analyzer:anticipate_tree] PHASE 1 ANALYSIS")
        print(f"{'='*80}")
        print(f"📸 Screenshot Path: {screenshot_path or 'None (not required for dump-based analysis)'}")
        print(f"🎮 Device Type: {'MOBILE/WEB (dump-based)' if is_mobile_or_web else 'TV/STB (AI vision-based)'}")
        print(f"📱 Device Model: {self.device_model_name}")
        
        if is_mobile_or_web:
            # Use UI dump for mobile/web (screenshot not needed)
            try:
                return self._analyze_from_dump(screenshot_path)
            except Exception as e:
                print(f"❌ [@screen_analyzer:anticipate_tree] DUMP ANALYSIS FAILED")
                print(f"   Device: {self.device_model_name}")
                print(f"   Error: {e}")
                import traceback
                traceback.print_exc()
                # ❌ DO NOT SILENTLY FALL BACK - re-raise the error
                raise Exception(f"UI dump analysis failed for {self.device_model_name}: {e}")
        else:
            # Use AI vision for TV/STB (screenshot required)
            if not screenshot_path:
                # Fallback for TV/STB without screenshot
                print(f"  ⚠️ No screenshot available for TV/STB device - using basic fallback")
                return {
                    'menu_type': 'horizontal',
                    'items': ['search', 'home', 'settings', 'profile'],  # Generic fallback
                    'lines': [['search', 'home', 'settings', 'profile']],
                    'predicted_depth': 1,
                    'strategy': 'test_dpad_directions',
                    'item_selectors': {}
                }
            try:
                return self._analyze_from_ai_vision(screenshot_path)
            except Exception as e:
                print(f"❌ [@screen_analyzer:anticipate_tree] AI VISION ANALYSIS FAILED")
                print(f"   Device: {self.device_model_name}")
                print(f"   Screenshot: {screenshot_path}")
                print(f"   Error: {e}")
                import traceback
                traceback.print_exc()
                raise Exception(f"AI vision analysis failed for {self.device_model_name}: {e}")
    
    def _analyze_from_dump(self, screenshot_path: str) -> Dict:
        """
        Extract interactive elements from UI dump (mobile/web only)
        Fails fast if dump is not available - no fallback
        """
        print(f"\n📱 USING UI DUMP ANALYSIS")
        print(f"{'-'*80}")
        
        # Both mobile and web now use unified dump_elements()
        print(f"[@screen_analyzer] Using unified dump_elements() method")
        print(f"[@screen_analyzer] Device model: {self.device_model_name}")
        print(f"[@screen_analyzer] Controller type: {type(self.controller).__name__}")
        
        # Try calling dump_elements - signature varies by controller type
        # ✅ Handle both sync (mobile) and async (web) controllers
        try:
            result = self.controller.dump_elements()
            print(f"[@screen_analyzer] dump_elements() returned type: {type(result)}")
            
            # ✅ Check if result is a coroutine (async method)
            import inspect
            if inspect.iscoroutine(result):
                print(f"[@screen_analyzer] Detected async method - using existing event loop")
                import asyncio
                try:
                    # Try to get the running loop (Playwright's controller loop)
                    loop = asyncio.get_running_loop()
                    print(f"[@screen_analyzer] Using running loop: {loop}")
                    # We're already in an async context - this shouldn't happen
                    # But if it does, we need to schedule it differently
                    raise RuntimeError("Cannot use asyncio.run() from within async context")
                except RuntimeError:
                    # Not in async context OR need to use existing loop
                    # Get the controller's loop and submit the coroutine
                    if hasattr(self.controller, '_submit_to_controller_loop'):
                        print(f"[@screen_analyzer] Submitting to controller loop")
                        future = self.controller._submit_to_controller_loop(result)
                        result = future.result()  # Block until complete
                        print(f"[@screen_analyzer] Controller loop result type: {type(result)}")
                    else:
                        # Fallback to asyncio.run (may cause issues but better than crashing)
                        print(f"[@screen_analyzer] Fallback to asyncio.run()")
                        result = asyncio.run(result)
                        print(f"[@screen_analyzer] Async result type: {type(result)}")
            
        except Exception as e:
            print(f"❌ [@screen_analyzer:_analyze_from_dump] dump_elements() FAILED")
            print(f"   Controller: {type(self.controller).__name__}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            raise Exception(f"dump_elements() call failed: {e}")
        
        # Handle different return types
        if isinstance(result, dict):
            # Web returns dict: {success: bool, elements: list, ...}
            print(f"[@screen_analyzer] Web format detected - keys: {result.keys()}")
            
            if not result.get('success'):
                error = result.get('error', 'Unknown error')
                print(f"❌ [@screen_analyzer:_analyze_from_dump] UI dump indicated failure")
                print(f"   Success: {result.get('success')}")
                print(f"   Error: {error}")
                print(f"   Full result: {result}")
                raise Exception(f"Failed to get UI dump - cannot proceed: {error}")
            
            elements = result.get('elements', [])
            print(f"[@screen_analyzer] Elements retrieved: {len(elements)}")
            
            # Debug: Log full raw dump for exploration debugging
            print(f"\n{'='*80}")
            print(f"[@screen_analyzer:DEBUG] FULL RAW DUMP ({len(elements)} elements)")
            print(f"{'='*80}")
            for i, elem in enumerate(elements, 1):
                # Clean textContent for logging (remove newlines, truncate)
                text_raw = elem.get('textContent', '')
                text_clean = ' '.join(text_raw.split())[:100]  # Remove all whitespace, first 100 chars
                
                print(f"[Element {i}/{len(elements)}] tag={elem.get('tagName')} id={elem.get('id')} selector={elem.get('selector')} text='{text_clean}' class='{elem.get('className', '')[:50]}' visible={elem.get('isVisible')}")
            print(f"{'='*80}\n")
            
            if not elements:
                print(f"❌ [@screen_analyzer:_analyze_from_dump] No elements in dump")
                print(f"   Result: {result}")
                raise Exception("No elements found in UI dump")
            
            # Parse web elements (dict format)
            print(f"[@screen_analyzer] Parsing web elements...")
            interactive_elements = self._extract_interactive_elements_web(elements)
        else:
            # Mobile returns tuple: (success, elements, error)
            print(f"[@screen_analyzer] Mobile format detected - tuple with {len(result)} items")
            success, elements, error = result
            print(f"[@screen_analyzer] Success: {success}, Elements: {len(elements) if elements else 0}, Error: {error}")
            
            if not success:
                print(f"❌ [@screen_analyzer:_analyze_from_dump] Mobile dump failed")
                print(f"   Success: {success}")
                print(f"   Error: {error}")
                print(f"   Elements: {elements}")
                raise Exception(f"Failed to get UI dump - cannot proceed: {error}")
            
            # Parse mobile elements (AndroidElement objects)
            print(f"[@screen_analyzer] Parsing mobile elements...")
            interactive_elements = self._extract_interactive_elements_mobile(elements)
        
        if not interactive_elements:
            print(f"⚠️  [@screen_analyzer:_analyze_from_dump] No interactive elements after parsing")
            print(f"   Raw element count: {len(elements)}")
            print(f"   This may indicate:")
            print(f"   - Flutter app without activated semantics")
            print(f"   - Page still loading")
            print(f"   - Dynamic content not yet rendered")
            
            # Return empty result instead of raising exception
            # Let the caller (exploration engine) handle this gracefully
            return {
                'menu_type': 'click_based',
                'items': [],
                'lines': [],
                'predicted_depth': 0,
                'strategy': 'click_elements',
                'error': 'No interactive elements found in UI dump',
                'suggestion': 'Check if page is fully loaded or if Flutter semantics need manual activation'
            }
        
        print(f"✅ EXTRACTED FROM DUMP:")
        print(f"{'-'*80}")
        print(f"Items ({len(interactive_elements)}):")
        print(f"Elements: {', '.join(interactive_elements)}")
        print(f"{'-'*80}\n")
        
        return {
            'menu_type': 'click_based',  # Mobile/web = click-based, no line structure
            'items': interactive_elements,
            'lines': [],  # No lines for click-based navigation
            'predicted_depth': 2,
            'strategy': 'click_elements'
        }
    
    def _extract_interactive_elements_mobile(self, elements: list) -> list:
        """
        Parse mobile UI dump elements (AndroidElement objects)
        Extract both static navigation + dynamic content
        
        Args:
            elements: List of AndroidElement objects from dump_elements()
        
        Returns:
            List of element names (strings)
        """
        interactive_elements = []
        
        # Filter out common non-interactive text
        ignore_keywords = ['image', 'icon', 'loading', 'placeholder', '...', 'content', 'decoration', 'logo', 'home', 'accueil']
        
        # UI accessibility hints to strip (before dynamic content detection)
        # ONLY strip instructions/state, NOT element types (Tab, Button, etc.)
        accessibility_patterns = [
            ', Double-tap to Open',
            ', Double-tap to activate',
            ', Double-tap to select',
            ' currently selected',
        ]
        
        # Dynamic content indicators (program titles, prices, descriptions)
        dynamic_indicators = [
            'available for replay',
            'chf', 'usd', 'eur', 'gbp', '$', '€', '£',  # Price indicators
            ' - ',  # Time ranges like "21:10 - 23:10"
            ' from ', ' to ',  # Alternate time/price ranges
            'season ', 'episode ', 's0', 'e0',  # TV series
            'podcast ',  # Podcast titles
            ','  # Titles often have commas (e.g., "Show Name, Description")
        ]
        
        # Navigation keywords that should NOT be filtered (even if they match above)
        # These are common navigation tab names that we MUST keep
        navigation_whitelist = ['replay', 'radio', 'guide', 'tv', 'home', 'search', 'settings', 'accueil']
        
        # UI element type keywords (multilingual) - elements containing these get more lenient filtering
        # These indicate proper UI elements, not dynamic content
        ui_element_keywords = [
            'button', 'btn', 'bouton',  # Button (EN, abbrev, FR)
            'tab', 'onglet',  # Tab (EN, FR)
            'selected', 'sélectionné', 'seleccionado',  # Selected (EN, FR, ES)
            'menu', 'menü',  # Menu (EN, DE)
            'switch', 'toggle',  # Toggle switches
            'checkbox', 'radio',  # Form controls
        ]
        
        for elem in elements:
            # ✅ FIX: Don't require clickable=true
            # TextViews in navigation bars (bottom tabs, top tabs) are NOT marked clickable
            # but they ARE navigation elements. We'll filter by content instead.
            # Only skip if it's a container or decoration (checked via keywords)
            
            # Get the best label for this element
            label = None
            
            # Priority 1: text
            if elem.text and elem.text != '<no text>' and elem.text.strip():
                label = elem.text.strip()
            # Priority 2: content_desc
            elif elem.content_desc and elem.content_desc != '<no content-desc>' and elem.content_desc.strip():
                label = elem.content_desc.strip()
            # Priority 3: resource_id (extract last part after /)
            elif elem.resource_id and elem.resource_id != '<no resource-id>' and elem.resource_id.strip():
                # Extract meaningful part from resource ID like "com.example:id/button_name"
                resource_id = elem.resource_id.strip()
                if '/' in resource_id:
                    label = resource_id.split('/')[-1]
                else:
                    label = resource_id
            
            # Skip if no useful label
            if not label:
                continue
            
            # Filter out number-only elements and number-percentage elements
            import re
            # Filter pure numbers (any length) and numbers with percentage signs
            if re.match(r'^\d+$', label) or re.match(r'^\d+%$', label):
                print(f"[@screen_analyzer:_extract_interactive_elements_mobile] 🚫 FILTERED: Number/Percentage | label='{label}' | elem.id={elem.id}")
                continue
            
            # Filter out non-interactive keywords
            if any(keyword in label.lower() for keyword in ignore_keywords):
                continue
            
            # ✅ CLEAN: Strip accessibility hints BEFORE dynamic content detection
            original_label = label
            for pattern in accessibility_patterns:
                if pattern.lower() in label.lower():
                    # Case-insensitive removal
                    import re
                    label = re.sub(re.escape(pattern), '', label, flags=re.IGNORECASE).strip()
            
            # Clean up extra commas/spaces after stripping
            label = label.rstrip(',').strip()
            
            # Skip if label became empty after cleaning
            if not label:
                continue
            
            # ✅ Detect and SKIP dynamic content (AFTER cleaning accessibility text)
            # 1. Very long labels (> 30 chars) = likely program description
            # 2. Contains time patterns or content indicators
            # BUT: Don't skip common navigation keywords even if they match
            
            # Check if it's a navigation keyword (whitelist)
            is_navigation = any(nav.lower() == label.lower() for nav in navigation_whitelist)
            
            # Check if label contains UI element type keywords (more lenient filtering)
            contains_ui_keyword = any(keyword in label.lower() for keyword in ui_element_keywords)
            
            # Determine length threshold based on whether it's a UI element
            if contains_ui_keyword:
                length_threshold = 40  # More lenient for UI elements with metadata
                print(f"[@screen_analyzer:_extract_interactive_elements_mobile] 🏷️  UI element detected: '{label}' | using threshold={length_threshold}")
            else:
                length_threshold = 30  # Standard threshold for other elements
            
            if not is_navigation:
                # Not a whitelisted navigation keyword, apply dynamic content filter
                if len(label) > length_threshold or any(indicator in label.lower() for indicator in dynamic_indicators):
                    print(f"[@screen_analyzer:_extract_interactive_elements_mobile] 🚫 FILTERED: Dynamic content | label='{label}' | len={len(label)} | threshold={length_threshold} | elem.id={elem.id}")
                    continue  # Skip dynamic content
            
            # Add to list (avoid duplicates)
            if label not in interactive_elements:
                interactive_elements.append(label)
                print(f"[@screen_analyzer:_extract_interactive_elements_mobile] ✅ KEPT: '{label}' | elem.id={elem.id} | clickable={elem.clickable}")
            else:
                print(f"[@screen_analyzer:_extract_interactive_elements_mobile] 🔁 DUPLICATE: '{label}' | elem.id={elem.id}")
        
        return interactive_elements[:20]  # Limit to top 20 elements
    
    def _extract_interactive_elements_web(self, elements: list) -> list:
        """
        Parse web UI dump elements (dict objects from Playwright)
        Extract NAVIGATION targets only - filter out layout, external links, and grouped components
        
        Args:
            elements: List of dict objects from dump_elements()
                     Each dict has: text, tag, selector, visible, clickable, etc.
        
        Returns:
            List of element names (strings) - navigation targets only
        """
        interactive_elements = []
        seen_selectors = set()  # Track duplicates
        
        # ═══════════════════════════════════════════════════════════════
        # FILTER PATTERNS
        # ═══════════════════════════════════════════════════════════════
        
        # Layout containers (structural, not clickable destinations)
        layout_keywords = [
            'container', 'wrapper', 'columns', 'row', 'grid', 'sidebar',
            'header', 'footer', 'upper', 'lower', 'table-cell', 'layout',
            'section', 'main', 'content', 'aside', 'nav'  # nav is container, not link
        ]
        
        # Non-interactive decorations
        decoration_keywords = [
            'image', 'icon', 'loading', 'placeholder', 'decoration', 
            'logo', 'banner', 'badge', 'divider', 'spacer', 'tagline',
            'slogan', 'motto', 'caption'
        ]
        
        # External/social links (navigate AWAY from app)
        external_keywords = [
            'social', 'facebook', 'twitter', 'instagram', 'youtube',
            'linkedin', 'pinterest', 'tiktok', 'share', 'external',
            'rss', 'feed', 'subscribe', 'newsletter'
        ]
        
        # ═══════════════════════════════════════════════════════════════
        # PASS 1: Build map of container relationships
        # ═══════════════════════════════════════════════════════════════
        # Track which containers have interactive children to skip them later
        containers_with_children = set()
        
        for elem in elements:
            tag = elem.get('tagName', '').lower()
            selector = elem.get('selector', '')
            
            # If this is an interactive element (a, button, input[type=submit])
            if tag == 'a' or tag == 'button' or (tag == 'input' and elem.get('attributes', {}).get('type') == 'submit'):
                # Mark potential parent containers as "has interactive children"
                # Simple heuristic: any div/span with similar position is likely a container
                elem_pos = elem.get('position', {})
                for potential_container in elements:
                    container_tag = potential_container.get('tagName', '').lower()
                    if container_tag in ['div', 'span']:
                        container_pos = potential_container.get('position', {})
                        # If container fully contains this interactive element
                        if (container_pos.get('x', 0) <= elem_pos.get('x', 0) and
                            container_pos.get('y', 0) <= elem_pos.get('y', 0) and
                            container_pos.get('x', 0) + container_pos.get('width', 0) >= elem_pos.get('x', 0) + elem_pos.get('width', 0) and
                            container_pos.get('y', 0) + container_pos.get('height', 0) >= elem_pos.get('y', 0) + elem_pos.get('height', 0)):
                            containers_with_children.add(potential_container.get('selector', ''))
        
        print(f"[@screen_analyzer:_extract_web] 🗂️  Identified {len(containers_with_children)} containers with interactive children (will skip)")
        
        # ═══════════════════════════════════════════════════════════════
        # PASS 2: Extract navigation targets with filtering
        # ═══════════════════════════════════════════════════════════════
        
        for elem in elements:
            selector = elem.get('selector', '') or elem.get('id', '')
            if not selector:
                continue
            
            tag = elem.get('tagName', '').lower()
            
            # ═══════════════════════════════════════════════════════════════
            # FILTER: Skip containers that have interactive children
            # ═══════════════════════════════════════════════════════════════
            if selector in containers_with_children:
                print(f"[@screen_analyzer:_extract_web] Filtered CONTAINER WITH CHILDREN: {selector}")
                continue
            
            # ═══════════════════════════════════════════════════════════════
            # FILTER: Skip non-interactive containers (div/span without href)
            # ═══════════════════════════════════════════════════════════════
            if tag in ['div', 'span']:
                # Only keep if it has special interactive attributes
                attributes = elem.get('attributes', {})
                if not (attributes.get('onclick') or attributes.get('role') == 'button'):
                    print(f"[@screen_analyzer:_extract_web] Filtered NON-INTERACTIVE CONTAINER: {selector}")
                    continue
        
            # ═══════════════════════════════════════════════════════════════
            # FILTER: Skip text input fields (not navigation targets)
            # ═══════════════════════════════════════════════════════════════
            if tag == 'input':
                input_type = elem.get('attributes', {}).get('type', 'text')
                if input_type in ['text', 'email', 'password', 'number', 'tel', 'url']:
                    print(f"[@screen_analyzer:_extract_web] Filtered TEXT INPUT: {selector}")
                    continue
                # Keep submit buttons and other clickable inputs
            
            # ═══════════════════════════════════════════════════════════════
            # SMART DUPLICATE CHECK
            # ═══════════════════════════════════════════════════════════════
            # Generic selectors (a, div, button) are not unique.
            # Use text+href as the uniqueness key for generic selectors.
            # For specific selectors (#id, .class), the selector itself is unique enough.
            
            text_content = elem.get('textContent', '').strip()
            attributes = elem.get('attributes', {})
            href = attributes.get('href', '')
            
            # Generic selectors (single tag name without #id or .class)
            is_generic = not ('#' in selector or '.' in selector or ':' in selector)
            
            if is_generic:
                # Use text+href as uniqueness key for generic selectors
                unique_key = f"{selector}|{text_content}|{href}"
            else:
                # Use selector for specific ones
                unique_key = selector
            
            # Skip duplicates
            if unique_key in seen_selectors:
                continue
            
            seen_selectors.add(unique_key)
            
            # ═══════════════════════════════════════════════════════════════
            # PRIORITY FILTER: Navigation elements need (ID OR text) AND href
            # ═══════════════════════════════════════════════════════════════
            
            tag = elem.get('tagName', '').lower()
            element_id = elem.get('id', '') or ''  # Handle None
            
            # Detect Flutter semantic elements
            is_flutter = tag == 'flt-semantics' or (element_id and element_id.startswith('flt-semantic-node'))
            
            # For Flutter elements, REQUIRE text (IDs are dynamic and unstable)
            if is_flutter:
                if not text_content or len(text_content) < 2:
                    print(f"[@screen_analyzer:_extract_web] Filtered FLUTTER NO TEXT: {selector}")
                    continue
                # Check for tappable - can be className OR role=button in attributes
                is_tappable = (
                    'flt-tappable' in elem.get('className', '') or 
                    elem.get('attributes', {}).get('role') == 'button'
                )
                if not is_tappable:
                    print(f"[@screen_analyzer:_extract_web] Filtered FLUTTER NOT TAPPABLE: {text_content[:30]}")
                    continue
                
                # CRITICAL: Replace unstable ID selector with text-based selector
                # Flutter IDs change on refresh (flt-semantic-node-6 → flt-semantic-node-7)
                selector = text_content  # Use text as selector
                print(f"[@screen_analyzer:_extract_web] Flutter element: using text selector '{text_content}' instead of dynamic ID")
            
            # Check identifiers (skip ID check for Flutter)
            has_id = '#' in selector and not is_flutter
            has_text = len(text_content) > 2
            
            # Check if clickable/navigable
            # For <a> tags: MUST have href (otherwise it's not a link)
            # For other tags: href not required (buttons, inputs, Flutter elements, etc.)
            if tag == 'a':
                # Links without href are not navigation targets
                if not href or href.startswith('#'):
                    print(f"[@screen_analyzer:_extract_web] Filtered NO HREF: {selector} (text: {text_content[:20]})")
                    continue
            
            # Filter elements with NO identifiers (no ID, no text)
            # BUT: If we have a valid href (and it's a link), we should keep it even without text
            # (The href itself describes the destination)
            if not has_id and not has_text:
                if tag == 'a' and href and len(href) > 2:
                    # Use href as fallback label
                    print(f"[@screen_analyzer:_extract_web] Weak identifier but valid href: {href} -> Keeping")
                else:
                    print(f"[@screen_analyzer:_extract_web] Filtered WEAK IDENTIFIER: {selector} (tag: {tag}, text: '{text_content}')")
                    continue
            
            # Get label for this element
            label = None
            label_suffix = None  # For disambiguating same-text elements
            
            # Priority 1: For Flutter, ALWAYS use text (IDs are dynamic)
            if is_flutter and text_content:
                label = text_content
            # Priority 2: Text content (More human-readable than ID for web)
            elif text_content:
                label = text_content
                
                # Add suffix for input[type=submit] to differentiate from links
                if tag == 'input' and attributes.get('type') == 'submit':
                    label_suffix = "Submit"
                    print(f"[@screen_analyzer:_extract_web] 🔘 Submit button detected: '{label}' -> will add suffix if needed")
                    
            # Priority 3: ID from selector (Reliable fallback if text is missing)
            elif has_id:
                label = selector.split('#')[-1].strip()
            # Priority 4: aria-label
            elif attributes.get('aria-label'):
                label = attributes['aria-label'].strip()
            # Priority 5: Placeholder for inputs
            elif tag == 'input' and attributes.get('placeholder'):
                label = attributes['placeholder'].strip()
                label_suffix = "Submit"  # Inputs are usually submit buttons
            # Priority 6: Derive from href (Fallback for links with empty text)
            elif tag == 'a' and href:
                # /collections/all -> collections/all
                clean_href = href.strip('/').split('/')[-1]
                if clean_href:
                    label = clean_href.replace('-', ' ').replace('_', ' ').title()
            # Priority 7: class name (last resort)
            elif '.' in selector:
                label = selector.split('.')[-1].strip()
            
            if not label:
                continue
            
            label_lower = label.lower()
            
            # ═══════════════════════════════════════════════════════════════
            # FILTERS: Exclude non-navigation elements
            # ═══════════════════════════════════════════════════════════════
            
            # Filter 1: Layout containers
            if any(kw in label_lower for kw in layout_keywords):
                print(f"[@screen_analyzer:_extract_web] Filtered LAYOUT: {label}")
                continue
            
            # Filter 2: Decorations
            if any(kw in label_lower for kw in decoration_keywords):
                print(f"[@screen_analyzer:_extract_web] Filtered DECORATION: {label}")
                continue
            
            # Filter 3: External/social links
            if any(kw in label_lower for kw in external_keywords):
                print(f"[@screen_analyzer:_extract_web] Filtered EXTERNAL: {label}")
                continue
            
            # Filter 4: Very short (< 2 chars) or very long (> 40 chars)
            if len(label) < 2 or len(label) > 40:
                print(f"[@screen_analyzer:_extract_web] Filtered LENGTH: {label} ({len(label)} chars)")
                continue
            
            # Filter 5: URL quality checks
            # External URL check (for <a> tags)
            if tag == 'a' and href:
                # Skip external URLs
                if any(ext in href for ext in ['facebook.com', 'twitter.com', 'instagram.com', 'youtube.com', 'mailto:']):
                    print(f"[@screen_analyzer:_extract_web] Filtered EXTERNAL URL: {label} ({href})")
                    continue
                
                # Skip anchors (#)
                if href.startswith('#') and len(href) < 3:
                    print(f"[@screen_analyzer:_extract_web] Filtered ANCHOR: {label} ({href})")
                    continue
            
            # Filter 6: Dynamic content patterns
            dynamic_indicators = ['$', '€', '£', 'chf', 'usd', 'eur', 'season ', 'episode ']
            if any(ind in label_lower for ind in dynamic_indicators):
                print(f"[@screen_analyzer:_extract_web] Filtered DYNAMIC: {label}")
                continue

            # Filter 7: Number-only elements and number-percentage elements
            import re
            if re.match(r'^\d+$', label) or re.match(r'^\d+%$', label):
                print(f"[@screen_analyzer:_extract_web] Filtered NUMBER/PERCENTAGE: {label} ({len(label)} chars)")
                continue
            
            # ═══════════════════════════════════════════════════════════════
            # PASSED ALL FILTERS - Add to results
            # ═══════════════════════════════════════════════════════════════
            
            clean_label = label.replace('_', ' ').replace('-', ' ').title()
            
            # Handle duplicates: use suffix if available, otherwise append counter
            if clean_label in interactive_elements:
                if label_suffix:
                    # Use the suffix we identified earlier (e.g., "Submit")
                    unique_label = f"{clean_label} {label_suffix}"
                    print(f"[@screen_analyzer:_extract_web] 🔀 DUPLICATE DETECTED: '{clean_label}' -> '{unique_label}' (using suffix)")
                else:
                    # Find a unique name by appending counter
                    counter = 2
                    unique_label = f"{clean_label} {counter}"
                    while unique_label in interactive_elements:
                        counter += 1
                        unique_label = f"{clean_label} {counter}"
                    
                    print(f"[@screen_analyzer:_extract_web] 🔀 DUPLICATE DETECTED: '{clean_label}' -> '{unique_label}' (using counter)")
                
                clean_label = unique_label
            
            interactive_elements.append(clean_label)
            seen_selectors.add(selector)
            print(f"[@screen_analyzer:_extract_web] ✅ INCLUDED: {clean_label} (selector: {selector})")
        
        print(f"[@screen_analyzer:_extract_web] Final count: {len(interactive_elements)} navigation targets")
        
        return interactive_elements[:20]  # Limit to top 20 elements
    
    def _analyze_from_ai_vision(self, screenshot_path: str) -> Dict:
        """
        Use AI vision to analyze screenshot (TV/STB only)
        """
        print(f"\n{'='*80}")
        print(f"[@screen_analyzer:_analyze_from_ai_vision] AI VISION ANALYSIS")
        print(f"{'='*80}")
        print(f"📸 Screenshot: {screenshot_path}")
        print(f"🎮 Device Type: TV/STB (vision-based)")
        print(f"📱 Device Model: {self.device_model_name}")
        print(f"\n🤖 USING AI VISION ANALYSIS")
        print(f"{'-'*80}\n")
        
        # Simple prompt for TV/STB - just ask for a table
        prompt = """List ONLY THE VISIBLE clickable/focusable UI elements from this screenshot.

🚨 CRITICAL: Return ONLY what you can SEE in the image. DO NOT infer, assume, or add common elements.

⚠️ RULE #1: Group elements by VERTICAL POSITION (Y-coordinate), NOT by visual appearance.
Elements at the same HEIGHT = SAME ROW, even if separated by space or different types.

⚠️ RULE #2: Within each row, use STRICT LEFT-TO-RIGHT PIXEL ORDER (X-coordinate).
Scan from LEFT EDGE to RIGHT EDGE. Include ALL elements across the FULL WIDTH.
DO NOT miss elements on far left or far right edges!

⚠️ RULE #3: SCAN THE ENTIRE SCREEN WIDTH
- Check far LEFT edge for icons (search, menu)
- Check CENTER for main navigation
- Check far RIGHT edge for buttons (settings, profile, radio, etc.)

Output format (one row per line, elements separated by commas):

Row 1: element1, element2, element3
Row 2: element4, element5
Row 3: element6

What to include:
- Navigation buttons/tabs (visible text labels)
- Icons (describe what they are: search, menu, settings, etc.)
- Dropdowns (today, all channels, etc.)
- Utility buttons on edges (radio, settings, profile, etc.)

What to skip:
- TV show names, program cards, timestamps
- Channel numbers, logos
- Background decorative elements
- Time slots (19:00, 20:00, etc.)

🚨 CRITICAL: SKIP dynamic content in cards (movie posters, TV thumbnails, program cards)!
Ignore show names, movie titles, program titles ("Tehran", "virtualpy") and repeated thumbnails.


Example TV Guide Top Bar:

✅ CORRECT - Full width scan, left to right:
Row 1: search, today, all channels, radio

❌ WRONG - Missing far-right element:
Row 1: search, today, all channels
       ^^ Missing "radio" button on far right!

❌ WRONG - Including program content instead of navigation:
Row 1: search, today, all channels, Canal B, Heilige Messe, Le 20h
                                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                    These are program cards, NOT navigation!

Focus on THREE things:
1. Same Y-coordinate (vertical position)? → Same row!
2. Full width scan: LEFT edge → CENTER → RIGHT edge
3. ONLY return what's ACTUALLY VISIBLE in the image!"""

        print(f"📝 PROMPT SENT TO AI:")
        print(f"{'-'*80}")
        print(prompt)
        print(f"{'-'*80}\n")

        try:
            print(f"[@screen_analyzer:_analyze_from_ai_vision] 🤖 Calling VideoAIHelpers.analyze_full_image_with_ai()...")
            
            # Use existing VideoAIHelpers for AI analysis
            # VideoAIHelpers needs av_controller, but we'll pass None and use direct file path
            from backend_host.src.controllers.verification.video_ai_helpers import VideoAIHelpers
            
            ai_helpers = VideoAIHelpers(
                av_controller=None,  # We're passing file path directly
                device_name=self.device_id
            )
            
            # Use analyze_full_image_with_ai which exists
            # Note: We need to call the underlying AI directly with higher max_tokens
            # because analyze_full_image_with_ai() limits to 200 tokens
            from shared.src.lib.utils.ai_utils import call_vision_ai
            
            result = call_vision_ai(prompt, screenshot_path, max_tokens=800, temperature=0.0)
            
            if not result['success']:
                raise Exception(f"AI vision call failed: {result.get('error', 'Unknown error')}")
            
            response = result['content'].strip()
            
            print(f"\n{'='*80}")
            print(f"[@screen_analyzer:_analyze_from_ai_vision] 🤖 RAW AI RESPONSE:")
            print(f"{'='*80}")
            print(response)
            print(f"{'='*80}\n")
            
            # Parse simple table format
            print(f"[@screen_analyzer:_analyze_from_ai_vision] 📊 Parsing table...")
            
            def is_valid_menu_item(item: str) -> bool:
                """Filter out non-menu items (time/date displays, etc.)"""
                # Remove items with digits or special chars (except spaces, &, -, ')
                import re
                # Allow: letters, spaces, &, -, apostrophe
                # Reject: digits, other punctuation
                return bool(re.match(r"^[a-zA-Z\s&'\-]+$", item))
            
            lines = []
            all_items = []
            
            for line in response.strip().split('\n'):
                line = line.strip()
                if line.startswith('Row') and ':' in line:
                    # Extract items after "Row X:"
                    items_text = line.split(':', 1)[1].strip()
                    raw_items = [item.strip() for item in items_text.split(',') if item.strip()]
                    
                    # Filter out non-menu items (time, date, numbers)
                    filtered_items = []
                    for item in raw_items:
                        if is_valid_menu_item(item):
                            filtered_items.append(item)
                        else:
                            print(f"[@screen_analyzer:_analyze_from_ai_vision]   🚫 Filtered out '{item}' (contains digits/special chars)")
                    
                    items = filtered_items
                    
                    if items:
                        lines.append(items)
                        all_items.extend(items)
                        print(f"[@screen_analyzer:_analyze_from_ai_vision]   ✅ {line.split(':')[0]}: {len(items)} items - {items}")
            
            print(f"\n[@screen_analyzer:_analyze_from_ai_vision] 📊 Total items: {len(all_items)}")
            print(f"[@screen_analyzer:_analyze_from_ai_vision] 📊 Total rows: {len(lines)}")
            
            # Determine menu structure from lines
            if len(lines) == 1:
                menu_type = 'horizontal'
            elif len(lines) > 1:
                # Check if it's vertical (1 item per line) or grid (multiple items per line)
                if all(len(line) == 1 for line in lines):
                    menu_type = 'vertical'
                else:
                    menu_type = 'mixed'  # Has both horizontal and vertical navigation
            else:
                menu_type = 'unknown'
            
            print(f"[@screen_analyzer:_analyze_from_ai_vision] 🎯 Detected menu type: {menu_type}")
            
            # Strategy for TV/STB is always DPAD
            strategy = 'test_dpad_directions'
            print(f"[@screen_analyzer:_analyze_from_ai_vision] 🎮 Navigation strategy: {strategy}")
            
            result = {
                'menu_type': menu_type,
                'items': all_items,
                'lines': lines,  # Keep line structure for navigation logic
                'predicted_depth': 2,
                'strategy': strategy
            }
            
            print(f"\n{'='*80}")
            print(f"[@screen_analyzer:_analyze_from_ai_vision] ✅ ANALYSIS COMPLETE")
            print(f"{'='*80}")
            print(f"📊 Menu Type: {menu_type}")
            print(f"📊 Strategy: {strategy}")
            print(f"📊 Items ({len(all_items)}):")
            for i, line in enumerate(lines, 1):
                print(f"   Row {i}: {', '.join(line)}")
            print(f"{'='*80}\n")
            
            if not all_items:
                print(f"⚠️  [@screen_analyzer:_analyze_from_ai_vision] WARNING: No items extracted from AI response")
                print(f"   Screenshot: {screenshot_path}")
                print(f"   Device: {self.device_model_name}")
                print(f"   Suggestion: Check if AI vision model is working or screenshot is valid")
                raise ValueError("No interactive elements found in AI vision analysis")
            
            return result
            
        except Exception as e:
            print(f"\n❌ [@screen_analyzer:_analyze_from_ai_vision] ANALYSIS FAILED")
            print(f"   Screenshot: {screenshot_path}")
            print(f"   Device: {self.device_model_name}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            
            # Re-raise ValueError for consistent error handling
            if isinstance(e, ValueError):
                raise
            else:
                raise Exception(f"AI vision analysis failed for {self.device_model_name}: {e}")
    
    def is_new_screen(
        self,
        before_path: str,
        after_path: str,
        action: str
    ) -> Dict:
        """
        Phase 2: After OK/BACK action, determine if we reached new screen
        
        Args:
            before_path: Screenshot before action
            after_path: Screenshot after action
            action: Action taken (e.g., 'OK', 'BACK')
            
        Returns:
            {
                'is_new_screen': True,
                'context_visible': False,
                'suggested_name': 'settings',
                'screen_type': 'menu',
                'reasoning': 'Completely different screen...'
            }
        """
        from backend_host.src.controllers.verification.video_ai_helpers import VideoAIHelpers
        
        prompt = f"""Compare these two screenshots after action '{action}'.

Please answer:
1. Is this a NEW SCREEN (completely different UI) or SAME SCREEN (just focus changed)?
2. Can you still see the previous menu? (Yes/No)
3. What is a good name for this screen based on visible content?
4. What type of screen is this? (menu, settings, content, info, player, etc.)
5. Brief reasoning for your decision

Return ONLY valid JSON in this exact format:
{{
    "is_new_screen": true,
    "context_visible": false,
    "suggested_name": "settings",
    "screen_type": "menu",
    "reasoning": "Completely different screen, cannot see previous menu"
}}

Context visible = Can you still see elements from the previous screen?
"""

        try:
            # Use existing VideoAIHelpers with both images
            from backend_host.src.controllers.verification.video_ai_helpers import VideoAIHelpers
            
            ai_helpers = VideoAIHelpers(
                av_controller=None,  # We're passing file path directly
                device_name=self.device_id
            )
            
            # Use analyze_full_image_with_ai for the after screenshot
            response = ai_helpers.analyze_full_image_with_ai(
                image_path=after_path,
                user_question=prompt
            )
            
            print(f"[@screen_analyzer:is_new_screen] AI response: {response}")
            
            # Parse JSON from response
            result = self._parse_json_response(response)
            
            if not result:
                # Fallback: assume it's a new screen
                return {
                    'is_new_screen': True,
                    'context_visible': False,
                    'suggested_name': 'screen',
                    'screen_type': 'screen',
                    'reasoning': 'Could not determine, assuming new screen'
                }
            
            return result
            
        except Exception as e:
            print(f"[@screen_analyzer:is_new_screen] Error: {e}")
            # Return safe defaults on error
            return {
                'is_new_screen': True,
                'context_visible': False,
                'suggested_name': 'screen',
                'screen_type': 'screen',
                'reasoning': f'Error during analysis: {str(e)}'
            }
    
    def capture_screenshot(self) -> Optional[str]:
        """
        Capture screenshot and save to cold storage:
        - android_mobile: Use ADB native screenshot (exact display buffer)
        - Other devices: Use HDMI capture via VideoAIHelpers
        
        Returns:
            Screenshot file path in COLD storage or None on error
        """
        try:
            import shutil
            from datetime import datetime
            from shared.src.lib.utils.storage_path_utils import get_captures_path, get_capture_folder_from_device_id
            
            # Get device capture folder
            try:
                device_folder = get_capture_folder_from_device_id(self.device_id)
            except ValueError as e:
                print(f"[@screen_analyzer:capture_screenshot] Error getting device folder: {e}")
                return None
            
            # For android_mobile, use native ADB screenshot
            if self.device_model_name and 'mobile' in self.device_model_name.lower() and self.controller:
                success, base64_data, error = self.controller.take_screenshot()
                if success and base64_data:
                    # Convert base64 to image data
                    import base64
                    image_data = base64.b64decode(base64_data)
                    
                    # Save to COLD storage (captures path)
                    captures_path = get_captures_path(device_folder)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                    filename = f"ai_exploration_{timestamp}.png"
                    cold_path = f"{captures_path}/{filename}"
                    
                    # Ensure directory exists
                    import os
                    os.makedirs(captures_path, exist_ok=True)
                    
                    # Write to cold storage
                    with open(cold_path, 'wb') as f:
                        f.write(image_data)
                    
                    print(f"\n{'='*80}")
                    print(f"[@screen_analyzer:capture_screenshot] SCREENSHOT CAPTURED")
                    print(f"{'='*80}")
                    print(f"📸 Local Path: {cold_path}")
                    print(f"📁 Device Folder: {device_folder}")
                    print(f"📝 Filename: {filename}")
                    print(f"{'='*80}\n")
                    
                    return cold_path
            
            # Fallback to HDMI capture for all other devices using device's AV controller
            av_controller = self.device._get_controller('av')
            if not av_controller:
                print(f"[@screen_analyzer:capture_screenshot] ❌ FAIL EARLY: No AV controller found for device {self.device_id}")
                return None
            
            print(f"[@screen_analyzer:capture_screenshot] Attempting HDMI capture via AV controller...")
            temp_screenshot = av_controller.take_screenshot()
            
            if not temp_screenshot:
                print(f"[@screen_analyzer:capture_screenshot] ❌ FAIL EARLY: AV controller returned None/empty")
                return None
            
            # Verify file exists
            import os
            if not os.path.exists(temp_screenshot):
                print(f"[@screen_analyzer:capture_screenshot] ❌ FAIL EARLY: Screenshot file doesn't exist: {temp_screenshot}")
                return None
            
            if temp_screenshot:
                # Copy to cold storage
                captures_path = get_captures_path(device_folder)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                filename = f"ai_exploration_{timestamp}.png"
                cold_path = f"{captures_path}/{filename}"
                
                # Ensure directory exists
                import os
                os.makedirs(captures_path, exist_ok=True)
                
                # Copy file
                shutil.copy2(temp_screenshot, cold_path)
                print(f"[@screen_analyzer:capture_screenshot] Copied to cold storage: {cold_path}")
                return cold_path
            
            return None
            
        except Exception as e:
            print(f"[@screen_analyzer:capture_screenshot] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _parse_json_response(self, response: str) -> Optional[Dict]:
        """
        Parse JSON from AI response text
        
        Args:
            response: Raw AI response (may contain text + JSON)
            
        Returns:
            Parsed dict or None if failed
        """
        try:
            # Try direct JSON parse first
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if '```json' in response:
                start = response.find('```json') + 7
                end = response.find('```', start)
                if end != -1:
                    json_str = response[start:end].strip()
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        pass
            
            # Try to find JSON object in text
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1:
                json_str = response[start:end+1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
            
            print(f"[@screen_analyzer:_parse_json_response] Failed to parse JSON from: {response[:200]}")
            return None

