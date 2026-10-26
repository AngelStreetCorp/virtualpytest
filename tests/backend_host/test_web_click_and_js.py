"""
tests/backend_host/test_web_click_and_js.py — web controller fixes from the TASK-135 turn-waste analysis.

- click_element(text) tried 5 native selectors with a 3 s click timeout each before the DOM-dump fallback:
  15 s lost per click on a Flutter page, where none of them match. Absent selectors are now skipped by count.
- click_element took no `xpath` param although the tool description offers it ("element_id parameter is required").
- A bare element id (kc-login) is tried as [id="..."].
- execute_javascript failed on a top-level `return` ("Illegal return statement").
- An invented command (click_element_by_id) says what to use instead.
"""
import asyncio
import importlib

import pytest

playwright_mod = importlib.import_module('backend_host.src.controllers.web.playwright')
PlaywrightWebController = playwright_mod.PlaywrightWebController


class _Locator:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    async def count(self):
        self.page.counted.append(self.sel)
        return 1 if self.sel in self.page.present else 0


class _Page:
    def __init__(self, present=()):
        self.present = set(present)
        self.counted, self.clicked, self.evaluated = [], [], []

    def locator(self, sel):
        return _Locator(self, sel)

    async def click(self, sel, timeout=None):
        self.clicked.append(sel)
        if sel not in self.present:
            raise TimeoutError(f'waited {timeout} ms for {sel}')

    async def evaluate(self, script):
        self.evaluated.append(script)
        if script.lstrip().startswith('return'):
            raise Exception('Page.evaluate: SyntaxError: Illegal return statement')
        return 'ok'


@pytest.fixture
def make(monkeypatch):
    def _make(present=()):
        ctl = PlaywrightWebController(browser_engine='chromium')
        page = _Page(present)

        async def persistent_page(*_a, **_k):
            return page

        monkeypatch.setattr(ctl, '_get_persistent_page', persistent_page)
        return ctl, page
    return _make


def run(coro):
    return asyncio.run(coro)


def test_absent_native_selectors_are_never_clicked(make, monkeypatch):
    ctl, page = make()

    async def no_match(term):
        return {'success': False, 'error': 'not found'}
    monkeypatch.setattr(ctl, 'find_element', no_match)
    out = run(ctl.execute_command('click_element', {'text': 'TV Guide'}))
    assert out['success'] is False
    assert page.clicked == [], 'no 3 s click timeout is spent on a selector that matches nothing'
    assert len(page.counted) == 6


def test_a_bare_id_is_clicked_as_an_id(make):
    ctl, page = make(present={'[id="kc-login"]'})
    out = run(ctl.execute_command('click_element', {'element_id': 'kc-login'}))
    assert out['success'] is True and page.clicked == ['[id="kc-login"]']


def test_xpath_param_is_accepted(make):
    ctl, page = make(present={"xpath=//button[@id='kc-login']"})
    out = run(ctl.execute_command('click_element', {'xpath': "//button[@id='kc-login']"}))
    assert out['success'] is True
    assert page.clicked == ["xpath=//button[@id='kc-login']"]


def test_top_level_return_runs_as_a_function_body(make):
    ctl, page = make()
    out = run(ctl.execute_command('execute_javascript', {'script': 'return location.href'}))
    assert out['success'] is True and out['result'] == 'ok'
    assert page.evaluated[-1].startswith('(() => {')


def test_invented_command_gets_a_hint(make):
    ctl, _ = make()
    out = run(ctl.execute_command('click_element_by_id', {'element_id': 'x'}))
    assert out['success'] is False
    assert "click_element with params {'element_id': '#<id>'}" in out['error']
    out = run(ctl.execute_command('execute_pyautogui_keypress', {'key': 'ctrl+a'}))
    assert 'press_key' in out['error']


def _dump_ctl(make, monkeypatch, matches):
    ctl, page = make()

    async def dump():
        return {'success': True, 'elements': [{}]}
    monkeypatch.setattr(ctl, 'dump_elements', dump)
    monkeypatch.setattr(ctl, '_search_dumped_elements', lambda sel, els: matches)
    taps = []

    async def tap(x, y):
        taps.append((x, y))
        return {'success': True}
    monkeypatch.setattr(ctl, 'tap_x_y', tap)
    return ctl, taps


def _m(pos):
    return {'position': pos, 'match_reason': 'aria', 'element_id': 'e', 'matched_value': 'Menu'}


def test_dump_click_skips_matches_without_a_box(make, monkeypatch):
    """BUG-0701: the first dump match had no box, a later one did."""
    ctl, taps = _dump_ctl(make, monkeypatch, [
        _m({}), _m({'x': 5, 'y': 5, 'width': 0, 'height': 0}), _m({'x': 10, 'y': 20, 'width': 100, 'height': 40})])
    out = run(ctl.click_element('Menu'))
    assert out['success'] is True
    assert taps == [(60, 40)]


def test_dump_click_errors_only_when_no_match_has_a_box(make, monkeypatch):
    ctl, taps = _dump_ctl(make, monkeypatch, [_m({}), _m({'x': 1, 'y': 1, 'width': 0, 'height': 9})])
    out = run(ctl.click_element('Menu'))
    assert out['success'] is False
    assert 'no coordinates available' in out['error']
    assert taps == []
