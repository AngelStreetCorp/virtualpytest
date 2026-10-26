"""TASK-102 STREAM_PROFILE loader (backend_host/scripts/stream_profile.sh).

The loader is a bash function (associative array; needs bash 4+). Tests run on
macOS where `/bin/bash` is 3.2, so we run the bash loader in a `bash >= 4` if
present, or fall back to a Python-emulated test of the same env keys when
bash 4 is unavailable. Either way the contract is the same: 3 named
profiles, the right env keys expanded, a typo'd name falls back to the
safe default, legacy hosts are unchanged.

Fakes only — no device, no DB, no network, no ffmpeg.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOADER = REPO_ROOT / 'backend_host' / 'scripts' / 'stream_profile.sh'


def _has_bash4() -> bool:
    """Returns True iff the system has a bash >= 4 binary on PATH (the loader
    uses `declare -A`). macOS /bin/bash is 3.2 and would fail."""
    bash4 = shutil.which('bash')
    if not bash4:
        return False
    try:
        out = subprocess.run([bash4, '-c', 'echo "${BASH_VERSINFO[0]}"'],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip().isdigit() and int(out.stdout.strip()) >= 4
    except Exception:
        return False


needs_bash4 = pytest.mark.skipif(
    not _has_bash4(),
    reason="bash >= 4 required (associative array; macOS /bin/bash is 3.2)",
)


def _run_loader(env_overrides: dict[str, str]) -> dict[str, str]:
    """Source stream_profile.sh in a clean subshell with the given env, return
    the post-loader env (only the keys we care about)."""
    script = f"""
        set -e
        source '{LOADER}'
        {''.join(f'export {k}={v!r}\\n' for k, v in env_overrides.items())}
        apply_stream_profile
        printf '%s\\n' \
          "STREAM_PROFILE=${{STREAM_PROFILE:-}}" \
          "HOST_TIER_CAP=${{HOST_TIER_CAP:-}}" \
          "VAAPI_MODE=${{VAAPI_MODE:-}}" \
          "VAAPI_MIN_QUALITY=${{VAAPI_MIN_QUALITY:-}}" \
          "STREAM_TYPE_DEFAULT=${{STREAM_TYPE_DEFAULT:-}}" \
          "SW_THREADS=${{SW_THREADS:-}}" \
          "MONITOR_PROFILE=${{MONITOR_PROFILE:-}}"
    """
    result = subprocess.run(
        ['bash', '-c', script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"loader failed: {result.stderr}"
    parsed = {}
    for line in result.stdout.strip().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            parsed[k] = v
    return parsed


@needs_bash4
def test_stream_local_hd_expands_to_the_right_bundle():
    env = _run_loader({'STREAM_PROFILE': 'stream_local_hd'})
    assert env['STREAM_PROFILE'] == 'stream_local_hd'
    assert env['HOST_TIER_CAP'] == '12'
    assert env['VAAPI_MODE'] == 'off'
    assert env['VAAPI_MIN_QUALITY'] == 'low'
    assert env['STREAM_TYPE_DEFAULT'] == 'videofile'
    assert env['SW_THREADS'] == '1'
    assert env['MONITOR_PROFILE'] == 'tv_lite'


@needs_bash4
def test_stream_hls_720p_expands_to_decode_only_cap_24():
    env = _run_loader({'STREAM_PROFILE': 'stream_hls_720p'})
    assert env['STREAM_PROFILE'] == 'stream_hls_720p'
    assert env['HOST_TIER_CAP'] == '24'
    assert env['VAAPI_MODE'] == 'decode_only'
    assert env['VAAPI_MIN_QUALITY'] == 'low'
    assert env['STREAM_TYPE_DEFAULT'] == 'hls'
    assert env['SW_THREADS'] == '1'
    assert env['MONITOR_PROFILE'] == 'tv_lite'


@needs_bash4
def test_stream_hls_360p_expands_to_off_cap_48():
    env = _run_loader({'STREAM_PROFILE': 'stream_hls_360p'})
    assert env['STREAM_PROFILE'] == 'stream_hls_360p'
    assert env['HOST_TIER_CAP'] == '48'
    assert env['VAAPI_MODE'] == 'off'
    assert env['VAAPI_MIN_QUALITY'] == 'low'
    assert env['STREAM_TYPE_DEFAULT'] == 'hls'
    assert env['SW_THREADS'] == '1'
    assert env['MONITOR_PROFILE'] == 'tv_lite'


@needs_bash4
def test_stream_local_360p_expands_to_file_cap_48():
    """TASK-103: the 4th profile — local files, software, cap 48. Same VAAPI / SW /
    MONITOR as stream_hls_360p (no GPU) but STREAM_TYPE_DEFAULT=file so /var/lib/vpt-movies/
    is the default source instead of HLS network."""
    env = _run_loader({'STREAM_PROFILE': 'stream_local_360p'})
    assert env['STREAM_PROFILE'] == 'stream_local_360p'
    assert env['HOST_TIER_CAP'] == '48'
    assert env['VAAPI_MODE'] == 'off'
    assert env['VAAPI_MIN_QUALITY'] == 'low'
    assert env['STREAM_TYPE_DEFAULT'] == 'file'
    assert env['SW_THREADS'] == '1'
    assert env['MONITOR_PROFILE'] == 'tv_lite'


@needs_bash4
def test_typo_profile_name_falls_back_to_stream_hls_720p():
    """An unknown profile name logs a warning and falls back to the safe default.
    A typo shouldn't kill the host (it has 24 ffmpeg children running)."""
    env = _run_loader({'STREAM_PROFILE': 'stream_uhd_8k'})
    assert env['STREAM_PROFILE'] == 'stream_hls_720p'
    assert env['HOST_TIER_CAP'] == '24'
    assert env['VAAPI_MODE'] == 'decode_only'
    assert env['STREAM_TYPE_DEFAULT'] == 'hls'


