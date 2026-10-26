"""validate_languages.py: a series must read each run's OWN result (BUG-0709 trap: a stale result printed as the next one's)."""
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

_p = os.path.join(os.path.dirname(__file__), "..", "scripts", "agent", "validate_languages.py")
spec = importlib.util.spec_from_file_location("validate_languages", _p)
vl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vl)

T0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)


def test_own_result_accepts_its_execution():
    s = {"execution_id": "abc", "done": True, "passed": True}
    assert vl.own_result(s, "abc", T0, (T0 + timedelta(minutes=9)).isoformat()) is s


def test_other_execution_is_refused():
    with pytest.raises(vl.StaleResult):
        vl.own_result({"execution_id": "previous", "done": True}, "abc", T0)


def test_result_older_than_the_start_is_refused():
    with pytest.raises(vl.StaleResult):
        vl.own_result({"execution_id": "abc", "done": True}, "abc", T0, (T0 - timedelta(minutes=1)).isoformat())


def test_running_is_not_a_result():
    with pytest.raises(vl.StaleResult):
        vl.own_result({"execution_id": "abc", "done": False, "status": "running"}, "abc", T0)


def test_epoch_ms_and_naive_iso_timestamps():
    assert vl.parse_ts(1_792_000_000_000).year == 2026
    assert vl.parse_ts("2026-10-20T10:00:00").tzinfo is not None
    assert vl.parse_ts("") is None


def test_steps_from_text():
    assert vl.steps_from_text("done: 49/49 steps passed") == (49, 49)
    assert vl.steps_from_text("Steps: 47/49") == (47, 49)
    assert vl.steps_from_text("nothing") is None


def _proof(href, label, selected=None):
    return json.dumps({"href": href, "label": label, "selected": selected})


def test_language_proof_needs_address_selected_item_and_label():
    before = _proof("https://x/en/settings", "Home, Currently selected", 1)
    after = _proof("https://x/de/settings", "Home, Aktuell ausgewählt", 2)
    assert vl.language_proved(before, after, "de")
    # the list still marks English: not switched
    assert not vl.language_proved(before, _proof("https://x/de/settings", "Home, Aktuell ausgewählt", 1), "de")
    # the address says de but the label did not change and before was another language: not proven
    assert not vl.language_proved(before, _proof("https://x/de/settings", "Home, Currently selected", 2), "de")
    # the address alone proves nothing
    assert not vl.language_proved(before, _proof("https://x/en/settings", "Home, Aktuell ausgewählt", 2), "de")


def test_already_in_the_language_is_proven_by_its_address():
    p = _proof("https://x/fr/settings", "Home, Actuellement sélectionné", 4)
    assert vl.language_proved(p, p, "fr")


def test_selected_language_reads_the_list_position():
    assert vl.selected_language(_proof("u", "l", 3)) == "it"
    assert vl.selected_language(_proof("u", "l", None)) is None


def test_table_has_one_row_per_language_with_its_own_link():
    rows = [{"lang": "de", "passed": True, "steps": (49, 49), "execution_id": "11111111xx", "report_url": "https://r/1", "proof": "a"},
            {"lang": "fr", "passed": False, "steps": (47, 49), "execution_id": "22222222xx", "report_url": "https://r/2", "proof": "b"}]
    t = vl.render_table(rows)
    assert "https://r/1" in t and "https://r/2" in t and "49/49 ✓" in t and "47/49 ✗" in t
