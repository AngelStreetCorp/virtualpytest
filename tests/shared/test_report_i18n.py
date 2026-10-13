"""Unit tests for report i18n (TASK-52): catalogs, t()/tx(), the generated page and snapshots."""

import json
import re
from html import unescape

import pytest

from shared.src.lib.i18n import report_i18n as i18n
from shared.src.lib.utils import report_snapshot_builder as builder
from shared.src.lib.utils.report_generation_utils import (
    generate_campaign_orchestrator_report,
    generate_validation_report,
)

pytestmark = pytest.mark.unit

SCRIPT_STRINGS = {
    '🎯 Result: {r}': {'fr': '🎯 Résultat : {r}', 'de': '🎯 Ergebnis: {r}'},
    'Captured {saved} of {total} sample frames': {'fr': '{saved} images capturées sur {total}'},
    'Navigation step: {a} → {b}': {'fr': 'SCRIPT {a} → {b}'},
}


def _span_parts(markup):
    key = re.search(r'data-i18n="([^"]*)"', markup).group(1)
    args_match = re.search(r"data-i18n-args='([^']*)'", markup)
    args = json.loads(unescape(args_match.group(1))) if args_match else {}
    text = re.search(r'>(.*)</span>$', markup, re.S).group(1)
    return key, args, text


def _catalog_block(page):
    match = re.search(r'<script type="application/json" id="vpt-i18n">(.*?)</script>', page, re.S)
    assert match, 'catalog block missing'
    return json.loads(match.group(1).replace('<\\/', '</'))


# ---- platform files --------------------------------------------------------------------------

def test_every_language_has_every_english_key_and_no_extra():
    strings = i18n.load_platform_strings()
    assert {'en', 'fr', 'de'} <= set(strings)
    english = set(strings['en'])
    for code, table in strings.items():
        assert set(table) == english, (code, sorted(set(table) ^ english))
        assert table['_name']


def test_placeholders_match_english():
    strings = i18n.load_platform_strings()
    for code, table in strings.items():
        for key, text in table.items():
            assert sorted(re.findall(r'\{(\w+)\}', text)) == sorted(re.findall(r'\{(\w+)\}', strings['en'][key])), (code, key)


def test_available_languages_order_and_names():
    assert list(i18n.available_languages())[:3] == ['en', 'fr', 'de']
    assert i18n.available_languages()['fr'] == 'Français'


# ---- t() -------------------------------------------------------------------------------------

def test_t_without_catalog_is_plain_english():
    assert i18n.t('summary.status') == 'Status:'
    assert i18n.t('summary.steps', n=2, total=3) == '2/3 steps'
    assert '<span' not in i18n.t('summary.steps', n='<b>', total=3)
    assert '&lt;b&gt;' in i18n.t('summary.steps', n='<b>', total=3)


def test_t_with_catalog_makes_span_and_records_key():
    catalog = i18n.ReportCatalog()
    with i18n.use_report_catalog(catalog):
        markup = i18n.t('steps.title', passed=1, total='<2>')
    key, args, text = _span_parts(markup)
    assert key == 'steps.title'
    assert args == {'passed': '1', 'total': '<2>'}
    assert text == 'Test Steps (1/&lt;2&gt; passed)'
    assert "'" not in re.search(r"data-i18n-args='(.*?)'>", markup).group(1)
    assert 'steps.title' in catalog.used_platform


def test_t_missing_french_key_falls_back_to_english_in_page(monkeypatch):
    strings = i18n.load_platform_strings()
    trimmed = {**strings, 'fr': {k: v for k, v in strings['fr'].items() if k != 'summary.status'}}
    monkeypatch.setattr(i18n, 'load_platform_strings', lambda: trimmed)
    catalog = i18n.ReportCatalog()
    with i18n.use_report_catalog(catalog):
        i18n.t('summary.status')
        i18n.t('summary.host')
    block = json.loads(catalog.script_tag().split('>', 1)[1].rsplit('</script>', 1)[0])
    assert 'summary.status' not in block['strings']['fr']  # JS falls back to en
    assert block['strings']['en']['summary.status'] == 'Status:'
    assert block['strings']['fr']['summary.host'] == 'Hôte :'


