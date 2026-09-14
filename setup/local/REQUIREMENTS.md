# System Requirements for VirtualPyTest

This document lists all system-level dependencies required for VirtualPyTest on **Ubuntu/Linux** that are **NOT** installed by the existing `install_*.sh` scripts.

## 🖥️ **Operating System**

- **Ubuntu 18.04+** (Recommended)
- **Debian 10+** (Compatible)
- **Other Linux** (May work with package name adjustments)

## 📋 **System Dependencies**

### **Already Installed by VirtualPyTest Scripts:**
- ✅ **Python 3.11+** - Installed by `install_shared.sh`
- ✅ **Node.js 20+** - Installed by `install_frontend.sh` 
- ✅ **PostgreSQL** - Installed by `install_supabase.sh` (with complete VirtualPyTest schema)
- ✅ **Grafana** - Installed by `install_grafana.sh`

### **Required System Packages (NOT installed by scripts):**

#### **🔧 Build Tools & Development**
```bash
sudo apt-get install -y build-essential git curl wget
```

#### **🎥 Video & Audio Processing**
```bash
sudo apt-get install -y ffmpeg imagemagick
```

#### **🔤 OCR & Text Recognition**
```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-ita
```

#### **🖥️ VNC & Remote Desktop (for backend_host)**
```bash
sudo apt-get install -y tigervnc-standalone-server xvfb xfce4 xfce4-goodies novnc websockify
```

#### **🌐 Web Browser (for browser automation)**
```bash
# Try chromium first (Debian 12+), fallback to chromium-browser for older versions
sudo apt-get install -y epiphany-browser chromium || sudo apt-get install -y epiphany-browser chromium-browser
```

#### **📁 File System Monitoring**
```bash
sudo apt-get install -y inotify-tools
```

#### **🔗 Network & System Tools**
```bash
sudo apt-get install -y lsof net-tools psmisc
```

#### **📡 IR Remote Control (for Apple TV, Samsung TV, etc.)**
```bash
sudo apt-get install -y lirc lirc-tools ir-keytable
```

## 🎯 **Hardware-Specific Requirements**

### **For Video Capture (HDMI devices):**
- **Video4Linux drivers** (`/dev/video*` devices)
- **ALSA audio drivers** (`plughw:*` devices)
- **USB capture cards** (compatible with V4L2)

### **For Mobile Device Testing:**
- **ADB (Android Debug Bridge)** - For Android devices (✅ **NOW INSTALLED AUTOMATICALLY**)
- **USB drivers** - For device connectivity
- **Appium Server** - Installed via Python requirements

## 🚀 **Quick Install (One Command)**

```bash
sudo apt-get update && sudo apt-get install -y \
    build-essential git curl wget \
    ffmpeg imagemagick \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-ita \
    tigervnc-standalone-server xvfb fluxbox novnc websockify \
    epiphany-browser \
    # Try chromium first (Debian 12+), fallback to chromium-browser for older versions
    chromium || chromium-browser \
    inotify-tools lsof net-tools psmisc \
    lirc lirc-tools ir-keytable
```

## 🔍 **Verification**

After installation, verify key components:
```bash
# Check video processing
ffmpeg -version

# Check OCR
tesseract --version

# Check VNC (should show TigerVNC)
tigervncserver -help | head -1

# Check file monitoring
which inotifywait
```

## 💡 **Notes**

- **Optional Components**: Video capture and VNC are only needed for hardware testing
- **Browser Dependencies**: Web browsers are only needed for browser automation tests
- **Package Search**: Use `apt-cache search <package>` to find alternatives
