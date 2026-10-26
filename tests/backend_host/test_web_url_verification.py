"""BUG-0703: web `waitForUrlToMatch` verifies a page by URL path, in any UI language. Fake page only."""
import asyncio
import importlib

import pytest

pv = importlib.import_module('backend_host.src.controllers.web.playwright_verifications')

pytestmark = pytest.mark.unit


class FakePage:
    def __init__(self, url):
        self.url = url


class FakeController(pv.PlaywrightVerificationsMixin):
    """Runs on the test's own loop: _ensure_loop / _submit_to_controller_loop are not needed."""
    def __init__(self, url):
        self.page = FakePage(url)

    async def _get_persistent_page(self):
        return self.page


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def inner(name):
    # the decorator hops to the controller loop; call the undecorated coroutine
    return getattr(pv.PlaywrightVerificationsMixin, name).__closure__[0].cell_contents


def test_match_in_german_and_english():
    for url in ('https://h/de/epg/initial', 'https://h/en/epg/initial?a=1'):
        ok, msg, det = run(inner('waitForUrlToMatch')(FakeController(url), '/epg/initial', timeout=0))
        assert ok, msg
        assert det['current_url'] == url


def test_mismatch_reports_current_url():
    ok, msg, det = run(inner('waitForUrlToMatch')(FakeController('https://h/de/home'), '/epg/initial', timeout=0))
    assert not ok
    assert 'https://h/de/home' in msg


def test_schema_lists_the_command():
    cmds = {v['command']: v for v in FakeController('x').get_available_verifications()}
    assert 'url_pattern' in cmds['waitForUrlToMatch']['params']
