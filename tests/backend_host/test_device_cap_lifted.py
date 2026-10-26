"""TASK-95: a host takes more than 30 devices (DEVICE31, DEVICE45 ... are discovered, folders provisioned)."""
import os
import re
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPTS = [
    'backend_host/scripts/run_ffmpeg.sh',
    'backend_host/scripts/run_ffmpeg_macos.sh',
    'backend_host/scripts/setup_ramdisk_macos.sh',
    'backend_host/docker/scripts/generate_env.sh',
    'backend_host/docker/scripts/entrypoint.sh',
    'setup/local/shared/parse_devices.sh',
    'setup/local/linux/backend_host/setup_permissions.sh',
    'setup/local/linux/backend_host/setup_ram_hot_storage.sh',
    'setup/local/linux/backend_host/ensure_hot_mounts.sh',
]
LOOP = re.compile(r'^\s*for i in (\$\(seq 1 "\$\{MAX_DEVICES:-99\}"\)); do', re.M)


def test_no_script_keeps_the_30_device_loop():
    for rel in SCRIPTS:
        src = open(os.path.join(ROOT, rel)).read()
        assert '{1..30}' not in src, rel
        assert LOOP.search(src), rel
    assert subprocess.run(['bash', '-n', os.path.join(ROOT, SCRIPTS[0])]).returncode == 0


def test_the_loop_header_reaches_device31_and_device45():
    # run the exact loop header used by run_ffmpeg.sh against an env holding DEVICE31 and DEVICE45
    header = LOOP.search(open(os.path.join(ROOT, SCRIPTS[0])).read()).group(1)
    script = 'for i in %s; do v="DEVICE${i}_VIDEO"; [ -n "${!v}" ] && echo "$i"; done' % header
    env = {'PATH': os.environ['PATH'], 'DEVICE1_VIDEO': 'a', 'DEVICE31_VIDEO': 'b', 'DEVICE45_VIDEO': 'c'}
    out = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True).stdout.split()
    assert out == ['1', '31', '45']
    env['MAX_DEVICES'] = '40'
    out = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True).stdout.split()
    assert out == ['1', '31']


def test_controller_manager_discovers_beyond_30(monkeypatch):
    src = open(os.path.join(ROOT, 'backend_host/src/controllers/controller_manager.py')).read()
    assert 'range(1, 31)' not in src and 'MAX_DEVICES' in src
