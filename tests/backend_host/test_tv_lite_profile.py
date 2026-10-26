"""tv_lite (TASK-95): stream and control only. The profile, the services that follow it, vpt-host's restarts and
run_ffmpeg.sh's lean outputs."""
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import shared.src.lib.utils.monitor_profile as mp  # noqa: E402
import backend_host.src.lib.utils.monitor_profile as hostmp  # noqa: E402

RUN_FFMPEG = os.path.join(ROOT, 'backend_host', 'scripts', 'run_ffmpeg.sh')
PROFILES = os.path.join(ROOT, 'backend_host', 'config', 'monitor', 'profiles')


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if mp._PROFILE_KEY.match(k):
            monkeypatch.delenv(k)


def test_tv_lite_switches_every_host_service_off_and_keeps_nothing_but_the_stream():
    assert mp.profile_services('tv_lite') == {s: False for s in mp.SERVICES}
    assert mp.profile_stream_mode('tv_lite') == 'lean'
    for other in ('tv_app', 'counting_cars', 'egg_quality', 'ad_meter'):
        assert mp.profile_stream_mode(other) == 'full'
        assert mp.profile_services(other)['archiver'] and mp.profile_services(other)['kpi'] and mp.profile_services(other)['avq']


def test_both_validators_accept_the_manifest():
    from monitor.profiles import load_profile
    prof = load_profile('tv_lite')
    assert prof.stream == 'lean' and prof.services.archiver is False and prof.services.img is False
    assert load_profile('tv_app').stream == 'full'


def test_a_bad_stream_value_is_refused():
    with pytest.raises(ValueError):
        mp.validate_manifest_light({'name': 'x', 'stream': 'tiny', 'img': {'analyzers': [{'type': 'tv_app'}]}}, 'x')


def test_resolution_per_device():
    env = {'MONITOR_PROFILE': 'tv_lite', 'DEVICE3_MONITOR_PROFILE': 'tv_app'}
    assert mp.resolve_monitor_profile(1, env=env) == 'tv_lite'
    assert mp.resolve_monitor_profile(3, env=env) == 'tv_app'
    assert mp.resolve_monitor_profile(1, env={'MONITOR_PROFILE': 'tv_lyte'}) == 'tv_app'   # a typo never stops a device


def test_folders_for_each_service_on_a_mixed_host(monkeypatch):
    import shared.src.lib.utils.storage_path_utils as spu
    monkeypatch.setattr(spu, 'get_device_info_from_capture_folder',
                        lambda f: {'device_index': int(f[-1])})
    env = {'DEVICE2_MONITOR_PROFILE': 'tv_lite'}
    folders = ['capture1', 'capture2']
    for service in mp.SERVICES:
        assert mp.folders_needing_service(service, folders, env) == ['capture1'], service
    # every device lean: every service has nothing to do and idles
    env = {'MONITOR_PROFILE': 'tv_lite'}
    for service in mp.SERVICES:
        assert mp.folders_needing_service(service, folders, env) == [], service


# ---- vpt-host ---------------------------------------------------------------------------------

@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setattr(hostmp, 'STATE_FILE', str(tmp_path / 'applied.json'))
    env = {'DEVICE1_VIDEO_CAPTURE_PATH': '/x/capture1', 'DEVICE2_VIDEO_CAPTURE_PATH': '/x/capture2'}
    monkeypatch.setattr(hostmp, 'read_env_files', lambda pattern=None: dict(env))
    restarted = []
    return env, restarted, (lambda unit: restarted.append(unit) or True)


def test_every_device_to_tv_lite_restarts_all_followers_and_the_stream_once(host):
    env, restarted, restart = host
    hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)
    env['MONITOR_PROFILE'] = 'tv_lite'
    out = hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)
    assert sorted(out['restarted']) == sorted([
        'vpt-monitor-img', 'vpt-monitor-audio', 'vpt-monitor-subtitle', 'vpt-archiver', 'vpt-kpi', 'vpt-avq', 'vpt-stream'])
    restarted.clear()
    del env['MONITOR_PROFILE']                                   # rollback
    out = hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)
    assert 'vpt-stream' in out['restarted'] and 'vpt-archiver' in out['restarted']


