# Backend Host Technical Documentation

**Hardware interface service for direct device control.**

---

## 🎯 **Purpose**

Backend Host provides:
- **Hardware Interface**: Direct access to physical devices
- **Device Control**: Execute commands on connected hardware
- **Screenshot Capture**: Visual verification capabilities
- **Service Registration**: Auto-register with Backend Server
- **VNC Access**: Remote desktop functionality

---

## 🏗️ **Architecture**

```
backend_host Service:
├── Flask Application (Port 6109)
│   ├── Route Handlers (/host/*)
│   ├── Controller Integration
│   └── Hardware Abstraction Layer
├── VNC Server (Port 5900)
├── NoVNC Web Interface (Port 6080)
└── Hardware Device Access
    ├── USB Devices (/dev/ttyUSB*)
    ├── Video Capture (/dev/video*)
    ├── Audio Devices
    └── GPIO/Serial Interfaces
```

---

## 🌐 **API Endpoints**

### Device Control
```python
POST /host/takeControl        # Take control of device
POST /host/releaseControl     # Release device control  
GET  /host/status            # Get device status
```

### Remote Control
```python
POST /host/remote/executeAction    # Execute remote action
POST /host/remote/pressKey         # Press specific key
POST /host/remote/navigate         # Navigate direction
```

### Recording & Capture
```python
POST /host/rec/listRestartImages   # List recent screenshots
GET  /host/rec/stream              # Live video stream
POST /host/rec/capture             # Capture screenshot
```

### Verification
```python
POST /host/verification/image      # Image verification
POST /host/verification/text       # Text verification (OCR)
POST /host/verification/audio      # Audio verification
```

---

## 🔧 **Hardware Integration**

### Device Detection
```python
class HardwareManager:
    def detect_devices(self) -> List[Device]:
        devices = []
        
        # Detect USB devices
        usb_devices = self.scan_usb_devices()
        devices.extend(usb_devices)
        
        # Detect video capture devices
        video_devices = self.scan_video_devices()
        devices.extend(video_devices)
        
        # Detect audio devices
        audio_devices = self.scan_audio_devices()
        devices.extend(audio_devices)
        
        return devices
    
    def scan_video_devices(self) -> List[VideoDevice]:
        devices = []
        for i in range(10):  # Check /dev/video0 to /dev/video9
            device_path = f'/dev/video{i}'
            if os.path.exists(device_path):
                devices.append(VideoDevice(device_path, i))
        return devices
```

### Controller Integration
```python
from backend_host.controllers import get_controller

@app.route('/host/remote/executeAction', methods=['POST'])
def execute_remote_action():
    action = request.json
    device_model = action.get('device_model', 'android_mobile')
    
    # Get appropriate controller from backend_host
    controller = get_controller('remote', device_model)
    
    if not controller:
        return {'error': 'Controller not found'}, 404
    
    # Execute action
    result = controller.execute_action(action)
    
    return {
        'success': result,
        'timestamp': datetime.utcnow().isoformat()
    }
```

---

## 📸 **Screenshot & Recording**

### HDMI Capture
```python
class HDMICaptureService:
    def __init__(self, video_device='/dev/video0'):
        self.video_device = video_device
        self.ffmpeg_cmd_base = [
            'ffmpeg', '-f', 'v4l2', '-i', video_device,
            '-vf', 'scale=1280:720', '-q:v', '2'
        ]
    
    def capture_screenshot(self, output_path: str) -> bool:
        cmd = self.ffmpeg_cmd_base + [
            '-vframes', '1', '-y', output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0
    
    def start_stream(self, stream_url: str) -> bool:
        cmd = self.ffmpeg_cmd_base + [
            '-f', 'mjpeg', stream_url
        ]
        
        self.stream_process = subprocess.Popen(cmd)
        return self.stream_process.poll() is None
```