def test_context_is_restored():
    with i18n.use_report_catalog(i18n.ReportCatalog()):
        assert i18n.active_catalog() is not None
    assert i18n.active_catalog() is None


# ---- tx() ------------------------------------------------------------------------------------

def test_tx_no_catalog_escapes_and_keeps_markup():
    assert i18n.tx('a & b') == 'a &amp; b'
    assert i18n.tx('<b>x</b>') == '<b>x</b>'
    assert i18n.tx('<b>x</b>', escape_markup=True) == '&lt;b&gt;x&lt;/b&gt;'
    assert i18n.tx(None) == ''


def test_tx_platform_msg_template_with_args():
    with i18n.use_report_catalog(i18n.ReportCatalog()):
        markup = i18n.tx('Navigation step: Home → Settings')
    key, args, text = _span_parts(markup)
    assert key == 'msg.nav_step'
    assert args == {'from': 'Home', 'to': 'Settings'}
    assert text == 'Navigation step: Home → Settings'


def test_tx_repeated_placeholder():
    with i18n.use_report_catalog(i18n.ReportCatalog()):
        key, args, _ = _span_parts(i18n.tx('Zap iteration 2: press_key (2/5)'))
    assert key == 'msg.zap_iteration'
    assert args['iteration'] == '2' and args['max'] == '5' and args['command'] == 'press_key'


def test_tx_no_match_is_escaped_text():
    with i18n.use_report_catalog(i18n.ReportCatalog(SCRIPT_STRINGS)):
        assert i18n.tx('Something <nobody> wrote') == 'Something <nobody> wrote'  # markup untouched
        assert i18n.tx('Unknown & free text') == 'Unknown &amp; free text'


def test_tx_script_template_beats_platform_and_is_namespaced():
    catalog = i18n.ReportCatalog(SCRIPT_STRINGS)
    with i18n.use_report_catalog(catalog):
        key, args, _ = _span_parts(i18n.tx('Navigation step: A → B'))
    assert key == 's:Navigation step: {a} → {b}'
    assert args == {'a': 'A', 'b': 'B'}


def test_tx_most_specific_template_wins():
    catalog = i18n.ReportCatalog({
        'Error: {what}': {'fr': 'Erreur : {what}'},
        'Error: timeout after {s} seconds': {'fr': 'Erreur : délai de {s} secondes'},
    })
    with i18n.use_report_catalog(catalog):
        key, args, _ = _span_parts(i18n.tx('Error: timeout after 5 seconds'))
        key2, _, _ = _span_parts(i18n.tx('Error: disk full'))
    assert key == 's:Error: timeout after {s} seconds' and args == {'s': '5'}
    assert key2 == 's:Error: {what}'


def test_tx_is_full_match_and_single_line():
    catalog = i18n.ReportCatalog({'Hello {name}': {'fr': 'Bonjour {name}'}})
    with i18n.use_report_catalog(catalog):
        assert 'data-i18n' not in i18n.tx('Oh Hello world')
        assert 'data-i18n' not in i18n.tx('Hello a\nb')
        assert 'data-i18n' in i18n.tx('Hello world')


def test_tx_lines_translates_each_line():
    catalog = i18n.ReportCatalog(SCRIPT_STRINGS)
    with i18n.use_report_catalog(catalog):
        out = i18n.tx_lines('🎯 Result: SUCCESS\nplain line')
    first, second = out.split('\n')
    assert _span_parts(first)[0] == 's:🎯 Result: {r}'
    assert second == 'plain line'


def test_template_with_only_placeholder_never_matches():
    with i18n.use_report_catalog(i18n.ReportCatalog({'{x}': {'fr': '{x}'}})):
        assert 'data-i18n' not in i18n.tx('anything')


