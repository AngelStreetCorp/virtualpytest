"""
HM moves in the field (French Gen 1): teaching HM01 Cut from the bag, and using Cut on a tree.

Both are menu trips read from the screen (the START menu, the bag, the party list, the field-move box).
The pure parts (which row is which, who learns it) are separate so they can be tested on plain screen text.
Nothing is written to the game's memory: every key is a real press.
"""

from typing import Dict, List, Optional

from . import battle, learn
from .memory import ADDR, Read, screen_rows, text_box_open
from .milestones import HM01_CUT, HM03_SURF, HM04_STRENGTH, POKE_FLUTE, STRENGTH, SURF, bag

# Nugget: the game refuses TMs, HMs and fossils (\"too important\"; verified on a TM). BUG-0711: then a Full Restore: with
# no Nugget left a full bag kept Silph Co.'s Card Key on the floor, and the story is worth more than one potion; then the
# Rare Candies (the president's Master Ball wanted another slot)
TOSSABLE = (0x31, 0x10, 0x28)
CUT = 15                   # the move id
FIELD_HMS = (("Cut", HM01_CUT, CUT), ("Surf", HM03_SURF, SURF), ("Strength", HM04_STRENGTH, STRENGTH))   # (name, item, move) in story order
LIST_OFFSET = 0xCC36       # wListScrollOffset: first visible bag entry
PARTY_STRUCT = 0x2C
MENU_WORDS = ("RETOUR", "STATS", "OUI", "APTE", "UTIL")   # any of these on screen: a menu is still open


def party_moves(read: Read) -> List[List[int]]:
    """The move ids of each party Pokémon."""
    n = min(read(ADDR["party_count"], 1)[0], 6)
    return [[m for m in read(ADDR["party_mons"] + PARTY_STRUCT * i + 8, 4) if m] for i in range(n)]


def cut_user(read: Read) -> Optional[int]:
    """Party index of the first Pokémon knowing Cut, or None."""
    return next((i for i, ms in enumerate(party_moves(read)) if CUT in ms), None)


def surf_user(read: Read) -> Optional[int]:
    """Party index of the first Pokémon knowing Surf, or None (BUG-0681)."""
    return next((i for i, ms in enumerate(party_moves(read)) if SURF in ms), None)


def strength_user(read: Read) -> Optional[int]:
    """Party index of the first Pokémon knowing Strength, or None (BUG-0874: the boulder only moves
    when Strength is the field move in use)."""
    return next((i for i, ms in enumerate(party_moves(read)) if STRENGTH in ms), None)


def pending_hm(read: Read, tries: Dict[str, int], max_tries: int):
    """The first (name, item, move) of FIELD_HMS in the bag that nobody knows yet and has tries left, else None."""
    items, mons = bag(read), party_moves(read)
    return next((h for h in FIELD_HMS if h[1] in items and not any(h[2] in ms for ms in mons)
                 and tries.get(h[0], 0) < max_tries), None)


def compat(rows: List[str]) -> List[Optional[bool]]:
    """Per party row on the 'teach to which Pokémon?' screen: True (APTE), False (PAS APTE), None (no Pokémon)."""
    out = []
    for i in range(6):
        t = rows[2 * i + 1] if 2 * i + 1 < len(rows) else ""
        out.append(False if "PAS APTE" in t else True if "APTE" in t else None)
    return out


def pick_learner(flags: List[Optional[bool]], moves: List[List[int]], levels: List[int], tried=()) -> Optional[int]:
    """The compatible Pokémon losing least by it: one with a free move slot first, then the lowest level
    (the strongest keep their moves). An HM move cannot be forgotten later, so it should sit on a spare."""
    ok = [i for i, f in enumerate(flags) if f and i < len(moves) and i not in tried]
    return min(ok, key=lambda i: (len(moves[i]) >= 4, levels[i], i)) if ok else None


