"""ensure_host_prereqs.sh: the sudoers rule for restarting vpt-* units and the vpt-timeline unit, on a host (TASK-90 follow-up). Temp dirs, no root."""
import os
import stat
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'setup', 'proxmox', 'node', 'ensure_host_prereqs.sh')
TEMPLATE = os.path.join(ROOT, 'backend_host', 'config', 'services', 'linux', 'timeline.service')


@pytest.fixture
def box(tmp_path):
    proj = tmp_path / 'proj'
    (proj / 'backend_host' / 'config' / 'services' / 'linux').mkdir(parents=True)
    (proj / 'backend_host' / 'config' / 'services' / 'linux' / 'timeline.service').write_text(open(TEMPLATE).read())
    (proj / 'backend_host' / 'src').mkdir(parents=True)
    systemd, sudoers, bindir = tmp_path / 'systemd', tmp_path / 'sudoers.d', tmp_path / 'bin'
    for d in (systemd, sudoers, bindir):
        d.mkdir()
    for name, body in (('systemctl', f'echo "$@" >> {tmp_path}/systemctl.log\n'), ('visudo_ok', 'exit 0\n'), ('visudo_bad', 'exit 1\n')):
        p = bindir / name
        p.write_text('#!/bin/bash\n' + body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    def run(*args, visudo='visudo_ok', env=None):
        e = {**os.environ, 'VISUDO': str(bindir / visudo), 'SYSTEMCTL': str(bindir / 'systemctl'), **(env or {})}
        return subprocess.run(['bash', SCRIPT, '--project-root', str(proj), '--systemd-dir', str(systemd), '--sudoers-dir', str(sudoers), *args],
                              capture_output=True, text=True, env=e)
    run.proj, run.systemd, run.sudoers, run.log = proj, systemd, sudoers, tmp_path / 'systemctl.log'
    return run


def test_adds_the_rule_as_its_own_file_with_exactly_the_installers_three_lines(box):
    r = box()
    assert r.returncode == 0, r.stderr
    f = box.sudoers / 'vpt-restart'
    text = f.read_text()
    for verb in ('start', 'stop', 'restart'):
        assert f'vpt_user ALL=(root) NOPASSWD: /bin/systemctl {verb} vpt-*, /usr/bin/systemctl {verb} vpt-*' in text
    assert stat.S_IMODE(f.stat().st_mode) == 0o440
    assert [p.name for p in box.sudoers.iterdir()] == ['vpt-restart']          # no temp file left


def test_a_rule_that_does_not_pass_visudo_is_not_installed(box):
    r = box(visudo='visudo_bad')
    assert r.returncode == 1
    assert list(box.sudoers.iterdir()) == []


def test_an_existing_grant_in_any_file_is_left_alone(box):
    (box.sudoers / 'virtualpytest').write_text('vpt_user ALL=(root) NOPASSWD: /bin/systemctl restart vpt-*, /usr/bin/systemctl restart vpt-*\n')
    r = box()
    assert r.returncode == 0 and 'already lets' in r.stdout
    assert [p.name for p in box.sudoers.iterdir()] == ['virtualpytest']


def test_the_old_file_without_the_rule_is_not_edited(box):
    old = box.sudoers / 'virtualpytest'
    old.write_text('vpt_user ALL=(root) NOPASSWD: /bin/systemctl restart stream*\n')
    box()
    assert old.read_text() == 'vpt_user ALL=(root) NOPASSWD: /bin/systemctl restart stream*\n'
    assert (box.sudoers / 'vpt-restart').exists()


def test_skip_switch_leaves_sudoers_alone(box):
    box(env={'VPT_SKIP_SUDOERS': '1'})
    assert list(box.sudoers.iterdir()) == []


def test_the_timeline_unit_is_installed_rendered_and_never_enabled(box):
    r = box()
    unit = (box.systemd / 'vpt-timeline.service').read_text()
    assert str(box.proj) in unit and '%PROJECT_ROOT%' not in unit
    calls = box.log.read_text().split('\n')
    assert 'daemon-reload' in calls and not any('enable' in c or 'start' in c for c in calls)
    assert 'not enabled' in r.stdout


def test_a_second_run_changes_nothing(box):
    box()
    before = {p.name: p.read_text() for p in list(box.sudoers.iterdir()) + list(box.systemd.iterdir())}
    box.log.unlink()
    r = box()
    assert r.returncode == 0 and 'up to date' in r.stdout
    assert before == {p.name: p.read_text() for p in list(box.sudoers.iterdir()) + list(box.systemd.iterdir())}
    assert not box.log.exists()                                                   # no daemon-reload for nothing


def test_a_lite_host_gets_no_timeline_unit(box):
    (box.proj / 'backend_host' / 'src' / '.env').write_text('HOST_PROFILE=lite\n')
    box()
    assert not (box.systemd / 'vpt-timeline.service').exists()


def test_dry_run_touches_nothing(box):
    r = box('--dry-run')
    assert r.returncode == 0 and 'would' in r.stdout
    assert list(box.sudoers.iterdir()) == [] and list(box.systemd.iterdir()) == []
