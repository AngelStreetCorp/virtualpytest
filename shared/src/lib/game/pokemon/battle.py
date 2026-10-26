"""
Battle: state from memory, the legal options with facts, a heuristic chooser and menu key plans.

The options are what a decision model (Jev, an LLM) chooses from; the harness executes the choice by
reading the menu cursor from memory (memory.ADDR["menu_item"]), never by counting key presses blind.
"""

from math import floor
from typing import Dict, List, Optional

from .memory import ADDR, B_CATCH, B_HP, B_LEVEL, B_MOVES, B_PP, B_SPECIES, B_STATS, B_TYPES, Read, word
from .milestones import bag
from .rom import TYPE_NAMES, GameData

# Gen 1 physical types use Attack / Defense, the others Special.
PHYSICAL = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x07, 0x08}
FLEE_LEVELS_BELOW = 6   # while travelling, a wild Pokémon this many levels below ours is not worth the fight
BALLS = {0x04: "POKé BALL", 0x03: "SUPER BALL", 0x02: "HYPER BALL"}   # cheapest first: the one we throw first
CATCH_BELOW = 0.6       # the heuristic throws a ball once the wild Pokémon's HP share is at or below this
CATCH_CHANCE_MIN = 0.5  # ... or the catch chance estimate (Gen 1 formula) is at or above this
CATCH_UNSOFT_MIN = 0.25  # a ball at full HP when our only damaging move would KO it, at this chance or better
CATCH_PARTY_MAX = 2     # ... and only while the party is this small (a backup is worth the balls)
B_STATUS = 4   # status byte: bits 0-2 sleep turns, 3 poison, 4 burn, 5 freeze, 6 paralysis


def status_name(byte: int) -> str:
    if byte & 0x07:
        return "asleep"
    return next((n for bit, n in ((3, "poisoned"), (4, "burned"), (5, "frozen"), (6, "paralyzed")) if byte >> bit & 1), "")


def mon(read: Read, base: int) -> Dict:
    raw = read(base, 30)
    stats = [raw[B_STATS + 2 * i] * 256 + raw[B_STATS + 2 * i + 1] for i in range(5)]
    return {
        "species": raw[B_SPECIES], "hp": raw[B_HP] * 256 + raw[B_HP + 1], "max_hp": stats[0],
        "status": status_name(raw[B_STATUS]),
        "types": [raw[B_TYPES], raw[B_TYPES + 1]], "level": raw[B_LEVEL], "catch_rate": raw[B_CATCH],
        "attack": stats[1], "defense": stats[2], "speed": stats[3], "special": stats[4],
        "moves": [m for m in raw[B_MOVES:B_MOVES + 4]], "pp": [p & 0x3F for p in raw[B_PP:B_PP + 4]],
    }


def state(read: Read) -> Dict:
    return {"kind": {1: "wild", 2: "trainer"}.get(read(ADDR["in_battle"], 1)[0], "none"),
            "ours": mon(read, ADDR["battle_mon"]), "enemy": mon(read, ADDR["enemy_mon"])}


def expected_damage(data: GameData, attacker: Dict, defender: Dict, move: Dict) -> float:
    """Gen 1 damage formula without the random factor and critical hits."""
    if not move["power"]:
        return 0.0
    phys = move["type"] in PHYSICAL
    a = attacker["attack"] if phys else attacker["special"]
    d = max(1, defender["defense"] if phys else defender["special"])
    base = ((2 * attacker["level"] / 5 + 2) * move["power"] * a / d) / 50 + 2
    stab = 1.5 if move["type"] in attacker["types"] else 1.0
    return base * stab * data.effectiveness(move["type"], defender["types"]) * move["accuracy"] / 100


def options(read: Read, data: GameData) -> List[Dict]:
    """The legal battle options, each {id, kind, facts}."""
    st = state(read)
    ours, enemy = st["ours"], st["enemy"]
    out = []
    for slot, (move_id, pp) in enumerate(zip(ours["moves"], ours["pp"])):
        if not move_id or pp == 0:
            continue
        mv = data.move(move_id)
        dmg = expected_damage(data, ours, enemy, mv)
        out.append({"id": f"move{slot + 1}", "kind": "move", "slot": slot + 1, "facts": {
            "move_id": move_id, "type": TYPE_NAMES.get(mv["type"], hex(mv["type"])), "power": mv["power"],
            "accuracy_pct": mv["accuracy"], "pp_left": pp,
            "effectiveness": data.effectiveness(mv["type"], enemy["types"]),
            "expected_damage": round(dmg, 1),
            "expected_ko": dmg >= enemy["hp"] > 0,
            "status_move": mv["power"] == 0,
        }})
    sw = switch_option(read, data, enemy, max([o["facts"]["expected_damage"] for o in out], default=0.0))
    if sw:
        out.append(sw)
    ball = ball_to_throw(bag(read)) if st["kind"] == "wild" else None
    party = read(ADDR["party_count"], 1)[0]
    if ball and party < 6 and enemy["species"] not in read(ADDR["party_species"], min(party, 6)):
        out.append(catch_option(enemy, ball, bag(read)[ball], party))
    if st["kind"] == "wild":
        out.append({"id": "run", "kind": "run", "facts": {"note": "flee the wild battle",
                                                         "levels_below": ours["level"] - enemy["level"]}})
    return out


