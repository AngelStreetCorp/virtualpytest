"""E56: an imagefile capture source must not be poisoned by a truncated frame.

A phone on a host is captured from a frame FILE that emulator_screencap.sh keeps
rewriting. When the phone dropped off USB in the middle of a screencap, adb
handed back a partial PNG and the loop published it over the last good frame.
From then on the capture agent had no source it could decode: it wrote no
thumbnail and no playlist, the platform reported a 404 for a device it still
listed, and nothing on the host said why.

The tests below pin the three things that had to be true:

  * the frame loop never publishes a frame that did not arrive whole;
  * the capture agent still SELECTS the phone slot — a capture list that drops a
    device must fail these tests, not skip it;
  * the reader names a truncated source as truncated, and keeps the boot-race
    message for a source that is simply not there yet.

Fakes only — no device, no adb, no ffmpeg, no host, no network. The serials and
the slot names below are made up.
"""

import os
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / 'backend_host' / 'scripts'
FRAME_SOURCE = SCRIPTS / 'frame_source.sh'
SCREENCAP = SCRIPTS / 'emulator_screencap.sh'
RUN_FFMPEG = SCRIPTS / 'run_ffmpeg.sh'


# --------------------------------------------------------------------------
# PNG fixtures
# --------------------------------------------------------------------------