def test_one_lean_device_keeps_the_archiver_running_for_the_other(host):
    env, restarted, restart = host
    hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)
    env['DEVICE2_MONITOR_PROFILE'] = 'tv_lite'
    out = hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)
    assert 'vpt-stream' in out['restarted'] and 'vpt-archiver' in out['restarted']      # device set changed: it re-reads
    assert hostmp.get_monitor_profiles([{'device_id': 'device1'}, {'device_id': 'device2'}], ) is not None


def test_a_record_written_before_tv_lite_does_not_restart_the_new_followers(host):
    """The first deploy of this change must not bounce the archiver, kpi and avq on hosts that stay tv_app."""
    env, restarted, restart = host
    hostmp._write_state({'profiles': {'device1': 'tv_app', 'device2': 'tv_app'},
                         'services': {'img': ['device1', 'device2'], 'audio': ['device1', 'device2'], 'subtitle': ['device1', 'device2']}})
    out = hostmp.apply_monitor_profiles(restart, is_active=lambda u: True)
    assert out['restarted'] == []


def test_only_known_units_are_restartable():
    for unit in ('vpt-archiver', 'vpt-kpi', 'vpt-avq', 'vpt-stream', 'vpt-monitor-img'):
        assert hostmp._RESTARTABLE.fullmatch(unit)
    for unit in ('vpt-host', 'vpt-stream; id', 'vpt-vnc'):
        assert not hostmp._RESTARTABLE.fullmatch(unit)


# ---- run_ffmpeg.sh ----------------------------------------------------------------------------

def _bash_functions(*names):
    """The text of the named top-level shell functions, to run them without the rest of the script."""
    src = open(RUN_FFMPEG).read()
    out = []
    for n in names:
        m = re.search(r'^%s\(\) \{\n.*?^\}\n' % re.escape(n), src, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return '\n'.join(out)


def _mode(index, env):
    script = ('MONITOR_PROFILES_DIR=%s\n' % PROFILES) + _bash_functions('stream_mode_for') + '\nstream_mode_for %s\n' % index
    full_env = {k: v for k, v in os.environ.items() if not mp._PROFILE_KEY.match(k)}
    full_env.update(env)
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=full_env).stdout.strip()


def test_run_ffmpeg_resolves_the_stream_mode_like_python():
    assert _mode('device1', {}) == 'full'
    assert _mode('device1', {'MONITOR_PROFILE': 'tv_lite'}) == 'lean'
    assert _mode('device2', {'MONITOR_PROFILE': 'tv_lite', 'DEVICE2_MONITOR_PROFILE': 'tv_app'}) == 'full'
    assert _mode('device2', {'DEVICE2_MONITOR_PROFILE': 'tv_lite'}) == 'lean'
    assert _mode('device1', {'DEVICE2_MONITOR_PROFILE': 'tv_lite'}) == 'full'
    assert _mode('host', {'MONITOR_PROFILE': 'tv_lite'}) == 'lean'
    assert _mode('device1', {'MONITOR_PROFILE': 'tv_lyte'}) == 'full'          # no manifest = tv_app
    assert _mode('device1', {'MONITOR_PROFILE': '../tv_lite'}) == 'full'       # not a profile name
    assert _mode('device1', {'MONITOR_PROFILE': 'counting_cars'}) == 'full'


def _python_mode(index, env):
    n = mp.device_index_from_id(index)
    name = mp.resolve_monitor_profile(n, PROFILES, env=env)
    text = open(os.path.join(PROFILES, f'{name}.yaml')).read()
    return 'lean' if re.search(r'^stream:\s*lean\s*(#.*)?$', text, re.M) else 'full'


