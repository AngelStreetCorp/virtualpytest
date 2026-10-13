"""TASK-50 subtitle QA: SRT, sampler, verdicts per issue type, and OCR on synthetic frames."""
import os
import shutil

import cv2
import numpy as np
import pytest

from shared.src.lib.subtitle_qa import judge
from shared.src.lib.subtitle_qa.judge import OcrResult, judge_sample, judge_timing
from shared.src.lib.subtitle_qa.sampler import plan_samples
from shared.src.lib.subtitle_qa.srt import Cue, normalize, parse_srt

ASSETS = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'subtitle_qa', 'assets')

CUES = [
    Cue(1, 10.0, 12.0, 'Hello there, Celia.'),
    Cue(2, 13.0, 16.0, "Look, we have to follow\nour passions; it's time."),
    Cue(3, 20.0, 22.0, 'Memory overwrite, 90%.'),
]


def ocr(text, conf=90, contrast=8.0, lang=None):
    n = len(text.split())
    return OcrResult(text, n, conf, contrast if text else None, lang)


def test_parse_real_srt():
    cues = parse_srt(open(os.path.join(ASSETS, 'TOS-en.srt'), encoding='utf-8-sig').read())
    assert len(cues) == 76 and cues[0].start == 23.0 and cues[0].end == 24.5
    assert cues[2].text == "...you have your robotics, and I\njust want to be awesome in space."
    assert normalize("You're a <i>jerk</i>, Thom!") == "you're a jerk thom"


def test_sampler_budget_and_density():
    cues = parse_srt(open(os.path.join(ASSETS, 'TOS-en.srt'), encoding='utf-8-sig').read())
    dur = 734.0
    s = plan_samples(cues, dur)
    ts = [x.t for x in s]
    assert len(s) / dur <= 1.0
    for c in cues:  # >= 4 samples within +/-1 s of every cue start
        assert sum(1 for t in ts if abs(t - c.start) <= 1.0) >= 4
    gap_far = [t for t in ts if all(abs(t - c.start) > 6 and abs(t - c.end) > 6 for c in cues)]
    assert gap_far  # sparse coverage exists where nothing happens


def test_ok_present_and_absent():
    assert judge_sample(11.0, CUES, ocr('Hello there, Celia.')).ok
    assert judge_sample(18.0, CUES, ocr('')).ok
    assert judge_sample(10.1, CUES, ocr('')).ok          # cue edge: either state accepted


def test_missing_subtitle():
    v = judge_sample(11.0, CUES, ocr(''))
    assert v.issue == judge.MISSING and v.state == 'present'


def test_unexpected_subtitle():
    v = judge_sample(18.0, CUES, ocr('Totally unrelated words here'))
    assert v.issue == judge.UNEXPECTED


def test_stuck_subtitle():
    v = judge_sample(18.0, CUES, ocr("Look, we have to follow our passions; it's time."))
    assert v.issue == judge.STUCK and v.matched_cue == 2
    v = judge_sample(14.5, CUES, ocr('Hello there, Celia.'))   # old cue over a new one
    assert v.issue == judge.STUCK and v.matched_cue == 1


def test_wrong_text_with_word_diff():
    v = judge_sample(11.0, CUES, ocr('Goodbye over there, Marta.'))
    assert v.issue == judge.WRONG_TEXT and v.cer > judge.CER_OK and 'hello' in v.missing_words


def test_truncated_line():
    v = judge_sample(14.5, CUES, ocr('Look, we have to follow'))
    assert v.issue == judge.TRUNCATED


def test_wrong_language():
    v = judge_sample(14.5, CUES, ocr('Schau, wir muessen unseren Leidenschaften folgen', lang='de'), expected_lang='en')
    assert v.issue == judge.WRONG_LANG


def test_overlap():
    v = judge_sample(14.5, CUES, ocr("Hello there, Celia. Look, we have to follow our passions; it's time."))
    assert v.issue == judge.OVERLAP


def test_unreadable_contrast_flag():
    v = judge_sample(11.0, CUES, ocr('Hello there, Celia.', contrast=1.4))
    assert not v.ok and judge.CONTRAST in v.flags


def test_picture_text_wall_is_not_a_subtitle():
    assert judge_sample(18.0, CUES, ocr(' '.join(['Name'] * 40))).ok


def test_timing_late_early_ok():
    c = CUES[0]
    assert judge_timing(c, 10.25, 11.9, 10.1).issue is None
    late = judge_timing(c, 12.0, 12.0, 10.1)
    assert late.issue == judge.LATE and late.lag_audio > 1.0
    early = judge_timing(c, 8.0, 9.9, 10.1)
    assert early.issue == judge.EARLY
    assert judge_timing(c, 11.5, 12, None).issue == judge.LATE   # SRT basis without audio


