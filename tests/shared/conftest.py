"""Shared-lib tests never read the price table from a database (TASK-87): unpriced unless a test sets prices."""
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))


@pytest.fixture(autouse=True)
def _no_price_table():
    from shared.src.lib.ai import prices
    prices.set_for_tests([])
    yield
    prices.invalidate()
