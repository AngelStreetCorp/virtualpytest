"""X11 auth self-repair in run_ffmpeg.sh (dashboard auto-fix for a dead x11grab device).

The dashboard's auto-fix button only knows `systemctl restart vpt-stream`. For a host
device whose x11grab died on "Authorization required, but no authorization protocol
specified" that restart cannot help: ffmpeg dies again on the same broken cookie and the
staleness watchdog retries every 60s forever, so the host card reads healthy while nothing
is captured (BUG-0464).

These tests extract the three helpers (setup_x11_auth / x11_auth_fault / repair_x11_auth)
out of run_ffmpeg.sh and exercise their DECISION LOGIC against fakes for xdpyinfo, xhost,
ffmpeg, pgrep and stat. No X server, no display, no real cookie.

Fakes only — no device, no X server, no network, no real ffmpeg.
"""

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_FFMPEG = REPO_ROOT / 'backend_host' / 'scripts' / 'run_ffmpeg.sh'

HELPERS = ('setup_x11_auth', 'x11_auth_fault', 'repair_x11_auth')

# The exact stderr ffmpeg/Xlib produce on a display whose cookie the client cannot match.
AUTH_LOG = (
    'Authorization required, but no authorization protocol specified\n'
    '\n'
    '[x11grab @ 0x5602dcd378c0] Cannot open display :1, error 1.\n'
    '[in#0 @ 0x5602dcd37780] Error opening input: Input/output error\n'
    'Error opening input file :1.\n'
)
HEALTHY_LOG = 'frame=  100 fps=0.0 q=-1.0 size=N/A time=00:01:40.00 bitrate=N/A speed=1.0x\n'


def _extract_helpers(dest: Path) -> str:
    """Copy the three helpers verbatim out of run_ffmpeg.sh.

    Sourcing the whole script would boot the capture service, so the functions are sliced
    out by their `name() {` … `}` block. Reading them from the real file (rather than a
    copy kept in the test) is the point: the test fails if someone edits the logic.
    """
    lines = RUN_FFMPEG.read_text(encoding='utf-8').splitlines(keepends=True)
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
    assert found == set(HELPERS), f'missing helpers in run_ffmpeg.sh: {sorted(set(HELPERS) - found)}'
    dest.write_text(''.join(chunks), encoding='utf-8')
    return str(dest)


@pytest.fixture
def x11(tmp_path):
    """A fake X world: ./bin stubs + the extracted helpers, and a `run()` to drive them."""
    helpers = _extract_helpers(tmp_path / 'helpers.sh')

    bindir = tmp_path / 'bin'
    bindir.mkdir()
    trace = tmp_path / 'trace.log'

    # Fakes read their knobs from the environment at RUN TIME so one stub file can serve
    # every scenario. A `.granted` marker file models what a real `xhost +local:` changes:
    # the X SERVER's state, which a later, separate process observes.
    (bindir / 'xdpyinfo').write_text(
        '#!/usr/bin/env bash\n'
        f'echo "xdpyinfo $*" >> "$TRACE"\n'
        'if [ "${FAKE_XDPI_OK:-0}" = 1 ] || [ -f "$TRACE.granted" ]; then\n'
        '  echo "dimensions: 1280x720"; exit 0\n'
        'fi\n'
        'echo "Authorization required, but no authorization protocol specified" >&2\n'
        'exit 1\n'
    )
    (bindir / 'xhost').write_text(
        '#!/usr/bin/env bash\n'
        f'echo "xhost $*" >> "$TRACE"\n'
        'if [ "${FAKE_XHOST_GRANTS:-0}" = 1 ] && [ ! -f "$TRACE.granted" ]; then\n'
        '  : > "$TRACE.granted"\n'
        '  exit 0\n'
        'fi\n'
        'exit 1\n'
    )
    # The capture output is the LAST argv entry (`-frames:v 1 <file>`).
    (bindir / 'ffmpeg').write_text(
        '#!/usr/bin/env bash\n'
        f'echo "ffmpeg $*" >> "$TRACE"\n'
        'out=""; for a in "$@"; do out="$a"; done\n'
        'if [ "${FAKE_GRAB_OK:-0}" = 1 ] && [ -n "$out" ]; then printf JPEGDATA > "$out"; exit 0; fi\n'
        'echo "Authorization required, but no authorization protocol specified" >&2\n'
        'exit 1\n'
    )
    (bindir / 'pgrep').write_text('#!/usr/bin/env bash\nexit 1\n')
    # run_ffmpeg.sh uses GNU `stat -c %Y`, which macOS lacks; stub it so the staleness
    # guard inside x11_auth_fault is testable on a dev machine.
    (bindir / 'stat').write_text(
        '#!/usr/bin/env bash\n'
        '[ "$1" = "-c" ] && [ "$2" = "%Y" ] || exit 1\n'
        'echo "${FAKE_LOG_MTIME:-0}"\n'
    )
    for f in bindir.iterdir():
        f.chmod(0o755)

    class World:
        trace_path = trace
        bin = bindir
        granted = tmp_path / 'trace.log.granted'
        xdpi_ok = False
        xhost_grants = False
        grab_ok = False
        log_mtime = 0

        @classmethod
        def reset(cls):
            cls.xdpi_ok = cls.xhost_grants = cls.grab_ok = False
            cls.log_mtime = 0
            trace.write_text('')
            if cls.granted.exists():
                cls.granted.unlink()

        @classmethod
        def run(cls, script: str) -> str:
            env = {
                'PATH': f'{bindir}{os.pathsep}{os.environ.get("PATH", "")}',
                'TRACE': str(trace),
                'FFMPEG_BIN': str(bindir / 'ffmpeg'),
                'FAKE_XDPI_OK': '1' if cls.xdpi_ok else '0',
                'FAKE_XHOST_GRANTS': '1' if cls.xhost_grants else '0',
                'FAKE_GRAB_OK': '1' if cls.grab_ok else '0',
                'FAKE_LOG_MTIME': str(cls.log_mtime),
            }
            proc = subprocess.run(
                ['bash', '-c', f'source {helpers}; {script}'],
                capture_output=True, text=True, env=env, timeout=30,
            )
            return proc.stdout + proc.stderr

        @classmethod
        def calls(cls) -> str:
            return trace.read_text()

    World.reset()
    yield World
    World.reset()


