"""Foreground app of an adb-driven phone (profile `mobile`): its package, named for the video badge.

One short read-only `dumpsys activity activities | grep -m1 topResumedActivity` per device, never faster than
READ_EVERY_S, on a background thread (the 1 Hz Localize worker must never wait on adb, BUG-0675), with a 3 s timeout, and
never while a script or take-control is driving the device (a command in `last_action.json` within BUSY_WINDOW_S): then the last
answer, or the package of the last launch_app, is kept. phone_agent phones are not read (their app is the agent, see PHONE_AGENT.md).
"""
import logging
import os
import re
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("capture_monitor")

READ_EVERY_S = 30.0
BUSY_WINDOW_S = 20.0
ADB_TIMEOUT_S = 3.0
_CMD = 'dumpsys activity activities | grep -m1 -E "topResumedActivity|mResumedActivity"'
_PKG = re.compile(r'\bu\d+\s+([A-Za-z0-9_.]+)/')

# package -> badge text. Anything else falls back to the last package segment, capitalised.
APP_LABELS = {
    'com.supercell.clashofclans': 'Clash of Clans',
    'com.google.android.youtube': 'YouTube',
    'com.netflix.mediaclient': 'Netflix',
    'com.android.chrome': 'Chrome',
    'com.android.launcher3': 'Home screen',
    'com.sec.android.app.launcher': 'Home screen',
    'io.virtualpytest.app': 'VirtualPyTest',
}


def parse_package(text: str) -> Optional[str]:
    m = _PKG.search(text or '')
    return m.group(1) if m else None


def app_label(package: str) -> str:
    return APP_LABELS.get(package) or package.rsplit('.', 1)[-1].replace('_', ' ').title()


def adb_address(env) -> Optional[str]:
    """DEVICE<N>_ADB_SERIAL, else ip:port, from the given env mapping; None for a device with neither."""
    return env.get('serial') or (f"{env['ip']}:{env.get('port') or 5555}" if env.get('ip') else None)


class ForegroundApp:
    def __init__(self):
        self._pkg: Dict[str, Tuple[Optional[str], float]] = {}   # device_id -> (package, read at)
        self._running: Dict[str, bool] = {}

    def _device_env(self, device_id: str) -> Optional[dict]:
        m = re.fullmatch(r'device(\d+)', device_id or '')
        if not m:
            return None
        n = m.group(1)
        if (os.getenv(f'DEVICE{n}_MODEL') or '').strip() != 'android_mobile':
            return None
        return {'serial': (os.getenv(f'DEVICE{n}_ADB_SERIAL') or '').strip() or None,
                'ip': (os.getenv(f'DEVICE{n}_IP') or '').strip() or None,
                'port': (os.getenv(f'DEVICE{n}_PORT') or '').strip() or None}

    def _read(self, device_id: str, address: str) -> None:
        pkg = None
        try:
            out = subprocess.run(['adb', '-s', address, 'shell', _CMD], capture_output=True, text=True,
                                 timeout=ADB_TIMEOUT_S).stdout
            pkg = parse_package(out)
        except Exception as e:                        # timeout, adb missing, device offline: keep the last answer
            logger.debug(f"[foreground] {device_id} read failed: {e}")
        finally:
            prev = self._pkg.get(device_id)
            self._pkg[device_id] = (pkg or (prev[0] if prev else None), time.time())
            self._running[device_id] = False

    def get(self, device_id: str, busy: bool, last_launch: Optional[str] = None) -> Optional[str]:
        """Package in the foreground (cached; starts a background read when one is due and the device is idle)."""
        env = self._device_env(device_id)
        address = adb_address(env) if env else None
        if not address:
            return None
        cached = self._pkg.get(device_id)
        if cached is None and last_launch:
            cached = self._pkg[device_id] = (last_launch, 0.0)    # seed: the app a script just launched
        due = cached is None or time.time() - cached[1] >= READ_EVERY_S
        if due and not busy and not self._running.get(device_id):
            self._running[device_id] = True
            threading.Thread(target=self._read, args=(device_id, address), daemon=True, name="foreground-app").start()
        return cached[0] if cached else None