### VNC Integration
```python
class VNCService:
    def start_vnc_server(self, display=':1'):
        # Start Xvfb virtual display
        xvfb_cmd = ['Xvfb', display, '-screen', '0', '1024x768x24']
        self.xvfb_process = subprocess.Popen(xvfb_cmd)
        
        # Start VNC server
        vnc_cmd = ['x11vnc', '-display', display, '-forever', '-nopw']
        self.vnc_process = subprocess.Popen(vnc_cmd)
        
        # Start NoVNC web interface
        novnc_cmd = ['websockify', '--web', '/usr/share/novnc', '6080', 'localhost:5900']
        self.novnc_process = subprocess.Popen(novnc_cmd)
```

---

## 🔄 **Service Registration**

### Auto-Registration with Backend Server
```python
class HostRegistrationService:
    def __init__(self, server_url: str):
        self.server_url = server_url
        self.host_info = self.gather_host_info()
        
    def register_with_server(self) -> bool:
        registration_data = {
            'host_name': self.host_info['name'],
            'host_url': self.host_info['url'],
            'capabilities': self.host_info['capabilities'],
            'hardware': self.host_info['hardware'],
            'status': 'available'
        }
        
        try:
            response = requests.post(
                f"{self.server_url}/api/hosts/register",
                json=registration_data,
                timeout=30
            )
            return response.status_code == 200
        except requests.RequestException:
            return False
    
    def send_heartbeat(self):
        """Send periodic heartbeat to server"""
        while True:
            try:
                requests.post(
                    f"{self.server_url}/api/hosts/{self.host_info['name']}/heartbeat",
                    timeout=10
                )
            except requests.RequestException:
                logger.warning("Failed to send heartbeat to server")
            
            time.sleep(30)  # Heartbeat every 30 seconds
```

---

## ⚙️ **Configuration Management**

### Environment-Based Configuration
```python
class HostConfig:
    def __init__(self):
        self.host_name = os.environ.get('HOST_NAME', socket.gethostname())
        self.host_port = int(os.environ.get('HOST_PORT', 6109))
        self.server_url = os.environ.get('SERVER_URL', 'http://localhost:5109')
        
        # Device configurations
        self.device_configs = self.load_device_configs()
        
    def load_device_configs(self) -> Dict[str, Dict]:
        configs = {}
        
        # Load device configurations from environment
        for i in range(1, 10):  # Support up to 9 devices
            device_prefix = f'DEVICE{i}_'
            if os.environ.get(f'{device_prefix}VIDEO'):
                configs[f'device{i}'] = {
                    'video_device': os.environ.get(f'{device_prefix}VIDEO'),
                    'audio_device': os.environ.get(f'{device_prefix}AUDIO'),
                    'capture_path': os.environ.get(f'{device_prefix}VIDEO_CAPTURE_PATH'),
                    'fps': int(os.environ.get(f'{device_prefix}FPS', 10))
                }
        
        return configs
```

### Dynamic Service Detection
```python
class ServiceManager:
    def detect_required_services(self) -> List[str]:
        """Detect which services need to start based on configuration"""
        services = ['vnc']  # VNC always starts
        
        if self.config.device_configs:
            services.append('ffmpeg_capture')
            services.append('monitor')
        
        if os.environ.get('ENABLE_POWER_MANAGEMENT'):
            services.append('power_control')
        
        return services
    
    def start_services(self, services: List[str]):
        for service_name in services:
            if service_name == 'vnc':
                self.vnc_service.start()
            elif service_name == 'ffmpeg_capture':
                self.capture_service.start()
            elif service_name == 'monitor':
                self.monitor_service.start()
```

---

## 🔔 **Async Completion and Callbacks**

Backend Host now uses push-based completion reporting for async execution flows.

### Script Execution Completion

1. Client triggers `POST /server/script/execute`.
2. Server proxies to host (`/host/script/execute`) with generated task id.
3. Host executes script asynchronously.
4. Host posts completion to server: `POST /server/script/taskComplete`.
5. Server emits `/system` socket events:
   - `execution_update` (`execution_type: "script"`)
   - `deployment_execution_changed` (`action: "script_task_complete"`)
6. If request included external `callback_url`, server also posts webhook payload to that URL.

### Deployment Scheduler Completion

