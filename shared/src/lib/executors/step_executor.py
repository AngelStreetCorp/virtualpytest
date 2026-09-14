"""
Simple Step Executor Wrapper for VirtualPyTest

Lightweight wrapper that standardizes step creation without changing existing executors.
Converts executor results to standardized step dictionaries for consistent reporting.
"""

import time
from typing import Dict, List, Any, Optional


class StepExecutor:
    """Simple wrapper that creates standardized steps from existing executor results"""
    
    def __init__(self, context):
        """Initialize with script execution context"""
        self.context = context
    
    def create_navigation_step(self, nav_result: dict, from_node: str, to_node: str) -> dict:
        """Convert NavigationExecutor result to standardized step dict"""
        return {
            'success': nav_result.get('success', False),
            'from_node': from_node,
            'to_node': to_node,
            'execution_time_ms': int(nav_result.get('execution_time', 0) * 1000),
            'transitions_executed': nav_result.get('transitions_executed', 0),
            'actions_executed': nav_result.get('actions_executed', 0),
            'total_transitions': nav_result.get('total_transitions', 0),
            'total_actions': nav_result.get('total_actions', 0),
            'step_category': 'navigation',
            'error': nav_result.get('error'),
            'screenshots': []  # Populated by script from action_screenshots
        }
    
    def create_zap_step(self, iteration: int, action_command: str, analysis_result: dict,
                       max_iterations: int = 0, screenshot_paths: dict = None,
                       step_success: bool = None, start_time: float = None, end_time: float = None) -> dict:
        """Convert ZapController analysis to standardized step dict"""
        # Real pass/fail: prefer the iteration result passed by ZapExecutor (zapping AND
        # motion for zap actions). Fall back to analysis_result.success only when not given.
        success = step_success if step_success is not None else analysis_result.get('success', False)

        # Timing: format like navigation steps ("HH:MM:SS") so the report shows
        # Start/End/Duration instead of N/A.
        if start_time is not None and end_time is not None:
            execution_time_ms = int(max(0.0, end_time - start_time) * 1000)
            start_str = time.strftime('%H:%M:%S', time.localtime(start_time))
            end_str = time.strftime('%H:%M:%S', time.localtime(end_time))
        else:
            execution_time_ms = analysis_result.get('execution_time_ms', 0)
            start_str = 'N/A'
            end_str = 'N/A'

        # When the iteration failed, surface why (zapping vs frozen destination) as the error.
        error = analysis_result.get('error')
        if not success and not error:
            if not analysis_result.get('zapping_detected', False):
                error = 'Zap not detected (no channel change)'
            elif not analysis_result.get('motion_detected', False):
                error = 'Destination frozen (zapped but no motion detected)'
            else:
                error = 'Zap iteration failed'

        step_dict = {
            'success': success,
            'iteration': iteration,
            'max_iterations': max_iterations,
            'action_command': action_command,
            'action_name': action_command,  # Backward compatibility
            'from_node': 'live',
            'to_node': 'live',
            'step_category': 'zap_action',
            'execution_time_ms': execution_time_ms,
            'start_time': start_str,
            'end_time': end_str,
            'motion_detection': analysis_result.get('motion_details', {}),
            'motion_analysis': analysis_result.get('motion_details', {}),
            'subtitle_analysis': analysis_result.get('subtitle_analysis', {}),
            'audio_analysis': analysis_result.get('audio_analysis', {}),
            'zapping_analysis': analysis_result.get('zapping_analysis', {}),
            'error': error,
            'message': f"Zap iteration {iteration}: {action_command} ({iteration}/{max_iterations})",
            'screenshots': []  # Populated by script
        }

        # Add screenshot paths if provided (same fields as navigation steps)
        if screenshot_paths:
            step_dict.update(screenshot_paths)
            # Also populate action_screenshots for backward compatibility
            screenshots = []
            for path in screenshot_paths.values():
                if path and path not in screenshots:
                    screenshots.append(path)
            step_dict['action_screenshots'] = screenshots

            # Add action_results and actions for report formatter compatibility (minimal fix for screenshot labeling)
            # Zap steps have only one action, but may have multiple analysis screenshots
            # A zap step is only ever recorded after the key-send (navigation)
            # succeeded — see ZapExecutor: _record_zap_step runs inside the
            # `if result.get('success')` branch. So the action itself succeeded;
            # set success explicitly. Without it the report formatter's
            # `result.get('success', False)` defaulted to False and rendered a
            # red ✗ on the action even though the key was sent. The zap *outcome*
            # (whether the channel actually changed) is reported separately under
            # Analysis Results → Zapping Detection.
            step_dict['action_results'] = [{
                'message': action_command,  # Simple command name for report formatter
                'action_category': 'main',
                'success': True,
                'screenshot_path': screenshots[0] if screenshots else None  # First screenshot represents the action
            }]

            # Add actions array for backward compatibility with report formatter fallback logic
            step_dict['actions'] = [{
                'command': action_command,
                'params': {}
            }]

        return step_dict
    
    def create_validation_step(self, validation_result: dict, from_node: str, to_node: str,
                              actions: List[Dict] = None, verifications: List[Dict] = None) -> dict:
        """Convert validation result to standardized step dict"""
        return {
            'success': validation_result.get('success', False),
            'from_node': from_node,
            'to_node': to_node,
            'step_category': 'validation',
            'execution_time_ms': validation_result.get('execution_time_ms', 0),
            'actions': actions or validation_result.get('actions', []),
            'verifications': verifications or validation_result.get('verifications', []),
            'verification_results': validation_result.get('verification_results', []),
            'recovered': validation_result.get('recovered', False),
            'recovery_used': validation_result.get('recovery_used', False),
            'error': validation_result.get('error'),
            'screenshots': []  # Populated by script
        }
    
    def create_action_step(self, action_result: dict, action_name: str, from_node: str = None, 
                          to_node: str = None) -> dict:
        """Convert ActionExecutor result to standardized step dict"""
        return {
            'success': action_result.get('success', False),
            'action_name': action_name,
            'from_node': from_node or 'current',
            'to_node': to_node or 'current',
            'step_category': 'action',
            'execution_time_ms': action_result.get('execution_time_ms', 0),
            'passed_count': action_result.get('passed_count', 0),
            'total_count': action_result.get('total_count', 0),
            'error': action_result.get('error'),
            'screenshots': action_result.get('action_screenshots', [])  # Use executor screenshots
        }
