# Backend Core Technical Documentation

**Shared library containing device controllers and business logic.**

---

## 🎯 **Purpose**

Backend Core is a **shared Python library** that provides:
- Device controller implementations
- Business service logic
- Abstract interfaces
- Test execution framework

**Key Point**: This is NOT a standalone service - it's imported by other components.

---

## 📁 **Structure**

```
backend_host/src/
├── controllers/             # Device-specific controllers
│   ├── desktop/            # Desktop automation (PyAutoGUI, Bash)
│   ├── remote/             # Mobile/TV control (ADB, Appium, IR)
│   ├── audiovideo/         # A/V capture (HDMI, VNC, Camera)
│   ├── power/              # Power management (Tapo, UPS)
│   ├── web/                # Web automation (Playwright)
│   ├── verification/       # Content verification (OCR, Image, Audio)
│   └── ai/                 # AI-powered automation
├── services/               # Business logic services
│   ├── actions/            # Action execution
│   ├── navigation/         # Navigation pathfinding
│   └── verifications/      # Verification services
├── interfaces/             # Abstract base classes
└── examples/               # Usage examples
```

---

## 🎮 **Controller System**

### Controller Registry
Controllers are organized by type and implementation:

```python
CONTROLLER_REGISTRY = {
    'remote': {
        'android_tv': AndroidTVRemoteController,
        'android_mobile': AndroidMobileRemoteController,
        'appium_remote': AppiumRemoteController,
        'ir_remote': IRRemoteController,
    },
    'av': {
        'hdmi_stream': HDMIStreamController,
        'vnc_stream': VNCStreamController,
        'camera_stream': CameraStreamController,
    },
    'verification': {
        'text': TextVerificationController,
        'image': ImageVerificationController,
        'audio': AudioVerificationController,
        'video': VideoVerificationController,
    },
    # ... more controller types
}
```

### Device-Controller Mapping
Each device model has predefined controllers:

```python
DEVICE_CONTROLLER_MAP = {
    'android_mobile': {
        'av': ['hdmi_stream'], 
        'remote': ['android_mobile'],
        'ai': ['ai_agent']
    },
    'android_tv': {
        'av': ['hdmi_stream'], 
        'remote': ['android_tv'],
        'power': ['tapo'],
        'ai': ['ai_agent']
    },
    # ... more device mappings
}
```

---

## 🔧 **Controller Interfaces**

### Base Controller
All controllers inherit from `BaseController`:

```python
class BaseController:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.logger = structlog.get_logger()
    
    def initialize(self) -> bool:
        """Initialize controller resources"""
        return True
    
    def cleanup(self) -> bool:
        """Clean up controller resources"""
        return True
```

### Remote Controller Interface
For device control:

```python
class RemoteControllerInterface(BaseController):
    def press_key(self, key: str) -> bool:
        """Press a key on the remote"""
        raise NotImplementedError
    
    def navigate(self, direction: str) -> bool:
        """Navigate in a direction"""
        raise NotImplementedError
```

### AV Controller Interface
For audio/video capture:

```python
class AVControllerInterface(BaseController):
    def get_stream_url(self) -> str:
        """Get live stream URL"""
        raise NotImplementedError
    
    def capture_screenshot(self, path: str) -> bool:
        """Capture screenshot"""
        raise NotImplementedError
```

---

## 📱 **Device Controllers**

### Android Mobile Controller
**Purpose**: Control Android phones/tablets via ADB

```python
class AndroidMobileRemoteController(RemoteControllerInterface):
    def press_key(self, key: str) -> bool:
        # Map key to ADB keycode
        keycode = self._get_keycode(key)
        result = subprocess.run([
            'adb', 'shell', 'input', 'keyevent', str(keycode)
        ])
        return result.returncode == 0
    
    def tap(self, x: int, y: int) -> bool:
        result = subprocess.run([
            'adb', 'shell', 'input', 'tap', str(x), str(y)
        ])
        return result.returncode == 0
```

### HDMI Stream Controller
**Purpose**: Capture video from HDMI source

```python
class HDMIStreamController(AVControllerInterface):
    def get_stream_url(self) -> str:
        return f"http://{self.host}:8080/stream.mjpg"
    
    def capture_screenshot(self, path: str) -> bool:
        # Use FFmpeg to capture frame
        cmd = [
            'ffmpeg', '-f', 'v4l2', '-i', self.video_device,
            '-vframes', '1', '-y', path
        ]
        result = subprocess.run(cmd)
        return result.returncode == 0
```

---

## 🧠 **Business Services**

### Action Executor
**Purpose**: Execute test actions using appropriate controllers