def party_attacker(raw: List[int]) -> Dict:
    """A party struct as the attacker dict expected_damage wants (types at +5, level +0x21, stats from +0x22)."""
    st = [raw[0x22 + 2 * i] * 256 + raw[0x23 + 2 * i] for i in range(5)]
    return {"types": [raw[5], raw[6]], "level": raw[0x21], "attack": st[1], "defense": st[2], "speed": st[3],
            "special": st[4]}


def best_damage(data: GameData, raw: List[int], enemy: Dict) -> float:
    """The best expected damage over a party member's moves that still have PP."""
    me = party_attacker(raw)
    return max([expected_damage(data, me, enemy, data.move(m)) for i, m in enumerate(raw[B_MOVES:B_MOVES + 4])
                if m and raw[PARTY_PP + i] & 0x3F], default=0.0)


def switch_option(read: Read, data: GameData, enemy: Dict, now: float) -> Optional[Dict]:
    """Switch to the party member with HP left that hurts the enemy more than twice as much as the fighter
    does (`now`: its best expected damage, 0 when it has no attacking PP left: a lone Vine Whip is gone, or
    resisted by a Grass type). The condition stops two weak members swapping for ever. None without one."""
    n, here = min(read(ADDR["party_count"], 1)[0], 6), read(ADDR["player_mon"], 1)[0]
    best = None
    for i in range(n):
        raw = read(ADDR["party_mons"] + 0x2C * i, 0x2C)
        hp, dmg = raw[1] * 256 + raw[2], best_damage(data, raw, enemy)
        if i != here and hp and dmg > 2 * now and (best is None or dmg > best[1]):
            best = (i, dmg, hp, raw[0x21])
    if not best:
        return None
    return {"id": "switch", "kind": "switch", "slot": best[0], "facts": {
        "party_index": best[0], "expected_damage": round(best[1], 1), "hp": best[2], "level": best[3]}}


def ball_to_throw(items: Dict[int, int]) -> Optional[int]:
    """The ball to throw from a bag ({item: count}): the cheapest kind we have, None without any."""
    return next((b for b in BALLS if items.get(b)), None)


def ball_row(items: Dict[int, int], ball: int) -> int:
    """The ball's row in the bag list (the bag keeps its order, one row per item)."""
    return list(items).index(ball)


def list_cursor(read: Read) -> int:
    """The absolute row of a scrolling list's cursor: the cursor within the window plus the scroll offset."""
    return read(ADDR["menu_item"], 1)[0] + read(ADDR["list_offset"], 1)[0]