def entries(rows: List[str], col: int = 13) -> List[str]:
    """The words of a vertical menu box on the right (rows top to bottom): field moves, STATS, ORDRE, RETOUR."""
    out = []
    for r in rows:
        t = r[col:col + 6].strip(". ")
        if t.isalpha() and len(t) >= 4:
            out.append(t)
    return out


def start_entry(rows: List[str], word: str) -> Optional[int]:
    """Index of the START menu entry whose label holds `word` (rows 2, 4, 6 ...)."""
    for i in range(8):
        if 2 * i + 2 < len(rows) and word in rows[2 * i + 2][12:]:
            return i
    return None


def menu_open(rows: List[str]) -> bool:
    return any(w in r for r in rows for w in MENU_WORDS)


# --- the menu trips (they take the runner for its io and reads) --------------------------------------
def look(r) -> List[str]:
    if hasattr(r.io, "refresh"):
        r.io.refresh()
    return screen_rows(r.read)


def press(r, key: str, wait: int = 350) -> None:
    r.io.press(key, 90)
    r.io.wait(wait)


def goto(r, index: int, base: int = 0, current=None) -> None:
    """Move a vertical cursor (menu_item + `base`) onto `index`, reading it back; the caller presses A. BUG-0711: up to
    a full bag's 20 entries plus a few slow reads (14 moves stopped short of the 19th item and tossed another)."""
    for _ in range(26):
        look(r)
        at = base + r.read(ADDR["menu_item"])[0] if current is None else current()
        if at == index:
            return
        press(r, battle.keys_to_menu_item(at, index)[0], 250)


def close_menus(r) -> None:
    """B (A on a text) until no menu is left on screen."""
    for _ in range(12):
        rows = look(r)
        if not text_box_open(r.read) and not menu_open(rows):
            return
        press(r, "A" if text_box_open(r.read) and not menu_open(rows) else "B", 350)


def open_start_entry(r, word: str) -> bool:
    """START, then the entry whose label holds `word` (POK.MON, OBJET), A."""
    for _ in range(3):
        rows = look(r)
        idx = start_entry(rows, word)
        if idx is not None and "SAUVER" in " ".join(rows):
            goto(r, idx)
            press(r, "A", 600)
            return True
        close_menus(r)
        press(r, "START", 300)
        for _ in range(8):   # the menu may be slow to draw: another START now would close it
            if "SAUVER" in " ".join(look(r)):
                break
            r.io.wait(200)
    return False


def bag_cursor(r) -> int:
    return r.read(LIST_OFFSET)[0] + r.read(ADDR["menu_item"])[0]


def teach_hm(r, name: str, item: int, move: int) -> Optional[int]:
    """START, OBJET, the HM, UTILISER, yes, then the Pokémon to teach; the move-forget questions are answered
    by the runner's own learn_tick. Returns the party index taught (None when nobody can learn it)."""
    if not open_start_entry(r, "OBJET"):
        return None
    items = list(bag(r.read))
    goto(r, items.index(item), current=lambda: bag_cursor(r))
    press(r, "A", 500)   # the item's box (UTILISER / JETER): UTILISER is first
    press(r, "A", 800)
    chosen = None
    for _ in range(40):
        rows = look(r)
        if r.learn_tick():
            continue
        if "Capsule" in learn.lower_text(r.read):
            flags = compat(rows)
            moves = party_moves(r.read)
            levels = [p["level"] for p in r.party()]
            chosen = pick_learner(flags, moves, levels, r.memo.get(f"{name}_tried", []))
            if chosen is None:
                break
            goto(r, chosen)
            press(r, "A", 900)
            r.memo.setdefault(f"{name}_tried", []).append(chosen)
            continue
        if any(move in ms for ms in party_moves(r.read)) and not text_box_open(r.read):
            break
        press(r, "A" if text_box_open(r.read) else "B", 600)
    close_menus(r)
    return chosen if any(move in ms for ms in party_moves(r.read)) else None


