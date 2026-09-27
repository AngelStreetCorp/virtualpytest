"""
analyze_screen_for_action on web picks the element the intent names (BUG-0173).

Web dumps carry no xpath, and fields often have no id or text (YouTube's search box is
`input.ytSearchboxComponentInput` with name/placeholder only), so the scorer found nothing.
And a web id was accepted regardless of intent, so any unique id on the page won.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from shared.src.lib.utils.selector_scoring import find_best_selector  # noqa: E402
    from backend_server.src.mcp.tools.screen_analysis_tools import ScreenAnalysisTools  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

SEARCH_BOX = {'id': None, 'selector': 'css=input.ytSearchboxComponentInput.yt-searchbox-input',
              'tagName': 'input', 'textContent': '', 'name': 'search_query',
              'placeholder': 'Search', 'role': 'combobox', 'type': 'text'}
PAGE = [
    {'id': 'guide-button', 'selector': 'css=#guide-button', 'tagName': 'button', 'textContent': ''},
    {'id': 'logo', 'selector': 'css=#logo', 'tagName': 'a', 'textContent': 'YouTube Home'},
    SEARCH_BOX,
    {'id': 'avatar-btn', 'selector': 'css=#avatar-btn', 'tagName': 'button', 'textContent': 'Sign in'},
]


def test_search_box_found_by_its_describing_attributes():
    result = find_best_selector([SEARCH_BOX], 'web', context_label='search field')
    assert result['selector_type'] == 'css'
    assert result['selector_value'] == SEARCH_BOX['selector']


def test_unrelated_unique_ids_do_not_win():
    result = find_best_selector(PAGE, 'web', context_label='search field')
    assert result['element'] is SEARCH_BOX


def test_web_id_still_wins_when_it_matches_the_intent():
    result = find_best_selector(PAGE, 'web', context_label='logo')
    assert result['selector_type'] == 'id'
    assert result['selector_value'] == 'logo'


def test_analyze_returns_runnable_actions_in_its_text():
    result = ScreenAnalysisTools().analyze_screen_for_action(
        {'elements': PAGE, 'intent': 'search field', 'platform': 'web'})
    assert result['isError'] is False
    lines = result['content'][0]['text'].split('\n')
    action = json.loads(lines[1].split('action: ', 1)[1])
    assert action == {'command': 'click_element',
                      'params': {'element_id': SEARCH_BOX['selector'], 'wait_time': 1000}}
    typing = json.loads(lines[2].split('to type into it: ', 1)[1])
    assert typing['command'] == 'input_text'
    assert typing['params']['selector'] == SEARCH_BOX['selector']


def test_analyze_never_emits_click_element_by_id_on_web():
    result = ScreenAnalysisTools().analyze_screen_for_action(
        {'elements': PAGE, 'intent': 'logo', 'platform': 'web'})
    assert result['command'] == 'click_element'
    assert result['params']['element_id'] == '[id="logo"]'
