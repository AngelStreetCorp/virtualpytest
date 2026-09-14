"""
Exploration Engine - Main orchestrator for AI-driven navigation tree generation
Coordinates screen analysis, navigation, and tree building
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
import traceback

from backend_host.src.services.ai_exploration.screen_analyzer import ScreenAnalyzer
from backend_host.src.services.ai_exploration.navigation_strategy import NavigationStrategy
from backend_host.src.services.ai_exploration.node_generator import NodeGenerator
from backend_host.src.services.ai_exploration.exploration_context import ExplorationContext, create_exploration_context
from shared.src.lib.database.navigation_trees_db import (
    save_node,
    save_edge,
    create_sub_tree,
    get_tree_metadata,
    get_node_by_id
)


class ExplorationEngine:
    """Main orchestrator for AI-driven exploration"""
    
    def __init__(
        self,
        tree_id: str,
        device,  # Device instance (passed from ExplorationExecutor)
        team_id: str,
        userinterface_name: str,
        screenshot_callback=None,
        progress_callback=None,
        cancellation_check=None
    ):
        """
        Initialize exploration engine

        Args:
            tree_id: Tree ID to add nodes to
            device: Device instance (from ExplorationExecutor)
            team_id: Team ID
            userinterface_name: UI name (e.g., 'example_mobile')
            screenshot_callback: Optional callback function to notify when screenshot is captured
            progress_callback: Optional callback function to notify of progress updates
            cancellation_check: Optional function to check if exploration should be cancelled

        Note: Exploration is SIMPLE - only 1 level (click → back → create node/edge)
        """
        self.device = device
        self.tree_id = tree_id
        self.device_id = device.device_id
        self.host_name = device.host_name
        self.device_model_name = device.device_model
        self.team_id = team_id
        self.userinterface_name = userinterface_name
        self.screenshot_callback = screenshot_callback
        self.cancellation_check = cancellation_check
        self.progress_callback = progress_callback
        
        # ✅ FIX: Device-aware controller selection
        # Web/Host devices use 'web' controller, others use 'remote'
        device_model_lower = self.device_model_name.lower()
        
        if 'host' in device_model_lower or 'web' in device_model_lower:
            # Web device: Use web/playwright controller
            self.controller = self.device._get_controller('web')
            controller_type = 'web'
        else:
            # Mobile/TV/STB: Use remote controller (ADB or infrared)
            self.controller = self.device._get_controller('remote')
            controller_type = 'remote'
        
        if not self.controller:
            raise ValueError(f"No {controller_type} controller found for device {self.device_id} (model: {self.device_model_name})")
        
        print(f"[@exploration_engine] Using {controller_type} controller for {self.device_model_name}")
        
        # Initialize components with existing controller
        self.screen_analyzer = ScreenAnalyzer(
            device=self.device,  # Pass device directly
            controller=self.controller,
            ai_model='qwen'
        )
        
        self.navigation_strategy = NavigationStrategy(self.controller, self.screen_analyzer)
        self.node_generator = NodeGenerator(tree_id, team_id)
        
        # Exploration state
        self.created_nodes = []
        self.created_edges = []
        self.created_subtrees = []
        self.exploration_log = []
        
        # Phase 1 state (stored for Phase 2)
        self.initial_screenshot = None
        self.prediction = None
        
        # ✅ NEW: MCP client for tool orchestration
        try:
            from backend_server.src.mcp.mcp_server import VirtualPyTestMCPServer
            self.mcp_server = VirtualPyTestMCPServer()
            print(f"[@exploration_engine] MCP server initialized")
        except Exception as e:
            print(f"[@exploration_engine] Warning: MCP server initialization failed: {e}")
            self.mcp_server = None
        
        # ✅ NEW: Context instance (will be set by executor)
        self.context: Optional[ExplorationContext] = None
        
    # ========== NEW: MCP-FIRST METHODS (v2.0) ==========
    
    def phase0_detect_strategy(self, context: ExplorationContext) -> ExplorationContext:
        """
        Phase 0: Detect device capabilities and determine strategy
        
        NEW in v2.0: Device-aware strategy detection
        
        Args:
            context: Exploration context to update
            
        Returns:
            Updated context with strategy and available_elements
        """
        print(f"\n[@exploration_engine] === PHASE 0: STRATEGY DETECTION ===")
        print(f"Device Model: {context.device_model}")
        
        device_model = context.device_model.lower()
        
        # Mobile/Web: Try dump_ui_elements
        if 'mobile' in device_model or 'host' in device_model:
            print(f"  Device type: Mobile/Web - attempting dump_ui_elements")
            
            if self.mcp_server:
                try:
                    # Call MCP tool: dump_ui_elements
                    result = self.mcp_server.call_tool('dump_ui_elements', {
                        'device_id': context.device_id,
                        'host_name': context.host_name,
                        'platform': 'android' if 'mobile' in device_model else 'web'
                    })
                    
                    if result and not result.get('isError', False):
                        context.strategy = 'click_with_selectors'
                        context.has_dump_ui = True
                        # Extract elements from MCP response
                        if 'content' in result and result['content']:
                            # Parse MCP response
                            content = result['content'][0].get('text', '{}')
                            import json
                            try:
                                parsed = json.loads(content) if isinstance(content, str) else content
                                context.available_elements = parsed.get('elements', [])
                            except:
                                context.available_elements = []
                        print(f"  ✅ dump_ui_elements succeeded: {len(context.available_elements)} elements found")
                    else:
                        context.strategy = 'click_with_text'
                        context.has_dump_ui = False
                        print(f"  ⚠️ dump_ui_elements failed: fallback to click_with_text")
                except Exception as e:
                    print(f"  ⚠️ dump_ui_elements error: {e}")
                    context.strategy = 'click_with_text'
                    context.has_dump_ui = False
            else:
                # No MCP server - fallback
                context.strategy = 'click_with_text'
                context.has_dump_ui = False
                print(f"  ⚠️ MCP server not available: fallback to click_with_text")
        
        # TV/STB: Screenshot only
        else:
            print(f"  Device type: TV/STB - using screenshot-based strategy")
            context.strategy = 'dpad_with_screenshot'
            context.has_dump_ui = False
        
        context.add_step_result('phase0_detection', {
            'success': True,
            'strategy': context.strategy,
            'has_dump_ui': context.has_dump_ui,
            'elements_found': len(context.available_elements)
        })
        
        print(f"  Strategy: {context.strategy}")
        print(f"  Has dump_ui: {context.has_dump_ui}")
        print(f"[@exploration_engine] === PHASE 0 COMPLETE ===\n")
        
        return context
    
    def phase1_analyze_and_plan(self, context: ExplorationContext) -> ExplorationContext:
        """
        Phase 1: Analyze screenshot and populate context with sanitized items
        
        Args:
            context: Exploration context
            
        Returns:
            Updated context with predicted_items (sanitized), item_selectors, screenshot_url, menu_type
        """
        print(f"\n[@exploration_engine] === PHASE 1: Analysis & Planning ===")
        
        # Capture screenshot (optional - continue even if it fails)
        screenshot_path = self.screen_analyzer.capture_screenshot()
        if not screenshot_path:
            print(f"  ⚠️ Screenshot capture failed - continuing without screenshot")
            screenshot_path = None  # Continue with None
        
        # Analyze and predict
        try:
            prediction = self._phase1_anticipation(screenshot_path)
        except Exception as e:
            print(f"❌ [@exploration_engine:phase1_analyze_and_plan] ANALYSIS FAILED")
            print(f"   Screenshot: {screenshot_path}")
            print(f"   Device: {self.device_model_name}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            
            # Store error in context
            context.add_step_result('phase1_analysis', {
                'success': False,
                'error': str(e),
                'screenshot': screenshot_path
            })
            return context
        
        raw_items = prediction.get('items', [])
        
        print(f"  📝 Sanitizing {len(raw_items)} items...")
        sanitized_items = []
        seen = set()
        duplicate_items = []
        
        for item in raw_items:
            sanitized = self.node_generator.target_to_node_name(item)
            if sanitized not in seen:
                seen.add(sanitized)
                sanitized_items.append(sanitized)
                print(f"    '{item}' → '{sanitized}'")
            else:
                duplicate_items.append(sanitized)
                print(f"    '{item}' → '{sanitized}' (duplicate)")
        
        # Store duplicate positions for context (if needed later)
        context.duplicate_positions = duplicate_items if hasattr(context, 'duplicate_positions') else []
        
        # ✅ SPLIT AND REORDER for horizontal D-pad navigation
        # For TV/STB horizontal menus, we explore: RIGHT items first, then LEFT items
        # Apply to 'horizontal' (single row) and 'mixed' (Row 1 is horizontal, but has other rows too)
        if context.strategy in ['dpad_with_screenshot', 'test_dpad_directions'] and prediction.get('menu_type') in ['horizontal', 'mixed']:
            print(f"\n  🔄 SPLITTING items around HOME for D-pad navigation...")
            
            # For 'mixed' menus: only process Row 1 (horizontal nav bar), keep other rows unchanged
            lines = prediction.get('lines', [])
            if prediction.get('menu_type') == 'mixed' and lines:
                # Row 1 is already sanitized in sanitized_items, extract it
                row1_count = len(lines[0])
                row1_items = sanitized_items[:row1_count]
                other_items = sanitized_items[row1_count:]
                
                print(f"    Mixed menu: Row 1 has {row1_count} items, other rows have {len(other_items)} items")
                items_to_process = row1_items
            else:
                # Pure horizontal: process all items
                items_to_process = sanitized_items
                other_items = []
            
            # Find home index
            home_index = -1
            for i, item in enumerate(items_to_process):
                if item.lower() == 'home':
                    home_index = i
                    break
            
            if home_index > 0:
                # Home found with items on left side
                left_items = items_to_process[:home_index]
                right_items = items_to_process[home_index + 1:]
                
                # Store metadata (for action_sets)
                context.items_left_of_home = left_items
                context.items_right_of_home = right_items
                
                # ✅ FIX: Reorder: [home, right items, LEFT items, THEN vertical rows]
                # Complete Row 0 (horizontal) first, then Row 1+ (vertical)
                reordered = ['home'] + right_items + left_items
                
                print(f"    Original L→R: {items_to_process}")
                print(f"    Home at index: {home_index}")
                print(f"    Left items: {left_items}")
                print(f"    Right items: {right_items}")
                print(f"    Reordered Row 0: {reordered}")
                print(f"    Vertical rows (Row 1+): {other_items}")
                
                # ✅ FIX: Row 0 (RIGHT + LEFT) FIRST, then Row 1+ (vertical)
                sanitized_items = reordered + other_items
                print(f"    Final order: {sanitized_items}")
            else:
                # Home at start or not found
                print(f"    Home at start or not found - no left items")
                context.items_left_of_home = []
                context.items_right_of_home = items_to_process[1:] if len(items_to_process) > 1 else []
        
        # Populate context with SANITIZED (and possibly REORDERED) items
        context.predicted_items = sanitized_items
        context.menu_type = prediction.get('menu_type')
        context.screenshot_url = screenshot_path
        context.total_steps = len(sanitized_items)
        
        # Store item selectors if available (keys should also be sanitized)
        item_selectors = prediction.get('item_selectors', {})
        context.item_selectors = {
            self.node_generator.target_to_node_name(k): v 
            for k, v in item_selectors.items()
        }
        
        context.add_step_result('phase1_analysis', {
            'success': True,
            'items_found': len(sanitized_items),
            'menu_type': context.menu_type
        })
        
        print(f"  ✅ Phase 1 complete: {len(sanitized_items)} items (sanitized)")
        print(f"[@exploration_engine] === PHASE 1 COMPLETE ===\n")
        
        return context
    
    def phase2_create_single_edge_mcp(self, item: str, context: ExplorationContext) -> Dict:
        """
        Phase 2: Create and test SINGLE edge using MCP tools (incremental)
        
        NEW in v2.0: MCP-first incremental approach
        
        Workflow:
        1. create_node (MCP)
        2. create_edge (MCP)
        3. get_edge + execute_device_action (MCP) ← MANDATORY TEST
        4. save_node_screenshot (MCP)
        
        Args:
            item: Item name to create edge for
            context: Exploration context
            
        Returns:
            {
                'success': bool,
                'node_created': str,
                'edge_created': str,
                'edge_tested': bool,
                'error': str  # if failed
            }
        """
        print(f"\n[@exploration_engine] Creating edge for: {item}")
        
        if not self.mcp_server:
            return {'success': False, 'error': 'MCP server not available'}
        
        # Sanitize label (normalize accents: è→e, é→e, etc.)
        from .node_generator import NodeGenerator
        node_gen = NodeGenerator()
        sanitized_label = node_gen.target_to_node_name(item)
        
        # 1. Create Node via MCP
        print(f"  Step 1/4: Creating node ('{item}' → '{sanitized_label}')...")
        node_result = self.mcp_server.call_tool('create_node', {
            'tree_id': context.tree_id,
            'label': sanitized_label,
            'type': 'screen',
            'position': {'x': 250 + (context.current_step * 200), 'y': 300},
            'team_id': context.team_id
        })
        
        if node_result.get('isError', False):
            return {
                'success': False,
                'error': f"Node creation failed: {node_result.get('content', [{}])[0].get('text', 'Unknown error')}",
                'step': 'create_node'
            }
        
        print(f"  ✅ Node created: {sanitized_label}")
        
        # 2. Create Edge via MCP  
        print(f"  Step 2/4: Creating edge...")
        
        # Determine source node: for D-pad, use previous item; for click, use 'home'
        if context.strategy in ['dpad_with_screenshot', 'test_dpad_directions']:
            # Sequential navigation: source is previous item in list
            current_index = context.predicted_items.index(item)
            source_node_id = context.predicted_items[current_index - 1] if current_index > 0 else 'home'
            source_node_id = source_node_id.lower().replace(' ', '_')
        else:
            # Click navigation: always from home
            source_node_id = 'home'
        
        action_sets = self._build_action_sets_for_context(item, source_node_id, context)
        
        edge_result = self.mcp_server.call_tool('create_edge', {
            'tree_id': context.tree_id,
            'source_node_id': source_node_id,
            'target_node_id': sanitized_label,  # Use sanitized label
            'source_label': source_node_id,
            'target_label': sanitized_label,    # Use sanitized label
            'action_sets': action_sets,
            'team_id': context.team_id
        })
        
        if edge_result.get('isError', False):
            return {
                'success': False,
                'error': f"Edge creation failed: {edge_result.get('content', [{}])[0].get('text', 'Unknown error')}",
                'step': 'create_edge'
            }
        
        # Extract edge_id from response
        edge_content = edge_result.get('content', [{}])[0].get('text', '')
        edge_id = self._extract_edge_id_from_response(edge_content)
        
        print(f"  ✅ Edge created: {edge_id}")
        
        # 3. TEST EDGE via MCP (CRITICAL!)
        print(f"  Step 3/4: Testing edge...")
        
        # Get edge details first
        edge_details = self.mcp_server.call_tool('get_edge', {
            'edge_id': edge_id,
            'tree_id': context.tree_id,
            'team_id': context.team_id
        })
        
        if edge_details.get('isError', False):
            return {
                'success': False,
                'error': f"Failed to get edge details: {edge_details.get('content', [{}])[0].get('text', 'Get edge failed')}",
                'step': 'get_edge',
                'edge_id': edge_id
            }
        
        # Extract actions from edge
        edge_content = edge_details.get('content', [{}])[0].get('text', '{}')
        import json
        try:
            edge_data = json.loads(edge_content)
            actions = edge_data.get('action_sets', [{}])[0].get('actions', [])
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            return {
                'success': False,
                'error': f"Failed to parse edge data: {str(e)}",
                'step': 'parse_edge',
                'edge_id': edge_id
            }
        
        # Execute actions
        test_result = self.mcp_server.call_tool('execute_device_action', {
            'device_id': context.device_id,
            'host_name': context.host_name,
            'actions': actions,
            'team_id': context.team_id
        })
        
        if test_result.get('isError', False):
            return {
                'success': False,
                'error': f"Edge test failed: {test_result.get('content', [{}])[0].get('text', 'Test failed')}",
                'step': 'execute_device_action',
                'edge_id': edge_id
            }
        
        print(f"  ✅ Edge tested successfully")
        
        # 4. Capture Screenshot via MCP
        print(f"  Step 4/4: Capturing screenshot...")
        screenshot_result = self.mcp_server.call_tool('save_node_screenshot', {
            'tree_id': context.tree_id,
            'node_id': item,
            'label': item,
            'host_name': context.host_name,
            'device_id': context.device_id,
            'userinterface_name': context.userinterface_name,
            'team_id': context.team_id
        })
        
        screenshot_url = None
        if not screenshot_result.get('isError', False):
            print(f"  ✅ Screenshot captured")
            # Extract URL from response if available
            screenshot_content = screenshot_result.get('content', [{}])[0].get('text', '')
            # Parse URL from response (format: "✅ Screenshot saved to node...")
            if 'Screenshot URL:' in screenshot_content:
                screenshot_url = screenshot_content.split('Screenshot URL:')[1].split('\n')[0].strip()
        
        return {
            'success': True,
            'node_created': item,
            'edge_created': edge_id,
            'edge_tested': True,
            'screenshot_url': screenshot_url
        }
    
    def _build_action_sets_for_context(self, item: str, source_item: str, context: ExplorationContext) -> List[Dict]:
        """
        Build device-aware action_sets based on context strategy
        
        Args:
            item: Target item name
            source_item: Source item name (for sequential D-pad navigation)
            context: Exploration context with strategy
            
        Returns:
            List of action_sets (bidirectional)
        """
        # Determine action_type from device_model
        # STB/Infrared → 'remote' (IR commands)
        # android_tv → 'adb' (ADB keyevents)
        # web → 'web' (Playwright)
        device_model = getattr(context, 'device_model', 'stb')
        
        if device_model in ['stb', 'fire_tv']:
            action_type = 'remote'
        elif device_model in ['android_mobile', 'android_tv']:
            action_type = 'adb'
        elif device_model == 'web':
            action_type = 'web'
        else:
            action_type = 'remote'  # Default fallback
        
        print(f"  [@_build_action_sets] device_model={device_model}, action_type={action_type}, strategy={context.strategy}")
        
        # CLICK-BASED STRATEGIES (Mobile/Web)
        if context.strategy == 'click_with_selectors':
            # Use exact selector from Phase 1
            selector_info = context.item_selectors.get(item, {})
            selector = selector_info.get('value', item)  # Fallback to text
            
            return [
                {
                    'id': f'{source_item}_to_{item}',
                    'label': f'{source_item} → {item}',
                    'actions': [{
                        'command': 'click_element',
                        'params': {'element_id': selector}
                    }],
                    'retry_actions': [],
                    'failure_actions': []
                },
                {
                    'id': f'{item}_to_{source_item}',
                    'label': f'{item} → {source_item}',
                    'actions': [{
                        'command': 'press_key',
                        'params': {'key': 'BACK'}
                    }],
                    'retry_actions': [],
                    'failure_actions': []
                }
            ]
        
        # D-PAD STRATEGIES (TV/STB) - SEQUENTIAL NAVIGATION
        elif context.strategy in ['dpad_with_screenshot', 'test_dpad_directions']:
            # Determine base D-pad direction from menu_type
            menu_type = getattr(context, 'menu_type', 'horizontal')
            right_key = 'RIGHT' if menu_type == 'horizontal' else 'DOWN'
            left_key = 'LEFT' if menu_type == 'horizontal' else 'UP'
            
            # Get left/right metadata from context
            items_left = getattr(context, 'items_left_of_home', [])
            items_right = getattr(context, 'items_right_of_home', [])
            
            # Determine which side this item is on
            is_left_item = item in items_left
            
            # Choose direction key
            direction_key = left_key if is_left_item else right_key
            reverse_direction_key = right_key if is_left_item else left_key
            
            print(f"  [@_build_action_sets] D-pad: {source_item} → {item}")
            print(f"    Left items: {items_left}")
            print(f"    Right items: {items_right}")
            print(f"    Item '{item}' side: {'LEFT' if is_left_item else 'RIGHT'}")
            print(f"    Direction: {direction_key}")
            
            # Build forward actions
            # Sequential navigation: direction + OK
            # Note: For first LEFT item, executor will navigate to home before calling this
            forward_actions = [
                {
                    'command': 'press_key',
                    'action_type': action_type,
                    'params': {'key': direction_key, 'wait_time': 500}
                },
                {
                    'command': 'press_key',
                    'action_type': action_type,
                    'params': {'key': 'OK', 'wait_time': 1000}
                }
            ]
            
            # Build reverse actions (BACK + reverse direction)
            reverse_actions = [
                {
                    'command': 'press_key',
                    'action_type': action_type,
                    'params': {'key': 'BACK', 'wait_time': 500}
                },
                {
                    'command': 'press_key',
                    'action_type': action_type,
                    'params': {'key': reverse_direction_key, 'wait_time': 500}
                }
            ]
            
            return [
                {
                    'id': f'{source_item}_to_{item}',
                    'label': f'{source_item} → {item}',
                    'actions': forward_actions,
                    'retry_actions': [],
                    'failure_actions': []
                },
                {
                    'id': f'{item}_to_{source_item}',
                    'label': f'{item} → {source_item}',
                    'actions': reverse_actions,
                    'retry_actions': [],
                    'failure_actions': []
                }
            ]
        
        # UNSUPPORTED STRATEGY - FAIL EARLY!
        else:
            raise ValueError(
                f"❌ Unsupported strategy '{context.strategy}' for device_model '{device_model}'. "
                f"Cannot fallback to click - device doesn't support it!"
            )
    
    def _build_edges_preview(
        self,
        raw_items: List[str],
        lines: List[List[str]],
        strategy: str,
        menu_type: str,
        items_left_of_home: List[str],
        items_right_of_home: List[str]
    ) -> List[Dict]:
        """
        Build edge preview for frontend display (matches structure_creator.py logic)
        
        Returns list of edge previews with source/target/actions
        """
        from backend_host.src.services.ai_exploration.node_generator import NodeGenerator
        node_gen = NodeGenerator(self.tree_id, self.team_id)
        
        edges_preview = []
        
        # DUAL-LAYER TV NAVIGATION
        if strategy in ['dpad_with_screenshot', 'test_dpad_directions']:
            # ========== ROW 1: HORIZONTAL MENU ==========
            if len(lines) > 0 and len(lines[0]) > 1:
                row1_items = lines[0]
                
                # Build focus node list for Row 1
                all_focus_nodes_row1 = []
                for item in row1_items:
                    node_name_clean = node_gen.target_to_node_name(item)
                    if node_name_clean.lower() in ['home', 'accueil']:
                        all_focus_nodes_row1.append('home')
                    else:
                        all_focus_nodes_row1.append(f"home_{node_name_clean}")
                
                # Find home index
                try:
                    start_idx = all_focus_nodes_row1.index('home')
                except ValueError:
                    start_idx = 0
                
                # RIGHT edges (outward from home)
                for idx in range(start_idx, len(all_focus_nodes_row1) - 1):
                    source_focus = all_focus_nodes_row1[idx]
                    target_focus = all_focus_nodes_row1[idx + 1]
                    original_item = row1_items[idx + 1]
                    
                    # Get screen node name
                    screen_node = node_gen.target_to_node_name(original_item)
                    
                    edges_preview.append({
                        'item': original_item,
                        'horizontal': {
                            'source': source_focus,
                            'target': target_focus,
                            'forward_action': 'RIGHT',
                            'reverse_action': 'LEFT'
                        },
                        'vertical': {
                            'source': target_focus,
                            'target': screen_node,
                            'forward_action': 'OK',
                            'reverse_action': 'BACK'
                        }
                    })
                
                # LEFT edges (inward to home)
                for idx in range(start_idx, 0, -1):
                    source_focus = all_focus_nodes_row1[idx]
                    target_focus = all_focus_nodes_row1[idx - 1]
                    original_item = row1_items[idx - 1]
                    
                    # Get screen node name
                    screen_node = node_gen.target_to_node_name(original_item)
                    
                    edges_preview.append({
                        'item': original_item,
                        'horizontal': {
                            'source': source_focus,
                            'target': target_focus,
                            'forward_action': 'LEFT',
                            'reverse_action': 'RIGHT'
                        },
                        'vertical': {
                            'source': target_focus,
                            'target': screen_node,
                            'forward_action': 'OK',
                            'reverse_action': 'BACK'
                        }
                    })
            
            # ========== ROW 2+: VERTICAL MENU (CHAINED) ==========
            if len(lines) > 1:
                prev_vertical_focus = 'home'  # Start from home for vertical chain
                
                for row_idx in range(1, len(lines)):
                    row_items = lines[row_idx]
                    
                    for item in row_items:
                        node_name_clean = node_gen.target_to_node_name(item)
                        focus_node = f"home_{node_name_clean}"
                        screen_node = node_name_clean
                        
                        edges_preview.append({
                            'item': item,
                            'horizontal': {
                                'source': prev_vertical_focus,  # ✅ Chain from previous
                                'target': focus_node,
                                'forward_action': 'DOWN',
                                'reverse_action': 'UP'
                            },
                            'vertical': {
                                'source': focus_node,
                                'target': screen_node,
                                'forward_action': 'OK',
                                'reverse_action': 'BACK'
                            }
                        })
                        
                        # Update prev for next item in chain
                        prev_vertical_focus = focus_node
        
        else:
            # MOBILE/WEB: Click-based navigation
            for item in raw_items:
                node_name_clean = node_gen.target_to_node_name(item)
                
                # Skip home
                if node_name_clean.lower() in ['home', 'accueil']:
                    continue
                
                edges_preview.append({
                    'item': item,
                    'click': {
                        'source': 'home',
                        'target': node_name_clean,
                        'forward_action': f'click("{item}")',
                        'reverse_action': 'BACK'
                    }
                })
        
        return edges_preview
    
    def _extract_edge_id_from_response(self, response_text: str) -> str:
        """
        Extract edge_id from MCP response text
        
        Args:
            response_text: MCP response text
            
        Returns:
            Extracted edge_id or generated fallback
        """
        import re
        
        # Look for "ID: <edge_id>" pattern
        match = re.search(r'ID:\s*([a-f0-9\-]+)', response_text, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Fallback: look for UUID pattern
        uuid_match = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', response_text)
        if uuid_match:
            return uuid_match.group(0)
        
        # Last fallback
        import uuid
        return str(uuid.uuid4())
    
    # ========== EXISTING METHODS (v1.x - kept for compatibility) ==========
        
    def analyze_and_plan(self) -> Dict:
        """
        PHASE 1: Analyze screenshot and create exploration plan
        
        Returns:
            {
                'success': True,
                'plan': {
                    'menu_type': 'horizontal',
                    'items': ['home', 'settings', 'profile'],
                    'strategy': 'test_right_left_first_then_ok',
                    'reasoning': 'AI reasoning here...',
                    'screenshot': 'url',
                    'screen_name': 'Initial Screen'
                }
            }
        """
        try:
            print(f"\n{'='*60}")
            print(f"[@exploration_engine] PHASE 1: Analysis & Planning")
            print(f"Tree: {self.tree_id}")
            print(f"Device: {self.device_model_name} ({self.device_id})")
            print(f"{'='*60}\n")
            
            # Capture initial screenshot (optional - continue even if it fails)
            self.initial_screenshot = self.screen_analyzer.capture_screenshot()
            if not self.initial_screenshot:
                print(f"[@exploration_engine:analyze_and_plan] ⚠️ Screenshot capture failed - continuing without screenshot")
                self.initial_screenshot = None  # Continue with None
            
            # Notify callbacks
            if self.screenshot_callback:
                self.screenshot_callback(self.initial_screenshot)
            if self.progress_callback:
                self.progress_callback(
                    step="Phase 1: Analyzing initial screenshot with AI...",
                    screenshot=self.initial_screenshot,
                    analysis=None
                )
            
            print(f"[@exploration_engine:analyze_and_plan] About to call _phase1_anticipation with screenshot: {self.initial_screenshot}")

            # Check for cancellation before AI analysis
            if self.cancellation_check and self.cancellation_check():
                print(f"[@exploration_engine:analyze_and_plan] ⚠️ Analysis cancelled before AI processing")
                return {
                    'success': False,
                    'error': 'Exploration was cancelled by user'
                }

            # AI analyzes and predicts structure
            try:
                self.prediction = self._phase1_anticipation(self.initial_screenshot)
            except Exception as e:
                print(f"❌ [@exploration_engine:analyze_and_plan] ANALYSIS FAILED")
                print(f"   Screenshot: {self.initial_screenshot}")
                print(f"   Device: {self.device_model_name}")
                print(f"   Error: {e}")
                import traceback
                traceback.print_exc()
                
                return {
                    'success': False,
                    'error': f"Screen analysis failed: {str(e)}"
                }
            
            print(f"[@exploration_engine:analyze_and_plan] _phase1_anticipation completed, prediction: {self.prediction}")
            
            # ✅ Extract left/right items for D-pad navigation AND reorder
            items_left_of_home = []
            items_right_of_home = []
            raw_items = self.prediction.get('items', [])
            lines = self.prediction.get('lines', [])
            
            # ✅ RENAME duplicates so they're auto-unselected (simpler than tracking!)
            seen = {}  # Track seen items: {sanitized_name: occurrence_count}
            duplicate_positions = []  # Still track positions for frontend red chips
            
            # Rename duplicates in both flat list and lines structure
            for row_idx, row in enumerate(lines):
                for item_idx, item in enumerate(row):
                    sanitized = self.node_generator.target_to_node_name(item)
                    
                    if sanitized in seen:
                        # Duplicate found - rename it!
                        seen[sanitized] += 1
                        duplicate_suffix = f"_duplicate{seen[sanitized]}"
                        renamed_item = f"{item}{duplicate_suffix}"
                        
                        # Update in lines structure
                        lines[row_idx][item_idx] = renamed_item
                        
                        # Update in flat items list
                        flat_index = sum(len(lines[r]) for r in range(row_idx)) + item_idx
                        raw_items[flat_index] = renamed_item
                        
                        # Track position for frontend
                        duplicate_positions.append(f"{row_idx}_{item_idx}")
                        
                        print(f"  🔍 Duplicate detected: '{sanitized}' at row {row_idx}, index {item_idx} → renamed to '{renamed_item}' (auto-unselected)")
                    else:
                        seen[sanitized] = 1  # First occurrence
            
            if duplicate_positions:
                print(f"  ✅ Detected {len(duplicate_positions)} duplicates (renamed and auto-unselected)")
            
            reordered_items = raw_items  # Keep ALL items (duplicates included)
            
            # Check if this is horizontal D-pad navigation
            if self.prediction.get('strategy') in ['dpad_with_screenshot', 'test_dpad_directions'] and self.prediction.get('menu_type') in ['horizontal', 'mixed']:
                
                # For mixed menu: only process Row 0 (horizontal), keep Row 1+ separate
                if self.prediction.get('menu_type') == 'mixed' and lines:
                    row0_items = lines[0]  # Row 0
                    other_items = []
                    for row_idx in range(1, len(lines)):
                        other_items.extend(lines[row_idx])  # Row 1+ items
                    print(f"  📊 Mixed menu: Row 0 = {row0_items}, Row 1+ = {other_items}")
                else:
                    row0_items = raw_items
                    other_items = []
                
                # Find home index in Row 0
                home_index = -1
                for i, item in enumerate(row0_items):
                    if item.lower() == 'home':
                        home_index = i
                        break
                
                if home_index > 0:
                    # Home found with items on left in Row 0
                    items_left_of_home = row0_items[:home_index]
                    items_right_of_home = row0_items[home_index + 1:]
                    
                    # ✅ CORRECT ORDER: [home, Row 0 RIGHT, Row 0 LEFT, Row 1+ vertical]
                    reordered_items = ['home'] + items_right_of_home + items_left_of_home + other_items
                    
                    print(f"  📊 Split Row 0 around home: {len(items_left_of_home)} left, {len(items_right_of_home)} right")
                    print(f"  🔄 Reordered for validation: {reordered_items}")
                else:
                    # Home at start or not found
                    items_right_of_home = row0_items[1:] if len(row0_items) > 1 else []
                    reordered_items = row0_items + other_items
                    print(f"  📊 No left items - home at start")
            
            # ✅ NEW: Build edge preview for frontend (calculate edges once!)
            edges_preview = self._build_edges_preview(
                raw_items=raw_items,
                lines=lines,
                strategy=self.prediction.get('strategy', 'click'),
                menu_type=self.prediction.get('menu_type', 'horizontal'),
                items_left_of_home=items_left_of_home,
                items_right_of_home=items_right_of_home
            )
            
            # Build reasoning for user
            reasoning = f"""Menu Type: {self.prediction.get('menu_type', 'unknown')}
