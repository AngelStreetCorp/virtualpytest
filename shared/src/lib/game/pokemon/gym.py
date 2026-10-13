"""
Vermilion Gym's electric barrier (TASK-33): Lt. Surge is behind two electric locks, each opened by a switch
under one of 15 trash cans (5 x 3, at x 1 3 5 7 9, y 7 9 11 on the gym's map; verified on the emulator).
The first switch is in a random can, the second in a can next to it (up, down, left or right). A wrong
second guess closes the first lock again and the switches move (seen on the emulator: the old first can then
held nothing), so after a reset the search starts over; within one attempt it keeps what it learned.
Pure bookkeeping here; the walking and the A presses are the runner's. Texts are the French ROM's.
"""

from typing import Dict, List, Optional, Tuple

Square = Tuple[int, int]
CANS: List[Square] = [(x, y) for y in (7, 9, 11) for x in (1, 3, 5, 7, 9)]
EMPTY = "ordures"      # "Un joli tas d'ordures... miam!": a can without a switch, no lock open
FIRST = "premier"      # "Oh! Un bouton dans la poubelle! ... Le premier verrouillage est levé!"
RESET = "Oups"         # "Une poubelle bien dégueulasse! Oups... Les verrouillages sont en place!": a wrong second guess
TRAINER = "veut"       # "MARIN veut se battre!": a trainer spotted us, the text is not the can's


def new_state() -> Dict:
    """`first`: the can with the first switch (once found); `open`: its lock is open now; `tried`: cans
    without the first switch; `bad`: cans next to the first that did not hold the second."""
    return {"first": None, "open": False, "tried": [], "bad": []}


def neighbours(can: Square) -> List[Square]:
    x, y = can
    return [c for c in ((x - 2, y), (x + 2, y), (x, y - 2), (x, y + 2)) if c in CANS]


def next_can(state: Dict, pos: Square) -> Optional[Square]:
    """The can to look under next: an untried one for the first switch, a neighbour of it for the second.
    The nearest to `pos` first. None when nothing is left."""
    first = tuple(state["first"]) if state["first"] else None
    skip = {tuple(t) for t in state["bad" if first else "tried"]}
    pool = [c for c in (neighbours(first) if first else CANS) if c not in skip]
    return min(pool, key=lambda c: abs(c[0] - pos[0]) + abs(c[1] - pos[1]), default=None)


def stands(can: Square) -> List[Tuple[Square, str]]:
    """Squares next to a can, with the key that faces it from there."""
    x, y = can
    return [((x, y - 1), "DOWN"), ((x, y + 1), "UP"), ((x - 1, y), "RIGHT"), ((x + 1, y), "LEFT")]


def after(state: Dict, can: Square, texts: List[str]) -> str:
    """Record what the can said; returns "first", "reset", "solved", "nothing" or "none" (no text came, or a
    trainer's: not the can's)."""
    text = " ".join(texts)
    if not texts or TRAINER in text:
        return "none"
    if FIRST in text:
        state.update(first=list(can), open=True, bad=[])
        return "first"
    if RESET in text:
        state.update(first=None, open=False, tried=[], bad=[])   # the switches moved
        return "reset"
    if EMPTY in text:
        if state["first"] and not state["open"]:
            state.update(first=None, tried=[], bad=[])   # an old first can that holds nothing now
        if not state["first"]:
            state["tried"].append(list(can))
        else:
            state["bad"].append(list(can))
        return "nothing"
    return "solved"   # the second lock's own text: anything else a can says
