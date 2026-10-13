"""grabber_detect — enumerate the capture / audio / bluetooth / IR peripherals
attached to a host and pair each UVC video node with the USB UAC card that
shares its USB parent.

This is a Python port of `scripts/detect_grabber.sh`, returning the same data as
a JSON-friendly dict so the host's HTTP API can expose it without forking a
shell. The CLI script is kept for operator-side eyeballing; this module is the
programmatic surface that powers the Host & Devices UI's auto-fill.

Why pairing lives on the USB parent: a UVC + UAC composite device (MS2109, the
"sabrent" dongle, the elgato cam link pair) shows up as two separate /dev/video
nodes and one or more /dev/snd/cardN nodes, but they all live under the same
USB device directory. The host writes the kernel-assigned names
(`/dev/video0`, `plughw:2,0`) to its .env; those shuffle across reboots, so the
stable key is the USB port string (`3-1`, `5-2`). We surface the port so the
operator can pin udev rules to it.

Usage:
    from backend_host.src.lib.grabber_detect import detect_grabbers
    report = detect_grabbers()
    # report == {'grabbers': [...], 'bluetooth': [...], 'infrared': [...]}
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any


# Bit 0 of V4L2's device capabilities = V4L2_CAP_VIDEO_CAPTURE. Every UVC device
# with a metadata sibling exposes two nodes under /dev/video*; only the capture
# node is usable as an ffmpeg source, so we filter to it the same way the bash
# script does.
_V4L2_CAP_VIDEO_CAPTURE = 0x1


def _readlink(path: str) -> str:
    try:
        return os.readlink(path)
    except OSError:
        return ''


def _is_link(path: str) -> bool:
    return os.path.lexists(path) and os.path.islink(path)


def _usb_parent(device_path: str, sysfs_root: str) -> str:
    """Walk up the sysfs tree from `device_path` until we hit the USB device
    node (the one that has `idVendor`). Returns the absolute path, or '' if
    the device is not under a USB bus."""
    if not device_path:
        return ''
    # Combine: device_path is already absolute (e.g. /sys/class/video4linux/video0/device)
    # or relative. We resolve to absolute and then walk up.
    p = device_path
    if not os.path.isabs(p):
        p = os.path.join(sysfs_root, p.lstrip('/'))
    p = os.path.normpath(p)
    while p and p != '/' and not os.path.isfile(os.path.join(p, 'idVendor')):
        parent = os.path.dirname(p)
        if parent == p:
            return ''
        p = parent
    id_vendor_path = os.path.join(p, 'idVendor')
    if not os.path.isfile(id_vendor_path):
        return ''
    return p


def _usb_parent_from_symlink(symlink_path: str, sysfs_root: str) -> str:
    """Resolve a sysfs symlink (like /sys/class/video4linux/video0/device)
    and then walk up. Uses ``os.path.realpath`` so layered parent symlinks
    are followed: real Linux sysfs exposes ``/sys/class/video4linux/video0``
    as a symlink to ``../../devices/.../video4linux/video0``, and the
    ``device`` symlink under it also resolves through that bridge. Walking
    the canonical path lands on the USB device node (with ``idVendor``) in
    a single step, the same way the bash script's ``readlink -f`` does."""
    real = os.path.realpath(symlink_path) if _is_link(symlink_path) else symlink_path
    return _usb_parent(real, sysfs_root)


def _card_for_usb(usb_path: str, sysfs_root: str) -> int | None:
    """If `usb_path` is a USB device directory that owns an ALSA sound card,
    return the card number. The card's `device/` symlink resolves into the
    same USB device tree, so the same `_usb_parent` walk matches."""
    if not usb_path:
        return None
    sound_root = os.path.join(sysfs_root, 'class', 'sound')
    if not os.path.isdir(sound_root):
        return None
    for entry in sorted(os.listdir(sound_root)):
        if not entry.startswith('card'):
            continue
        card_path = os.path.join(sound_root, entry, 'device')
        if not os.path.isdir(card_path) and not _is_link(card_path):
            continue
        parent = _usb_parent_from_symlink(card_path, sysfs_root)
        if parent and os.path.normpath(parent) == os.path.normpath(usb_path):
            try:
                return int(entry[len('card'):])
            except ValueError:
                continue
    return None


