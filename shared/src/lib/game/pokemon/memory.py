"""
Memory map of Pokémon Blue, French version, as verified on the owner's ROM (TASK-33 §00000).

The community (US) addresses apply with a +5 byte shift from the CF.. area onwards; the screen tile
map and the joypad-ignore flag are not shifted. Every address here was checked on the French ROM;
never assume a US address without checking it.

All helpers take `read(addr, n) -> list[int]`, so they work on the emulator page (execute_javascript)
and on plain bytes in tests.
"""

from typing import Callable, Dict, List

Read = Callable[[int, int], List[int]]

SHIFT = 5
ADDR = {
    "tilemap": 0xC3A0,             # 20 x 18 screen tiles (not shifted)
    "menu_item": 0xCC26,           # wCurrentMenuItem: battle menu row, move slot (1-based) (not shifted)
    "list_offset": 0xCC36,         # wListScrollOffset: first visible entry of a scrolling list (bag, shop) (not shifted)
    "menu_cursor_x": 0xCC25,       # cursor column on the battle menu: 7 left, 13 right
    "joy_ignore": 0xCD6B,          # wJoyIgnore: 0xFC while a cutscene owns the controls (not shifted)
    "enemy_mon": 0xCFE5 + SHIFT,   # wEnemyMon (battle struct)
    "in_battle": 0xD057 + SHIFT,   # wIsInBattle: 0 no, 1 wild, 2 trainer
    "battle_mon": 0xD014 + SHIFT,  # wBattleMon (battle struct)
    "player_name": 0xD158 + SHIFT,
    "player_mon": 0xCC2F,          # wPlayerMonNumber: party index of the Pokémon fighting (not shifted)
    "party_count": 0xD163 + SHIFT,
    "party_species": 0xD164 + SHIFT,
    "party_mons": 0xD16B + SHIFT,  # 6 x 44-byte party structs
    "rival_name": 0xD34A + SHIFT,
    "map": 0xD35E + SHIFT,
    "y": 0xD361 + SHIFT,
    "x": 0xD362 + SHIFT,
}

# Battle struct (wBattleMon / wEnemyMon) offsets.
B_SPECIES, B_HP, B_STATUS, B_TYPES, B_CATCH, B_MOVES, B_LEVEL, B_STATS, B_PP = 0, 1, 4, 5, 7, 8, 14, 15, 25
TEXT_BOX_TOP_LEFT, TEXT_BOX_BOTTOM_LEFT = 0x79, 0x7D
PUNCT = {0x7F: " ", 0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";", 0xE0: "'", 0xE3: "-", 0xE6: "?", 0xE7: "!",
         0xE8: ".", 0xF4: ","}


def char(b: int) -> str:
    """One Gen 1 character; unknown codes (French accents, symbols) become '.'."""
    if 0x80 <= b <= 0x99:
        return chr(ord("A") + b - 0x80)
    if 0xA0 <= b <= 0xB9:
        return chr(ord("a") + b - 0xA0)
    if 0xF6 <= b <= 0xFF:
        return str(b - 0xF6)
    return PUNCT.get(b, ".")


def decode(bs: List[int]) -> str:
    out = []
    for b in bs:
        if b == 0x50:  # string terminator
            break
        out.append(char(b))
    return "".join(out)


def word(read: Read, addr: int) -> int:
    hi, lo = read(addr, 2)
    return hi * 256 + lo


def screen_rows(read: Read) -> List[str]:
    tiles = read(ADDR["tilemap"], 360)
    return ["".join(char(b) for b in tiles[r * 20:(r + 1) * 20]) for r in range(18)]


def text_box_open(read: Read) -> bool:
    tiles = read(ADDR["tilemap"], 360)
    return tiles[12 * 20] == TEXT_BOX_TOP_LEFT and tiles[17 * 20] == TEXT_BOX_BOTTOM_LEFT


def text_box(read: Read) -> str:
    """The text inside the bottom text box, rows joined with ' / '."""
    rows = screen_rows(read)
    return " / ".join(r[1:19].strip() for r in rows[13:17] if r[1:19].strip())


def busy(read: Read) -> bool:
    """A text box is open or a cutscene owns the controls."""
    return text_box_open(read) or read(ADDR["joy_ignore"], 1)[0] != 0


def overworld(read: Read) -> Dict[str, int]:
    return {k: read(ADDR[k], 1)[0] for k in ("map", "x", "y", "party_count", "in_battle")}
