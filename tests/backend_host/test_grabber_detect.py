"""Unit tests for `backend_host.src.lib.grabber_detect`.

We avoid touching the real /sys tree on the test machine by writing a fixture
under a temporary directory that mirrors the layout the host produces:

    <tmp>/class/video4linux/video0 -> ../../devices/pci/usb3/3-1/3-1:1.0/video4linux/video0
    <tmp>/class/sound/card1/device -> ../../devices/pci/usb3/3-1/3-1:1.2/sound/card1
    <tmp>/class/bluetooth/hci0/device -> ../../devices/pci/usb3/3-10/3-10:1.0/bluetooth/hci0
    <tmp>/class/lirc/lirc0/device -> ../../devices/pci/usb3/3-12/3-12:1.0/lirc/lirc0

Plus the USB device nodes with idVendor/idProduct. v4l2-ctl is mocked because
it is not always installed in CI; we use a tiny shim that reads the device
capability from a sidecar file.
"""
from __future__ import annotations

import os
import sys
import textwrap
import types
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend_host.src.lib import grabber_detect  # noqa: E402


def _write(path: str, content: str = '') -> None:
    parent = os.path.dirname(path)
    # If `parent` is a symlink (e.g. /tmp/.../class/video4linux/video0 that
    # already points to the device-side directory), the underlying target
    # is the right place to create the file. makedirs(exist_ok=True) raises
    # FileExistsError when `parent` itself is a symlink, so fall through
    # and let open() handle the path.
    if not os.path.lexists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _symlink(link: str, target: str) -> None:
    """Create a symlink with the given (relative or absolute) target. We use
    relative targets to mirror how the kernel populates real sysfs."""
    parent = os.path.dirname(link)
    if not os.path.lexists(parent):
        os.makedirs(parent, exist_ok=True)
    if os.path.lexists(link):
        os.unlink(link)
    os.symlink(target, link)


class _FakeV4l2Ctl:
    """Test double for `v4l2-ctl -d <dev> --info`.

    The real binary reports `Device Caps      : 0x<hex>`; we accept a sidecar
    file `<sysfs_root>/__caps__/<dev_basename>` so tests can specify the
    capability of each /dev/video* node without a real video device.
    """

    def __init__(self, sysfs_root: str) -> None:
        self._caps_dir = os.path.join(sysfs_root, '__caps__')
        os.makedirs(self._caps_dir, exist_ok=True)

    def __call__(self, *args: str) -> str:
        # Expected invocation: v4l2-ctl -d /dev/videoN --info
        if '-d' not in args:
            return ''
        dev = args[args.index('-d') + 1]
        cap_file = os.path.join(self._caps_dir, os.path.basename(dev))
        if not os.path.isfile(cap_file):
            return ''
        with open(cap_file, 'r', encoding='utf-8') as f:
            cap = f.read().strip()
        return textwrap.dedent(f'''\
            Card type:        Fake
            Device Caps:      0x{int(cap, 16):08x}
        ''')


def _build_fixture(tmp: str) -> _FakeV4l2Ctl:
    """Build a minimal sysfs fixture with two video nodes (one capture, one
    metadata), one ALSA card on the same USB device, one BT adapter, and one
    LIRC device.

    Real Linux sysfs uses layered symlinks: ``/sys/class/video4linux/video0``
    is itself a symlink to ``../../devices/.../video4linux/video0`` (the
    kernel bridges the class/ and devices/ views). The `device` symlink
    under that resolves to the UVC interface, then the USB device node
    (which has ``idVendor``). We mirror that layout here so ``os.path.realpath``
    lands on the same place it would on a real host.

    Both endpoints of the layered symlinks must exist as real directories for
    ``os.path.realpath`` to follow them, so we create the device-side stub
    directories up front.
    """
    def _ensure_dir(path: str) -> None:
        if not os.path.lexists(path):
            os.makedirs(path, exist_ok=True)

    def _link_class_to_devices(class_subpath: str, device_subpath: str) -> None:
        # Mirror how the kernel wires class/X/Y -> ../../devices/.../X/Y
        # The target directory must exist for realpath to follow it.
        target = f'{tmp}/devices/{device_subpath}'
        _ensure_dir(target)
        _symlink(
            f'{tmp}/class/{class_subpath}',
            f'../../devices/{device_subpath}',
        )

    # USB device 1 (3-1) hosts a UVC node and a UAC node.
    _write(f'{tmp}/devices/pci0000:00/usb3/3-1/idVendor', '345f')
    _write(f'{tmp}/devices/pci0000:00/usb3/3-1/idProduct', '2130')
    _link_class_to_devices(
        'video4linux/video0',
        'pci0000:00/usb3/3-1/3-1:1.0/video4linux/video0',
    )
    _symlink(
        f'{tmp}/class/video4linux/video0/device',
        '../../3-1:1.0',
    )
    _link_class_to_devices(
        'video4linux/video1',
        'pci0000:00/usb3/3-1/3-1:1.1/video4linux/video1',
    )
    _symlink(
        f'{tmp}/class/video4linux/video1/device',
        '../../3-1:1.1',
    )
    _link_class_to_devices(
        'sound/card1',
        'pci0000:00/usb3/3-1/3-1:1.2/sound/card1',
    )
    _symlink(
        f'{tmp}/class/sound/card1/device',
        '../../3-1:1.2',
    )
    # Mark /dev/video0 as capture (bit 0 set), /dev/video1 as metadata-only.
    _write(f'{tmp}/__caps__/video0', '0x1')          # VIDEO_CAPTURE only
    _write(f'{tmp}/__caps__/video1', '0x0')          # no capture bit

    # USB device 2 (3-2) is a UVC video node with NO companion ALSA card.
    _write(f'{tmp}/devices/pci0000:00/usb3/3-2/idVendor', '534d')
    _write(f'{tmp}/devices/pci0000:00/usb3/3-2/idProduct', '2109')
    _link_class_to_devices(
        'video4linux/video2',
        'pci0000:00/usb3/3-2/3-2:1.0/video4linux/video2',
    )
    _symlink(
        f'{tmp}/class/video4linux/video2/device',
        '../../3-2:1.0',
    )
    _write(f'{tmp}/__caps__/video2', '0x1')

    # Bluetooth adapter (3-10).
    _write(f'{tmp}/devices/pci0000:00/usb3/3-10/idVendor', '0e8d')
    _write(f'{tmp}/devices/pci0000:00/usb3/3-10/idProduct', 'c616')
    _link_class_to_devices(
        'bluetooth/hci0',
        'pci0000:00/usb3/3-10/3-10:1.0/bluetooth/hci0',
    )
    _symlink(
        f'{tmp}/class/bluetooth/hci0/device',
        '../../3-10:1.0',
    )
    _write(f'{tmp}/class/bluetooth/hci0/address', '2C:1B:3A:BC:B6:F2')

    # IR receiver (3-12).
    _write(f'{tmp}/devices/pci0000:00/usb3/3-12/idVendor', '04d8')
    _write(f'{tmp}/devices/pci0000:00/usb3/3-12/idProduct', 'fd08')
    _link_class_to_devices(
        'lirc/lirc0',
        'pci0000:00/usb3/3-12/3-12:1.0/lirc/lirc0',
    )
    _symlink(
        f'{tmp}/class/lirc/lirc0/device',
        '../../3-12:1.0',
    )
    return _FakeV4l2Ctl(tmp)


