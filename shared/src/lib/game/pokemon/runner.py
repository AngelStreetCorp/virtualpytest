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
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

from . import battle, gym, hm, learn, names, overworld, shop, strategy, strength
from .memory import ADDR, busy, decode, dex_page_open, screen_rows, text_box, text_box_open
from .milestones import (CERULEAN_MART, FUCHSIA_CENTER, GAME_CORNER, LAVENDER_CENTER, OAKS_LAB, PEWTER_MART, POKE_FLUTE, ROCKET_B1F, ROCKET_B2F, ROCKET_B4F,
                         HM03_SURF, HM04_STRENGTH, MART_ROOF, ROUTE7_GATE, ROCKET_HIDEOUT, ROCKET_LIFT, SAFARI_ZONE, SURF, ROUTE2, ROUTE4, ROUTE24, TOWER_6F, TOWER_7F, VERMILION_GYM, VIRIDIAN_FOREST,
                         VIRIDIAN_MART, badges, bag, current, party_knows, MT_MOON_B2F, CELADON, SAFFRON,
                         DEFERRED_BY, FUCHSIA, GOOD_ROD, GOOD_ROD_HOUSE, ROAD_TO_FUCHSIA, STRENGTH, CINNABAR_ISLAND, MANSION, MANSION_1F, MANSION_2F, MANSION_3F, MANSION_B1F,
                         CARD_KEY, CARD_KEY_DOORS, CARD_KEY_DOOR_11F, SILPH_CO, SILPH_CO_11F, SILPH_3F, SILPH_5F, SILPH_7F, SAFFRON_GYM)
from .strength import CINNABAR_GYM
from .rom import HM_STRENGTH_BIT, HM_SURF_BIT as SURF_BIT, GameData
from .world import ANY_MAP, INERT_WARPS, OPPOSITE, World, hop_target, links, pad_route

# Surf-learner gifts that pre-empt the Safari Zone hunt (TASK-105). The Magikarp on Mt. Moon B2F is
# the lowest-risk option (the long-play visits Mt. Moon B2F on the way to Cerulean, so the world graph
# already knows the path back from `surf`). The Silph Co. 7F Lapras is mid-game but the long-play's
# milestone flow skips Silph Co. entirely (the world graph does not learn its maps unless visited),
# so in practice only the Magikarp source is reachable from a `surf` milestone — the Lapras is kept
# for completeness. Silph Co. 7F's map id is pokered BLUE: MAP_SILPH_CO_7F EQU $6E
# (pokered/constants/map_constants.asm); the French ROM should match (verified on deploy).
SILPH_CO_7F = 0x6E
MAGIKARP, LAPRAS, GOLDEEN, HORSEA, KRABBY, STARYU = 129, 131, 118, 116, 98, 120   # species ids (Gen 1 internal order)
SURF_LEARNERS = (MAGIKARP, LAPRAS, GOLDEEN, HORSEA, KRABBY, STARYU)                # any party member that can learn Surf
MT_MOON_MAGIKARP_GIFT = (3, 8)   # Mt. Moon B2F: the fisherman's square next to TM08 (to be verified on a save)
SILPH_LAPRAS_GIFT = (3, 3)        # Silph Co. 7F: the scientist's square after Team Rocket is cleared
SURF_GIFT_SOURCES = (("Mt. Moon", MT_MOON_B2F, MT_MOON_MAGIKARP_GIFT, MAGIKARP),
                     ("Silph Co.", SILPH_CO_7F, SILPH_LAPRAS_GIFT, LAPRAS))

OAK_PICTURE = 3
MOM_PICTURE = 51          # in the player's house, ground floor (map 0x25); heals the party
PLAYERS_HOUSE_1F = 0x25
BILLS_PC_SPOT = (1, 5)  # Bill's house: below the PC (1, 4), facing up, starts the cell separator
STARTER_BALL = (8, 3)   # Oak's lab: Bulbasaur's Poké Ball
CINNABAR_CENTER, SAFFRON_CENTER = 0xAB, 0xB6   # BUG-0698: without Cinnabar's, `prepare` for the Mansion walked back to Viridian
POKEMON_CENTERS = (0x29, 0x3A, 0x44, 0x40, 0x59, 0x51, 0x85, LAVENDER_CENTER, FUCHSIA_CENTER,
                   CINNABAR_CENTER, SAFFRON_CENTER)  # Viridian, Pewter, Mt. Moon (Route 4), Cerulean, Vermilion, Route 10, Celadon, Lavender, Fuchsia, Cinnabar, Saffron: the nurse heals behind the counter
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
# BUG-0895: how many presses a square of rock may cost. The game moves the rock one square and
# swallows the presses that land in the animation of the push (pokered's `AnimateBoulderDust` runs
# eight steps of `Delay3` and `DoBoulderDustAnimation` discards the button press), during which the
# player cannot step into the square the rock left: a square of rock costs about four presses.
PUSH_PRESSES_MAX = 6
PUSH_SHORT_TRIES = 3       # ... and how often a push that does not move the rock is tried again
# BUG-0872: how many blank reads in a row mean the emulator page is gone for good. A blank read is the page
# answering nothing (its JavaScript call timed out) and the runner being handed 8 KB of zeros (game_pokemon.py:
# VptGameIO.wram). One is a hiccup, three in a row is a dead page: the run ends there instead of spinning.
BLANK_READ_LIMIT = 3
# BUG-0875: how many ticks in a row with a work-RAM snapshot that does not change at all mean the emulator
# is not running. The game writes its OAM shadow every frame, so a snapshot that never moves is a game
# whose keys go nowhere: its loop is dead or the page is wedged (the second lane's new game of
# 2026-10-23 stood at the title menu for 450 s while the runner pressed A and START into a frozen game).
FROZEN_TICKS = 4
GRIND_MAPS = (VIRIDIAN_FOREST, ROUTE2, ROUTE24, ROUTE4)   # after Misty the party is at Cerulean: Route 24 (wild level 8-14), else Route 4
GRIND_STALL_S = 240      # seconds of training without experience gained before the target is dropped as hopeless
RECRUIT_PARTY = 2         # a `prepare` milestone wants this many Pokémon first
RECRUIT_GIVE_UP_TICKS = 700
CUT_TRIES = 3               # attempts to teach HM01 before it is given up
SURF_HUNT_GIVE_UP = 600     # ticks spent hunting a Surf learner in the Safari Zone before the story moves on. 600 ticks ~ 7 min of game time; the stall detector does not count hunt time (`Runner.self_guarded`), so `surf_deferred = True` is what ends a hopeless hunt. (Was 2400: at ~80 ticks/min that was 30-40 min, past the stall; the runner looped on RUN-only Safari Zone encounters and never set the defer flag — TASK-33 stall 20261015-021503, diagnosis in ~/vpt-private/pokemon/stalls/surf_20261015-021503.diagnosis.md.)
VENDING_SPOT = (12, 3)       # Celadon Mart roof: below the machine at (12, 2) (verified: "Un distributeur!", EAU FRAICHE 200 / SODA COOL 300 / LIMONADE 350)
BAG_SLOTS = 20               # the bag's capacity (the vending machine refuses when it is full)
DRINKS = (0x3C, 0x3D, 0x3E)  # Fresh Water, Soda Pop, Lemonade (item ids)
PRESIDENT_PICTURE = 43      # Silph Co.'s president (read on 11F: the sprite at (7, 5))
BALL_PICTURE = 61           # an item ball's sprite (verified: the Safari Zone's west area shows four)
GYM_TRAINER_WORD = "veut"   # a trainer's battle line in the French ROM: "GIOVANNI veut se battre!" (gym.py knows it too)
# BUG-0719: a gym leader's speech is followed by his battle line ("GIOVANNI veut se battre!") and the battle starts
# right after it: the answer is only settled after a quiet while (the box is closed and no battle started).
GYM_ANSWER_QUIET_S = 18.0   # seconds without a new page before the answer counts as settled
GYM_ANSWER_MAX_S = 40.0     # seconds after the talk before the answer counts as settled, whatever happens
# BUG-0723: how many times the runner steps into the leader's line of sight before he is judged "not the
# leader": the step is the last thing tried (the fight comes from the leader's own script, ~13 s after the talk).
GYM_CHALLENGE_TRIES = 3
GOLD_TEETH = 0x40           # item id (verified: the ball in the Safari Zone's west area added it to the bag)
SAFARI_ORDER = (0xDB, 0xDA, 0xD9, 0xDC)   # where to look for items: west, north, east, centre
HUNT_TICKS_PER_AREA = 120   # Safari Zone: ticks spent wandering one area before the next
GUIDE = "guide_i"
POSTER_GUARD, POSTER_SPOT = (9, 5), (9, 5)   # Game Corner: the guard stands on the square in front of the poster (9, 4)
MANSION_2F_NW_STAIRS = (6, 1)   # BUG-0697: the Mansion 2F stairs into 3F's hole part (the others lead to dead ends)
MANSION_HOLES = ((16, 14), (17, 14), (19, 14))   # 3F's holes: tried in turn until one drops into 1F ((16, 14) does)
MANSION_3F_SWITCH_SPOT = (10, 6)   # below 3F's switch statue: one press opens the gates to the holes (emulator)
MANSION_B1F_SWITCH_SPOTS = ((18, 26), (20, 4))   # below the basement's two statue switches (south, north)
MANSION_B1F_STAIRS = (23, 22)   # the basement's only way out, up to 1F
MANSION_1F_B1F_STAIRS = (21, 23)   # 1F's stairs down to the basement, in the part the 3F hole drops into
# BUG-0705: Blaine's gym is six rooms shut by gates; a quiz machine (faced from the square below) opens the next gate on a
# right answer, a wrong one brings the trainer behind it to fight, and beating him opens it too. Answers: the French ROM's
# questions in machine order (Chenipan -> Papilusion yes, 9 badges no, Ptitard 3 evolutions no, Electric on Ground no,
# same kind and level not identical yes, TM28 no)
CINNABAR_QUIZ = ((15, 7), (10, 1), (9, 7), (9, 13), (1, 13), (1, 7))
CINNABAR_QUIZ_YES = (True, False, False, False, True, False)
QUIZ_IDLE_TICKS = 10   # ticks with no machine in reach and Blaine shut off before they are all asked again
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

    def snapshot(self):
        """The raw work-RAM snapshot of this tick (8 KB). The runner compares it with the previous one to
        see whether the emulator is still running (BUG-0875): the game writes its OAM shadow every frame,
        so a snapshot that never changes is a game whose keys go nowhere."""
        if self.mem is None:
            self.mem = self.io.wram()
        return self.mem

    def reboot(self):
        """Restart the emulator in the page (the ROM, and the save with it, are loaded again). False when
        the page does not answer: the game is then really gone (BUG-0875)."""
        self.mem = None
        reboot = getattr(self.io, "reboot", None)
        return bool(reboot()) if reboot else False