# ------------------------------------------------------------------ repair_x11_auth

def test_a_healthy_display_is_left_completely_alone(x11):
    """The common case must be a no-op: no grant issued, no probe run, no repair claimed.
    Anything else would mean the watchdog mutates every healthy host every 30s."""
    x11.xdpi_ok = True
    out = x11.run('repair_x11_auth :1; echo "rc=$?"')
    assert 'rc=0' in out
    assert 'xhost' not in x11.calls()
    assert 'ffmpeg' not in x11.calls()
    assert 'repaired' not in out


def test_a_broken_display_is_repaired_by_the_xhost_grant(x11):
    x11.xhost_grants = True
    out = x11.run('repair_x11_auth :1; echo "rc=$?"')
    assert 'repaired on :1 (step: grant)' in out
    assert 'xhost -display :1 +local:' in x11.calls()


def test_repair_is_verified_with_a_real_grab_when_xdpyinfo_is_not_enough(x11):
    """xdpyinfo can succeed where a fresh x11grab open is still refused, so the last word
    belongs to a one-frame grab that must actually land a file on disk."""
    x11.grab_ok = True
    out = x11.run('repair_x11_auth :1; echo "rc=$?"')
    assert 'frame probe OK' in out
    assert 'ffmpeg ' in x11.calls()
    assert '-i :1' in x11.calls()


def test_an_unrepairable_display_falls_back_instead_of_claiming_success(x11):
    out = x11.run('repair_x11_auth :1; echo "rc=$?"')
    assert 'rc=1' in out
    assert 'falling back to the normal restart policy' in out
    assert 'auth repaired on :1' not in out


def test_an_unrepairable_display_leaves_no_probe_file_behind(x11, tmp_path):
    x11.run('repair_x11_auth :1')
    # A mktemp DIRECTORY is used on purpose: BSD mktemp only substitutes TRAILING X's, so
    # `mktemp ...XXXXXX.jpg` returns the template verbatim on macOS and every run would
    # collide on one predictable path.
    assert list(Path(tempfile.gettempdir()).glob('vpt_x11_probe_*')) == []


def test_an_empty_display_is_refused_without_touching_anything(x11):
    out = x11.run('repair_x11_auth ""; echo "rc=$?"')
    assert 'rc=1' in out
    assert x11.calls() == ''


def test_setup_x11_auth_prefers_the_x_servers_own_auth_path(x11, tmp_path):
    """BUG-0464's root cause: vpt-stream runs with a different HOME than vpt-vnc. Asking
    the live server for its -auth argument is what keeps this correct."""
    cookie = tmp_path / '.Xauthority'
    cookie.write_text('cookie')
    (x11.bin / 'pgrep').write_text(
        '#!/usr/bin/env bash\n'
        f'echo "111 /usr/bin/Xtigervnc :1 -auth {cookie}"\n'
    )
    (x11.bin / 'pgrep').chmod(0o755)
    out = x11.run('setup_x11_auth :1')
    assert f'XAUTHORITY={cookie}' in out


