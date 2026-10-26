"""Video timeline for a test run (TASK-94): contact sheet, geometry for click-to-seek, steps, html, i18n keys."""
import json
import os
import shutil
import subprocess

import pytest

from shared.src.lib.utils import report_timeline as rt

needs_ffmpeg = pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not installed')


@pytest.mark.parametrize('duration,step', [(30, 1), (180, 2), (300, 3), (600, 6), (601, 10), (900, 10), (3600, 60), (7200, 120)])
def test_pick_step_keeps_the_sheet_a_glance(duration, step):
    assert rt.pick_step(duration) == step
    assert duration / rt.pick_step(duration) <= rt.MAX_TILES + 1


def test_steps_for_video_converts_recorded_time_to_video_seconds():
    steps = rt.steps_for_video([
        {'step_number': 1, 'timestamp': 1010.0, 'execution_time_ms': 4000, 'success': True, 'message': 'Launch'},
        {'step_number': 2, 'timestamp': 1030.0, 'execution_time_ms': 10000, 'success': False, 'from_node': 'a', 'to_node': 'b'},
        {'step_number': 3, 'message': 'no timing'},
    ], 1000.0)
    assert [(s['number'], s['start'], s['end'], s['ok'], s['label']) for s in steps] == [
        (1, 6.0, 10.0, True, 'Launch'), (2, 20.0, 30.0, False, 'a → b')]
    assert rt.steps_for_video([{'timestamp': 1.0, 'execution_time_ms': 1}], 0.0) == []


@pytest.fixture
def video(tmp_path):
    p = tmp_path / 'run.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=65',
                    '-pix_fmt', 'yuv420p', str(p)], check=True)
    return str(p)


@needs_ffmpeg
def test_build_timeline_and_html(tmp_path, video):
    steps = [{'number': 1, 'start': 0.0, 'end': 20.0, 'ok': True, 'label': 'A <b>'},
             {'number': 2, 'start': 20.0, 'end': 50.0, 'ok': False, 'label': 'B'}]
    info = rt.build_video_timeline(video, str(tmp_path / 't.jpg'), steps)
    assert info['step_s'] == 1 and info['tiles'] == 66 or info['tiles'] in (65, 66)
    assert info['cols'] == 10 and info['rows'] == -(-info['tiles'] // 10)
    assert os.path.getsize(tmp_path / 't.jpg') == info['bytes'] < 400_000
    page = rt.build_timeline_html(info, 'https://example.com/v.mp4?sig=1&x=2', 'My <script>', rt.timeline_strings())
    assert 'data:image/jpeg;base64,' in page and 'v.mp4?sig=1&amp;x=2' in page
    assert 'My &lt;script&gt;' in page and 'My <script>' not in page
    # the step label reaches the page only as data (json), never as markup
    assert '"label": "A <b>"' in page.replace('<\\/', '</') or 'A <b>' not in page.split('<script>')[0]


@needs_ffmpeg
def test_missing_or_bad_video_returns_none(tmp_path):
    assert rt.build_video_timeline(str(tmp_path / 'nope.mp4'), str(tmp_path / 't.jpg')) is None
    bad = tmp_path / 'bad.mp4'
    bad.write_text('not a video')
    assert rt.build_video_timeline(str(bad), str(tmp_path / 't.jpg')) is None


def test_timeline_i18n_keys_in_every_language():
    strings = rt.timeline_strings()
    assert {'en', 'fr', 'de'} <= set(strings)
    keys = set(strings['en'])
    assert {'timeline.title', 'timeline.hint', 'timeline.ok', 'timeline.fail'} <= keys
    for code in ('fr', 'de'):
        assert set(strings[code]) == keys
