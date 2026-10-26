import json

from backend_host.src.lib.utils import caption_translate as ct
from backend_host.src.lib.utils.caption_vtt import build_vtt


def seg(s, e, text):
    return {'start': s, 'end': e, 'text': text, 'words': [{'word': text.split()[0], 'start': s, 'end': e}]}


def write_chunk(tmp_path, segments, lang='de'):
    p = tmp_path / 'chunk_10min_0.json'
    p.write_text(json.dumps({'language': lang, 'segments': segments, 'transcript': 'x', 'minute_statuses': {}}))
    return str(p)


class FakeLLM:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, prompt):
        self.calls.append(prompt)
        if self.fail:
            return {'success': False, 'error': 'down'}
        texts = json.loads(prompt[prompt.index('['):])
        return {'success': True, 'content': json.dumps([f'FR:{t}' for t in texts]), 'model': 'm',
                'usage': {'prompt_tokens': 50, 'completion_tokens': 20}}


def test_target_languages_skip_source_and_env():
    assert ct.target_languages('de', {}) == ['en', 'fr']
    assert ct.target_languages('fr', {'CAPTION_TRANSLATE_LANGS': 'en, fr ,xx'}) == ['en']
    assert ct.target_languages('de', {'CAPTION_TRANSLATE_LANGS': ''}) == []


def test_parse_answer_requires_exact_count():
    assert ct.parse_answer('Sure: ["a", "b"]', 2) == ['a', 'b']
    assert ct.parse_answer('["a"]', 2) is None
    assert ct.parse_answer('no json', 1) is None
    assert ct.parse_answer('[1, 2]', 2) is None


def test_cue_mapping_keeps_source_timing(tmp_path):
    path = write_chunk(tmp_path, [seg(1.0, 3.5, 'Guten Abend'), seg(4.0, 6.0, 'meine Damen')])
    llm = FakeLLM()
    ct.translate_chunk(path, 'fr', llm)
    out = json.loads((tmp_path / 'chunk_10min_0_fr.json').read_text())
    assert [(s['start'], s['end'], s['text']) for s in out['segments']] == [(1.0, 3.5, 'FR:Guten Abend'), (4.0, 6.0, 'FR:meine Damen')]
    assert out['machine_translated'] and out['source_language'] == 'de' and out['translated_to'] == 'fr'
    assert out['translated_minutes']['0']['tokens_in'] == 50
    vtt = build_vtt(out, 'de')
    assert '[auto] FR:Guten' in vtt and 'machine-translated' in vtt and '00:00:01.400 -->' in vtt


def test_one_call_per_minute_and_cached(tmp_path):
    path = write_chunk(tmp_path, [seg(1, 2, 'a'), seg(5, 6, 'b'), seg(65, 66, 'c')])
    llm = FakeLLM()
    r1 = ct.translate_chunk(path, 'fr', llm)
    assert r1['translated'] == [0, 1] and len(llm.calls) == 2
    r2 = ct.translate_chunk(path, 'fr', llm)
    assert r2['translated'] == [] and r2['cached'] == 2 and len(llm.calls) == 2   # never re-translated


def test_new_minute_translates_only_that_minute(tmp_path):
    path = write_chunk(tmp_path, [seg(1, 2, 'a')])
    llm = FakeLLM()
    ct.translate_chunk(path, 'fr', llm)
    write_chunk(tmp_path, [seg(1, 2, 'a'), seg(70, 72, 'zwei')])
    r = ct.translate_chunk(path, 'fr', llm)
    assert r['translated'] == [1] and len(llm.calls) == 2


def test_failure_keeps_source_text_flagged_and_retries_later(tmp_path):
    path = write_chunk(tmp_path, [seg(1, 2, 'Hallo Welt')])
    r = ct.translate_chunk(path, 'fr', FakeLLM(fail=True))
    assert r['failed'] == [0]
    out = json.loads((tmp_path / 'chunk_10min_0_fr.json').read_text())
    assert out['segments'][0]['untranslated'] and out['segments'][0]['text'] == 'Hallo Welt'
    assert '[auto de] Hallo' in build_vtt(out, 'de')
    llm = FakeLLM()
    assert ct.translate_chunk(path, 'fr', llm)['translated'] == [0]
    assert not json.loads((tmp_path / 'chunk_10min_0_fr.json').read_text())['segments'][0].get('untranslated')


def test_same_language_makes_no_call(tmp_path):
    path = write_chunk(tmp_path, [seg(1, 2, 'a')], lang='fr')
    llm = FakeLLM()
    assert ct.translate_chunk(path, 'fr', llm)['skipped'] == 'same language' and not llm.calls
    assert not (tmp_path / 'chunk_10min_0_fr.json').exists()


def test_language_name_or_code():
    assert ct.lang_code('German') == 'de' and ct.lang_code('fr') == 'fr'
    assert ct.target_languages('German', {}) == ['en', 'fr']


def test_source_handed_back_is_rejected_then_retried(tmp_path):
    path = write_chunk(tmp_path, [seg(1, 2, 'Guten Abend meine Damen'), seg(3, 4, 'und Herren im Saal')])
    answers = iter([lambda t: t, lambda t: [f'FR:{x}' for x in t]])

    def llm(prompt):
        texts = json.loads(prompt[prompt.index('['):])
        return {'success': True, 'content': json.dumps(next(answers)(texts)), 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}

    r = ct.translate_chunk(path, 'fr', llm)
    assert r['translated'] == [0]
    out = json.loads((tmp_path / 'chunk_10min_0_fr.json').read_text())
    assert out['translated_minutes']['0']['tokens_in'] == 20 and out['segments'][0]['text'].startswith('FR:')


def test_source_handed_back_twice_is_a_failure(tmp_path):
    path = write_chunk(tmp_path, [seg(1, 2, 'Guten Abend meine Damen')])
    llm = lambda p: {'success': True, 'content': p[p.index('['):], 'usage': {}}
    assert ct.translate_chunk(path, 'fr', llm)['failed'] == [0]


def test_failing_minute_is_given_up_after_three_tries(tmp_path):
    path = write_chunk(tmp_path, [seg(1, 2, 'Hallo Welt')])
    llm = FakeLLM(fail=True)
    for _ in range(5):
        ct.translate_chunk(path, 'fr', llm)
    assert len(llm.calls) == ct.MAX_MINUTE_TRIES
