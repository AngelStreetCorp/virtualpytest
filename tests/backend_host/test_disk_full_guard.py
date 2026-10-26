"""Disk-full guard in run_ffmpeg.sh (a full filesystem that a restart cannot fix).

A full filesystem fails the same invisible way the X11 auth fault did: ffmpeg's log
stays fresh, the process stays up and the service reports active, while every output
write fails with ENOSPC. On labox-backend the archiver that trims the 24 h capture
archive had been left stopped by an earlier deploy; the archive grew to 12 G, `/` hit
100 %, and every capture/segment/latest.jpg write failed — an empty heatmap behind a
"running" service. The watchdog then restart-looped ffmpeg, which wrote more.

These tests extract `disk_full_fault` and `disk_emergency_reclaim` out of run_ffmpeg.sh
and exercise their decision logic against a fake `df` and a real temp capture tree. The
invariant that matters: the guard must name the real cause, reclaim ONLY the disposable
tail, and never block a host whose disk it simply cannot measure.

Fakes only — no device, no ffmpeg, no network, no real disk pressure.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_FFMPEG = REPO_ROOT / 'backend_host' / 'scripts' / 'run_ffmpeg.sh'

HELPERS = ('disk_full_fault', 'disk_emergency_reclaim')


def _extract_helpers(dest: Path) -> str:
    """Copy the disk helpers verbatim out of run_ffmpeg.sh, plus DISK_FULL_PCT.

    Sourcing the whole script would boot the capture service, so each `name() {` … `}`
    block is sliced out by regex, together with the threshold variable they read.
    Reading them from the real file (rather than a copy in the test) is the point: the
    test fails if someone edits the shipped logic.
    """
    text = RUN_FFMPEG.read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)
    starts = []
    for i, line in enumerate(lines):
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\(\) \{', line)
        if m:
            starts.append((i, m.group(1)))
    starts.append((len(lines), None))

    found = set()
    chunks = []
    for (i, name), (end, _) in zip(starts, starts[1:]):
        if name in HELPERS:
            chunks.append(''.join(lines[i:end]))
            found.add(name)
    missing = set(HELPERS) - found
    assert not missing, f'helpers not found in run_ffmpeg.sh: {sorted(missing)}'

    threshold = re.search(r'^DISK_FULL_PCT=.*$', text, re.M)
    assert threshold, 'DISK_FULL_PCT is not defined in run_ffmpeg.sh'
    chunks.insert(0, threshold.group(0) + '\n')

    dest.write_text('\n'.join(chunks), encoding='utf-8')
    return str(dest)


def _fake_df(tmp_path: Path, used_pct: int) -> Path:
    """A `df` on PATH that reports a filesystem at `used_pct` percent used."""
    bindir = tmp_path / 'bin'
    bindir.mkdir(exist_ok=True)
    df = bindir / 'df'
    df.write_text(
        '#!/bin/bash\n'
        'echo "Filesystem 512-blocks Used Available Capacity Mounted on"\n'
        f'echo "/dev/fake 100 {used_pct} {100 - used_pct} {used_pct}% /"\n'
    )
    df.chmod(0o755)
    return bindir


def _run(snippet: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', '-c', snippet], env=env, capture_output=True, text=True)


@pytest.fixture()
def guard(tmp_path):
    """Sourced disk-guard helpers + a helper to run a snippet with them."""
    script = _extract_helpers(tmp_path / 'guard.sh')
    env = dict(os.environ)

    def run(snippet: str, bindir: Path = None, extra_env: dict = None):
        e = dict(env)
        if bindir:
            e['PATH'] = f'{bindir}:{e["PATH"]}'
        if extra_env:
            e.update(extra_env)
        return _run(f'source {script}\n{snippet}', e)

    return run


def _make_old(path: Path, minutes: int) -> None:
    """Backdate a file's mtime, portable across GNU and BSD touch."""
    seconds = int(time.time()) - minutes * 60
    os.utime(path, (seconds, seconds))


# --- disk_full_fault ---------------------------------------------------------

def test_healthy_disk_is_not_a_fault(guard, tmp_path):
    bindir = _fake_df(tmp_path, used_pct=40)
    r = guard('disk_full_fault /', bindir=bindir)
    assert r.returncode == 1, 'a healthy disk must never be reported as full'


def test_unknown_filesystem_is_not_a_fault(guard, tmp_path):
    """A disk we cannot measure must not block the host from capturing."""
    r = guard('disk_full_fault /nonexistent/definitely/not/here')
    assert r.returncode == 1


def test_disk_at_threshold_is_a_fault(guard, tmp_path):
    bindir = _fake_df(tmp_path, used_pct=99)
    r = guard('disk_full_fault /', bindir=bindir, extra_env={'DISK_FULL_PCT': '98'})
    assert r.returncode == 0, '99% used must be a fault at a 98% threshold'


def test_threshold_is_inclusive(guard, tmp_path):
    """99% used against a 100% threshold is still healthy: the comparison is >=."""
    bindir = _fake_df(tmp_path, used_pct=99)
    r = guard('disk_full_fault /', bindir=bindir, extra_env={'DISK_FULL_PCT': '100'})
    assert r.returncode == 1


def test_completely_full_disk_is_a_fault(guard, tmp_path):
    bindir = _fake_df(tmp_path, used_pct=100)
    r = guard('disk_full_fault /', bindir=bindir)
    assert r.returncode == 0


