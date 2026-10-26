"""Opt-in burn-in of the vehicle telemetry (TASK-90 goal 12): the shell functions in run_ffmpeg.sh that decide and build the drawtext
filter, run against a real ffmpeg. Skipped where ffmpeg has no drawtext or no font is installed."""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'backend_host', 'scripts', 'run_ffmpeg.sh')
FFMPEG = shutil.which('ffmpeg')
FONTS = ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf', '/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf',
         '/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf', '/System/Library/Fonts/Menlo.ttc']
FONT = next((f for f in FONTS if os.path.isfile(f)), None)


def functions():
    """The two shell functions, cut out of run_ffmpeg.sh (the script itself needs bash 4 and a host)."""
    src = open(SCRIPT).read()
    a = src.index('telemetry_burn_in_enabled() {')
    b = src.index('# Function to detect source type')
    return src[a:b]


def sh(code, env=None, check=True):
    full = {'PATH': os.environ['PATH'], 'BACKEND_HOST_DIR': os.path.join(ROOT, 'backend_host'), **(env or {})}
    r = subprocess.run(['bash', '-c', functions() + '\n' + code], env=full, capture_output=True, text=True)
    if check:
        assert r.returncode == 0, r.stderr
    return r


def enabled(device, env):
    return sh(f'telemetry_burn_in_enabled {device}', env, check=False).returncode == 0


def test_off_by_default_and_for_every_shipped_profile():
    assert not enabled('device1', {})
    for profile in ('tv_app', 'counting_cars', 'egg_quality', 'ad_meter', 'drone'):
        assert not enabled('device1', {'MONITOR_PROFILE': profile}), profile      # the drone profile ships with burn-in off


def test_the_device_variable_turns_it_on_or_off_for_that_device_only():
    env = {'DEVICE1_TELEMETRY_BURN_IN': '1', 'MONITOR_PROFILE': 'drone'}
    assert enabled('device1', env) and not enabled('device2', env)
    assert not enabled('device1', {'DEVICE1_TELEMETRY_BURN_IN': 'off'})
    assert enabled('device3', {'DEVICE3_TELEMETRY_BURN_IN': 'TRUE'})
    assert not enabled('host', {'DEVICE1_TELEMETRY_BURN_IN': '1'})


def test_the_profile_manifest_can_ask_for_it(tmp_path):
    cfg = tmp_path / 'config' / 'monitor' / 'profiles'
    cfg.mkdir(parents=True)
    (cfg / 'rover.yaml').write_text('name: rover\nburn_in: true\n')
    (cfg / 'plain.yaml').write_text('name: plain\n# burn_in: true\n')
    base = {'BACKEND_HOST_DIR': str(tmp_path)}
    assert enabled('device1', {**base, 'MONITOR_PROFILE': 'rover'})
    assert enabled('device2', {**base, 'DEVICE2_MONITOR_PROFILE': 'rover', 'MONITOR_PROFILE': 'plain'})     # a device profile wins over the host's
    assert not enabled('device1', {**base, 'MONITOR_PROFILE': 'plain'})                                      # a commented line is nothing
    assert not enabled('device1', {**base, 'DEVICE1_TELEMETRY_BURN_IN': '0', 'MONITOR_PROFILE': 'rover'})   # the variable wins over the manifest
    assert not enabled('device1', {**base, 'MONITOR_PROFILE': '../etc/passwd'})                              # a name is a name


def test_python_and_shell_agree(tmp_path):
    from shared.src.lib.drone.telemetry_status import telemetry_burn_in
    (tmp_path / 'rover.yaml').write_text('name: rover\nburn_in: true\n')
    (tmp_path / 'plain.yaml').write_text('name: plain\n')
    cfg = tmp_path / 'config' / 'monitor' / 'profiles'
    cfg.mkdir(parents=True)
    for n in ('rover', 'plain'):
        shutil.copy(tmp_path / f'{n}.yaml', cfg / f'{n}.yaml')
    for env in ({'MONITOR_PROFILE': 'rover'}, {'MONITOR_PROFILE': 'plain'}, {'MONITOR_PROFILE': 'rover', 'DEVICE1_TELEMETRY_BURN_IN': '0'},
                {'MONITOR_PROFILE': 'plain', 'DEVICE1_TELEMETRY_BURN_IN': 'yes'}, {}):
        assert enabled('device1', {**env, 'BACKEND_HOST_DIR': str(tmp_path)}) == telemetry_burn_in(1, env, str(cfg)), env


def test_nothing_is_printed_or_created_when_it_is_off(tmp_path):
    r = sh(f'telemetry_hud_filter device1 "{tmp_path}/metadata"')
    assert r.stdout == '' and not (tmp_path / 'metadata').exists()


def test_no_font_means_a_clean_video_and_a_log_line(tmp_path):
    r = sh(f'telemetry_hud_filter device1 "{tmp_path}/metadata"', {'DEVICE1_TELEMETRY_BURN_IN': '1', 'TELEMETRY_HUD_FONT': '/nowhere.ttf'})
    assert r.stdout == '' and 'no font' in r.stderr or FONT is not None     # (a host with a default font finds that instead)


needs_ffmpeg = pytest.mark.skipif(not FFMPEG or not FONT or b' drawtext ' not in subprocess.run([FFMPEG or 'true', '-hide_banner', '-filters'], capture_output=True).stdout,
                                  reason='needs ffmpeg with drawtext and a font')


@needs_ffmpeg
def test_the_filter_draws_top_right_and_follows_the_text_file(tmp_path):
    meta = tmp_path / 'metadata'
    r = sh(f'FFMPEG_BIN="{FFMPEG}" telemetry_hud_filter device1 "{meta}"', {'DEVICE1_TELEMETRY_BURN_IN': '1', 'TELEMETRY_HUD_FONT': FONT})
    flt = r.stdout
    assert flt.startswith('drawtext=') and flt.endswith(',') and 'reload=1' in flt and 'x=w-tw' in flt
    assert (meta / 'telemetry_hud.txt').read_text() == 'NO TELEMETRY'          # a placeholder, so a grabber that starts first does not fail
    (meta / 'telemetry_hud.txt').write_text('BAT 87%  62C  ALT 1.2m  0.5m/s')

    def frame(extra=''):
        out = tmp_path / 'f.raw'
        subprocess.run([FFMPEG, '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x336699:s=960x720:r=5', '-vf', f'{extra}format=gray',
                        '-frames:v', '1', '-f', 'rawvideo', str(out)], check=True)
        return out.read_bytes()

    plain, burned = frame(), frame(flt)
    w, h = 960, 720
    changed = [(i % w, i // w) for i in range(w * h) if plain[i] != burned[i]]
    assert changed, 'nothing was drawn'
    xs, ys = [c[0] for c in changed], [c[1] for c in changed]
    assert min(xs) > w * 0.4 and max(xs) > w * 0.9 and max(ys) < h * 0.15, (min(xs), max(xs), max(ys))   # top right only
    # the file is re-read: other text gives another picture, with no restart of anything
    (meta / 'telemetry_hud.txt').write_text('NO TELEMETRY')
    assert frame(flt) != burned
