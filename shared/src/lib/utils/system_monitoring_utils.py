"""
System Monitoring Utilities

Centralized system monitoring functions for VirtualPyTest.
Provides shared utilities for CPU load average and temperature monitoring
used by both backend_host and backend_server.
"""

import os
import platform
import sys
import subprocess
from typing import Tuple, Optional


def _get_load_average() -> Tuple[float, float, float]:
    """
    Get load average (1m, 5m, 15m). Uses os.getloadavg(); on failure (e.g. Debian in
    container) falls back to reading /proc/loadavg on Linux. Prevents OSError from
    breaking entire stats collection.

    Returns:
        Tuple of (1m_load, 5m_load, 15m_load) averages
    """
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        pass
    if platform.system() == 'Linux' or sys.platform.startswith('linux'):
        try:
            with open('/proc/loadavg', 'r') as f:
                line = f.read().strip().split()
                if len(line) >= 3:
                    return (float(line[0]), float(line[1]), float(line[2]))
        except (OSError, ValueError):
            pass
    return (0.0, 0.0, 0.0)


def get_cpu_temperature() -> Optional[float]:
    """
    Get CPU temperature: Raspberry Pi (vcgencmd), thermal_zone, or hwmon (Debian/x86).
    
    Returns:
        CPU temperature in Celsius, or None if not available
    """
    try:
        # Method 1: vcgencmd (Raspberry Pi specific)
        result = subprocess.run(['vcgencmd', 'measure_temp'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            temp_str = result.stdout.strip()  # "temp=42.8'C"
            temp_value = float(temp_str.split('=')[1].replace("'C", ""))
            return temp_value
    except Exception:
        pass

    try:
        # Method 2: thermal zone (common on ARM / some x86)
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp_millidegrees = int(f.read().strip())
            return temp_millidegrees / 1000.0
    except Exception:
        pass

    # Method 3: hwmon (Debian/Ubuntu x86: coretemp, k10temp, etc.)
    try:
        hwmon_base = '/sys/class/hwmon'
        if os.path.isdir(hwmon_base):
            best = None
            for name in sorted(os.listdir(hwmon_base)):
                if not name.startswith('hwmon'):
                    continue
                base = os.path.join(hwmon_base, name)
                for entry in os.listdir(base):
                    if entry.startswith('temp') and entry.endswith('_input'):
                        path = os.path.join(base, entry)
                        try:
                            with open(path, 'r') as f:
                                val = int(f.read().strip()) / 1000.0
                                if val > 0 and (best is None or val > best):
                                    best = val
                        except (OSError, ValueError):
                            continue
            if best is not None:
                return best
    except Exception:
        pass

    # Temperature not available - this is normal on VMs, containers, and some cloud instances
    return None
