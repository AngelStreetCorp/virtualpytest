# app_install.py — Android App Install Script

Install Android apps on emulators/devices via ADB. Supports single APKs, XAPK (split APKs), and direct download from URLs.

---

## Usage

```bash
# Install from library
python test_scripts/android/app_install.py --apk_name netflix

# Install from URL (any APK/XAPK)
python test_scripts/android/app_install.py --apk_url https://example.com/app.apk --package_name com.example.app

# Just launch (already installed)
python test_scripts/android/app_install.py --package_name com.netflix.mediaclient
```

### Arguments

| Arg | Description |
|-----|-------------|
| `--apk_name` | Key from APK_LIBRARY (e.g., `netflix`, `vlc`) |
| `--apk_url` | Direct URL to APK or XAPK file |
| `--package_name` | Android package name (for install check + launch) |

Priority: `--apk_url` > `--apk_name` > `--package_name` only

### Available apps (APK_LIBRARY)

| Key | App | Package | Download |
|-----|-----|---------|----------|
| `netflix` | Netflix | `com.netflix.mediaclient` | APKPure (auto) |
| `vlc` | VLC for Android | `org.videolan.vlc` | Manual |
| `mxplayer` | MX Player | `com.mxtech.videoplayer.ad` | Manual |

---

## How it works

```
1. Connect via ADB (emulator or TCP/IP device)
2. Check if package already installed → if yes, launch and done
3. Download APK/XAPK from URL (if --apk_url or library download_url)
4. Detect format:
   - Single APK → adb install -r (auto-renames .xapk → .apk for ADB)
   - True XAPK (zip with split APKs) → extract + adb install-multiple
5. Verify installation + launch app
6. Report: ALREADY_INSTALLED / INSTALLED / FAILED
```

---

## XAPK support

XAPK is a ZIP file containing split APKs (app bundles). The script:
1. Detects XAPK by checking for `.apk` files inside the ZIP
2. Reads `manifest.json` for package name
3. Extracts all `.apk` files to a temp directory
4. Installs via `adb install-multiple -r`

Note: Some downloads end in `.xapk` but are actually single APKs (e.g., Netflix from APKPure). The script handles this — if no `.apk` files inside the ZIP, it falls back to single APK install.

---

## QualiAi integration

QualiAi's pipeline uses this script for mobile platform testing. Three app source modes:

| Mode | CreateProjectModal field | Pipeline behavior |
|------|--------------------------|-------------------|
| `package` | Package name input | Check if installed, launch |
| `apk_url` | APK URL input | Download, install, launch |
| `apk_upload` | File upload | Store on host, install, launch |

The pipeline calls this script on the VPT host before starting the crawl-app skill.

---

## Adding apps to the library

```python
"myapp": {
    "display_name": "My App",
    "package": "com.example.myapp",
    "download_url": "https://direct-download-url.com/app.apk",
    "apk_path": "/tmp/apks/myapp.apk",
    "targets": ["android_mobile", "android_tablet"],
},
```

---

## ADB requirements

Emulators: TCP/IP enabled by default (port 5554/5555).
Physical devices: `adb tcpip 5555 && adb connect <ip>:5555`
