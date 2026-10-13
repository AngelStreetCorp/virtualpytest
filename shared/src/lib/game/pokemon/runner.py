"""
The Pokémon Blue game loop: one action per tick, decided from the game's memory.

Each tick:
- **battle**: on the FIGHT menu, build the options (battle.options) and ask the chooser; else advance
  the battle text;
- **text box**: advance it with A (B for "give a nickname?": the harness never nicknames);
- **cutscene** (wJoyIgnore): wait;
- **overworld**: one A* step toward the next map of the current milestone's route (an edge or a
  warp), or the milestone's action on its goal map (talk to Oak).

IO (VirtualPyTest executors on a host, or Playwright locally) provides:
read(addr, n) -> list[int], press(key, hold_ms), wait(ms), and optionally save_state() -> str.
`choose(state_text, options, instructions) -> {choice, ...}` decides battles (Jev, an LLM or the
heuristic). Every decision and milestone is logged in `self.log` for the report and the strategist.
"""

import random
import time
from typing import Callable, Dict, List, Optional

from . import battle, gym, hm, learn, names, overworld, shop, strategy
from .memory import ADDR, busy, decode, screen_rows, text_box, text_box_open
from .milestones import (CERULEAN_MART, FUCHSIA_CENTER, GAME_CORNER, LAVENDER_CENTER, OAKS_LAB, PEWTER_MART, POKE_FLUTE, ROCKET_B4F,
                         ROCKET_HIDEOUT, ROCKET_LIFT, ROUTE2, ROUTE4, ROUTE24, TOWER_6F, TOWER_7F, VERMILION_GYM, VIRIDIAN_FOREST,
                         VIRIDIAN_MART, badges, bag, current)
from .rom import GameData
from .world import ANY_MAP, OPPOSITE, World, hop_target, links

OAK_PICTURE = 3
MOM_PICTURE = 51          # in the player's house, ground floor (map 0x25); heals the party
PLAYERS_HOUSE_1F = 0x25
BILLS_PC_SPOT = (1, 5)  # Bill's house: below the PC (1, 4), facing up, starts the cell separator
STARTER_BALL = (8, 3)   # Oak's lab: Bulbasaur's Poké Ball
POKEMON_CENTERS = (0x29, 0x3A, 0x44, 0x40, 0x59, 0x51, 0x85, LAVENDER_CENTER, FUCHSIA_CENTER)  # Viridian, Pewter, Mt. Moon (Route 4), Cerulean, Vermilion, Route 10, Celadon, Lavender, Fuchsia: the nurse heals behind the counter
MARTS = (VIRIDIAN_MART, PEWTER_MART, CERULEAN_MART)   # Poké Marts; known once a town's door was seen from outside
SHOP_BELOW_PARTY = 3      # shop for balls while the party has fewer Pokémon than this and none are in the bag
SHOP_MIN_MONEY = 1000     # ... with at least this much money
SHOP_GIVE_UP_TICKS = 600  # ticks of one shopping errand before it is dropped (a mart we cannot work)
PARTY_STRUCT = 0x2C       # bytes per party Pokémon; current HP at +1, max HP at +0x22
HEAL_BELOW = 0.4          # go and heal when the party's HP falls below this share
HEAL_PP_BELOW = 5         # ... or when the party's attacking moves have fewer PP left than this
HEAL_FORCED_BELOW = 0.15  # below this HP share (or with 0 attacking PP) healing is forced, no question
MONEY = 0xD347 + 5        # 3 bytes BCD; a blackout halves it (a defeat)
PARTY_NICKS = 0xD2B5 + 5  # 11 bytes per Pokémon; the species name unless nicknamed
BLOCKER_TALKS_MAX = 3     # after this many talks to the same blocker square, treat it as a wall
GRIND_MAPS = (VIRIDIAN_FOREST, ROUTE2, ROUTE24, ROUTE4)   # after Misty the party is at Cerulean: Route 24 (wild level 8-14), else Route 4
GRIND_STALL_S = 240      # seconds of training without experience gained before the target is dropped as hopeless
RECRUIT_PARTY = 2         # a `prepare` milestone wants this many Pokémon first
RECRUIT_GIVE_UP_TICKS = 700
CUT_TRIES = 3               # attempts to teach HM01 before it is given up
GUIDE = "guide_i"
POSTER_GUARD, POSTER_SPOT = (9, 5), (9, 5)   # Game Corner: the guard stands on the square in front of the poster (9, 4)
LIFT_KEY_BALL, LIFT_KEY_GUARD = (10, 2), (11, 2)   # B4F's north-west room: the ball with the Lift Key and the Rocket next to it
NO_ROUTE_TICKS = 8   # ticks without any route before the map entered is taken for a dead end
SNORLAX_PICTURE = 67   # the sleeping Snorlax's sprite on Route 12 (Route 16's looks the same)
LIFT_PANEL_SPOT, LIFT_DOOR_SPOT = (1, 2), (2, 2)   # Rocket elevator: below the panel, below the door
WING_GUARDS, GIOVANNI_AT, GIOVANNI_SIDE, GIOVANNI_BALL = [(23, 12), (26, 12)], (25, 3), (25, 4), (25, 2)   # B4F, Giovanni's half
POSTER_STAIRS, STAIRS_OPEN_BLOCK = (17, 4), 67   # the stairs square; its map block once the switch is pressed (42 before; verified)


def heal_options(hp: int, max_hp: int, attack_pp: int, heal_place, heal_maps, goal: str, goal_maps,
                 opponent_levels) -> tuple:
    """The state text and decision options Jev sees when the party is low but not in danger: heal now or
    push on. Pure; distances are `len(route)` and "unknown" when a route is not known."""
    state = (f"Pokémon Blue, travelling. Party HP {hp}/{max_hp}, attacking PP left {attack_pp}. "
             f"Goal: {goal}. Levels of the last opponents: "
             + (", ".join(str(x) for x in opponent_levels) if opponent_levels else "(none)")
             + ".")

    def _d(n):
        return str(n) if isinstance(n, int) else "unknown"
    heal_dist = _d(heal_maps)
    total_dist = _d(goal_maps + heal_maps) if isinstance(heal_maps, int) and isinstance(goal_maps, int) else "unknown"
    heal_facts = (f"Go and heal at {heal_place}, {heal_dist} map(s) away; the goal is then {total_dist} "
                  f"maps of travel.")
    push_facts = (f"Keep going to the goal, {_d(goal_maps)} map(s) away, with HP {hp}/{max_hp} and "
                  f"{attack_pp} attacking PP; a lost battle sends the party back to the last Pokémon "
                  f"Center and halves the money.")
    return state, [{"id": "heal", "facts": heal_facts}, {"id": "push", "facts": push_facts}]


def prev_exits(entry: Dict, prev: Dict, dead) -> List[List[int]]:
    """The exits [map, x, y] of the map before, along its edge, that lead to the `dead` squares of the edge
    entered: the two edges line up by the shift seen on the crossing (exit square to landing square)."""
    side, (ex, ey), (lx, ly) = entry["side"], entry["exit"], entry["landing"]
    if side in ("west", "east"):
        x = 0 if side == "west" else prev["width"] - 1
        return [[entry["from"], x, y] for y in sorted({q[1] - (ly - ey) for q in dead})]
    y = 0 if side == "north" else prev["height"] - 1
    return [[entry["from"], x, y] for x in sorted({q[0] - (lx - ex) for q in dead})]


def no_battle() -> Dict:
    """The empty in-progress battle state kept in memo["battle"]."""
    return {"ids": [], "turns": 0, "kind": None, "last": None, "wiped": False}


class SnapshotIO:
    """Serve the runner's many memory reads from one work-RAM snapshot per tick.

    `io.wram()` returns C000-DFFF (8 KB) in one call; a press or a wait invalidates the snapshot. On a
    host every call is an executor action (~25 ms), so this turns dozens of calls per tick into one."""

    BASE, SIZE = 0xC000, 0x2000

    def __init__(self, io):
        self.io, self.mem = io, None

    def read(self, addr, n=1):
        if not (self.BASE <= addr and addr + n <= self.BASE + self.SIZE):
            return self.io.read(addr, n)
        if self.mem is None:
            self.mem = self.io.wram()
        return self.mem[addr - self.BASE:addr - self.BASE + n]

    def press(self, key, hold_ms=90):
        self.mem = None
        self.io.press(key, hold_ms)

    def wait(self, ms):
        self.mem = None
        self.io.wait(ms)

    def refresh(self):
        self.mem = None


