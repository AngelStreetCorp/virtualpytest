"""The contract table of docs/agent/atlas/USECASES.md — the 109 use cases of TASK-163.

Three tools read that file:

* the benchmark (``scripts/atlas_usecase_bench.py``),
* the FAQ alias backfill (``scripts/agent/faq_alias_backfill.py``),
* the FAQ guard test (``tests/backend_server/test_atlas_faq.py``).

The file also holds the results tables and the browser-verification table, whose rows
start with a UC- id too. Those are documentation, not contract rows: a browser row is
graded against a tools cell that holds prose ("list_hosts, get_device_info (both
ticked)"), so no call can satisfy it, and one of them carries a real device name into
the FAQ-hijack check.

So the contract table is found by its SECTION, not by "the first UC- line in the file":
the section whose heading names the use cases, up to the next heading of the same level.
A sub-heading inside the table does not end it, and a reordering of the file does not
change what is read.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
USECASES = REPO / "docs" / "agent" / "atlas" / "USECASES.md"

HEADING = re.compile(r"^(#{1,6})\s")
CONTRACT_SECTION = re.compile(r"\buse cases?\b", re.IGNORECASE)
ROW = re.compile(r"^\|\s*(UC-\d{3})\s*\|(.*)\|\s*$")


def contract_lines(text: str) -> list[str]:
    """The lines of the contract section of the file."""
    lines = text.splitlines()
    start = None
    level = 0
    for index, line in enumerate(lines):
        heading = HEADING.match(line)
        if not heading:
            continue
        if start is None:
            # the section that names the use cases (a section, not the document title)
            if len(heading.group(1)) >= 2 and CONTRACT_SECTION.search(line):
                start = index + 1
                level = len(heading.group(1))
            continue
        if len(heading.group(1)) <= level:
            return lines[start:index]
    return lines[start:] if start is not None else []


def contract_rows(text: str) -> list[dict]:
    """The contract rows: ``{"id": "UC-001", "cells": [...]}``.

    The cells are the table cells after the id, stripped.
    """
    rows = []
    for line in contract_lines(text):
        match = ROW.match(line)
        if not match:
            continue
        rows.append({"id": match.group(1), "cells": [cell.strip() for cell in match.group(2).split("|")]})
    return rows