def catch_chance(catch_rate: int, hp: int, max_hp: int, ball: int, status: str = "") -> float:
    """Gen 1 (Red/Blue) capture probability for one throw of a ball at an enemy Pokémon; `status` is the enemy's."""
    if ball == 0x01:                                                                    # always catches
        return 1.0
    s = 25 if status in ("asleep", "frozen") else 12 if status in ("paralyzed", "burned", "poisoned") else 0
    n = {0x04: 255, 0x03: 200, 0x02: 150}.get(ball, 255)                                # Poké / Great / Ultra range
    n1 = n + 1
    p_first = s / n1                                                                    # P(R1 < s)
    p_continue = (min(s + catch_rate, n) - s + 1) / n1                                  # P(s <= R1 <= s + catch_rate)
    g = 8 if ball == 0x03 else 12                                                       # Great Ball modifier
    f = min(floor(max_hp * 255 / g) // max(1, hp // 4), 255)                            # integer maths, as the game does
    p_second = (f + 1) / 256                                                            # P(R2 <= f) on 256 values
    return max(0.0, min(1.0, round(p_first + p_continue * p_second, 2)))


def catch_option(enemy: Dict, ball: int, balls_left: int, party: int) -> Dict:
    """The option 'throw a ball at the wild Pokémon', with the facts a decision model needs."""
    return {"id": "catch", "kind": "catch", "ball": ball, "facts": {
        "ball": BALLS[ball], "balls_left": balls_left,
        "enemy_hp_share": round(enemy["hp"] / max(1, enemy["max_hp"]), 2), "enemy_level": enemy["level"],
        "enemy_types": [TYPE_NAMES.get(t, hex(t)) for t in dict.fromkeys(enemy["types"])],
        "catch_rate": enemy["catch_rate"], "party_size": party,
        "catch_chance": catch_chance(enemy["catch_rate"], enemy["hp"], enemy["max_hp"], ball, enemy.get("status", "")),
        "note": "a species not in the party yet; a second Pokémon is a backup when the leader faints and can "
                "cover more types"}}


def names(read: Read) -> Dict[str, str]:
    """The two Pokémon names as the battle screen shows them (row 0: enemy, row 7: ours)."""
    from .memory import screen_rows
    rows = screen_rows(read)
    return {"enemy": rows[0].strip(" .") or "?", "ours": rows[7].strip(" .") or "?"}


def describe(read: Read) -> str:
    """The battle state as text, for a decision model."""
    st, nm = state(read), names(read)

    def side(label, m, name):
        types = "/".join(dict.fromkeys(TYPE_NAMES.get(t, hex(t)) for t in m["types"]))
        return (f"{label}: {name} level {m['level']}, HP {m['hp']}/{m['max_hp']}, type {types}, speed {m['speed']}"
                + (f", {m['status']}" if m["status"] else ""))
    return (f"Pokémon Blue, {st['kind']} battle. " + side("Ours", st["ours"], nm["ours"]) + ". "
            + side("Enemy", st["enemy"], nm["enemy"]) + ".")


def option_text(opt: Dict) -> str:
    f = opt["facts"]
    if opt["kind"] == "catch":
        chance_pct = int(round(100 * f["catch_chance"]))
        return (f"Throw a {f['ball']} ({f['balls_left']} left), estimated catch chance {chance_pct} %, to catch this new "
                f"species: HP share {f['enemy_hp_share']:g} (lower is easier), level {f['enemy_level']}, type "
                f"{'/'.join(f['enemy_types'])}, catch rate {f['catch_rate']} of 255, party of {f['party_size']}. A second "
                f"Pokémon is a backup when the leader faints and can cover more types.")
    if opt["kind"] == "switch":
        return (f"Switch to the party member in slot {f['party_index'] + 1} (level {f['level']}, HP {f['hp']}), expected damage "
                f"{f['expected_damage']}: the fighter does far less (or has no attacking PP left).")
    if opt["kind"] == "run":
        below = f.get("levels_below", 0)
        return "Run away from this wild battle." + (
            f" The enemy is {below} levels below ours: little experience for the PP and HP it costs." if below >= FLEE_LEVELS_BELOW else "")
    if f["status_move"]:
        return (f"Status move (no damage), {f['type']}, accuracy {f['accuracy_pct']}%, PP left {f['pp_left']}.")
    return (f"Attack: {f['type']}, power {f['power']}, accuracy {f['accuracy_pct']}%, PP left {f['pp_left']}, "
            f"effectiveness x{f['effectiveness']:g}, expected damage {f['expected_damage']}"
            + (", likely knocks the enemy out" if f["expected_ko"] else "") + ".")


def heuristic_choice(opts: List[Dict], our_hp_share: float = 1.0, last: Optional[str] = None,
                     travelling: bool = False, must_catch: bool = False) -> Optional[str]:
    """Baseline: run from a wild battle below 30 % HP; catch a new species while the party is small once
    it is weak enough (until then attack gently to weaken it); while travelling (not training) run from a
    wild Pokémon far below our level (a cave's Zubats: little experience, PP and HP spent); else the move
    with the highest expected damage; with no damaging move left, run from a wild battle, or use a status
    move other than the last one. `must_catch` (BUG-0673: the Surf learner the party lacks) wants the catch at
    any party size."""
    run = next((o for o in opts if o["kind"] == "run"), None)
    can_run = run is not None
    if can_run and our_hp_share < 0.3:
        return "run"
    moves = [o for o in opts if o["kind"] == "move"]
    wanted = next((o for o in opts if o["kind"] == "catch" and (must_catch or o["facts"]["party_size"] <= CATCH_PARTY_MAX)), None)
    if wanted and (wanted["facts"]["enemy_hp_share"] <= CATCH_BELOW
                   or wanted["facts"].get("catch_chance", 0) >= CATCH_CHANCE_MIN):
        return "catch"
    if can_run and travelling and not wanted and run["facts"].get("levels_below", 0) >= FLEE_LEVELS_BELOW:
        return "run"
    if any(o["kind"] == "switch" for o in opts):
        return "switch"   # offered only when the member hurts the enemy more than twice as much
    if not moves:
        return "catch" if wanted else (opts[0]["id"] if opts else None)
    best = max(moves, key=lambda o: o["facts"]["expected_damage"])
    if wanted and best["facts"]["expected_damage"] > 0:
        # weaken, not kill: the weakest damaging move that leaves the enemy standing
        soft = [o for o in moves if 0 < o["facts"]["expected_damage"] and not o["facts"]["expected_ko"]]
        if soft:
            return min(soft, key=lambda o: o["facts"]["expected_damage"])["id"]
        # every damaging move would KO (a lone Vine Whip against a level 8): a ball now, not a KO
        return "catch" if wanted["facts"].get("catch_chance", 0) >= CATCH_UNSOFT_MIN else best["id"]
    if best["facts"]["expected_damage"] > 0:
        return best["id"]
    if can_run:
        return "run"
    others = [o for o in moves if o["id"] != last] or moves
    return others[0]["id"]


PARTY_PP = 0x1D  # PP in a party struct (the battle struct has them at B_PP = 25)


def damaging_pp_left(read: Read, data: GameData, mon_base: int, pp_offset: int = PARTY_PP) -> int:
    """PP left on the moves that do damage, for a party struct (default) or a battle struct
    (pp_offset=B_PP); both have the moves at +8."""
    raw = read(mon_base, 0x2C)
    return sum(raw[pp_offset + i] & 0x3F for i, m in enumerate(raw[B_MOVES:B_MOVES + 4]) if m and data.move(m)["power"])


def main_menu_open(read: Read) -> bool:
    """The FIGHT / PKMN / ITEM / RUN menu is on screen (cursor column 7 or 13 at text row 14)."""
    from .memory import screen_rows
    rows = screen_rows(read)
    return any("ATTAQ" in r for r in rows[12:18])


def safari_menu_open(rows: List[str]) -> bool:
    """The Safari battle menu (BALL / APPAT over CAILLOU / FUITE) is on screen."""
    return len(rows) > 16 and "APPAT" in rows[14] and "FUITE" in rows[16]


def party_text(read: Read) -> str:
    """The lower box's text, rows joined (a phrase wraps over two rows)."""
    from .memory import screen_rows
    return " ".join(r[1:19].strip() for r in screen_rows(read)[13:17] if r[1:19].strip())


def party_select(read: Read) -> bool:
    """The party list is open to choose who fights ("Faire combattre quel POKéMON?"), after a faint. A fainted
    pick is refused ("Il ne veut pas combattre") and the same list comes back."""
    return "Faire combattre quel POK" in party_text(read)


def first_alive(read: Read, data: Optional[GameData] = None) -> Optional[int]:
    """The party index of the first Pokémon with HP left, None if none. With `data`, one that still has
    attacking PP comes first (a leader with none would fight on with status moves)."""
    n = min(read(ADDR["party_count"], 1)[0], 6)
    alive = [i for i in range(n) if any(read(ADDR["party_mons"] + 0x2C * i + 1, 2))]
    armed = [i for i in alive if data and damaging_pp_left(read, data, ADDR["party_mons"] + 0x2C * i)]
    return (armed or alive or [None])[0]


def move_list(read: Read) -> str:
    """What the move list's side box says when the list is left open after a refused move: "no pp" (the
    TYPE/ box; "/" decodes as ".") or "disabled" (NON DISP., the move was hit by Disable); "" if closed."""
    from .memory import screen_rows
    rows = screen_rows(read)[7:12]
    if any("NON DISP" in r for r in rows):
        return "disabled"
    return "no pp" if any("TYPE" in r for r in rows) else ""


def keys_to_menu_item(current: int, target: int) -> List[str]:
    """UP / DOWN presses to move a vertical cursor from `current` to `target`."""
    return (["DOWN"] * (target - current)) if target > current else (["UP"] * (current - target))


def outcome(fled: bool, party_hp_left: int) -> str:
    """Pure: 'lost' if no HP left, else 'fled' if the run attempt went through, else 'won'."""
    if party_hp_left == 0:
        return "lost"
    return "fled" if fled else "won"
