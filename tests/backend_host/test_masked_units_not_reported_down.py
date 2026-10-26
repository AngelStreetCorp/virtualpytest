"""A systemd unit that was deliberately masked must NOT be reported as 'stopped'.

Regression: a headless vpt host (no display, no video devices) has vpt-stream,
vpt-vnc, vpt-websockify and vpt-monitor-audio masked on purpose. systemd answers
`systemctl show -p LoadState` with `masked` and `systemctl is-active` with
`inactive`, so the pre-BUG-xxxx mapping reported 'stopped'. vpt-stream is a
critical service, so the Dashboard card rendered a red "Stream down" and the
fleet counted a host as degraded — for a service nobody asked to run.

The fix treats LoadState=masked the same as not-found, so the row lands in the
Dashboard's collapsed "Not installed" list instead of raising an incident.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend_host.src.lib.utils.system_info_utils import _check_linux_service  # noqa: E402


class FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess with .returncode / .stdout."""

    def __init__(self, stdout: str = '', returncode: int = 0):
        self.stdout = stdout
        self.stderr = ''
        self.returncode = returncode


def fake_systemctl(load_state: str, is_active: str):
    """systemctl stub: `show LoadState` returns load_state, `is-active` returns is_active.

    The real call is ['systemctl', 'show', '--property=LoadState', '--value', name],
    so match on the '--property=LoadState' argv token, not a bare 'LoadState'.
    """

    def run(cmd, *args, **kwargs):
        if 'show' in cmd and '--property=LoadState' in cmd:
            return FakeCompleted(load_state + '\n')
        if 'is-active' in cmd:
            # Real systemctl exits 3 for a masked unit while printing "inactive".
            return FakeCompleted(is_active + '\n', 3 if is_active != 'active' else 0)
        return FakeCompleted('', 0)

    return run


@pytest.mark.parametrize(
    'unit',
    ['vpt-stream', 'vpt-vnc', 'vpt-websockify', 'vpt-monitor-audio'],
)
def test_masked_unit_is_not_installed_not_stopped(unit):
    with patch.object(subprocess, 'run', fake_systemctl('masked', 'inactive')):
        result = _check_linux_service([unit])

    assert result['status'] == 'not_installed', (
        f'{unit} is masked on purpose; it must not be reported as {result["status"]!r}'
    )
    assert result['status'] != 'stopped'


def test_masked_unit_alongside_a_healthy_one_still_reports_the_healthy_one():
    """A masked candidate must not mask a healthy one in the same list."""
    states = {'vpt-host': ('loaded', 'active'), 'vpt-stream': ('masked', 'inactive')}

    def run(cmd, *args, **kwargs):
        name = cmd[-1]
        load_state, is_active = states.get(name, ('not-found', 'inactive'))
        if 'show' in cmd and '--property=LoadState' in cmd:
            return FakeCompleted(load_state + '\n')
        if 'is-active' in cmd:
            return FakeCompleted(is_active + '\n', 0 if is_active == 'active' else 3)
        return FakeCompleted('', 0)

    with patch.object(subprocess, 'run', run):
        result = _check_linux_service(['vpt-stream', 'vpt-host'])

    assert result['status'] == 'active'
    assert result['resolved_name'] == 'vpt-host'


@pytest.mark.parametrize(
    'load_state,is_active,expected',
    [
        ('loaded', 'active', 'active'),      # healthy: unchanged
        ('loaded', 'inactive', 'stopped'),   # installed but stopped: still a real 'stopped'
        ('loaded', 'failed', 'error'),       # crashed: still a real 'error'
        ('masked', 'inactive', 'not_installed'),  # deliberately off
        ('not-found', '', 'not_installed'),  # never installed
    ],
)
def test_status_mapping_table(load_state, is_active, expected):
    with patch.object(subprocess, 'run', fake_systemctl(load_state, is_active)):
        result = _check_linux_service(['vpt-stream'])
    assert result['status'] == expected


def test_all_candidates_masked_collapses_to_not_installed():
    with patch.object(subprocess, 'run', fake_systemctl('masked', 'inactive')):
        result = _check_linux_service(['vpt-vnc', 'vpt-websockify'])
    assert result['status'] == 'not_installed'
    assert result['runtime'] == 'service'