```python
class ActionExecutor:
    def execute_action(self, action: Dict[str, Any]) -> bool:
        action_type = action.get('type')
        
        if action_type == 'press_key':
            return self._execute_key_press(action)
        elif action_type == 'tap':
            return self._execute_tap(action)
        elif action_type == 'verify_text':
            return self._execute_text_verification(action)
        
        return False
```

### Navigation Executor
**Purpose**: Navigate through device interfaces using pathfinding

```python
class NavigationExecutor:
    def find_path(self, start_node: str, end_node: str) -> List[Dict]:
        # Use navigation tree to find shortest path
        return find_shortest_path(self.tree_id, start_node, end_node)
    
    def execute_path(self, path: List[Dict]) -> bool:
        for step in path:
            if not self.execute_navigation_step(step):
                return False
        return True
```

---

## 🔍 **Verification Services**

### Image Verification
**Purpose**: Verify visual content on screen

```python
class ImageVerificationController(VerificationControllerInterface):
    def verify_element_present(self, template_path: str, 
                              screenshot_path: str) -> bool:
        # Use OpenCV template matching
        template = cv2.imread(template_path)
        screenshot = cv2.imread(screenshot_path)
        
        result = cv2.matchTemplate(screenshot, template, 
                                 cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        
        return max_val > self.threshold
```

### Text Verification
**Purpose**: Verify text content using OCR

```python
class TextVerificationController(VerificationControllerInterface):
    def verify_text_present(self, expected_text: str, 
                           screenshot_path: str) -> bool:
        # Use Tesseract OCR
        image = Image.open(screenshot_path)
        detected_text = pytesseract.image_to_string(image)
        
        return expected_text.lower() in detected_text.lower()
```

---

## 🔧 **Configuration System**

### Controller Configuration
Controllers use shared configuration:

```python
from shared.lib.config.settings import shared_config

class AndroidMobileRemoteController:
    def __init__(self):
        self.adb_timeout = shared_config.get('adb_timeout', 30)
        self.device_id = shared_config.get('android_device_id')
```

### Device-Specific Configuration
Device configurations stored in JSON:

```json
{
  "android_mobile": {
    "adb_timeout": 30,
    "screenshot_quality": 80,
    "tap_duration": 100,
    "keycode_mapping": {
      "back": 4,
      "home": 3,
      "menu": 82
    }
  }
}
```

---

## 🧪 **Usage Examples**

### Direct Controller Usage
```python
from backend_host.src.controllers.remote.android_mobile import AndroidMobileRemoteController

# Initialize controller
controller = AndroidMobileRemoteController()
controller.initialize()

# Use controller
controller.press_key('home')
controller.tap(500, 300)
controller.swipe(100, 100, 200, 200)

# Cleanup
controller.cleanup()
```

### Service-Level Usage
```python
from backend_host.services.actions.action_executor import ActionExecutor

# Create executor
executor = ActionExecutor()

# Execute actions
result = executor.execute_action({
    'type': 'tap',
    'parameters': {'x': 100, 'y': 200}
})
```

---

## 🔄 **Integration**

### Backend Host Integration
Backend Host imports and uses controllers:

```python
# In backend_host/src/routes/remote_routes.py
from backend_host.controllers import get_controller

@app.route('/host/remote/executeAction', methods=['POST'])
def execute_remote_action():
    controller = get_controller('remote', 'android_mobile')
    action = request.json
    result = controller.execute_action(action)
    return {'success': result}
```

### Backend Server Integration
Backend Server uses business services:

```python
# In backend_server/src/services/test_orchestrator.py
from backend_host.services.navigation.navigation_execution import NavigationExecutor

class TestOrchestrator:
    def execute_test(self, test_case):
        navigator = NavigationExecutor()
        path = navigator.find_path(start_node, end_node)
        return navigator.execute_path(path)
```

---

## 📊 **Performance Considerations**

### Controller Lifecycle
- **Lazy Loading**: Controllers created on first use
- **Resource Management**: Proper initialization/cleanup
- **Connection Pooling**: Reuse expensive connections
- **Caching**: Cache configuration and templates

### Error Handling
- **Graceful Degradation**: Fallback when controllers fail
- **Retry Logic**: Automatic retry for transient failures
- **Logging**: Detailed error logging for debugging
- **Recovery**: Automatic recovery from common issues

---

## 🔧 **Development Guidelines**

### Adding New Controllers
1. **Inherit from appropriate interface**
2. **Implement required methods**
3. **Add to controller registry**
4. **Create configuration schema**
5. **Add tests and examples**

### Best Practices
- **Single Responsibility**: Each controller has one purpose
- **Configuration-Driven**: Avoid hardcoded values
- **Error Handling**: Proper exception handling
- **Logging**: Structured logging for debugging
- **Testing**: Unit tests for all controllers

---

**Want to see controller implementations? Check the Device Controllers Guide!** 🎮