@pytest.mark.parametrize('index,env', [
    ('host', {'HOST_VNC_STREAM_PATH': '/host/vnc/stream'}),                       # host_vnc -> pc (lean)
    ('host', {'HOST_VNC_STREAM_PATH': '/host/vnc/stream', 'MONITOR_PROFILE': 'tv_app'}),  # explicit wins
    ('device1', {'DEVICE1_MODEL': 'android_mobile'}),
    ('device2', {'DEVICE2_MODEL': 'phone_agent', 'DEVICE2_MONITOR_PROFILE': 'tv_lite'}),
    ('device3', {'DEVICE3_MODEL': 'android_tv'}),
    ('host', {}),
])
def test_run_ffmpeg_applies_the_model_default_like_python(index, env):
    """BUG-0695: python gave host_vnc the lean `pc` profile (archiver idle) while run_ffmpeg.sh streamed it full, so
    nothing pruned its captures and the hot tmpfs filled: every screenshot then failed."""
    assert _mode(index, env) == _python_mode(index, env)


def test_run_ffmpeg_is_valid_bash():
    assert subprocess.run(['bash', '-n', RUN_FFMPEG]).returncode == 0


def test_a_full_device_still_gets_every_thumbnail_output():
    """The full-mode text is what it was: 5 fps thumbnails, 5 fps captures; only lean drops them."""
    src = open(RUN_FFMPEG).read()
    assert src.count('thm_graph="[thm]fps=5,scale=320:180:flags=neighbor,split=2[thumbout][latestout]"') == 3
    assert src.count('[cap]fps=${cap_fps_v},') == 3 and 'local lean=false cap_fps_v=5' in src
    assert src.count('thumb_out=""') >= 3 and src.count('$thumb_out') >= 3


def test_prune_keeps_the_newest_captures_and_drops_thumbnails(tmp_path):
    hot = tmp_path / 'capture1' / 'hot'
    for d in ('captures', 'thumbnails', 'metadata'):
        (hot / d).mkdir(parents=True)
    for i in range(1, 201):
        f = hot / 'captures' / f'capture_{i:09d}.jpg'
        f.write_text('x')
        os.utime(f, (1000 + i, 1000 + i))
    (hot / 'thumbnails' / 'capture_000000001_thumbnail.jpg').write_text('x')
    (hot / 'thumbnails' / 'latest.jpg').write_text('x')
    old = hot / 'metadata' / 'capture_1.json'
    old.write_text('{}')
    os.utime(old, (1, 1))
    script = _bash_functions('prune_lean_device') + '\nprune_lean_device %s\n' % (tmp_path / 'capture1')
    xargs_r = shutil.which('gxargs') or shutil.which('xargs')
    # BSD xargs (macOS) has no -r but skips empty input by itself; GNU xargs on the hosts needs -r.
    script = script.replace('xargs -r', xargs_r)
    assert subprocess.run(['bash', '-c', script], capture_output=True, text=True).returncode == 0
    left = sorted(os.listdir(hot / 'captures'))
    assert len(left) == 150 and left[-1] == 'capture_000000200.jpg' and left[0] == 'capture_000000051.jpg'
    assert os.listdir(hot / 'thumbnails') == ['latest.jpg']
    assert not old.exists()


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='needs ffmpeg')
def test_the_lean_graph_writes_two_captures_a_second_latest_and_no_thumbnails(tmp_path):
    """The lean filter graph (same filters and encoders as run_ffmpeg.sh's v4l2 branch) on a synthetic source."""
    for d in ('captures', 'thumbnails', 'segments'):
        (tmp_path / d).mkdir()
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-t', '6', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=10',
           '-filter_complex',
           '[0:v]split=3[str][cap][thm];[str]fps=10,scale=320:180:flags=fast_bilinear[streamout];'
           '[cap]fps=2,scale=1280:720:flags=fast_bilinear,setpts=PTS-STARTPTS[captureout];'
           '[thm]fps=2,scale=320:180:flags=neighbor[latestout]',
           '-map', '[streamout]', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-pix_fmt', 'yuv420p', '-g', '4',
           '-f', 'hls', '-hls_time', '0.4', '-hls_segment_filename', str(tmp_path / 'segments' / 'segment_%09d.ts'), str(tmp_path / 'segments' / 'output.m3u8'),
           '-map', '[captureout]', '-fps_mode', 'passthrough', '-c:v', 'mjpeg', '-q:v', '8', '-f', 'image2', '-atomic_writing', '1',
           '-start_number', '0', str(tmp_path / 'captures' / 'capture_%09d.jpg'),
           '-map', '[latestout]', '-fps_mode', 'passthrough', '-c:v', 'mjpeg', '-q:v', '8', '-f', 'image2', '-update', '1', '-atomic_writing', '1',
           str(tmp_path / 'thumbnails' / 'latest.jpg')]
    assert subprocess.run(cmd, capture_output=True, text=True, timeout=60).returncode == 0
    caps = os.listdir(tmp_path / 'captures')
    assert 8 <= len(caps) <= 14, caps                                    # 6 s at 2 fps
    assert os.listdir(tmp_path / 'thumbnails') == ['latest.jpg']
    assert len(os.listdir(tmp_path / 'segments')) > 10