class Runner:
    learn_choice: Optional[Dict] = None         # the decision on the current forget-a-move question
    thrown = 0                                  # balls thrown in the current battle
    no_route_ticks = 0                          # consecutive ticks without a route to the next map
    lift_floor_set = False                      # the elevator's floor was chosen on this ride
    mat_map, mat = None, {}                     # warps stepped off so far on this map: {warp: tries}
    catch_target: Optional[Dict] = None         # the wild Pokémon they went to: species, name, party size before

    def __init__(self, io, rom: bytes, choose: Optional[Callable] = None, memo: Optional[Dict] = None,
                 world: Optional[World] = None, complete: Optional[Callable] = None,
                 on_battle_end: Optional[Callable] = None):
        self.io, self.rom, self.data = io, rom, GameData(rom)
        self.choose = choose
        self.complete = complete  # complete(prompt, system) -> text, for the strategist
        self.on_battle_end = on_battle_end  # on_battle_end(decision_ids, outcome) -> None
        self.memo = memo if memo is not None else {}
        self.world = world or World()
        self.log: List[Dict] = []
        self.stuck = 0
        self._last_tick = 0.0   # play-time accounting (a stop between runs does not count)
        self.disabled = None     # the move hit by Disable in the current battle
        # the in-progress battle lives in the memo so a run that ends mid-battle saves it with
        # json.dump; the next run, built from the loaded memo, finishes the battle (calls
        # on_battle_end with the saved decision ids)
        self.memo.setdefault("battle", no_battle())

    def _battle(self) -> Dict:
        """The battle-state dict in `self.memo["battle"]`, created with the empty default on first
        access. Reset = replace the dict with the empty default (not field-by-field)."""
        return self.memo.setdefault("battle", no_battle())

    @property
    def battle_ids(self) -> List[Optional[str]]:
        """Decision ids of the current battle, in order."""
        return self._battle()["ids"]

    @battle_ids.setter
    def battle_ids(self, v: List[Optional[str]]) -> None:
        self._battle()["ids"] = v

    @property
    def battle_turns(self) -> int:
        """Choices made in the current battle."""
        return self._battle()["turns"]

    @battle_turns.setter
    def battle_turns(self, v: int) -> None:
        self._battle()["turns"] = v

    @property
    def battle_kind(self) -> Optional[str]:
        """`"wild"` or `"trainer"`, remembered for battle_end."""
        return self._battle()["kind"]

    @battle_kind.setter
    def battle_kind(self, v: Optional[str]) -> None:
        self._battle()["kind"] = v

    @property
    def last_choice_kind(self) -> Optional[str]:
        """`"move"` or `"run"`, the last choice of the just-ended battle."""
        return self._battle()["last"]

    @last_choice_kind.setter
    def last_choice_kind(self, v: Optional[str]) -> None:
        self._battle()["last"] = v

    @property
    def battle_wiped(self) -> bool:
        """The party hit 0 HP during this battle (a blackout heals it before we look)."""
        return self._battle()["wiped"]

    @battle_wiped.setter
    def battle_wiped(self, v: bool) -> None:
        self._battle()["wiped"] = v

    # --- helpers -----------------------------------------------------------------------------
    def read(self, addr, n=1):
        return self.io.read(addr, n)

    def pos(self):
        return self.read(ADDR["x"])[0], self.read(ADDR["y"])[0]

    def step(self, direction: str) -> bool:
        before = (self.read(ADDR["map"])[0],) + self.pos()
        self.io.press(direction, 180)
        self.io.wait(150)
        after = (self.read(ADDR["map"])[0],) + self.pos()
        return before != after

    def party_hp(self):
        n = self.read(ADDR["party_count"])[0]
        cur = tot = 0
        for i in range(min(n, 6)):
            m = self.read(ADDR["party_mons"] + PARTY_STRUCT * i, PARTY_STRUCT)
            cur += m[1] * 256 + m[2]
            tot += m[0x22] * 256 + m[0x23]
        return cur, tot

    def attack_pp(self) -> int:
        """Attacking PP left on the Pokémon that fights first (the first with HP left): a backup's PP
        would hide a leader with none, who then fights the next trainer with status moves only."""
        n = min(self.read(ADDR["party_count"])[0], 6)
        for i in range(n):
            base = ADDR["party_mons"] + PARTY_STRUCT * i
            hp = self.read(base + 1, 2)
            if hp[0] or hp[1]:
                return battle.damaging_pp_left(self.read, self.data, base)
        return 0

    def in_intro(self) -> bool:
        """Before the game starts (title screen, Oak's speech, naming): no Pokémon and the map position still
        Pallet Town (0, 0), a tree square no player stands on; a new game starts in the bedroom. The names
        are no signal: the title screen fills in defaults. Until the first map is loaded (Oak's last words),
        its header is still empty (width 0)."""
        if self.read(ADDR["party_count"])[0] or "starter" in self.memo.get("done", []):
            return False
        return self.read(ADDR["map"])[0] == 0 and self.pos() == (0, 0) or self.read(overworld.MAP_WIDTH)[0] == 0

    def money(self) -> int:
        b = self.read(MONEY, 3)
        return int("".join(f"{x:02x}" for x in b) or "0")

    def party(self) -> List[Dict]:
        out = []
        for i in range(min(self.read(ADDR["party_count"])[0], 6)):
            m = self.read(ADDR["party_mons"] + PARTY_STRUCT * i, PARTY_STRUCT)
            moves = []
            for mid in m[8:12]:
                if mid:
                    mv = self.data.move(mid)
                    en = names.move_en(mid)   # the strategist thinks in English: FOUET LIANES = Vine Whip
                    moves.append(f"{self.data.move_name(mid)}{' = ' + en if en else ''} "
                                 f"({battle.TYPE_NAMES.get(mv['type'], mv['type'])}, power {mv['power']})")
            out.append({"name": decode(self.read(PARTY_NICKS + 11 * i, 11)), "level": m[0x21],
                        "hp": m[1] * 256 + m[2], "max_hp": m[0x22] * 256 + m[0x23], "moves": moves})
        return out

    def leader_xp(self) -> int:
        """The leader's experience, 3 bytes big-endian at offset 0x0E of slot 0's party struct."""
        b = self.read(ADDR["party_mons"] + 0x0E, 3)
        return (b[0] << 16) | (b[1] << 8) | b[2]

    def rethink(self, trigger: str) -> None:
        ms = current(self.read, self.memo)
        snap = {"milestone": ms.id, "goal": ms.goal, "party": self.party(), "money": self.money(),
                "badges": badges(self.read), "done": list(self.memo.get("done", [])),
                "opponent_levels": list(self.memo.get("opponent_levels", []))}
        decision = strategy.update(self.memo, trigger, snap, self.complete)
        call = decision.get("call") or {}
        self.event("strategy", trigger=trigger, source=decision["source"], plan=decision.get("plan"),
                   train_to_level=strategy.memory(self.memo)["rules"].get("train_to_level"),
                   lessons=decision.get("lessons"), reason=decision.get("reason"),
                   prompt=call.get("prompt"), answer=call.get("content"), model=call.get("model"),
                   usage=call.get("usage"), cost=call.get("cost"), ms=call.get("ms"))

    def facts(self, milestone: str) -> Dict:
        """What the game's memory says at the moment a milestone is found done: map, badges, key items (ids)."""
        items = sorted(i for i in bag(self.read) if i >= 0x3F)   # the key items of this part of the story, not potions and balls
        return {"id": milestone, "map": self.read(ADDR["map"])[0], "badges": badges(self.read), "bag": items}

    def event(self, kind: str, **facts):
        self.log.append({"t": round(time.time(), 2), "kind": kind, **facts})

    def grid(self, sprites_block: bool = True) -> overworld.Grid:
        """The current map's grid, with `memo["walls"]` squares (beaten trainers that never move)
        marked unwalkable. Sprites block by default; pass `sprites_block=False` for the layout."""
        walk = overworld.full_grid(self.read, self.rom, sprites_block=sprites_block, cut=hm.cut_user(self.read) is not None)
        here = self.read(ADDR["map"])[0]
        for sq in self.memo.get("walls", {}).get(str(here), []):
            t = (sq[0], sq[1]) if isinstance(sq, (list, tuple)) else sq
            if t in walk:
                walk[t] = False
        return walk

    # --- one tick ----------------------------------------------------------------------------
    def tick(self) -> str:
        if hasattr(self.io, "refresh"):
            self.io.refresh()  # one fresh snapshot per tick, whatever the previous tick did
        now = time.time()
        if self.memo.get("grinding") and self._last_tick:
            self.memo["grind_s"] = self.memo.get("grind_s", 0.0) + min(5.0, now - self._last_tick)   # play time only
        self._last_tick = now
        if "starter" in self.memo.get("done", []) and not self.read(ADDR["party_count"])[0]:
            # a blank memory read (seen on a host: no Pokémon, money 0): it would look like a defeat
            self.io.wait(300)
            return "bad read"
        if self.battle_turns and self.read(ADDR["in_battle"])[0] and self.party_hp()[0] == 0:
            self.battle_wiped = True   # a blackout warps to a Pokémon Center and heals: remember the wipe now
        if self.battle_turns and not self.read(ADDR["in_battle"])[0]:
            # a battle just ended: in_battle was 1 last tick(s), now it is 0 — capture the outcome once
            cur = 0 if self.battle_wiped else self.party_hp()[0]
            outcome = battle.outcome(self.last_choice_kind == "run", cur)
            ids = [i for i in self.battle_ids if i]
            self.catch_result()
            self.event("battle_end", outcome=outcome, battle=self.battle_kind,
                       turns=self.battle_turns, decision_ids=list(self.battle_ids))
            if outcome == "won" and self.battle_kind == "trainer":
                self.memo["trainer_wins"] = self.memo.get("trainer_wins", 0) + 1   # scripted fights count them (Giovanni's guards)
            if self.on_battle_end and ids:
                self.on_battle_end(ids, {"result": outcome, "turns": self.battle_turns,
                                          "battle": self.battle_kind, "by": "game"})
            if outcome == "lost":
                self._attach_heal_outcomes({"result": "lost before healing", "by": "game"})
            self.memo["battle"] = no_battle()
            self.memo.pop("woken", None)
            self.learn_choice = None
        money = self.money()
        shopping = self.memo.get("shopping") and self.read(ADDR["map"])[0] in MARTS   # a purchase is no defeat
        if self.memo.get("money") and money < self.memo["money"] * 0.7 and not self.read(ADDR["in_battle"])[0] and not shopping:
            self.event("defeat", money_before=self.memo["money"], money_after=money)
            self.memo["money"] = money
            self.memo.pop("stalled_target", None)    # after a defeat, training is worth a new try
            self.rethink(f"defeat at {current(self.read, self.memo).id}")
        self.memo["money"] = money
        if self.in_intro():
            # a new game: title screen, NEW GAME, Oak's speech, then the player's and the rival's names
            # (A on the keyboard types letters up to the limit, then confirms). START gets past the title
            self.intro_presses = getattr(self, "intro_presses", 0) + 1
            self.io.press("START" if self.intro_presses % 6 == 0 else "A", 90)
            self.io.wait(300)
            return "intro"
        learning = self.learn_tick()   # before every generic A press: it would forget the first move
        if learning:
            return learning
        if self.read(ADDR["in_battle"])[0]:
            return self.battle_tick()
        self.disabled = None
        here = self.read(ADDR["map"])[0]
        if self.memo.get("shopping") and here in MARTS:
            shopped = self.shop(here)   # the clerk's boxes are answered on purpose, not with a blind A
            if shopped:
                return shopped
        if text_box_open(self.read):
            t = text_box(self.read)
            self.io.press("B" if "surnom" in t.lower() else "A", 90)
            self.io.wait(250)
            return "text"
        if busy(self.read):
            self.io.wait(250)
            return "cutscene"
        return self.overworld_tick()

    def learn_tick(self) -> Optional[str]:
        """Answer the learn-a-move questions (learn.py) by decision; None when none is on screen."""
        step = learn.stage(self.read) if text_box_open(self.read) else ""
        if not step:
            return None
        if step == "list":
            return self.learn_pick()
        if step == "wait":
            self.io.wait(150)
            return "learn wait"
        if not self.learn_decision():
            return None
        want_forget = self.learn_choice["forget"] is not None
        # "Ne pas apprendre X?": OUI drops the new move; if we want it, NON goes back to the first question
        self.answer_yes_no(want_forget if step == "ask" else not want_forget)
        return "learn answer"

    def answer_yes_no(self, yes: bool) -> None:
        """Put the OUI / NON cursor (menu_item 0 / 1, read back from memory) on the answer, A."""
        for _ in range(3):
            if hasattr(self.io, "refresh"):
                self.io.refresh()
            at = self.read(ADDR["menu_item"])[0]
            if at == (0 if yes else 1):
                break
            self.io.press("UP" if yes else "DOWN", 90)
            self.io.wait(250)
        self.io.press("A", 90)
        self.io.wait(500)

    def learn_pick(self) -> str:
        """The list "Oublier quelle attaque?": the cursor (menu_item = slot) onto the move to forget, A."""
        slot = (self.learn_choice or {}).get("forget")
        if slot is None:
            self.io.press("B", 90)   # we declined: back out of the list (the game asks again)
            self.io.wait(400)
            return "learn back"
        at = self.read(ADDR["menu_item"])[0]
        keys = battle.keys_to_menu_item(at, slot) or ["A"]
        self.io.press(keys[0], 90)
        self.io.wait(600 if keys[0] == "A" else 300)
        return "learn pick"

    def learn_decision(self) -> bool:
        """Decide once per question (a repeated question keeps its answer): True when a decision stands."""
        index, new_id = self.read(learn.LEARNER)[0], self.read(learn.NEW_MOVE)[0]
        mon = learn.learner(self.read, self.data, ADDR["party_mons"], index)
        if len(mon["moves"]) < 4 or not self.data.move(new_id) or new_id in [m["move_id"] for m in mon["moves"]]:
            return False   # not a full-moves question
        key = (index, new_id, tuple(m["move_id"] for m in mon["moves"]))
        if self.learn_choice and self.learn_choice["key"] == key:
            return True
        new = learn.move_facts(self.data, new_id)
        opts = learn.options(mon["moves"], new)
        name = decode(self.read(PARTY_NICKS + 11 * index, 11))
        state_text, instructions = learn.describe(name, mon, new), learn.INSTRUCTIONS
        texts = [{"id": o["id"], "facts": learn.option_text(o)} for o in opts]
        out = {"choice": learn.heuristic_choice(opts), "by": "heuristic"}
        if self.choose:
            got = self.choose(state_text, texts, instructions) or {}
            if got.get("choice") in {o["id"] for o in opts}:
                out = {**got, "by": got.get("model", "chooser")}
        picked = next(o for o in opts if o["id"] == out["choice"])
        slot = picked.get("slot")
        self.learn_choice = {"key": key, "forget": slot}
        if out.get("decision_id") and self.battle_turns:
            self.battle_ids.append(out["decision_id"])
        self.event("move_learn_choice", choice=out["choice"], by=out["by"], confidence=out.get("confidence"),
                   probabilities=out.get("probabilities"), state=state_text,
                   options=[{**t, "name": o["facts"]["name"] if o["kind"] == "forget" else "keep"}
                            for t, o in zip(texts, opts)],
                   instructions=instructions if self.choose else None, usage=out.get("usage"), cost=out.get("cost"),
                   ms=out.get("ms"), decision_id=out.get("decision_id"), new_move=new["name"],
                   forgotten=mon["moves"][slot]["name"] if slot is not None else None)
        return True

    def struggle(self) -> str:
        """No PP left on any move: the game picks Struggle by itself once FIGHT is chosen (nothing to decide)."""
        self.event("struggle")
        self.menu_cell(0, 7)
        self.io.press("A", 90)
        self.io.wait(600)
        return "battle struggle"

    def battle_tick(self) -> str:
        if battle.party_select(self.read):
            return self.send_out_next()
        if not (battle.main_menu_open(self.read) and self.read(ADDR["menu_cursor_x"])[0] in (7, 13)):
            refused = battle.move_list(self.read)
            if refused:
                # stuck in the move list: the move picked had no PP left, or is disabled. Back to the main
                # menu, where the options leave out the moves without PP and the disabled one
                if refused == "disabled":
                    self.disabled = self.memo.get("last_move")
                self.io.press("B", 90)
                self.io.wait(300)
                return "battle back"
            nick = "surnom" in text_box(self.read).lower()   # after a catch: never nickname
            self.io.press("B" if nick else "A", 90)
            self.io.wait(300)
            return "battle text"
        opts = [o for o in battle.options(self.read, self.data) if o["id"] != self.disabled] or \
            battle.options(self.read, self.data)
        if not opts:
            return self.struggle()
        st = battle.state(self.read)
        share = st["ours"]["hp"] / max(1, st["ours"]["max_hp"])
        state_text = battle.describe(self.read)
        option_texts = [{"id": o["id"], "facts": battle.option_text(o)} for o in opts]
        instructions = "Pick the option that wins this battle while keeping our Pokémon healthy."
        out = {"choice": battle.heuristic_choice(opts, share, self.memo.get("last_move"),
                                                 travelling=not self.memo.get("grinding") and not self.must_fight()), "by": "heuristic"}
        if self.choose:
            got = self.choose(state_text, option_texts, instructions) or {}
            if got.get("choice") in {o["id"] for o in opts}:
                out = {**got, "by": got.get("model", "chooser")}
        choice = next(o for o in opts if o["id"] == out["choice"])
        self.memo["last_move"] = choice["id"]
        names = {o["id"]: (self.data.move_name(o["facts"]["move_id"]) if o["kind"] == "move"
                           else o["facts"]["ball"] if o["kind"] == "catch" else "PKMN " + str(o["slot"] + 1) if o["kind"] == "switch" else "FUITE") for o in opts}
        self.memo["opponent_levels"] = (self.memo.get("opponent_levels", []) + [st["enemy"]["level"]])[-8:]
        self.battle_kind = st["kind"]
        self.last_choice_kind = choice["kind"]
        self.battle_turns += 1
        if out.get("decision_id"):
            self.battle_ids.append(out["decision_id"])
        self.event("battle_choice", kind_battle=st["kind"], our_hp=st["ours"]["hp"], enemy_hp=st["enemy"]["hp"],
                   enemy_level=st["enemy"]["level"],
                   choice=choice["id"], choice_name=names.get(choice["id"]), by=out["by"],
                   confidence=out.get("confidence"), probabilities=out.get("probabilities"),
                   state=state_text, options=[{**t, "name": names.get(t["id"])} for t in option_texts],
                   instructions=instructions if self.choose else None,
                   usage=out.get("usage"), cost=out.get("cost"), ms=out.get("ms"))
        if choice["kind"] == "catch":
            return self.throw_ball(choice["ball"], st)
        if choice["kind"] == "switch":
            return self.switch_to(choice["slot"])
        if choice["kind"] == "run":
            self.menu_cell(1, 13)              # FUITE: bottom right
            self.io.press("A", 90); self.io.wait(500)
            return "battle run"
        self.menu_cell(0, 7)                   # ATTAQUE: top left (the game remembers the last cell)
        self.io.press("A", 90); self.io.wait(450)
        for k in battle.keys_to_menu_item(self.read(ADDR["menu_item"])[0], choice["slot"]):
            self.io.press(k, 90); self.io.wait(200)
        self.io.press("A", 90); self.io.wait(500)
        return "battle move"

    def must_fight(self) -> bool:
        """Pokémon Tower's 6F: the Marowak ghost stands on the way to the stairs and comes back each time the
        player flees, so a wild battle there is fought; so is the Snorlax just woken with the flute (it
        stays in the road when it is fled from)."""
        return self.read(ADDR["map"])[0] == TOWER_6F or bool(self.memo.get("woken"))

    def switch_to(self, slot: int) -> str:
        """PKMN (top right), the member's row in the party list, A, then A on the first entry of its menu."""
        self.menu_cell(0, 13)
        self.io.press("A", 90); self.io.wait(600)
        for _ in range(8):
            if hasattr(self.io, "refresh"):
                self.io.refresh()
            at = self.read(ADDR["menu_item"])[0]
            if at == slot:
                break
            self.io.press("DOWN" if at < slot else "UP", 90); self.io.wait(250)
        self.io.press("A", 90); self.io.wait(500)
        self.io.press("A", 90); self.io.wait(800)
        return "battle switch"

    def catch_result(self) -> None:
        """After a battle with balls thrown: the party grew (caught) or not (it broke free, ran or fainted)."""
        if not self.thrown:
            return
        t, now = self.catch_target, self.read(ADDR["party_count"])[0]
        kind = "caught" if now > t["party"] else "catch_failed"
        self.event(kind, species=t["species"], name=t["name"], balls_thrown=self.thrown, party=now, balls_left=self.balls())
        self.thrown, self.catch_target = 0, None

    def send_out_next(self) -> str:
        """The party list after a faint: put the cursor on the first Pokémon with HP left, A."""
        target = battle.first_alive(self.read, self.data)
        at = self.read(ADDR["menu_item"])[0]
        if target is None or at == target:
            self.io.press("A", 90)
            self.io.wait(500)
            return "battle send out"
        self.io.press("DOWN" if at < target else "UP", 90)
        self.io.wait(250)
        return "battle party"

    def throw_ball(self, ball: int, st: Dict) -> str:
        """OBJET (bottom left), the ball's row in the bag list, A: the game plays the throw."""
        if not self.thrown:
            self.catch_target = {"species": st["enemy"]["species"], "name": battle.names(self.read)["enemy"],
                                 "party": self.read(ADDR["party_count"])[0]}
        self.thrown += 1
        self.menu_cell(1, 7)
        self.io.press("A", 90); self.io.wait(500)
        target = battle.ball_row(bag(self.read), ball)
        for _ in range(25):
            at = battle.list_cursor(self.read)
            if at == target:
                break
            self.io.press("DOWN" if at < target else "UP", 90); self.io.wait(200)
        self.io.press("A", 90); self.io.wait(600)
        return "battle ball"

    def menu_cell(self, row: int, col: int):
        """Put the battle menu cursor on (row 0/1, column 7/13), reading it back from memory."""
        for _ in range(4):
            r, c = self.read(ADDR["menu_item"])[0], self.read(ADDR["menu_cursor_x"])[0]
            if (r, c) == (row, col):
                return
            key = "UP" if r > row else "DOWN" if r < row else "LEFT" if c > col else "RIGHT"
            self.io.press(key, 90)
            self.io.wait(200)

    def overworld_tick(self) -> str:
        ms = current(self.read, self.memo)
        if ms.id in self.memo.get("done", []):
            # every milestone is done: the story as written ends here (no endless talk to the last gym leader)
            if not self.memo.get("story_done"):
                self.memo["story_done"] = True
                self.event("milestone_done", **self.facts(ms.id))
                self.event("story_done", milestone=ms.id)
            return "story done"
        if self.memo.get("milestone") != ms.id:
            if self.memo.get("milestone"):
                self.event("milestone_done", **self.facts(self.memo["milestone"]))
            self.memo["milestone"], self.memo[GUIDE] = ms.id, 0
            self.memo.pop("story_done", None)   # a milestone was added since the story ended
            self.event("milestone", id=ms.id, goal=ms.goal)
            self._attach_heal_outcomes({"result": "milestone reached"})
            self.rethink(f"new milestone {ms.id}")
        here = self.read(ADDR["map"])[0]
        info = self.world.learn(self.read, self.grid(sprites_block=False))
        self.note_entry(here)
        # advance the guide pointer to the furthest guide map we are on
        maps, i = ms.maps, self.memo.get(GUIDE, 0)
        if maps[i] != here and here in maps:
            # moving on along the route, or back on an earlier map (backtracking, a blackout)
            ahead = [j for j in range(i, len(maps)) if maps[j] == here]
            i = ahead[0] if ahead else max(j for j in range(len(maps)) if maps[j] == here)
        self.memo[GUIDE] = i
        cur, tot = self.party_hp()
        n = self.read(ADDR["party_count"])[0]
        attack_pp = self.attack_pp() if n else 0
        no_attack = n and attack_pp < HEAL_PP_BELOW   # heal before a trainer fight leaves us with only Growl
        if tot and (self.memo.get("healing") or cur / tot < HEAL_BELOW or no_attack):
            # low but not in danger: ask Jev once per situation whether to heal now or push on
            asked = (self.choose and not self.memo.get("healing") and cur / tot >= HEAL_FORCED_BELOW
                     and attack_pp > 0)
            if not asked or self._decide_heal(cur, tot, attack_pp, here) != "push":
                return self.heal(here, cur, tot)
        if ms.prepare and ms.id not in self.memo.setdefault("prepared", []):
            visited = self.prepare(ms, here)
            if visited:
                return visited
        if ms.prepare:
            recruiting = self.recruit(ms, here, info)
            if recruiting:
                return recruiting
        if self.wants_balls() or self.memo.get("shopping"):
            shopped = self.shop(here)
            if shopped:
                return shopped
        if hm.has_hm01(self.read) and hm.cut_user(self.read) is None and self.memo.get("cut_tries", 0) < CUT_TRIES:
            return self.teach_cut()
        want = strategy.memory(self.memo)["rules"].get("train_to_level")
        top = max((p["level"] for p in self.party()), default=0)
        if want and top < want and self.memo.get("stalled_target") != want:
            return self.grind(here, info, top, want)
        if want and top >= want and self.memo.get("grinding"):
            self.memo["grinding"] = False
            self.event("trained", level=top)
        story = self.story_step(ms, here, info)
        if story:
            return story
        if ms.goal_via is not None:
            # a part of the last map (Route 4's far side), through maps not all visited yet (Mt. Moon)
            goal_part = self.world.part_with_warp_to(maps[-1], ms.goal_via)
            return self.go_to_map(here, maps[-1], info, goal_part=goal_part, explore=ms.area, anywhere=True)
        if here == maps[-1]:
            return self.goal_action(ms)
        if maps[i] == here:
            nxt = maps[i + 1] if i + 1 < len(maps) else maps[-1]
        elif here in ms.area:
            nxt = maps[min(i + 1, len(maps) - 1)]   # inside a detour the route leads through (Cerulean's house): on, not back
        else:
            # off the route (a detour to heal, a building): back to the route map last reached,
            # or the closest route map we know a way to
            reachable = [m for m in [maps[i]] + maps if self.world.route(here, m)]
            nxt = reachable[0] if reachable else maps[-1]
        return self.go_to_map(here, nxt, info, explore=ms.area, anywhere=True)   # `area`: maps to visit when no route is known yet

    def story_step(self, ms, here: int, info: Dict) -> Optional[str]:
        """The places where the story is more than "walk to the next map": None when the guide is enough."""
        if ms.id == "lift_key" and here == GAME_CORNER:
            return self.game_corner_poster()
        if here != ROCKET_LIFT:
            self.lift_floor_set = False
        if here in ROCKET_HIDEOUT:
            return self.hideout_step(ms, here, info)
        if ms.id == "poke_flute" and here == TOWER_7F:
            return self.talk_to_topmost()
        return None

    def fetch_lift_key(self) -> str:
        """B4F's north-west room: the Rocket who had the Lift Key is fought first (he drops it); only then is
        the ball next to him there to be picked up (before, the square looks free and walking onto it does
        nothing). A beaten Rocket only talks, so after a few talks the ball is tried."""
        px, py = self.pos()
        talks = self.memo.setdefault("key_guard_talks", 0)
        if talks < BLOCKER_TALKS_MAX and LIFT_KEY_GUARD in overworld.sprites(self.read):
            if abs(LIFT_KEY_GUARD[0] - px) + abs(LIFT_KEY_GUARD[1] - py) == 1:
                self.memo["key_guard_talks"] = talks + 1
            return self.talk_at(LIFT_KEY_GUARD)
        return self.talk_at(LIFT_KEY_BALL)

    def game_corner_poster(self) -> Optional[str]:
        """The Game Corner's guard stands in front of a poster hiding a switch; once he is beaten, A on the
        poster opens the stairs to the Rocket Hideout. None when the stairs are open already."""
        if overworld.block_at(self.read, *POSTER_STAIRS) == STAIRS_OPEN_BLOCK:
            return None
        if POSTER_GUARD in overworld.sprites(self.read):
            return self.talk_at(POSTER_GUARD)
        if self.pos() != POSTER_SPOT:
            return self.walk(POSTER_SPOT)
        self.step("UP")   # the poster blocks: the press only turns the player toward it
        texts = self.read_texts("A")
        self.event("poster_switch", text=" | ".join(texts))
        return "poster"

    def hideout_step(self, ms, here: int, info: Dict) -> Optional[str]:
        """B4F's two halves meet only through the elevator on B1F (the Lift Key starts it): the half where
        the stairs lead has no way to Giovanni's, and from his half the elevator is the only way out (the
        world graph cannot know where its door leads: to the floor last chosen)."""
        wing = here == ROCKET_B4F and self.in_giovanni_wing(info)
        if here == ROCKET_LIFT:
            return self.ride_lift("4EME" if ms.id == "silph_scope" and not self.memo.get("healing") else "1ER")
        if ms.id == "silph_scope":
            return self.giovanni() if wing else self.go_to_map(here, ROCKET_LIFT, info, explore=ROCKET_HIDEOUT)
        return self.go_to_map(here, ROCKET_LIFT, info) if wing else None

    def talk_to_topmost(self) -> str:
        """Mr. Fuji is the person farthest up: behind three Rockets on Pokémon Tower's top floor (walking up to
        him fights whoever stands in the way: the blocker logic of walk; his thanks warp the player to his
        house), at the back of his house (he hands over the flute)."""
        people = overworld.sprite_list(self.read)
        if not people:
            self.io.wait(300)
            return "nobody"
        return self.talk_at(min(people, key=lambda p: p[1][1])[1])

    def in_giovanni_wing(self, info: Dict) -> bool:
        """The player's part of the map holds a warp to the elevator."""
        part = overworld.reachable(self.grid(sprites_block=False), self.pos())
        return any((w[0], w[1]) in part for w in info["warps"] if w[2] == ROCKET_LIFT)

    def ride_lift(self, floor: str) -> str:
        """In the Rocket elevator: the panel (on the wall above its left square) asks for a floor; pick the
        wanted floor, then leave through the door. The door leads to the floor last chosen, so a way out of
        B4F's far half asks for the first basement."""
        if not self.lift_floor_set:
            if self.pos() != LIFT_PANEL_SPOT:
                return self.walk(LIFT_PANEL_SPOT)
            self.step("UP")   # the panel is a wall: the press only turns the player toward it
            self.io.press("A", 90)
            self.io.wait(700)
            return self.pick_lift_floor(floor)
        if self.pos() != LIFT_DOOR_SPOT:
            return self.walk(LIFT_DOOR_SPOT)
        self.step("UP")
        return "lift out"

    def pick_lift_floor(self, floor: str) -> str:
        """The floor menu ("Quel étage?"): the cursor onto the floor labelled `floor`, A."""
        hm.look(self)
        rows = screen_rows(self.read)
        labels = [r for r in rows if "SS" in r]
        index = next((i for i, r in enumerate(labels) if floor in r), None)
        if index is None:
            return "lift menu"
        hm.goto(self, index)
        hm.press(self, "A", 800)
        self.lift_floor_set = True
        self.memo["wing_base"] = self.memo.get("trainer_wins", 0)
        self.event("lift_floor", floor=floor)
        return "lift floor"

    def giovanni(self) -> str:
        """Giovanni's half of B4F: two Rockets guard the door (it opens once they are beaten; the fights won
        since the elevator ride say which is next), then Giovanni; what he leaves lies next to him as a ball."""
        beyond = overworld.astar(self.grid(sprites_block=False), self.pos(), GIOVANNI_SIDE)
        if beyond is None:
            fought = self.memo.get("trainer_wins", 0) - self.memo.get("wing_base", 0)
            return self.talk_at(WING_GUARDS[min(fought, len(WING_GUARDS) - 1)])
        if GIOVANNI_AT in overworld.sprites(self.read):
            return self.talk_at(GIOVANNI_AT)
        return self.talk_at(GIOVANNI_BALL)

    def go_to_map(self, here: int, dest: int, info: Dict, goal_part: Optional[int] = None, explore=(), anywhere: bool = False) -> str:
        """One step of the trip to `dest` (its part `goal_part`, if given): toward the next hop (edge or
        warp) of the route. With `explore` (maps), when no route is known yet, toward the nearest of
        those maps not visited yet; with `anywhere`, failing that, toward any map not visited yet (the way on may
        be through a gate house the milestone does not list)."""
        if here == ROCKET_B4F and dest != ROCKET_LIFT and self.in_giovanni_wing(info):
            dest = ROCKET_LIFT   # whatever the errand (a heal, the next milestone), the elevator is the only way out of that half
        walk = self.grid(sprites_block=False)   # the layout: people move or fight
        part = overworld.reachable(walk, self.pos())
        edges = {side: set(overworld.edge_squares(walk, side, info.get("spans", {}).get(side)))
                 for side in ("north", "south", "west", "east")}

        def first_hop_ok(how):
            return (how[1] in part) if how[0] == "warp" else bool(edges[how[1]] & part)
        start_part = (info.get("parts") or {}).get("player")
        route = self.find_route(here, dest, first_hop_ok, start_part, goal_part, explore, anywhere)
        if not route:
            back = self.retreat(here, info, part) if self.no_route_ticks >= NO_ROUTE_TICKS else None
            if back:
                return back
            guard = self.guard_in_reach(here, part)
            if guard:
                return self.talk_at(guard)   # a locked room opens when its guard is beaten (the Rocket elevator's)
            if self.memo.get("lost") != [here, dest]:
                self.memo["lost"] = [here, dest]
                self.event("lost", map=here, next=dest, known=sorted(self.world.maps))
            return "no route"
        how = route[0][1]
        if how[0] == "warp":
            # several warps can lead to the same map (a 2-square door); some are drawn as wall and
            # never trigger: use the nearest one not marked unusable
            bad = {tuple(b) for b in self.memo.get("bad_warps", []) if b[0] == here}
            px, py = self.pos()
            # the twins of the chosen warp: same destination warp, reachable from where the player stands
            # (a cave floor has several ladders to the next floor, in different parts)
            chosen = next((w for w in info["warps"] if (w[0], w[1]) == how[1]), None)
            cands = sorted(((w[0], w[1]) for w in info["warps"] if w[2] == route[0][0] and (here, w[0], w[1]) not in bad
                            and (w[0], w[1]) in part and (chosen is None or w[3] == chosen[3])),
                           key=lambda w: abs(w[0] - px) + abs(w[1] - py))
            if cands:
                how = ("warp", cands[0])
                if self.stuck >= 6:
                    self.memo.setdefault("bad_warps", []).append([here, *cands[0]])
                    self.event("warp_unusable", map=here, warp=list(cands[0]))
                    self.stuck = 0
        target = hop_target(info, how, self.pos())
        if how[0] == "warp" and self.pos() == target:
            return self.step_off_warp(here, info, target)
        return self.walk(target, edge=how[0] == "edge" and how[1])

    def find_route(self, here: int, dest: int, first_hop_ok, start_part, goal_part, explore, anywhere: bool):
        """The route to `dest`; failing that toward the nearest unvisited map of `explore` (the cave's floors), and
        once that has failed for NO_ROUTE_TICKS ticks (the first ticks after a crossing can read a stale map
        header) toward any unvisited map next to this one when `anywhere`. Counts the ticks without a route."""
        route, exploring = self.world.route(here, dest, first_hop_ok, start_part=start_part, goal_part=goal_part), False
        if not route and explore:
            route, exploring = self.world.explore(here, explore, first_hop_ok, start_part=start_part), True
        self.no_route_ticks = 0 if route else self.no_route_ticks + 1
        if not route and anywhere and self.no_route_ticks >= NO_ROUTE_TICKS:
            near = self.world.explore(here, ANY_MAP, first_hop_ok, start_part=start_part)
            route, exploring = (near if near and len(near) == 1 else None), True   # a door or edge of this map: not a trek elsewhere
        if route and exploring and self.memo.get("exploring") != route[-1][0]:
            self.memo["exploring"] = route[-1][0]
            self.event("explore", map=here, toward=route[-1][0])
        return route

    def note_entry(self, here: int) -> None:
        """A map was just entered over an edge: remember from where and at which square."""
        c = self.memo.get("crossing")
        if c and c[0] != here:
            x, y = self.pos()
            self.memo["entry"] = {"from": c[0], "side": c[1], "exit": c[2:4], "map": here, "landing": [x, y]}
            self.memo.pop("crossing")

    def retreat(self, here: int, info: Dict, part) -> Optional[str]:
        """No way on from the part of the map entered by an edge (Route 14: the lane entered from Route 13
        ends at a beaten trainer in a one-square lane): mark every edge square of that part, and the exits of
        the map before them that lead there, as bad, and go back to cross somewhere else."""
        e = self.memo.get("entry")
        if not e or e["map"] != here or e["from"] not in self.world.maps:
            return None
        walk = self.grid(sprites_block=False)
        dead = [q for q in overworld.edge_squares(walk, OPPOSITE[e["side"]], info.get("spans", {}).get(OPPOSITE[e["side"]])) if q in part]
        bad = self.memo.setdefault("bad_exits", [])
        fresh = [b for b in prev_exits(e, self.world.maps[e["from"]], dead) if b not in bad]
        if not fresh and not self.world.route(here, e["from"]):
            return None
        if fresh:
            bad.extend(fresh)
            self.event("dead_end", map=here, came_from=e["from"], exits_dropped=len(fresh))
        return self.go_to_map(here, e["from"], info)

    def guard_in_reach(self, here: int, part) -> Optional[tuple]:
        """The nearest person standing in the player's part of the map who was not talked to BLOCKER_TALKS_MAX
        times yet: with no way out, talking to him is the one thing left to try."""
        px, py = self.pos()
        talks = self.memo.setdefault("guard_talks", {})
        near = sorted((abs(q[0] - px) + abs(q[1] - py), q) for q in overworld.sprites(self.read) if q in part)
        for dist, q in near:
            key = f"{here}:{q[0]},{q[1]}"
            if talks.get(key, 0) <= BLOCKER_TALKS_MAX:
                if dist == 1:
                    talks[key] = talks.get(key, 0) + 1   # only a real talk counts, not the steps walking up to him
                return q
        return None

    def step_off_warp(self, here: int, info: Dict, target) -> str:
        """On the warp itself: an indoor exit mat fires when stepping off it towards the outside (off the map);
        a ladder, by stepping off it and back on (next tick). Nearest edge first, but only off the map or onto a
        walkable square. A door drawn in a wall (the Rocket elevator's) only fires on a press into the wall:
        those sides come last, after a step off and back on did nothing."""
        x, y = target
        if self.mat_map != here:
            self.mat_map, self.mat = here, {}
        grid = self.grid()
        sides = [d for _, d in sorted([(y, "UP"), (info["height"] - 1 - y, "DOWN"), (x, "LEFT"), (info["width"] - 1 - x, "RIGHT")])]
        # not onto a twin warp square (a 2-wide gangway): moving between the two never triggers either
        twins = {(w[0], w[1]) for w in info["warps"]}
        nxt = {d: (x + overworld.STEP[d][0], y + overworld.STEP[d][1]) for d in sides}
        ok = [d for d in sides if grid.get(nxt[d], True) and nxt[d] not in twins]
        walls = [d for d in sides if d not in ok and nxt[d] not in twins]
        order = ok + walls or [sides[0]]
        tries = self.mat.get(target, 0)
        self.mat[target] = tries + 1
        self.stuck = 0 if self.step(order[tries % len(order)]) else self.stuck + 1
        return "exit mat"

    def open_exits(self, here: int, edge: str, pos, exits: List) -> List:
        """The edge squares not known to be blocked beyond: the connection's strip can meet a tree line on the
        other side (Lavender's west edge meets Route 8's trees except on its road), which only a failed
        crossing shows. Three failed steps on an exit square mark it; the rest are tried instead."""
        bad = self.memo.setdefault("bad_exits", [])
        if pos in exits and self.stuck >= 3 and [here, *pos] not in bad:
            bad.append([here, *pos])
            self.event("exit_blocked", map=here, at=list(pos))
            self.stuck = 0
        left = [e for e in exits if [here, *e] not in bad]
        return left or exits

    def walk(self, target, edge=None) -> str:
        """One step toward `target` (or, for an edge hop, toward the nearest walkable square on that
        edge, then across it), planned with A* on the whole map."""
        px, py = self.pos()
        walk = self.grid()
        self.avoid_warps(walk, target)
        across = {"north": "UP", "south": "DOWN", "west": "LEFT", "east": "RIGHT"}
        path = None
        if edge:
            info = self.world.maps.get(self.read(ADDR["map"])[0], {})
            here = self.read(ADDR["map"])[0]
            exits = self.open_exits(here, edge, (px, py), overworld.edge_squares(walk, edge, info.get("spans", {}).get(edge)))
            if (px, py) in exits:
                path = [across[edge]]
                self.memo["crossing"] = [here, edge, px, py]   # where the next map is entered, to take another way if it is a dead end
            else:
                paths = [p for p in (overworld.astar(walk, (px, py), e) for e in exits) if p]
                path = min(paths, key=len) if paths else None
                if path is None:
                    goal = self.nearest_open(exits)   # only people stand between the player and the edge (Snorlax)
                    action, path = self.unblock((px, py), goal) if goal else (None, None)
                    if action:
                        return action
        else:
            path = overworld.astar(walk, (px, py), target)
            if path is None:
                action, path = self.unblock((px, py), target)
                if action:
                    return action
                if path is None:
                    path = overworld.toward(walk, (px, py), target)
        if not path:
            self.stuck += 1
            return "no path"
        ahead = (px + overworld.STEP[path[0]][0], py + overworld.STEP[path[0]][1])
        if ahead in getattr(walk, "cuts", ()) and walk.get(ahead):
            return self.cut_tree(path[0], ahead)   # a tree is in the way and Cut is known: cut it
        moved = self.step(path[0]) or self.step(path[0])  # the first press may only turn the player
        self.stuck = 0 if moved else self.stuck + 1
        return "walk"

    def nearest_open(self, squares) -> Optional[tuple]:
        """The square of `squares` with the shortest path on the layout (people ignored), None without one."""
        open_map, start = self.grid(sprites_block=False), self.pos()
        paths = [(len(p), sq) for sq in squares if (p := overworld.astar(open_map, start, sq)) is not None]
        return min(paths)[1] if paths else None

    def unblock(self, start, target) -> tuple:
        """The path to `target` is blocked by people or items only (Mt. Moon B2F: the Super Nerd and the fossils):
        talk to the first one (a trainer fights, an item is picked up, the sleeping Snorlax is woken with the
        flute) and the way opens. Returns (action, path): an action when this tick was spent, else the re-planned
        path (None when nothing blocks)."""
        px, py = start
        blocker = self.blocker_on_the_way(start, target)
        if not blocker:
            return None, None
        here = self.read(ADDR["map"])[0]
        if self.wakes(blocker):
            return self.wake(blocker), None
        key = f"{here}:{blocker[0]},{blocker[1]}"
        count = self.memo.setdefault("blocker_talks", {}).get(key, 0)
        if abs(blocker[0] - px) + abs(blocker[1] - py) == 1:
            count += 1   # only a real talk counts, not the steps walking up to it
        self.memo["blocker_talks"][key] = count
        if count > BLOCKER_TALKS_MAX:
            # a beaten trainer never moves: keep talking and we loop forever on the same line
            # re-plan now that this square is unwalkable
            walk = self.grid()
            return None, overworld.astar(walk, start, target) or overworld.toward(walk, start, target)
        if self.memo.get("blocker") != list(blocker):
            self.memo["blocker"] = list(blocker)
            self.event("blocked_by", at=list(blocker), target=list(target))
        if count == BLOCKER_TALKS_MAX:
            # the 3rd talk is the last: wall the square so A* routes around it from now on
            mwalls = self.memo.setdefault("walls", {}).setdefault(str(here), [])
            if [blocker[0], blocker[1]] not in mwalls:
                mwalls.append([blocker[0], blocker[1]])
                self.event("blocker_wall", map=here, at=list(blocker))
        return self.talk_at(blocker), None

    def wakes(self, blocker) -> bool:
        """The blocker is a sleeping Snorlax and the Poké Flute is in the bag."""
        pics = {pos: pic for pic, pos in overworld.sprite_list(self.read)}
        return pics.get(tuple(blocker)) == SNORLAX_PICTURE and POKE_FLUTE in bag(self.read)

    def wake(self, blocker) -> str:
        """Walk up to the Snorlax, face it and play the flute: it wakes up and fights (the battle ticks go on)."""
        px, py = self.pos()
        d = (blocker[0] - px, blocker[1] - py)
        if abs(d[0]) + abs(d[1]) != 1:
            return self.walk(blocker)
        self.step({(0, -1): "UP", (0, 1): "DOWN", (-1, 0): "LEFT", (1, 0): "RIGHT"}[d])   # a blocked press only turns
        used = hm.use_flute(self)
        self.io.refresh() if hasattr(self.io, "refresh") else None
        self.memo["woken"] = bool(self.read(ADDR["in_battle"])[0])   # it fights: no fleeing from it
        self.event("flute_used", at=list(blocker), used=used, battle=self.memo["woken"])
        return "flute"

    def avoid_warps(self, walk, target) -> None:
        """Warp squares are walls for the path unless they are the target: stairs in a narrow corridor
        (the Rocket Hideout) would otherwise be walked over, undoing the trip."""
        for w in links(self.read)["warps"]:
            if (w[0], w[1]) != tuple(target) and (w[0], w[1]) != self.pos() and (w[0], w[1]) in walk:
                walk[(w[0], w[1])] = False

    def teach_cut(self) -> str:
        """HM01 is in the bag and nobody knows Cut: teach it to the Pokémon losing least by it (hm.py)."""
        self.memo["cut_tries"] = self.memo.get("cut_tries", 0) + 1
        index = hm.teach_cut(self)
        if index is None:
            self.event("hm_failed", move="Cut", tries=self.memo["cut_tries"])
        else:
            mon = self.party()[index]
            self.event("hm_taught", move="Cut", pokemon=mon["name"], level=mon["level"], moves=mon["moves"])
        return "teach cut"

    def cut_tree(self, direction: str, tree) -> str:
        """Face the tree square and use Cut on it (hm.py); a tree that stays after two tries becomes a wall."""
        self.step(direction)   # a blocked press only turns the player toward the tree
        used = hm.use_cut(self)
        here = self.read(ADDR["map"])[0]
        if used and tree not in self.grid().cuts:
            self.event("cut_tree", map=here, at=list(tree), pokemon=self.party()[hm.cut_user(self.read)]["name"])
            return "cut tree"
        key = f"{here}:{tree[0]},{tree[1]}"
        fails = self.memo.setdefault("cut_fails", {})
        fails[key] = fails.get(key, 0) + 1
        if fails[key] >= 2:
            self.memo.setdefault("walls", {}).setdefault(str(here), []).append([tree[0], tree[1]])
            self.event("cut_failed", map=here, at=list(tree))
        return "cut failed"

    def trash_cans(self) -> str:
        """One step of the barrier puzzle (gym.py): go next to the next can, look under it, learn from the text."""
        state = self.memo.setdefault("trash", gym.new_state())
        px, py = self.pos()
        can = gym.next_can(state, (px, py))
        if can is None:
            self.memo["trash"] = gym.new_state()   # nothing left to try: what was learned is wrong, start over
            return "trash wait"
        walk = self.grid()
        spots = [(len(p), s, key) for s, key in gym.stands(can) if walk.get(s) and (p := overworld.astar(walk, (px, py), s)) is not None]
        if not spots:
            self.io.wait(300)
            return "trash blocked"
        _, spot, key = min(spots)
        if (px, py) != spot:
            return self.walk(spot)
        self.step(key)   # the can blocks: the press only turns the player toward it
        facing = self.read(overworld.FACING_ADDR)[0]
        near = [list(q) for q in overworld.sprites(self.read) if abs(q[0] - px) + abs(q[1] - py) <= 2]
        texts = self.read_texts("A") if facing == overworld.FACING_KEY[key] else []   # a text not from the can must not count
        what = gym.after(state, can, texts)
        self.event("trash_can", at=list(can), result=what, text=" | ".join(texts), facing=facing, near=near)
        return "trash can"

    def read_texts(self, key: str) -> List[str]:
        """Press `key`, then A through the text boxes that follow; every box's finished text, in order. A box
        that is still being typed is read again; the first box may take a moment to come."""
        self.io.press(key, 90)
        texts, misses = [], 0
        while misses < (8 if not texts else 3) and len(texts) < 8:
            self.io.wait(300)
            if hasattr(self.io, "refresh"):
                self.io.refresh()
            if not text_box_open(self.read) or self.read(ADDR["in_battle"])[0]:
                misses += 1
                continue
            misses, last = 0, None
            for _ in range(8):   # typing done: two reads agree
                last, now = text_box(self.read), None
                self.io.wait(150)
                self.io.refresh() if hasattr(self.io, "refresh") else None
                now = text_box(self.read)
                if now == last:
                    break
            texts.append(now)
            self.io.press("A", 90)
        self.io.wait(900)   # a trainer who spotted us talks first and the battle starts a moment after its text
        if hasattr(self.io, "refresh"):
            self.io.refresh()
        return [] if self.read(ADDR["in_battle"])[0] else texts

    def goal_action(self, ms) -> str:
        if ms.id == "starter" and self.read(ADDR["map"])[0] == OAKS_LAB:
            # the three Poké Balls lie on the table at (6, 3), (7, 3), (8, 3) (the map's fixed layout; their
            # sprites read as hidden from some squares); the right-hand one is Bulbasaur in Blue
            return self.talk_at(STARTER_BALL)
        if ms.id == "pokedex" and self.read(ADDR["map"])[0] == OAKS_LAB:
            return self.talk_to(OAK_PICTURE)
        if ms.id == "bill":
            # Bill is the only person in the house (a Pokémon first, then himself). After he has asked for help
            # nobody is in sight: he is in the machine and the PC starts it; then he is back, talk until the ticket
            px, py = self.pos()
            if overworld.sprite_list(self.read):
                return self.talk_to_nearest()
            if (px, py) != BILLS_PC_SPOT:
                return self.walk(BILLS_PC_SPOT)
            self.io.press("UP", 60); self.io.wait(200)
            self.io.press("A", 90); self.io.wait(400)
            return "use pc"
        if ms.id == "lift_key":
            return self.fetch_lift_key()
        if ms.id == "poke_flute":
            return self.talk_to_topmost()
        if ms.id == "ss_anne_cut":
            return self.talk_to_nearest()   # the seasick captain: his back is rubbed by talking, then he gives HM01
        if ms.id.endswith("_badge"):
            # the gym leader stands at the back of the gym: the topmost sprite (of those with a picture of their own:
            # Koga's jugglers share one and some stand higher up)
            people = overworld.sprite_list(self.read)
            if people:
                alone = [p for p in people if [q[0] for q in people].count(p[0]) == 1] or people
                leader = min(alone, key=lambda p: p[1][1])
                if self.read(ADDR["map"])[0] == VERMILION_GYM and \
                        overworld.astar(self.grid(sprites_block=False), self.pos(), leader[1]) is None:
                    return self.trash_cans()   # Lt. Surge is behind the electric barrier
                seen = self.memo.setdefault("leaders_seen", [])
                if ms.id not in seen:
                    seen.append(ms.id)
                    self.event("gym_leader", milestone=ms.id, picture=leader[0], at=list(leader[1]))
                return self.talk_at(leader[1])   # by position: the picture alone finds the nearest juggler
        self.io.wait(300)
        return "at goal"

    def _grind_progress(self, top: int, xp: int) -> None:
        """Track training progress: a level-up or any XP gain resets the stall timer (memo['grind_s'])."""
        if top > self.memo.get("grind_level", 0):
            self.memo["grind_level"], self.memo["grind_xp"], self.memo["grind_s"] = top, xp, 0.0
        elif xp > self.memo.get("grind_xp", 0):
            self.memo["grind_xp"], self.memo["grind_s"] = xp, 0.0

    def grind(self, here: int, info: Dict, top: int, want: int) -> str:
        """Train: wander a grass area (wild battles come by themselves) until the level is reached."""
        if not self.memo.get("grinding"):
            self.memo["grinding"] = True
            self.memo["grind_level"], self.memo["grind_xp"], self.memo["grind_s"] = top, self.leader_xp(), 0.0
            self.event("train_start", level=top, target=want)
        self._grind_progress(top, self.leader_xp())
        if self.memo.get("grind_s", 0) >= GRIND_STALL_S:
            # the opponents here are too weak to level up the party: drop the target, tell the strategist
            secs = round(self.memo["grind_s"])
            self.memo.update(grinding=False, stalled_target=want, grind_s=0.0)   # levels now come from the route
            self.event("train_stalled", level=top, target=want, seconds=secs)
            self.rethink(f"training stalled: {secs} s of training without experience gained at level {top} (target {want}), "
                         f"opponents' levels {self.memo.get('opponent_levels')}")
            return "training stalled"
        return self.wander(here, info)

    def wander(self, here: int, info: Dict) -> str:
        """Walk around the grass of the nearest grind map: wild battles come by themselves."""
        if here not in GRIND_MAPS:
            places = [m for m in GRIND_MAPS if self.world.route(here, m)]
            if not places:
                return "no grind area"
            return self.go_to_map(here, min(places, key=lambda m: len(self.world.route(here, m))), info)
        walk = self.grid()
        part = [p for p in overworld.reachable(walk, self.pos()) if walk.get(p)]
        spot = tuple(self.memo.get("grind_spot") or ())
        if not spot or spot == self.pos() or spot not in part or self.stuck >= 4:
            px, py = self.pos()
            near = [p for p in part if 3 <= abs(p[0] - px) + abs(p[1] - py) <= 8] or part
            spot = random.choice(near)
            self.memo["grind_spot"] = list(spot)
            self.stuck = 0
        return self.walk(spot)

    def recruit(self, ms, here: int, info: Dict) -> Optional[str]:
        """Before a `prepare` gauntlet: catch a second Pokémon (a backup finishes what the leader's few
        attacking PP cannot). None when the party has two, or when the errand was given up."""
        if self.read(ADDR["party_count"])[0] >= RECRUIT_PARTY or not self.balls() or self.memo.get("recruit_gave_up"):
            return None
        self.memo["recruit_ticks"] = self.memo.get("recruit_ticks", 0) + 1
        if self.memo["recruit_ticks"] > RECRUIT_GIVE_UP_TICKS:
            self.memo["recruit_gave_up"] = True
            self.event("recruit_failed", milestone=ms.id)
            return None
        return self.wander(here, info)

    def heal(self, here: int, cur: int, tot: int) -> str:
        """Heal at the nearest known place: a Pokémon Center (the nurse behind the counter) or home
        (mom)."""
        if not self.memo.get("healing"):
            self.memo["healing"] = True
            self.event("heal_start", hp=cur, max_hp=tot)
        if cur == tot and self.attack_pp() >= HEAL_PP_BELOW:
            self.memo["healing"] = False
            self.event("healed", hp=cur)
            self._attach_heal_outcomes({"result": "healed"})
            return "healed"
        places = [m for m in (PLAYERS_HOUSE_1F,) + POKEMON_CENTERS if m == here or self.world.route(here, m)]
        if not places:
            return "no route to heal"
        dest = min(places, key=lambda m: 0 if m == here else len(self.world.route(here, m)))
        if here != dest:
            return self.go_to_map(here, dest, self.world.maps[here])
        if here == PLAYERS_HOUSE_1F:
            return self.talk_to(MOM_PICTURE)
        return self.talk_to_nurse()

    def prepare(self, ms, here: int) -> Optional[str]:
        """Once per milestone with `prepare`: a Pokémon Center visit (the nurse restores HP and PP), even
        when HP looks fine. None when done or when no Center is known."""
        places = [m for m in POKEMON_CENTERS if m == here or self.world.route(here, m)]
        if not places or self.memo.pop("nurse_talked", False):
            self.memo["prepared"].append(ms.id)   # the dialog that followed the last talk is over
            self.event("prepared", milestone=ms.id, hp=self.party_hp(), attack_pp=self.attack_pp())
            return None
        dest = min(places, key=lambda m: 0 if m == here else len(self.world.route(here, m)))
        if here != dest:
            return self.go_to_map(here, dest, self.world.maps[here])
        tick = self.talk_to_nurse()
        self.memo["nurse_talked"] = tick == "talk nurse"
        return tick

    def balls(self) -> int:
        return sum(n for item, n in bag(self.read).items() if item in battle.BALLS)

    def wants_balls(self) -> bool:
        """No balls, a small party and money to spare: a shopping errand (not after one was given up)."""
        return (not self.balls() and self.read(ADDR["party_count"])[0] < SHOP_BELOW_PARTY
                and self.money() >= SHOP_MIN_MONEY and not self.memo.get("shop_gave_up"))

    def shop(self, here: int) -> Optional[str]:
        """Errand: walk to the nearest known Poké Mart and buy balls. None when no mart is known (the story
        goes on), else the tick's result. `memo["shopping"]` keeps the errand going once begun."""
        places = [m for m in MARTS if m == here or self.world.route(here, m)]
        if not places:
            return None
        if not self.memo.get("shopping"):
            self.memo.update(shopping=True, shop_ticks=0, shop_money=self.money(), shop_balls0=self.balls(),
                             shop_want=shop.balls_to_buy(self.money()))
            self.event("shop_start", money=self.money(), map=here)
        self.memo["shop_ticks"] += 1
        if self.memo["shop_ticks"] > SHOP_GIVE_UP_TICKS:
            self.memo.update(shopping=False, shop_gave_up=True)
            self.event("shop_failed", money=self.money(), map=here)
            return None
        dest = min(places, key=lambda m: 0 if m == here else len(self.world.route(here, m)))
        if here != dest:
            return self.go_to_map(here, dest, self.world.maps[here])
        return self.buy_balls()

    def buy_balls(self) -> str:
        """In the mart: talk to the clerk and answer his boxes (shop.screen) until the balls are in the bag."""
        rows = screen_rows(self.read)
        open_box = shop.screen(rows)
        if open_box == "confirm":
            return self.shop_press("A" if self.read(ADDR["menu_item"])[0] == 0 else "UP")   # OUI
        if open_box == "quantity":
            return self.shop_press("A" if shop.quantity(rows) >= self.memo["shop_want"] else "UP")
        bought = self.balls() > self.memo["shop_balls0"]
        if open_box == "list":
            if bought:
                return self.shop_press("B")
            return self.shop_press("A" if battle.list_cursor(self.read) == 0 else "UP")   # the balls are the first ware
        if open_box == "menu":
            return self.shop_press("B" if bought else "A")   # ACHETER is the first entry and the default
        if text_box_open(self.read):
            return self.shop_press("A")
        if busy(self.read):
            return self.shop_press(None)
        if bought:
            self.memo["shopping"] = False
            self.event("bought", count=self.balls() - self.memo["shop_balls0"], money_before=self.memo["shop_money"],
                       money_after=self.money(), balls=self.balls())
            return "bought"
        return self.talk_to_clerk()

    def shop_press(self, key: Optional[str]) -> str:
        if key:
            self.io.press(key, 90)
        self.io.wait(350)
        return "shop"

    def talk_to_clerk(self) -> str:
        """The clerk is behind the counter: stand two squares right of him, face him over the counter, A."""
        people = overworld.sprite_list(self.read)
        clerk = next((pos for pic, pos in people if pic == shop.CLERK_PICTURE), None) or (min(people, key=lambda p: p[1][0])[1] if people else None)
        if not clerk:
            self.io.wait(300)
            return "no clerk"
        spot = (clerk[0] + 2, clerk[1])
        if self.pos() != spot:
            return self.walk(spot)
        self.io.press("LEFT", 60)
        self.io.wait(200)
        self.io.press("A", 90)
        self.io.wait(500)
        return "talk clerk"

    def _decide_heal(self, cur: int, tot: int, attack_pp: int, here: int) -> str:
        """Ask Jev once per situation whether to heal now or push on. Returns 'heal', 'push', or 'rule'.

        - 'heal'   : heal now (forced cases: HP below HEAL_FORCED_BELOW or 0 attacking PP, no call to chooser)
        - 'push'   : keep going to the goal
        - 'rule'   : no chooser, no route to heal, or chooser returned nothing/garbage; the caller falls back
                     to the old heal rule.
        Memoised by [here, cur*10//tot, min(attack_pp, 10)] in `memo["heal_asked"]`."""
        if not self.choose:
            return "rule"
        share = cur / tot
        if share < HEAL_FORCED_BELOW or attack_pp == 0:
            return "heal"   # forced: no question, no LLM call
        places = [m for m in (PLAYERS_HOUSE_1F,) + POKEMON_CENTERS if m == here or self.world.route(here, m)]
        if not places:
            return "rule"
        heal_place = min(places, key=lambda m: 0 if m == here else len(self.world.route(here, m)))
        if heal_place == here:
            heal_route = None
            heal_maps = 0
        else:
            heal_route = self.world.route(here, heal_place)
            heal_maps = len(heal_route) if heal_route else None
        ms = current(self.read, self.memo)
        goal_map = ms.maps[-1]
        if goal_map == here:
            goal_maps = 0
        else:
            goal_route = self.world.route(here, goal_map)
            goal_maps = len(goal_route) if goal_route else None
        key = [here, cur * 10 // tot, min(attack_pp, 10)]
        asked = self.memo.get("heal_asked")
        if isinstance(asked, list) and asked[0] == key:
            return asked[1]
        state, options = heal_options(cur, tot, attack_pp, heal_place, heal_maps, ms.goal, goal_maps,
                                       self.memo.get("opponent_levels", []))
        instructions = ("Decide whether to heal now or keep going: losing a battle costs half the money and "
                         "sends the party back, while a heal trip costs travel time.")
        got = self.choose(state, options, instructions) or {}
        choice = got.get("choice")
        if choice not in ("heal", "push"):
            return "rule"
        self.memo["heal_asked"] = [key, choice]
        self.event("heal_choice", choice=choice, by=got.get("model", "chooser"),
                   confidence=got.get("confidence"), probabilities=got.get("probabilities"),
                   state=state, options=options, instructions=instructions,
                   usage=got.get("usage"), cost=got.get("cost"), ms=got.get("ms"),
                   decision_id=got.get("decision_id"))
        if choice == "push" and got.get("decision_id"):
            self.memo.setdefault("heal_ids", []).append(got["decision_id"])
        return choice

    def _attach_heal_outcomes(self, outcome: Dict) -> None:
        """Attach `outcome` to any pending heal-or-push decision ids (`memo["heal_ids"]`) and clear them.
        Never raises if `on_battle_end` is None or it itself raises."""
        heal_ids = [i for i in self.memo.get("heal_ids", []) if i]
        self.memo["heal_ids"] = []
        if not heal_ids or not self.on_battle_end:
            return
        try:
            self.on_battle_end(heal_ids, outcome)
        except Exception:
            pass

    def talk_to_nurse(self) -> str:
        """The nurse is the topmost sprite; she is behind the counter: stand two squares below, face up."""
        people = overworld.sprite_list(self.read)
        if not people:
            self.io.wait(300)
            return "no nurse"
        nurse = min(people, key=lambda p: p[1][1])[1]
        spot = (nurse[0], nurse[1] + 2)
        if self.pos() != spot:
            return self.walk(spot)
        if not self.memo.get("nurse_seen"):
            self.memo["nurse_seen"] = True
            self.event("nurse", picture=min(people, key=lambda p: p[1][1])[0], at=list(nurse))
        self.io.press("UP", 60)
        self.io.wait(200)
        self.io.press("A", 90)
        self.io.wait(400)
        return "talk nurse"

    def talk_to(self, picture: int) -> str:
        who = self.sprite_position(picture)
        if not who:
            self.io.wait(300)
            return "nobody"
        return self.talk_at(who)

    def talk_to_nearest(self) -> str:
        """Talk to the nearest present sprite (None in sight: wait)."""
        px, py = self.pos()
        people = [p[1] for p in overworld.sprite_list(self.read)]
        if not people:
            self.io.wait(300)
            return "nobody"
        return self.talk_at(min(people, key=lambda q: abs(q[0] - px) + abs(q[1] - py)))

    def talk_at(self, who) -> str:
        """Face the sprite at `who` and press A (walking next to it first)."""
        px, py = self.pos()
        d = (who[0] - px, who[1] - py)
        if d == (0, 0):
            return self.step_aside()   # the player stands where the person appeared (an item shown under his feet)
        if abs(d[0]) + abs(d[1]) == 1:
            self.io.press({(0, -1): "UP", (0, 1): "DOWN", (-1, 0): "LEFT", (1, 0): "RIGHT"}[d], 60)
            self.io.wait(200)
            self.io.press("A", 90)
            self.io.wait(400)
            return "talk"
        return self.walk(who)

    def step_aside(self) -> str:
        """One step onto a walkable neighbouring square (south first)."""
        px, py = self.pos()
        walk = self.grid()
        for d in ("DOWN", "UP", "LEFT", "RIGHT"):
            dx, dy = overworld.STEP[d]
            if walk.get((px + dx, py + dy)) and self.step(d):
                break
        return "step aside"

    def blocker_on_the_way(self, start, target):
        """The first sprite on the path to `target` when only sprites block it, else None."""
        open_map = self.grid(sprites_block=False)
        path = overworld.astar(open_map, start, target)
        if not path:
            return None
        people = set(overworld.sprites(self.read))
        sq = start
        for d in path:
            sq = (sq[0] + overworld.STEP[d][0], sq[1] + overworld.STEP[d][1])
            if sq in people:
                return sq
        return None

    def sprite_position(self, picture: int):
        """The nearest present sprite with this picture."""
        px, py = self.pos()
        found = [pos for pic, pos in overworld.sprite_list(self.read) if pic == picture]
        return min(found, key=lambda p: abs(p[0] - px) + abs(p[1] - py)) if found else None

    def run(self, seconds: float) -> Dict:
        t0, counts = time.time(), {}
        while time.time() - t0 < seconds:
            what = self.tick()
            counts[what] = counts.get(what, 0) + 1
            if what == "story done":
                break   # nothing left to play: end the run, it saves as usual
            if what in ("no route", "no path", "no route to heal", "no grind area", "nobody", "no nurse", "at goal"):
                self.io.wait(200)  # nothing to do this tick: do not spin
        return {"ticks": sum(counts.values()), "counts": counts, "milestone": current(self.read, self.memo).id,
                "map": self.read(ADDR["map"])[0], "pos": self.pos(), "party": self.read(ADDR["party_count"])[0]}
