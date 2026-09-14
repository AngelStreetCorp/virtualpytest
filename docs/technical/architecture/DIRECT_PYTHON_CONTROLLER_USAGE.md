# Direct Python Controller Usage Guide

This guide shows how to use controllers directly in Python scripts without HTTP requests, avoiding common "controller not found" errors.

## Quick Reference

### ✅ **Use Existing Utils - Don't Reinvent the Wheel**

```python
from shared.lib.utils.host_utils import get_controller

# Get any controller type directly
video_controller = get_controller(device_id, 'verification_video')
remote_controller = get_controller(device_id, 'remote')
av_controller = get_controller(device_id, 'av')
desktop_controller = get_controller(device_id, 'desktop')
```

### ✅ **Call Controller Methods Directly**

```python
# Motion detection (same as HTTP routes do)
result = video_controller.detect_motion_from_json(json_count=3, strict_mode=False)

# AI subtitle detection (same as HTTP routes do)
result = video_controller.detect_subtitles_ai([screenshot_path], extract_text=True)

# Remote control actions
result = remote_controller.execute_command('press_key', {'key': 'KEY_HOME'})
```

## Common Patterns

### 1. Video Analysis (Avoid "No AV controller found")

```python
# ❌ DON'T: Try to create AV controllers directly
# av_controller = get_controller(device_id, 'av')  # Can fail!
# video_controller = VideoVerificationController(av_controller)

# ✅ DO: Use verification_video controller directly
from shared.lib.utils.host_utils import get_controller

device_id = context.selected_device.device_id
video_controller = get_controller(device_id, 'verification_video')

if video_controller:
    # Motion detection
    motion_result = video_controller.detect_motion_from_json(
        json_count=3, 
        strict_mode=False
    )
    
    # AI subtitle detection
    subtitle_result = video_controller.detect_subtitles_ai(
        [screenshot_path], 
        extract_text=True
    )
    
    # Language menu analysis
    menu_result = video_controller.analyze_language_menu_ai([screenshot_path])
```

### 2. Remote Control Actions

```python
from shared.lib.utils.host_utils import get_controller

device_id = context.selected_device.device_id
remote_controller = get_controller(device_id, 'remote')

if remote_controller:
    # Execute actions directly
    result = remote_controller.execute_command('press_key', {'key': 'KEY_HOME'})
    result = remote_controller.execute_command('tap_coordinates', {'x': 100, 'y': 200})
    result = remote_controller.execute_sequence(actions, retry_actions)
```

### 3. Desktop Automation

```python
from shared.lib.utils.host_utils import get_controller

# For host device operations
desktop_controller = get_controller('host', 'desktop')

if desktop_controller:
    # Execute bash commands
    result = desktop_controller.execute_command('execute_bash_command', {
        'command': 'ls -la'
    })
    
    # GUI automation (if PyAutoGUI controller)
    result = desktop_controller.execute_command('execute_pyautogui_click', {
        'x': 100, 'y': 200
    })
```

### 4. Power Control

```python
from shared.lib.utils.host_utils import get_controller

device_id = context.selected_device.device_id
power_controller = get_controller(device_id, 'power')

if power_controller:
    result = power_controller.execute_command('power_on')
    result = power_controller.execute_command('power_off')
```

## Error Handling Pattern

```python
from shared.lib.utils.host_utils import get_controller

def safe_controller_operation(device_id: str, controller_type: str, command: str, params: dict = None):
    """Safe pattern for controller operations"""
    try:
        # Get controller
        controller = get_controller(device_id, controller_type)
        if not controller:
            return {
                'success': False, 
                'error': f'No {controller_type} controller found for device {device_id}'
            }
        
        # Execute command
        result = controller.execute_command(command, params or {})
        return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'{controller_type} operation error: {str(e)}'
        }

# Usage
result = safe_controller_operation('device1', 'remote', 'press_key', {'key': 'KEY_HOME'})
```

## Controller Types Reference

