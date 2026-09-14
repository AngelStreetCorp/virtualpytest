#!/usr/bin/env python3
"""
Android App Install Script for VirtualPyTest

Checks if an app from the APK library is installed on the device.
If not installed, downloads and installs it via ADB.
Supports single APK and XAPK (split APK) formats.

Usage:
    python test_scripts/android/app_install.py --apk_name vlc
    python test_scripts/android/app_install.py --apk_url https://example.com/app.apk
    python test_scripts/android/app_install.py --apk_url https://example.com/app.xapk --package_name com.example.app

Examples:
    python test_scripts/android/app_install.py --apk_name vlc --device device1
    python test_scripts/android/app_install.py --apk_url https://dl.example.com/netflix.xapk --package_name com.netflix.mediaclient
"""

import sys
import os
import re
import subprocess
import tempfile
import time
import urllib.request
import zipfile
import json
import shutil
from datetime import datetime

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device


# ---------------------------------------------------------------------------
# APK Library
# Add entries here to grow the library. Supported fields:
#   display_name  Human-readable app name
#   package       Android package ID (used to check if already installed)
#   download_url  Direct APK download URL (None = use apk_path instead)
#   apk_path      Local fallback APK path (used when download_url is None)
#   targets       Informational — which device models this app is for
# ---------------------------------------------------------------------------
APK_LIBRARY = {
    "vlc": {
        "display_name": "VLC for Android",
        "package": "org.videolan.vlc",
        # Official VLC APK — get latest URL from https://www.videolan.org/vlc/download-android.html
        "download_url": None,
        "apk_path": "/tmp/apks/vlc.apk",
        "targets": ["android_mobile", "android_tablet", "android_tv"],
    },
    "mxplayer": {
        "display_name": "MX Player",
        "package": "com.mxtech.videoplayer.ad",
        # Available on APKMirror — set download_url or drop APK to apk_path
        "download_url": None,
        "apk_path": "/tmp/apks/mxplayer.apk",
        "targets": ["android_mobile", "android_tablet"],
    },
    "googletv": {
        "display_name": "Google TV",
        "package": "com.google.android.apps.tv.launcherx",
        # Google TV is a proprietary GMS app — NOT available as standalone APK.
        # Requires a Google TV certified device or system image.
        "download_url": None,
        "apk_path": None,
        "targets": ["android_tv"],
        "not_installable": True,
        "not_installable_reason": "Google TV requires a certified device and cannot be installed via APK.",
    },
    "netflix": {
        "display_name": "Netflix",
        "package": "com.netflix.mediaclient",
        "download_url": "https://d.apkpure.net/b/XAPK/com.netflix.mediaclient?version=latest",
        "apk_path": "/tmp/apks/netflix.apk",
        "targets": ["android_mobile", "android_tablet"],
        "notes": "Netflix uses split APKs. Download XAPK from apkpure.com and place at apk_path, or use --apk_url",
    },
}


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

def _resolve_serial(device_ip: str, device_port: str = "5555") -> str:
    """
    Resolve the ADB serial for a device.
    - Local emulator (127.0.0.1): use emulator-<port-1> (e.g. port 5555 -> emulator-5554)
    - Remote device: use <ip>:<port>
    """
    if device_ip in ("127.0.0.1", "localhost"):
        try:
            emulator_port = int(device_port) - 1
        except (ValueError, TypeError):
            emulator_port = 5554
        return f"emulator-{emulator_port}"
    return f"{device_ip}:{device_port}"


