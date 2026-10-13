"""
Poké Mart screens (French ROM, read from the screen text) and how many balls to buy. Pure functions.

The clerk's dialog is a chain of boxes the generic text handler would answer with A, buying one Poké Ball
per loop until the money is gone: the runner reads which box is open and answers each on purpose.
"""

import re
from typing import List

BALL_PRICE, BALLS_WANTED, BALLS_MAX = 200, 5, 10
CLERK_PICTURE = 38        # the mart clerk's sprite; he stands behind the counter, one square left of it
QUANTITY = re.compile(r"\.\.(\d\d) +(\d+)")   # the "x03   600" box: quantity, then the price of that many


def balls_to_buy(money: int) -> int:
    """5 balls, more when rich (a third of the money at most, 10 at most), never more than the money buys."""
    return min(money // BALL_PRICE, BALLS_MAX, max(BALLS_WANTED, money // (3 * BALL_PRICE)))


def screen(rows: List[str]) -> str:
    """Which part of the shop dialog is open: "confirm" (OUI / NON), "quantity", "list" (the wares), "menu"
    (ACHETER / VENDRE / SORTIE) or "" (none: plain text or nothing)."""
    if any("OUI" in r for r in rows) and any("NON" in r for r in rows):
        return "confirm"
    if quantity(rows):
        return "quantity"
    if "ACHETER" not in rows[1]:
        return ""
    return "menu" if "VENDRE" in rows[3] else "list"


def quantity(rows: List[str]) -> int:
    """The quantity shown in the quantity box, 0 when there is none."""
    for r in rows[8:12]:
        m = QUANTITY.search(r)
        if m:
            return int(m.group(1))
    return 0
