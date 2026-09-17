"""
tests/backend_host/test_phone_selector.py — what `click_element` picks, and what it refuses.

The selector syntax is `a|b` for fallback terms and `!term` to disqualify a match. Exclusions
work by screen AREA rather than by label, because the thing that needs excluding usually
carries the word on a parent while the thing that would be tapped is a child of it.

Both cases below came off the reporting phone's own UI trace, not from imagination:

  BUG-0121  a sponsored feed card carries a duration like any other, so ' seconds' opened an
            advertiser's page. The word "Sponsored" is on the wrapping Button; the duration is
            on a child that says nothing about being an ad.
  dump 14   on the player, a scrubber describes itself as a duration
            ("38 minutes 24 seconds of 1 hour 3 minutes 38 seconds"), is clickable, and has the
            shortest label on screen — everything _best_match prefers. The edge's retry seeked
            the video instead of opening one.
"""
import importlib

import pytest

phone_agent = importlib.import_module(
    'features.mobile-app.backend_host.controllers.phone_agent')
PhoneAgentRemoteController = phone_agent.PhoneAgentRemoteController
AndroidElement = phone_agent.AndroidElement
parse_selector = phone_agent._parse_selector


def element(eid, desc, cls='android.widget.Button', bounds='[0,0][100,100]', clickable=True):
    # Keywords, not positions: AndroidElement's second parameter is `tag`, and passing
    # positionally silently shifts every field along one.
    return AndroidElement(element_id=eid, tag='node', text='', resource_id='',
                          content_desc=desc, class_name=cls, bounds=bounds,
                          clickable=clickable)


# --- as the trace recorded them ----------------------------------------------------------
SCRUBBER = element(1, '38 minutes 24 seconds of 1 hour 3 minutes 38 seconds',
                   'android.widget.SeekBar', '[0,600][1080,660]')
SUGGESTED = element(2, 'Crise financiere en France - 22 minutes, 4 seconds - Go to channel '
                       'Xerfi - 40K views - play video', bounds='[0,1400][1080,2000]')
CARD = element(3, "L'argent n'est plus gratuit - 1 hour, 3 minutes, 39 seconds - Go to channel "
                  "La Martingale - play video", bounds='[0,700][1080,1300]')
AD = element(4, 'Sponsored - swype - 7 minutes, 19 seconds', bounds='[0,100][1080,690]')
AD_DURATION = element(5, '7 minutes, 19 seconds', 'android.view.ViewGroup',
                      '[860,600][1050,680]', clickable=False)
MINI_SCRUBBER = element(6, '12 minutes 3 seconds of 30 minutes', 'android.widget.SeekBar',
                        '[600,2200][1080,2260]')


@pytest.fixture
def controller():
    ctrl = PhoneAgentRemoteController.__new__(PhoneAgentRemoteController)
    ctrl.device_type = 'phone_agent'
    return ctrl


def best(ctrl, selector, tree):
    ctrl.last_ui_elements = tree
    wanted, unwanted = parse_selector(selector)
    blocked = ctrl._blocked_regions(unwanted) if unwanted else []
    for term in wanted:
        hit = ctrl._best_match(term, blocked)
        if hit:
            return hit
    return None


TREE_SELECTOR = ' seconds|!Sponsored|!SeekBar'


# --- the scrubber ------------------------------------------------------------------------

def test_without_the_exclusion_the_player_scrubber_wins(controller):
    """Reproduces dump 14: this is what made the retry seek."""
    assert best(controller, ' seconds|!Sponsored', [SCRUBBER, SUGGESTED]) is SCRUBBER


def test_excluding_seekbar_picks_the_suggested_video_instead(controller):
    assert best(controller, TREE_SELECTOR, [SCRUBBER, SUGGESTED]) is SUGGESTED


def test_a_player_with_nothing_else_yields_nothing_rather_than_seeking(controller):
    assert best(controller, TREE_SELECTOR, [SCRUBBER]) is None


def test_a_minimised_player_on_the_feed_is_excluded_too(controller):
    """Why the exclusion belongs on the main action and not only on the retry."""
    assert best(controller, TREE_SELECTOR, [MINI_SCRUBBER, CARD]) is CARD
    assert best(controller, TREE_SELECTOR, [MINI_SCRUBBER]) is None


# --- the advert --------------------------------------------------------------------------

def test_the_feed_still_picks_a_real_card_over_the_advert(controller):
    assert best(controller, TREE_SELECTOR, [AD, CARD]) is CARD


def test_the_adverts_unlabelled_child_is_excluded_by_area(controller):
    """AD_DURATION says nothing about being an advert; it is inside one, which is enough."""
    assert best(controller, TREE_SELECTOR, [AD, AD_DURATION]) is None


# --- how the match is scoped -------------------------------------------------------------

def test_an_exclusion_matches_the_widget_class_but_a_positive_term_does_not(controller):
    """The asymmetry is the point: an exclusion names a KIND of widget, while a positive term
    names what a person sees. Letting positive terms match class names would silently widen
    every selector already saved in a tree."""
    assert controller._matches(SCRUBBER, 'seekbar', include_class=True) is True
    assert controller._matches(SCRUBBER, 'seekbar') is False

    # so a bare 'SeekBar' selects nothing, and only the `!` form has any effect
    assert best(controller, 'SeekBar', [SCRUBBER, CARD]) is None


def test_the_selector_splits_into_wanted_and_unwanted():
    assert parse_selector(TREE_SELECTOR) == (['seconds'], ['Sponsored', 'SeekBar'])
    # no pipe: passed through verbatim, leading space and all
    assert parse_selector(' seconds') == ([' seconds'], [])