def _adb(serial: str, *args) -> subprocess.CompletedProcess:
    """Run an adb command targeting the device by serial."""
    cmd = ["adb", "-s", serial] + list(args)
    print(f"[app_install] adb -s {serial} {' '.join(args)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def _is_installed(serial: str, package: str) -> bool:
    result = _adb(serial, "shell", "pm", "list", "packages", package)
    return f"package:{package}" in result.stdout


def _connect(device_ip: str, device_port: str = "5555") -> tuple[bool, str]:
    """
    Connect to device. Returns (success, serial).
    - Local emulators are already connected — just verify the serial is in adb devices.
    - Remote devices require adb connect.
    """
    serial = _resolve_serial(device_ip, device_port)

    if device_ip in ("127.0.0.1", "localhost"):
        # Local emulator — verify it's listed in adb devices
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        if serial in result.stdout:
            print(f"[app_install] local emulator {serial} already connected")
            return True, serial
        # Try connecting anyway (emulator may need a nudge)
        subprocess.run(["adb", "connect", f"127.0.0.1:{device_port}"], capture_output=True, text=True, timeout=10)
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        if serial in result.stdout:
            print(f"[app_install] local emulator {serial} connected after nudge")
            return True, serial
        print(f"[app_install] local emulator {serial} not found in: {result.stdout.strip()}")
        return False, serial

    # Remote device — explicit adb connect
    result = subprocess.run(
        ["adb", "connect", f"{device_ip}:{device_port}"],
        capture_output=True, text=True, timeout=10
    )
    connected = "connected" in result.stdout.lower() or "already connected" in result.stdout.lower()
    print(f"[app_install] connect {device_ip}:{device_port} -> {result.stdout.strip()}")
    return connected, serial


def _download_apk(url: str, dest: str) -> bool:
    print(f"[app_install] Downloading from {url} -> {dest}")
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        print(f"[app_install] Downloaded {size / 1024:.1f} KB")
        return size > 0
    except Exception as e:
        print(f"[app_install] Download failed: {e}")
        return False


def _install_apk(serial: str, apk_path: str) -> tuple[bool, str]:
    """Returns (success, message). Handles non-.apk extensions (adb requires .apk)."""
    if not os.path.exists(apk_path):
        return False, f"APK not found: {apk_path}"
    # ADB requires .apk extension — rename if needed
    actual_path = apk_path
    if not apk_path.endswith('.apk'):
        actual_path = apk_path.rsplit('.', 1)[0] + '.apk' if '.' in os.path.basename(apk_path) else apk_path + '.apk'
        shutil.copy2(apk_path, actual_path)
        print(f"[app_install] Renamed {os.path.basename(apk_path)} -> {os.path.basename(actual_path)} (adb requires .apk)")
    result = _adb(serial, "install", "-r", actual_path)
    success = "Success" in result.stdout
    msg = result.stdout.strip() or result.stderr.strip()
    return success, msg


# ---------------------------------------------------------------------------
# XAPK (split APK) support
# ---------------------------------------------------------------------------

def _is_xapk(filepath: str) -> bool:
    """Check if file is true XAPK format (zip containing multiple .apk files).
    Some downloads end in .xapk but are actually single APKs — detect this."""
    try:
        with zipfile.ZipFile(filepath, 'r') as z:
            names = z.namelist()
            apk_files = [n for n in names if n.endswith('.apk')]
            # True XAPK has split APK files inside; a single APK zip has AndroidManifest.xml etc. but no .apk entries
            return len(apk_files) > 0
    except Exception:
        return False


def _extract_xapk(xapk_path: str, extract_dir: str) -> tuple[list, str | None]:
    """Extract XAPK and return (list of APK paths, package_name)."""
    apk_paths = []
    package_name = None

    # Clean extract dir if it exists
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(xapk_path, 'r') as z:
        # Read manifest for package name
        if 'manifest.json' in z.namelist():
            manifest = json.loads(z.read('manifest.json'))
            package_name = manifest.get('package_name')
            print(f"[app_install] XAPK manifest: package={package_name}")

        # Extract all .apk files
        for name in z.namelist():
            if name.endswith('.apk'):
                z.extract(name, extract_dir)
                apk_paths.append(os.path.join(extract_dir, name))
                print(f"[app_install] Extracted: {name}")

    print(f"[app_install] XAPK contains {len(apk_paths)} APK(s)")
    return apk_paths, package_name


def _install_split_apks(serial: str, apk_paths: list) -> tuple[bool, str]:
    """Install split APKs using adb install-multiple."""
    cmd = ["adb", "-s", serial, "install-multiple", "-r"] + apk_paths
    print(f"[app_install] adb install-multiple with {len(apk_paths)} APKs")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    success = "Success" in result.stdout
    msg = result.stdout.strip() or result.stderr.strip()
    return success, msg


def _get_package_from_apk(apk_path: str) -> str | None:
    """Extract package name from APK using aapt."""
    # Try aapt first
    try:
        result = subprocess.run(
            ["aapt", "dump", "badging", apk_path],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split('\n'):
            if line.startswith('package:'):
                match = re.search(r"name='([^']+)'", line)
                if match:
                    return match[1]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: read AndroidManifest.xml from the APK (binary XML but package name is often readable)
    try:
        with zipfile.ZipFile(apk_path, 'r') as z:
            if 'AndroidManifest.xml' in z.namelist():
                data = z.read('AndroidManifest.xml')
                # Package name appears as a readable string in the binary manifest
                text = data.decode('latin-1')
                # Look for common package patterns
                match = re.search(r'(com\.[a-zA-Z0-9_.]+)', text)
                if match:
                    return match[1]
    except Exception:
        pass

    return None


def _launch_app(serial: str, package: str, wait_s: int = 8) -> bool:
    """Launch app via monkey and wait for it to render. Returns True if launch succeeded."""
    print(f"[app_install] Launching {package}...")
    result = _adb(serial, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
    launched = "Events injected: 1" in result.stdout
    if launched:
        print(f"[app_install] App launched — waiting {wait_s}s for render...")
        time.sleep(wait_s)
    else:
        print(f"[app_install] Launch output: {result.stdout.strip()} {result.stderr.strip()}")
    return launched


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

def _build_report(context) -> str:
    lines = ["ANDROID APP INSTALL REPORT", "=" * 40]

    app_name = getattr(context, "app_display_name", "Unknown")
    package = getattr(context, "app_package", "Unknown")
    status = getattr(context, "install_status", "UNKNOWN")

    lines.append(f"App:     {app_name}")
    lines.append(f"Package: {package}")
    lines.append(f"Status:  {status}")

    if hasattr(context, "already_installed") and context.already_installed:
        lines.append("Result:  Already installed — launched")
    elif hasattr(context, "install_message"):
        lines.append(f"Result:  {context.install_message}")

    if hasattr(context, "error_message") and context.error_message:
        lines.append(f"Error:   {context.error_message}")

    exec_time = context.get_execution_time_ms() if hasattr(context, "get_execution_time_ms") else 0
    lines.append(f"Time:    {exec_time / 1000:.1f}s")

    return "\n".join(lines)


def _build_step_result(context, success: bool) -> dict:
    status = getattr(context, "install_status", "UNKNOWN")
    return {
        "step_number": 1,
        "success": success,
        "message": f"App Install — {status}",
        "actions": [{"command": "install_apk", "params": {"apk_name": getattr(context, "apk_name", "")}}],
        "action_results": [{
            "action_category": "main",
            "success": success,
            "message": getattr(context, "install_message", ""),
        }],
        "verifications": [{"command": "verify_install", "type": "package_check"}],
        "verification_results": [{
            "success": success,
            "verification_type": "package_check",
            "message": f"Package {getattr(context, 'app_package', '')} {'installed' if success else 'not installed'}",
        }],
        "execution_time_ms": context.get_execution_time_ms(),
        "start_time": datetime.now().isoformat(),
        "end_time": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Helpers for context failure/success reporting
# ---------------------------------------------------------------------------

def _fail(context, error_msg: str, status: str = "FAILED") -> bool:
    """Set context for a failure and return False."""
    context.error_message = error_msg
    context.install_status = status
    context.overall_success = False
    context.step_results = [_build_step_result(context, False)]
    context.execution_summary = _build_report(context)
    print(f"[app_install] FAILED: {error_msg}")
    return False


def _succeed(context, msg: str, serial: str | None = None, package: str | None = None, already_installed: bool = False) -> bool:
    """Set context for success and return True."""
    context.install_message = msg
    context.already_installed = already_installed
    context.install_status = "ALREADY_INSTALLED" if already_installed else "INSTALLED"
    if serial and package:
        _launch_app(serial, package)
    context.overall_success = True
    context.step_results = [_build_step_result(context, True)]
    context.execution_summary = _build_report(context)
    return True


# ---------------------------------------------------------------------------
# Install from URL (APK or XAPK)
# ---------------------------------------------------------------------------

def _install_from_file(serial: str, filepath: str, package_name: str | None) -> tuple[bool, str, str | None]:
    """
    Install from a local file (APK or XAPK). Returns (success, message, detected_package_name).
    Always checks _is_xapk() regardless of file extension.
    """
    if _is_xapk(filepath):
        print(f"[app_install] Detected XAPK format — extracting split APKs...")
        extract_dir = os.path.join(tempfile.gettempdir(), 'apks', 'extracted')
        apk_paths, detected_package = _extract_xapk(filepath, extract_dir)

        if not apk_paths:
            return False, "XAPK contains no APK files", package_name or detected_package

        if not package_name:
            package_name = detected_package

        success, msg = _install_split_apks(serial, apk_paths)
        return success, msg, package_name
    else:
        # Single APK
        if not package_name:
            package_name = _get_package_from_apk(filepath)
            if package_name:
                print(f"[app_install] Detected package from APK: {package_name}")

        success, msg = _install_apk(serial, filepath)
        return success, msg, package_name


# ---------------------------------------------------------------------------
# Main script
# ---------------------------------------------------------------------------

@script("app_install", "Check and install an Android app via ADB", default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()

    apk_name = (args.apk_name or "").strip().lower()
    apk_url = (args.apk_url or "").strip()
    package_name = (args.package_name or "").strip()

    context.apk_name = apk_name or apk_url or "custom"
    context.app_display_name = apk_name or apk_url.split('/')[-1] if apk_url else "Unknown"
    context.app_package = package_name or "Unknown"

    print(f"[app_install] Device: {device.device_name} ({device.device_model}) @ {device.device_ip}")
    print(f"[app_install] apk_name={apk_name!r}  apk_url={apk_url!r}  package_name={package_name!r}")

    # --- Validate: need at least one of apk_name, apk_url, or package_name ---
    if not apk_name and not apk_url and not package_name:
        available = ", ".join(APK_LIBRARY.keys())
        return _fail(context, f"Provide --apk_name (library: {available}), --apk_url, or --package_name")

    # --- Connect via ADB ---
    device_port = getattr(device, 'device_port', None) or "5555"
    connected, serial = _connect(device.device_ip, str(device_port))
    print(f"[app_install] ADB serial: {serial}")

    if not connected:
        return _fail(context, f"Could not connect to ADB serial {serial}")

    # ===================================================================
    # Flow 1: --apk_url (arbitrary URL — APK or XAPK)
    # ===================================================================
    if apk_url:
        # Check if already installed (if package_name known)
        if package_name and _is_installed(serial, package_name):
            context.app_display_name = package_name
            context.app_package = package_name
            print(f"[app_install] {package_name} is already installed — launching")
            return _succeed(context, f"{package_name} is already installed", serial, package_name, already_installed=True)

        # Determine extension from URL (but we always check actual format later)
        ext = '.xapk' if '.xapk' in apk_url.lower() else '.apk'
        download_dir = os.path.join(tempfile.gettempdir(), 'apks')
        download_path = os.path.join(download_dir, f'download{ext}')

        if not _download_apk(apk_url, download_path):
            return _fail(context, f"Failed to download from {apk_url}")

        success, msg, detected_pkg = _install_from_file(serial, download_path, package_name or None)

        if detected_pkg:
            package_name = detected_pkg
            context.app_package = package_name
            context.app_display_name = package_name

        context.install_message = msg
        context.already_installed = False

        if success:
            print(f"[app_install] Install succeeded: {msg}")
            context.install_status = "INSTALLED"
            if package_name:
                _launch_app(serial, package_name)
            context.overall_success = True
            context.step_results = [_build_step_result(context, True)]
            context.execution_summary = _build_report(context)
            return True
        else:
            return _fail(context, msg)

    # ===================================================================
    # Flow 2: --package_name only (no apk_name, no apk_url)
    # ===================================================================
    if not apk_name and package_name:
        context.app_display_name = package_name
        context.app_package = package_name

        if _is_installed(serial, package_name):
            print(f"[app_install] {package_name} is already installed — launching")
            return _succeed(context, f"{package_name} is already installed", serial, package_name, already_installed=True)
        else:
            return _fail(context, f"{package_name} is not installed. Provide --apk_url or --apk_name to install it.")

    # ===================================================================
    # Flow 3: --apk_name (library lookup — original flow)
    # ===================================================================
    if apk_name not in APK_LIBRARY:
        available = ", ".join(APK_LIBRARY.keys())
        return _fail(context, f"Unknown app '{apk_name}'. Available: {available}")

    entry = APK_LIBRARY[apk_name]
    context.app_display_name = entry["display_name"]
    context.app_package = entry["package"]

    # Fail early if app is marked as not installable
    if entry.get("not_installable"):
        reason = entry.get("not_installable_reason", "This app cannot be installed on this device.")
        return _fail(context, reason, status="NOT_INSTALLABLE")

    print(f"[app_install] App: {entry['display_name']} ({entry['package']})")

    # Check if already installed
    if _is_installed(serial, entry["package"]):
        print(f"[app_install] {entry['display_name']} is already installed — launching")
        return _succeed(context, f"{entry['display_name']} is already installed", serial, entry["package"], already_installed=True)

    # Resolve APK path
    apk_path = entry.get("apk_path") or os.path.join(tempfile.gettempdir(), "apks", f"{apk_name}.apk")
    download_url = entry.get("download_url")

    if download_url and not os.path.exists(apk_path):
        print(f"[app_install] APK not found locally — downloading...")
        if not _download_apk(download_url, apk_path):
            return _fail(context, f"Failed to download APK from {download_url}")

    if not os.path.exists(apk_path):
        return _fail(context, (
            f"APK not found at {apk_path}. "
            f"Set download_url in APK_LIBRARY, drop the APK file there manually, or use --apk_url."
        ))

    # Install (handles both APK and XAPK transparently)
    print(f"[app_install] Installing {entry['display_name']} from {apk_path}...")
    success, msg, _ = _install_from_file(serial, apk_path, entry["package"])

    context.install_message = msg
    context.already_installed = False

    if success:
        print(f"[app_install] Install succeeded: {msg}")
        context.install_status = "INSTALLED"
        _launch_app(serial, entry["package"])
    else:
        print(f"[app_install] Install failed: {msg}")
        context.error_message = msg
        context.install_status = "FAILED"

    context.overall_success = success
    context.step_results = [_build_step_result(context, success)]
    context.execution_summary = _build_report(context)
    return success


# Script arguments
main._script_args = [
    '--apk_name:str:',       # App key from APK_LIBRARY (optional)
    '--apk_url:str:',        # Direct APK/XAPK download URL (optional)
    '--package_name:str:',   # Package name (optional, for launch after install)
]
main._script_description = "Install an Android app via ADB if not present. Supports APK and XAPK (split APK) formats."
main._arg_descriptions = {
    'apk_name': 'App key from APK library (e.g. vlc, netflix)',
    'apk_url': 'Direct download URL for APK or XAPK file',
    'package_name': 'Android package name (e.g. com.netflix.mediaclient) — for checking install status and launching',
}

main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "android_mobile",
}

if __name__ == "__main__":
    main()
