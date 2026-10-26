"""HDMI signal presence read from the capture dongle's HID interface.

Generic UVC grabbers (MacroSilicon MS2109 / MS2130) never tell V4L2 whether HDMI is live: they
stream black or colour bars. Their HID interface (/dev/hidraw*) exposes chip memory through the
`0xB5` read-memory feature report (same protocol as github.com/BertoldVdb/ms-tools), and on the
MS2130 byte 0xF6E9 is 1 when no HDMI signal is present. See docs/agent/devices/MONITOR_PROFILES.md.

`signal_present(device_index)` returns True / False, or None when this dongle gives no answer
(unknown chip, no hidraw, no permission). None means "fall back to the image detector".
"""
import fcntl
import glob
import logging
import os
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# (idVendor, idProduct) -> (register, value meaning "no signal"). Only chips verified live.
_NO_SIGNAL_REGISTER: Dict[Tuple[str, str], Tuple[int, int]] = {
    ('345f', '2130'): (0xF6E9, 1),  # MS2130, verified vpt-mf1 2026-10-19
}

_CACHE_SECONDS = 1.0
_cache: Dict[int, Tuple[float, Optional[bool]]] = {}
_node_cache: Dict[int, Optional[Tuple[str, Tuple[int, str]]]] = {}


def _ioc(nr: int) -> int:
    # _IOC(_IOC_READ|_IOC_WRITE, 'H', nr, 9)
    return (3 << 30) | (9 << 16) | (ord('H') << 8) | nr


def _read_register(hidraw: str, addr: int) -> int:
    fd = os.open(hidraw, os.O_RDWR)
    try:
        req = bytearray([0xB5, addr >> 8, addr & 0xFF, 0, 0, 0, 0, 0, 0])
        fcntl.ioctl(fd, _ioc(0x06), req)  # HIDIOCSFEATURE
        out = bytearray(9)
        out[0] = 0xB5
        fcntl.ioctl(fd, _ioc(0x07), out)  # HIDIOCGFEATURE
        return out[3]
    finally:
        os.close(fd)


def _usb_device_dir(sys_node: str) -> str:
    """The USB device directory (holds idVendor) above a sysfs interface node."""
    path = os.path.realpath(sys_node)
    while path and path != '/':
        if os.path.exists(os.path.join(path, 'idVendor')):
            return path
        path = os.path.dirname(path)
    return ''


def _find_node(device_index: int) -> Optional[Tuple[str, Tuple[int, str]]]:
    """(hidraw path, (register, no-signal value)) for DEVICE<n>, or None."""
    video = os.getenv(f'DEVICE{device_index}_VIDEO', '').split('#')[0].strip()
    if not video.startswith('/dev/'):
        return None
    video_name = os.path.basename(os.path.realpath(video))
    usb_dir = _usb_device_dir(f'/sys/class/video4linux/{video_name}/device')
    if not usb_dir:
        return None
    with open(os.path.join(usb_dir, 'idVendor')) as f:
        vendor = f.read().strip()
    with open(os.path.join(usb_dir, 'idProduct')) as f:
        product = f.read().strip()
    spec = _NO_SIGNAL_REGISTER.get((vendor, product))
    if spec is None:
        return None
    for node in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        if _usb_device_dir(os.path.join(node, 'device')) == usb_dir:
            return '/dev/' + os.path.basename(node), spec
    return None


def signal_present(device_index: Optional[int]) -> Optional[bool]:
    """True = HDMI signal, False = no HDMI signal, None = dongle cannot tell."""
    if not device_index:
        return None
    now = time.monotonic()
    hit = _cache.get(device_index)
    if hit and now - hit[0] < _CACHE_SECONDS:
        return hit[1]
    result: Optional[bool] = None
    try:
        if device_index not in _node_cache:
            _node_cache[device_index] = _find_node(device_index)
        node = _node_cache[device_index]
        if node:
            hidraw, (addr, no_signal_value) = node
            result = _read_register(hidraw, addr) != no_signal_value
    except OSError as e:
        logger.debug(f"hdmi_signal DEVICE{device_index}: {e}")
        _node_cache.pop(device_index, None)  # re-resolve next time (replug renumbers hidraw)
    _cache[device_index] = (now, result)
    return result
