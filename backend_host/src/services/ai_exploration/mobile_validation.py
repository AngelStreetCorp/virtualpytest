"""
Mobile/Web Validation Strategy - Click-based navigation testing

Handles Mobile/Web-specific navigation validation:
- Click-based navigation (click_element)
- BACK button navigation
- Home verification after BACK
- Recovery navigation if validation fails
"""

import time
from typing import Dict, Any, Optional
from backend_host.src.services.ai_exploration.node_generator import NodeGenerator
from shared.src.lib.database.navigation_trees_db import get_edge_by_id, save_edge


class MobileValidationStrategy:
    """Mobile/Web validation strategy"""
    
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
        Validate Mobile/Web item
        
        Process:
        1. Click element to navigate
        2. Capture screenshot + dump
        3. Press BACK to return
        4. Verify home screen
        5. Recovery if BACK failed
        
        Returns:
            {
                'success': True,
                'item': str,
                'click_result': str,
                'back_result': str,
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
            if 'home' in node_name.lower() and node_name != 'home_temp' and node_name != self.executor.exploration_state.get('home_id', 'home'):
                print(f"[@MobileValidation] ⏭️  Skipping home/start node: {node_name}")
                self.executor.exploration_state['current_validation_index'] = current_index + 1
                return self.executor.validate_next_item()
        
        # Capture HOME dump before first navigation
        controller = self.exploration_engine.controller
        if current_index == 0:
            self._capture_home_dump(controller)
        
        print(f"[@MobileValidation] Validating {current_index + 1}/{len(items_to_validate)}")
        print(f"  Target: {current_item} → {node_name}")
        
        with self.executor._lock:
            self.executor.exploration_state['status'] = 'validating'
            self.executor.exploration_state['current_step'] = f"Validating {current_index + 1}/{len(items_to_validate)}: {current_item}"
        
        # Get context
        home_indicator = self.executor.exploration_state['exploration_plan']['items'][0]
        
        # Execute validation
        click_result = 'failed'
        back_result = 'failed'
        screenshot_url = None
        
        # 1. Click navigation
        try:
            result = controller.click_element(current_item)
            
            import inspect
            if inspect.iscoroutine(result):
                import asyncio
                result = asyncio.run(result)
            
            click_success = result if isinstance(result, bool) else result.get('success', False)
            click_result = 'success' if click_success else 'failed'
            print(f"    {'✅' if click_success else '❌'} Click {click_result}")
            time.sleep(5)
            
            # Capture screenshot + dump if click succeeded
            if click_success:
                screenshot_url, dump_data = self.executor._capture_screen_data(
                    node_name,
                    node_name.replace('_temp', ''),
                    controller
                )
        except Exception as e:
            print(f"    ❌ Click failed: {e}")
        
        # 2. BACK navigation + home verification
        if click_result == 'success':
            back_result = self._execute_back_with_verification(controller, home_indicator, tree_id, team_id)
        
        # 3. Recovery if needed
        if click_result == 'failed' or back_result == 'failed':
            recovery_result = self._execute_recovery(click_result, back_result, current_item, current_index, len(items_to_validate))
            if not recovery_result.get('success'):
                return recovery_result
            
            # Update back_result if recovery succeeded
            if back_result == 'failed':
                back_result = 'failed_recovered'
        
        # 4. Update edge validation status
        self._update_edge_validation(tree_id, team_id, node_name, click_result, back_result)
        
        # 5. Update state and return
        with self.executor._lock:
            home_id = self.executor.exploration_state['home_id']
            self.executor.exploration_state['current_validation_index'] = current_index + 1
            has_more = self.executor.exploration_state['current_validation_index'] < len(items_to_validate)
            
            if not has_more:
                self.executor.exploration_state['status'] = 'validation_complete'
                self.executor.exploration_state['current_step'] = 'Edge validation complete - ready for node verification'
            else:
                self.executor.exploration_state['status'] = 'awaiting_validation'
                next_index = self.executor.exploration_state['current_validation_index']
                next_item = items_to_validate[next_index]
                next_node_name = target_to_node_map.get(next_item, f"{next_item}_temp")
                next_node_display = next_node_name.replace('_temp', '')
                self.executor.exploration_state['current_step'] = f"Ready: Step {next_index + 1}/{len(items_to_validate)} - home → {next_node_display}"
            
            node_name_display = node_name.replace('_temp', '')
            
            return {
                'success': True,
                'item': current_item,
                'node_name': node_name_display,
                'node_id': node_name,
                'click_result': click_result,
                'back_result': back_result,
                'edge_updated': True,
                'has_more_items': has_more,
                'screenshot_url': screenshot_url,
                'action_sets': {
                    'forward': {
                        'source': home_id,
                        'target': node_name_display,
                        'action': f'click_element("{current_item}")',
                        'result': click_result
                    },
                    'reverse': {
                        'source': node_name_display,
                        'target': home_id,
                        'action': 'press_key(BACK)',
                        'result': back_result
                    }
                },
                'progress': {
                    'current_item': self.executor.exploration_state['current_validation_index'],
                    'total_items': len(items_to_validate)
                }
            }
    
    def _capture_home_dump(self, controller):
        """Capture HOME dump before first navigation"""
        try:
            print(f"[@MobileValidation] 🏠 Capturing HOME dump...")
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
    
    def _execute_back_with_verification(self, controller, home_indicator: str, tree_id: str, team_id: str) -> str:
        """Execute BACK and verify home screen"""
        try:
            # Select verification controller based on device model
            device_model = self.device.device_model.lower()
            verifier = None
            
            if 'mobile' in device_model:
                # Mobile: Use ADB verification
                for v in self.device.get_controllers('verification'):
                    if getattr(v, 'verification_type', None) == 'adb':
                        verifier = v
                        print(f"    📱 Using ADB verification for mobile device")
                        break
            elif 'host' in device_model:
                # Web: Use controller itself
                verifier = controller
                print(f"    🌐 Using Playwright controller for web verification")
            
            # Execute BACK
            press_result = controller.press_key('BACK')
            import inspect
            if inspect.iscoroutine(press_result):
                import asyncio
                asyncio.run(press_result)
            time.sleep(5)
            
            print(f"    🔍 Verifying return to home: {home_indicator}")
            
            # Verify home
            back_success = self._verify_home_element(verifier, home_indicator, device_model, attempt=1)
            
            # Double-back fallback if first attempt failed
            if not back_success:
                print(f"    🔄 Trying second BACK...")
                press_result = controller.press_key('BACK')
                import inspect
                if inspect.iscoroutine(press_result):
                    import asyncio
                    asyncio.run(press_result)
                time.sleep(5)
                
                back_success = self._verify_home_element(verifier, home_indicator, device_model, attempt=2)
            
            return 'success' if back_success else 'failed'
            
        except Exception as e:
            print(f"    ⚠️ Back failed: {e}")
            return 'failed'
    
    def _verify_home_element(self, verifier, home_indicator: str, device_model: str, attempt: int) -> bool:
        """Verify home element is present"""
        if not verifier:
            print(f"    ⚠️ No verifier available for device model '{device_model}'")
            return False
        
        try:
            if 'host' in device_model:
                # Web: Check if home element exists
                dump_result = verifier.dump_elements()
                import inspect
                if inspect.iscoroutine(dump_result):
                    import asyncio
                    dump_result = asyncio.run(dump_result)
                
                if isinstance(dump_result, dict) and dump_result.get('success'):
                    elements = dump_result.get('elements', [])
                    found = any(
                        home_indicator.lower() in str(elem.get('text', '')).lower() or
                        home_indicator.lower() in str(elem.get('selector', '')).lower()
                        for elem in elements
                    )
                    message = f"Element '{home_indicator}' {'found' if found else 'not found'} in page"
                    print(f"    {'✅' if found else '❌'} Back ({attempt}{'st' if attempt==1 else 'nd'}) {('success' if found else 'failed')}: {message}")
                    return found
                else:
                    print(f"    ❌ Back ({attempt}{'st' if attempt==1 else 'nd'}) failed: Could not dump elements")
                    return False
            else:
                # Mobile: Use waitForElementToAppear
                import inspect
                timeout = 3.0 if attempt == 1 else 5.0
                if inspect.iscoroutinefunction(verifier.waitForElementToAppear):
                    import asyncio
                    success, message, details = asyncio.run(verifier.waitForElementToAppear(
                        search_term=home_indicator,
                        timeout=timeout
                    ))
                else:
                    success, message, details = verifier.waitForElementToAppear(
                        search_term=home_indicator,
                        timeout=timeout
                    )
                print(f"    {'✅' if success else '❌'} Back ({attempt}{'st' if attempt==1 else 'nd'}) {('success' if success else 'failed')}: {message}")
                return success
        except Exception as e:
            print(f"    ❌ Back ({attempt}{'st' if attempt==1 else 'nd'}) failed: {e}")
            return False
    
    def _execute_recovery(self, click_result: str, back_result: str, current_item: str, current_index: int, total_items: int) -> Dict[str, Any]:
        """Execute recovery navigation if validation failed"""
        print(f"    🔄 Validation failed (click={click_result}, back={back_result}) - going home...")
        nav_result = self.executor._navigate_to_home()
        
        if nav_result.get('success'):
            print(f"    ✅ Recovery successful - ready for next validation")
            return {'success': True}
        else:
            error_msg = nav_result.get('error', 'Unknown error')
            print(f"    🛑 STOPPING validation - recovery failed")
            with self.executor._lock:
                self.executor.exploration_state['status'] = 'validation_failed'
                self.executor.exploration_state['error'] = f"Validation recovery failed: {error_msg}"
                self.executor.exploration_state['current_step'] = 'Validation stopped - recovery failed'
            
            return {
                'success': False,
                'error': f"Validation stopped: Cannot recover to home.\nReason: {error_msg}",
                'validation_stopped': True,
                'failed_at_item': current_item,
                'failed_at_index': current_index
            }
    
    def _update_edge_validation(self, tree_id: str, team_id: str, node_name: str, click_result: str, back_result: str):
        """Update edge with validation results"""
        try:
            start_node_id = self.executor.exploration_state.get('home_id', 'home')
            
            # Edge ID is clean (no _temp)
            node_name_clean = node_name.replace('_temp', '')
            edge_id = f"edge_{start_node_id}_to_{node_name_clean}"
            
            edge_result = get_edge_by_id(tree_id, edge_id, team_id)
            
            if edge_result['success']:
                edge = edge_result['edge']
                action_sets = edge.get('action_sets', [])
                
                if len(action_sets) >= 2:
                    # Update forward direction (action_sets[0])
                    if action_sets[0].get('actions') and len(action_sets[0]['actions']) > 0:
                        action_sets[0]['actions'][0]['validation_status'] = click_result
                        action_sets[0]['actions'][0]['validated_at'] = time.time()
                        action_sets[0]['actions'][0]['actual_result'] = click_result
                    
                    # Update reverse direction (action_sets[1])
                    if action_sets[1].get('actions') and len(action_sets[1]['actions']) > 0:
                        action_sets[1]['actions'][0]['validation_status'] = back_result
                        action_sets[1]['actions'][0]['validated_at'] = time.time()
                        action_sets[1]['actions'][0]['actual_result'] = back_result
                    
                    # Save updated edge
                    save_edge(tree_id, edge, team_id)
        except Exception as e:
            print(f"    ⚠️ Failed to update edge validation: {e}")