def _is_capture_node(dev_path: str, v4l2_ctl: str = 'v4l2-ctl') -> bool:
    """Run `v4l2-ctl -d <dev> --info` and return True iff the device's
    Device Caps include V4L2_CAP_VIDEO_CAPTURE (bit 0). Permission errors
    short-circuit to False (the operator running this script must be in the
    `video` group)."""
    try:
        result = subprocess.run(
            [v4l2_ctl, '-d', dev_path, '--info'],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False
    # Output line is e.g.: "        Device Caps      : 0x04a00001"
    m = re.search(r'Device Caps\s*:\s*0x([0-9a-fA-F]+)', result.stdout)
    if not m:
        return False
    try:
        caps = int(m.group(1), 16)
    except ValueError:
        return False
    return bool(caps & _V4L2_CAP_VIDEO_CAPTURE)


def _read_usb_id(usb_path: str) -> tuple[str, str]:
    """Return (vendor, product) id strings read from idVendor/idProduct.
    Empty string if the file is missing or unreadable."""
    if not usb_path:
        return '', ''
    vendor = ''
    product = ''
    try:
        with open(os.path.join(usb_path, 'idVendor'), 'r', encoding='utf-8') as f:
            vendor = f.read().strip()
    except (OSError, IOError):
        pass
    try:
        with open(os.path.join(usb_path, 'idProduct'), 'r', encoding='utf-8') as f:
            product = f.read().strip()
    except (OSError, IOError):
        pass
    return vendor, product


def _read_bluetooth_address(hci_path: str, name: str, hciconfig: str = 'hciconfig') -> str:
    """The /sys/class/bluetooth/hciN/address file is often empty until the
    controller is powered up; hciconfig reads the BD address directly. Empty
    string if we cannot determine the MAC."""
    mac = ''
    try:
        with open(os.path.join(hci_path, 'address'), 'r', encoding='utf-8') as f:
            mac = f.read().strip()
    except (OSError, IOError):
        pass
    if mac and mac != '00:00:00:00:00:00':
        return mac
    try:
        result = subprocess.run(
            [hciconfig, name],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return mac or ''
    if result.returncode != 0:
        return mac or ''
    m = re.search(r'BD Address:\s*([0-9A-Fa-f:]{17})', result.stdout)
    if m:
        return m.group(1)
    return mac or ''


def detect_grabbers(
    sysfs_root: str = '/sys',
    v4l2_ctl: str = 'v4l2-ctl',
    hciconfig: str = 'hciconfig',
) -> dict[str, list[dict[str, Any]]]:
    """Enumerate capture cards, bluetooth controllers, and IR receivers.

    Returns a dict with three keys: 'grabbers', 'bluetooth', 'infrared'. Each
    grabber entry is paired with its USB UAC card (same USB parent) so the
    host .env can write `DEVICE1_VIDEO=/dev/video0` and
    `DEVICE1_VIDEO_AUDIO=plughw:1,0` without the operator looking it up.

    The function is read-only and never raises on missing devices: a headless
    host with no capture cards, no bluetooth, and no IR returns three empty
    lists. This is the same behavior as the bash script.
    """
    grabbers: list[dict[str, Any]] = []
    bluetooth: list[dict[str, Any]] = []
    infrared: list[dict[str, Any]] = []

    video4linux_root = os.path.join(sysfs_root, 'class', 'video4linux')
    if os.path.isdir(video4linux_root):
        for entry in sorted(os.listdir(video4linux_root)):
            if not entry.startswith('video'):
                continue
            dev_path = f'/dev/{entry}'
            if not _is_capture_node(dev_path, v4l2_ctl=v4l2_ctl):
                continue
            v4l_path = os.path.join(video4linux_root, entry)
            usb_path = _usb_parent_from_symlink(os.path.join(v4l_path, 'device'), sysfs_root)
            if not usb_path:
                continue
            vendor, product = _read_usb_id(usb_path)
            card_num = _card_for_usb(usb_path, sysfs_root)
            if card_num is not None:
                audio = f'plughw:{card_num},0'
                has_audio = True
            else:
                audio = '(none)'
                has_audio = False
            grabbers.append({
                'video': dev_path,
                'audio': audio,
                'has_audio': has_audio,
                'usb_id': f'{vendor}:{product}' if vendor and product else '',
                'usb_path': os.path.basename(usb_path),
                'vendor': vendor,
                'product': product,
            })

    bluetooth_root = os.path.join(sysfs_root, 'class', 'bluetooth')
    if os.path.isdir(bluetooth_root):
        for entry in sorted(os.listdir(bluetooth_root)):
            if not entry.startswith('hci'):
                continue
            hci_path = os.path.join(bluetooth_root, entry)
            mac = _read_bluetooth_address(hci_path, entry, hciconfig=hciconfig)
            usb_path = _usb_parent_from_symlink(os.path.join(hci_path, 'device'), sysfs_root)
            if usb_path:
                vendor, product = _read_usb_id(usb_path)
                usb_id = f'{vendor}:{product}' if vendor and product else ''
                usb_path_str = os.path.basename(usb_path)
                bluetooth.append({
                    'name': entry,
                    'mac': mac or '',
                    'usb_id': usb_id,
                    'usb_path': usb_path_str,
                })
            else:
                bluetooth.append({
                    'name': entry,
                    'mac': mac or '',
                    'usb_id': '',
                    'usb_path': '',
                })

    lirc_root = os.path.join(sysfs_root, 'class', 'lirc')
    if os.path.isdir(lirc_root):
        for entry in sorted(os.listdir(lirc_root)):
            if not entry.startswith('lirc'):
                continue
            name = f'/dev/{entry}'
            usb_path = _usb_parent_from_symlink(os.path.join(lirc_root, entry, 'device'), sysfs_root)
            if usb_path:
                vendor, product = _read_usb_id(usb_path)
                infrared.append({
                    'name': name,
                    'usb_id': f'{vendor}:{product}' if vendor and product else '',
                    'usb_path': os.path.basename(usb_path),
                })
            else:
                infrared.append({
                    'name': name,
                    'usb_id': '',
                    'usb_path': '',
                })

    return {'grabbers': grabbers, 'bluetooth': bluetooth, 'infrared': infrared}