def use_cut(r) -> bool:
    """START, POKéMON, the Cut user, COUPE in its field-move box. True when the menus are closed again."""
    return use_field_move(r, cut_user(r.read), "COUPE")


def use_surf(r) -> bool:
    """START, POKéMON, the Surf user, SURF in its field-move box: facing water, the player gets on it (BUG-0681)."""
    return use_field_move(r, surf_user(r.read), "SURF")


def use_strength(r) -> bool:
    """START, POKéMON, the Strength user, FORCE in its field-move box: facing a boulder, the player can
    push it. BUG-0874: pressing A on the boulder alone does not move it - the field move has to be the
    one in use, and the runner used to press A and walk into the boulder, which the game answers with
    "the boulder won't budge"."""
    return use_field_move(r, strength_user(r.read), "FORCE")


def use_field_move(r, who: Optional[int], word: str) -> bool:
    """START, POKéMON, party member `who`, `word` in its field-move box. True when the menus are closed again."""
    if who is None or not open_start_entry(r, "POK.MON"):
        close_menus(r)
        return False
    goto(r, who)
    press(r, "A", 600)
    words = entries(look(r))
    if word not in words:
        close_menus(r)
        return False
    goto(r, words.index(word))
    press(r, "A", 900)
    for _ in range(14):   # the texts of the move, the tree falling; any menu left (it could not be used) is closed
        rows = look(r)
        if text_box_open(r.read) and not menu_open(rows):
            press(r, "A", 500)
        elif menu_open(rows):
            press(r, "B", 400)
        else:
            break
    close_menus(r)
    return True



def use_flute(r) -> bool:
    """START, OBJET, the Poké Flute, UTILISER: facing a sleeping Pokémon this wakes it (it attacks: the runner's
    battle ticks take over). True when the item was used and the menus are closed again (or a battle began)."""
    return use_item(r, POKE_FLUTE)


def use_item(r, item: int) -> bool:
    """START, OBJET, `item`, UTILISER, then its texts until they end or a battle begins (the flute's woken Snorlax,
    a rod's bite: BUG-0673). True when the item was used and the menus are closed again (or a battle began)."""
    if item not in bag(r.read) or not open_start_entry(r, "OBJET"):
        close_menus(r)
        return False
    goto(r, list(bag(r.read)).index(item), current=lambda: bag_cursor(r))
    press(r, "A", 500)   # the item's box (UTILISER / JETER): UTILISER is first
    press(r, "A", 900)
    for _ in range(16):   # the item's texts, then maybe the battle starts
        look(r)
        if r.read(ADDR["in_battle"])[0]:
            return True
        if text_box_open(r.read):
            press(r, "A", 500)
        else:
            break
    close_menus(r)
    return True


def tossable(items) -> Optional[int]:
    """An item in the bag that the game lets us throw away (see TOSSABLE), else None."""
    return next((i for i in TOSSABLE if i in items), None)


def toss_item(r) -> Optional[int]:
    """START, OBJET, a tossable item, JETER (second entry of its box), yes: frees one bag slot. Returns the item tossed or None."""
    items = list(bag(r.read))
    item = tossable(items)
    if item is None or not open_start_entry(r, "OBJET"):
        close_menus(r)
        return None
    goto(r, items.index(item), current=lambda: bag_cursor(r))
    press(r, "A", 500)
    press(r, "DOWN", 250)   # UTILISER / JETER
    press(r, "A", 600)
    if bag(r.read).get(item, 0) > 1:
        press(r, "DOWN", 250)   # BUG-0711: the quantity box starts at 1; down wraps to all of them, the slot is freed
    for _ in range(8):   # a quantity box (A tosses one) and "Jeter?" (the cursor starts on OUI)
        look(r)
        if item not in bag(r.read):
            break
        press(r, "A", 500)
    close_menus(r)
    return item if item not in bag(r.read) else None
