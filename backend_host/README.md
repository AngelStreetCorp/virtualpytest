# VirtualPyTest Backend Host

## 🎯 **Overview**

Backend Host is the hardware interface layer that provides direct device control and system management capabilities. It serves as the bridge between cloud-based test orchestration and physical device manipulation, running on hardware devices like Raspberry Pi to enable remote testing and automation.

## 🔧 **Software Stack**

- **Language**: Python 3.8+
- **Framework**: Flask web application with Gunicorn WSGI server
- **Deployment**: Docker containerization
- **System Dependencies**: Hardware drivers, graphics libraries (libGL, Xvfb)

## 🏗️ **Core Services**

### **Device Control Services**
- **REST API**: HTTP endpoints for device management and control
- **Hardware Abstraction**: Unified interface for different device types
- **Automation Controllers**: Web, mobile, and desktop automation capabilities

### **Media & Capture Services**
- **VNC Services**: NoVNC web interface and direct VNC server access
- **Video Capture**: FFmpeg-based video streaming and recording
- **Audio Capture**: Multi-channel audio device support
- **Screenshot Services**: Image capture and verification

### **System Services**
- **Virtual Display**: Xvfb server for headless desktop operations
- **Power Management**: Device power control and monitoring
- **Network Monitoring**: IoT device and smart switch integration

## 📋 **Device Support**

- **Mobile Devices**: Android (ADB), iOS (Appium)
- **Desktop Systems**: Local display automation and remote access
- **Audio/Video**: USB cameras, HDMI capture, audio devices
- **Power Control**: Smart plugs, UPS devices
- **Network Devices**: IoT devices, smart switches

## 🎯 **Main Purpose**

Backend Host enables VirtualPyTest to interact with physical hardware in real-time, providing the foundation for automated testing across multiple device types. It transforms physical devices into remotely controllable test endpoints while maintaining the performance and reliability needed for production testing environments.

## 📚 **Technical Documentation**

- **[Services Configuration](config/services/README.md)** - Detailed service setup and configuration
- **[Docker Deployment](docker/README.md)** - Container deployment and orchestration
- **[Dockerfile](Dockerfile)** - Container build configuration
- **[Requirements](requirements.txt)** - Python dependencies and versions 