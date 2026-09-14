"""
TV Validation Strategy - Dual-layer depth-first edge testing

Handles TV-specific navigation validation:
- Multi-row menu structure (Row 1: horizontal, Rows 2+: vertical)
- Focus nodes (menu positions): home_tvguide, home_apps, etc.
- Screen nodes (actual screens): tvguide, apps, etc.
- D-pad navigation: RIGHT/LEFT within rows, DOWN/UP between rows
- Vertical navigation: OK to enter screens, BACK to exit
"""

import time
from typing import Dict, Any, Optional
from backend_host.src.services.ai_exploration.node_generator import NodeGenerator


class TVValidationStrategy:
    """TV dual-layer validation strategy"""
    
    def __init__(self, executor):
        """
        Args:
            executor: ExplorationExecutor instance (has device, state, helpers)
        """
        self.executor = executor
        self.device = executor.device
        self.exploration_engine = executor.exploration_engine
    
    def validate_item(self) -> Dict[str, Any]:
        """
        Validate TV item using depth-first approach
        
        Row structure:
        - Row 0: home (starting point)
        - Row 1: horizontal menu (RIGHT/LEFT between focus nodes)
        - Rows 2+: vertical menu (DOWN/UP between focus nodes)
        
        For each item:
        1. Navigate to focus node (RIGHT or DOWN)
        2. Enter screen (OK)
        3. Capture screenshot + dump
        4. Exit screen (BACK)
        
        Returns:
            {
                'success': True,
                'item': str,
                'edges': [...],
                'has_more_items': bool
            }
        """
        with self.executor._lock:
            tree_id = self.executor.exploration_state['tree_id']
            team_id = self.executor.exploration_state['team_id']
            current_index = self.executor.exploration_state['current_validation_index']
            items_to_validate = self.executor.exploration_state['items_to_validate']
            current_item = items_to_validate[current_index]
            target_to_node_map = self.executor.exploration_state['target_to_node_map']
            node_name = target_to_node_map.get(current_item)
            
            if not node_name:
                node_gen = NodeGenerator(tree_id, team_id)
                node_name_clean = node_gen.target_to_node_name(current_item)
                node_name = f"{node_name_clean}_temp"
            
            # Skip home
            if 'home' in node_name.lower() and node_name != 'home_temp':
                print(f"[@TVValidation] ⏭️  Skipping home node: {node_name}")
                self.executor.exploration_state['current_validation_index'] = current_index + 1
                return self.executor.validate_next_item()
        
        # Capture HOME dump before first navigation
        controller = self.exploration_engine.controller
        if current_index == 0:
            self._capture_home_dump(controller)
        
        print(f"[@TVValidation] Validating {current_index + 1}/{len(items_to_validate)}")
        print(f"  Target: {current_item} → {node_name}")
        
        with self.executor._lock:
            self.executor.exploration_state['status'] = 'validating'
            self.executor.exploration_state['current_step'] = f"Validating {current_index + 1}/{len(items_to_validate)}: {current_item}"
        
        # Calculate navigation
        nav_plan = self._calculate_navigation(current_index, current_item, tree_id, team_id)
        
        # Execute recovery if needed
        self._execute_recovery(nav_plan, tree_id, team_id)
        
        # Execute validation edges
        return self._execute_validation_edges(
            nav_plan,
            current_item,
            current_index,
            len(items_to_validate),
            controller
        )
    
    def _capture_home_dump(self, controller):
        """Capture HOME dump before first navigation"""
        try:
            print(f"[@TVValidation] 🏠 Capturing HOME dump...")
            home_dump_data = None
            home_screenshot_url = self.executor.exploration_state.get('current_analysis', {}).get('screenshot')
            
            if hasattr(controller, 'dump_elements') and callable(getattr(controller, 'dump_elements')):
                dump_result = controller.dump_elements()
                import inspect
                if inspect.iscoroutine(dump_result):
                    import asyncio
                    dump_result = asyncio.run(dump_result)
                
                if isinstance(dump_result, tuple):
                    success, elements, error = dump_result
                    if success and elements:
                        home_dump_data = {'elements': elements}
                elif isinstance(dump_result, dict):
                    home_dump_data = dump_result
            
            if home_dump_data or home_screenshot_url:
                with self.executor._lock:
                    if 'node_verification_data' not in self.executor.exploration_state:
                        self.executor.exploration_state['node_verification_data'] = []
                    
                    self.executor.exploration_state['node_verification_data'].append({
                        'node_id': self.executor.exploration_state.get('home_id', 'home'),
                        'node_label': 'home',
                        'dump': home_dump_data,
                        'screenshot_url': home_screenshot_url
                    })
                print(f"    ✅ Home data stored")
        except Exception as e:
            print(f"    ⚠️ Failed to capture Home dump: {e}")
    
    def _calculate_navigation(self, current_index: int, current_item: str, tree_id: str, team_id: str) -> Dict[str, Any]:
        """Calculate navigation direction and recovery needs for TV menu"""
        lines = self.executor.exploration_state.get('exploration_plan', {}).get('lines', [])
        items_to_validate = self.executor.exploration_state['items_to_validate']
        
        node_gen = NodeGenerator(tree_id, team_id)
        screen_node_name = node_gen.target_to_node_name(current_item)
        focus_node_name = f"home_{screen_node_name}"
        
        # Find current item's position in row structure
        current_row_index = -1
        current_position_in_row = -1
        for row_idx, row_items in enumerate(lines):
            if current_item in row_items:
                current_row_index = row_idx
                current_position_in_row = row_items.index(current_item)
                break
        
        # Find previous item's position
        prev_row_index = -1
        prev_position_in_row = -1
        if current_index > 0:
            prev_item = items_to_validate[current_index - 1]
            for row_idx, row_items in enumerate(lines):
                if prev_item in row_items:
                    prev_row_index = row_idx
                    prev_position_in_row = row_items.index(prev_item)
                    break
        
        # Determine navigation type
        is_same_row = (prev_row_index == current_row_index) and (prev_row_index != -1)
        is_first_item_overall = (current_index == 0)
        
        if is_first_item_overall:
            # Check if 'home' is in current row
            home_in_current_row = False
            if current_row_index >= 0 and current_row_index < len(lines):
                home_in_current_row = 'home' in [item.lower() for item in lines[current_row_index]]
            
            prev_focus_name = 'home'
            nav_direction = 'RIGHT' if home_in_current_row else 'DOWN'
            needs_home_recovery = nav_direction == 'DOWN'
            needs_row_recovery = False
        elif is_same_row:
            # Same row: horizontal navigation
            prev_item_name = node_gen.target_to_node_name(items_to_validate[current_index - 1])
            prev_focus_name = f"home_{prev_item_name}"
            nav_direction = 'RIGHT'
            needs_home_recovery = False
            needs_row_recovery = False
        else:
            # Different rows: vertical navigation
            prev_focus_name = 'home'
            nav_direction = 'DOWN'
            needs_home_recovery = False
            needs_row_recovery = True
        
        return {
            'screen_node_name': screen_node_name,
            'focus_node_name': focus_node_name,
            'prev_focus_name': prev_focus_name,
            'nav_direction': nav_direction,
            'reverse_direction': 'LEFT' if nav_direction == 'RIGHT' else 'UP',
            'current_row_index': current_row_index,
            'current_position_in_row': current_position_in_row,
            'needs_home_recovery': needs_home_recovery,
            'needs_row_recovery': needs_row_recovery,
            'is_first_item': is_first_item_overall
        }
    
    def _execute_recovery(self, nav_plan: Dict, tree_id: str, team_id: str):
        """Execute recovery navigation if needed"""
        if nav_plan['needs_home_recovery']:
            print(f"\n    🔄 ROW {nav_plan['current_row_index'] + 1} START: Ensuring we're at home...")
            nav_result = self.executor._navigate_to_home()
            if nav_result.get('success'):
                print(f"    ✅ At home - ready for DOWN navigation")
        elif nav_plan['needs_row_recovery']:
            print(f"\n    🔽 ROW {nav_plan['current_row_index'] + 1} TRANSITION: Returning to home...")
            nav_result = self.executor._navigate_to_home()
            if nav_result.get('success'):
                print(f"    ✅ Back at home - ready for DOWN navigation")
    
    def _execute_validation_edges(
        self,
        nav_plan: Dict,
        current_item: str,
        current_index: int,
        total_items: int,
        controller
    ) -> Dict[str, Any]:
        """Execute the 3 validation edges for TV dual-layer"""
        screen_node_name = nav_plan['screen_node_name']
        focus_node_name = nav_plan['focus_node_name']
        prev_focus_name = nav_plan['prev_focus_name']
        nav_direction = nav_plan['nav_direction']
        reverse_direction = nav_plan['reverse_direction']
        
        print(f"\n  🎮 TV DUAL-LAYER VALIDATION")
        print(f"     Edges to test:")
        print(f"       1. {prev_focus_name} → {focus_node_name}: {nav_direction}")
        print(f"       2. {focus_node_name} ↓ {screen_node_name}: OK")
        print(f"       3. {screen_node_name} ↑ {focus_node_name}: BACK")
        
        edge_results = {
            'horizontal': 'pending',
            'enter': 'pending',
            'exit': 'pending'
        }
        screenshot_url = None
        
        # Edge 1: Focus navigation (RIGHT/DOWN)
        try:
            print(f"\n    Edge 1/3: {prev_focus_name} → {focus_node_name}")
            result = controller.press_key(nav_direction)
            import inspect
            if inspect.iscoroutine(result):
                import asyncio
                result = asyncio.run(result)
            
            edge_results['horizontal'] = 'success'
            print(f"    ✅ Focus navigation: {nav_direction}")
            time.sleep(1.5)
        except Exception as e:
            edge_results['horizontal'] = 'failed'
            print(f"    ❌ Focus navigation failed: {e}")
        
        # Edge 2: Vertical enter (OK) - with screenshot + dump
        try:
            print(f"\n    Edge 2/3: {focus_node_name} ↓ {screen_node_name}")
            result = controller.press_key('OK')
            import inspect
            if inspect.iscoroutine(result):
                import asyncio
                result = asyncio.run(result)
            
            edge_results['enter'] = 'success'
            print(f"    ✅ Vertical enter: OK")
            time.sleep(3)
            
            # Capture screenshot + dump using helper
            screenshot_url, dump_data = self.executor._capture_screen_data(
                f"{screen_node_name}_temp",
                screen_node_name,
                controller
            )
        except Exception as e:
            edge_results['enter'] = 'failed'
            print(f"    ❌ Vertical enter failed: {e}")
        
        # Edge 3: Vertical exit (BACK)
        try:
            print(f"\n    Edge 3/3: {screen_node_name} ↑ {focus_node_name}")
            result = controller.press_key('BACK')
            import inspect
            if inspect.iscoroutine(result):
                import asyncio
                asyncio.run(result)
            
            edge_results['exit'] = 'success'
            print(f"    ✅ Vertical exit: BACK")
            time.sleep(2)
        except Exception as e:
            edge_results['exit'] = 'failed'
            print(f"    ❌ Vertical exit failed: {e}")
        
        # Update state
        with self.executor._lock:
            self.executor.exploration_state['current_validation_index'] = current_index + 1
            has_more = (current_index + 1) < total_items
            
            if not has_more:
                self.executor.exploration_state['status'] = 'validation_complete'
                self.executor.exploration_state['current_step'] = 'Edge validation complete - ready for node verification'
            else:
                self.executor.exploration_state['status'] = 'awaiting_validation'
        
        # Return results
        return {
            'success': True,
            'item': current_item,
            'node_name': focus_node_name,
            'node_id': f"{focus_node_name}_temp",
            'has_more_items': has_more,
            'screenshot_url': screenshot_url,
            'edges': [
                {
                    'edge_type': 'horizontal',
                    'action_sets': {
                        'forward': {
                            'source': prev_focus_name,
                            'target': focus_node_name,
                            'action': nav_direction,
                            'result': edge_results['horizontal']
                        },
                        'reverse': {
                            'source': focus_node_name,
                            'target': prev_focus_name,
                            'action': reverse_direction,
                            'result': edge_results['horizontal']
                        }
                    }
                },
                {
                    'edge_type': 'vertical',
                    'action_sets': {
                        'forward': {
                            'source': focus_node_name,
                            'target': screen_node_name,
                            'action': 'OK',
                            'result': edge_results['enter']
                        },
                        'reverse': {
                            'source': screen_node_name,
                            'target': focus_node_name,
                            'action': 'BACK',
                            'result': edge_results['exit']
                        }
                    }
                }
            ],
            'progress': {
                'current_item': current_index + 1,
                'total_items': total_items
            }
        }

