"""
Story milestones, checked against the game's own memory: up to the first badge, through Mt. Moon, then
Cerulean City and the second badge, Nugget Bridge, Bill, Vermilion City, HM01 Cut from the S.S. Anne (taught
and used by hm.py), the third badge, Rock Tunnel, Lavender, Celadon and the fourth badge, then the Rocket
Hideout under the Celadon Game Corner (the Lift Key, the elevator, Giovanni's Silph Scope), Pokémon Tower and
Mr. Fuji's Poké Flute, and the road south past the sleeping Snorlax to Fuchsia City.

Like Jev's harness, the route to each milestone comes from a guide (the maps to pass through); the AI
decides battles, prompts and, through its strategy, everything that is not "where is the story".
Map ids are the game's (identical on the US and French ROMs as far as verified).
"""

from typing import Callable, Dict, List, Optional

from .memory import ADDR, Read

SH = 5
BAG_COUNT, BAG_ITEMS = 0xD31D + SH, 0xD31E + SH       # verified: empty bag at the start
BADGES = 0xD356 + SH                                   # verified: 0 at the start
OAKS_PARCEL = 0x46

PALLET, ROUTE1, VIRIDIAN, OAKS_LAB, VIRIDIAN_MART = 0x00, 0x0C, 0x01, 0x28, 0x2A
PLAYERS_HOUSE_1F, PLAYERS_HOUSE_2F = 0x25, 0x26
ROUTE2, VIRIDIAN_FOREST, PEWTER, PEWTER_GYM = 0x0D, 0x33, 0x02, 0x36
FOREST_SOUTH_GATE, FOREST_NORTH_GATE = 0x32, 0x2F
ROUTE3, ROUTE4, MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F = 0x0E, 0x0F, 0x3B, 0x3C, 0x3D
CERULEAN, CERULEAN_GYM = 0x03, 0x41
ROUTE24, ROUTE25, BILLS_HOUSE = 0x23, 0x24, 0x58
SS_TICKET = 0x3F
ROUTE5, ROUTE6, VERMILION = 0x10, 0x11, 0x05
TRASHED_HOUSE = 0x3E   # Cerulean: the house the Rocket broke into; its back hole leads out to the south of the city
VERMILION_DOCK, CAPTAINS_ROOM = 0x5E, 0x65
HM01_CUT = 0xC4
SILPH_SCOPE, POKE_FLUTE, LIFT_KEY = 0x48, 0x49, 0x4A   # item ids (verified on the emulator where noted in the milestones)
VERMILION_GYM = 0x5C
SS_ANNE = tuple(range(0x5E, 0x69))   # dock and ship floors
PATH_ROUTE5, PATH_ROUTE6, UNDERGROUND_PATH = 0x47, 0x4A, 0x77   # Route 5's gate to Saffron is guarded: the path under it
PEWTER_MART, CERULEAN_MART = 0x38, 0x43
ROUTE7, ROUTE8, ROUTE9, ROUTE10, LAVENDER, CELADON = 0x12, 0x13, 0x14, 0x15, 0x04, 0x06
ROCK_TUNNEL_1F, ROCK_TUNNEL_B1F = 0x52, 0xE8
CELADON_GYM = 0x86
PATH_ROUTE8, PATH_WEST_EAST, PATH_ROUTE7 = 0x50, 0x79, 0x4D   # the Underground Path from Route 8 to Route 7: both ends and the tunnel
GAME_CORNER = 0x87
ROCKET_B1F, ROCKET_B2F, ROCKET_B3F, ROCKET_B4F, ROCKET_LIFT = 0xC7, 0xC8, 0xC9, 0xCA, 0xCB   # Rocket Hideout floors and its elevator
ROCKET_HIDEOUT = (ROCKET_B1F, ROCKET_B2F, ROCKET_B3F, ROCKET_B4F, ROCKET_LIFT)
LAVENDER_CENTER, TOWER_1F, TOWER_6F, TOWER_7F, FUJI_HOUSE = 0x8D, 0x8E, 0x93, 0x94, 0x95   # Lavender Town: Pokémon Center, Pokémon Tower's ground and top floors, Mr. Fuji's house
POKEMON_TOWER = tuple(range(TOWER_1F, TOWER_7F + 1))
ROUTE12, ROUTE13, ROUTE14, ROUTE15, FUCHSIA = 0x17, 0x18, 0x19, 0x1A, 0x07   # south of Lavender: Routes 12-15 on foot (no Bicycle), then Fuchsia City
FUCHSIA_CENTER, FUCHSIA_GYM = 0x9A, 0x9D   # Fuchsia City's Pokémon Center and gym (door (5, 27))
ROUTE12_GATE = 0x57   # the gate house across Route 12: its two doors are the road
MT_MOON_EXIT_X = 24   # Route 4: Mt. Moon's exit (from B1F) lands at x 24; the entrance side is west of it


