# Unified Device Controller

**One script. All devices.**

Write a test script once, and run it on Android TV, iOS, phones, set-top boxes and smart TVs. You do not change the script for each device.

---

## Why it matters

Other tools need a different script for each kind of device. The same test then gets rewritten again and again.

<div data-technical>

- Android and iOS use separate automation tools.
- TVs and phones have different ways to be controlled.
- Each platform means rewriting the same tests.
- Several codebases have to be kept up to date.

</div>

---

## What you get

- **One set of commands.** The same commands work on every device.
- **Focus on the user journey.** You write what a user does, not how each device works.
- **Automatic adaptation.** The controller picks the right method for each device.
- **Easy to extend.** New device types can be added.

---

## Supported devices

### Android devices

- **Android TV** (Fire TV, Google TV and similar)
- **Android phones and tablets**

<div data-technical>

Control via: ADB, Appium, Web interface.

</div>

### iOS devices

- **iPhone** and **iPad**

<div data-technical>

Control via: Appium, WebDriver.

</div>

### Set-top boxes (STB)

- **Infrared (IR) controlled** boxes
- **Bluetooth** remotes

<div data-technical>

Control via: IR transmitter, GPIO, USB-UIRT.

</div>

### Smart TVs

- **Samsung Tizen**
- **LG webOS**

<div data-technical>

Control via: Network API, IR.

</div>

### Desktop and web

- **Browser automation**

<div data-technical>

Control via: Selenium, Playwright.

</div>

---

## How it works

### 1. Define your test once

You write a test against a navigation tree and its checks. The same commands work whatever the device is.

<div data-technical>

Test scripts written against the navigation-tree and verification abstraction do not hardcode a device-specific controller. The same `navigate_to` and verification calls work regardless of device model. Under the hood, `backend_host/src/controllers/controller_config_factory.py` resolves the right controller implementation (ADB, Appium, IR, web, etc.) from the device's model config. There is no importable `ControllerFactory.get_controller(...)` class. The real factory is config-driven and used internally by the host, not called directly from test scripts. See [Writing Scripts](../user-guide/writing-scripts.md) for the real script-authoring API.

</div>

### 2. Run on any device

The controller adapts to the device. An Android TV is driven with ADB, an iPhone with touch actions, a set-top box with IR signals, and a web page with clicks.

<div data-technical>

```python
# On Android TV: Uses ADB commands
# On iOS: Uses Appium touch actions
# On STB: Sends IR signals
# On Web: Uses Selenium clicks
```

</div>

---

## Supported actions

Common actions cover moving around the app, using the remote, checking the screen, and power.

<div data-technical>

**Navigation**
- `navigate_to(node)` - Go to any screen in your navigation tree
- `go_home()` - Return to home screen
- `go_back()` - Navigate backwards

**Remote control**
- `press_key(key)` - Press any button (UP, DOWN, SELECT, BACK, etc.)
- `enter_text(text)` - Type text into fields
- `swipe(direction)` - Swipe gestures on touch devices

**Verification**
- `verify_text(text)` - Check if text appears on screen
- `verify_image(image_path)` - Compare visual elements
- `capture_screenshot()` - Take evidence screenshots

**Power management**
- `power_on()` - Turn device on
- `power_off()` - Turn device off
- `reboot()` - Restart device

</div>

---

## Example: a multi-device test

The same script runs on different devices. You pick the device when you run the test.

<div data-technical>

Pick a different `device_id` or `host_name` at execution time (via the web UI, the campaign runner, or the `/server/script/execute` API), rather than switching controller code per device.

</div>

---

## Controller configuration

A device is set up in its host's settings. The settings say which connections it really has. Connections that are not set up are skipped.

<div data-technical>

A device is declared in its host's `.env` (`DEVICE{n}_MODEL`, plus the keys of whatever is wired to it: `_ADB_SERIAL`, `_IR_PATH` / `_IR_IP`, `_BLE_TYPE`, power plug...). The model names which controllers it *may* have (`DEVICE_CONTROLLER_MAP` in `shared/src/lib/config/device_capabilities.py`). The `.env` decides which of them it *does* have, and `create_controller_configs_from_device_info()` in `backend_host/src/controllers/controller_config_factory.py` builds them. A controller whose keys are not set is skipped.

The **Device Models** page (`device_models` table) is the list of models a userinterface can target. Add Model offers only names a host can run; it does not configure controllers.

</div>

---

## Benefits

Write tests once and run them everywhere. One test suite replaces many, so there is less to maintain and more multi-device problems are caught.

---

## Under the hood

<div data-technical>

VirtualPyTest uses a **config-driven factory** (not a class you call directly from test scripts) to build the right controller:

```
Device config (DB) → controller_config_factory.py → per-type controller
                                                      (ADB / Appium / IR / Web / ...)
```

Each controller implements a shared interface but uses device-specific methods internally.

</div>

---

## Add your own device type

For developers, the step-by-step process is in the [Controller Creation Guide](../technical/architecture/CONTROLLER_CREATION_GUIDE.md).

<div data-technical>

In short: implement the controller class, wire it into the controller package `__init__.py`, and register it in the factory configuration and the controller manager and registry.

</div>

---

## Next Steps

- [Visual Capture](./visual-capture.md): monitor what your devices display
- [AI Validation](./ai-validation.md): verify content automatically
- [User Guide - Running Tests](../user-guide/running-tests.md): execute your first test
- [Technical Docs - Architecture](../technical/README.md): a deep dive into controllers

---

**Ready to control all your devices from one script?**
[Get Started](../get-started/README.md)