def _frame(bg, text, outline):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new('RGB', (1280, 720), (bg, bg, bg))
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 34)
    kw = {'stroke_width': 2, 'stroke_fill': (0, 0, 0)} if outline else {}
    ImageDraw.Draw(im).text((330, 590), text, font=font, fill=(255, 255, 255), **kw)
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


@pytest.mark.skipif(shutil.which('tesseract') is None or not os.path.exists('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                    reason='tesseract or DejaVu font not installed')
def test_ocr_on_synthetic_frame():
    from shared.src.lib.subtitle_qa.ocr import read_subtitle
    r = read_subtitle(_frame(90, 'Look Celia, we have to follow', True), 'en')
    assert judge.cer('Look Celia, we have to follow', r.text) < 0.2
    assert r.contrast and r.contrast > 3
    assert read_subtitle(np.full((720, 1280, 3), 90, np.uint8), 'en').text == ''
    # white text with no outline on a light background: text read at best, contrast below 3:1
    low = read_subtitle(_frame(235, 'Look Celia, we have to follow', False), 'en')
    assert low.contrast is None or low.contrast < 3


def _row(t, text, conf=90):
    return {'t': t, 'ocr': text, 'verdict': judge_sample(t, CUES, ocr(text, conf)).__dict__}


def test_noise_cleared_only_when_other_samples_read_the_cue():
    noisy = [_row(10.5, 'Hello there, Celia.'), _row(11.0, 'Hlo thre'), _row(11.5, 'Hello there, Celia.')]
    assert judge.downgrade_transient(noisy, CUES) == 1 and noisy[1]['verdict']['issue'] is None
    broken = [_row(10.5, 'Goodbye Marta'), _row(11.0, 'Goodbye Marta'), _row(11.5, 'Goodbye Marta')]
    assert judge.downgrade_transient(broken, CUES) == 0 and broken[0]['verdict']['issue'] == judge.WRONG_TEXT


def test_edge_tolerance_for_device_capture_jitter():
    old_cue_text = ocr('Hello there, Celia.')
    assert judge_sample(12.6, CUES, old_cue_text).issue == judge.STUCK          # strict (local): 0.6 s after the end
    assert judge_sample(12.6, CUES, old_cue_text, edge=1.0).ok                  # device mode: inside the jitter window
    assert judge_sample(14.0, CUES, ocr('Hello there, Celia.'), edge=1.0).issue == judge.STUCK   # 2 s late is still caught


def test_script_restart_detection(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('subtitle_qa_script', os.path.join(os.path.dirname(__file__), '..', '..', 'test_scripts', 'subtitle_qa.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = 1_000_000.0
    times = [base + i * 0.2 for i in range(10)] + [base + 1.8 + 1.4 + i * 0.2 for i in range(5)]  # 1.4 s gap = restart
    for i, mt in enumerate(times):
        f = tmp_path / f'capture_{i:09d}.jpg'
        f.write_bytes(b'x')
        os.utime(f, (mt, mt))
    assert mod.wait_for_restart(str(tmp_path), since=base + 1.0, timeout=1) == pytest.approx(base + 3.2)
    assert mod.wait_for_restart(str(tmp_path), since=base + 4.0, timeout=0.3) is None   # no restart after `since`


def test_alignment_counts_noisy_reads_of_the_right_cue():
    from shared.src.lib.subtitle_qa import pipeline
    noisy_right = [_row(11.0, 'Helo thre, Cela.'), _row(14.5, "Lok, we hav to folow our pasions")]
    assert pipeline.summarize(noisy_right, [], CUES)['alignment_ok']
    shifted = [_row(11.0, "Look, we have to follow our passions; it's time."), _row(14.5, 'Memory overwrite, 90%.')]
    assert not pipeline.summarize(shifted, [], CUES)['alignment_ok']


def test_source_check_separates_device_issues_from_ocr_limits(monkeypatch):
    from shared.src.lib.subtitle_qa import pipeline, report
    rows = [_row(11.0, 'Goodbye Marta'),            # device shows wrong text, source reads fine -> stays
            _row(14.5, 'Lok w hav'),                # source reads equally badly -> OCR limit
            _row(18.0, 'Netherlands Film Fund')]    # text outside cues, also in the source -> picture text
    source = {11.0: 'Hello there, Celia.', 14.5: 'Lok w hav', 18.0: 'Netherlands Film Fund'}
    monkeypatch.setattr(pipeline, 'read_subtitle', lambda img, lang: ocr(source[img]))
    monkeypatch.setattr(report, 'band_b64', lambda img: '')
    out = pipeline.check_against_source(rows, lambda t: t, CUES, 'en')
    assert out == {'checked': 3, 'source_ok': 1, 'ocr_limit': 1, 'in_source': 1, 'no_frame': 0}
    assert rows[0]['verdict']['issue'] == judge.WRONG_TEXT
    assert rows[1]['verdict']['issue'] is None and rows[1]['verdict']['cleared'] == judge.WRONG_TEXT
    assert rows[2]['verdict']['issue'] is None and rows[2]['ref_kind'] == 'in_source'