# ------------------------------------------------------------------ x11_auth_fault

def _fault_log(x11, body: str, mtime: int) -> Path:
    """Write a fake per-device ffmpeg log and return its ABSOLUTE path.

    Absolute because the helper runs in a subprocess whose cwd is the repo root, not
    tmp_path — a relative './t.log' would miss the file and silently read nothing.
    """
    log = x11.bin.parent / 't.log'
    log.write_text(body)
    x11.log_mtime = mtime
    return log


def test_the_reported_failure_is_recognised(x11):
    """The exact log from the report: `cat /tmp/ffmpeg_output_host.log` on a host whose
    display :1 has no matching cookie."""
    log = _fault_log(x11, AUTH_LOG, int(time.time()) - 120)
    assert 'rc=0' in x11.run(f'x11_auth_fault {log}; echo "rc=$?"')


def test_a_fresh_log_is_not_repaired_again(x11):
    """A display that works now may have logged the fault minutes ago. Only a QUIET log is
    a live fault, otherwise the watchdog would re-repair a healthy capture forever."""
    log = _fault_log(x11, AUTH_LOG, int(time.time()))
    assert 'rc=1' in x11.run(f'x11_auth_fault {log}; echo "rc=$?"')


def test_a_stalled_but_healthy_log_is_not_a_fault(x11):
    """No auth line: this is the ordinary output-stall case, which the existing
    restart/dormant policy already handles. The repair must not hijack it."""
    log = _fault_log(x11, HEALTHY_LOG, int(time.time()) - 120)
    assert 'rc=1' in x11.run(f'x11_auth_fault {log}; echo "rc=$?"')


def test_a_missing_log_is_not_a_fault(x11):
    assert 'rc=1' in x11.run('x11_auth_fault ./does_not_exist.log; echo "rc=$?"')


def test_an_old_fault_under_fresh_progress_is_not_re_flagged(x11):
    """60 progress lines bury the fault outside the tail window: history, not current state."""
    log = _fault_log(x11, AUTH_LOG + 'frame=1 fps=1.0\n' * 60, int(time.time()) - 120)
    assert 'rc=1' in x11.run(f'x11_auth_fault {log}; echo "rc=$?"')


def test_a_fault_inside_the_tail_window_is_still_flagged(x11):
    log = _fault_log(x11, AUTH_LOG + 'frame=1 fps=1.0\n' * 10, int(time.time()) - 120)
    assert 'rc=0' in x11.run(f'x11_auth_fault {log}; echo "rc=$?"')


# -------------------------------------------------------------- wiring in run_ffmpeg.sh

def test_run_ffmpeg_shell_syntax_is_valid():
    assert subprocess.run(['bash', '-n', str(RUN_FFMPEG)]).returncode == 0


def test_the_watchdog_repairs_before_it_restarts():
    """restart_unhealthy_grabber must call repair_x11_auth BEFORE killing/restarting, and
    only for an x11grab source whose log carries the fault signature."""
    text = RUN_FFMPEG.read_text(encoding='utf-8')
    body = text[text.index('restart_unhealthy_grabber() {'):text.index('check_grabber_health() {')]
    repair = body.index('repair_x11_auth')
    assert 'x11_auth_fault' in body[:repair], 'repair must be gated on the fault signature'
    assert 'detect_source_type' in body[:repair], 'repair must be gated on an x11grab source'
    assert body.index('kill_all_ffmpeg_for_device') > repair, 'repair must run before the restart'


def test_every_x11grab_start_self_heals():
    """The x11grab branch verifies the display and repairs it, so EVERY entry point heals:
    the dashboard auto-fix, a systemd restart, the watchdog, a source switch."""
    text = RUN_FFMPEG.read_text(encoding='utf-8')
    branch = text[text.index('source_type" = "x11grab"'):]
    # Bound the slice at the next source_type branch, not the first 'fi' — the quality
    # tiering above is a plain if/else and would truncate the search too early.
    end = branch.find('source_type" = "', 10)
    branch = branch[:end if end != -1 else len(branch)]
    assert 'xdpyinfo' in branch, 'the x11grab branch must verify the display'
    assert 'repair_x11_auth' in branch, 'the x11grab branch must repair the display'
    # And the verification must gate the repair, not run after it unconditionally.
    assert branch.index('xdpyinfo') < branch.index('repair_x11_auth')