"""
Game data located in the ROM at run time (no game data is copied into this repo).

- Move table: 6 bytes per move (animation, effect, power, type, accuracy, PP), move 1 first. Found by
  its first two entries (Pound: 40 power, Normal, 100 %, 35 PP; Karate Chop: 50 power).
- Type chart: (attacker type, defender type, multiplier x10) triples, ending with 0xFF. Found by its
  first three entries (Water > Fire, Fire > Grass, Fire > Ice).
- Move names: 0x50-terminated strings from ROM 0xB0000 (bank 0x2C), move 1 first (French ROM:
  "ECRAS'FACE", ..., "FOUET LIANES" = Vine Whip, "CHARGE" = Tackle).
On the French ROM: move table at 0x38000, type chart at 0x3E489 (TASK-33 §00000).
"""

from typing import Dict, List, Optional, Tuple

MOVES_SIGNATURE = bytes([0x01, 0x00, 0x28, 0x00, 0xFF, 0x23, 0x02, 0x00, 0x32])
TYPES_SIGNATURE = bytes([0x15, 0x14, 0x14, 0x14, 0x16, 0x14, 0x14, 0x19, 0x14])
MOVE_COUNT = 165
MOVE_NAMES_AT = 0xB0000

TYPE_NAMES = {0x00: "Normal", 0x01: "Fighting", 0x02: "Flying", 0x03: "Poison", 0x04: "Ground", 0x05: "Rock",
              0x07: "Bug", 0x08: "Ghost", 0x14: "Fire", 0x15: "Water", 0x16: "Grass", 0x17: "Electric",
              0x18: "Psychic", 0x19: "Ice", 0x1A: "Dragon"}


class GameData:
    def __init__(self, rom: bytes):
        moves_at = rom.find(MOVES_SIGNATURE)
        types_at = rom.find(TYPES_SIGNATURE)
        if moves_at < 0 or types_at < 0:
            raise ValueError("move table or type chart not found in this ROM")
        self.moves_at, self.types_at = moves_at, types_at
        self.moves: Dict[int, dict] = {}
        for move_id in range(1, MOVE_COUNT + 1):
            anim, effect, power, mtype, acc, pp = rom[moves_at + 6 * (move_id - 1): moves_at + 6 * move_id]
            self.moves[move_id] = {"id": move_id, "effect": effect, "power": power, "type": mtype,
                                   "accuracy": round(acc * 100 / 255), "pp": pp}
        self.names: Dict[int, str] = {}
        if len(rom) > MOVE_NAMES_AT:
            from .memory import decode
            i = MOVE_NAMES_AT
            for move_id in range(1, MOVE_COUNT + 1):
                end = rom.find(b"\x50", i, i + 20)
                if end < 0:
                    break
                self.names[move_id] = decode(list(rom[i:end]))
                i = end + 1
        self.chart: Dict[Tuple[int, int], float] = {}
        i = types_at
        while rom[i] != 0xFF:
            self.chart[(rom[i], rom[i + 1])] = rom[i + 2] / 10
            i += 3

    def move_name(self, move_id: int) -> str:
        return self.names.get(move_id) or f"move {move_id}"

    def move(self, move_id: int) -> Optional[dict]:
        return self.moves.get(move_id)

    def effectiveness(self, move_type: int, defender_types: List[int]) -> float:
        mult = 1.0
        for t in dict.fromkeys(defender_types):  # a single-type Pokémon lists its type twice
            mult *= self.chart.get((move_type, t), 1.0)
        return mult
