"""Text verification scores on word boundaries (BUG-0406)."""
import pytest

from backend_host.src.controllers.verification.text_helpers import TextHelpers
from scripts.jev_review import matchers

H = TextHelpers('')
S = H.text_match_score


def test_short_target_inside_a_longer_word_no_longer_scores_high():
    assert S('TVGuide Apps Aufnahmen TV Shop', 'Home') < 0.7
    assert S('Replay Filme Serien Aufnahmen', 'Home') < 0.7
    assert S('Aufnahmen', 'Home') < 0.7


def test_whole_word_is_verbatim_one():
    assert S('Q Home TVGuide Apps', 'Home') == 1.0
    assert S('Movies & Series', 'movies series') == 1.0
    assert S('Settings!', 'settings') == 1.0
    assert S('Uber uns', 'Über') == 1.0           # accents folded
    assert S('Paramètres', 'Parametres') == 1.0


def test_inside_a_word_is_not_verbatim_for_threshold_one():
    assert not H.text_matches('Aufnahmen', 'Home', threshold=1.0)
    assert H.text_matches('Go Home now', 'Home', threshold=1.0)


def test_one_character_ocr_misread_still_passes():
    assert S('Anrnelden', 'Anmelden') >= 0.8
    assert H.text_matches('Konto Anrnelden', 'Anmelden')
    assert S('Einstellunqen', 'Einstellungen') >= 0.9


def test_word_merges_and_splits_are_tolerated():
    assert S('Q Home TVGuide Apps', 'TV Guide') >= 0.9
    assert S('Bitte An melden', 'Anmelden') >= 0.9


def test_multi_word_target():
    assert S('x Von Anfang an abspielen y', 'Von Anfang an abspielen') == 1.0
    assert S('Von Anfang an abspielen', 'Von Anfang abspielen') >= 0.8
    assert S('Weiter schauen Anschauen', 'Von Anfang an abspielen') < 0.5


def test_empty_inputs():
    assert S('', 'x') == 0.0 and S('x', '') == 0.0 and S('...', 'x') == 0.0


def test_unspaced_scripts_keep_the_character_window():
    assert S('日本語のテキスト表示', 'テキスト') == 1.0
    assert S('日本語のテキス卜表示', 'テキスト') >= 0.7


def test_local_mirror_agrees_with_host_scorer():
    cases = [('Aufnahmen', 'Home'), ('Anrnelden', 'Anmelden'), ('Q Home TVGuide', 'TV Guide'),
             ('日本語のテキスト', 'テキスト'), ('Uber uns', 'Über'), ('a b c', 'x y z w')]
    for e, t in cases:
        assert matchers._LocalText().text_match_score(e, t) == pytest.approx(S(e, t))