def test_lean_latest_is_never_sparser_than_the_capture_branch():
    """A fps=1 latest branch next to fps=2 captures slowed ffmpeg 8 to 0.65x realtime (TASK-95 measurement)."""
    src = open(RUN_FFMPEG).read()
    assert 'fps=1,scale=320:180' not in src
    assert src.count('thm_graph="[thm]fps=${cap_fps_v},scale=320:180:flags=neighbor[latestout]"') == 3


# ---- VAAPI modes (TASK-95) ---------------------------------------------------------------------

def _net_block():
    """The network branch's plan + codec block, run with stubs for what start_grabber supplies."""
    src = open(RUN_FFMPEG).read()
    a = src.index('    local hw_input_flags="" stream_filter stream_codec\n')
    b = src.index('    local thm_graph=', a)
    return src[a:b]


def _net(env, quality='hd', sub_filter='', retry=False):
    script = (_bash_functions('vaapi_quality_rank', 'use_vaapi_for', 'vaapi_plan')
              + '\ndeclare -A VAAPI_SW_RETRY=()\n' + ('VAAPI_SW_RETRY[d1]=1\n' if retry else '')
              + 'f() {\n local index=d1 quality=%s input_fps=10 stream_scale=1280:720 stream_bitrate=1500k '
                'stream_maxrate=1800k stream_bufsize=3600k sub_filter="%s"\n' % (quality, sub_filter)
              + _net_block()
              + '\n echo "PLAN=$net_plan"; echo "HW=$hw_input_flags"; echo "FILTER=$stream_filter"; echo "CODEC=$stream_codec"'
                '; echo "THR=$net_threads"; echo "CAPPRE=$net_cap_pre"\n}\nf\n')
    full_env = {k: v for k, v in os.environ.items() if not k.startswith('VAAPI_') and k != 'SW_THREADS'}
    full_env.update(env)
    out = subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=full_env)
    assert out.returncode == 0, out.stderr
    return dict(l.split('=', 1) for l in out.stdout.splitlines() if re.match(r'^[A-Z]+=', l))


NODE = {'VAAPI_RENDER_NODE': '/dev/dri/renderD128'}


def test_auto_and_default_keys_are_todays_command():
    r = _net(NODE)
    assert r['PLAN'] == 'gpu'
    assert r['HW'] == '-hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -vaapi_device /dev/dri/renderD128'
    assert r['FILTER'] == '[str]fps=10,scale=1280:720:flags=fast_bilinear,format=nv12,hwupload[streamout]'
    assert r['CODEC'] == '-c:v h264_vaapi -b:v 1500k -maxrate 1800k -bufsize 3600k -g 4'
    assert r['THR'] == '' and r['CAPPRE'] == ''
    assert _net(dict(NODE, VAAPI_MODE='auto', VAAPI_MIN_QUALITY='low', SW_THREADS='0')) == r
    sw = _net({})                       # no node (empty /tmp/vpt_vaapi_render_node) = software, as before
    assert sw['PLAN'] == 'software' and sw['HW'] == ''
    assert sw['FILTER'] == '[str]fps=10,scale=1280:720:flags=fast_bilinear[streamout]'
    assert 'libx264 -preset ultrafast -tune zerolatency' in sw['CODEC'] and 'bframes=0 -pix_fmt' in sw['CODEC'] and 'threads' not in sw['CODEC']