class Runner:
    learn_choice: Optional[Dict] = None         # the decision on the current forget-a-move question
    thrown = 0                                  # balls thrown in the current battle
    no_route_ticks = 0                          # consecutive ticks without a route to the next map
    lift_floor_set = False                      # the elevator's floor was chosen on this ride
    mat_map, mat = None, {}                     # warps stepped off so far on this map: {warp: tries}
    catch_target: Optional[Dict] = None         # the wild Pokémon they went to: species, name, party size before
    stuck = 0                                   # ticks since the last successful step (class default so tests can `object.__new__`)
    busy_ticks = 0                              # consecutive ticks with the input-ignore flag set (BUG-0648)
    blank_reads = 0                             # consecutive blank reads of the game's memory (BUG-0872)
    frozen_ticks = 0                            # consecutive ticks with a game that does not move at all (BUG-0875)
    last_snapshot = None                        # the work-RAM snapshot of the previous tick (BUG-0875)
    intro_now = False                           # the runner is in the intro of a new game (BUG-0875)
    text_ticks = 0                              # consecutive ticks with a text box open (BUG-0653)
    last_pos = None                             # where the player was at the start of the last tick (BUG-0718)
    last_map = None                             # the map he was on at the start of the last tick (BUG-0738)
    step_dir = None                             # the direction of the last step the runner made (BUG-0718)
    answer_texts: tuple = ()                    # the lines the game showed since the last talk (BUG-0718)
    answer_at = 0.0                              # when the game showed the last page of the answer (BUG-0719)
    answer_since = 0.0                           # when the runner talked to the leader candidate (BUG-0719)

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
        self.busy_ticks = 0
        self.blank_reads = 0
        self.text_ticks = 0
        self.answer_texts: List[str] = []   # the lines the game showed since the last talk (BUG-0718)
        self.answer_at = 0.0               # when the game showed the last page of the answer (BUG-0719)
        self.answer_since = 0.0            # when the runner talked to the leader candidate (BUG-0719)

        self.last_pos = None    # where the player was at the start of the last tick (BUG-0718: the game moved him)
        self.last_map = None    # the map he was on then (BUG-0738: a hop that changes map is not a hop)
        self._hop_unwalkable = False   # BUG-0891: the hop of the route could not be walked to
        self.step_dir = None    # the direction of the last step the runner made
        self.step_to = None     # the square that step was to land on
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
        if before != after:
            # BUG-0738: the press that moved the player is the one the game pushes him back from: remember
            # its direction, or a move the runner made itself (the gym leader's "step aside", BUG-0723) is
            # read as the game's push-back and seals the square for ever (the "same_spot" stall of run
            # 20261020-175235: the only way out of the player's pocket in the Viridian gym was sealed).
            self.step_dir = direction
            return True
        # BUG-0740: the key did not move the player (a gym's chevron blocks it and the game carries him
        # later). The direction of the last step says nothing about the move the game is about to make: a
        # stale one made the runner read the carry as a push-back and close the square as a one-way hop
        # tile. The gym's corridor was closed for good, the leader behind it was unreachable, and the run
        # walked between two squares for five minutes (the "no_progress" stall 20261020-213314).
        self.step_dir = None
        return False

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
        if hm.surf_user(self.read) is not None:
            walk.update({sq: True for sq in getattr(walk, "water", ())})   # BUG-0681: Surf known, water is a way (A* charges the menu trip)
        here = self.read(ADDR["map"])[0]
        # BUG-0886: a boulder is not a wall. The runner used to talk to the boulders of Victory Road 1F
        # (the fallback that talks to "the nearest person in the way"), and the three talks marked them
        # as walls for good. The boulder at (2, 10) stands in the one-wide corridor to the stairs
        # (1, 1): with its square walled the floor is cut in two (measured on the stalled save: the
        # player's part drops from 190 squares to 129 and the stairs to Victory Road 2F are out of
        # reach), so the guide walked the runner back to Route 23, whose guide asked for Victory Road 1F
        # again, and the two maps took turns for ever (the same_spot stall of the run 20261024-003359).
        # A boulder is pushed with Strength, not walled: the marks on it are dropped.
        boulders = set(strength.live_boulders(self.read))
        # BUG-0889: a wall mark on a square the floor's puzzle names belonged to a boulder, and the mark
        # outlived the rock: the runner had talked to the boulders of Victory Road 1F until they were
        # walled (the bug of BUG-0885), and when the boulder was pushed away its square stayed walled.
        # The corridor boulder (2, 10) stands in the one-wide passage to the stairs (1, 1): with its
        # square walled the floor is cut in two, the stairs are out of reach, the guide walks the runner
        # back to Route 23 and the lane stalls with "no_progress" on map 108 (the run 20261024-093928:
        # 23 minutes of play, 37 boulder pushes and no new square). A boulder is a rock, not a person:
        # the marks on the squares it stands on - and on the squares it has left - are dropped.
        puzzle = strength.puzzle_for(here)
        rocks = {tuple(w[0]) for w in puzzle.plan} if puzzle else set()
        # BUG-0893: the barrier of a floor is the game's business, not the runner's. BUG-0892
        # opened the barrier on the rocky ridge of Victory Road 1F as soon as the runner's own
        # chain counter said the boulder of the pressure switch was on the switch tile. The game
        # does not open it: measured on the live save, the boulder the chain pushes onto
        # (17, 13) falls into the hole that tile is (it is gone from the sprite list), the map's
        # block table stays the one of the ROM and the barrier on the ridge stays closed for ever
        # (the game's own tile-pair collision says (5, 8) and (5, 9) cannot be walked between).
        # A grid that believes the barrier is open plans a path into a wall the game refuses: the
        # player ping-pongs in the grass of the floor and the stall detector writes "no_progress"
        # (the run 20261024-134917: 22 wild battles, no new square in 11 minutes, the save locked).
        # The grid follows the game's own collision data now: when the game opens a barrier, the
        # tiles of the floor change and the wall pairs go with them. The pressure switch's plan
        # and its tile are unchanged - the chain still pushes the boulder to (17, 13); only the
        # runner's guess about what the game does with it is gone.
        for sq in self.memo.get("walls", {}).get(str(here), []):
            t = (sq[0], sq[1]) if isinstance(sq, (list, tuple)) else sq
            if t in boulders or t in rocks:
                continue
            if t in walk:
                walk[t] = False
        for sq in self.memo.get("hops", {}).get(str(here), []):   # BUG-0718: the game's one-way hop tiles
            t = (sq[0], sq[1]) if isinstance(sq, (list, tuple)) else sq
            if len(sq) > 3:      # BUG-0741: the mark remembers where the carry lands: the tile is a passage
                self.hop_jump(walk, t, (sq[2], sq[3]))
            if t in walk and t != self.pos() and not self.plain_floor(walk, t):
                walk[t] = False
        return walk

    def hop_jump(self, walk, tile, land) -> None:
        """BUG-0741: a chevron the game carries the player over is a passage, not a trap: the grid jumps over it
        the way it jumps over the ledges. `tile` is the square the player stood on and `land` is where the game
        carried him. From the square before the tile, the key in the carry's direction moves him onto the tile and
        the game carries him over to `land`; from the tile itself, the same key carries him on. Closing the tile
        for ever (the old model) cut the only way out of the Viridian gym and the runner stood still for 300 ticks
        (the same_spot stall of run 20261020-223419)."""
        dx, dy = land[0] - tile[0], land[1] - tile[1]
        if abs(dx) + abs(dy) == 0 or (dx and dy):
            return     # no carry, or a diagonal one: nothing to model
        step = ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
        d = {(-1, 0): "LEFT", (1, 0): "RIGHT", (0, -1): "UP", (0, 1): "DOWN"}[step]
        jumps = getattr(walk, "jumps", None)
        if jumps is None:
            return
        for sq in ((tile[0] - step[0], tile[1] - step[1]), tile):
            jumps.setdefault(sq, []).append((d, land))

    def plain_floor(self, walk, square) -> bool:
        """True when the square carries the plain floor of the map (the tile most of its walkable squares share).
        BUG-0738: a one-way hop tile is never the plain floor, so a hop mark on it is a wrong one - the runner's
        own step was read as the game's push-back - and it must not close the square: the stall 20261020-175235
        sealed the only way out of the player's pocket in the Viridian gym with such a mark. A grid without tile
        data (a layout) trusts every mark."""
        tiles = getattr(walk, "tiles", None)
        if not tiles:
            return False
        floor = Counter(t for sq, t in tiles.items() if walk.get(sq)).most_common(1)
        return bool(floor) and tiles.get(square) == floor[0][0]

    def note_hop(self, here: int, pos_now) -> None:
        """The game carried the player: the square he stood on is a one-way hop tile (the chevron squares of a
        gym) and the mark remembers where the carry landed him (BUG-0741), so the runner can cross the tile the way
        the game carries him instead of having it closed for ever.
        BUG-0738: only the game pushes the player back. The runner's own step (the gym leader's "step aside")
        moves him one square the other way, and it was read as a push-back: the square was closed for ever and
        the player was sealed in the pocket it was the only way out of. The press that moved the player is the
        direction the game would push him back from, so the runner's own step is never a hop.
        A hop that changes map is not a hop either: the square he came from is on the map he left."""
        if self.last_pos is None or pos_now == self.last_pos or not self.step_dir:
            return
        if self.last_map is not None and here != self.last_map:
            return
        step = overworld.STEP.get(self.step_dir, (0, 0))
        if (pos_now[0] - self.last_pos[0], pos_now[1] - self.last_pos[1]) == (-step[0], -step[1]):
            hops = self.memo.setdefault("hops", {}).setdefault(str(here), [])
            mark = [self.last_pos[0], self.last_pos[1], pos_now[0], pos_now[1]]
            if not any(h[:2] == mark[:2] for h in hops):
                hops.append(mark)   # BUG-0741: with the landing square: the tile is a passage, not a dead end
                self.event("hop", map=here, at=list(self.last_pos), to=list(pos_now))
            self.step_dir = None   # the hop plays over several squares: only the first one is the hop tile

    # --- one tick ----------------------------------------------------------------------------
    def tick(self) -> str:
        if hasattr(self.io, "refresh"):
            self.io.refresh()  # one fresh snapshot per tick, whatever the previous tick did
        now = time.time()
        if self.game_is_frozen():
            # BUG-0875: the emulator is not running (its loop is dead or the page is wedged): the keys go
            # nowhere. Restart the emulator in the page, so the run goes on from the save; when the page
            # does not answer at all the game is gone: the run ends there, before the detector sees it, so
            # no stall and no lock are written and the dispatcher keeps playing (as BUG-0872 wanted).
            if self.reboot_emulator():
                self.event("emulator_restarted", ticks=self.frozen_ticks)
                self.frozen_ticks = 0
                self.last_snapshot = None
                return "emulator restart"
            self.event("emulator_gone", ticks=self.frozen_ticks)
            return "emulator gone"
        # BUG-0718: the game moved the player (a one-way hop tile in a gym): the runner had stepped onto it
        here = self.read(ADDR["map"])[0]
        pos_now = self.pos()
        self.note_hop(here, pos_now)
        self.last_pos = pos_now
        self.last_map = here
        if self.memo.get("grinding") and self._last_tick:
            self.memo["grind_s"] = self.memo.get("grind_s", 0.0) + min(5.0, now - self._last_tick)   # play time only
        self._last_tick = now
        if "starter" in self.memo.get("done", []) and not self.read(ADDR["party_count"])[0]:
            # a blank memory read (seen on a host: no Pokémon, money 0): it would look like a defeat
            # BUG-0872: the emulator page died (the host's journal: "Page screenshot timed out after 20s",
            # then no live page) and every read of the game's memory waits out its 15 s timeout and answers
            # with nothing: `VptGameIO.wram()` hands the runner 8 KB of zeros (game_pokemon.py) that look
            # like an empty game. The runner used to wait 300 ms and read again for ever: the run of
            # 20261023-132854 spun 9 min 35 s with no event at all, the detector then called it
            # "no_progress" at map 0, pos (0, 0) - a map the game is not on - and the LOCK stopped every
            # later run. The game is gone: end the run there instead of spinning on it.
            self.blank_reads += 1
            if self.blank_reads >= BLANK_READ_LIMIT:
                self.event("emulator_gone", reads=self.blank_reads)
                return "emulator gone"
            self.io.wait(300)
            return "bad read"
        self.blank_reads = 0   # the game answered: the count of blank reads starts again
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
        intro = self.in_intro()
        self.intro_now = intro
        if intro:
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
            self.answer_texts = []       # BUG-0719: the battle's text is not an answer to a talk
            self.forget_not_leader()     # BUG-0719: the game has proven him a trainer
            return self.battle_tick()
        self.disabled = None
        here = self.read(ADDR["map"])[0]
        if self.memo.get("shopping") and here in MARTS:
            shopped = self.shop(here)   # the clerk's boxes are answered on purpose, not with a blind A
            if shopped:
                return shopped
        if dex_page_open(self.read):
            self.io.press("A", 90)   # BUG-0643: the prize Pokémon's dex page waits for A, walking keys do nothing
            self.io.wait(250)
            return "dex page"
        if text_box_open(self.read):
            t = text_box(self.read)
            self.answer_texts = list(self.answer_texts) + [t]   # BUG-0718: a trainer answers with a battle line
            self.answer_at = time.time()   # BUG-0719: the answer is only settled after a quiet while
            self.text_ticks += 1
            if self.text_ticks >= 60:   # BUG-0653: NPC lines cycle with no move (about 15 s): B twice closes the box
                self.event("text_stuck", ticks=self.text_ticks, pos=list(self.pos()), map=self.read(ADDR["map"])[0])
                self.io.press("B", 90)
                self.io.wait(250)
                self.io.press("B", 90)
                self.io.wait(250)
                self.text_ticks = 0
                return "text stuck"
            self.io.press("B" if "surnom" in t.lower() else "A", 90)
            self.io.wait(250)
            return "text"
        self.text_ticks = 0   # BUG-0653: any tick that is not a text tick starts the count again
        if busy(self.read):
            self.busy_ticks += 1
            if self.busy_ticks % 20 == 0:   # BUG-0648: no text box and the controls stay locked (about 5 s): press A once
                self.event("cutscene_stuck", ticks=self.busy_ticks)
                self.io.press("A", 90)
            self.io.wait(250)
            return "cutscene"
        self.busy_ticks = 0
        if self.stuck >= 3 and hm.menu_open(screen_rows(self.read)):
            hm.close_menus(self)   # a menu trip cut short (the bag left open) would swallow every walking key press
            self.stuck = 0
            return "close menu"
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
        if self.read(ADDR["map"])[0] in SAFARI_ZONE:
            return self.safari_tick()
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
        must_catch = st["kind"] == "wild" and self.surf_wanted(st["enemy"]["species"])   # BUG-0673: the Surf learner
        out = {"choice": battle.heuristic_choice(opts, share, self.memo.get("last_move"),
                                                 travelling=not self.memo.get("grinding") and not self.must_fight(),
                                                 must_catch=must_catch), "by": "heuristic"}
        if self.choose and not must_catch:
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

    def safari_tick(self) -> str:
        """Safari battles have no fight: BALL / BAIT / ROCK / RUN. Run from everything, except a species that can
        learn Surf while nobody in the party can: Safari Balls are thrown at it until it is caught."""
        rows = screen_rows(self.read)
        if not battle.safari_menu_open(rows):
            self.io.press("B", 90)   # B advances a text too, and does nothing on a menu still being drawn (A there throws a ball)
            self.io.wait(300)
            return "battle text"
        enemy = battle.state(self.read)["enemy"]
        want = self.surf_wanted(enemy["species"])
        for key in ["UP", "LEFT"] if want else ["UP", "LEFT", "DOWN", "RIGHT"]:   # the cursor is remembered: start from BALL
            self.io.press(key, 90)
            self.io.wait(150)
        if want and not self.thrown:
            self.catch_target = {"species": enemy["species"], "name": battle.names(self.read)["enemy"],
                                 "party": self.read(ADDR["party_count"])[0]}
        self.thrown += 1 if want else 0
        self.last_choice_kind = "catch" if want else "run"
        if not self.battle_turns:
            self.event("safari_battle", map=self.read(ADDR["map"])[0], pokemon=battle.names(self.read)["enemy"], types=sorted(set(enemy["types"])), throw=want)
        self.battle_turns += 1
        self.io.press("A", 90)
        self.io.wait(600)
        return "safari ball" if want else "safari run"

    def surf_wanted(self, species: int) -> bool:
        """`species` can learn Surf, nobody in the party can, and there is room for it (ROM TM/HM flags)."""
        n = self.read(ADDR["party_count"])[0]
        mine = self.read(ADDR["party_species"], min(n, 6))
        return n < 6 and self.data.can_learn(species, SURF_BIT) and not any(self.data.can_learn(m, SURF_BIT) for m in mine)

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

    def lift_defers(self) -> None:
        """BUG-0673: a defer flag whose move the party knows now (a learner joined later) is cleared, and the
        milestones it let through are taken out of `done`: they are played, not skipped."""
        for flag, move in (("surf_deferred", SURF), ("strength_deferred", STRENGTH)):
            if self.memo.get(flag) and party_knows(self.read, move):
                self.memo.pop(flag)
                done = self.memo.setdefault("done", [])
                reopened = [m for m in DEFERRED_BY[flag] if m in done]
                self.memo["done"] = [m for m in done if m not in reopened]
                self.event("deferred_cleared", flag=flag, reopened=reopened)

    def overworld_tick(self) -> str:
        self.lift_defers()
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
            if self.memo.get("milestone") == "silph_co":
                # BUG-0711: Giovanni beaten, the Rockets below Saffron's doors are gone: their squares (the gym's (34, 4)
                # among them) are no walls any more
                self.memo.get("walls", {}).pop(str(SAFFRON), None)
            self.memo["milestone"], self.memo[GUIDE] = ms.id, 0
            self.memo.pop("story_done", None)   # a milestone was added since the story ended
            self.event("milestone", id=ms.id, goal=ms.goal)
            self._attach_heal_outcomes({"result": "milestone reached"})
            self.rethink(f"new milestone {ms.id}")
        here = self.read(ADDR["map"])[0]
        # BUG-0886: the game puts the boulders of a floor back where they were when the player leaves
        # it and comes back, so the pushes of a floor start over on the second visit (the stalled save
        # of 20261024-003359 had seven pushes of the pressure switch logged and the boulder of the
        # switch back at (5, 15), where it started). The counter of the floor's plan is reset when the
        # map the player stands on changes.
        if self.memo.get("pokemon_map") not in (None, here):
            self.memo["seafoam_pushes_done"] = 0
            # BUG-0896: the game puts the boulders of a floor back where they were, so a floor
            # whose plan was given up can be solved again on the next visit.
            self.memo.pop("seafoam_plan_given_up", None)
            # BUG-0890: another floor, another chance: the pushes the game refused there do not
            # apply here.
            self.memo.pop("push_refused", None)
            # BUG-0891: another floor, another chance: the hop that a boulder sealed on that floor
            # is walkable here (the game put the boulders of that floor back where they were).
            self.memo.pop("hop_blocked", None)
        self.memo["pokemon_map"] = here
        info = self.world.learn(self.read, self.grid(sprites_block=False))
        self.note_entry(here)
        # advance the guide pointer to the furthest guide map we are on
        maps = ms.maps
        i = min(self.memo.get(GUIDE, 0), len(maps) - 1)   # BUG-0690: a saved pointer past a milestone whose route got shorter
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
                healing = self.heal(here, cur, tot)
                if healing != "no route to heal":
                    return healing
                # BUG-0877: the way to a healing place is not known: the trip waits and the runner
                # goes on playing the story instead of spinning on "no route to heal" for ever.
                if not self.memo.get("heal_waiting"):
                    self.memo["heal_waiting"] = True
                    self.event("heal_waiting", map=here, hp=cur, max_hp=tot)
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
        if self.memo.get("hm_party") != n:
            self.memo["hm_party"], self.memo["hm_tries"] = n, {}   # a new Pokémon may be able to learn what the others could not
        todo = hm.pending_hm(self.read, self.memo.setdefault("hm_tries", {}), CUT_TRIES)
        if todo:
            return self.teach_hm(*todo)
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
        goal_part = None
        if maps[i] == here or here in ms.area:
            j = min(i + 1, len(maps) - 1)   # inside a detour the route leads through (Cerulean's house): on, not back
            nxt = maps[j]
            if j + 1 < len(maps):
                # BUG-0689: into the part of the next map that holds the way on. Seafoam B1F's nearest ladder lands in a
                # dead-end corner of B2F, whose only way on to B3F is back up: the runner went up and down that ladder
                goal_part = self.world.part_with_warp_to(nxt, maps[j + 1])
                if goal_part is not None and not self.world.route(here, nxt, start_part=(info.get("parts") or {}).get("player"),
                                                                  goal_part=goal_part):
                    goal_part = None
            # BUG-0880: the waypoint the guide asks for can be a map the runner cannot reach from where it
            # stands. On Route 23 the next waypoint was Victory Road 2F (194) and the only warp to 194
            # sits in another part of the map, so every tick answered "no route", the player never moved
            # and the stall detector wrote "same_spot" (the run of 20261023-213300). When there is no way
            # on, the runner walks back to the waypoint it came from instead of standing still.
            # BUG-0891: a hop the player cannot walk to is no way on either (the boulder that seals the
            # corridor to the stairs of Victory Road 1F): the runner walks back to Route 23, the game
            # puts the boulders of the floor back where they were, and the floor can be solved.
            if maps[i] == here and (self.hop_blocked(here, nxt)
                                    or not self.world.route(here, nxt, start_part=(info.get("parts") or {}).get("player"))):
                part = (info.get("parts") or {}).get("player")
                if self.way_on_in_area(here, ms.area, part):
                    # BUG-0963: the way on is in the milestone's area (Cerulean's trashed house, the door
                    # to the path under Route 5): the runner explores it instead of walking back to the
                    # waypoint it came from, which sent it back and forth between Cerulean and Route 24
                    # for ever (the run of 20261026-204910: no milestone, no new map and no new square
                    # for 5 min of game time).
                    self.memo.pop("waypoint_unreachable", None)
                else:
                    back = next((m for m in reversed(maps[:i])
                                 if not self.hop_blocked(here, m)
                                 and self.world.route(here, m, start_part=(info.get("parts") or {}).get("player"))), None)
                    if back is not None:
                        if self.memo.get("waypoint_unreachable") != [here, nxt, back]:
                            self.memo["waypoint_unreachable"] = [here, nxt, back]
                            self.event("waypoint_unreachable", map=here, wanted=nxt, back=back)
                        nxt, goal_part = back, None
                    else:
                        self.memo.pop("waypoint_unreachable", None)
        else:
            # off the route (a detour to heal, a building): back to the route map last reached,
            # or the closest route map we know a way to
            reachable = [m for m in [maps[i]] + maps if self.world.route(here, m)]
            nxt = reachable[0] if reachable else maps[-1]
        return self.go_to_map(here, nxt, info, goal_part=goal_part, explore=ms.area, anywhere=True)   # `area`: maps to visit when no route is known yet

    def story_step(self, ms, here: int, info: Dict) -> Optional[str]:
        """The places where the story is more than "walk to the next map": None when the guide is enough."""
        if ms.id == "lift_key" and here == GAME_CORNER:
            return self.game_corner_poster()
        if here != ROCKET_LIFT:
            self.lift_floor_set = False
        if here in ROCKET_HIDEOUT:
            return self.hideout_step(ms, here, info)
        if ms.id == "silph_co" and here in SILPH_CO:
            return self.silph_step(here, info)
        if ms.id == "secret_key" and here in MANSION:
            return self.mansion_step(here)
        if here in (MANSION_1F, MANSION_B1F):
            return self.mansion_way_out(here)
        if ms.id == "poke_flute" and here == TOWER_7F:
            return self.talk_to_topmost()
        if ms.id == "surf" and self.needs_surf_learner():
            # TASK-105: pre-empt the Safari Zone hunt with a guaranteed gift (Mt. Moon Magikarp /
            # Silph Co. Lapras) before falling back. The gift method returns None when no source is
            # reachable from `here`, on a party-full rejection, or after six failed talk attempts;
            # in any of those cases the Safari Zone hunt runs as before.
            gift = self.catch_surf_learner(here, info)
            if gift is not None:
                return gift
            return self.hunt_surf_learner(here, info)
        if ms.id == "surf_learner":
            return self.surf_rod_step(here, info)
        if ms.id == "strength":
            return self.strength_step(here, info)
        if ms.id == "saffron":
            return self.saffron_step(here, info)
        if ms.id == "hall_of_fame" and here in strength.VICTORY_ROAD:
            return self.strength_puzzle_step(here, info)
        return None

    def saffron_step(self, here: int, info: Dict) -> Optional[str]:
        """A drink from the roof's vending machine first (once), then the gate guard takes it. None: walk on.

        When the drink is in the bag and the runner is NOT at ROUTE7_GATE, the saffron_area's A* is
        `first_hop_ok`-filtered by the runner's current part of the current map. The runner can be
        in a part of Celadon that doesn't include any saffron-area edge (the saffron area covers
        Route 7 (0x12), the gates around Saffron, the underground path, and the path gates to
        Route 5/6). When the runner's part is stuck in the south-east of Celadon (e.g. (39, 20),
        stall 20261015-091504, stall 20261015-121504), the A* picks a south-gate warp as the first
        hop and the runner stalls at `warp_unusable` on (39, 19). Walk the runner to the closest
        saffron-edge square before letting the A* route, so `first_hop_ok` is satisfied for the
        direct edge to Route 7 (or any other saffron-area map).

        BUG-0607: when the runner is on a saffron-area map OTHER than Celadon (already past Celadon),
        filter saffron-edges to only those whose destination is closest to SAFFRON via the world
        graph. Without this, on Route 7 (0x12) the runner at the west edge (e.g. (0, 3) — entered
        from Celadon, host run 20261017-174506) can pick the south edge to PATH_ROUTE7 (0x4D)
        over the east edge to ROUTE7_GATE (0x4C) by Manhattan distance (both roughly tied). The
        runner then walks into PATH_ROUTE7 → Route 8 west → PATH_ROUTE8 → Route 7 east →
        ROUTE7_GATE and ends up back on Celadon's east side at (48, 11) (host run 20261017-194505:
        `lost: [77, 18]` = PATH_ROUTE7 (0x4D = 77) at y=18, then re-entry to Celadon at (48, 11)).
        The world-graph hop-distance to SAFFRON identifies the correct saffron-edge: ROUTE7_GATE
        is 1 hop from SAFFRON; PATH_ROUTE7 is 5+ hops. Pick the saffron-edge with the minimum
        hop distance to SAFFRON.
        """
        self.note_items()
        if here == CELADON and self.memo.get("drink_bought") and not any(d in bag(self.read) for d in DRINKS):
            # BUG-0634: the flag says a drink was bought, but none is in the bag (given away or lost). Without
            # this, the MART_ROOF buy below is skipped for ever and the runner heads for the roof with no drink.
            self.memo["drink_bought"] = False
            self.event("drink_missing", map=here)
        if any(d in bag(self.read) for d in DRINKS):
            had_drink_before = bool(self.memo.get("drink_bought"))
            self.memo["drink_bought"] = True
            if here == ROUTE7_GATE:
                return self.talk_to_nearest()
            # the runner is on a saffron-area map but not at the gate: route the runner to a part
            # of the current map that has a saffron-area connection. The saffron area covers:
            # Route 7 (0x12), ROUTE7_GATE (0x4C), and the gate/path maps to the north, east, and
            # south of Saffron. The runner's own `reachable` partition is the source of truth for
            # what the A* can route to — if the runner's part has no saffron edge, the A* would
            # pick a south-gate warp as the only valid first hop and stall.
            saffron_maps = (0x12, 0x4C, 0x47, 0x4A, 0x4D, 0x50, 0x57, 0x79)   # Route 7, ROUTE7_GATE, path/gate maps around Saffron
            # Group saffron-edge squares by their destination map; the BUG-0607 filter (below)
            # removes destinations that would loop the runner back through PATH_ROUTE7/PATH_ROUTE8
            # south of Cycling Road instead of progressing east toward ROUTE7_GATE.
            saffron_edges_by_dest: Dict[int, List[Tuple[int, int]]] = {}
            for side, dest in (info.get("edges") or {}).items():
                if dest in saffron_maps:
                    saffron_edges_by_dest[dest] = saffron_edges_by_dest.get(dest, []) + \
                        overworld.edge_squares(
                            self.grid(sprites_block=False), side, info.get("spans", {}).get(side))
            # BUG-0607: when not on Celadon, prefer saffron-edges whose destination is closest to
            # SAFFRON via the world graph. On Celadon the runner might be in a wrong partition
            # and need to walk to ANY saffron-edge (not necessarily the closest-to-Saffron one);
            # the BUG-0589/0596 logic handles that. Once past Celadon, the runner is committed to
            # the saffron path and must not detour back through PATH_ROUTE7/PATH_ROUTE8.
            saffron_edges: List[Tuple[int, int]]
            if here != CELADON and saffron_edges_by_dest:
                world = getattr(self, "world", None)
                if world is not None and hasattr(world, "route"):
                    def dist_to_saffron(d: int) -> int:
                        if d == SAFFRON:
                            return 0
                        r = world.route(d, SAFFRON)
                        if r:
                            return len(r)
                        # BUG-0629: SAFFRON is not in the graph until the runner has been there, so every
                        # route is unknown and the tie went to the closest edge (PATH_ROUTE7, the loop).
                        # ROUTE7_GATE is the gate to Saffron: it is the one edge that is never far.
                        return 1 if d == ROUTE7_GATE else 10 ** 6   # other unknown routes: far (never picked over a known shorter one)
                    best_dist = min(dist_to_saffron(d) for d in saffron_edges_by_dest)
                    saffron_edges = [sq for d, sqs in saffron_edges_by_dest.items()
                                     if dist_to_saffron(d) == best_dist for sq in sqs]
                else:
                    saffron_edges = [sq for sqs in saffron_edges_by_dest.values() for sq in sqs]
            else:
                saffron_edges = [sq for sqs in saffron_edges_by_dest.values() for sq in sqs]
            # BUG-0632: Route 7's east edge leads to SAFFRON (10), not to ROUTE7_GATE, so it is no saffron-edge
            # and the list above is empty here. The gate house is a warp in the middle of Route 7, reached
            # from the west part. Until the runner has learned it, go_to_map would take the known route to
            # SAFFRON (world.route, 16 hops via PATH_ROUTE7 and Route 8) before any explore toward the gate.
            if not saffron_edges and here in saffron_maps and ROUTE7_GATE not in self.world.maps \
                    and self.world.route(here, ROUTE7_GATE):
                return self.go_to_map(here, ROUTE7_GATE, info)
            if saffron_edges:
                part = overworld.reachable(self.grid(sprites_block=False), self.pos())
                if not any(sq in part for sq in saffron_edges):
                    target = min(saffron_edges, key=lambda s: abs(s[0] - self.pos()[0]) + abs(s[1] - self.pos()[1]))
                    # BUG-0597: also bump GUIDE on the same call before walking one step.
                    # The walk moves the runner toward the saffron-edge; the bump ensures the next
                    # observe's GUIDE pointer is past MART_ROOF (so go_to_map does not detour back
                    # to the vending machine while the runner is walking).
                    if had_drink_before:
                        self._saffron_skip_drink_detour(here)
                    return self.walk(target)
            # BUG-0596: also when the runner IS on a partition that already has a saffron-edge, walk
            # toward it explicitly. The earlier check ('part includes saffron-edge ⇒ return None')
            # skipped the walk, but the host then sat on (39, 20) for the whole 2000-s budget because
            # `go_to_map` cannot start a one-step A* to a far edge from a position right next to a
            # celadon-mart warp (the runner's own part technically owns the edge, but the A* picks
            # the south-gate warp at (39, 19) as the first hop and stalls — same shape as the BUG-0589
            # stall, just on a different partition). Walk to the saffron-edge on every CELADON observe
            # while the drink is in the bag; once the runner is on the edge, the next observe lets A*
            # cross east to Route 7. BUG-0597: also bump GUIDE on this same call (so the runner
            # doesn't wait many ticks for the bump to happen — the bump fires in the SAME tick that
            # saffron_step issues the first walk, instead of being delayed until the runner reaches
            # the edge many ticks later).
            if saffron_edges:
                target = min(saffron_edges, key=lambda s: abs(s[0] - self.pos()[0]) + abs(s[1] - self.pos()[1]))
                if self.pos() != target:
                    if had_drink_before:
                        self._saffron_skip_drink_detour(here)
                    return self.walk(target)
            if had_drink_before:
                self._saffron_skip_drink_detour(here)
            return None
        if here == MART_ROOF and not self.memo.get("drink_bought"):
            items = list(bag(self.read))
            if len(items) >= BAG_SLOTS and self.memo.get("toss_failed") != items:   # "L'inventaire est plein": make room first
                item = hm.toss_item(self)
                self.memo["toss_failed"] = None if item else items   # the same bag is not tried twice
                self.event("tossed" if item else "toss_failed", item=item)
                return "toss item"
            return self.buy_drink()
        return None

    def _saffron_skip_drink_detour(self, here: int) -> None:
        """The saffron milestone lists MART_ROOF between two CELADON entries: `[..., ROUTE7,
        CELADON, MART_ROOF, CELADON, ROUTE7, SAFFRON]`. When the runner is on CELADON and the
        drink is already in the bag, the GUIDE pointer can still be parked on the first CELADON
        — the overworld_tick would then ask go_to_map to route the runner back to MART_ROOF
        (a redundant detour to a vending machine it doesn't need). Bump GUIDE to the second
        CELADON so the route uses the saffron area directly.

        Idempotent and safe on a runner built via `object.__new__` (no `world`, no `current()` —
        those are test-only constructions): guard on what we need.
        """
        if here != CELADON or not self.memo.get("drink_bought"):
            return
        memo = getattr(self, "memo", None)
        if not isinstance(memo, dict):
            return
        i = memo.get(GUIDE, 0)
        # `current()` reads from the save (moneymap, milestone predicates); cheap, but only use it
        # when the read callback exists — the test-only Runner has it as a plain function.
        try:
            ms = current(self.read, memo)
        except Exception:
            return
        if ms.id != "saffron":
            return
        maps = getattr(ms, "maps", None)
        if not isinstance(maps, (list, tuple)) or not maps or maps[i] != here:
            return
        # Skip over the MART_ROOF detour: bump GUIDE to the next occurrence of `here` in the maps.
        later = [j for j in range(i + 1, len(maps)) if maps[j] == here]
        if later:
            memo[GUIDE] = later[0]
            self.event("guide_skip", milestone=ms.id, from_=i, to=later[0], map=here)
            # Reset the same-spot stall counter: the GUIDE bump means the runner is on a
            # NEW route (the saffron-area edge way, not the MART_ROOF detour), and the
            # runner's current position is a temporary waypoint shared with the old route.
            # The same_spot stall would otherwise trigger instantly because the memo
            # carried a 600+ spot_ticks from earlier failing runs on the same square;
            # the bump alone does not move the player on the screen, so the detector
            # sees another same-spot tick and stalls.
            stall = memo.get("stall")
            if isinstance(stall, dict):
                stall["spot"] = None
                stall["spot_ticks"] = 0
                stall["progress_s"] = 0.0

    def buy_drink(self) -> str:
        """Stand below the first machine, face it, A: its list opens (the texts are answered by the tick; the first
        entry, the cheapest drink, is under the cursor)."""
        if self.pos() != VENDING_SPOT:
            return self.walk(VENDING_SPOT)
        self.io.press("UP", 60); self.io.wait(200)
        self.io.press("A", 90); self.io.wait(500)
        return "vending machine"

    def strength_step(self, here: int, info: Dict) -> Optional[str]:
        """Until the Gold Teeth are in the bag: take every item ball in the Safari Zone's areas, west first. None once
        they are (the Warden's house is the goal then)."""
        if GOLD_TEETH in bag(self.read) or HM04_STRENGTH in bag(self.read):
            # HM04 may be in the bag with no party member that can learn Strength (Gen-1 Strength
            # learners: Mankey, Machop, Geodude, Onix, Cubone, Rhyhorn, Graveler, etc. — the
            # Venusaur-line party has none). When the teach has been tried `CUT_TRIES` times the
            # runner would otherwise loop on the Warden at the Warden's House pressing A; set
            # `strength_deferred = True` so the milestone predicate fires and the guide walks the
            # runner on. The Boulder puzzles in Seafoam and Victory Road will fail without a real
            # Strength-learner — that's a follow-up (mirror of TASK-35 for Surf). Clear the
            # `hm_tries["Strength"]` counter so a future new party member is a fresh attempt.
            if HM04_STRENGTH in bag(self.read) and not self.memo.get("strength_deferred"):
                n = self.read(ADDR["party_count"])[0]
                party = self.read(ADDR["party_species"], min(n, 6))
                if not any(self.data.can_learn(m, HM_STRENGTH_BIT) for m in party):
                    self.memo["strength_deferred"] = True
                    self.memo.get("hm_tries", {}).pop("Strength", None)
                    self.event("strength_deferred", party=n, reason="no learner in party",
                               tries=str(self.memo.get("hm_tries", {})))
            return None
        self.note_items()
        if here in SAFARI_ZONE:
            ball = self.next_ball(here)
            if ball:
                return self.take_ball(here, ball)
            todo = [m for m in SAFARI_ORDER if m not in self.memo.setdefault("balls_done", [])]
            if here in todo:
                self.memo["balls_done"].append(here)   # every ball in sight is taken: the next area
            todo = [m for m in SAFARI_ORDER if m not in self.memo["balls_done"]]
            return self.go_to_map(here, todo[0], info, anywhere=True) if todo else None
        return self.go_to_map(here, SAFARI_ORDER[0], info, anywhere=True)

    def strength_puzzle_step(self, here: int, info: Dict) -> Optional[str]:
        """Plan and execute one Strength boulder push on a Seafoam / Victory Road puzzle map.

        The solver (`strength.plan_strength_puzzle`) returns the canonical push list when the floor's
        boulder sprite count is at its open threshold; once one boulder has been pushed into a hole
        the count drops and the solver returns None. The runner caches the plan in `memo` on its
        first successful read and tracks per-map progress in `memo["seafoam_pushes_done"]`, so the
        remaining pushes are still executed across subsequent ticks of the same visit. When all
        pushes in the plan are done, the floor's drain flag (`seafoam_drained_b3f` /
        `seafoam_drained_b4f`) is set so the `seafoam` milestone predicate can fire.

        Returns None when no plan is available (non-puzzle map, or floor is no longer "open" and
        no plan was cached): the regular guide walks the runner off the floor. Memo is left
        untouched in that case.
        """
        # Ask the solver for a plan; fall back to the cached plan when the boulder sprite count
        # has dropped below the open threshold (the solver stops returning a plan mid-floor).
        plan = strength.plan_strength_puzzle(self.read, here)
        if plan is None and self.memo.get("seafoam_puzzle_map") == here:   # BUG-0690: never another floor's plan
            plan = self.memo.get("seafoam_plan")
        if plan is None:
            return None

        # Map-change reset: only after confirming we have a plan, so a non-puzzle map leaves memo
        # untouched and we never carry a half-done counter onto a new puzzle floor.
        if self.memo.get("seafoam_puzzle_map") != here:
            self.memo["seafoam_puzzle_map"] = here
            self.memo["seafoam_pushes_done"] = 0

        # BUG-0881: a plan that changed starts its pushes over: the counter of the old plan would skip
        # the pushes of the new one. The memo of the run that gave Victory Road 1F up (with the old,
        # impossible plan of that floor) kept its closed counter, so the corrected plan was never run.
        # The key is a string, so it survives the save/load round trip of the memo unchanged.
        key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
        if self.memo.get("seafoam_plan_key") != key:
            self.memo["seafoam_plan_key"] = key
            self.memo["seafoam_pushes_done"] = 0
            self.memo.pop("seafoam_plan_given_up", None)

        # Cache the (canonical) plan: the runner may need it for the rest of the floor even after
        # the live boulder sprite count has dropped below the open threshold.
        self.memo["seafoam_plan"] = list(plan)

        done = self.memo["seafoam_pushes_done"]
        if self.memo.get("seafoam_plan_given_up"):
            # BUG-0896: the floor's plan was given up (a push that cannot be set up): the guide
            # walks the runner on. The plan is run again when the player comes back (the game puts
            # the boulders of a floor back where they were).
            return None
        # BUG-0896: the rock's real place is the truth about the chain. The counter was the
        # runner's own guess, and it lied: a push that did not move the rock was counted all the
        # same, so the chain went on with a rock that stood somewhere else (the run of
        # 20261024-225457: the rock stood at (7, 16) while the chain believed it was on (9, 16),
        # (9, 14), (16, 14)... - the six pushes after the second one pushed air, the switch was
        # never pressed, the floor was given up and the lane ping-ponged between the floor and
        # Route 23 until the stall detector wrote no_progress). The rock says which push is next.
        #
        # BUG-0891: the rock may only pull the chain BACK: a rock that is out of sight is not gone,
        # so the chain never jumps to a later push of the plan because another rock happens to be
        # in sight (the chain of Victory Road 1F jumped from its second push to the corridor
        # boulder and the floor was given up again).
        live = set(strength.live_boulders(self.read))
        state = strength.chain_step(plan, live, upto=min(done, len(plan) - 1))
        if state is not None:
            done, rock_xy, target_xy, direction, steps = state
        elif done >= len(plan):
            # All pushes in the plan were already done on a previous tick: nothing more to execute.
            return None
        else:
            # the rock is not in sight: the chain is on the step the counter says
            boulder, direction, steps = plan[done]
            rock_xy = (int(boulder[0]), int(boulder[1]))
            dx, dy = overworld.STEP[direction]
            target_xy = (rock_xy[0] + dx * steps, rock_xy[1] + dy * steps)
        dx, dy = overworld.STEP[direction]
        boulder_xy = rock_xy        # the rock's real square: the chain is read from it

        # Walk to the boulder. The boulder sprite blocks its own square, so A* parks the player on
        # an adjacent square; the `step` below then faces the boulder correctly.
        #
        # BUG-0874: the player has to walk to the square the push starts from, not to the boulder: A*
        # parks him on an arbitrary side of the boulder (it blocks its own square), and when that is
        # not the side the push needs, the runner walks to the boulder again and again - the "no
        # path" spin of the run of 20261023-132854 on map 108 (612 no-path ticks in a local replay).
        stand = (boulder_xy[0] - dx, boulder_xy[1] - dy)
        if self.pos() != stand:
            walked = self.walk(stand)
            if walked != "no path":
                # BUG-0879: `walk` does not answer "no path" for a square that cannot be reached: it
                # talks the blocker away (the boulder) and, once the talks are used up, steps greedily
                # towards it (`overworld.toward` ignores the walls). The give-up below therefore never
                # ran on Victory Road 1F: the runner asked for (2, 9) on every tick, ping-ponged
                # between (2, 11) and (2, 12) - the grass of the floor, a wild battle every step -
                # and the stall detector wrote "no_progress" (the run of 20261023-194719, 42 wild
                # battles and no square beyond the two it could reach). The reachability is asked of
                # the grid itself, not of the walk.
                if overworld.astar(self.grid(), self.pos(), stand) is not None:
                    return walked
            # BUG-0877: the square the push starts from cannot be walked to: on Victory Road 1F the
            # boulder at (2, 10) seals the one-wide corridor to the stairs at (1, 1) and the player is
            # on the wrong side of it, so the north side (2, 9) is out of reach (nor can the boulder
            # be pushed from there: pushed the other way it only goes as far as (2, 9), which seals
            # the corridor just as well). Asking for the square again was a "no path" on every tick
            # and the run stood still for 300 ticks (the same_spot stall of run 20261023-173029).
            # The push is given up for this floor and the guide walks the runner on.
            #
            # BUG-0896: but the rock may seal the PLAYER in: on Victory Road 1F the rock of the
            # pressure switch stood at (9, 14), the doorway to the pocket with the stairs, and the
            # player was east of it - the plan's push (east) needs the player west of the rock,
            # which it could not reach (its part of the floor was 24 squares, the floor 159). The
            # rock is then pushed out of the way, when that opens the plan's push: the player steps
            # into the square the rock leaves and stands where the plan needs it.
            aside = self.push_rock_aside(boulder_xy, direction)
            if aside:
                return aside
            # BUG-0948: the rock that seals the player in is not always the rock of the plan's
            # push. On Victory Road 1F the plan starts with the rock west of the entrance
            # (5, 15) and ends with the rock in the corridor to the stairs (2, 10). A player who
            # comes down the stair from Victory Road 2F stands in the pocket with the stairs:
            # the plan's first push cannot be set up there (its stand (5, 14) is across the
            # corridor rock) and the corridor rock is the one that seals him in. The floor's plan
            # was given up, the player could not leave the pocket by any other way, and the lane
            # ping-ponged between the two floors until the detector wrote same_spot (the run of
            # 20261026-125130). The rock that seals the player in is pushed aside, whatever rock
            # of the floor it is: the corridor opens and the plan can be run from the side it needs.
            aside = self.push_sealing_rock_aside(direction)
            if aside:
                return aside
            self.event("push_unreachable", map=here, boulder=list(boulder_xy), stand=list(stand),
                       pos=list(self.pos()))
            self.memo["seafoam_pushes_done"] = len(plan)     # the floor's plan is done with
            self.memo["seafoam_plan_given_up"] = True        # BUG-0896: and it stays given up
            self.memo.pop("seafoam_plan", None)
            # BUG-0896: the floor's state changed (the plan is closed, the rocks are where they
            # are now): the hops that a rock stood in the way of are walkable again.
            self.memo.pop("hop_blocked", None)
            return None

        # The push of the plan: the rock moves one square and the player has to step into the square
        # it left before it can push it again, so a square of rock costs several presses.
        #
        # BUG-0895: the runner pressed the plan's `steps` times and believed the rock had moved
        # `steps` squares. It had not. Measured on the stalled save of Victory Road 1F: the rock of
        # the chain stands on (5, 16) and the four presses of the second push of the plan moved it
        # to (6, 16) and not to (9, 16) - the first press moves the rock, the next three are
        # swallowed by the animation of the push (pokered's `AnimateBoulderDust` runs eight steps
        # of `Delay3` and `DoBoulderDustAnimation` discards the button press), during which the
        # player cannot step into the square the rock left. The six pushes after that pushed air
        # (the rock was not on the square the plan named any more), the chain never ended on the
        # pressure switch (17, 13) - the game opens the barrier of the floor only while a rock lies
        # on that switch - and the runner walked the floor for ever (the run of 20261024-152049:
        # 24 boulder pushes, 390 ticks, no new map).
        # The push is checked now: the runner presses until the rock has really moved, and it
        # watches the rock from the first press on (a press that finds the rock in front of the
        # player moves it when the field move of the last push is still in use).
        #
        # BUG-0896: the push ends when the rock has really reached the square the step of the plan
        # wants, and not after a count of presses. The presses the game swallowed (the dust of the
        # push) were counted as squares of rock, so the chain went on with a rock that stood
        # somewhere else: the six pushes after the second one of the run of 20261024-225457 pushed
        # air (the rock stood at (7, 16) and the chain believed it was on (9, 16), (9, 14),
        # (16, 14)...), the switch was never pressed, the floor was given up and the lane
        # ping-ponged between the floor and Route 23 until the stall detector wrote no_progress.
        before = set(strength.live_boulders(self.read))
        rock_pos = boulder_xy
        presses = 0
        strength_ready = False
        gone = False
        moved = False
        while presses < PUSH_PRESSES_MAX * steps and rock_pos != target_xy:
            presses += 1
            self.step(direction)           # the first press of the push also faces the boulder
            live = set(strength.live_boulders(self.read))
            if not strength_ready:
                # BUG-0874: the boulder only moves when Strength is the field move in use: the runner
                # used to press A on the boulder and walk into it, and the game answered "the boulder
                # won't budge" - the push never happened (the Seafoam floors were never drained
                # either: `seafoam_drained_b3f` was never set). Use the field move the way Surf and
                # Cut are used: START, POKéMON, the Strength user, FORCE.
                if not hm.use_strength(self):
                    self.event("no_strength", map=here, boulder=list(boulder_xy))
                    return "no strength"
                strength_ready = True
            if live == before:
                continue                    # the press did not move the rock: press again
            gone = len(live) < len(before)
            before = live
            moved = True
            # where the rock is now: one square further along the push, or nowhere (it fell into a
            # hole or it lies on the switch)
            nxt = (rock_pos[0] + dx, rock_pos[1] + dy)
            if nxt in live:
                rock_pos = nxt
            elif rock_pos not in live:
                rock_pos = None              # the rock is out of sight (a hole, or off the screen)
            if gone or rock_pos is None:
                break                       # the rock fell into a hole or it lies on the switch

        # Post-step current correction (Seafoam B4F). The runner does not integrate currents into
        # the grid; if the player's new square has a current, log it and step in the push direction.
        # Integration into `Runner.grid()` is a separate PR.
        layout = strength.puzzle_for(here)
        if layout is not None and layout.currents:
            pos = self.pos()
            shift = layout.currents.get(pos)
            if shift is not None:
                cdx, cdy = shift
                self.event("current_push", square=list(pos), to=[pos[0] + cdx, pos[1] + cdy])
                corr = {(1, 0): "RIGHT", (-1, 0): "LEFT", (0, 1): "DOWN", (0, -1): "UP"}.get((cdx, cdy))
                if corr:
                    self.step(corr)

        # Where the rock ended: what the game did, not what the plan asked for (BUG-0895: the event
        # that reported the plan's claim is what hid the lost chain of the floor).
        next_xy = (boulder_xy[0] + dx * steps, boulder_xy[1] + dy * steps)
        reached = rock_pos == target_xy
        self.event("boulder_push", map=here, boulder=list(boulder_xy), to=list(rock_pos or next_xy),
                   direction=direction, steps=steps, plan_index=done, reached=reached, moved=moved)

        if not reached and not gone and not moved:
            # BUG-0896: the rock did not move at all: the push is not set up (the game refuses it
            # or the player is not in front of the rock). The chain does not move on - the rock's
            # real place is the truth about the chain, and the next tick reads it again.
            key = self.push_key(boulder_xy, direction)
            tries = int(self.memo.setdefault("push_short", {}).get(key, 0)) + 1
            self.memo["push_short"][key] = tries
            self.event("push_short", map=here, boulder=list(boulder_xy), want=list(target_xy),
                       direction=direction, presses=presses, tries=tries)
            self.memo.pop("hop_blocked", None)
            if tries >= PUSH_SHORT_TRIES:
                # the game will not move that rock that way: the floor's plan is given up and the
                # guide walks the runner on (the plan is run again when the player comes back).
                self.memo.setdefault("push_refused", {})[key] = True
                self.memo["seafoam_pushes_done"] = len(plan)
                self.memo["seafoam_plan_given_up"] = True
                self.memo.pop("seafoam_plan", None)
                self.memo.pop("hop_blocked", None)
                self.event("push_refused", map=here, boulder=list(boulder_xy), direction=direction,
                           tries=tries)
                return None
            return "boulder push"

        self.memo["seafoam_pushes_done"] = done + 1
        # BUG-0896: a rock that moved changes the floor: the hops the rock stood in the way of are
        # walkable again (the marks of the blocked hops of a floor are only dropped when the player
        # leaves it, and a floor whose every way out is marked blocked is a floor the player cannot
        # leave).
        self.memo.pop("hop_blocked", None)
        # Mark the floor drained the moment the last push completes, so the `seafoam` milestone
        # predicate fires on the next `current()` lookup instead of after a follow-up tick.
        if done + 1 >= len(plan):
            if here == strength.SEAFOAM_B3F:
                self.memo["seafoam_drained_b3f"] = True
            elif here == strength.SEAFOAM_B4F:
                self.memo["seafoam_drained_b4f"] = True
            self.memo.pop("seafoam_plan", None)
        return "boulder push"

    def next_ball(self, here: int) -> Optional[tuple]:
        """The nearest item ball of this map not taken yet and on land we can walk to (some lie on islands)."""
        taken = self.memo.setdefault("balls_taken", [])
        px, py = self.pos()
        walk = self.grid(sprites_block=False)
        balls = [p for pic, p in overworld.sprite_list(self.read) if pic == BALL_PICTURE and [here, *p] not in taken
                 and overworld.astar(walk, (px, py), p) is not None]
        return min(balls, key=lambda q: abs(q[0] - px) + abs(q[1] - py)) if balls else None

    def take_ball(self, here: int, ball: tuple) -> str:
        """Walk to the ball and press A on it; once taken it is not a target any more."""
        done = self.talk_at(ball)
        if done == "talk":
            self.memo["balls_taken"].append([here, *ball])
        return done

    def note_items(self) -> None:
        """Log items that newly came into the bag (what the balls held)."""
        now, seen = bag(self.read), self.memo.setdefault("bag_seen", [])
        new = [i for i in now if i not in seen]
        if seen and new:
            self.event("found_items", items=new, map=self.read(ADDR["map"])[0])
        self.memo["bag_seen"] = list(now)

    def needs_surf_learner(self) -> bool:
        """HM03 is in the bag but nobody in the party can learn Surf."""
        n = self.read(ADDR["party_count"])[0]
        return (HM03_SURF in bag(self.read) and not party_knows(self.read, SURF)
                and not any(self.data.can_learn(m, SURF_BIT) for m in self.read(ADDR["party_species"], min(n, 6))))

    def catch_surf_learner(self, here: int, info: Dict) -> Optional[str]:
        """Pre-empt the Safari Zone hunt with a guaranteed Surf-learner gift (TASK-105).

        Tries the lowest-cost source first (Mt. Moon B2F Magikarp on the way to Cerulean, then the
        mid-game Silph Co. 7F Lapras). On each tick the method either walks one step closer to the
        gift map/square, talks to the gift NPC, or confirms the post-gift party has grown by 1 with a
        Surf-learner species in the new slot. When confirmed, sets `memo["surf_learner"]` to the
        species id and returns a status string ("got Magikarp at Mt. Moon" / "got Lapras at Silph
        Co."). On miss (party full, NPC not present, no source reachable from `here`), logs a
        `surf_gift_missed` event and returns None — `hunt_surf_learner` then takes over.

        The dispatch in `story_step` calls this method before `hunt_surf_learner` when `ms.id ==
        "surf"` and `needs_surf_learner()` is True; the Safari Zone hunt stays the fallback for
        runs that already missed the gifts.
        """
        if self.memo.get("surf_learner"):
            return None   # already have a learner in hand; the milestone predicate does the rest

        before_party_count = self.read(ADDR["party_count"])[0]
        if before_party_count >= 6:
            self.memo["surf_gift_missed"] = True
            self.event("surf_gift_missed", reason="party_full", here=here)
            return None

        source = self._pick_surf_gift_source(here)
        if source is None:
            self.memo["surf_gift_missed"] = True
            self.event("surf_gift_missed", reason="no_reachable_source", here=here)
            return None

        label, gift_map, gift_square, _expected = source

        if here != gift_map:
            return self.go_to_map(here, gift_map, info, anywhere=True)

        if self.pos() != gift_square:
            return self.walk(gift_square)

        # On the gift square; the gift NPC is the only person in sight. Talk and check whether the
        # party grew: the dialogue takes a few ticks, so the post-gift state is only visible after
        # the last A press has dismissed the final text box.
        self.event("surf_gift_try", source=label, map=gift_map, square=list(gift_square))
        self.talk_to_nearest()
        after_party_count = self.read(ADDR["party_count"])[0]
        if after_party_count > before_party_count:
            species = self.read(ADDR["party_species"] + (after_party_count - 1), 1)[0]
            if species in SURF_LEARNERS:
                self.memo["surf_learner"] = species
                self.memo["surf_taught"] = False
                self.event("surf_learner", source=label, species=species, map=gift_map)
                name = {MAGIKARP: "Magikarp", LAPRAS: "Lapras"}.get(species, "fish")
                return f"got {name} at {label}"
            # a party member was added but it isn't a Surf learner (a different gift?): keep talking
            self.memo["surf_gift_unknown"] = self.memo.get("surf_gift_unknown", 0) + 1
            if self.memo["surf_gift_unknown"] > 6:   # six tries: the NPC wasn't a gift-giver after all
                self.memo["surf_gift_missed"] = True
                self.event("surf_gift_missed", reason="wrong_species", source=label, species=species)
                return None
            return "surf gift dialogue"

        # No Pokémon added yet: still mid-dialogue. The next call will detect the gift.
        return "surf gift dialogue"

    def _pick_surf_gift_source(self, here: int):
        """The first reachable Surf-learner gift source, in priority order.

        A source is only "reachable" once the runner has visited its map (the world graph is built
        lazily from the player's visits); for the long-play this means Mt. Moon B2F is known by the
        time `surf` fires (the runner passed through Mt. Moon B2F on the way to Cerulean — it's in
        the `area` of the `mt_moon_exit` milestone), but Silph Co. 7F is not (no milestone visits
        Silph Co.). Returns None when no source's map is in `world.maps` or no route from `here`.
        """
        for source in SURF_GIFT_SOURCES:
            label, gift_map, _square, _species = source
            if gift_map not in self.world.maps:
                continue
            if here == gift_map or self.world.route(here, gift_map):
                return source
        return None

    def surf_rod_step(self, here: int, info: Dict) -> Optional[str]:
        """BUG-0673: the fishing guru in Fuchsia gives the Good Rod (his question's cursor starts on OUI: the tick's
        A answers it); with the rod, fish from the nearest shore of this map, or of Fuchsia. A bite is a wild
        battle with a Surf learner, caught by `must_catch`; `pending_hm` teaches HM03 next. None: the guide walks."""
        if not self.needs_surf_learner():
            return None
        if GOOD_ROD not in bag(self.read):
            if here == GOOD_ROD_HOUSE:
                return self.talk_to_nearest()
            return self.to_fuchsia(here, info) if here != FUCHSIA else None
        fished = self.fish()
        if fished:
            return fished
        return self.to_fuchsia(here, info) if here != FUCHSIA else "no shore"

    def to_fuchsia(self, here: int, info: Dict) -> str:
        """On the long play's road to Fuchsia: its next map; elsewhere (a tunnel floor, a house) the world graph's way."""
        road = ROAD_TO_FUCHSIA
        return self.go_to_map(here, road[road.index(here) + 1] if here in road else FUCHSIA, info, anywhere=True)

    def fish(self) -> Optional[str]:
        """Walk to the nearest square next to water, face it and cast the Good Rod. None: no shore on this map."""
        walk, here = self.grid(), self.pos()
        shore = {sq: d for sq, ok in walk.items() if ok for d, (dx, dy) in overworld.STEP.items()
                 if (sq[0] + dx, sq[1] + dy) in walk.water}
        if here not in shore:
            near = sorted(shore, key=lambda q: abs(q[0] - here[0]) + abs(q[1] - here[1]))[:12]
            paths = [(len(p), sq) for sq in near if (p := overworld.astar(walk, here, sq)) is not None]
            return self.walk(min(paths)[1]) if paths else None
        d = shore[here]
        if overworld.FACING.get(self.read(overworld.FACING_ADDR)[0]) != d:
            self.io.press(d, 60)   # a press toward water only turns
            self.io.wait(200)
        used = hm.use_item(self, GOOD_ROD)
        self.event("fished", map=self.read(ADDR["map"])[0], at=list(here), facing=d, used=used,
                   bite=bool(self.read(ADDR["in_battle"])[0]))
        return "fish"

    def hunt_surf_learner(self, here: int, info: Dict) -> str:
        """Back into the Safari Zone (the gate charges the fee again), wandering its grass: safari_tick throws balls
        at the first species that can learn Surf (Kangaskhan, Nidoking...) that shows up."""
        area = SAFARI_ZONE[self.memo.get("hunt_i", 0) % len(SAFARI_ZONE)]   # each area has its own wild Pokémon
        if self.memo.get("hunt_area") != area:
            self.memo["hunt_area"] = area
            self.event("safari_area", map=area, here=here)
        if here == area:
            self.memo["hunt_total"] = self.memo.get("hunt_total", 0) + 1
            if self.memo["hunt_total"] >= SURF_HUNT_GIVE_UP:
                # a Surf learner is rare in the Safari Zone: the story goes on, the HM is taught when one turns up
                self.memo["surf_deferred"] = True
                self.event("surf_deferred", ticks=self.memo["hunt_total"], party=self.read(ADDR["party_count"])[0])
            self.memo["hunt_ticks"] = self.memo.get("hunt_ticks", 0) + 1   # only time spent in the area counts, not the walk there
            if self.memo["hunt_ticks"] >= HUNT_TICKS_PER_AREA:
                self.memo.update(hunt_i=self.memo.get("hunt_i", 0) + 1, hunt_ticks=0)
            return self.wander(here, info, (area,))
        return self.go_to_map(here, area, info, anywhere=True)

    def mansion_step(self, here: int) -> Optional[str]:
        """BUG-0697: the Mansion's basement stairs are in a part of 1F the entrance does not reach: 2F's north-west
        stairs lead to the part of 3F with the holes, and one hole drops into that part of 1F. The holes are no warps,
        so the world graph does not know them. A landing on 2F (not on a stairs square) was the wrong hole: the next.
        On B1F the key is one of the item balls. None: the guide walks on (1F to 2F, 1F to B1F)."""
        k = self.memo.get("mansion_hole", 0)
        if here == MANSION_3F:
            self.memo["mansion_on_3f"] = True
            hole = MANSION_HOLES[k % len(MANSION_HOLES)]
            if overworld.astar(self.grid(sprites_block=False), self.pos(), hole) is None:
                return self.mansion_switch(MANSION_3F_SWITCH_SPOT)   # the gates around the holes are shut
            return self.walk(hole)
        fell = self.memo.pop("mansion_on_3f", False) and \
            tuple(self.pos()) not in [tuple(w[:2]) for w in self.world.maps.get(here, {}).get("warps", [])]
        if fell:
            self.event("mansion_hole", hole=list(MANSION_HOLES[k % len(MANSION_HOLES)]), landed=here, pos=list(self.pos()))
        if here == MANSION_2F:
            if fell:
                self.memo["mansion_hole"] = k + 1
            return self.walk(MANSION_2F_NW_STAIRS)
        if here == MANSION_B1F:
            took = self.ball_step(here)
            if took:
                if took != "toss item":
                    self.memo["mansion_presses"] = 0
                return took
            taken = self.memo["balls_taken"]
            left = [p for pic, p in overworld.sprite_list(self.read) if pic == BALL_PICTURE and [here, *p] not in taken]
            return self.mansion_switch_toward(here, left)
        return None

    def ball_step(self, here: int) -> Optional[str]:
        """One step of taking this map's item balls, room made in a full bag first. None: no ball left in reach."""
        self.note_items()
        # BUG-0699: with 20 kinds of items in the bag the key's ball answers "no room" and stays on the floor: a slot is
        # made first, and a ball still on the floor is not taken (its A press was marked all the same)
        room = self.make_room()
        if room:
            return room
        # BUG-0703: only a ball in the visible window tells taken from not: off screen a taken ball reads as still there,
        # and dropping its mark sent the runner to it and back at the screen's edge (18, 20) <-> (18, 21)
        seen = [(tuple(p), hidden) for pic, p, hidden in overworld.screen_sprites(self.read) if pic == BALL_PICTURE]
        taken = [b for b in self.memo.setdefault("balls_taken", [])
                 if b[0] != here or (tuple(b[1:]), False) not in seen]
        self.memo["balls_taken"] = taken + [[here, *p] for p, hidden in seen if hidden and [here, *p] not in taken]
        ball = self.next_ball(here)
        return self.take_ball(here, ball) if ball else None

    def make_room(self) -> Optional[str]:
        """A full bag: toss one kind of item (a gift or a ball is refused without room). None: room enough, or the toss
        failed for this bag already. BUG-0711: the mark names what would be tossed, so a new tossable kind is tried."""
        items = list(bag(self.read))
        mark = items + [hm.tossable(items)]
        if len(items) < BAG_SLOTS or self.memo.get("toss_failed") == mark:
            return None
        item = hm.toss_item(self)
        self.memo["toss_failed"] = None if item else mark
        self.event("tossed" if item else "toss_failed", item=item)
        return "toss item"

    def silph_step(self, here: int, info: Dict) -> Optional[str]:
        """BUG-0711: 11F's stairs end in a part with no way to Giovanni. The Card Key (a ball on 5F) first; then 11F's
        part the 7F teleporter lands in (7F's own teleporter part is 3F's, behind a Card Key gate on 3F); there the gate
        to Giovanni's room is opened. None: the guide's goal action (talk to the president) or the guide."""
        if CARD_KEY not in bag(self.read):
            if here != SILPH_5F:
                return self.go_to_map(here, SILPH_5F, info, explore=SILPH_CO, anywhere=True)
            return self.ball_step(here)
        if here == SILPH_CO_11F and overworld.astar(self.grid(sprites_block=False), self.pos(), self.sprite_position(PRESIDENT_PICTURE)
                                                    or (7, 5)) is not None:
            return None
        part = (info.get("parts") or {}).get("player")
        goal = self.world.part_with_warp_to(SILPH_CO_11F, SILPH_7F)
        if here == SILPH_CO_11F and part == goal:
            return self.card_key_door(here)
        if self.world.route(here, SILPH_CO_11F, start_part=part, goal_part=goal):
            return self.go_to_map(here, SILPH_CO_11F, info, goal_part=goal)
        if here != SILPH_3F:
            return self.go_to_map(here, SILPH_3F, info, explore=SILPH_CO, anywhere=True)
        return self.card_key_door(here)

    def card_key_door(self, here: int) -> Optional[str]:
        """BUG-0711: walk next to the nearest shut Card Key gate in reach, face it and press A (the gate opens, its blocks
        turn to floor and the map's parts are learned anew). None: no gate left to try here (the tried ones are tried again)."""
        walk = self.grid(sprites_block=False)
        pos = tuple(self.pos())
        tiles = CARD_KEY_DOORS + ((CARD_KEY_DOOR_11F,) if here == SILPH_CO_11F else ())
        tried = self.memo.setdefault("card_key_tried", [])
        best = None
        for sq, t in getattr(walk, "tiles", {}).items():
            if t not in tiles or walk.get(sq) or [here, *sq] in tried:
                continue
            for d, (dx, dy) in overworld.STEP.items():
                stand = (sq[0] - dx, sq[1] - dy)
                path = [] if stand == pos else overworld.astar(walk, pos, stand) if walk.get(stand) else None
                if path is not None and (best is None or len(path) < len(best[0])):
                    best = (path, stand, d, sq)
        if best is None:
            self.memo["card_key_tried"] = [t for t in tried if t[0] != here]
            return None
        _, stand, d, sq = best
        if stand != pos:
            return self.walk(stand)
        self.io.press(d, 60)
        self.io.wait(200)
        self.io.press("A", 90)
        self.io.wait(400)
        tried.append([here, *sq])
        self.event("card_key_door", map=here, door=list(sq))
        return "card key door"

    def mansion_way_out(self, here: int) -> Optional[str]:
        """Key in the bag, the way out of the Mansion. Every switch flips the gates of all floors: the presses on B1F can
        leave the hole's part of 1F shut off from the doors, and that part has no switch. Then the gates are flipped
        once more on B1F (its south switch is in reach of the stairs) and the way out is tried again."""
        if here == MANSION_1F:
            doors = [tuple(w[:2]) for w in self.world.maps.get(here, {}).get("warps", []) if w[2] == CINNABAR_ISLAND]
            walk, pos = self.grid(sprites_block=False), self.pos()
            open_doors = [d for d in doors if overworld.astar(walk, pos, d) is not None]
            if tuple(pos) in doors:
                self.step("DOWN")   # the doors are mats on the bottom row: a step down leaves
                return "exit mat"
            if open_doors:   # walked straight to: the world graph's parts of the Mansion do not follow the gates
                return self.walk(min(open_doors, key=lambda d: abs(d[0] - pos[0]) + abs(d[1] - pos[1])))
            if not doors or overworld.astar(walk, self.pos(), MANSION_1F_B1F_STAIRS) is None:
                return None
            self.memo["mansion_flip"] = True
            return self.walk(MANSION_1F_B1F_STAIRS)
        if self.memo.get("mansion_flip"):
            walk = self.grid(sprites_block=False)
            spots = [p for p in MANSION_B1F_SWITCH_SPOTS if overworld.astar(walk, self.pos(), p) is not None]
            if not spots:
                self.memo.pop("mansion_flip")
                return None
            done = self.mansion_switch(spots[0])
            if done == "switch":
                self.memo.pop("mansion_flip")
            return done
        if overworld.astar(self.grid(sprites_block=False), self.pos(), MANSION_B1F_STAIRS) is not None:
            self.memo["mansion_presses"] = 0
            return self.walk(MANSION_B1F_STAIRS)
        return self.mansion_switch_toward(here, [MANSION_B1F_STAIRS])   # a gate shuts the way to the stairs

    def mansion_switch_toward(self, here: int, goals: List[tuple]) -> Optional[str]:
        """B1F's goals (the balls left, the stairs) behind gates: every switch flips all of the floor's gates, so the
        switch in reach nearest a goal is pressed (the north one opens the key's west room, the south one the way back
        to the stairs). None when a goal is in reach, or after three presses that opened none."""
        walk, pos = self.grid(sprites_block=False), self.pos()
        if not goals or any(overworld.astar(walk, pos, g) is not None for g in goals):
            self.memo["mansion_presses"] = 0
            return None
        spots = [s for s in MANSION_B1F_SWITCH_SPOTS if overworld.astar(walk, pos, s) is not None]
        if not spots or self.memo.get("mansion_presses", 0) >= 3:
            return None
        return self.mansion_switch(min(spots, key=lambda s: min(abs(s[0] - g[0]) + abs(s[1] - g[1]) for g in goals)))

    def mansion_switch(self, spot: tuple) -> str:
        """A statue below the spot hides a switch; A on it (and A on "L'actionner?") flips the floor's gates."""
        if tuple(self.pos()) != spot:
            return self.walk(spot)
        self.step("UP")   # the statue blocks: the press only turns the player toward it
        texts = self.read_texts("A")
        self.memo["mansion_presses"] = self.memo.get("mansion_presses", 0) + 1
        self.event("mansion_switch", map=self.read(ADDR["map"])[0], text=" | ".join(texts))
        return "switch"

    def cinnabar_quiz(self) -> str:
        """BUG-0705: the nearest quiz machine in reach not answered yet (memo "quiz_done"): A on it, the answer on OUI / NON.
        A wrong answer starts a trainer's battle (the battle ticks fight it, the gate opens after). When every machine in
        reach was answered and Blaine is still shut off (a battle lost), they are all tried again."""
        walk, pos = self.grid(sprites_block=False), tuple(self.pos())
        done = self.memo.setdefault("quiz_done", [])
        spots = [(i, (x, y + 1)) for i, (x, y) in enumerate(CINNABAR_QUIZ)
                 if i not in done and overworld.astar(walk, pos, (x, y + 1)) is not None]
        if not spots:
            # a gate just opened is redrawn a moment later: only a long wait means Blaine stays shut off
            self.memo["quiz_idle"] = self.memo.get("quiz_idle", 0) + 1
            if self.memo["quiz_idle"] >= QUIZ_IDLE_TICKS:
                self.memo.update(quiz_done=[], quiz_idle=0)
            self.io.wait(300)
            return "quiz wait"
        self.memo["quiz_idle"] = 0
        i, spot = min(spots, key=lambda s: abs(s[1][0] - pos[0]) + abs(s[1][1] - pos[1]))
        if pos != spot:
            return self.walk(spot)
        self.step("UP")   # the machine blocks: the press only turns the player toward it
        self.io.press("A", 90)
        texts, answered = [], False
        for _ in range(16):
            self.io.wait(400)
            if hasattr(self.io, "refresh"):
                self.io.refresh()
            if self.read(ADDR["in_battle"])[0]:
                break
            if not text_box_open(self.read):
                if texts:
                    break
                continue
            if not answered and shop.screen(screen_rows(self.read)) == "confirm":
                self.answer_yes_no(CINNABAR_QUIZ_YES[i])
                answered = True
                continue
            box = text_box(self.read)
            if not texts or texts[-1] != box:
                texts.append(box)
            self.io.press("A", 90)
        done.append(i)
        self.event("gym_quiz", machine=i, at=list(CINNABAR_QUIZ[i]), answer="yes" if CINNABAR_QUIZ_YES[i] else "no",
                   answered=answered, text=" | ".join(texts), battle=bool(self.read(ADDR["in_battle"])[0]))
        return "quiz"

    def fetch_lift_key(self) -> str:
        """B4F's north-west room: the Rocket who had the Lift Key is fought first (he drops it); only then is
        the ball next to him there to be picked up. The ball is a sprite hidden (image 0xFF) until his talk
        reveals it, and a hidden on-screen sprite is not in `overworld.sprites`: the ball in sight is picked up,
        otherwise the Rocket is talked to again. (A talk counter used to give up on him after BLOCKER_TALKS_MAX
        and poke the hidden ball forever: the host sat there from 5 Oct, TASK-33 stall.)"""
        sprites = overworld.sprites(self.read)
        if LIFT_KEY_BALL in sprites:
            return self.talk_at(LIFT_KEY_BALL)
        if LIFT_KEY_GUARD in sprites:
            return self.talk_at(LIFT_KEY_GUARD)
        return self.talk_at(LIFT_KEY_BALL)   # neither in sight: walk there

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
            return self.ride_lift(self.lift_floor(ms))
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

    def lift_floor(self, ms) -> str:
        """BUG-0966: the floor the elevator takes. The cabin is a leaf of the world graph (its warps lead
        back to the floor it came from), so the graph cannot say where the elevator goes: the floor to
        take is the one the graph knows a way out of. The way out of the Rocket Hideout is the Game
        Corner's hole (map 135): from the landing part of B1F (the elevator's corridor, part 2) the
        graph knows no way out, but from B2F's (part 15) it does - the ledges and the stairs at (27, 8).
        Riding "1ER" (B1F) would bring the player back to the corridor he came from, for ever."""
        if ms.id == "silph_scope" and not self.memo.get("healing"):
            return "4EME"     # Giovanni's floor: the Silph Scope is there
        for floor, label in ((ROCKET_B1F, "1ER"), (ROCKET_B2F, "2EME"), (ROCKET_B4F, "4EME")):
            part = self.world.part_with_warp_to(floor, ROCKET_LIFT)
            if part is None or not self.world.route(floor, GAME_CORNER, start_part=part):
                continue
            return label
        return "1ER"

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

        # BUG-0948: the player stands ON a door that an earlier walk marked unusable. The mark says
        # that a walk toward the square did not move the player; he is standing on the square now,
        # and the door fires when he steps on it (the stair of Victory Road 1F, (1, 1): the run
        # landed on map 194 at (0, 8)). The mark is dropped and the door is tried again: the mark
        # of the only way down of the floor, kept in the save by an earlier run, left the lane
        # answering "no route" on every tick and the player standing still on the stair for 300
        # ticks (the runs of 20261026-121745 and 20261026-125130).
        standing = tuple(self.pos())
        revived = [tuple(b) for b in self.memo.get("bad_warps", []) if b[0] == here and tuple(b[1:]) == standing]
        if revived:
            self.memo["bad_warps"] = [b for b in self.memo.get("bad_warps", []) if tuple(b) not in revived]
            self.event("warp_revived", map=here, warps=[list(b[1:]) for b in revived])

        # BUG-0635: a door marked unusable, and already retried once (BUG-0634), is dead for the milestone: no route
        # may start with it. World.learn rewrites the warp list from the game on every tick, so the exclusion lives here.
        bad_all = {tuple(b) for b in self.memo.get("bad_warps", [])}
        dead = {tuple(w) for w in self.memo.get("warp_retried", []) if tuple(w) in bad_all}

        # BUG-0639: an edge exit marked bad (it leads into a dead end) is no first hop of a route either
        closed = {(b[1], b[2]) for b in self.memo.get("bad_exits", []) if b[0] == here}

        def first_hop_ok(how):
            if how[0] == "warp" and (here, *how[1]) in dead:
                return False
            return (how[1] in part) if how[0] == "warp" else bool((edges[how[1]] - closed) & part)
        start_part = (info.get("parts") or {}).get("player")
        route, exploring = self.find_route(here, dest, first_hop_ok, start_part, goal_part, explore, anywhere)
        branch = "explore" if exploring else "route"   # BUG-0655: the label of the target in the walk_target event
        if not route:
            route, branch = self.unvisited_door(here, first_hop_ok, start_part), "explore"
        if not route:
            # BUG-0966: the player stands ON a door (he came through it) and the graph knows no way out
            # of his part. The only door next to him is its twin, and moving between the two halves of
            # a door never triggers a warp: the runner walked from one half to the other for 300 s (the
            # run of 20261027-033452, the elevator corridor of the Rocket Hideout's B1F, (24, 19) and
            # (25, 19)) and the lane was dead. The door under his feet is the one to fire, and the game
            # fires it when he presses into the wall next to it (the Rocket elevator's door is drawn in
            # a wall: the press is refused and the warp happens instead).
            fired = self.fire_door(here, info, walk)
            if fired:
                return fired
            # BUG-0965: the runner is sealed in a part of the map whose only way out is the door next
            # to it. A door square is not part of the walkable fill (stepping on it warps the player),
            # so the part of the player and the part of the door can differ and the world graph knows
            # no way out: the runner answered "no route" on every tick - 607 of them on the house of
            # Route 5 (map 70), where the player stood on the one square next to the door (the run of
            # 20261026-223502) until the stall detector wrote the run down. The door is one step away:
            # step on it and the player is out.
            door = self.door_beside(here, info, walk)
            if door is not None:
                self.note_walk_target(here, door, None, "door")
                return self.walk(door)
        if not route:
            back = self.retreat(here, info, part) if self.no_route_ticks >= NO_ROUTE_TICKS else None
            if back:
                return back
            guard = self.guard_in_reach(here, part, walk)
            if guard:
                if abs(guard[0] - self.pos()[0]) + abs(guard[1] - self.pos()[1]) > 1:
                    self.note_walk_target(here, guard, None, "guard")   # BUG-0655: the walk toward him is the guard branch
                return self.talk_at(guard)   # a locked room opens when its guard is beaten (the Rocket elevator's)
            if self.memo.get("lost") != [here, dest]:
                self.memo["lost"] = [here, dest]
                self.event("lost", map=here, next=dest, known=sorted(self.world.maps))
            return "no route"
        e = self.memo.get("entry")
        if e and e["map"] == here and route[0][0] == e["from"] and dest != e["from"] and tuple(e["landing"]) in part:
            # BUG-0639: the way on from the part entered by an edge is back over that edge: a dead end (the landing
            # part is unknown to the graph, so the route read it as open). Its exits are marked, and the way back is taken
            # BUG-0640: unless a door of this part leads to a map never visited (Route 5's pocket: the gate house to the north)
            door = self.unvisited_door(here, first_hop_ok, start_part)
            if door:
                route, branch = door, "explore"
            else:
                back = self.retreat(here, info, part)
                if back:
                    return back
        how = route[0][1]
        if how[0] == "warp":
            # several warps can lead to the same map (a 2-square door); some are drawn as wall and
            # never trigger: use the nearest one not marked unusable
            bad = {tuple(b) for b in self.memo.get("bad_warps", []) if b[0] == here}
            px, py = self.pos()
            # the twins of the chosen warp: same destination warp, reachable from where the player stands
            # (a cave floor has several ladders to the next floor, in different parts)
            chosen = next((w for w in info["warps"] if (w[0], w[1]) == how[1]), None)
            usable = [w for w in info["warps"] if w[2] == route[0][0] and (here, w[0], w[1]) not in bad and (w[0], w[1]) in part]
            if not usable and (here, *how[1]) in bad:
                # BUG-0634: the only door to that map is marked unusable (an earlier stall at Celadon's mart
                # door (39, 19)). Nothing else to try, so the mark is dropped and the door is tried again, once
                # (BUG-0635): six more failed steps mark it again and it is dead (see `dead` above).
                self.memo["bad_warps"] = [b for b in self.memo.get("bad_warps", []) if tuple(b) != (here, *how[1])]
                self.memo.setdefault("warp_retried", []).append([here, *how[1]])
                self.event("warp_retry", map=here, warp=list(how[1]))
                bad = {tuple(b) for b in self.memo.get("bad_warps", []) if b[0] == here}
                usable = [w for w in info["warps"] if w[2] == route[0][0] and (here, w[0], w[1]) not in bad and (w[0], w[1]) in part]
            # BUG-0938: a warp square the game draws as a wall is a door that never opens: the map's warp
            # table lists it, the tiles do not. The south gate of Viridian Forest lists two warps north
            # ((4,0) to the forest's warp 3 and (5,0) to its warp 4), but only (5,0) is a door (tile 3B);
            # (4,0) is the wall tile 4A. Aiming at the wall walks the player into it for ever: the game
            # refuses the step and the fallback of the walk (BUG-0740) steps him back down, so the run
            # ping-ponged between (4,1) and (4,2) until the stall detector fired (20261026-075140).
            # The squares the game shows as walls are skipped; when every candidate is one, the old choice
            # is kept (the screen may be stale, and a door that is off screen is not known to be a wall).
            open_warps = [w for w in usable if walk.get((w[0], w[1]), True)]
            if open_warps:
                usable = open_warps
            # a twin leading to the same destination warp first; when it is all marked, any other door to that map
            # (Route 7's gate house has two door squares, each with its own destination warp)
            twins = [w for w in usable if chosen is None or w[3] == chosen[3]] or usable
            cands = sorted(((w[0], w[1]) for w in twins), key=lambda w: abs(w[0] - px) + abs(w[1] - py))
            if cands:
                how = ("warp", cands[0])
                if self.stuck == 3:
                    # diagnostic: a door that stops the runner three ticks in is logged before it is marked unusable
                    self.event("warp_stuck", map=here, warp=list(cands[0]), pos=list(self.pos()),
                               in_part=cands[0] in part)
                if self.stuck >= 6:
                    # BUG-0925: a rock that seals the way to the door is not the door's fault: the door was
                    # never stepped on (the part of the map ignores the sprites, the walk does not), so it is
                    # no unusable door - the hop is unwalkable (BUG-0891) and is marked as such, and the guide
                    # walks the runner back to the map it came from, where the game puts the rocks of the floor
                    # back where they were. A door marked unusable is dead for the milestone (BUG-0635), and
                    # the only way down of Victory Road 1F never worked again because of it: the stair (1, 1)
                    # was marked bad and retried while the rock of the corridor sealed it, then every tick
                    # answered "no route" and the run stood still for 300 ticks (20261026-020740).
                    # BUG-0947: the player STANDS on the door: the six ticks that did not move are the
                    # walk's failure to step onto the square, not the door's failure to fire. The rock
                    # test is vacuous there (the layout path from the square to itself is empty), so the
                    # door was marked unusable, died for the milestone (BUG-0635) and every tick answered
                    # "no route": the player stood still on the stair of Victory Road 1F (1, 1) until the
                    # detector wrote same_spot (the run of 20261026-121745, after the lane ping-ponged
                    # between Victory Road 1F and 2F). The stair fires when the player steps onto it (the
                    # same run landed on map 194 at (0, 8)), so the door is not marked: the hop is marked
                    # blocked instead, and the guide walks the runner back to the waypoint it came from
                    # (BUG-0891), where the game puts the boulders of the floor back where they were and
                    # the floor's plan can be run from the side it needs.
                    # BUG-0948: the door of a hop that has no other door is never marked unusable by a
                    # walk that did not move. The mark kills the only way down of the floor for the
                    # milestone (BUG-0635): the route cannot start with it, every tick answers "no route"
                    # and the player stands still (the run of 20261026-125130, the same shape as the run
                    # before it). The hop is marked blocked instead and the door's mark is dropped: the
                    # door is not proven broken, the walk could not step onto it.
                    if self.pos() == tuple(cands[0]) or self.boulder_on_the_way(self.pos(), tuple(cands[0])) is not None:
                        self.memo["bad_warps"] = [b for b in self.memo.get("bad_warps", []) if tuple(b) != (here, *cands[0])]
                        if [here, dest] not in (self.memo.get("hop_blocked") or []):
                            self.mark_hop_blocked(here, dest)
                            self.event("hop_blocked", map=here, next=dest, target=list(cands[0]))
                        self.stuck = 0
                    else:
                        self.memo.setdefault("bad_warps", []).append([here, *cands[0]])
                        # BUG-0635: a door that failed again after its one retry is dead for the milestone
                        retried = [here, *cands[0]] in self.memo.get("warp_retried", [])
                        self.event("warp_dropped" if retried else "warp_unusable", map=here, warp=list(cands[0]))
                        self.stuck = 0
        target = hop_target(info, how, self.pos())
        if how[0] == "warp" and self.pos() == target:
            return self.step_off_warp(here, info, target)
        self.note_walk_target(here, target, how[0] == "edge" and how[1], branch)
        walked = self.walk(target, edge=how[0] == "edge" and how[1])
        if getattr(self, "_hop_unwalkable", False):
            # BUG-0891: the hop of the route cannot be walked to: the route is no route, and the
            # guide goes back to the waypoint it came from (Victory Road 1F: the stairs at (1, 1)
            # are behind the boulder that seals the one-wide corridor to them - the runner walked at
            # them for 33 minutes and 42 wild battles without a new square, the run of
            # 20261024-105855). Leaving the floor puts the boulders of the floor back where they
            # were, so the floor can be solved.
            self.mark_hop_blocked(here, dest)
            self.event("hop_blocked", map=here, next=dest, target=list(target))
        return walked

    def find_route(self, here: int, dest: int, first_hop_ok, start_part, goal_part, explore, anywhere: bool):
        """The route to `dest` and whether it is an exploring one; failing that toward the nearest unvisited map of
        `explore` (the cave's floors), and once that has failed for NO_ROUTE_TICKS ticks (the first ticks after a
        crossing can read a stale map header) toward any unvisited map next to this one when `anywhere`. Counts the
        ticks without a route."""
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
        return route, exploring

    def door_beside(self, here: int, info: Dict, walk=None) -> Optional[Tuple[int, int]]:
        """BUG-0965: the door (a warp square of this map) next to the player, when the world graph knows
        no way out of the player's part. The door square is not part of the walkable fill (stepping on
        it warps the player), so the square the player stands on and the door can be in two parts and
        the graph sees no way out. The door is one step away, so the runner can step on it and be out.
        None when there is no door next to the player, or when the game refused it before (a door
        marked unusable)."""
        px, py = self.pos()
        bad = {tuple(b)[1:3] for b in self.memo.get("bad_warps", []) if b[0] == here}
        near = [(w[0], w[1]) for w in (info.get("warps") or [])
                if abs(w[0] - px) + abs(w[1] - py) == 1 and (w[0], w[1]) not in bad]
        if not near:
            return None
        grid = walk if walk is not None else self.grid()
        return next(((x, y) for x, y in near if grid.get((x, y))), None)

    def fire_door(self, here: int, info: Dict, walk=None) -> Optional[str]:
        """BUG-0966: fire the door the player stands on. The world graph knows no way out of his part and
        the only door next to him is the twin of the one under his feet; moving between the two halves
        of a door never triggers a warp, so the runner walked from one half to the other for 300 s (the
        run of 20261027-033452: the elevator corridor of the Rocket Hideout's B1F, (24, 19) and
        (25, 19)). The door under his feet is the one to fire, and the game fires it when he presses
        into the wall next to it: the Rocket elevator's door is drawn in a wall, so the press is refused
        and the warp happens instead (measured on the stalled save: pressing DOWN on (24, 19) takes the
        player to the elevator's cabin, map 203). None when he does not stand on a door, or when no side
        of it is a wall (an exit mat on the border of the map)."""
        x, y = self.pos()
        warps = info.get("warps") or []
        if not any((w[0], w[1]) == (x, y) for w in warps):
            return None
        twins = {(w[0], w[1]) for w in warps}
        grid = walk if walk is not None else self.grid(sprites_block=False)
        sides = [d for _, d in sorted([(y, "UP"), (info["height"] - 1 - y, "DOWN"),
                                       (x, "LEFT"), (info["width"] - 1 - x, "RIGHT")])]
        walls = [d for d in sides
                 if (x + overworld.STEP[d][0], y + overworld.STEP[d][1]) not in twins
                 and not grid.get((x + overworld.STEP[d][0], y + overworld.STEP[d][1]), True)]
        if not walls:
            return None
        key = f"{here}:{x}:{y}"
        tries = self.memo.setdefault("door_presses", {}).get(key, 0)
        side = walls[tries % len(walls)]
        self.memo["door_presses"][key] = tries + 1
        if tries >= 2 * len(walls) and [here, x, y] not in self.memo.setdefault("bad_warps", []):
            # the door never fired: it is unusable, and an unusable door is dead for the milestone
            self.memo["bad_warps"].append([here, x, y])
            self.event("warp_unusable", map=here, warp=[x, y])
        self.event("door_press", map=here, at=[x, y], side=side)
        self.step(side)      # the press into the wall fires the warp (the game refuses the step)
        return "door press"

    def way_on_in_area(self, here: int, area, part) -> bool:
        """BUG-0963: the milestone's area holds the way on when the next waypoint cannot be reached.
        Cerulean City cannot walk south to Route 5: its south exit is in another part of the city (the
        trashed house's two doors are the only way between the parts, and stepping on them warps the
        player into the house), so the world graph knows no route to Route 5. The guide then walked the
        runner back to the waypoint it came from (Route 24) and the two swapped it for ever (the run of
        20261026-204910). The area's unvisited maps (the trashed house, the path under Route 5, the
        underground path) are the way on: the runner explores them instead."""
        return bool(area) and bool(self.world.explore(here, area, None, start_part=part))

    def unvisited_door(self, here: int, first_hop_ok, start_part) -> Optional[List]:
        """BUG-0640: the one-hop route through a door or edge of the player's part into a map never visited, or None.
        A part entered by an edge whose only known way on is back is a dead end only once its unvisited doors were tried."""
        near = self.world.explore(here, ANY_MAP, first_hop_ok, start_part=start_part)
        if not near or len(near) != 1:
            return None
        if self.memo.get("door_exploring") != near[0][0]:   # its own key: the area explorer's would flip every tick
            self.memo["door_exploring"] = near[0][0]
            self.event("explore", map=here, toward=near[0][0])
        return near

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
        if not fresh:
            # nothing new to mark: going back would call this again through go_to_map, without end (recursion)
            return None
        bad.extend(fresh)
        self.event("dead_end", map=here, came_from=e["from"], exits_dropped=len(fresh))
        return self.go_to_map(here, e["from"], info)

    def guard_in_reach(self, here: int, part, layout=None) -> Optional[tuple]:
        """The nearest person standing in the player's part of the map who has had fewer than BLOCKER_TALKS_MAX
        talks yet: with no way out, talking to him is the one thing left to try. The square chosen is kept
        (memo "guard_target") until he is gone from the part or capped: a sprite is hidden once it is on screen
        within 5 squares, so re-choosing each tick flipped between two guards (BUG-0651). Adjacent counts too: his
        sprite is hidden there, and releasing him made the runner swap to the other guard before any talk (BUG-0656).
        BUG-0741: the people the memo marks as walls (the beaten trainers) are skipped: their sprite is still in
        the game but they are gone, and talking to one does nothing at all. The runner pressed A on the beaten
        leader of the Viridian gym three times and stood still for 300 ticks (the same_spot stall of run
        20261020-223419)."""
        walls = {(w[0], w[1]) for w in self.memo.get("walls", {}).get(str(here), [])}
        # BUG-0881: a boulder is not a person: the fallback that talks to "the nearest person in the
        # part" took the picture-63 boulders too, and the runner walked to the boulder next to it and
        # pressed A on a rock three times, then stood still for 300 ticks (the same_spot stall of the
        # run 20261023-231857 on Victory Road 1F).
        boulders = set(strength.live_boulders(self.read))
        kept = self.memo.get("guard_target")
        if kept and kept[0] == here:
            q = (kept[1], kept[2])
            if q in part and q not in walls and q not in boulders and self.guard_reachable(q, layout) \
                    and self.guard_talk_left(here, q):
                return q
        near = sorted((abs(q[0] - self.pos()[0]) + abs(q[1] - self.pos()[1]), q)
                      for q in overworld.sprites(self.read)
                      if q in part and q not in walls and q not in boulders and self.guard_reachable(q, layout))
        for _, q in near:
            if self.guard_talk_left(here, q):
                self.memo["guard_target"] = [here, q[0], q[1]]
                return q
        self.memo.pop("guard_target", None)
        return None

    def guard_reachable(self, who, layout=None) -> bool:
        """The person is in reach: no boulder stands between the player and him.

        BUG-0919: the part is the layout's (the people move or fight), so the guard behind the corridor
        boulder of Victory Road 1F - a pocket with no other way in - was chosen as "the nearest person
        in the part", and the runner pushed the boulder against him for ever: the walk to him failed,
        the walk asked the boulder to move, the push was refused, and the two asked each other again
        (walk -> unblock -> talk_at -> walk) until the run died with "maximum recursion depth exceeded".
        A rock on the floor blocks the way like a wall does for the player: a person behind one is not
        in reach, and the runner does the boulder puzzle instead of talking to a man he cannot reach.
        """
        if layout is None:
            return True
        return self.boulder_on_the_way(self.pos(), tuple(who), layout) is None

    def guard_talk_left(self, here: int, q) -> bool:
        """True while the guard on `q` can still be talked to. A talk made from next to him counts in blocker_talks
        (the counter the route path uses too), and the 3rd one walls him. Once his talks reach BLOCKER_TALKS_MAX he is
        released."""
        px, py = self.pos()
        talks = self.memo.setdefault("blocker_talks", {})
        key = f"{here}:{q[0]},{q[1]}"
        if talks.get(key, 0) >= BLOCKER_TALKS_MAX:
            self.wall_on_cap("guard", q, here)
            return False
        if abs(q[0] - px) + abs(q[1] - py) == 1:
            talks[key] = talks.get(key, 0) + 1   # only a real talk counts, not the steps walking up to him
            self.wall_on_cap("guard", q, here)
        return True

    def wall_on_cap(self, kind: str, square, here: int) -> bool:
        """A person talked to BLOCKER_TALKS_MAX times is a wall: his square joins memo "walls" for the map, so A*
        routes around him (a beaten trainer never moves). Shared by the guard path and the route path, which count
        on the same blocker_talks entry. True when the square is capped."""
        count = self.memo.get("blocker_talks", {}).get(f"{here}:{square[0]},{square[1]}", 0)
        if count < BLOCKER_TALKS_MAX:
            return False
        mwalls = self.memo.setdefault("walls", {}).setdefault(str(here), [])
        if [square[0], square[1]] not in mwalls:
            mwalls.append([square[0], square[1]])
            self.event("npc_walled", who=kind, map=here, square=[square[0], square[1]], talks=count)
        return True

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
        # BUG-0696: a door square drawn as wall (Route 7 gate's (18, 9); its twin (18, 10) fires) never fires from
        # any side, and each step off moves the player, so `stuck` never counts it unusable: after every side twice it
        # is marked, and the route takes another door to the same map. A sole door is left to the BUG-0634 retry.
        door = next((w for w in info["warps"] if (w[0], w[1]) == tuple(target) and len(w) > 2), None)
        other = door and any(w[2] == door[2] and (w[0], w[1]) != tuple(target) for w in info["warps"])
        if other and tries >= 2 * len(order) and [here, *target] not in self.memo.setdefault("bad_warps", []):
            self.memo["bad_warps"].append([here, *target])
            self.event("warp_unusable", map=here, warp=list(target))
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
        self._hop_unwalkable = False   # BUG-0891: the hop of the route is walkable until proven otherwise
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
                    if path is None:
                        # BUG-0891: the exits of this edge cannot be walked to: a boulder seals them
                        layout = self.grid(sprites_block=False)
                        self._hop_unwalkable = any(self.boulder_on_the_way((px, py), e, layout) is not None
                                                   for e in exits)
        else:
            path = overworld.astar(walk, (px, py), target)
            if path is None:
                # BUG-0887: a boulder that stands in the way is pushed with Strength, not walked into.
                # The greedy step of the fallback below was refused by the game, the hop-tile fallback
                # (BUG-0740) stepped away again, and the player ping-ponged between (2, 11) and (2, 12)
                # - the grass of Victory Road 1F, a wild battle every step - for 18 minutes (48 wild
                # battles) until the stall detector wrote "no_progress" (the run of 20261024-072503).
                pushed = self.push_blocking_boulder((px, py), target)
                if pushed:
                    return pushed
                action, path = self.unblock((px, py), target)
                if action:
                    return action
                if path is None:
                    # BUG-0891: the target cannot be walked to at all. When a boulder stands on the
                    # way, the hop of the route is not walkable (Victory Road 1F: the stairs at
                    # (1, 1) are behind the boulder that seals the one-wide corridor to them), and
                    # the guide has to know it: the greedy step below only bounces the player
                    # between two squares of the grass for ever.
                    self._hop_unwalkable = self.boulder_on_the_way((px, py), target) is not None
                    path = overworld.toward(walk, (px, py), target)
        if not path:
            self.stuck += 1
            self.walk_stuck_log(walk, target, edge)
            return "no path"
        ahead = (px + overworld.STEP[path[0]][0], py + overworld.STEP[path[0]][1])
        if ahead in getattr(walk, "cuts", ()) and walk.get(ahead):
            return self.cut_tree(path[0], ahead)   # a tree is in the way and Cut is known: cut it
        water = getattr(walk, "water", ())
        if ahead in water and walk.get(ahead) and (px, py) not in water:
            return self.surf_onto(path[0], ahead)   # BUG-0681: land to water, Surf is known: get on the water
        direction = path[0]
        moved = self.step(direction) or self.step(direction)  # the first press may only turn the player
        if not moved:
            # BUG-0740: the game's hop tiles (the gym's chevrons) block the key the runner planned and
            # throw him to their landing square whichever key he presses. On the Viridian gym's chevron
            # (5, 13) the runner had to press DOWN to be carried east to (6, 13): with the planned key
            # alone he stood on the chevron for ever (the same_spot stall of run 20261020-175235).
            for d in ("DOWN", "LEFT", "UP", "RIGHT"):
                if d != direction and self.step(d):
                    moved, direction = True, d
                    break
        self.stuck = 0 if moved else self.stuck + 1
        if moved:
            self._walk_stuck_logged = False
            self.step_dir = direction   # BUG-0718: the game may push the player back off the square he stepped on
        else:
            self.walk_stuck_log(walk, target, edge)
        return "walk"

    def boulder_on_the_way(self, start, target, layout=None) -> Optional[tuple]:
        """The boulder that stands on the layout path from `start` to `target`, None when none does.

        BUG-0891: a boulder is a sprite, so it blocks the grid the walk uses and the path to a
        square behind it is no path. The layout path (the sprites ignored) says whether a rock is
        what stands in the way.
        """
        boulders = set(strength.live_boulders(self.read))
        if not boulders:
            return None
        layout = self.grid(sprites_block=False) if layout is None else layout
        path = overworld.astar(layout, start, target)
        if not path:
            return None
        sq = start
        for d in path:
            nxt = (sq[0] + overworld.STEP[d][0], sq[1] + overworld.STEP[d][1])
            if nxt in boulders:
                return nxt
            sq = nxt
        return None

    def hop_blocked(self, here: int, dest: int) -> bool:
        """Has the hop of the route to `dest` been found unwalkable on this visit?

        BUG-0891: the world graph knows the warps of a map, the game does not let the player walk
        to a warp that a boulder seals. Such a hop is no route at all.
        """
        return [here, dest] in (self.memo.get("hop_blocked") or [])

    def mark_hop_blocked(self, here: int, dest: int) -> None:
        """Remember that the hop of the route to `dest` cannot be walked to (BUG-0891)."""
        blocked = self.memo.setdefault("hop_blocked", [])
        if [here, dest] not in blocked:
            blocked.append([here, dest])

    def note_walk_target(self, here: int, target, edge, branch: str) -> None:
        """BUG-0655 diagnostic, called where go_to_map picks the walk target: one `walk_target` event when the
        target or the branch that chose it changes (memo "last_walk_target" / "last_walk_branch"). Nothing is
        logged while both stay the same. Movement is not touched."""
        now = [here, target[0], target[1], edge or None]
        if self.memo.get("last_walk_target") == now and self.memo.get("last_walk_branch") == branch:
            return
        self.memo["last_walk_target"], self.memo["last_walk_branch"] = now, branch
        self.event("walk_target", map=here, pos=list(self.pos()), target=list(target), branch=branch, edge=edge or None)

    def walk_stuck_log(self, walk, target, edge) -> None:
        """BUG-0646 diagnostic: the walk has failed to move four times in a row. Logged once per stuck
        episode (the flag clears when a step moves), with the part of the map the player can reach."""
        if self.stuck != 4 or getattr(self, "_walk_stuck_logged", False):
            return
        self._walk_stuck_logged = True
        self.event("walk_stuck", map=self.read(ADDR["map"])[0], pos=list(self.pos()), target=list(target),
                   edge=edge, part_size=len(overworld.reachable(walk, self.pos())))

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
        if tuple(blocker) == tuple(target):
            # BUG-0919: he stands on the target square, so talking to him means walking to him - and the
            # walk to him already failed (unblock is only called when it did). Talking here would ask
            # the walk the same question again and it would answer the same way, for ever: the run of
            # 20261025 died with "maximum recursion depth exceeded" (walk -> unblock -> talk_at ->
            # walk -> unblock ...) on Victory Road 1F, where the boulder in the corridor keeps the
            # guard out of reach. There is no way on: the caller re-plans.
            return None, None
        here = self.read(ADDR["map"])[0]
        if self.wakes(blocker):
            return self.wake(blocker), None
        key = f"{here}:{blocker[0]},{blocker[1]}"
        count = self.memo.setdefault("blocker_talks", {}).get(key, 0)
        if count >= BLOCKER_TALKS_MAX:
            # a beaten trainer never moves: already walled by his talks (here or on the guard path), so
            # re-plan now that this square is unwalkable instead of talking again
            walk = self.grid()
            return None, overworld.astar(walk, start, target) or overworld.toward(walk, start, target)
        if abs(blocker[0] - px) + abs(blocker[1] - py) == 1:
            count += 1   # only a real talk counts, not the steps walking up to it
        self.memo["blocker_talks"][key] = count
        if self.memo.get("blocker") != list(blocker):
            self.memo["blocker"] = list(blocker)
            self.event("blocked_by", at=list(blocker), target=list(target))
        self.wall_on_cap("blocker", blocker, here)   # the 3rd talk is the last: from now on A* routes around him
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

    def push_blocking_boulder(self, start, target):
        """A boulder that stands in the way is pushed with Strength: the game decides whether it moves.

        BUG-0887: the runner used to walk into the boulder that seals the one-wide corridor to the
        stairs of Victory Road 1F (2, 10). The greedy step of the walk's fallback was refused by the
        game, the hop-tile fallback (BUG-0740) stepped away again, and the player ping-ponged between
        (2, 11) and (2, 12) - the grass of the floor, a wild battle every step - for 18 minutes
        (48 wild battles, no new square for the last 5) until the stall detector wrote "no_progress"
        (the run of 20261024-072503). A boulder is a rock, not a person: it is never talked to (it
        answers "the boulder won't budge"), it is pushed - with Strength, the way the game wants it.

        The boulder is found on the *layout* path (the path the map allows when the sprites are
        ignored): that path runs through the boulder's square, the sprite path does not. The player
        stands on the square before it and pushes it on; the game decides what happens (the boulder
        may slide, fall into a hole or drop to the floor below), and the runner reads the result.
        """
        if getattr(self, "_pushing", False):
            return None            # the walk of the push itself: no second push in the same tick
        boulders = set(strength.live_boulders(self.read))
        if not boulders:
            return None
        layout = self.grid(sprites_block=False)
        self.avoid_warps(layout, target)
        path = overworld.astar(layout, start, target)
        if not path:
            return None            # no way on at all: not a boulder's fault
        sq = start
        for d in path:
            nxt = (sq[0] + overworld.STEP[d][0], sq[1] + overworld.STEP[d][1])
            if nxt in boulders:
                return self.push_boulder(nxt, sq, d)
            sq = nxt
        return None

    def push_rock_aside(self, boulder, plan_direction) -> Optional[str]:
        """Push the rock out of the way when the plan's push cannot be set up: the player is sealed
        behind it and cannot stand where the push needs it.

        BUG-0896: the rock of the pressure switch of Victory Road 1F stood at (9, 14), the doorway
        to the pocket with the stairs, and the player was east of it while the plan's push (east)
        needs the player west of it. The rock is pushed the other way, and the push is only allowed
        when it OPENS the plan's push: the player can then stand where the plan needs it (the square
        before the rock's new place, along the plan's direction). The corridor boulder of the floor
        (2, 10) is never pushed that way: it would seal the corridor even tighter and the game
        refuses the move in any case (BUG-0890).
        """
        px, py = self.pos()
        if getattr(self, "rom", None) is None:
            return None      # no map data: the floor cannot be read, there is no way around the rock
        blocked = self.grid()             # the sprites block: the player cannot stand behind a rock
        pdx, pdy = overworld.STEP[plan_direction]
        for d in ("UP", "DOWN", "LEFT", "RIGHT"):
            dx, dy = overworld.STEP[d]
            stand = (boulder[0] - dx, boulder[1] - dy)
            if not blocked.get(stand):
                continue
            if overworld.astar(blocked, (px, py), stand) is None:
                continue      # the player cannot stand behind the rock that way
            if self.push_refused(boulder, d):
                continue      # the game already refused this push: never try it again
            # the plan's push after this one: the player would stand where the rock leaves it
            nxt = (boulder[0] + dx, boulder[1] + dy)
            if not self.sealed_in_by(boulder, blocked, (px, py)):
                continue      # the rock does not seal the player in: the plan keeps its way
            if (px, py) != stand:
                self._pushing = True
                try:
                    self.walk(stand)
                finally:
                    self._pushing = False
            before = set(strength.live_boulders(self.read))
            self.step(d)
            if not hm.use_strength(self):
                self.event("no_strength", map=self.read(ADDR["map"])[0], boulder=list(boulder))
                return "no strength"
            self.step(d)
            after = set(strength.live_boulders(self.read))
            moved = sorted(after - before)
            self.event("boulder_push", map=self.read(ADDR["map"])[0], boulder=list(boulder),
                       to=[list(p) for p in moved], direction=d, steps=1, moved=bool(moved),
                       aside=True)
            if moved:
                # BUG-0896: a rock that moved changes the floor: the hops the rock stood in the
                # way of are walkable again. The marks of a blocked hop are only dropped when the
                # player leaves the map, and a floor whose every way out is marked blocked is a
                # floor the player cannot leave (the run of 20261024-225457: the marks of the
                # stalled save kept the runner on the floor for ever).
                self.memo.pop("hop_blocked", None)
                return "boulder push"
            # the game refused this push: remember it, so the runner never tries it again
            self.memo.setdefault("push_refused", {})[self.push_key(boulder, d)] = True
        return None

    def push_sealing_rock_aside(self, plan_direction) -> Optional[str]:
        """Push the rock that seals the player in, whichever rock of the floor it is.

        BUG-0948: the rock of the plan's push is not always the rock that seals the player in.
        Victory Road 1F: the plan starts with the rock west of the entrance (5, 15) and ends with
        the rock in the corridor to the stairs (2, 10). A player who comes down the stair from
        Victory Road 2F stands in the pocket with the stairs: the plan's first push cannot be set
        up there (its stand (5, 14) is across the corridor rock), the floor's plan is given up
        and the corridor rock is the one that seals him in. The pocket then has no other way out
        and the lane ping-ponged between the two floors until the detector wrote same_spot (the
        run of 20261026-125130). The rock that seals the player in is pushed aside (the way the
        plan wants the corridor rock pushed, from the pocket side): the corridor opens and the
        plan can be run from the side it needs.
        """
        if getattr(self, "rom", None) is None:
            return None      # no map data: the floor cannot be read, there is no way around the rock
        blocked = self.grid()
        px, py = self.pos()
        for rock in sorted(strength.live_boulders(self.read)):
            sq = (int(rock[0]), int(rock[1]))
            if not self.sealed_in_by(sq, blocked, (px, py)):
                continue      # this rock does not seal the player in
            for d in ("UP", "DOWN", "LEFT", "RIGHT"):
                dx, dy = overworld.STEP[d]
                stand = (sq[0] - dx, sq[1] - dy)
                if not blocked.get(stand):
                    continue
                if overworld.astar(blocked, (px, py), stand) is None:
                    continue      # the player cannot stand behind the rock that way
                if self.push_refused(sq, d):
                    continue      # the game already refused this push: never try it again
                if (px, py) != stand:
                    # the player has to stand behind the rock before it can be pushed: the walk
                    # moves him one square per tick, so the push is a later tick's work
                    self._pushing = True
                    try:
                        self.walk(stand)
                    finally:
                        self._pushing = False
                    return "walk"
                before = set(strength.live_boulders(self.read))
                self.step(d)
                if not hm.use_strength(self):
                    self.event("no_strength", map=self.read(ADDR["map"])[0], boulder=list(sq))
                    return "no strength"
                self.step(d)
                after = set(strength.live_boulders(self.read))
                moved = sorted(after - before)
                self.event("boulder_push", map=self.read(ADDR["map"])[0], boulder=list(sq),
                           to=[list(p) for p in moved], direction=d, steps=1, moved=bool(moved),
                           aside=True)
                if moved:
                    self.memo.pop("hop_blocked", None)
                    return "boulder push"
                # the game refused this push: remember it, so the runner never tries it again
                self.memo.setdefault("push_refused", {})[self.push_key(sq, d)] = True
                return None
        return None

    def sealed_in_by(self, boulder, blocked, pos) -> bool:
        """True when the rock at `boulder` seals the player in: the rock is the only link between the
        player's part of the floor and a bigger part of it.

        BUG-0896: the rock of the pressure switch of Victory Road 1F stood at (9, 14), the doorway
        to the pocket with the stairs: the player was east of it in a part of 24 squares, the floor
        159 the other side, and it could not leave the pocket at all. The corridor boulder of the
        floor (2, 10) does not seal the player in (it closes the pocket with the stairs, which is
        the big floor's side), so the plan keeps its way there (BUG-0890).
        """
        mine = self.part_of(blocked, pos)
        for d in ("UP", "DOWN", "LEFT", "RIGHT"):
            dx, dy = overworld.STEP[d]
            nxt = (boulder[0] + dx, boulder[1] + dy)
            if not blocked.get(nxt) or nxt in mine:
                continue
            if len(self.part_of(blocked, nxt)) > len(mine):
                return True
        return False

    @staticmethod
    def part_of(walk, start) -> set:
        """The squares connected to `start` - the player's part of the map, without the fringe
        `overworld.reachable` adds (the squares next to it, walkable or not)."""
        jumps, walls = getattr(walk, "jumps", {}), getattr(walk, "walls", set())
        seen, stack = {start}, [start]
        while stack:
            x, y = stack.pop()
            for nxt in [(x + dx, y + dy) for dx, dy in overworld.STEP.values()] + \
                       [land for _, land in jumps.get((x, y), [])]:
                if nxt in walk and nxt not in seen and walk[nxt] and ((x, y), nxt) not in walls:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    def plan_push_direction(self, boulder) -> Optional[str]:
        """The direction the floor's plan pushes this boulder in, or None when the plan does not name it.

        BUG-0890: the generic "push the boulder out of the way" shoved the corridor boulder of
        Victory Road 1F NORTH, against the plan that wants it pushed SOUTH out of the corridor to the
        stairs. The rock ended up in the alcove (2, 9), where the game refuses to move it at all, and
        the floor could never be finished (the run of 20261024-093928). The plan has to win: a boulder
        the plan names is only ever pushed the way the plan says. A boulder the plan does not name
        (the rocks of (7, 17) and (14, 2)) stays free.
        """
        here = self.read(ADDR["map"])[0]
        layout = strength.puzzle_for(here)
        if layout is None:
            return None
        sq = (int(boulder[0]), int(boulder[1]))
        for b, direction, _steps in layout.plan:
            if (int(b[0]), int(b[1])) == sq:
                return direction
        # BUG-0896: a rock that stands BETWEEN two squares of the plan (a push that was cut short)
        # is pushed the way the plan says too: the generic push used to shove it the other way and
        # the chain lost the rock (the run of 20261024-225457: the rock stood at (7, 16) between
        # (5, 16) and (9, 16) and the generic push sent it west).
        for b, direction, steps in layout.plan:
            dx, dy = overworld.STEP[direction]
            start = (int(b[0]), int(b[1]))
            for k in range(1, steps):
                if (start[0] + dx * k, start[1] + dy * k) == sq:
                    return direction
        return None

    def push_key(self, boulder, direction) -> str:
        """The memo key of one refused push: the floor, the square of the rock and the direction."""
        here = self.read(ADDR["map"])[0]
        return f"{here}:{int(boulder[0])},{int(boulder[1])}:{direction}"

    def push_refused(self, boulder, direction) -> bool:
        """Has the game already refused this push? A refused push is never tried again: the runner
        used to spend whole runs shoving a rock that does not move (the run of 20261024-102539: 40
        pushes of the boulder at (2, 9) in 13 minutes, and no new square)."""
        return bool(self.memo.get("push_refused", {}).get(self.push_key(boulder, direction)))

    def push_boulder(self, boulder, path_stand, path_dir):
        """Push the boulder that blocks the way: the player stands behind it and presses the
        direction with Strength in use. The game decides whether it moves (it may slide, fall into
        a hole or drop to the floor below): a push the game refuses is tried from the next side.
        """
        px, py = self.pos()
        blocked = self.grid()             # the sprites block: the player cannot stand behind a boulder
        allowed = self.plan_push_direction(boulder)      # BUG-0890: the plan has to win
        cands = []
        for d in ("UP", "DOWN", "LEFT", "RIGHT"):
            dx, dy = overworld.STEP[d]
            stand = (boulder[0] - dx, boulder[1] - dy)
            # BUG-0890: `astar` lets a *blocked goal* be entered (its docstring says so), so a wall
            # passed as a place to stand: (2, 8), the wall north of the corridor boulder of Victory
            # Road 1F, was a candidate for ever and the push was tried from a square the player can
            # never reach. A square that is not walkable is not one.
            if not blocked.get(stand):
                continue
            if overworld.astar(blocked, (px, py), stand) is None:
                continue      # the player cannot stand behind the boulder that way
            if allowed is not None and d != allowed:
                continue      # BUG-0890: the plan pushes this boulder another way: the plan wins
            if self.push_refused(boulder, d):
                continue      # BUG-0890: the game already refused this push: never try it again
            cands.append((d, stand))
        # the push the path asks for (the boulder is pushed on) comes first, then the sides that
        # would move it off the path: that one opens the way when the game allows it
        cands.sort(key=lambda c: 0 if c[0] == path_dir else 1)
        for d, stand in cands:
            if (px, py) != stand:
                # the push starts from the square the player stands on: it is the square before the
                # boulder on the path, so the boulder is not in the way of reaching it
                self._pushing = True
                try:
                    return self.walk(stand)
                finally:
                    self._pushing = False
            before = set(strength.live_boulders(self.read))
            self.step(d)      # a blocked press only turns the player towards the boulder
            if not hm.use_strength(self):
                self.event("no_strength", map=self.read(ADDR["map"])[0], boulder=list(boulder))
                return "no strength"
            self.step(d)      # the push: the boulder slides one square, the player follows
            after = set(strength.live_boulders(self.read))
            moved = sorted(after - before)
            self.event("boulder_push", map=self.read(ADDR["map"])[0], boulder=list(boulder),
                       to=[list(p) for p in moved], direction=d, steps=1, moved=bool(moved))
            if moved:
                return "boulder push"
            # the game refused this push: remember it, so the runner never tries it again (the run
            # of 20261024-102539: the same refused push, 40 times, for 13 minutes and no new square)
            self.memo.setdefault("push_refused", {})[self.push_key(boulder, d)] = True
            # the game refused this push: try the next side of the boulder
        return None

    def avoid_warps(self, walk, target) -> None:
        """Warp squares are walls for the path unless they are the target: stairs in a narrow corridor
        (the Rocket Hideout) would otherwise be walked over, undoing the trip.
        BUG-0881: the target is a warp square itself now and then - the square a Strength push starts
        from on Victory Road 1F is the exit mat (9, 17), which can only be reached over its twin
        (8, 17). An exit mat (a warp square on the border of the map) fires when the player steps off
        the map, not when he steps on it, so the border warp squares may be crossed when the runner
        walks to a warp square of the same map."""
        here = self.read(ADDR["map"])[0]
        info = links(self.read)
        warps = info["warps"]
        target_is_warp = any((w[0], w[1]) == tuple(target) for w in warps)
        for w in warps:
            if (here, w[0], w[1]) in INERT_WARPS:
                continue
            if (w[0], w[1]) == tuple(target) or (w[0], w[1]) == self.pos():
                continue
            if target_is_warp and (w[0] in (0, info["width"] - 1) or w[1] in (0, info["height"] - 1)):
                continue   # an exit mat: it fires when the player steps off the map, not onto it
            if (w[0], w[1]) in walk:
                walk[(w[0], w[1])] = False

    def teach_hm(self, name: str, item: int, move: int) -> str:
        """An HM is in the bag and nobody knows its move: teach it to the Pokémon losing least by it (hm.py)."""
        tries = self.memo["hm_tries"]
        tries[name] = tries.get(name, 0) + 1
        index = hm.teach_hm(self, name, item, move)
        if index is None:
            self.event("hm_failed", move=name, tries=tries[name])
        else:
            mon = self.party()[index]
            self.event("hm_taught", move=name, pokemon=mon["name"], level=mon["level"], moves=mon["moves"])
        return "teach " + name

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

    def surf_onto(self, direction: str, square) -> str:
        """BUG-0681: face the water square and use Surf on it (hm.py); getting off is a plain step onto land. A square
        Surf fails on twice becomes a wall, like a tree Cut fails on."""
        self.step(direction)   # a blocked press only turns the player toward the water
        hm.use_surf(self)
        here = self.read(ADDR["map"])[0]
        if self.pos() == tuple(square) or self.pos() in getattr(self.grid(), "water", ()):
            self.event("surf", map=here, at=list(square), pokemon=self.party()[hm.surf_user(self.read)]["name"])
            return "surf"
        key = f"{here}:{square[0]},{square[1]}"
        fails = self.memo.setdefault("surf_fails", {})
        fails[key] = fails.get(key, 0) + 1
        if fails[key] >= 2:
            self.memo.setdefault("walls", {}).setdefault(str(here), []).append([square[0], square[1]])
            self.event("surf_failed", map=here, at=list(square))
        return "surf failed"

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
        if ms.id == "surf":
            return self.talk_to_nearest()   # the Secret House's only person hands over HM03
        if ms.id == "strength":
            return self.talk_to_nearest()   # the Warden (the only person in his house) takes the Gold Teeth and gives HM04
        if ms.id == "lift_key":
            return self.fetch_lift_key()
        if ms.id == "silph_co":
            # BUG-0710: the president, once Giovanni is beaten, hands over the Master Ball. BUG-0711: by his picture, the
            # nearest person from the teleporter's part is a Rocket who has nothing more to say once beaten
            return self.make_room() or self.talk_to(PRESIDENT_PICTURE)   # BUG-0711: his Master Ball needs a free slot
        if ms.id == "poke_flute":
            return self.talk_to_topmost()
        if ms.id == "ss_anne_cut":
            return self.talk_to_nearest()   # the seasick captain: his back is rubbed by talking, then he gives HM01
        if ms.id.endswith("_badge"):
            # the gym leader stands at the back of the gym: the topmost sprite (of those with a picture of their own:
            # Koga's jugglers share one and some stand higher up)
            people = overworld.sprite_list(self.read)
            leader = self.leader_candidate(people)   # BUG-0957: the candidate does not change under the runner's feet
            if leader is None and people and self.not_leaders:
                # BUG-0719: every candidate of the gym was judged "not the leader" and there is
                # nobody left: the blacklist is a memory of this visit, it must never empty the gym,
                # or the runner stands still on the spot for ever (the "same_spot" stall of run
                # 20261020-134355: 533 "at goal" ticks with Giovanni wrongly in the blacklist).
                # Forget it and start again.
                forgotten = len(self.not_leaders)
                self.memo["not_leaders"] = []
                self.memo.pop("leader_talked", None)
                self.answer_texts = []
                self.event("leaders_forgotten", milestone=ms.id, forgotten=forgotten)
                return "forget the blacklist"
            if leader:
                if self.read(ADDR["map"])[0] == VERMILION_GYM and \
                        overworld.astar(self.grid(sprites_block=False), self.pos(), leader[1]) is None:
                    return self.trash_cans()   # Lt. Surge is behind the electric barrier
                if self.read(ADDR["map"])[0] == CINNABAR_GYM and \
                        overworld.astar(self.grid(sprites_block=False), self.pos(), leader[1]) is None:
                    return self.cinnabar_quiz()   # Blaine is behind the quiz gates
                if self.read(ADDR["map"])[0] == SAFFRON_GYM:
                    pad = pad_route(self.grid(sprites_block=False), links(self.read), self.pos(), leader[1])
                    if pad:
                        return self.walk(pad)   # BUG-0712: Sabrina's room is reached only by teleporter pads
                seen = self.memo.setdefault("leaders_seen", [])
                if ms.id not in seen:
                    seen.append(ms.id)
                    self.event("gym_leader", milestone=ms.id, picture=leader[0], at=list(leader[1]))
                if self.memo.get("leader_talked") == list(leader[1]) and self.answer_texts \
                        and not self.answer_is_a_trainer():
                    # BUG-0718: he answered with a plain dialogue and not with a battle: he is not the leader
                    # (the Viridian gym's kid: "I don't know who the champion of Viridian is"). Remember him
                    # and let the next candidate have a go. A candidate that answered nothing (a trainer whose
                    # line of sight is elsewhere) is not marked: the game has not said he is no leader.
                    # BUG-0719: the answer must have settled first. A gym leader's speech is followed by his
                    # battle line ("GIOVANNI veut se battre!") and the battle starts right after it: judged
                    # while the speech was still being typed (the page cut in the middle of a word), the
                    # leader was blacklisted and the gym never gave its badge. Wait for the game to be
                    # quiet: if a battle starts in the meantime, it proves he is a trainer.
                    # BUG-0723: while the game is talking, the runner must not MOVE: a step cancels the
                    # leader's script and his speech starts again (the Viridian leader never fought in 200 s
                    # of replay). His fight comes from his own script, ~13 s after the talk (run
                    # 20261020-134355: the trainer battle, level 38, 13.7 s after his text was read).
                    if not self.answer_settled():
                        self.io.wait(200)
                        return "answer pending"
                    # the game has been quiet and no fight came: step into the leader's line of sight before
                    # judging him (BUG-0719). The step cancels nothing now (the game is quiet) and in Gen 1 a
                    # trainer's fight starts when the player enters the square he looks at.
                    if self.memo.get("leader_challenged", 0) < GYM_CHALLENGE_TRIES:
                        self.memo["leader_challenged"] = self.memo.get("leader_challenged", 0) + 1
                        self.challenge(leader[1])
                        self.io.wait(200)
                        return "challenged"
                    said = list(self.answer_texts)
                    self.memo.setdefault("not_leaders", []).append(list(leader[1]))
                    self.memo.pop("leader_talked", None)
                    self.memo.pop("leader_challenged", None)
                    self.answer_texts = []
                    self.event("not_the_leader", milestone=ms.id, picture=leader[0], at=list(leader[1]), said=said)
                    self.io.wait(200)
                    return "not the leader"
                talked = self.talk_at(leader[1])   # by position: the picture alone finds the nearest juggler
                if talked == "talk":
                    self.memo["leader_talked"] = list(leader[1])
                    self.answer_texts = []   # the game's answer to this talk is what tells a trainer from a passer-by
                    self.answer_since = time.time()   # BUG-0719: the answer is settled a quiet while after this talk
                    self.memo.pop("leader_challenged", None)   # BUG-0723: a new talk, a new set of tries
                elif talked == "no path":
                    # BUG-0957: the candidate cannot be walked to (he is in another room): the next person
                    # of the gym is tried instead of walking the same unreachable square for ever.
                    self.memo.pop("leader_candidate", None)
                return talked
        self.io.wait(300)
        return "at goal"

    def is_person(self, who, people, alone: bool = True) -> bool:
        """True when `who` can be the gym leader: a person (not a Poké Ball lying on the floor, BUG-0718),
        not one the runner has already found not to be a trainer, and with a picture of his own (`alone`)."""
        pic, pos = who[0], tuple(who[1])
        if pic == BALL_PICTURE or pos in self.not_leaders:
            return False
        return not alone or [q[0] for q in people].count(pic) == 1

    def answer_is_a_trainer(self) -> bool:
        """True when the game's answer to the last talk was a trainer's battle line ("GIOVANNI veut se battre!",
        BUG-0718): a passer-by answers with a plain dialogue and is not the gym leader."""
        return any(GYM_TRAINER_WORD in t for t in self.answer_texts)

    def answer_settled(self) -> bool:
        """True when the game's answer to the last talk has settled (BUG-0719): the text box has been closed
        for a quiet while and the battle (the leader's battle line and the fight it starts) had the time to
        come. Judged earlier, a gym leader whose speech was still being typed was taken for a passer-by."""
        now = time.time()
        return now - self.answer_at >= GYM_ANSWER_QUIET_S or now - self.answer_since >= GYM_ANSWER_MAX_S

    def challenge(self, who) -> str:
        """Step onto the square a gym leader looks at (BUG-0719): in Gen 1 a trainer starts the fight when
        the player enters the line he faces, and the leader of a gym stands at the top of his room. A leader
        answered with a plain line when the runner talked to him ("Tu ne pourras accéder à la LIGUE
        POKéMON..."), so talking alone never starts his battle: the runner walks towards the square in front
        of him (below first, then the sides) and lets the game decide.
        BUG-0723: the runner usually stands on that square already (it walked there to talk) and the game only
        checks the sight when the player MOVES: step aside, so that coming back on it starts the fight."""
        x, y = who
        here = self.pos()
        sight = (x, y + 1)          # the leader stands at the top of his room and looks down
        walk = self.grid()
        if here != sight and walk.get(sight):
            return self.walk(sight)
        if here == sight:
            for d in ("LEFT", "RIGHT", "DOWN", "UP"):
                dx, dy = overworld.STEP[d]
                if walk.get((here[0] + dx, here[1] + dy)) and self.step(d):
                    return "step aside"
            return "challenge"
        for target in ((x - 1, y), (x + 1, y), (x, y - 1)):
            if target == here or not walk.get(target):
                continue
            return self.walk(target)
        return "challenge"

    def forget_not_leader(self) -> None:
        """The person the runner talked to last started a battle: the game has proven he is a trainer, so he
        is not "not the leader" any more (BUG-0719). Without this a wrong verdict about the gym leader was
        final: the leader stayed in the blacklist and the gym could never give its badge."""
        talked = self.memo.get("talked_to")
        if not talked:
            return
        not_leaders = self.memo.get("not_leaders") or []
        if any(list(s) == list(talked) for s in not_leaders):
            self.memo["not_leaders"] = [s for s in not_leaders if list(s) != list(talked)]
            self.event("leader_is_a_trainer", at=list(talked))

    @property
    def not_leaders(self) -> set:
        """The people the runner has already talked to without a battle (BUG-0718: the Viridian gym's kid)."""
        return {tuple(s) for s in self.memo.get("not_leaders", [])}

    def leader_candidate(self, people) -> Optional[tuple]:
        """The person of the gym the runner is going to talk to (None when the gym has nobody to talk to).

        BUG-0957: the candidate was picked again on every tick, and who is on screen depends on where the
        player stands: in the Cerulean gym (65) the trainer at (8, 7) was on screen while the player stood
        at (5, 11), the runner walked one square down to reach him, the trainer went off screen, the leader
        at the top of the room (4, 2) became the candidate again, and the runner walked back up: it
        ping-ponged between two squares for ever (the `no_progress` stall of the run 20261026-163011: 220
        walks and no other action in 100 s of play).
        The candidate is remembered now (in the memo, so a run that ends on the way keeps it). It only
        changes when the person is gone (beaten) or judged not to be the leader, or when the runner is in
        another gym.
        """
        here = self.read(ADDR["map"])[0]
        remembered = self.memo.get("leader_candidate")
        if remembered:
            spot = list(remembered[1:]) if remembered[0] == here else None
            if spot:
                for pic, pos in people:
                    if list(pos) == spot and self.is_person((pic, pos), people):
                        return (pic, tuple(pos))
            self.memo.pop("leader_candidate", None)   # another gym, or he is gone (beaten): look for a new one
        leader = self.gym_leader(people)      # BUG-0716: the person standing in the player's room
        if leader is None and people:
            alone = [p for p in people if self.is_person(p, people)] or \
                    [p for p in people if self.is_person(p, people, alone=False)]
            leader = min(alone, key=lambda p: p[1][1]) if alone else None
        if leader:
            self.memo["leader_candidate"] = [here, leader[1][0], leader[1][1]]
        return leader

    def gym_leader(self, people) -> Optional[tuple]:
        """The gym leader among the people: the one standing in the player's room (on screen, not hidden) whose
        picture no other person shares. BUG-0716: the trainers of the other rooms are hidden, and one of them
        can have a picture of his own in the room's list: the runner then chased a trainer it could never reach
        and walked on two squares for 5 min. None when nobody qualifies: the caller keeps the old rule.
        BUG-0718: a Poké Ball lying on the gym's floor (picture 61) is not a person: the runner took it for the
        leader, walked to it and the game's ledge bounced it back for ever."""
        here = self.read(ADDR["map"])[0]
        walls = {tuple(s) for s in self.memo.get("walls", {}).get(str(here), [])}
        seen = [pic for pic, _ in people]
        on_screen = {(pic, tuple(pos)) for pic, pos, hidden in overworld.screen_sprites(self.read) if not hidden}
        out = [(pic, pos) for pic, pos in people if (pic, tuple(pos)) in on_screen
               and tuple(pos) not in walls and self.is_person((pic, pos), people) and seen.count(pic) == 1]
        return min(out, key=lambda p: p[1][1]) if out else None

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
        where = self.wander(here, info)
        if where == "no grind area":
            # BUG-0878: the training cannot even start here: no way from this map to a grass area.
            # The run of 20261023-175436 stood on Victory Road 1F for 300 ticks and every tick answered
            # "no grind area" without pressing a key: the target was never dropped, so the runner spun
            # on the training instead of playing the story. A training that cannot begin is hopeless
            # like a stalled one: drop the target and go on (the levels come from the route).
            self.memo.update(grinding=False, stalled_target=want, grind_s=0.0)
            self.event("train_stalled", level=top, target=want, seconds=0, reason="no grind area")
            self.rethink(f"training stalled: no way from map {here} to a grass area to train in, "
                         f"the level {top} (target {want}) has to come from the route")
            return "training stalled"
        return where

    def wander(self, here: int, info: Dict, maps=GRIND_MAPS) -> str:
        """Walk around the grass of the nearest of `maps`: wild battles come by themselves."""
        if here not in maps:
            places = [m for m in maps if self.world.route(here, m)]
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

    def reachable_places(self, here: int, places) -> List[int]:
        """The places of `places` the route can start from, where the player stands.

        BUG-0888: the world graph knows a way to a Pokémon Center from *another* part of the map the
        player is on, but not from the part he stands in: on Route 23 the way to Pallet Town's Center
        starts at the map's south edge, which lies in a part of its own (the gate house leads back to
        Route 23), while the player was in the north part, at (4, 32). The trip could never start, and
        the tick answered "no route" for ever: the player stood on the same square for 300 ticks (the
        same_spot stall of run 20261024-085053, the last event "lost map 34 next 41" - 41 is Pallet
        Town's Center). A trip is only planned to a place the route can start from.
        """
        part = ((self.world.maps.get(here) or {}).get("parts") or {}).get("player")
        return [m for m in places if m == here or self.world.route(here, m, start_part=part)]

    def heal(self, here: int, cur: int, tot: int) -> str:
        """Heal at the nearest known place: a Pokémon Center (the nurse behind the counter) or home
        (mom)."""
        if not self.memo.get("healing"):
            self.memo["healing"] = True
            self.event("heal_start", hp=cur, max_hp=tot)
        if cur == tot and self.attack_pp() >= HEAL_PP_BELOW:
            self.memo["healing"] = False
            self.memo.pop("heal_waiting", None)
            self.event("healed", hp=cur)
            self._attach_heal_outcomes({"result": "healed"})
            return "healed"
        places = self.reachable_places(here, (PLAYERS_HOUSE_1F,) + POKEMON_CENTERS)
        if not places:
            # BUG-0877: no healing place is reachable (the runner is on Victory Road 1F, and the world
            # graph knows no way from there to a Center). The trip must not become a dead end: the
            # runner used to answer "no route to heal" on every tick and never played again (the
            # same_spot stall of run 20261023-173029: 605 ticks on map 108, not one step). The trip
            # waits here: the flag stays set (the trip is not restarted, and not logged again, on
            # every tick) and the caller goes on playing the story.
            # BUG-0888: the same waiting applies when a Center is known but the route to it cannot be
            # started from the player's own part of the map (Route 23, see `reachable_places`).
            return "no route to heal"
        part = ((self.world.maps.get(here) or {}).get("parts") or {}).get("player")
        dest = min(places, key=lambda m: 0 if m == here else len(self.world.route(here, m, start_part=part)))
        if here != dest:
            trip = self.go_to_map(here, dest, self.world.maps[here])
            if trip == "no route":
                # BUG-0888: the route the graph knows cannot be started from here after all (the
                # first hop is not in the player's part): the trip waits (BUG-0877) instead of the
                # tick ending on "no route" for ever, which left the player standing still.
                return "no route to heal"
            return trip
        if here == PLAYERS_HOUSE_1F:
            return self.talk_to(MOM_PICTURE)
        return self.talk_to_nurse()

    def prepare(self, ms, here: int) -> Optional[str]:
        """Once per milestone with `prepare`: a Pokémon Center visit (the nurse restores HP and PP), even
        when HP looks fine. None when done or when no Center is known."""
        places = self.reachable_places(here, POKEMON_CENTERS)
        if not places or self.memo.pop("nurse_talked", False):
            self.memo["prepared"].append(ms.id)   # the dialog that followed the last talk is over
            self.event("prepared", milestone=ms.id, hp=self.party_hp(), attack_pp=self.attack_pp())
            return None
        part = ((self.world.maps.get(here) or {}).get("parts") or {}).get("player")
        dest = min(places, key=lambda m: 0 if m == here else len(self.world.route(here, m, start_part=part)))
        if here != dest:
            trip = self.go_to_map(here, dest, self.world.maps[here])
            if trip == "no route":
                # BUG-0888: the trip cannot start from here: it waits instead of freezing the tick.
                self.memo["prepared"].append(ms.id)
                return None
            return trip
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
            self.memo["talked_to"] = list(who)   # BUG-0719: a battle afterwards proves he is a trainer
            return "talk"
        # BUG-0919: we are already walking to him (talk_at -> walk -> unblock -> talk_at -> walk ...):
        # walking to him again would ask the same walk the same question and it would answer the same
        # way, for ever. The run of 20261025 died with "maximum recursion depth exceeded" on Victory
        # Road 1F, where the boulder in the corridor keeps the guard out of reach.
        if getattr(self, "_walking_to", None) == tuple(who):
            return "no path"
        self._walking_to = tuple(who)
        try:
            return self.walk(who)
        finally:
            self._walking_to = None

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
        # BUG-0711: on the walk's own terms (warps are walls): Silph 5F's south strip is shut by a beaten Rocket and a
        # teleporter pad; a path over the pad named no blocker, and the walk went back and forth by the pad
        self.avoid_warps(open_map, target)
        path = overworld.astar(open_map, start, target)
        if not path:
            return None
        # BUG-0881: a boulder is not a person either: talking to it does nothing at all (the runner
        # pressed A on the rock next to it three times on Victory Road 1F and stood still for 300
        # ticks, the same_spot stall of the run 20261023-231857).
        people = set(overworld.sprites(self.read)) - set(strength.live_boulders(self.read))
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

    def game_is_frozen(self) -> bool:
        """True when the emulator is not running: the game's work RAM does not change from one tick to the
        next (BUG-0875). The game writes its OAM shadow every frame, so a snapshot that never moves is a
        game whose keys go nowhere. The second lane's new game of 2026-10-23 stood at the title menu
        (map 0, pos (0, 0), no Pokémon, no money) for the whole run: the runner pressed A and START into
        a frozen game and the detector called it "no progress"."""
        getter = getattr(self.io, "snapshot", None)
        if getter is None:
            return False                      # an IO without a snapshot (the unit tests): nothing to compare
        try:
            snap = list(getter())
        except Exception:                      # noqa: BLE001 - a page that does not answer is frozen
            self.frozen_ticks += 1
            return self.frozen_ticks >= FROZEN_TICKS
        if self.last_snapshot is not None and snap == self.last_snapshot:
            self.frozen_ticks += 1
        else:
            self.frozen_ticks = 0
        self.last_snapshot = snap
        return self.frozen_ticks >= FROZEN_TICKS

    def reboot_emulator(self) -> bool:
        """Restart the emulator in the page: the ROM is loaded again and the save with it, so the run goes
        on from where it was. False when the page does not answer at all: the game is then really gone."""
        reboot = getattr(self.io, "reboot", None)
        if reboot is None:
            return False
        try:
            return bool(reboot())
        except Exception:                      # noqa: BLE001 - a page that does not answer is gone
            return False

    def self_guarded(self) -> bool:
        """True while the runner is in an activity that ends itself when it goes nowhere: training (GRIND_STALL_S
        without experience) or the Safari Surf hunt (SURF_HUNT_GIVE_UP ticks). The stall detector does not count that time."""
        m = self.memo
        if m.get("grinding"):
            return True
        if self.intro_now:
            # BUG-0875: the intro of a new game (the title screen, Oak's speech, the names) is a long phase
            # in which the game moves nowhere: it must not be counted as "no progress" (the second lane's
            # new game was killed by the no-progress clock while it was still being named).
            return True
        return (not m.get("surf_deferred") and m.get("hunt_area") is not None
                and self.read(ADDR["map"])[0] in SAFARI_ZONE and m.get("hunt_total", 0) < SURF_HUNT_GIVE_UP)

    def run(self, seconds: float, stall=None) -> Dict:
        """Play for `seconds`. `stall` (a stall.StallDetector) ends the run early, cleanly, when it sees the run
        go nowhere; the result then has `stalled` = its reason and the log an event `stalled`."""
        t0, counts, stalled = time.time(), {}, None
        while time.time() - t0 < seconds:
            what = self.tick()
            counts[what] = counts.get(what, 0) + 1
            if what == "story done":
                break   # nothing left to play: end the run, it saves as usual
            if what == "emulator gone":
                # BUG-0872: the page died: there is no game left to play on. The run ends here, before the
                # detector sees it: a map and a position the game is not on are not a stall.
                break
            if what in ("no route", "no path", "no route to heal", "no grind area", "nobody", "no nurse", "at goal"):
                self.io.wait(200)  # nothing to do this tick: do not spin
            if stall:
                stalled = stall.observe(what, current(self.read, self.memo).id, self.read(ADDR["map"])[0], self.pos(),
                                        len(self.memo.get("done", [])), guarded=self.self_guarded())
                if stalled:
                    self.event("stalled", reason=stalled, milestone=current(self.read, self.memo).id,
                               map=self.read(ADDR["map"])[0], pos=list(self.pos()))
                    break
        return {"ticks": sum(counts.values()), "counts": counts, "milestone": current(self.read, self.memo).id,
                "map": self.read(ADDR["map"])[0], "pos": self.pos(), "party": self.read(ADDR["party_count"])[0],
                "stalled": stalled, "emulator_gone": bool(counts.get("emulator gone"))}
