import importlib
import json
import sys
import types

import pytest


@pytest.fixture
def acc(monkeypatch, tmp_path):
    """The accumulator imports Linux-only inotify and sets thread env vars at import: import it for this test only,
    leaving sys.modules and the environment as they were (other tests import the monitors too)."""
    try:
        import inotify.adapters  # noqa: F401
    except ImportError:
        m = types.ModuleType('inotify')
        m.adapters = types.ModuleType('inotify.adapters')
        monkeypatch.setitem(sys.modules, 'inotify', m)
        monkeypatch.setitem(sys.modules, 'inotify.adapters', m.adapters)
    for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        monkeypatch.setenv(k, '1')
    name = 'backend_host.scripts.transcript_accumulator'
    monkeypatch.delitem(sys.modules, name, raising=False)
    try:
        mod = importlib.import_module(name)
    except ImportError as e:
        pytest.skip(f'accumulator dependencies missing: {e}')
    monkeypatch.setattr(mod, 'get_transcript_path', lambda folder: str(tmp_path))
    yield mod
    sys.modules.pop(name, None)


def test_merge_offsets_words_and_records_source(acc, tmp_path):
    seg = {'start': 1.0, 'end': 2.0, 'text': 'hallo', 'words': [{'word': 'hallo', 'start': 1.0, 'end': 1.5}]}
    acc.merge_minute_to_chunk('capture1', 3, 0, {'minute_offset': 2, 'language': 'German', 'transcript': 'hallo', 'segments': [seg],
                                                 'caption_source': 'machine', 'subtitle_frames': 0, 'subtitle_checked': 12}, has_mp3=False)
    acc.merge_minute_to_chunk('capture1', 3, 0, {'minute_offset': 3, 'language': 'unknown', 'transcript': '', 'segments': [],
                                                 'skip_reason': 'broadcaster_subtitles', 'caption_source': 'broadcaster'}, has_mp3=False)
    chunk = json.load(open(tmp_path / '3' / 'chunk_10min_0.json'))
    assert chunk['segments'][0]['words'][0]['start'] == 121.0
    assert chunk['minute_statuses']['2']['caption_source'] == 'machine'
    assert chunk['minute_statuses']['3']['caption_source'] == 'broadcaster'


def test_legacy_minute_has_no_caption_fields(acc, tmp_path):
    acc.merge_minute_to_chunk('capture1', 3, 1, {'minute_offset': 0, 'language': 'German', 'transcript': 'a',
                                                 'segments': [{'start': 0, 'end': 1, 'text': 'a'}]}, has_mp3=False)
    chunk = json.load(open(tmp_path / '3' / 'chunk_10min_1.json'))
    assert 'caption_source' not in chunk['minute_statuses']['0'] and 'words' not in chunk['segments'][0]
