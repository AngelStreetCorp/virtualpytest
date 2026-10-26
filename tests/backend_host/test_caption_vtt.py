import re

from backend_host.src.lib.utils.caption_vtt import (CAPTION_SHIFT_S, build_cues, build_vtt, decide_subtitle_minute,
                                                    minute_coverage)


def w(word, s, e):
    return {'word': word, 'start': s, 'end': e}


def test_empty_chunk_is_header_only():
    assert build_vtt(None).startswith('WEBVTT')
    assert '-->' not in build_vtt({'segments': []})


def test_shift_marker_and_limits():
    words = [w(f'wort{i}', 10 + i * 0.5, 10.4 + i * 0.5) for i in range(40)]
    cues = build_cues([{'start': 10, 'end': 30, 'text': 'x', 'words': words}])
    assert cues[0][0] == 10 + CAPTION_SHIFT_S
    for s, e, lines in cues:
        assert 1.0 <= e - s <= 6.5
        assert len(lines) <= 2 and all(len(l) <= 42 for l in lines)
    assert cues[0][2][0].startswith('[auto] ')


def test_proportional_fallback_without_words():
    cues = build_cues([{'start': 0, 'end': 4, 'text': 'hallo welt wie geht es'}])
    assert cues and cues[0][0] == CAPTION_SHIFT_S


def test_vtt_timestamp_format():
    vtt = build_vtt({'segments': [{'start': 61, 'end': 63, 'text': 'hi', 'words': [w('hi', 61, 62)]}]})
    assert re.search(r'00:01:01\.400 --> 00:01:02\.\d{3}\n\[auto\] hi', vtt)


def test_sentence_end_splits():
    cues = build_cues([{'start': 0, 'end': 5, 'text': '', 'words': [w('Ja.', 0, 0.5), w('Nein', 0.6, 1.0)]}])
    assert len(cues) == 2


def test_coverage_and_subtitle_minute():
    chunk = {'minute_statuses': {'0': {'processed': True, 'has_audio': True},
                                '1': {'processed': True, 'caption_source': 'broadcaster'}}}
    cov = minute_coverage(chunk)
    assert cov[0]['caption_source'] == 'machine' and cov[1]['caption_source'] == 'broadcaster' and not cov[2]['ready']
    assert decide_subtitle_minute([True] * 6 + [False] * 2 + [None] * 9) == (True, 6, 8)
    assert decide_subtitle_minute([True] * 2)[0] is False      # too few frames looked at
    assert decide_subtitle_minute([False] * 10)[0] is False


def test_subtitle_flags_for_window(tmp_path):
    import json
    import os
    from backend_host.src.lib.utils.caption_vtt import subtitle_flags_for_window
    for i in range(8):
        p = tmp_path / f'capture_{i:04d}.json'
        p.write_text(json.dumps({'subtitle_analysis': {'has_subtitles': True}} if i < 6 else {'subtitle_analysis': {'skipped': True}}))
        os.utime(p, (1000 + i, 1000 + i))
    (tmp_path / 'capture_9999.json').write_text('{}')
    os.utime(tmp_path / 'capture_9999.json', (5000, 5000))      # outside the window
    flags = subtitle_flags_for_window(str(tmp_path), 999, 1010)
    assert flags == [True] * 6 + [None, None]
    assert decide_subtitle_minute(flags)[0] is True