class GrabberDetectTests(unittest.TestCase):

    def test_pairing_and_filtering(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fake_v4l2 = _build_fixture(tmp)
            # Inject our fake v4l2-ctl by monkey-patching subprocess.run inside
            # the module so it doesn't need to be on PATH.
            original_run = grabber_detect.subprocess.run
            def fake_run(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == 'v4l2-ctl':
                    return types.SimpleNamespace(
                        returncode=0,
                        stdout=fake_v4l2(*cmd[1:]),
                        stderr='',
                    )
                return original_run(cmd, *args, **kwargs)
            with mock.patch.object(grabber_detect.subprocess, 'run', side_effect=fake_run):
                report = grabber_detect.detect_grabbers(sysfs_root=tmp, v4l2_ctl='v4l2-ctl')
            self.assertEqual(len(report['grabbers']), 2,
                             'should pair video0+card1 and keep video2 (no ALSA)')

            # The 3-1 device should have its video and audio paired.
            by_video = {g['video']: g for g in report['grabbers']}
            self.assertEqual(by_video['/dev/video0']['audio'], 'plughw:1,0')
            self.assertTrue(by_video['/dev/video0']['has_audio'])
            self.assertEqual(by_video['/dev/video0']['usb_id'], '345f:2130')
            self.assertEqual(by_video['/dev/video0']['usb_path'], '3-1')

            # /dev/video1 must be filtered out (no V4L2_CAP_VIDEO_CAPTURE bit).
            self.assertNotIn('/dev/video1', by_video)

            # The 3-2 device has video but no audio on the same USB parent.
            self.assertEqual(by_video['/dev/video2']['audio'], '(none)')
            self.assertFalse(by_video['/dev/video2']['has_audio'])
            self.assertEqual(by_video['/dev/video2']['usb_id'], '534d:2109')
            self.assertEqual(by_video['/dev/video2']['usb_path'], '3-2')

            # Bluetooth entry from the same fixture.
            self.assertEqual(len(report['bluetooth']), 1)
            self.assertEqual(report['bluetooth'][0]['name'], 'hci0')
            self.assertEqual(report['bluetooth'][0]['mac'], '2C:1B:3A:BC:B6:F2')
            self.assertEqual(report['bluetooth'][0]['usb_id'], '0e8d:c616')
            self.assertEqual(report['bluetooth'][0]['usb_path'], '3-10')

            # IR entry.
            self.assertEqual(len(report['infrared']), 1)
            self.assertEqual(report['infrared'][0]['name'], '/dev/lirc0')
            self.assertEqual(report['infrared'][0]['usb_id'], '04d8:fd08')
            self.assertEqual(report['infrared'][0]['usb_path'], '3-12')

    def test_no_sysfs_returns_empty(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # No class/video4linux, class/sound, etc. — fixture has nothing.
            report = grabber_detect.detect_grabbers(sysfs_root=tmp)
            self.assertEqual(report, {'grabbers': [], 'bluetooth': [], 'infrared': []})

    def test_permission_denied_on_v4l2_skips_node(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _build_fixture(tmp)
            # No v4l2-ctl on PATH: subprocess raises FileNotFoundError, which
            # _is_capture_node swallows → all video nodes filtered out.
            report = grabber_detect.detect_grabbers(
                sysfs_root=tmp, v4l2_ctl='nonexistent-binary-xyz',
            )
            self.assertEqual(report['grabbers'], [])


if __name__ == '__main__':
    unittest.main()
