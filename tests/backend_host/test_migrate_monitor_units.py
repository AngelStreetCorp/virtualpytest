"""setup/proxmox/node/migrate_monitor_units.sh against a fake systemd (TASK-90 goal 1, review BLOCK 4 + WARN)."""
import os
import stat
import subprocess
import textwrap

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'setup', 'proxmox', 'node', 'migrate_monitor_units.sh')
OLD_NEW = {'vpt-monitor': 'vpt-monitor-img', 'vpt-transcript': 'vpt-monitor-audio', 'vpt-subtitle': 'vpt-monitor-subtitle'}


@pytest.fixture
def box(tmp_path):
    systemd = tmp_path / 'systemd'
    state = tmp_path / 'state'
    proj = tmp_path / 'proj' / 'setup' / 'local' / 'linux' / 'backend_host'
    for d in (systemd, state, proj, tmp_path / 'bin'):
        d.mkdir(parents=True)
    log = tmp_path / 'systemctl.log'
    # fake systemctl: state in files; enable/start of a unit whose file does not exist fails
    (tmp_path / 'bin' / 'systemctl').write_text(textwrap.dedent(f"""\
        #!/bin/bash
        echo "$@" >> {log}
        cmd=$1; shift
        unit=${{@: -1}}; unit=${{unit%.service}}
        case $cmd in
          is-enabled) cat {state}/$unit.enabled 2>/dev/null || exit 1 ;;
          is-active)  cat {state}/$unit.active 2>/dev/null || {{ echo inactive; exit 3; }} ;;
          disable)    rm -f {state}/$unit.enabled; [ "$1" = "--now" ] && rm -f {state}/$unit.active; true ;;
          enable)     [ -f {systemd}/$unit.service ] || exit 1; echo enabled > {state}/$unit.enabled ;;
          start)      [ -f {systemd}/$unit.service ] || exit 1; echo active > {state}/$unit.active ;;
          *) true ;;
        esac
        """))
    # fake install_service.sh: "renders" the template into the systemd dir; set FAIL_RENDER=1 to break it
    (proj / 'install_service.sh').write_text(textwrap.dedent(f"""\
        #!/bin/bash
        [ -n "$FAIL_RENDER" ] && exit 1
        echo "[Unit]" > {systemd}/vpt-$1.service
        """))
    for p in (tmp_path / 'bin' / 'systemctl', proj / 'install_service.sh'):
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    class Box:
        pass
    b = Box()
    b.systemd, b.state, b.log, b.root, b.tmp = systemd, state, log, tmp_path / 'proj', tmp_path

    def install_old(unit, enabled='enabled', active='active', dropin=False):
        (systemd / f'{unit}.service').write_text('[Unit]\nold\n')
        if enabled:
            (state / f'{unit}.enabled').write_text(enabled)
        if active:
            (state / f'{unit}.active').write_text(active)
        if dropin:
            (systemd / f'{unit}.service.d').mkdir()
            (systemd / f'{unit}.service.d' / 'transcription.conf').write_text('[Service]\nEnvironment=ENABLE_TRANSCRIPTION=true\n')
    b.install_old = install_old

    def run(**env):
        e = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}", **env)
        return subprocess.run(['bash', SCRIPT, '--project-root', str(b.root), '--systemd-dir', str(systemd)],
                              capture_output=True, text=True, env=e)
    b.run = run
    return b


def test_migrates_state_and_dropin_and_keeps_a_backup(box):
    box.install_old('vpt-transcript', dropin=True)
    r = box.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (box.systemd / 'vpt-transcript.service').exists()
    assert (box.systemd / 'vpt-monitor-audio.service').exists()
    assert (box.systemd / 'vpt-transcript.service.bak-task90').read_text() == '[Unit]\nold\n'     # recoverable
    assert (box.systemd / 'vpt-monitor-audio.service.d' / 'transcription.conf').exists()          # drop-in followed
    assert (box.state / 'vpt-monitor-audio.enabled').exists() and (box.state / 'vpt-monitor-audio.active').exists()
    assert not (box.systemd / 'vpt-transcript.service.state-task90').exists()


def test_second_run_is_a_no_op(box):
    box.install_old('vpt-monitor')
    assert box.run().returncode == 0
    box.log.write_text('')
    r = box.run()
    assert r.returncode == 0 and 'nothing to do' in r.stdout
    assert 'enable' not in box.log.read_text() and 'start' not in box.log.read_text()


def test_a_disabled_unit_stays_disabled_and_stopped(box):
    box.install_old('vpt-subtitle', enabled='disabled', active='inactive')     # a lite host
    assert box.run().returncode == 0
    assert (box.systemd / 'vpt-monitor-subtitle.service').exists()
    assert not (box.state / 'vpt-monitor-subtitle.enabled').exists() and not (box.state / 'vpt-monitor-subtitle.active').exists()


def test_activating_counts_as_active(box):
    box.install_old('vpt-monitor', active='activating')
    assert box.run().returncode == 0
    assert (box.state / 'vpt-monitor-img.active').exists()


def test_a_render_failure_leaves_the_old_unit_untouched_and_a_rerun_works(box):
    box.install_old('vpt-monitor', dropin=True)
    r = box.run(FAIL_RENDER='1')
    assert r.returncode == 1 and 'render FAILED' in r.stdout
    assert (box.systemd / 'vpt-monitor.service').exists() and (box.systemd / 'vpt-monitor.service.d').exists()
    assert (box.state / 'vpt-monitor.active').exists()                         # still running, never stopped
    assert not (box.systemd / 'vpt-monitor-img.service').exists()
    assert box.run().returncode == 0                                          # not "nothing to do": it migrates now
    assert (box.systemd / 'vpt-monitor-img.service').exists()


def test_recovery_after_an_interrupted_run(box):
    (box.systemd / 'vpt-monitor.service.bak-task90').write_text('[Unit]\nold\n')
    (box.systemd / 'vpt-monitor.service.state-task90').write_text('enabled active\n')
    r = box.run()
    assert r.returncode == 0 and 'recovering' in r.stdout
    assert (box.systemd / 'vpt-monitor-img.service').exists()
    assert (box.state / 'vpt-monitor-img.enabled').exists() and (box.state / 'vpt-monitor-img.active').exists()


def test_enable_failure_is_reported(box):
    box.install_old('vpt-monitor')
    (box.tmp / 'bin' / 'systemctl').write_text((box.tmp / 'bin' / 'systemctl').read_text().replace(
        'enable)     [', 'enable)     exit 1; ['))
    r = box.run()
    assert r.returncode == 1 and 'enable FAILED' in r.stdout
