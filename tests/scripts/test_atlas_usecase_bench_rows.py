"""The Atlas use-case bench (scripts/atlas_usecase_bench.py) reads the contract rows of
docs/agent/atlas/USECASES.md — and only those.

The file holds other tables whose rows also start with a UC- id: the results tables and
the browser-verification table (TASK-163). A browser row carries prose in its tools cell
("list_hosts, get_device_info (both ticked)"), so grade() expects a tool named
"get_device_info` (both ticked)" — a call that can never be made, and a row that can never
pass. Parsed as contract rows, four of them (UC-001, UC-003, UC-046, UC-051) would depress
the reported pass rate of every run.

The regression these tests pin down: parse_usecases() matched every "| UC-xxx |" line of
the file, so the browser-verification table added to the file by the TASK-163 documentation
silently became four unpassable contract rows.

Run: pytest tests/scripts/test_atlas_usecase_bench_rows.py -v
"""
import importlib.util
import os
from pathlib import Path

import pytest

_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "atlas_usecase_bench", os.path.join(_here, "..", "..", "scripts", "atlas_usecase_bench.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

_contract_spec = importlib.util.spec_from_file_location(
    "usecase_contract", os.path.join(_here, "..", "..", "scripts", "usecase_contract.py"))
C = importlib.util.module_from_spec(_contract_spec)
_contract_spec.loader.exec_module(C)

CONTRACT = Path(B.REPO) / "docs" / "agent" / "atlas" / "USECASES.md"
CONTRACT_ROWS = 109


def test_the_contract_table_holds_109_rows_without_duplicate_ids():
    rows = B.parse_usecases(CONTRACT)
    ids = [row["id"] for row in rows]
    assert len(rows) == CONTRACT_ROWS, f"expected {CONTRACT_ROWS} contract rows, got {len(rows)}"
    assert len(set(ids)) == len(ids), f"duplicate ids in the contract table: {sorted(i for i in ids if ids.count(i) > 1)}"
    assert ids[0] == "UC-001" and ids[-1] == "UC-109"


def test_the_browser_verification_table_is_not_parsed_as_contract_rows():
    """The four browser rows (UC-001, UC-003, UC-046, UC-051) are documentation.

    They name contract rows, so parsing them again would duplicate those ids — that is
    the trap this test pins down.
    """
    text = CONTRACT.read_text()
    browser_section = text.split("### Browser verification", 1)
    assert len(browser_section) == 2, "the browser-verification section is gone from USECASES.md"
    browser_ids = {m.group(1) for m in (B.ROW.match(line) for line in browser_section[1].splitlines()) if m}
    assert browser_ids, "the browser-verification table lost its rows — the check would be vacuous"

    rows = B.parse_usecases(CONTRACT)
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), (
        f"a row is parsed twice: the browser-verification table was parsed as contract rows "
        f"({sorted(browser_ids & set(ids))})")
    assert browser_ids <= set(ids), (
        "the browser-verification table names rows that are not in the contract — the test "
        "would not catch the trap any more")
    assert len(rows) == CONTRACT_ROWS


def test_every_contract_row_names_a_tool_the_router_can_call():
    """A contract row is graded against its tools cell, so the cell must hold tool names.

    The browser rows broke this: "get_device_info` (both ticked)" is not a tool. A cell
    that holds prose would make the row unpassable, whatever the agent does.
    """
    import re

    for row in B.parse_usecases(CONTRACT):
        for entry in row["tools"]:
            for alternative in entry.split("/"):
                assert re.fullmatch(r"[a-z][a-z0-9_]*", alternative), (
                    f"{row['id']} names '{alternative}', which is not a tool name")


# --------------------------------------------------------------------------
# the section anchor: the contract table is found by its section, not by "the
# first UC- line in the file" (scripts/usecase_contract.py)
# --------------------------------------------------------------------------

def test_the_contract_section_is_found_wherever_it_is():
    """The contract table moved to the end of the file is still the contract table."""
    text = CONTRACT.read_text()
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## ") and "use case" in line.lower())
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    section = lines[start:end]
    rest = lines[:start] + lines[end:]
    moved = "\n".join(rest + [""] + section) + "\n"
    assert len(C.contract_rows(moved)) == CONTRACT_ROWS, "the section anchor does not follow the table"


def test_a_sub_heading_inside_the_contract_table_does_not_end_it():
    text = CONTRACT.read_text()
    with_sub = text.replace("| UC-002 |", "### A sub-heading inside the table\n| UC-002 |", 1)
    assert "| UC-002 |" in with_sub
    assert len(C.contract_rows(with_sub)) == CONTRACT_ROWS, "a sub-heading ended the contract section"


def test_a_section_heading_after_the_first_row_ends_the_contract_section():
    """The one case the anchor cannot survive: the table is split by a heading.

    It is loud rather than silent: the row count no longer matches, and the
    assertions above fail.
    """
    text = CONTRACT.read_text()
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("| UC-001 |"))
    split = "\n".join(lines[:index + 1] + ["", "## Another section"] + lines[index + 1:]) + "\n"
    rows = C.contract_rows(split)
    assert len(rows) < CONTRACT_ROWS, "a heading inside the table should end the section"
    assert rows[0]["id"] == "UC-001"


def test_the_three_consumers_read_the_same_contract_rows():
    """The bench, the FAQ alias backfill and the FAQ guard test read the same table."""
    backfill_spec = importlib.util.spec_from_file_location(
        "faq_alias_backfill", os.path.join(_here, "..", "..", "scripts", "agent", "faq_alias_backfill.py"))
    backfill = importlib.util.module_from_spec(backfill_spec)
    backfill_spec.loader.exec_module(backfill)

    bench_rows = B.parse_usecases(CONTRACT)
    backfill_rows = backfill.read_usecases(CONTRACT)
    assert [r["id"] for r in bench_rows] == [r["id"] for r in backfill_rows]
    assert len(backfill_rows) == CONTRACT_ROWS
    assert backfill_rows[0]["prompt"] == bench_rows[0]["prompt"]
    assert backfill_rows[-1]["prompt"] == bench_rows[-1]["prompt"]
