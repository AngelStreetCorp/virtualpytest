#!/usr/bin/env python3
"""Browser window sizing helpers for Chrome/Chromium launches."""

import os
import platform
import re
import shutil
import subprocess
from typing import Dict, Optional


def _run_command(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _parse_bounds_csv(raw_value: str) -> Optional[Dict[str, int]]:
    numbers = [int(part.strip()) for part in raw_value.split(",") if part.strip()]
    if len(numbers) != 4:
        return None
    left, top, right, bottom = numbers
    width = max(0, right - left)
    height = max(0, bottom - top)
    if width <= 0 or height <= 0:
        return None
    return {"x": left, "y": top, "width": width, "height": height}


def _detect_macos_display_bounds() -> Optional[Dict[str, int]]:
    raw_value = _run_command(
        ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop']
    )
    return _parse_bounds_csv(raw_value)


def _detect_windows_display_bounds() -> Optional[Dict[str, int]]:
    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if not powershell:
        return None
    raw_value = _run_command([
        powershell,
        "-NoProfile",
        "-Command",
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        'Write-Output "$($b.X),$($b.Y),$($b.Width),$($b.Height)"',
    ])
    numbers = [int(part.strip()) for part in raw_value.split(",") if part.strip()]
    if len(numbers) != 4:
        return None
    x, y, width, height = numbers
    if width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _parse_xrandr_line(line: str) -> Optional[Dict[str, int]]:
    match = re.search(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", line)
    if not match:
        return None
    width, height, x, y = [int(value) for value in match.groups()]
    if width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _detect_linux_display_bounds() -> Optional[Dict[str, int]]:
    xrandr = shutil.which("xrandr")
    if xrandr and os.environ.get("DISPLAY"):
        raw_value = _run_command([xrandr, "--current"])
        lines = [line.strip() for line in raw_value.splitlines() if " connected" in line]
        for line in lines:
            if " primary " in line:
                parsed = _parse_xrandr_line(line)
                if parsed:
                    return parsed
        for line in lines:
            parsed = _parse_xrandr_line(line)
            if parsed:
                return parsed
    return None


def detect_primary_display_bounds() -> Dict[str, int]:
    """Detect primary display bounds for use with explicit browser sizing."""
    system_name = platform.system()
    detectors = {
        "Darwin": _detect_macos_display_bounds,
        "Windows": _detect_windows_display_bounds,
        "Linux": _detect_linux_display_bounds,
    }
    detector = detectors.get(system_name)
    bounds = detector() if detector else None
    if bounds:
        return bounds
    return {"x": 0, "y": 0, "width": 1920, "height": 1080}


def build_window_flags() -> list[str]:
    """Build explicit Chrome window flags from detected display bounds."""
    bounds = detect_primary_display_bounds()
    return [
        f'--window-position={bounds["x"]},{bounds["y"]}',
        f'--window-size={bounds["width"]},{bounds["height"]}',
    ]
