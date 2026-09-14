# 🎮 Unified Device Controller

**One script. All devices.**

Write test scripts once and run them across Android TV, iOS, mobile, set-top boxes, and smart TVs without changing your code.

---

## The Problem

Traditional testing tools require different scripts for each device type:
- ❌ Separate Android and iOS automation frameworks
- ❌ Different APIs for TV vs. mobile
- ❌ Rewriting tests for each platform
- ❌ Maintaining multiple codebases

---

## The VirtualPyTest Solution

✅ **Unified API** - Same commands work across all devices  
✅ **Hardware abstraction** - Code to user journeys, not device specifics  
✅ **Automatic adaptation** - Controller picks the right method for each device  
✅ **Extensible** - Add new device types easily  

---

## Supported Devices

### Android Devices
- **Android TV** (Fire TV, Google TV, etc.)
- **Android Mobile** phones and tablets
- **Control via**: ADB, Appium, Web interface

### iOS Devices
- **iPhone** and **iPad**
- **Control via**: Appium, WebDriver

### Set-Top Boxes (STB)
- **IR-controlled** boxes
- **Bluetooth** remotes
- **Control via**: IR transmitter, GPIO, USB-UIRT

### Smart TVs
- **Samsung Tizen**
- **LG webOS**
- **Control via**: Network API, IR

### Desktop/Web
- **Browser automation**
- **Control via**: Selenium, Playwright

---

## How It Works

### 1. Define Your Test Once

Test scripts written against the navigation-tree + verification abstraction don't hardcode a
device-specific controller — the same `navigate_to`/verification calls work regardless of device
model. Under the hood, `backend_host/src/controllers/controller_config_factory.py` resolves the
right controller implementation (ADB, Appium, IR, web, etc.) from the device's model config —
there is no importable `ControllerFactory.get_controller(...)` class; the real factory is
config-driven and used internally by the host, not called directly from test scripts. See
[Writing Scripts](../user-guide/writing-scripts.md) for the real script-authoring API.

### 2. Run on Any Device

The controller automatically adapts based on the device model:

```python
# On Android TV: Uses ADB commands
# On iOS: Uses Appium touch actions
# On STB: Sends IR signals
# On Web: Uses Selenium clicks
```

---

## Supported Actions

### Navigation
- `navigate_to(node)` - Go to any screen in your navigation tree
- `go_home()` - Return to home screen
- `go_back()` - Navigate backwards

### Remote Control
- `press_key(key)` - Press any button (UP, DOWN, SELECT, BACK, etc.)
- `enter_text(text)` - Type text into fields
- `swipe(direction)` - Swipe gestures on touch devices

### Verification
- `verify_text(text)` - Check if text appears on screen
- `verify_image(image_path)` - Compare visual elements
- `capture_screenshot()` - Take evidence screenshots

### Power Management
- `power_on()` - Turn device on
- `power_off()` - Turn device off
- `reboot()` - Restart device

---

## Example: Multi-Device Test

The same script (with the same navigation node names and verifications) can be run against
different registered devices without modification — pick a different `device_id`/`host_name` at
execution time (via the web UI, campaign runner, or the `/server/script/execute` API) rather than
switching controller code per device.

---

## Controller Configuration

Devices are configured through the web interface and stored in the database (`device` and
`device_models` tables, `setup/db/schema/001_core_tables.sql`) — not static YAML files. Each
device model maps to controller implementations and connection parameters via
`create_controller_configs_from_device_info()` in
`backend_host/src/controllers/controller_config_factory.py`.

---

## Benefits

### 🚀 Faster Development
Write tests once, deploy everywhere. No need to learn different frameworks for each platform.

### 💰 Cost Savings
One test suite instead of N different suites. Reduce maintenance overhead dramatically.

### 🎯 Better Coverage
Easy to test across all platforms means better multi-device compatibility.

### 🔧 Easy Maintenance
Update test logic once, all devices benefit. Fix once, deploy everywhere.

---

## Under the Hood

VirtualPyTest uses a **config-driven factory** (not a class you call directly from test scripts)
to build the right controller:

```
Device config (DB) → controller_config_factory.py → per-type controller
                                                      (ADB / Appium / IR / Web / ...)
```

Each controller implements a shared interface but uses device-specific methods internally.

---

## Add Your Own Device Type

See the real, step-by-step process in
[Controller Creation Guide](../technical/architecture/CONTROLLER_CREATION_GUIDE.md): implement the
controller class, wire it into the controller package `__init__.py`, register it in the factory
configuration and controller manager/registry.

---

## Next Steps

- 📖 [Visual Capture](./visual-capture.md) - Monitor what your devices display
- 📖 [AI Validation](./ai-validation.md) - Verify content automatically
- 📚 [User Guide - Running Tests](../user-guide/running-tests.md) - Execute your first test
- 🔧 [Technical Docs - Architecture](../technical/README.md) - Deep dive into controllers

---

**Ready to control all your devices from one script?**  
➡️ [Get Started](../get-started/README.md)