def bag(read: Read) -> Dict[int, int]:
    n = read(BAG_COUNT, 1)[0]
    raw = read(BAG_ITEMS, 2 * min(n, 20))
    return {raw[2 * i]: raw[2 * i + 1] for i in range(min(n, 20))}


def badges(read: Read) -> int:
    return bin(read(BADGES, 1)[0]).count("1")


class Milestone:
    """`maps`: the guide (maps to pass through). `goal_via`: the goal is the part of the last map holding
    a warp to this map (Route 4's far side, where Mt. Moon's exit lands); the route there is then found
    on the world graph, exploring the maps of `area` not visited yet (a cave's floors) instead of
    following a guide. `prepare`: a gauntlet of trainers ahead: visit a Pokémon Center first, so the fights
    start with full HP and PP (the PP of one Pokémon runs out over a rival and five trainers)."""

    def __init__(self, mid: str, goal: str, maps: List[int], done: Callable[[Read, Dict], bool], at_goal: str = "",
                 goal_via: Optional[int] = None, area: tuple = (), prepare: bool = False):
        self.id, self.goal, self.maps, self.done, self.at_goal = mid, goal, maps, done, at_goal
        self.goal_via, self.area, self.prepare = goal_via, area, prepare


# memo: facts the runner remembers across milestones ("had_parcel").
MILESTONES = [
    # a new game starts upstairs at home; Oak stops the player at Pallet Town's north exit and takes
    # them to his lab
    Milestone("starter", "Choose a starter Pokémon in Oak's lab",
              [PLAYERS_HOUSE_2F, PLAYERS_HOUSE_1F, PALLET, ROUTE1, OAKS_LAB],
              lambda r, m: r(ADDR["party_count"], 1)[0] >= 1, at_goal="pick a Poké Ball"),
    Milestone("parcel", "Go to the Viridian City shop to fetch Oak's parcel", [OAKS_LAB, PALLET, ROUTE1, VIRIDIAN, VIRIDIAN_MART],
              lambda r, m: OAKS_PARCEL in bag(r) or m.get("had_parcel", False)),
    Milestone("pokedex", "Bring the parcel back to Oak", [VIRIDIAN_MART, VIRIDIAN, ROUTE1, PALLET, OAKS_LAB],
              lambda r, m: m.get("had_parcel", False) and OAKS_PARCEL not in bag(r), at_goal="talk to Oak"),
    Milestone("pewter", "Cross Route 2 and Viridian Forest to Pewter City", [PALLET, ROUTE1, VIRIDIAN, ROUTE2, FOREST_SOUTH_GATE, VIRIDIAN_FOREST,
               FOREST_NORTH_GATE, ROUTE2, PEWTER],
              lambda r, m: r(ADDR["map"], 1)[0] == PEWTER),
    Milestone("boulder_badge", "Beat Brock at the Pewter City gym", [PEWTER, PEWTER_GYM],
              lambda r, m: badges(r) >= 1, at_goal="challenge the gym leader"),
    Milestone("route3", "Leave Pewter City east and cross Route 3 (trainers) to Route 4", [PEWTER_GYM, PEWTER, ROUTE3, ROUTE4],
              lambda r, m: r(ADDR["map"], 1)[0] in (ROUTE4, MT_MOON_1F)),
    Milestone("mt_moon", "Enter Mt. Moon", [ROUTE3, ROUTE4, MT_MOON_1F],
              lambda r, m: r(ADDR["map"], 1)[0] == MT_MOON_1F),
    Milestone("mt_moon_exit", "Find the way through Mt. Moon's floors (ladders) to the far side of Route 4",
              [MT_MOON_1F, ROUTE4],
              lambda r, m: r(ADDR["map"], 1)[0] == ROUTE4 and r(ADDR["x"], 1)[0] >= MT_MOON_EXIT_X
              or r(ADDR["map"], 1)[0] == CERULEAN, goal_via=MT_MOON_B1F,
              area=(MT_MOON_1F, MT_MOON_B1F, MT_MOON_B2F)),
    Milestone("cerulean", "Go down Route 4 east to Cerulean City", [ROUTE4, CERULEAN],
              lambda r, m: r(ADDR["map"], 1)[0] == CERULEAN),
    Milestone("cascade_badge", "Beat Misty at the Cerulean City gym", [CERULEAN, CERULEAN_GYM],
              lambda r, m: badges(r) >= 2, at_goal="challenge the gym leader"),
    # the bridge trainers, the rival and the Rocket are fought on the way: Route 24 is one long walk north
    Milestone("nugget_bridge", "Cross Nugget Bridge (Route 24) north to Route 25", [CERULEAN_GYM, CERULEAN, ROUTE24, ROUTE25],
              lambda r, m: r(ADDR["map"], 1)[0] == ROUTE25, prepare=True),
    # Bill is a Pokémon in the machine first: talking to him (yes, help) runs the cutscene, and talking to
    # him again hands over the ticket
    Milestone("bill", "Help Bill in his house at the end of Route 25 and get the S.S. Ticket",
              [ROUTE24, ROUTE25, BILLS_HOUSE], lambda r, m: SS_TICKET in bag(r), at_goal="talk to Bill"),
    Milestone("vermilion", "Go back through Cerulean and Route 5, under the Underground Path, to Vermilion City",
              [BILLS_HOUSE, ROUTE25, ROUTE24, CERULEAN, ROUTE5, ROUTE6, VERMILION],
              lambda r, m: r(ADDR["map"], 1)[0] == VERMILION, area=(TRASHED_HOUSE, PATH_ROUTE5, UNDERGROUND_PATH, PATH_ROUTE6)),
    Milestone("ss_anne_cut", "Board the S.S. Anne at Vermilion's dock and get HM01 Cut from the captain",
              [VERMILION, VERMILION_DOCK, CAPTAINS_ROOM], lambda r, m: HM01_CUT in bag(r), area=SS_ANNE,
              at_goal="talk to the captain"),
    # the gym is behind a cuttable tree (hm.py teaches Cut from the bag and cuts it on the way)
    Milestone("thunder_badge", "Cut the tree in Vermilion City and beat Lt. Surge at the gym", [VERMILION, VERMILION_GYM],
              lambda r, m: badges(r) >= 3, at_goal="challenge the gym leader", prepare=True),
    # Route 9 starts behind a cuttable tree; Route 10 is split in two by Rock Tunnel (dark, two floors)
    Milestone("rock_tunnel", "Go back to Cerulean, east along Routes 9 and 10 and through Rock Tunnel to Lavender Town",
              [VERMILION_GYM, VERMILION, ROUTE6, ROUTE5, CERULEAN, ROUTE9, ROUTE10, LAVENDER],
              lambda r, m: r(ADDR["map"], 1)[0] == LAVENDER,
              area=(TRASHED_HOUSE, PATH_ROUTE5, UNDERGROUND_PATH, PATH_ROUTE6, ROCK_TUNNEL_1F, ROCK_TUNNEL_B1F)),
    Milestone("celadon", "Go west on Route 8, under the Underground Path to Route 7 and Celadon City",
              [LAVENDER, ROUTE8, ROUTE7, CELADON], lambda r, m: r(ADDR["map"], 1)[0] == CELADON,
              area=(PATH_ROUTE8, PATH_WEST_EAST, PATH_ROUTE7)),
    # the gym's door and its inside are guarded by cuttable trees
    Milestone("rainbow_badge", "Cut through the trees and beat Erika at the Celadon City gym", [CELADON, CELADON_GYM],
              lambda r, m: badges(r) >= 4, at_goal="challenge the gym leader", prepare=True),
    # the poster in the Game Corner hides a switch (runner.game_corner_poster); three floors down, a Rocket
    # on B4F dropped the Lift Key
    Milestone("lift_key", "Find the switch behind the Game Corner's poster and the Lift Key in the Rocket Hideout below",
              [CELADON, GAME_CORNER, ROCKET_B1F, ROCKET_B2F, ROCKET_B3F, ROCKET_B4F],
              lambda r, m: LIFT_KEY in bag(r) or SILPH_SCOPE in bag(r), area=ROCKET_HIDEOUT, prepare=True),
    # the key starts the elevator on B1F; it opens the other half of B4F, where Giovanni waits
    Milestone("silph_scope", "Take the elevator to B4F and beat Giovanni for the Silph Scope",
              [ROCKET_B4F, ROCKET_B3F, ROCKET_B2F, ROCKET_B1F, ROCKET_LIFT, ROCKET_B4F],
              lambda r, m: SILPH_SCOPE in bag(r), area=ROCKET_HIDEOUT, prepare=True),
    # Lavender's tower is full of ghosts the Silph Scope reveals; the rival waits on 2F, the Marowak ghost on 6F
    # and three Rockets on 7F around Mr. Fuji, who takes the player to his house for the Poké Flute
    Milestone("poke_flute", "Climb Pokémon Tower in Lavender Town, free Mr. Fuji and get the Poké Flute from him",
              [CELADON, ROUTE7, ROUTE8, LAVENDER] + list(POKEMON_TOWER) + [FUJI_HOUSE],
              lambda r, m: POKE_FLUTE in bag(r), area=(GAME_CORNER, PATH_ROUTE7, PATH_WEST_EAST, PATH_ROUTE8) + ROCKET_HIDEOUT + POKEMON_TOWER, prepare=True),
    # Snorlax sleeps in the middle of Route 12: the flute wakes it, and it is beaten (or caught) to pass
    Milestone("fuchsia", "Wake the Snorlax on Route 12 with the Poké Flute and walk Routes 12 to 15 to Fuchsia City",
              [LAVENDER, ROUTE12, ROUTE13, ROUTE14, ROUTE15, FUCHSIA], lambda r, m: r(ADDR["map"], 1)[0] == FUCHSIA,
              area=(ROUTE12_GATE,), prepare=True),
    # the gym is a maze of invisible walls: they are real collision squares, so the grid knows them
    Milestone("soul_badge", "Beat Koga at the Fuchsia City gym", [FUCHSIA, FUCHSIA_GYM],
              lambda r, m: badges(r) >= 5, at_goal="challenge the gym leader", prepare=True),
]


def current(read: Read, memo: Dict) -> Milestone:
    """The first milestone not done yet. Done is sticky (memo["done"]): "reach Pewter City" stays done
    once reached, even inside the gym."""
    if OAKS_PARCEL in bag(read):
        memo["had_parcel"] = True
    done = memo.setdefault("done", [])
    for ms in MILESTONES:
        if ms.id in done:
            continue
        if ms.done(read, memo):
            done.append(ms.id)
            continue
        return ms
    return MILESTONES[-1]