Items Found: {len(self.prediction.get('items', []))} items
Predicted Depth: {self.prediction.get('predicted_depth', 1)} levels
Strategy: {self.prediction.get('strategy', 'unknown')}

AI identified the following menu items:
{', '.join(self.prediction.get('items', []))}

Exploration will navigate through these items using {self.prediction.get('strategy', 'default')} approach."""
            
            # Notify of prediction results
            if self.progress_callback:
                self.progress_callback(
                    step=f"Phase 1 Complete: Ready to explore {len(self.prediction.get('items', []))} items",
                    screenshot=self.initial_screenshot,
                    analysis={
                        'screen_name': 'Initial Analysis',
                        'elements_found': self.prediction.get('items', []),
                        'reasoning': reasoning
                    }
                )
            
            return {
                'success': True,
                'plan': {
                    'menu_type': self.prediction.get('menu_type'),
                    'items': reordered_items,
                    'lines': self.prediction.get('lines', []),
                    'duplicate_positions': duplicate_positions,
                    'strategy': self.prediction.get('strategy'),
                    'predicted_depth': self.prediction.get('predicted_depth', 1),
                    'reasoning': reasoning,
                    'screenshot': self.initial_screenshot,
                    'screen_name': 'Initial Screen',
                    'items_left_of_home': items_left_of_home,
                    'items_right_of_home': items_right_of_home,
                    'edges_preview': edges_preview
                }
            }
            
        except Exception as e:
            print(f"[@exploration_engine:analyze_and_plan] Error: {e}")
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
    
    def execute_exploration(self) -> Dict:
        """
        PHASE 2: Execute exploration based on approved plan
        
        Returns:
            {
                'success': True,
                'nodes_created': 3,
                'edges_created': 2,
                'subtrees_created': 1,
                'created_node_ids': ['home_temp', ...],
                'created_edge_ids': ['edge1_temp', ...],
                'created_subtree_ids': ['subtree1', ...]
            }
        """
        try:
            print(f"\n{'='*60}")
            print(f"[@exploration_engine] PHASE 2: Exploration Execution")
            print(f"{'='*60}\n")
            
            if not self.initial_screenshot or not self.prediction:
                return {
                    'success': False,
                    'error': 'Must run analyze_and_plan() first'
                }
            
            # PHASE 2: Validation - Explore to validate prediction
            self._phase2_validation(self.prediction, self.initial_screenshot)
            
            # Return results
            return {
                'success': True,
                'nodes_created': len(self.created_nodes),
                'edges_created': len(self.created_edges),
                'subtrees_created': len(self.created_subtrees),
                'created_node_ids': self.created_nodes,
                'created_edge_ids': self.created_edges,
                'created_subtree_ids': self.created_subtrees,
                'exploration_log': self.exploration_log
            }
            
        except Exception as e:
            print(f"[@exploration_engine:execute_exploration] Error: {e}")
            traceback.print_exc()
            return {
                'success': False,
                'error': str(e)
            }
    
    def explore_single_item(self, item: str, depth: int = 0) -> Dict:
        """
        Explore a SINGLE item (for incremental approval workflow)
        
        Args:
            item: Item name to explore (e.g., "Search", "Settings", "dynamic_1")
            depth: Current depth in exploration
        
        Returns:
            {
                'success': True,
                'node': {...},  # Node data created
                'edge': {...}   # Edge data created
            }
        """
        try:
            print(f"\n[@exploration_engine] Exploring single item: {item} (depth={depth})")
            
            # Get root node (or parent node for depth > 0)
            root_node_name = "home_temp"  # For now, always use home as source
            
            # Determine strategy
            strategy = self.prediction.get('strategy', 'click_elements')
            
            if strategy == 'click_elements':
                # Mobile/Web: Click-based
                return self._explore_single_item_click(root_node_name, item, depth)
            else:
                # TV/STB: DPAD-based (TODO)
                return {'success': False, 'error': 'DPAD strategy not yet implemented for single item'}
        
        except Exception as e:
            print(f"[@exploration_engine:explore_single_item] Error: {e}")
            traceback.print_exc()
            return {'success': False, 'error': str(e)}
    
    def _explore_single_item_click(self, source_node: str, item: str, depth: int) -> Dict:
        """
        Explore a single item using click-based navigation
        
        Args:
            source_node: Source node name (e.g., "home_temp")
            item: Item to click
            depth: Current depth
        
        Returns:
            Dict with success, node, edge
        """
        import time
        
        # Generate node name that would be created
        new_node_name = f"{item}_temp"
        
        # ✅ PROTECTION: Check if node already exists (important for subtrees)
        existing_node = get_node_by_id(self.tree_id, new_node_name, self.team_id)
        if existing_node.get('success') and existing_node.get('node'):
            print(f"    ⏭️ Node '{new_node_name}' already exists - skipping exploration")
            return {'success': False, 'error': f'Node {new_node_name} already exists'}
        
        # 1. Click element
        click_success = False
        if item.startswith('dynamic_'):
            # Dynamic content - skip for now (TODO: need bounds)
            return {'success': False, 'error': f'Dynamic element {item} not yet supported'}
        else:
            # Static element - click by text
            try:
                result = self.controller.click_element(text=item)
                click_success = result if isinstance(result, bool) else result.get('success', False)
            except Exception as e:
                print(f"    ❌ Click failed: {e}")
                return {'success': False, 'error': f'Click failed: {str(e)}'}
        
        if not click_success:
            return {'success': False, 'error': f'Click on {item} failed'}
        
        print(f"    ✅ Click succeeded")
        time.sleep(2)  # Wait for navigation
        
        # 2. Press BACK
        print(f"    ⬅️ Pressing BACK...")
        try:
            self.controller.press_key('BACK')
            time.sleep(2)
        except Exception as e:
            print(f"    ❌ BACK failed: {e}")
            back_success = False
        else:
            # 3. Verify we're back on source screen
            # Get a known source element (use first item from prediction if available)
            predicted_items = self.prediction.get('items', [])
            source_element = predicted_items[0] if predicted_items else 'Home'
            
            print(f"    🔍 Verifying source element '{source_element}' is visible...")
            try:
                is_back = self.controller.wait_for_element_by_text(
                    text=source_element,
                    timeout=5
                )
                back_success = is_back if isinstance(is_back, bool) else is_back.get('success', False)
            except Exception as e:
                print(f"    ⚠️ Back verification failed: {e}")
                back_success = False
        
        if back_success:
            print(f"    ✅ BACK succeeded - both directions valid")
        else:
            print(f"    ⚠️ BACK failed - only forward edge created")
        
        # 4. Create node and edge (node name already generated above for duplicate check)
        
        # Calculate position
        position_x = 250 + (len(self.created_nodes) % 3) * 300
        position_y = 250 + (len(self.created_nodes) // 3) * 200
        
        # Create node
        node_data = self.node_generator.create_node_data(
            node_name=new_node_name,
            position={'x': position_x, 'y': position_y},
            ai_analysis={
                'suggested_name': item,
                'screen_type': 'screen',
                'reasoning': f'Reached by clicking {item}'
            },
            node_type='screen'
        )
        
        node_result = save_node(self.tree_id, node_data, self.team_id)
        if not node_result['success']:
            return {'success': False, 'error': f"Failed to save node: {node_result.get('error')}"}
        
        self.created_nodes.append(new_node_name)
        print(f"    ✅ Created node: {new_node_name}")
        
        # Create edge with bidirectional action sets
        forward_actions = [
            {'command': 'click_element', 'params': {'text': item}, 'delay': 2000}
        ]
        
        backward_actions = [
            {'command': 'press_key', 'params': {'key': 'BACK'}, 'delay': 2000}
        ] if back_success else []
        
        edge_data = self.node_generator.create_edge_data(
            source=source_node,
            target=new_node_name,
            actions=forward_actions,
            reverse_actions=backward_actions
        )
        
        edge_result = save_edge(self.tree_id, edge_data, self.team_id)
        if not edge_result['success']:
            return {'success': False, 'error': f"Failed to save edge: {edge_result.get('error')}"}
        
        self.created_edges.append(edge_data['edge_id'])
        print(f"    ✅ Created edge: {source_node} ↔ {new_node_name} ({'bidirectional' if back_success else 'forward only'})")
        
        return {
            'success': True,
            'node': node_data,
            'edge': edge_data
        }
        
    def start_exploration(self) -> Dict:
        """
        Full exploration (Phase 1 + Phase 2 together)
        
        Returns:
            {
                'success': True,
                'nodes_created': 3,
                'edges_created': 2,
                'subtrees_created': 1,
                'exploration_log': [...]
            }
        """
        # Phase 1
        plan_result = self.analyze_and_plan()
        if not plan_result['success']:
            return plan_result
        
        # Phase 2
        return self.execute_exploration()
    
    def _phase1_anticipation(self, screenshot_path: str) -> Dict:
        """
        Phase 1: AI anticipates tree structure from first screenshot
        
        Args:
            screenshot_path: Path to initial screenshot
            
        Returns:
            Prediction dict from AI
        """
        print(f"\n[@exploration_engine] === PHASE 1: ANTICIPATION ===")
        print(f"[@exploration_engine] Screenshot: {screenshot_path}")
        print(f"[@exploration_engine] Device: {self.device_model_name}")
        
        try:
            # Check for cancellation before AI analysis
            if self.cancellation_check and self.cancellation_check():
                raise ValueError("Exploration was cancelled by user")

            prediction = self.screen_analyzer.anticipate_tree(screenshot_path)
            
            # Check if screen analysis returned empty results (no interactive elements)
            if prediction.get('error') or not prediction.get('items'):
                error_msg = prediction.get('error', 'No interactive elements detected')
                suggestion = prediction.get('suggestion', '')
                
                print(f"⚠️  [@exploration_engine:_phase1_anticipation] SCREEN ANALYSIS EMPTY")
                print(f"   Screenshot: {screenshot_path}")
                print(f"   Device: {self.device_model_name}")
                print(f"   Issue: {error_msg}")
                if suggestion:
                    print(f"   Suggestion: {suggestion}")
                
                # Raise clean error without stack trace
                raise ValueError(f"Screen analysis empty: {error_msg}")
                
        except ValueError as ve:
            # Clean error message (already logged above)
            raise
        except Exception as e:
            print(f"❌ [@exploration_engine:_phase1_anticipation] ANTICIPATION FAILED")
            print(f"   Screenshot: {screenshot_path}")
            print(f"   Device: {self.device_model_name}")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            raise  # Re-raise to be caught by caller
        
        print(f"Menu Type: {prediction.get('menu_type')}")
        print(f"Predicted Items: {prediction.get('items')}")
        print(f"Predicted Depth: {prediction.get('predicted_depth')}")
        print(f"Strategy: {prediction.get('strategy')}")
        
        self.exploration_log.append({
            'phase': 'anticipation',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'prediction': prediction
        })
        
        return prediction
    
    def _phase2_validation(self, prediction: Dict, initial_screenshot: str):
        """
        Phase 2: Validate predictions by testing navigation
        
        Strategy depends on device type:
        - Mobile/Web (click-based): Click element → if success, create forward edge → Press BACK → verify source visible
        - TV/STB (DPAD-based): Navigate with DPAD → Press OK → AI verify new screen → Press BACK → AI verify back
        
        Args:
            prediction: AI prediction from phase 1
            initial_screenshot: Path to initial screenshot
        """
        print(f"\n[@exploration_engine] === PHASE 2: VALIDATION ===")
        
        # Home node should already exist - userinterfaces have home by default
        root_node_name = "home"
        home_node_result = get_node_by_id(self.tree_id, root_node_name, self.team_id)
        if not (home_node_result.get('success') and home_node_result.get('node')):
            print(f"❌ Home node does not exist. Userinterface should have home node by default.")
            return
        
        print(f"✅ Using existing home node: {root_node_name}")
        
        # Determine strategy based on device type
        strategy = prediction.get('strategy', 'click_elements')
        
        if strategy == 'click_elements':
            # Mobile/Web: Click-based validation
            self._validate_click_based(
                current_node=root_node_name,
                prediction=prediction,
                depth=0
            )
        else:
            # TV/STB: DPAD-based validation (AI-guided)
            self._validate_dpad_based(
                current_node=root_node_name,
                parent_screenshot=initial_screenshot,
                prediction=prediction,
                depth=0
            )
    
    def _validate_click_based(
        self,
        current_node: str,
        prediction: Dict,
        depth: int
    ):
        """
        Mobile/Web validation: SIMPLE 1-LEVEL EXPLORATION
        
        Workflow for each item:
        1. Click element
        2. Wait 2s
        3. Press BACK
        4. Verify returned to home
        5. Create node and edge
        
        Args:
            current_node: Current node name (e.g., 'home_temp')
            prediction: AI prediction with items to click
            depth: Current depth (always 0 for simple exploration)
        """
        print(f"\n[@exploration_engine] 📱 MOBILE/WEB SIMPLE EXPLORATION: {current_node} (depth={depth})")
        
        predicted_items = prediction.get('items', [])
        print(f"  Items to explore: {len(predicted_items)}")
        
        # Get a known source element to verify BACK (use first item or 'Home')
        source_element = predicted_items[0] if predicted_items else 'Home'
        
        import time
        
        for i, item in enumerate(predicted_items):
            print(f"\n  [{i+1}/{len(predicted_items)}] Testing: {item}")
            
            # Generate node name that would be created
            new_node_name = f"{self.node_generator.target_to_node_name(item)}_temp"
            
            # ✅ PROTECTION: Check if node already exists (important for subtrees)
            existing_node = get_node_by_id(self.tree_id, new_node_name, self.team_id)
            if existing_node.get('success') and existing_node.get('node'):
                print(f"    ⏭️ Node '{new_node_name}' already exists - skipping exploration")
                continue
            
            # Notify progress
            if self.progress_callback:
                self.progress_callback(
                    step=f"Exploring {i+1}/{len(predicted_items)}: {item}",
                    screenshot=None,
                    analysis={'screen_name': item, 'elements_found': [item], 'reasoning': f'Clicking on {item}'}
                )
            
            # 1. Click element
            click_success = False
            if item.startswith('dynamic_'):
                print(f"    ⚠️ Dynamic element {item} - skipping")
                continue
            else:
                try:
                    result = self.controller.click_element(text=item)
                    click_success = result if isinstance(result, bool) else result.get('success', False)
                except Exception as e:
                    print(f"    ❌ Click failed: {e}")
                    click_success = False
            
            if not click_success:
                print(f"    ⏭️ Click failed - skipping {item}")
                continue
            
            print(f"    ✅ Click succeeded")
            time.sleep(2)
            
            # 2. Press BACK
            print(f"    ⬅️ Pressing BACK...")
            try:
                self.controller.press_key('BACK')
                time.sleep(2)
            except Exception as e:
                print(f"    ❌ BACK failed: {e}")
                continue
            
            # 3. Verify we're back on source screen
            print(f"    🔍 Verifying source element '{source_element}' is visible...")
            try:
                is_back = self.controller.wait_for_element_by_text(
                    text=source_element,
                    timeout=5
                )
                back_success = is_back if isinstance(is_back, bool) else is_back.get('success', False)
            except Exception as e:
                print(f"    ⚠️ Back verification failed: {e}")
                back_success = False
            
            if back_success:
                print(f"    ✅ BACK succeeded - both directions valid")
            else:
                print(f"    ⚠️ BACK failed - only forward edge created")
            
            # 4. Create node and edge (node name already generated above for duplicate check)
            
            # Calculate position
            position_x = 250 + (len(self.created_nodes) % 3) * 300
            position_y = 250 + (len(self.created_nodes) // 3) * 200
            
            # Create node
            node_data = self.node_generator.create_node_data(
                node_name=new_node_name,
                position={'x': position_x, 'y': position_y},
                ai_analysis={
                    'suggested_name': item,
                    'screen_type': 'screen',
                    'reasoning': f'Reached by clicking {item}'
                },
                node_type='screen'
            )
            
            node_result = save_node(self.tree_id, node_data, self.team_id)
            if node_result['success']:
                self.created_nodes.append(new_node_name)
                print(f"    ✅ Created node: {new_node_name}")
            else:
                print(f"    ❌ Failed to create node: {node_result.get('error')}")
                continue
            
            # Create edge with bidirectional action sets
            forward_actions = [
                {'command': 'click_element', 'params': {'text': item}, 'delay': 2000}
            ]
            
            backward_actions = [
                {'command': 'press_key', 'params': {'key': 'BACK'}, 'delay': 2000}
            ] if back_success else []
            
            edge_data = self.node_generator.create_edge_data(
                source=current_node,
                target=new_node_name,
                actions=forward_actions,
                reverse_actions=backward_actions
            )
            
            edge_result = save_edge(self.tree_id, edge_data, self.team_id)
            if edge_result['success']:
                self.created_edges.append(edge_data['edge_id'])
                print(f"    ✅ Created edge: {current_node} ↔ {new_node_name} ({'bidirectional' if back_success else 'forward only'})")
        
        print(f"\n[@exploration_engine] Simple exploration complete: {len(self.created_nodes)-1} nodes, {len(self.created_edges)} edges")
    
    def _validate_dpad_based(
        self,
        current_node: str,
        parent_screenshot: str,
        prediction: Dict,
        depth: int
    ):
        """
        TV/STB validation: DPAD-based navigation (AI verification required)
        
        Workflow:
        1. Navigate to item using DPAD
        2. AI verifies focus
        3. Press OK
        4. AI verifies new screen
        5. Press BACK
        6. AI verifies back to source
        
        Args:
            current_node: Current node name
            parent_screenshot: Screenshot at current position
            prediction: AI prediction
            depth: Current depth
        """
        # Call existing DPAD exploration logic
        self._explore_with_prediction(
            current_node=current_node,
            parent_screenshot=parent_screenshot,
            prediction=prediction,
            depth=depth
        )
    
    def _explore_with_prediction(
        self,
        current_node: str,
        parent_screenshot: str,
        prediction: Dict,
        depth: int
    ):
        """
        SMART exploration using AI prediction
        
        Strategy:
        1. Use predicted items to guide exploration
        2. Use menu type to determine navigation method
        3. Confirm predictions vs discover new items
        4. Recurse deeper for confirmed items
        
        Args:
            current_node: Current node name (with _temp)
            parent_screenshot: Screenshot at current position
            prediction: AI prediction (menu_type, items, etc)
            depth: Current depth in exploration
        """
        if depth >= self.depth_limit:
            print(f"[@exploration_engine] Max depth {self.depth_limit} reached")
            return
        
        print(f"\n[@exploration_engine] Smart Exploring: {current_node} (depth={depth})")
        
        # Extract prediction info
        menu_type = prediction.get('menu_type', 'mixed')
        predicted_items = prediction.get('items', [])
        
        print(f"  Menu Type: {menu_type}")
        print(f"  Predicted Items: {predicted_items}")
        
        confirmed_nodes = []
        
        # STRATEGY: Use prediction to guide exploration
        if menu_type == 'horizontal' and predicted_items:
            # Horizontal menu: Press RIGHT to move between items
            print(f"  🎯 Strategy: Horizontal menu with {len(predicted_items)} predicted items")
            
            for i, predicted_item in enumerate(predicted_items):
                print(f"\n  [{i+1}/{len(predicted_items)}] Looking for: {predicted_item}")
                
                # Move to position (press RIGHT i times from start)
                if i > 0:
                    self.navigation_strategy.test_direction('RIGHT', wait_time=500)
                
                # Press OK to enter
                ok_result = self.navigation_strategy.press_ok_and_analyze(parent_screenshot)
                
                # Notify progress
                if self.progress_callback and ok_result.get('screenshot'):
                    self.progress_callback(
                        step=f"Phase 2: Exploring item {i+1}/{len(predicted_items)}: {predicted_item}",
                        screenshot=ok_result['screenshot'],
                        analysis=ok_result.get('analysis')
                    )
                
                if ok_result['success'] and ok_result['is_new_screen']:
                    analysis = ok_result['analysis']
                    suggested_name = analysis.get('suggested_name', 'screen')
                    
                    # Check if prediction was correct
                    if predicted_item.lower() in suggested_name.lower():
                        print(f"  ✅ CONFIRMED: {predicted_item} (AI was right!)")
                    else:
                        print(f"  ⚠️  ADJUSTED: Expected '{predicted_item}', found '{suggested_name}'")
                    
                    # Create node with actual name
                    new_node_name = self.node_generator.generate_node_name(
                        ai_suggestion=suggested_name,
                        parent_node=current_node,
                        context_visible=analysis.get('context_visible', False)
                    )
                    
                    # Create and save node
                    confirmed_nodes.append(self._create_node_and_edge(
                        parent_node=current_node,
                        new_node_name=new_node_name,
                        analysis=analysis,
                        navigation_actions=[
                            {'command': 'RIGHT', 'params': {}, 'delay': 500} if i > 0 else None,
                            {'command': 'OK', 'params': {}, 'delay': 1000}
                        ],
                        after_screenshot=ok_result['after_screenshot'],
                        depth=depth
                    ))
                    
                    # Press BACK to return to menu
                    self.navigation_strategy.press_back_and_return()
                else:
                    print(f"  ⏭️  No new screen found")
                    self.navigation_strategy.press_back_and_return()
        
        elif menu_type == 'vertical' and predicted_items:
            # Vertical menu: Press DOWN to move between items
            print(f"  🎯 Strategy: Vertical menu with {len(predicted_items)} predicted items")
            
            for i, predicted_item in enumerate(predicted_items):
                print(f"\n  [{i+1}/{len(predicted_items)}] Looking for: {predicted_item}")
                
                if i > 0:
                    self.navigation_strategy.test_direction('DOWN', wait_time=500)
                
                ok_result = self.navigation_strategy.press_ok_and_analyze(parent_screenshot)
                
                if ok_result['success'] and ok_result['is_new_screen']:
                    analysis = ok_result['analysis']
                    suggested_name = analysis.get('suggested_name', 'screen')
                    
                    if predicted_item.lower() in suggested_name.lower():
                        print(f"  ✅ CONFIRMED: {predicted_item}")
                    else:
                        print(f"  ⚠️  ADJUSTED: Expected '{predicted_item}', found '{suggested_name}'")
                    
                    new_node_name = self.node_generator.generate_node_name(
                        ai_suggestion=suggested_name,
                        parent_node=current_node,
                        context_visible=analysis.get('context_visible', False)
                    )
                    
                    confirmed_nodes.append(self._create_node_and_edge(
                        parent_node=current_node,
                        new_node_name=new_node_name,
                        analysis=analysis,
                        navigation_actions=[
                            {'command': 'DOWN', 'params': {}, 'delay': 500} if i > 0 else None,
                            {'command': 'OK', 'params': {}, 'delay': 1000}
                        ],
                        after_screenshot=ok_result['after_screenshot'],
                        depth=depth
                    ))
                    
                    self.navigation_strategy.press_back_and_return()
        
        else:
            # Grid or mixed: Fallback to testing all directions
            print(f"  🎯 Strategy: Grid/Mixed menu - testing all directions")
            
            directions = self.navigation_strategy.get_directions_to_test(menu_type)
            
            for direction in directions:
                print(f"\n  Testing {direction}...")
                
                success = self.navigation_strategy.test_direction(direction, wait_time=500)
                
                if success:
                    ok_result = self.navigation_strategy.press_ok_and_analyze(parent_screenshot)
                    
                    if ok_result['success'] and ok_result['is_new_screen']:
                        analysis = ok_result['analysis']
                        
                        new_node_name = self.node_generator.generate_node_name(
                            ai_suggestion=analysis.get('suggested_name', 'screen'),
                            parent_node=current_node,
                            context_visible=analysis.get('context_visible', False)
                        )
                        
                        confirmed_nodes.append(self._create_node_and_edge(
                            parent_node=current_node,
                            new_node_name=new_node_name,
                            analysis=analysis,
                            navigation_actions=[
                                {'command': direction, 'params': {}, 'delay': 500},
                                {'command': 'OK', 'params': {}, 'delay': 1000}
                            ],
                            after_screenshot=ok_result['after_screenshot'],
                            depth=depth
                        ))
                        
                        self.navigation_strategy.press_back_and_return()
        
        # Recurse deeper into confirmed nodes
        print(f"\n[@exploration_engine] Recursing into {len(confirmed_nodes)} confirmed nodes...")
        
        for node_info in confirmed_nodes:
            if node_info and depth + 1 < self.depth_limit:
                # For deeper levels, re-analyze the screen to get new prediction
                new_screenshot = node_info.get('screenshot')
                
                if new_screenshot:
                    # Get fresh prediction for this screen
                    deeper_prediction = self.screen_analyzer.anticipate_tree(new_screenshot)
                    
                    # Recurse with new prediction
                    self._explore_with_prediction(
                        current_node=node_info['node_name'],
                        parent_screenshot=new_screenshot,
                        prediction=deeper_prediction,
                        depth=depth + 1
                    )
    
    def _create_node_and_edge(
        self,
        parent_node: str,
        new_node_name: str,
        analysis: Dict,
        navigation_actions: List[Dict],
        after_screenshot: str,
        depth: int
    ) -> Dict:
        """
        Helper to create node and edge, returns node info for recursion
        
        Returns:
            Dict with node_name and screenshot for deeper exploration
        """
        # Calculate position (simple grid layout)
        position_x = 250 + (len(self.created_nodes) % 3) * 300
        position_y = 250 + (len(self.created_nodes) // 3) * 200
        
        # Create node
        node_data = self.node_generator.create_node_data(
            node_name=new_node_name,
            position={'x': position_x, 'y': position_y},
            ai_analysis=analysis
        )
        
        # Save node to database
        node_result = save_node(self.tree_id, node_data, self.team_id)
        
        if not node_result['success']:
            print(f"    ❌ Failed to create node: {node_result.get('error')}")
            return None
        
        self.created_nodes.append(new_node_name)
        print(f"    ✅ Created node: {new_node_name}")
        
        # Create edge from parent to new node
        # Filter out None actions
        clean_actions = [a for a in navigation_actions if a is not None]
        
        edge_data = self.node_generator.create_edge_data(
            source=parent_node,
            target=new_node_name,
            actions=clean_actions
        )
        
        edge_result = save_edge(self.tree_id, edge_data, self.team_id)
        
        if edge_result['success']:
            self.created_edges.append(edge_data['edge_id'])
            print(f"    ✅ Created edge: {parent_node} → {new_node_name}")
        
        # Check if subtree should be created
        if self.node_generator.should_create_subtree(new_node_name, depth + 1):
            print(f"    🌲 Creating subtree for: {new_node_name}")
            
            subtree_result = create_sub_tree(
                parent_tree_id=self.tree_id,
                parent_node_id=new_node_name,
                tree_data={
                    'name': f'{new_node_name}_subtree',
                    'userinterface_id': None
                },
                team_id=self.team_id
            )
            
            if subtree_result['success']:
                self.created_subtrees.append(subtree_result['tree']['id'])
                print(f"    ✅ Subtree created: {subtree_result['tree']['id']}")
        
        return {
            'node_name': new_node_name,
            'screenshot': after_screenshot
        }