def _png_bytes(width: int = 8, height: int = 8, color=(10, 20, 30)) -> bytes:
    """A real, whole PNG (signature + IHDR + IDAT + IEND)."""
    raw = b''.join(b'\x00' + bytes(color) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _truncated_png(width: int = 8, height: int = 8) -> bytes:
    """The same frame with the transfer cut short: the tail is gone, so no
    decoder can read it (ImageMagick: "Read Exception", PIL: "image file is
    truncated")."""
    return _png_bytes(width, height)[:-20]


# --------------------------------------------------------------------------
# frame_source.sh
# --------------------------------------------------------------------------

def _bash(script: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                          env=env, timeout=30)


@pytest.mark.unit
def test_frame_source_state_names_the_three_states(tmp_path):
    """missing (boot race) / corrupt (a truncated frame) / ok (a whole frame)."""
    whole = tmp_path / 'whole.png'
    whole.write_bytes(_png_bytes())
    cut = tmp_path / 'cut.png'
    cut.write_bytes(_truncated_png())
    empty = tmp_path / 'empty.png'
    empty.write_bytes(b'')

    script = f"""
        source '{FRAME_SOURCE}'
        for f in '{tmp_path / 'absent.png'}' '{empty}' '{cut}' '{whole}'; do
            printf '%s %s\\n' "$(frame_source_state "$f")" "$(basename "$f")"
        done
    """
    out = _bash(script)
    assert out.returncode == 0, out.stderr
    states = {}
    for line in out.stdout.strip().splitlines():
        state, name = line.split()
        states[name] = state
    assert states['absent.png'] == 'missing'
    assert states['empty.png'] == 'corrupt'
    assert states['cut.png'] == 'corrupt'
    assert states['whole.png'] == 'ok'


@pytest.mark.unit
def test_frame_is_complete_rejects_a_cut_frame(tmp_path):
    cut = tmp_path / 'cut.png'
    cut.write_bytes(_truncated_png())
    whole = tmp_path / 'whole.png'
    whole.write_bytes(_png_bytes())

    script = f"""
        source '{FRAME_SOURCE}'
        frame_is_complete '{whole}' && echo "whole=yes" || echo "whole=no"
        frame_is_complete '{cut}' && echo "cut=yes" || echo "cut=no"
    """
    out = _bash(script)
    assert out.returncode == 0, out.stderr
    assert 'whole=yes' in out.stdout
    assert 'cut=no' in out.stdout


# --------------------------------------------------------------------------
# emulator_screencap.sh — the writer
# --------------------------------------------------------------------------

FAKE_ADB = r"""#!/bin/bash
# Fake adb: hands a frame back on stdout. The first FAKE_ADB_GOOD_CALLS calls
# return the whole frame, every later call returns the cut one — a phone that
# drops off USB mid-screencap.
n=$(cat "$FAKE_ADB_COUNT" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" > "$FAKE_ADB_COUNT"
case "$*" in
  *exec-out*screencap*)
    if [ "$n" -le "${FAKE_ADB_GOOD_CALLS:-1}" ]; then cat "$FAKE_ADB_GOOD"; else cat "$FAKE_ADB_BAD"; fi
    ;;
  *dumpsys*power*) echo "mWakefulness=Awake" ;;
  *) exit 0 ;;
esac
"""


def _run_screencap_loop(tmp_path, good_calls: int, seconds: str = '2'):
    """Run the frame loop with a fake adb and return the published frame."""
    bindir = tmp_path / 'bin'
    bindir.mkdir(exist_ok=True)
    adb = bindir / 'adb'
    adb.write_text(FAKE_ADB)
    adb.chmod(0o755)

    good = tmp_path / 'good.png'
    good.write_bytes(_png_bytes())
    bad = tmp_path / 'bad.png'
    bad.write_bytes(_truncated_png())
    published = tmp_path / 'latest.png'

    env = dict(os.environ)
    env['PATH'] = f"{bindir}:{env['PATH']}"
    env['FAKE_ADB_COUNT'] = str(tmp_path / 'calls')
    env['FAKE_ADB_GOOD'] = str(good)
    env['FAKE_ADB_BAD'] = str(bad)
    env['FAKE_ADB_GOOD_CALLS'] = str(good_calls)

    proc = subprocess.run(
        ['timeout', seconds, 'bash', str(SCREENCAP), 'fake-serial', str(published)],
        capture_output=True, text=True, env=env, timeout=60)
    return published, good, bad, proc


@pytest.mark.unit
def test_a_truncated_frame_never_replaces_the_last_whole_one(tmp_path):
    """THE CAUSE (E56): a frame that did not arrive whole must not be published.

    Publishing it replaced the last good frame with one no decoder can read:
    the capture agent then had no source at all, wrote no thumbnail and no
    playlist, and the platform reported a 404 for a device it still listed.
    """
    published, good, bad, proc = _run_screencap_loop(tmp_path, good_calls=1)

    assert published.exists(), 'no frame was published at all'
    assert published.read_bytes() == good.read_bytes(), (
        'the truncated frame replaced the last whole one — the capture source is '
        'poisoned until a whole frame comes back')
    assert published.read_bytes() != bad.read_bytes()


@pytest.mark.unit
def test_a_whole_frame_is_published(tmp_path):
    """The fix must not stop good frames from reaching the capture agent."""
    published, good, _bad, _proc = _run_screencap_loop(tmp_path, good_calls=999)

    assert published.exists()
    assert published.read_bytes() == good.read_bytes()


# --------------------------------------------------------------------------
# run_ffmpeg.sh — the capture list (which devices are captured at all)
# --------------------------------------------------------------------------

def _grabbers_loop_source() -> str:
    """The device-selection loop of run_ffmpeg.sh, verbatim.

    Extracted (not re-implemented) so the test exercises the shipped code: the
    loop decides which devices the capture agent captures, and a list that
    dropped a device must fail the test, not skip it.
    """
    src = RUN_FFMPEG.read_text()
    start = src.index('for i in $(seq 1 "${_max_devices}")')
    end = src.index('\ndone\n', start) + len('\ndone\n')
    return src[start:end]


# A host-shaped env: four working slots and the phone (DEVICE6), whose video
# comes from a frame file the screencap loop rewrites. The names and serials are
# made up.
HOST_ENV = {
    'DEVICE1_NAME': 'tv-one', 'DEVICE1_MODEL': 'apple_tv',
    'DEVICE1_VIDEO': '/dev/stb1', 'DEVICE1_VIDEO_CAPTURE_PATH': '/var/www/html/stream/capture1',
    'DEVICE2_NAME': 'stb-one', 'DEVICE2_MODEL': 'stb',
    'DEVICE2_VIDEO': '/dev/stb2', 'DEVICE2_VIDEO_CAPTURE_PATH': '/var/www/html/stream/capture2',
    'DEVICE3_NAME': 'stb-two', 'DEVICE3_MODEL': 'stb',
    'DEVICE3_VIDEO': '/dev/stb3', 'DEVICE3_VIDEO_CAPTURE_PATH': '/var/www/html/stream/capture3',
    'DEVICE5_NAME': 'tv-two', 'DEVICE5_MODEL': 'android_tv',
    'DEVICE5_ADB_SERIAL': 'fake-serial-tv-two', 'DEVICE5_VIDEO': '/dev/stb5',
    'DEVICE5_VIDEO_CAPTURE_PATH': '/var/www/html/stream/capture5',
    'DEVICE6_NAME': 'phone-slot', 'DEVICE6_MODEL': 'android_mobile',
    'DEVICE6_ADB_SERIAL': 'fake-serial-phone-slot',
    'DEVICE6_VIDEO': '/var/www/html/stream/emulator_frames/device6/latest.png',
    'DEVICE6_VIDEO_CAPTURE_PATH': '/var/www/html/stream/capture6',
}


@pytest.mark.unit
def test_the_capture_list_keeps_the_phone_slot():
    """The phone slot must be in the capture list.

    The list is built from the host's DEVICEn_* config, exactly as the capture
    agent builds it on the host. If the code dropped a slot, this test FAILS —
    it never skips the device it cannot find.
    """
    harness = f"""
        declare -A GRABBERS=()
        declare -A STREAM_TYPE=()
        declare -A OVERRIDE_KIND=()
        SINGLE_DEVICE_MODE=false
        TARGET_DEVICE=""
        _max_devices="${{MAX_DEVICES:-99}}"
        get_rtsp_url_state() {{ echo ""; }}
        get_video_path_state() {{ echo ""; }}
        override_kind_for_model() {{ echo ""; }}
        {_grabbers_loop_source()}
        for d in "${{!GRABBERS[@]}}"; do printf '%s\\t%s\\n' "$d" "${{GRABBERS[$d]}}"; done | sort
    """
    env = dict(os.environ)
    env.update(HOST_ENV)
    out = _bash(harness, env=env)
    assert out.returncode == 0, out.stderr

    selected = dict(line.split('\t') for line in out.stdout.strip().splitlines() if line)
    assert set(selected) == {'device1', 'device2', 'device3', 'device5', 'device6'}, selected
    assert 'device6' in selected, f'the capture list dropped the phone slot: {selected}'
    source, _audio, capture_dir, _fps = selected['device6'].split('|')
    assert source == HOST_ENV['DEVICE6_VIDEO']
    assert capture_dir == HOST_ENV['DEVICE6_VIDEO_CAPTURE_PATH']


# --------------------------------------------------------------------------
# run_ffmpeg.sh — the reader (what it says about a source it cannot decode)
# --------------------------------------------------------------------------

def _wait_loop_source() -> str:
    """The imagefile branch's wait-for-a-usable-source loop, verbatim."""
    src = RUN_FFMPEG.read_text()
    start = src.index('    local img_dims=""')
    end = src.index('\n    done\n', start) + len('\n    done\n')
    return src[start:end]


FAKE_IDENTIFY = r"""#!/bin/bash
# Fake identify: ImageMagick cannot read a truncated PNG, and neither can this.
file="${@: -1}"
if [ -f "$file" ] && [ "$(tail -c 12 "$file" | od -An -tx1 | tr -d ' \n')" = "0000000049454e44ae426082" ]; then
  printf '1080 1920\n'
fi
"""

FAKE_SLEEP = "#!/bin/bash\nexit 0\n"


def _run_wait_loop(tmp_path, source_path):
    """Run the reader's wait loop against a source file and return its output."""
    bindir = tmp_path / 'bin'
    bindir.mkdir(exist_ok=True)
    for name, body in (('identify', FAKE_IDENTIFY), ('sleep', FAKE_SLEEP)):
        fake = bindir / name
        fake.write_text(body)
        fake.chmod(0o755)

    harness = f"""
        source '{FRAME_SOURCE}'
        probe() {{
          local source='{source_path}'
        {_wait_loop_source()}
          echo "DIMS=$img_dims"
        }}
        probe
    """
    env = dict(os.environ)
    env['PATH'] = f"{bindir}:{env['PATH']}"
    return _bash(harness, env=env)


@pytest.mark.unit
def test_a_truncated_source_is_named_as_truncated(tmp_path):
    """A source that is there but unreadable must not be reported as missing.

    The two faults need different fixes: a source that is not written yet is a
    boot race and clears itself, a truncated frame stays broken until the frame
    loop publishes a whole one. Reporting both as "not available" sends the
    reader looking for a device that is simply not there yet.
    """
    cut = tmp_path / 'cut.png'
    cut.write_bytes(_truncated_png())

    out = _run_wait_loop(tmp_path, cut)
    assert out.returncode == 0, out.stderr
    assert 'truncated/corrupt' in out.stdout, out.stdout
    assert 'Source image not available' not in out.stdout, out.stdout


@pytest.mark.unit
def test_a_source_that_is_not_written_yet_stays_a_boot_race(tmp_path):
    """A source that does not exist yet keeps the boot-race message."""
    absent = tmp_path / 'absent.png'

    out = _run_wait_loop(tmp_path, absent)
    assert out.returncode == 0, out.stderr
    assert 'Source image not available' in out.stdout, out.stdout
    assert 'truncated/corrupt' not in out.stdout, out.stdout


@pytest.mark.unit
def test_a_whole_source_is_used_as_is(tmp_path):
    """A whole frame is measured and used, with no waiting."""
    whole = tmp_path / 'whole.png'
    whole.write_bytes(_png_bytes())

    out = _run_wait_loop(tmp_path, whole)
    assert out.returncode == 0, out.stderr
    assert 'DIMS=1080 1920' in out.stdout, out.stdout
    assert 'Waiting' not in out.stdout, out.stdout
