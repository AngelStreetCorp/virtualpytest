"""Tests for the LoadState=masked handling in the process-presence checks
(check_ffmpeg_status, check_monitor_status). The matching tests for the
service-state path (_check_linux_service) live in
tests/backend_host/test_masked_units_not_reported_down.py.

check_ffmpeg_status and check_monitor_status had a different blind spot:
they default to 'stopped' whenever the corresponding process is missing,
which let masked units slip through as red 'down' incidents even though
_load_state == 'masked' was already honoured by _check_linux_service. The
_linux_service_is_masked() helper added next to _check_linux_service makes
both code paths agree."""

import os
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'backend_host'))


import importlib.util
_spec = importlib.util.spec_from_file_location(
    'system_info_utils_for_masked_process_tests',
    os.path.join(PROJECT_ROOT, 'backend_host', 'src', 'lib', 'utils', 'system_info_utils.py'),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_linux_service_is_masked = _mod._linux_service_is_masked
check_ffmpeg_status = _mod.check_ffmpeg_status
check_monitor_status = _mod.check_monitor_status


# Tests for the helper itself ----------------------------------------------------

class LinuxServiceIsMaskedTests(unittest.TestCase):
    """_linux_service_is_masked() is a thin wrapper around `systemctl show`;
    pin the load-state string it accepts and the error fallback so a future
    refactor does not silently flip the convention back to 'stopped'."""

    def test_non_linux_short_circuits_to_false(self):
        with patch('platform.system', return_value='Darwin'):
            self.assertFalse(_linux_service_is_masked('vpt-stream'))

    def test_load_state_masked_returns_true(self):
        with patch('platform.system', return_value='Linux'), \
             patch('subprocess.run', return_value=_FakeResult(stdout='masked\n', returncode=0)):
            self.assertTrue(_linux_service_is_masked('vpt-stream'))

    def test_load_state_loaded_returns_false(self):
        with patch('platform.system', return_value='Linux'), \
             patch('subprocess.run', return_value=_FakeResult(stdout='loaded\n', returncode=0)):
            self.assertFalse(_linux_service_is_masked('vpt-stream'))

    def test_subprocess_error_returns_false(self):
        with patch('platform.system', return_value='Linux'), \
             patch('subprocess.run', side_effect=OSError('no systemctl')):
            self.assertFalse(_linux_service_is_masked('vpt-stream'))


class _FakeResult:
    def __init__(self, stdout='', returncode=0):
        self.stdout = stdout
        self.returncode = returncode


# Tests for the integration in check_ffmpeg_status / check_monitor_status -----

class CheckFfmpegStatusMaskedTests(unittest.TestCase):
    """When vpt-stream is masked and no ffmpeg process is running, the dashboard
    report must be 'not_installed' (NOT 'stopped'), so the UI files it under
    "Not installed" rather than raising a red 'down' incident."""

    def test_masked_vpt_stream_reports_not_installed(self):
        with patch.object(_mod, '_linux_service_is_masked', return_value=True), \
             patch.object(_mod, 'psutil') as psutil:
            psutil.process_iter.return_value = []  # zero ffmpeg processes
            psutil.disk_io_counters.return_value = None
            result = check_ffmpeg_status()
        self.assertEqual(result['status'], 'not_installed')

    def test_unmasked_vpt_stream_idle_reports_stopped(self):
        """An idle but installable stream is the common case: nothing is wrong,
        so reporting 'stopped' (and only that) is correct. Pin the regression."""
        with patch.object(_mod, '_linux_service_is_masked', return_value=False), \
             patch.object(_mod, 'psutil') as psutil:
            psutil.process_iter.return_value = []  # zero ffmpeg processes
            psutil.disk_io_counters.return_value = None
            result = check_ffmpeg_status()
        self.assertEqual(result['status'], 'stopped')


class CheckMonitorStatusMaskedTests(unittest.TestCase):
    """Same shape for vpt-monitor-img."""

    def test_masked_vpt_monitor_img_reports_not_installed(self):
        with patch.object(_mod, '_linux_service_is_masked', return_value=True), \
             patch.object(_mod, 'psutil') as psutil:
            psutil.process_iter.return_value = []
            psutil.disk_io_counters.return_value = None
            result = check_monitor_status()
        self.assertEqual(result['status'], 'not_installed')

    def test_unmasked_vpt_monitor_img_idle_reports_stopped(self):
        with patch.object(_mod, '_linux_service_is_masked', return_value=False), \
             patch.object(_mod, 'psutil') as psutil:
            psutil.process_iter.return_value = []
            psutil.disk_io_counters.return_value = None
            result = check_monitor_status()
        self.assertEqual(result['status'], 'stopped')


if __name__ == '__main__':
    unittest.main()