@needs_bash4
def test_empty_profile_name_falls_back_to_stream_hls_720p():
    env = _run_loader({'STREAM_PROFILE': ''})
    assert env['STREAM_PROFILE'] == 'stream_hls_720p'
    assert env['HOST_TIER_CAP'] == '24'


@needs_bash4
def test_no_profile_keeps_legacy_env():
    """No STREAM_PROFILE set: STREAM_TYPE_DEFAULT falls back to 'hls' (the
    autodetect default), the other env keys are NOT touched."""
    env = _run_loader({})
    assert env['STREAM_PROFILE'] == ''
    assert env['HOST_TIER_CAP'] == ''
    assert env['VAAPI_MODE'] == ''
    assert env['VAAPI_MIN_QUALITY'] == ''
    assert env['STREAM_TYPE_DEFAULT'] == 'hls'
    assert env['SW_THREADS'] == ''
    assert env['MONITOR_PROFILE'] == ''


@needs_bash4
def test_legacy_env_passes_through_when_no_profile():
    """Legacy hosts that hand-tune VAAPI_MODE / SW_THREADS / etc. in .env
    must keep working when STREAM_PROFILE is unset."""
    env = _run_loader({
        'VAAPI_MODE': 'full',
        'VAAPI_MIN_QUALITY': 'hd',
        'SW_THREADS': '2',
        'MONITOR_PROFILE': 'pc',
        'HOST_TIER_CAP': '60',
    })
    assert env['STREAM_PROFILE'] == ''
    assert env['VAAPI_MODE'] == 'full'
    assert env['VAAPI_MIN_QUALITY'] == 'hd'
    assert env['SW_THREADS'] == '2'
    assert env['MONITOR_PROFILE'] == 'pc'
    assert env['HOST_TIER_CAP'] == '60'


@needs_bash4
def test_per_host_cap_override_for_under_spec_hardware():
    """TASK-100 §3 contract: an operator can override HOST_TIER_CAP in .env
    for under-spec'd hardware. The loader runs AFTER _load_env_file so the
    .env value wins."""
    env = _run_loader({
        'STREAM_PROFILE': 'stream_local_hd',
        'HOST_TIER_CAP': '8',
    })
    # STREAM_PROFILE is set; the loader has the post-override value.
    assert env['STREAM_PROFILE'] == 'stream_local_hd'
    # The profile's default 12 is overridden by the .env value 8.
    assert env['HOST_TIER_CAP'] == '8'


@needs_bash4
def test_stream_profile_summary_format():
    """stream_profile_summary echoes "name|cap" on stdout. Used by the
    /host/system/config JSON field and the dashboard host card."""
    result = subprocess.run(
        ['bash', '-c', f"""
            source '{LOADER}'
            export STREAM_PROFILE=stream_hls_360p
            stream_profile_summary
        """],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    # Last line of stdout is the summary
    summary = result.stdout.strip().splitlines()[-1]
    assert summary == 'stream_hls_360p|48'


@needs_bash4
def test_run_ffmpeg_sh_sources_stream_profile_sh():
    """run_ffmpeg.sh MUST source the loader (not inline it). The inline version
    was a footgun: changes to the bundle had to be applied to two places."""
    run_ffmpeg = REPO_ROOT / 'backend_host' / 'scripts' / 'run_ffmpeg.sh'
    text = run_ffmpeg.read_text()
    assert "source \"$SCRIPT_DIR/stream_profile.sh\"" in text
    assert "apply_stream_profile" in text
    # The inline table should be GONE.
    assert "STREAM_PROFILES=(" not in text
    assert 'STREAM_PROFILES=(\n  ["stream_local_hd"]' not in text