| Controller Type | Purpose | Common Methods |
|----------------|---------|----------------|
| `'remote'` | Device control | `execute_command()`, `execute_sequence()` |
| `'verification_video'` | Video analysis | `detect_motion_from_json()`, `detect_subtitles_ai()` |
| `'verification_adb'` | ADB verification | `execute_verification()` |
| `'verification_image'` | Image matching | `execute_verification()` |
| `'av'` | Audio/Video capture | `capture_frame()`, `start_stream()` |
| `'desktop'` | Host automation | `execute_command()` |
| `'web'` | Browser automation | `execute_command()` |
| `'power'` | Power control | `execute_command()` |
| `'ai'` | AI operations | `execute_command()` |

## Real-World Example: ZapController

Here's how we fixed the "No AV controller found" error in the ZapController:

```python
class ZapController:
    def __init__(self):
        self.statistics = ZapStatistics()
    
    def _detect_motion(self, context) -> Dict[str, Any]:
        """Detect motion using direct controller call"""
        try:
            device_id = context.selected_device.device_id
            
            # ✅ Get controller directly - same as HTTP routes do
            video_controller = get_controller(device_id, 'verification_video')
            if not video_controller:
                return {"success": False, "message": f"No video verification controller found for device {device_id}"}
            
            # ✅ Call method directly - same as HTTP routes do
            result = video_controller.detect_motion_from_json(
                json_count=3, 
                strict_mode=False
            )
            
            return result
        except Exception as e:
            return {"success": False, "message": f"Motion detection error: {e}"}
    
    def _analyze_subtitles(self, context, screenshot_path: str) -> Dict[str, Any]:
        """Analyze subtitles using direct controller call"""
        try:
            device_id = context.selected_device.device_id
            
            # ✅ Get controller directly
            video_controller = get_controller(device_id, 'verification_video')
            if not video_controller:
                return {"success": False, "message": f"No video verification controller found for device {device_id}"}
            
            # ✅ Call method directly
            result = video_controller.detect_subtitles_ai([screenshot_path], extract_text=True)
            
            return result
        except Exception as e:
            return {"success": False, "message": f"Subtitle analysis error: {e}"}
```

## Key Benefits

1. **🎯 Direct Calls**: No HTTP overhead, faster execution
2. **🛠️ Same Methods**: Uses exact same methods that HTTP routes call
3. **✅ Reliable**: Avoids "controller not found" errors
4. **📋 Simple**: Just 2 lines instead of complex HTTP clients
5. **🔧 Existing Utils**: Uses proven `host_utils.get_controller()`

## Common Mistakes to Avoid

### ❌ Don't Create HTTP Clients for Host-Side Operations
```python
# BAD: Making HTTP requests from host to itself
response = requests.post('http://localhost:6109/host/verification/video/detectSubtitles', ...)
```

### ❌ Don't Try to Create AV Controllers Directly
```python
# BAD: This can fail with "No AV controller found"
av_controller = get_controller(device_id, 'av')
video_controller = VideoVerificationController(av_controller)
```

### ❌ Don't Reinvent Existing Functionality
```python
# BAD: Creating new client classes
class VideoAnalysisClient:
    def detect_motion(self):
        # ... reimplementing existing functionality
```

### ✅ Do Use Existing Controllers Directly
```python
# GOOD: Use existing controllers
video_controller = get_controller(device_id, 'verification_video')
result = video_controller.detect_motion_from_json(3, False)
```

## Summary

**When writing Python scripts that need controller functionality:**

1. **Import**: `from shared.lib.utils.host_utils import get_controller`
2. **Get Controller**: `controller = get_controller(device_id, 'controller_type')`
3. **Call Methods**: `result = controller.method_name(params)`
4. **Handle Errors**: Check if controller is None before calling methods

**This approach is:**
- ✅ **Simple**: Uses existing utilities
- ✅ **Reliable**: Same methods HTTP routes use
- ✅ **Fast**: No HTTP overhead
- ✅ **Proven**: Already working in the system

**Remember: Don't reinvent the wheel - use the existing controller infrastructure!**