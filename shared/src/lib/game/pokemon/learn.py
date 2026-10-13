"""
Move learning: the "forget a move to learn a new one" question of a full Pokémon (French Gen 1).

The game asks in steps: "Oublier une attaque pour apprendre X?" OUI/NON, then the list "Oublier quelle
attaque?", or after NON "Ne pas apprendre X?" OUI/NON (OUI = the new move is dropped). The harness
answers on purpose: facts as options for a decision model (Jev), a heuristic without one.
The new move's id is in wMoveNum and the learner's party index in wWhichPokemon (both checked on the French ROM).
"""

from typing import Dict, List, Optional

from .memory import Read, screen_rows
from .names import move_en
from .rom import TYPE_NAMES, GameData

NEW_MOVE = 0xD11E + 5          # wMoveNum: the move being learned
LEARNER = 0xCF92 + 5           # wWhichPokemon: party index of the Pokémon learning it
HM_MOVES = {15, 19, 57, 70, 148}   # Cut, Fly, Surf, Strength, Flash: the game refuses to delete them
INSTRUCTIONS = ("Choose which move to forget, if any, to learn the new move; the party needs strong damaging "
                "moves of varied types. Damaging moves matter more than status moves, above all for a party of "
                "one or two Pokémon.")


def lower_text(read: Read) -> str:
    """The lower text box's rows joined (what the question says)."""
    return " ".join(r[1:19].strip() for r in screen_rows(read)[13:17] if r[1:19].strip())


def yes_no_open(read: Read) -> bool:
    """The OUI / NON box is on screen (top right of the text box)."""
    right = [r[14:] for r in screen_rows(read)[5:12]]
    return any("OUI" in r for r in right) and any("NON" in r for r in right)


def stage(read: Read) -> str:
    """'ask' (forget a move for the new one?), 'abandon' (not learn it?), 'list' (which move?), 'wait' (the
    question is typed but the OUI / NON box is not drawn yet: an A now would be lost) or ''."""
    text = lower_text(read)
    if "Oublier quelle" in text:
        return "list"
    if "apprendre" not in text or not text.endswith("?"):
        return ""
    if not yes_no_open(read):
        return "wait"
    return "abandon" if "Ne pas" in text else "ask"


def move_facts(data: GameData, move_id: int, pp_left: Optional[int] = None, pp_ups: int = 0) -> Dict:
    mv = data.move(move_id)
    pp_max = mv["pp"] + pp_ups * max(1, mv["pp"] // 5)
    return {"move_id": move_id, "name": data.move_name(move_id), "name_en": move_en(move_id),
            "type": TYPE_NAMES.get(mv["type"], hex(mv["type"])), "power": mv["power"], "type_id": mv["type"],
            "accuracy_pct": mv["accuracy"], "pp_left": pp_max if pp_left is None else pp_left, "pp_max": pp_max,
            "status_move": mv["power"] == 0}


def learner(read: Read, data: GameData, base: int, index: int) -> Dict:
    """The learner from its party struct: types, the 4 moves with PP, and the new move."""
    raw = read(base + 0x2C * index, 0x2C)
    return {"types": list(dict.fromkeys(raw[5:7])), "level": raw[0x21],
            "moves": [move_facts(data, m, raw[0x1D + i] & 0x3F, raw[0x1D + i] >> 6)
                      for i, m in enumerate(raw[8:12]) if m]}


def only_of_type(moves: List[Dict], m: Dict) -> bool:
    """True if `m` is damaging and no other known move of its type is."""
    return not m["status_move"] and not any(o is not m and not o["status_move"] and o["type_id"] == m["type_id"]
                                            for o in moves)


def options(moves: List[Dict], new: Dict) -> List[Dict]:
    """`keep` plus `forget<i>` for each move that may be forgotten (not an HM), each {id, kind, slot, facts}."""
    out = [{"id": "keep", "kind": "keep", "facts": {"new": new, "kept": [m["name"] for m in moves]}}]
    for slot, m in enumerate(moves):
        if m["move_id"] not in HM_MOVES:
            out.append({"id": f"forget{slot + 1}", "kind": "forget", "slot": slot, "facts": {
                **m, "only_damaging_of_type": only_of_type(moves, m), "new": new,
                "new_covers_its_type": not new["status_move"] and new["type_id"] == m["type_id"]}})
    return out


def brief(m: Dict, pp: bool = True) -> str:
    kind = "status" if m["status_move"] else f"power {m['power']}"
    return (f"{m['name']} (= {m['name_en']}; {m['type']}, {kind}, accuracy {m['accuracy_pct']}%, "
            f"PP {m['pp_left']}/{m['pp_max']})" if pp else
            f"{m['name']} (= {m['name_en']}; {m['type']}, {kind}, accuracy {m['accuracy_pct']}%, PP {m['pp_max']})")


def option_text(opt: Dict) -> str:
    f = opt["facts"]
    if opt["kind"] == "keep":
        return f"Do not learn {f['new']['name']} (= {f['new']['name_en']}): keep {', '.join(f['kept'])}."
    note = (" It is the only damaging move of its type." if f["only_damaging_of_type"] else "") + (
        " The new move has the same type." if f["new_covers_its_type"] else "")
    return f"Forget {brief(f)} to learn {brief(f['new'], pp=False)}.{note}"


def describe(name: str, mon: Dict, new: Dict) -> str:
    types = "/".join(TYPE_NAMES.get(t, hex(t)) for t in mon["types"])
    return (f"Pokémon Blue. {name}, level {mon['level']}, type {types}, knows 4 moves: "
            + "; ".join(brief(m) for m in mon["moves"]) + f". It can learn {brief(new, pp=False)}.")


def worth(m: Dict) -> float:
    """What a move is worth in battle: power x accuracy; a status move 0."""
    return 0.0 if m["status_move"] else m["power"] * m["accuracy_pct"] / 100


def heuristic_choice(opts: List[Dict]) -> str:
    """Never forget the last damaging move of a type the new move does not cover. Among the others forget
    the weakest (a status move first) if the new move is worth more; a status move is never worth more than
    a move we have (it only gets in when a move is useless), so it is declined."""
    new = next(o for o in opts if o["kind"] == "keep")["facts"]["new"]
    free = [o for o in opts if o["kind"] == "forget"
            and not (o["facts"]["only_damaging_of_type"] and not o["facts"]["new_covers_its_type"])]
    if not free or new["status_move"]:
        return "keep"
    weakest = min(free, key=lambda o: worth(o["facts"]))
    return weakest["id"] if worth(weakest["facts"]) < worth(new) else "keep"