def test_script_tag_only_used_keys_and_script_languages():
    catalog = i18n.ReportCatalog(SCRIPT_STRINGS)
    with i18n.use_report_catalog(catalog):
        i18n.t('summary.status')
        i18n.tx('Captured 1 of 2 sample frames')
        i18n.tx('Not in any file')
    tag = catalog.script_tag()
    assert '</' not in tag.split('>', 1)[1].rsplit('</script>', 1)[0]
    block = json.loads(tag.split('>', 1)[1].rsplit('</script>', 1)[0].replace('<\\/', '</'))
    assert block['default'] == 'en'
    assert block['languages'] == {'en': 'English', 'fr': 'Français', 'de': 'Deutsch'}
    skey = 's:Captured {saved} of {total} sample frames'
    assert block['strings']['en'][skey] == 'Captured {saved} of {total} sample frames'
    assert block['strings']['fr'][skey] == '{saved} images capturées sur {total}'
    assert skey not in block['strings']['de']
    assert set(block['strings']['en']) == {'summary.status', skey}


def test_script_file_loading_is_defensive(tmp_path):
    good = tmp_path / 'x.i18n.json'
    good.write_text(json.dumps({'A {b}': {'fr': 'C {b}'}, '_comment': 'x', 'bad': 'nope'}), encoding='utf-8')
    assert i18n.load_script_strings(str(good)) == {'A {b}': {'fr': 'C {b}'}}
    broken = tmp_path / 'y.i18n.json'
    broken.write_text('{not json', encoding='utf-8')
    assert i18n.load_script_strings(str(broken)) == {}
    assert i18n.load_script_strings(str(tmp_path / 'missing.json')) == {}
    assert i18n.load_script_strings(None) == {}
    assert i18n.script_i18n_path('definitely_not_a_script.py') == ''
    assert i18n.script_i18n_path('') == ''


# ---- generated report ------------------------------------------------------------------------

def _report_data(**extra):
    data = {
        'script_name': 'goto.py',
        'device_info': {'device_name': 'stb1', 'device_model': 'model_x'},
        'host_info': {'host_name': 'host-a'},
        'execution_time': 5000,
        'success': False,
        'start_time': '20261005101500',
        'end_time': '20261005101505',
        'execution_summary': '🎯 Result: FAILURE\nPlain line',
        'error_msg': 'Verification failed',
        'step_results': [
            {'step_number': 1, 'success': True, 'step_category': 'navigation', 'from_node': 'A', 'to_node': 'B',
             'message': 'Navigation step: A → B', 'execution_time_ms': 800},
            {'step_number': 2, 'success': False, 'step_category': 'testcase_block', 'from_node': 'A', 'to_node': 'B',
             'message': 'Navigate to: home', 'execution_time_ms': 900, 'error': 'Verification failed',
             'verification_results': [{'success': False, 'message': 'Verification failed', 'verification_type': 'text'}]},
        ],
        'i18n_script_catalog': SCRIPT_STRINGS,
    }
    data.update(extra)
    return data


def test_generated_report_has_catalog_switcher_and_translatable_spans():
    page = generate_validation_report(_report_data())
    assert 'id="lang-switch"' in page and 'virtualpytest:language' in page
    block = _catalog_block(page)
    assert list(block['languages']) == ['en', 'fr', 'de']
    # every data-i18n key in the page has an English string embedded
    keys = set(re.findall(r'data-i18n="([^"]*)"', page))
    assert 'summary.status' in keys and 'msg.navigate_to' in keys and 's:Navigation step: {a} → {b}' in keys and 's:🎯 Result: {r}' in keys
    assert keys <= set(block['strings']['en'])
    assert block['strings']['fr']['summary.status'] == 'Statut :'
    # English text is in the page itself, title stays English without spans
    assert re.search(r'<title>Validation Report - goto.py</title>', page)
    assert '>Status:</span>' in page
    # unused keys are not embedded
    assert 'campaign.overview' not in block['strings']['en']
    # no str.format placeholder leaked
    assert '{success_steps_text}' not in page and '{passed_steps}' not in page


def test_report_without_script_catalog_still_works():
    data = _report_data()
    data['i18n_script_catalog'] = {}
    page = generate_validation_report(data)
    assert 'id="vpt-i18n"' in page
    assert 's:' not in ''.join(_catalog_block(page)['strings']['en'])


def test_campaign_report_has_switcher():
    page = generate_campaign_orchestrator_report({
        'campaign_name': 'c', 'script_executions': [{'script_name': 'a.py', 'success': True, 'execution_time_ms': 10}],
    })
    block = _catalog_block(page)
    assert 'campaign.title' in block['strings']['fr']
    assert 'id="lang-switch"' in page


