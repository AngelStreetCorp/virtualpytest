"""
Screenshot Manager
Handles screenshot capture for execution operations
"""

from typing import Dict, Any, Optional


class ScreenshotManager:
    """Manages screenshot capture for execution operations"""
    
    @staticmethod
    def capture_before_execution(device, context=None) -> Optional[str]:
        """
        Capture screenshot before execution starts
        
        Args:
            device: Device instance
            context: Optional execution context
            
        Returns:
            Screenshot path or None
        """
        from shared.src.lib.utils.device_utils import capture_screenshot
        
        screenshot_path = capture_screenshot(device, context) or ""
        if screenshot_path:
            print(f"[@ScreenshotManager] Before-execution screenshot: {screenshot_path}")
        return screenshot_path
    
    @staticmethod
    def capture_after_execution(device, context=None) -> Optional[str]:
        """
        Capture screenshot after execution completes
        
        Args:
            device: Device instance
            context: Optional execution context
            
        Returns:
            Screenshot path or None
        """
        from shared.src.lib.utils.device_utils import capture_screenshot
        
        screenshot_path = capture_screenshot(device, context) or ""
        if screenshot_path:
            print(f"[@ScreenshotManager] After-execution screenshot: {screenshot_path}")
        return screenshot_path
    
    @staticmethod
    def add_screenshots_to_result(result: Dict[str, Any], 
                                  before: Optional[str], 
                                  after: Optional[str]) -> Dict[str, Any]:
        """
        Add screenshot paths to execution result
        
        Args:
            result: Execution result dict
            before: Before screenshot path
            after: After screenshot path
            
        Returns:
            Updated result dict
        """
        if before:
            result['screenshot_before'] = before
        if after:
            result['screenshot_after'] = after
        
        return result

