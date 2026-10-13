"""
Unit tests for the container / physical-OS detection behind the dashboard
host card (BUG-0476).

A host named `vpt-windows` whose vpt-host runs as a Linux Docker container
reports `platform.system() == 'Linux'`, so the card used to claim a Windows PC
was a Linux box. `get_physical_platform()` separates the machine underneath
(`physical_platform`) from the runtime we actually execute on.

The detection reads a handful of small marker files and `platform.release()`,
so every case is driven by monkeypatching those rather than by touching the
real filesystem.
"""
import platform

import pytest

from backend_host.src.lib.utils.system_info_utils import (
    _detect_wsl,
    detect_container_runtime,
    get_physical_platform,
)


@pytest.fixture
def fake_linux(monkeypatch):
    """Pretend we are the vpt-windows host: Linux under the WSL2 kernel."""
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(
        platform, 'release', lambda: '5.15.167.4-microsoft-standard-WSL2'
    )
    monkeypatch.setattr('os.path.exists', lambda p: p == '/.dockerenv')
    monkeypatch.setattr(
        'backend_host.src.lib.utils.system_info_utils._read_text_file',
        lambda path, limit=8192: None,
    )


def test_bare_metal_linux_is_unchanged(monkeypatch):
    """
    The common case must not move: a Pi or a Debian VM on real hardware keeps
    reporting its own OS, with no container badge and no mismatch flag.
    """
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(platform, 'release', lambda: '6.1.0-rpi7-rpi-v8')
    monkeypatch.setattr('os.path.exists', lambda p: False)
    monkeypatch.setattr(
        'backend_host.src.lib.utils.system_info_utils._read_text_file',
        lambda path, limit=8192: None,
    )

    result = get_physical_platform()

    assert result['physical_platform'] == 'Linux'
    assert result['in_container'] is False
    assert result['container_runtime'] is None
    assert result['is_wsl'] is False
    assert result['os_mismatch'] is False


def test_docker_on_windows_reports_physical_windows(fake_linux):
    """The BUG-0476 case: Linux container on a Windows PC -> physical Windows."""
    result = get_physical_platform()

    assert result['physical_platform'] == 'Windows'
    assert result['in_container'] is True
    assert result['container_runtime'] == 'docker'
    assert result['is_wsl'] is True
    # This is the flag the card uses to explain the mismatch.
    assert result['os_mismatch'] is True


def test_docker_on_linux_is_not_a_mismatch(monkeypatch):
    """
    A container on a real Linux box is ordinary — same OS inside and out, so
    no "you are looking at a Windows machine" flag may be raised.
    """
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(platform, 'release', lambda: '6.1.0-18-amd64')
    monkeypatch.setattr('os.path.exists', lambda p: p == '/.dockerenv')
    monkeypatch.setattr(
        'backend_host.src.lib.utils.system_info_utils._read_text_file',
        lambda path, limit=8192: None,
    )

    result = get_physical_platform()

    assert result['physical_platform'] == 'Linux'
    assert result['in_container'] is True
    assert result['os_mismatch'] is False


def test_native_windows_host_is_not_a_container(monkeypatch):
    """The Windows-native install path (NSSM + Scheduled Task) stays plain."""
    monkeypatch.setattr(platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(platform, 'release', lambda: '10')
    monkeypatch.setattr('os.path.exists', lambda p: False)
    monkeypatch.setattr(
        'backend_host.src.lib.utils.system_info_utils._read_text_file',
        lambda path, limit=8192: None,
    )

    result = get_physical_platform()

    assert result['physical_platform'] == 'Windows'
    assert result['in_container'] is False
    assert result['os_mismatch'] is False


@pytest.mark.parametrize(
    'cgroup_body,expected',
    [
        ('0::/docker/8e20da5d30d8a1b2', 'docker'),
        ('11:pids:/kubepods/pod1234', 'kubernetes'),
        ('1:name=systemd:/docker/abc', 'docker'),
        ('0::/lxc/mycontainer', 'lxc'),
        ('0::/user.slice/user-1000.slice', None),
    ],
)
def test_detect_container_runtime_from_cgroup(monkeypatch, cgroup_body, expected):
    """
    /.dockerenv is not always present (cgroup v2 hosts, podman, k8s), so the
    cgroup markers are the fallback. A plain systemd cgroup must read None.
    """
    monkeypatch.setattr('os.path.exists', lambda p: False)
    monkeypatch.setattr(
        'backend_host.src.lib.utils.system_info_utils._read_text_file',
        lambda path, limit=8192: cgroup_body if path == '/proc/1/cgroup' else None,
    )

    assert detect_container_runtime() == expected


def test_wsl_detected_from_proc_version(monkeypatch):
    """
    Some WSL2 kernels only carry the marker in /proc/version, not in
    platform.release(), so both are probed.
    """
    monkeypatch.setattr(platform, 'release', lambda: '5.15.0-generic')
    monkeypatch.setattr(
        'backend_host.src.lib.utils.system_info_utils._read_text_file',
        lambda path, limit=8192: (
            'Linux version 5.15.0-microsoft-standard-WSL2' if path == '/proc/version' else None
        ),
    )

    assert _detect_wsl() is True


def test_physical_platform_never_guesses_windows_from_hostname(monkeypatch):
    """
    The name `vpt-windows` is an operator-set label and proves nothing. With
    no WSL evidence we must NOT claim Windows — that would invent an OS the
    host never reported.
    """
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(platform, 'release', lambda: '6.1.0-amd64')
    monkeypatch.setattr('os.path.exists', lambda p: p == '/.dockerenv')
    monkeypatch.setattr(
        'backend_host.src.lib.utils.system_info_utils._read_text_file',
        lambda path, limit=8192: None,
    )
    monkeypatch.setenv('HOST_NAME', 'vpt-windows')

    assert get_physical_platform()['physical_platform'] == 'Linux'