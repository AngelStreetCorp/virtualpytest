"""
Navigation Strategy - Depth-first exploration with DPAD testing
Executes navigation commands and analyzes results
"""

import time
from typing import Dict, List, Optional


class NavigationStrategy:
    """Depth-first exploration strategy with DPAD testing"""
    
    def __init__(self, controller, screen_analyzer):
        """
        Initialize with controller and AI analyzer
        
        Args:
            controller: Device controller (from ControllerFactory)
            screen_analyzer: ScreenAnalyzer instance
        """
        self.controller = controller
        self.screen_analyzer = screen_analyzer
        
    def test_direction(self, direction: str, wait_time: int = 500) -> bool:
        """
        Test a DPAD direction (RIGHT, LEFT, UP, DOWN)
        
        Note: For DPAD, we DON'T call is_new_screen() - optimization!
        Just test and move on. We only analyze after OK/BACK.
        
        Args:
            direction: 'DPAD_RIGHT', 'DPAD_LEFT', 'DPAD_UP', 'DPAD_DOWN'
            wait_time: Wait time in ms after command
            
        Returns:
            True if command executed successfully
        """
        try:
            # Map direction to controller command
            command_map = {
                'RIGHT': 'DPAD_RIGHT',
                'LEFT': 'DPAD_LEFT',
                'UP': 'DPAD_UP',
                'DOWN': 'DPAD_DOWN',
                'DPAD_RIGHT': 'DPAD_RIGHT',
                'DPAD_LEFT': 'DPAD_LEFT',
                'DPAD_UP': 'DPAD_UP',
                'DPAD_DOWN': 'DPAD_DOWN'
            }
            
            command = command_map.get(direction, direction)
            
            print(f"[@navigation_strategy:test_direction] Testing {command}")
            
            # Execute command with params dict (not delay= keyword)
            result = self.controller.execute_command(command, params={'wait_time': wait_time})
            
            return result.get('success', False)
            
        except Exception as e:
            print(f"[@navigation_strategy:test_direction] Error: {e}")
            return False
    
    def press_ok_and_analyze(self, before_screenshot: str) -> Dict:
        """
        Press OK and analyze if we entered new screen
        
        Args:
            before_screenshot: Path to screenshot before OK
            
        Returns:
            {
                'success': True,
                'is_new_screen': True/False,
                'analysis': {...},
                'after_screenshot': 'path'
            }
        """
        try:
            print(f"[@navigation_strategy:press_ok_and_analyze] Pressing OK...")
            
            # Press OK button with params dict
            ok_result = self.controller.execute_command('OK', params={'wait_time': 1000})
            
            if not ok_result.get('success', False):
                return {
                    'success': False,
                    'error': 'Failed to execute OK command'
                }
            
            # Wait for screen to stabilize
            time.sleep(1)
            
            # Capture new screenshot
            after_screenshot = self.screen_analyzer.capture_screenshot()
            
            if not after_screenshot:
                return {
                    'success': False,
                    'error': 'Failed to capture screenshot after OK'
                }
            
            # AI analyzes: is this a new screen?
            analysis = self.screen_analyzer.is_new_screen(
                before_path=before_screenshot,
                after_path=after_screenshot,
                action='OK'
            )
            
            return {
                'success': True,
                'is_new_screen': analysis.get('is_new_screen', False),
                'analysis': analysis,
                'after_screenshot': after_screenshot
            }
            
        except Exception as e:
            print(f"[@navigation_strategy:press_ok_and_analyze] Error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def press_back_and_return(self) -> bool:
        """
        Press BACK to return to previous screen
        
        Returns:
            True if successful
        """
        try:
            print(f"[@navigation_strategy:press_back_and_return] Pressing BACK...")
            
            result = self.controller.execute_command('BACK', params={'wait_time': 1000})
            
            # Wait for screen to stabilize
            time.sleep(0.5)
            
            return result.get('success', False)
            
        except Exception as e:
            print(f"[@navigation_strategy:press_back_and_return] Error: {e}")
            return False
    
    def get_directions_to_test(self, menu_type: str) -> List[str]:
        """
        Based on AI prediction, determine which directions to test
        
        Args:
            menu_type: 'horizontal', 'vertical', 'grid', 'mixed'
            
        Returns:
            List of directions to test (e.g., ['RIGHT', 'LEFT'])
        """
        if menu_type == 'horizontal':
            return ['RIGHT', 'LEFT']
        elif menu_type == 'vertical':
            return ['UP', 'DOWN']
        elif menu_type == 'grid':
            return ['RIGHT', 'DOWN', 'LEFT', 'UP']
        else:  # mixed or unknown
            return ['RIGHT', 'DOWN', 'LEFT', 'UP']
    
    def navigate_to_home(self) -> bool:
        """
        Navigate to home screen (emergency reset)
        Press HOME button if available
        
        Returns:
            True if successful
        """
        try:
            print(f"[@navigation_strategy:navigate_to_home] Navigating to home...")
            
            # Try HOME button first with params dict
            result = self.controller.execute_command('KEY_HOME', params={'wait_time': 1000})
            
            if result.get('success', False):
                time.sleep(1)
                return True
            
            # Fallback: press BACK multiple times
            for _ in range(5):
                self.press_back_and_return()
                time.sleep(0.3)
            
            return True
            
        except Exception as e:
            print(f"[@navigation_strategy:navigate_to_home] Error: {e}")
            return False