def test_catalog_survives_snapshot_rewrite():
    page = generate_validation_report(_report_data())
    before = _catalog_block(page)
    classifier = builder._Classifier('virtualpytest', ['platform.example.com'], True, 'script-reports/model_x/run_1/')
    out, _ = builder.rewrite_report_html(page, classifier)
    assert _catalog_block(out) == before
    assert 'id="lang-switch"' in out and 'LanguageManager' in out


# ---- testcase messages and in-source translations (virtual scripts) -------------------------

def test_testcase_block_and_loop_tag_translate():
    catalog = i18n.build_catalog(script_strings={})
    with i18n.use_report_catalog(catalog):
        key, args, _ = _span_parts(i18n.tx('Block: 3 action(s)'))
        assert key == 'msg.block_actions' and args == {'count': '3'}
        tagged = i18n.tx('[2/5] Standard block: press_key')
    assert tagged.startswith('[2/5] <span data-i18n="msg.standard_block"')
    assert _span_parts(tagged[len('[2/5] '):])[1] == {'command': 'press_key'}


def test_inline_i18n_merges_over_file(tmp_path):
    """`main._i18n` (script_i18n_inline) wins over <script>.i18n.json; a virtual script has only the inline dict."""
    from shared.src.lib.utils.report_generation_utils import _build_report_catalog
    path = tmp_path / 'x.i18n.json'
    path.write_text(json.dumps({'Hello {n}': {'fr': 'FILE {n}'}, 'Bye': {'fr': 'Au revoir'}}), encoding='utf-8')
    catalog = _build_report_catalog({'script_name': 'x.py', 'script_i18n_path': str(path),
                                     'script_i18n_inline': {'Hello {n}': {'fr': 'INLINE {n}'}}})
    assert catalog.script['Hello {n}']['fr'] == 'INLINE {n}'
    assert catalog.script['Bye']['fr'] == 'Au revoir'


def test_virtual_script_report_uses_inline_strings():
    page = generate_validation_report(_report_data(
        script_name='my_virtual_script.py', i18n_script_catalog=None,
        script_i18n_inline={'Captured {saved} of {total} sample frames': {'de': '{saved} von {total} erfasst'}},
        step_results=[{'step_number': 1, 'success': True, 'message': 'Captured 9 of 10 sample frames',
                       'execution_time_ms': 1}],
    ))
    strings = _catalog_block(page)['strings']
    assert strings['de']['s:Captured {saved} of {total} sample frames'] == '{saved} von {total} erfasst'


def test_theme_switch_is_icons_with_translated_tooltips():
    page = generate_validation_report(_report_data())
    for mode in ('light', 'dark', 'system'):
        option = re.search(rf'<div class="theme-option"[^>]*data-theme="{mode}"[^>]*>(.*?)</div>', page, re.S)
        assert option and '<svg' in option.group(1) and f'data-i18n-title="theme.{mode}"' in option.group(0)
    assert 'theme.system' in _catalog_block(page)['strings']['fr']


def test_summary_emoji_drawn_as_icons_in_text_only():
    from shared.src.lib.utils.report_icons import iconify_html
    page = generate_validation_report(_report_data(execution_summary='📊 Checks: 4 ✅ 4 ❌ 0\n⚠️ slow\n🦄 kept\n🎯 Result: SUCCESS'))
    summary = re.search(r'<pre class="summary-text">(.*?)</pre>', page, re.S).group(1)
    assert '✅' not in re.sub(r'<[^>]*>', '', summary)  # drawn, not printed
    assert 'tone-ok' in summary and 'tone-fail' in summary and 'tone-warn' in summary
    assert '🦄 kept' in summary  # unmapped emoji stays
    # the catalog keeps the script's emoji keys; the page script redraws icons after a switch
    assert 's:🎯 Result: {r}' in _catalog_block(page)['strings']['en']
    assert 'id="vpt-emoji-icons"' in page
    # attributes and scripts are never touched
    assert iconify_html('<p title="✅">✅</p><script>"✅"</script>').startswith('<p title="✅"><svg')
    assert '<script>"✅"</script>' in iconify_html('<p>x</p><script>"✅"</script>')
