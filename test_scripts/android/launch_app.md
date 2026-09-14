# launch_app.py — Android App Launch & Verify Script

Launches an Android app on the target device, dismisses any system dialogs
(ANR, crash), and verifies the app is actually displayed by checking UI
elements via ADB.

---

## Usage

```bash
python test_scripts/android/launch_app.py                        # default: settings
python test_scripts/android/launch_app.py --app clock
python test_scripts/android/launch_app.py --app settings --device device1
```

### Available apps

| Key | App | Package | Verify texts |
|-----|-----|---------|-------------|
| `settings` | Settings | `com.android.settings` | Settings, Search settings, Network, Battery |
| `clock` | Clock | `com.google.android.deskclock` | Clock, Alarm, Timer, Stopwatch, Bedtime |
| `contacts` | Contacts | `com.google.android.contacts` | Contacts |
| `chrome` | Chrome | `com.android.chrome` | Chrome, Search or type URL |
| `dialer` | Phone | `com.google.android.dialer` | Phone, Recents, Favorites |
| `messages` | Messages | `com.google.android.apps.messaging` | Messages, Start chat |

Default: `settings` (pre-installed on all Android devices and emulators).

---

## How it works

```
Step 1 — Launch app
  1. adb am start <package>
  2. Wait 2 s for app to render
  3. Dismiss ANR/crash dialogs (CLOSE_SYSTEM_DIALOGS broadcast)
  4. Take ADB screenshot

Step 2 — Verify app is displayed
  1. Dismiss lingering dialogs
  2. adb uiautomator dump → parse UI elements
  3. Match element text/resource_id against verify_texts
  4. Take ADB screenshot
  5. PASS if app content confirmed, FAIL if overlay or wrong app
```

Result statuses: `PASS` / `FAIL`

---

## Test steps in report

The script records **2 steps** with screenshots:

| Step | Description | Screenshot |
|------|------------|------------|
| 1 | Launch `<app_name>` | After launch + dialog dismissal |
| 2 | Verify `<app_name>` UI | After element dump verification |

Screenshots are captured via ADB (`adb screencap`) — no AV controller / video
stream required. This makes the script work on lightweight runner hosts.

---

## Screenshots

Runner hosts have no AV controller (no HDMI capture / VNC stream). Instead,
screenshots are taken via `adb screencap` and uploaded to R2 in batch at
script end. This is handled automatically by `capture_screenshot_for_script()`
which falls back to ADB for Android device models.

---

## ANR / crash dialog handling

Emulators frequently show "App isn't responding" (ANR) dialogs on first boot.
The script dismisses them with:

```
adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS
```

This is faster and more reliable than finding and clicking dialog buttons.

---

## Target devices

Runs on all Android runner models by default:

```python
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "runner_android_mobile|runner_android_tablet|runner_android_tv",
}
```

---

## Adding apps to the catalog

Add an entry to `APP_CATALOG` in `launch_app.py`:

```python
"myapp": {
    "display_name": "My App",
    "package": "com.example.myapp",
    "verify_texts": ["My App", "Welcome"],
},
```

`verify_texts` — any element whose text contains one of these strings confirms
the app is visible. Also matches if element `resource_id` contains the package name.

---

## ADB requirements

The device must be reachable via ADB. For emulators, ADB connects locally
(`localhost:5555`). For physical devices, TCP/IP mode must be enabled:

```bash
adb tcpip 5555
adb connect <device_ip>:5555
```
