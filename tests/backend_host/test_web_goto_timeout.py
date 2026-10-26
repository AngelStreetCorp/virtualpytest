"""navigate_to_url: the page-load timeout is its own parameter, never the edge's wait_time (BUG-0714)."""
import importlib

pw = importlib.import_module('backend_host.src.controllers.web.playwright')


def test_wait_time_is_not_the_load_timeout():
    # an edge with wait_time 2 s used to give the goto 2 s
    assert pw.resolve_goto_timeout({'url': 'x', 'wait_time': 2000}) == pw.GOTO_TIMEOUT_DEFAULT_MS
    assert pw.resolve_goto_timeout({'url': 'x', 'wait_time': 2}) == pw.GOTO_TIMEOUT_DEFAULT_MS


def test_explicit_page_load_timeout_wins_over_legacy_timeout():
    assert pw.resolve_goto_timeout({'page_load_timeout': 45000, 'timeout': 20000}) == 45000
    assert pw.resolve_goto_timeout({'timeout': 20000}) == 20000


def test_floor_applies():
    assert pw.resolve_goto_timeout({'page_load_timeout': 1000}) == pw.GOTO_TIMEOUT_MIN_MS
    assert pw.GOTO_TIMEOUT_MIN_MS >= 15000


def test_garbage_value_falls_back():
    assert pw.resolve_goto_timeout({'page_load_timeout': 'soon'}) == pw.GOTO_TIMEOUT_DEFAULT_MS
