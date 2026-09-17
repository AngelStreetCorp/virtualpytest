"""
tests/backend_host/test_ui_dump_capture.py — the per-execution UI dump trace.

Every dump a controller takes lands here, polls included, because "we looked eight times and
it never changed" is the answer to most questions about a stuck screen. The two things that
make that survivable are tested below: an identical tree collapses to a back-reference, and
the file is capped so a long polling run cannot grow without bound.

The label on each entry comes from the caller — a selector, a verification, a bare 'dump' —
so nothing in here has to know what a given controller considers a significant moment.
"""
import importlib

import pytest

cap = importlib.import_module('shared.src.lib.utils.ui_dump_capture')


def rows(*labels):
    return [{'text': '', 'content_desc': l, 'class_name': 'android.widget.Button',
             'clickable': True} for l in labels]


@pytest.fixture(autouse=True)
def clean():
    cap.reset_ui_dumps()
    yield
    cap.reset_ui_dumps()


def test_every_dump_is_its_own_numbered_entry():
    for i in range(3):
        cap.record('device2', f'dump {i}', rows(f'Item {i}'), 1)
    assert cap.get_ui_dump_count() == 3
    text = open(cap.get_ui_dump_file()).read()
    assert '=== dump 1 |' in text and '=== dump 2 |' in text and '=== dump 3 |' in text


def test_an_identical_tree_collapses_but_still_gets_an_entry():
    """A verification polling a screen that never changes must not print it twenty times —
    but each look still has to be visible, or you cannot tell one poll from twenty."""
    same = rows('Subscriptions', 'Shorts')
    for _ in range(4):
        cap.record('device2', "waitForElementToAppear('Home')", same, 2)
    text = open(cap.get_ui_dump_file()).read()

    assert cap.get_ui_dump_count() == 4
    for n in (1, 2, 3, 4):
        assert f'=== dump {n} |' in text
    # The tree itself appears once; the other three point back at it.
    assert text.count('Subscriptions') == 1
    assert text.count('(identical to dump 1)') == 3


def test_a_changed_tree_is_printed_again():
    cap.record('device2', 'a', rows('Home'), 1)
    cap.record('device2', 'b', rows('Player'), 1)
    text = open(cap.get_ui_dump_file()).read()
    assert 'Home' in text and 'Player' in text
    assert 'identical to' not in text


def test_the_caller_supplies_the_label():
    cap.record('device2', "click_element(' seconds|!Sponsored')", rows('x'), 1)
    assert "click_element(' seconds|!Sponsored')" in open(cap.get_ui_dump_file()).read()


def test_an_outcome_annotates_the_dump_it_acted_on():
    """Not a second copy of the same tree — one line on the entry that produced it."""
    cap.record('device2', "click_element(' seconds')", rows('Ad', 'Video'), 2)
    cap.note("' seconds' clicked 'Video'")
    text = open(cap.get_ui_dump_file()).read()
    assert cap.get_ui_dump_count() == 1
    assert "  -> ' seconds' clicked 'Video'" in text


def test_a_note_with_no_dump_yet_is_ignored_not_an_error():
    cap.note('nothing to attach to')
    assert cap.get_ui_dump_file() == ''


def test_an_empty_tree_says_so():
    cap.record('device2', 'dump', [], 0)
    assert 'empty tree' in open(cap.get_ui_dump_file()).read()


def test_unlabelled_node_counts_are_kept_even_though_the_nodes_are_not():
    """'3 labelled of 210' is itself a finding — a screen that is still drawing."""
    cap.record('device2', 'dump', rows('a', 'b', 'c'), 210)
    assert '3 labelled of 210 nodes' in open(cap.get_ui_dump_file()).read()


def test_the_trace_is_capped_and_says_what_it_dropped():
    original = cap.MAX_ENTRIES
    cap.MAX_ENTRIES = 5
    try:
        for i in range(9):
            cap.record('device2', f'dump {i}', rows(f'Item {i}'), 1)
        text = open(cap.get_ui_dump_file()).read()
        assert cap.get_ui_dump_count() == 5
        assert '4 earlier dump(s) dropped' in text
        # the oldest are gone, the newest are kept
        assert 'Item 0' not in text and 'Item 8' in text
    finally:
        cap.MAX_ENTRIES = original


def test_a_run_with_no_dumps_uploads_nothing():
    assert cap.get_ui_dump_file() == ''
    assert cap.get_ui_dump_count() == 0


def test_a_label_long_enough_to_select_on_is_not_cut():
    """The first version cut descriptions at 70 characters — which hid the duration in a
    YouTube feed card, i.e. exactly the substring the tree's selector matches on. A trace that
    cannot show why a selector missed is not doing its job."""
    card = ("L'argent n'est plus gratuit : la fin tragique des taux bas sur le marche de "
            "l'immobilier - 1 hour, 3 minutes, 39 seconds - Go to channel La Martingale - "
            "La Martingale - 308 views - 3 hours ago - play video")
    assert len(card) > 70
    cap.record('device2', "click_element(' seconds')",
               [{'text': '', 'content_desc': card, 'class_name': 'Button', 'clickable': True}], 1)
    text = open(cap.get_ui_dump_file()).read()
    assert ' seconds' in text, 'the substring the selector matches on must be visible'


def test_a_truly_enormous_label_is_cut_but_says_so():
    cap.record('device2', 'dump',
               [{'text': '', 'content_desc': 'x' * 400, 'class_name': 'Button'}], 1)
    text = open(cap.get_ui_dump_file()).read()
    assert '\u2026' in text
    assert 'x' * cap.DESC_WIDTH in text