def test_df_failure_does_not_claim_a_fault(guard):
    """A `df` that is not on PATH at all must not be read as "full"."""
    r = guard('PATH=/nonexistent; disk_full_fault /')
    assert r.returncode == 1


# --- disk_emergency_reclaim --------------------------------------------------

def _capture_tree(tmp_path: Path) -> Path:
    cap = tmp_path / 'capture'
    for sub in ('hot/captures', 'hot/segments', 'hot/thumbnails', 'captures'):
        (cap / sub).mkdir(parents=True, exist_ok=True)
    return cap


def test_reclaim_removes_old_hot_tail(guard, tmp_path):
    cap = _capture_tree(tmp_path)
    old = cap / 'hot' / 'captures' / 'capture_000000001.jpg'
    old.write_bytes(b'x')
    _make_old(old, minutes=180)
    guard('disk_emergency_reclaim "$CAP" >/dev/null', extra_env={'CAP': str(cap)})
    assert not old.exists(), 'a hot capture older than an hour is disposable'


def test_reclaim_keeps_recent_hot_capture(guard, tmp_path):
    cap = _capture_tree(tmp_path)
    recent = cap / 'hot' / 'captures' / 'capture_000000002.jpg'
    recent.write_bytes(b'x')
    guard('disk_emergency_reclaim "$CAP" >/dev/null', extra_env={'CAP': str(cap)})
    assert recent.exists(), 'the live window must never be touched'


def test_reclaim_keeps_latest_jpg(guard, tmp_path):
    """latest.jpg is what the heatmap reads; losing it blanks the cell."""
    cap = _capture_tree(tmp_path)
    latest = cap / 'hot' / 'thumbnails' / 'latest.jpg'
    latest.write_bytes(b'x')
    _make_old(latest, minutes=600)
    guard('disk_emergency_reclaim "$CAP" >/dev/null', extra_env={'CAP': str(cap)})
    assert latest.exists(), 'latest.jpg must survive a reclaim'


def test_reclaim_removes_cold_past_retention(guard, tmp_path):
    cap = _capture_tree(tmp_path)
    old = cap / 'captures' / 'capture_000000003.jpg'
    old.write_bytes(b'x')
    _make_old(old, minutes=1800)  # 30h > the 24h retention window
    guard('disk_emergency_reclaim "$CAP" >/dev/null', extra_env={'CAP': str(cap)})
    assert not old.exists(), 'a cold capture past the 24h window is disposable'


def test_reclaim_keeps_cold_inside_retention(guard, tmp_path):
    cap = _capture_tree(tmp_path)
    keep = cap / 'captures' / 'capture_000000004.jpg'
    keep.write_bytes(b'x')
    _make_old(keep, minutes=600)  # 10h < 24h
    guard('disk_emergency_reclaim "$CAP" >/dev/null', extra_env={'CAP': str(cap)})
    assert keep.exists(), 'the 24h review buffer must survive a reclaim'


def test_reclaim_removes_old_thumbnails(guard, tmp_path):
    """The thumbnail sweep still frees space — only latest.jpg is exempt."""
    cap = _capture_tree(tmp_path)
    old = cap / 'hot' / 'thumbnails' / 'capture_000000009_thumbnail.jpg'
    old.write_bytes(b'x')
    _make_old(old, minutes=180)
    guard('disk_emergency_reclaim "$CAP" >/dev/null', extra_env={'CAP': str(cap)})
    assert not old.exists(), 'a stale per-capture thumbnail is disposable'


def test_reclaim_reports_a_count(guard, tmp_path):
    cap = _capture_tree(tmp_path)
    for i in range(3):
        f = cap / 'hot' / 'captures' / f'capture_{i:09d}.jpg'
        f.write_bytes(b'x')
        _make_old(f, minutes=180)
    r = guard('disk_emergency_reclaim "$CAP"', extra_env={'CAP': str(cap)})
    assert r.stdout.strip() == '3', f'expected 3, got {r.stdout.strip()!r}'


def test_reclaim_on_missing_dir_is_not_an_error(guard, tmp_path):
    r = guard('disk_emergency_reclaim "$CAP"', extra_env={'CAP': str(tmp_path / 'nope')})
    assert r.returncode == 0
    assert r.stdout.strip() == '0'


def test_reclaim_leaves_files_outside_the_capture_tree_alone(guard, tmp_path):
    """Only the capture tree is ours to trim."""
    outside = tmp_path / 'important.txt'
    outside.write_text('keep me')
    _make_old(outside, minutes=1800)
    cap = _capture_tree(tmp_path)
    guard('disk_emergency_reclaim "$CAP" >/dev/null', extra_env={'CAP': str(cap)})
    assert outside.exists()


def test_reclaim_is_idempotent(guard, tmp_path):
    cap = _capture_tree(tmp_path)
    f = cap / 'hot' / 'captures' / 'capture_000000005.jpg'
    f.write_bytes(b'x')
    _make_old(f, minutes=180)
    env = {'CAP': str(cap)}
    first = guard('disk_emergency_reclaim "$CAP"', extra_env=env)
    second = guard('disk_emergency_reclaim "$CAP"', extra_env=env)
    assert first.stdout.strip() == '1'
    assert second.stdout.strip() == '0', 'a second reclaim has nothing left to do'