def test_off_means_software_even_with_a_render_node():
    assert _net(dict(NODE, VAAPI_MODE='off')) == _net({})


def test_decode_only_and_encode_only():
    d = _net(dict(NODE, VAAPI_MODE='decode_only'))
    assert d['PLAN'] == 'decode_only' and d['HW'] == '-hwaccel vaapi -hwaccel_device /dev/dri/renderD128'
    assert 'hwupload' not in d['FILTER'] and 'libx264' in d['CODEC']
    e = _net(dict(NODE, VAAPI_MODE='encode_only'))
    assert e['PLAN'] == 'encode_only' and e['HW'] == '-vaapi_device /dev/dri/renderD128' and '-hwaccel' not in e['HW']
    assert 'hwupload' in e['FILTER'] and 'h264_vaapi' in e['CODEC']


def test_full_keeps_frames_on_the_gpu_and_downloads_for_the_jpegs():
    f = _net(dict(NODE, VAAPI_MODE='full'))
    assert f['PLAN'] == 'full' and '-hwaccel_output_format vaapi' in f['HW']
    assert f['FILTER'] == '[str]fps=10,scale_vaapi=1280:720[streamout]' and 'h264_vaapi' in f['CODEC']
    assert f['CAPPRE'] == 'hwdownload,format=nv12,'
    assert _net(dict(NODE, VAAPI_MODE='full'), sub_filter='subtitles=x,')['PLAN'] == 'gpu'     # needs software frames
    assert _net(dict(NODE, VAAPI_MODE='full'), retry=True)['PLAN'] == 'software'               # GPU could not decode it


def test_min_quality_sends_lower_qualities_to_software():
    env = dict(NODE, VAAPI_MIN_QUALITY='hd')
    assert _net(env, 'low')['PLAN'] == 'software' and _net(env, 'sd')['PLAN'] == 'software'
    assert _net(env, 'hd')['PLAN'] == 'gpu' and _net(env, 'hd_plus')['PLAN'] == 'gpu'
    assert _net(dict(NODE, VAAPI_MIN_QUALITY='hd_plus'), 'hd')['PLAN'] == 'software'


def test_sw_threads_only_touch_the_software_branch():
    t = _net(dict(NODE, VAAPI_MODE='off', SW_THREADS='2'))
    assert t['THR'] == '-threads 2 -filter_complex_threads 2' and 'bframes=0:threads=2 -pix_fmt' in t['CODEC']
    assert _net(dict(NODE, SW_THREADS='2'))['THR'] == ''      # gpu plan untouched


def test_hd_plus_gate_follows_the_helper():
    src = open(RUN_FFMPEG).read()
    assert 'if [ "$quality" = "hd_plus" ] && ! use_vaapi_for hd_plus; then' in src
    assert src.count('vaapi_plan "$quality"') == 2


def test_full_mode_downloads_the_capture_branch_and_logs_one_line_per_start():
    src = open(RUN_FFMPEG).read()
    assert '${FFMPEG_CMD/\\[cap\\]fps=/[cap]${net_cap_pre}fps=}' in src
    assert 'echo "vaapi: mode=${VAAPI_MODE:-auto} quality=$quality -> $net_plan"' in src
    assert 'echo "vaapi: mode=${VAAPI_MODE:-auto} quality=$quality -> $v4l2_plan"' in src


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='needs ffmpeg')
def test_the_software_thread_flags_are_accepted_by_ffmpeg(tmp_path):
    cmd = ['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-t', '1', '-threads', '2', '-filter_complex_threads', '2',
           '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=10', '-c:v', 'libx264', '-preset', 'ultrafast',
           '-x264opts', 'keyint=4:min-keyint=4:no-scenecut:bframes=0:threads=2', str(tmp_path / 'o.mp4')]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    assert (tmp_path / 'o.mp4').stat().st_size > 0