1. Host scheduler runs cron deployment (`deployment_scheduler.py`).
2. Host updates `deployment_executions` DB record.
3. Host posts completion to server: `POST /server/deployment/executionComplete`.
4. Server emits `/system` socket events:
   - `execution_update` (`execution_type: "deployment"`)
   - `deployment_execution_changed` (`action: "deployment_execution_complete"`)
5. If completion payload contains `callback_url`, server sends external webhook.

### Why this model

- Removes frontend dependency on tight status polling loops for execution completion.
- Keeps one server-side fanout point for both socket and webhook consumers.
- Preserves compatibility with legacy status endpoints during migration.

---

## 🚀 **Deployment**

### Docker Configuration
```dockerfile
FROM python:3.11-slim

# Install system dependencies for hardware access
RUN apt-get update && apt-get install -y \
    # Video capture
    ffmpeg v4l-utils \
    # VNC server
    xvfb x11vnc novnc websockify \
    # Android tools
    android-tools-adb \
    # USB tools
    usbutils \
    # Network tools
    net-tools iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY backend_host/ /app/backend_host/
COPY shared/ /app/shared/
COPY backend_host/ /app/backend_host/

# Set Python path
ENV PYTHONPATH="/app/shared:/app/shared/lib:/app/backend_host/src"

# Install Python dependencies
RUN pip install -r /app/backend_host/requirements.txt

# Create directories for captures and logs
RUN mkdir -p /var/www/html/stream /var/log/virtualpytest

# Expose ports
EXPOSE 6109 5900 6080

# Start application
CMD ["python", "/app/backend_host/src/app.py"]
```

### Privileged Mode Requirements
```yaml
# docker-compose.yml
backend_host:
  build:
    context: ../
    dockerfile: backend_host/Dockerfile
  privileged: true  # Required for hardware access
  volumes:
    - /dev:/dev      # Hardware device access
    - ../shared:/app/shared:ro
    - ../backend_host:/app/backend_host:ro
  ports:
    - "6109:6109"    # API
    - "5900:5900"    # VNC
    - "6080:6080"    # NoVNC web interface
```

---

## 🔍 **Monitoring & Health Checks**

### Health Check Endpoint
```python
@app.route('/host/health')
def health_check():
    checks = {
        'system': check_system_resources(),
        'devices': check_connected_devices(),
        'services': check_running_services(),
        'network': check_network_connectivity()
    }
    
    overall_health = all(checks.values())
    
    return {
        'status': 'healthy' if overall_health else 'unhealthy',
        'checks': checks,
        'host_info': {
            'name': config.host_name,
            'capabilities': get_host_capabilities(),
            'uptime': get_system_uptime()
        }
    }

def check_connected_devices() -> bool:
    """Check if expected devices are connected"""
    expected_devices = config.device_configs.keys()
    
    for device_id in expected_devices:
        device_config = config.device_configs[device_id]
        video_device = device_config.get('video_device')
        
        if video_device and not os.path.exists(video_device):
            return False
    
    return True
```

---

## 🔧 **Development & Testing**

### Local Testing
```python
# Test device connectivity
python -c "
from backend_host.src.controllers.remote.android_mobile import AndroidMobileRemoteController
controller = AndroidMobileRemoteController()
print('Controller initialized:', controller.initialize())
"

# Test video capture
ffmpeg -f v4l2 -i /dev/video0 -t 5 -y test_capture.mp4

# Test VNC access
vncviewer localhost:5900
```

### Integration Testing
```python
class TestHostIntegration:
    def test_device_control(self):
        response = requests.post('http://localhost:6109/host/remote/executeAction', 
                               json={'action': 'press_key', 'key': 'home'})
        assert response.status_code == 200
        assert response.json()['success'] is True
    
    def test_screenshot_capture(self):
        response = requests.post('http://localhost:6109/host/rec/capture',
                               json={'device_id': 'device1'})
        assert response.status_code == 200
        assert 'screenshot_url' in response.json()
```

---

**Want to understand the frontend integration? Check [Frontend Documentation](frontend.md)!** 🌐
