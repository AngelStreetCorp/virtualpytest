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
from .strength import CINNABAR_GYM, CINNABAR_ISLAND, HALL_OF_FAME, INDIGO_PLATEAU, INDIGO_PLATEAU_LOBBY, MANSION_1F, \
    ROUTE_22, ROUTE_23, SEAFOAM_1F, SEAFOAM_B3F, SEAFOAM_B4F, SEAFOAM_ISLANDS, SEAFOAM_B1F, SEAFOAM_B2F, VICTORY_ROAD, \
    VICTORY_ROAD_1F, VICTORY_ROAD_2F, VICTORY_ROAD_3F

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
SECRET_KEY = 0x2B   # Pokémon Mansion B1F: it unlocks Blaine's gym door ("La porte est fermée..." without it, BUG-0697)
MANSION_2F, MANSION_3F, MANSION_B1F = 0xD6, 0xD7, 0xD8
MANSION = (MANSION_1F, MANSION_2F, MANSION_3F, MANSION_B1F)
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
ROUTE19, ROUTE20, ROUTE21 = 0x1E, 0x1F, 0x20   # Route 21: the sea south of Pallet Town to Cinnabar (BUG-0693); the sea south of Fuchsia: Route 19 south, then Route 20 west to the Seafoam Islands (by Surf)
FUCHSIA_CENTER, FUCHSIA_GYM = 0x9A, 0x9D   # Fuchsia City's Pokémon Center and gym (door (5, 27))
ROUTE12_GATE = 0x57   # the gate house across Route 12: its two doors are the road
ROUTE11, ROUTE11_GATE, ROUTE2_GATE = 0x16, 0x54, 0x31   # Route 11 (Vermilion to Route 12), its gate house, Route 2's gate house
DIGLETT_ROUTE11, DIGLETTS_CAVE, DIGLETT_ROUTE2 = 0x55, 0xC5, 0x2E   # Diglett's Cave: the Route 11 house, the cave, the Route 2 house
SAFARI_GATE, SAFARI_SECRET_HOUSE, WARDENS_HOUSE = 0x9C, 0xDE, 0x9B   # Fuchsia: the Safari Zone's entrance, the Secret House far inside it, the Warden's house
SAFARI_ZONE = (0xD9, 0xDA, 0xDB, 0xDC)   # east, north, west and centre areas (the Secret House is off the west one)
SAFARI_HOUSES = (0xDD, 0xDE, 0xDF, 0xE0, 0xE1)   # the rest houses and the Secret House
HM03_SURF, HM04_STRENGTH = 0xC6, 0xC7
SURF, STRENGTH = 57, 70   # move ids
GOOD_ROD, GOOD_ROD_HOUSE = 0x4D, 0xA4   # the fishing guru's house in Fuchsia (doors (31, 24) and (31, 27), world graph) gives it
# BUG-0673: the milestones a defer flag lets through without playing them: cleared from `done` with the flag
# the road to Fuchsia the long play has walked (Rock Tunnel, then Routes 12-15): the world graph's shorter way through
# Saffron's north gate ends in Route 5's south pocket (BUG-0639), where a replay of the 20261019-113003 save ping-ponged
ROAD_TO_FUCHSIA = (CERULEAN, ROUTE9, ROUTE10, LAVENDER, ROUTE12, ROUTE13, ROUTE14, ROUTE15, FUCHSIA)
DEFERRED_BY = {"surf_deferred": ("seafoam", "secret_key", "volcano_badge", "silph_co", "marsh_badge", "earth_badge", "hall_of_fame"), "strength_deferred": ()}
SAFFRON, ROUTE7_GATE = 0x0A, 0x4C   # Saffron City; the gate house across Route 7's east end (verified in the world graph)
ROUTE6_GATE, SAFFRON_GYM, VIRIDIAN_GYM, ROUTE22_GATE = 0x49, 0xB2, 0x2D, 0xC1   # BUG-0708: Sabrina's and Giovanni's gyms, the gates on the way
# BUG-0710: Silph Co.'s floors (map header table of the owner's ROM: 1F is Saffron's warp (18, 21); the stairs go 1F->11F)
SILPH_CO = (0xB5,) + tuple(range(0xCF, 0xD6)) + (0xE9, 0xEA, 0xEB)
SILPH_CO_1F, SILPH_CO_11F, SILPH_ELEVATOR = SILPH_CO[0], SILPH_CO[-1], 0xEC
MASTER_BALL = 0x01   # the Silph president's thanks once Giovanni is beaten on 11F
# BUG-0711: 11F's stairs end in a part with no way to Giovanni: his room is behind a Card Key gate in the part the 7F
# teleporter lands in, and 7F's teleporter is reached from 3F's, behind another gate. The Card Key is an item ball on 5F.
SILPH_3F, SILPH_5F, SILPH_7F = SILPH_CO[2], SILPH_CO[4], SILPH_CO[6]
CARD_KEY = 0x30
CARD_KEY_DOORS = (0x18, 0x24)   # the game's PrintCardKeyText: the tile in front of the player on every Silph floor,
CARD_KEY_DOOR_11F = 0x5E         # plus this one on 11F
ROUTE15_GATE = 0xB8   # the gate house across Route 15 (1F; 0xB9 is its 2F): both doors are on Route 15
CELADON_MART = (0x7A, 0x7B, 0x7C, 0x7D, 0x88, 0x7F)   # Celadon Dept. Store 1F..5F (5F is 0x88) and its elevator
MART_ROOF = 0x7E   # verified: 5F's stairs lead to it
MT_MOON_EXIT_X = 24   # Route 4: Mt. Moon's exit (from B1F) lands at x 24; the entrance side is west of it


def bag(read: Read) -> Dict[int, int]:
    n = read(BAG_COUNT, 1)[0]
    raw = read(BAG_ITEMS, 2 * min(n, 20))
    return {raw[2 * i]: raw[2 * i + 1] for i in range(min(n, 20))}


def party_knows(read: Read, move: int) -> bool:
    """Some party Pokémon knows this move (party structs: 44 bytes, moves at +8)."""
    n = min(read(ADDR["party_count"], 1)[0], 6)
    return any(move in read(ADDR["party_mons"] + 0x2C * i + 8, 4) for i in range(n))


def badges(read: Read) -> int:
    return bin(read(BADGES, 1)[0]).count("1")


MARSH_BADGE, VOLCANO_BADGE, EARTH_BADGE = 0x20, 0x40, 0x80   # badge bits: Boulder 0x01 ... Marsh 0x20, Volcano 0x40, Earth 0x80


def has_badge(read: Read, bit: int) -> bool:
    """BUG-0707: this one badge, not a count: Sabrina's Marsh Badge is skipped, so Blaine's is the 6th, not the 7th."""
    return bool(read(BADGES, 1)[0] & bit)


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
    # BUG-0968: the road to Fuchsia passes through the gate house across Route 15 (its two doors are on the
    # route, (7, 8) and (14, 8)), and the world graph learns a map's links only when the runner has been
    # inside it: the graph knew the door led to an unknown map, so it knew no way on to Fuchsia and the
    # guide walked the runner back to Route 14 - whose own next waypoint is Route 15 again. The two swapped
    # the runner for ever (the run of 20261027-052520: 2261 walk_targets, no milestone, no new map, no new
    # square for 5 min of game time). The area holds the way on (the gate house of Route 15): the runner
    # explores it, learns its doors and walks on to Fuchsia.
    Milestone("fuchsia", "Wake the Snorlax on Route 12 with the Poké Flute and walk Routes 12 to 15 to Fuchsia City",
              [LAVENDER, ROUTE12, ROUTE13, ROUTE14, ROUTE15, FUCHSIA], lambda r, m: r(ADDR["map"], 1)[0] == FUCHSIA,
              area=(ROUTE12_GATE, ROUTE15_GATE), prepare=True),
    # the gym is a maze of invisible walls: they are real collision squares, so the grid knows them
    Milestone("soul_badge", "Beat Koga at the Fuchsia City gym", [FUCHSIA, FUCHSIA_GYM],
              lambda r, m: badges(r) >= 5, at_goal="challenge the gym leader", prepare=True),
    # the Safari Zone's Secret House (far inside) gives HM03; the entrance fee is paid by walking in (the zone's
    # step limit sends the player back to the gate: the route simply leads in again)
    Milestone("surf", "Cross the Safari Zone to the Secret House, get HM03 and teach Surf",
              [FUCHSIA_GYM, FUCHSIA, SAFARI_GATE, SAFARI_SECRET_HOUSE],
              lambda r, m: party_knows(r, SURF) or m.get("surf_deferred", False), area=SAFARI_ZONE + SAFARI_HOUSES,
              at_goal="talk to the Secret House's owner"),
    # BUG-0673: the Safari hunt gave up (`surf_deferred`) and nothing else ever looked for a Surf learner, so the
    # story "ended" at 5 badges. The fishing guru's Good Rod hooks Goldeen / Poliwag (L10, both learn Surf, easy
    # catches) from any shore; HM03 is then taught by `pending_hm`
    Milestone("surf_learner", "Get the Good Rod in Fuchsia, fish a Pokémon that can learn Surf and teach it Surf",
              [FUCHSIA, GOOD_ROD_HOUSE], lambda r, m: party_knows(r, SURF)),
    # the Gold Teeth lie somewhere in the Safari Zone; the Warden in Fuchsia gives HM04 for them
    Milestone("strength", "Find the Warden's Gold Teeth in the Safari Zone and bring them to him for HM04",
              [FUCHSIA, WARDENS_HOUSE], lambda r, m: party_knows(r, STRENGTH) or m.get("strength_deferred", False), area=SAFARI_ZONE + SAFARI_HOUSES,
              at_goal="talk to the Warden"),
    # the gate guards are thirsty: a drink from the Dept. Store roof's vending machines (the way is walked back
    # from Fuchsia to Celadon first)
    Milestone("saffron", "Buy a drink on the Celadon Dept. Store roof, give it to a gate guard and enter Saffron City",
              [WARDENS_HOUSE, FUCHSIA, ROUTE15, ROUTE14, ROUTE13, ROUTE12, LAVENDER, ROUTE8, ROUTE7, CELADON, MART_ROOF,
               CELADON, ROUTE7, SAFFRON],   # the gate house is in `area`: a route through it ends on Route 7 again
              lambda r, m: r(ADDR["map"], 1)[0] == SAFFRON,
              area=(ROUTE12_GATE, ROUTE15_GATE, ROUTE7_GATE, PATH_ROUTE8, PATH_WEST_EAST, PATH_ROUTE7) + CELADON_MART, prepare=True),
    # BUG-0693: Route 20 is two seas (BUG-0690 read it as one): the Fuchsia side only meets the Cinnabar side through the
    # Seafoam Islands, whose B4F currents need the boulder puzzle (placeholder plans in strength.py). Cinnabar is reached
    # the boulder-free way: on to Pallet Town and surf Route 21 south. The id stays `seafoam`.
    # BUG-0694: Route 4's ledge is one-way (Cerulean is no way back west to Mt. Moon): Route 12 west to Route 11 and
    # Diglett's Cave to Route 2, then south to Viridian.
    Milestone("seafoam", "Walk from Fuchsia through Diglett's Cave to Pallet Town and surf Route 21 south to Cinnabar Island",
              [FUCHSIA, ROUTE15, ROUTE14, ROUTE13, ROUTE12, ROUTE11, DIGLETT_ROUTE11, DIGLETTS_CAVE, DIGLETT_ROUTE2, ROUTE2,
               VIRIDIAN, ROUTE1, PALLET, ROUTE21, CINNABAR_ISLAND],
              # BUG-0643: deferred when the party has no Surf user: without it the runner has no route and stalls
              lambda r, m: r(ADDR["map"], 1)[0] == CINNABAR_ISLAND or m.get("surf_deferred", False),
              # the islands and the sea south of Fuchsia: where a save of the old route stands (BUG-0683: the Good Rod house)
              area=SEAFOAM_ISLANDS + (GOOD_ROD_HOUSE, ROUTE19, ROUTE20, ROUTE12_GATE, ROUTE15_GATE, ROUTE11_GATE, ROUTE2_GATE,
                                      FOREST_NORTH_GATE, VIRIDIAN_FOREST, FOREST_SOUTH_GATE, MANSION_1F, CINNABAR_GYM), prepare=True),
    # BUG-0697: Blaine's gym door is locked until the Secret Key, an item ball in the Pokémon Mansion's basement
    Milestone("secret_key", "Find the Secret Key in the Pokémon Mansion's basement, it opens Blaine's gym",
              [CINNABAR_ISLAND, MANSION_1F, MANSION_2F, MANSION_3F, MANSION_1F, MANSION_B1F],   # 3F -> 1F: a hole (runner)
              lambda r, m: SECRET_KEY in bag(r) or has_badge(r, VOLCANO_BADGE) or m.get("surf_deferred", False),
              area=MANSION, prepare=True),
    # Blaine's gym has the Volcano Badge; the gym puzzle is trivial (Quiz / trainer-beating),
    # no Strength / puzzle to solve.
    Milestone("volcano_badge", "Beat Blaine at the Cinnabar Island gym for the Volcano Badge",
              [CINNABAR_ISLAND, CINNABAR_GYM],
              lambda r, m: has_badge(r, VOLCANO_BADGE) or m.get("surf_deferred", False),   # BUG-0643: Cinnabar is reached by Surf
              at_goal="challenge the gym leader", prepare=True),
    # BUG-0708: Route 23's guards check every badge up to the Earth Badge, and Giovanni's gym opens on 7 badges: Sabrina
    # (skipped on the way south, BUG-0707) and Giovanni come before Victory Road. Back by Route 21, Pallet and Diglett's
    # Cave (the `seafoam` way, walked the other way round), then Vermilion and Route 6 into Saffron.
    # BUG-0710: Route 6's gate stands inside Route 6 (its north door lands on Route 6's north strip, the edge to Saffron
    # is Route 6's): as a guide map it sent the runner back into the gate from that strip, round and round. Area only.
    # BUG-0710: Rocket grunts stand on the squares below Saffron's doors, the gym's (34, 4) among them, until Giovanni is
    # beaten on Silph Co. 11F: Saffron was a dead end. Up Silph Co.'s stairs first; the president then gives the Master Ball.
    Milestone("silph_co", "Free Silph Co.: beat Giovanni on 11F, the Rockets in front of Saffron's gym leave",
              [CINNABAR_GYM, CINNABAR_ISLAND, ROUTE21, PALLET, ROUTE1, VIRIDIAN, ROUTE2, DIGLETT_ROUTE2, DIGLETTS_CAVE,
               DIGLETT_ROUTE11, ROUTE11, VERMILION, ROUTE6, SAFFRON] + list(SILPH_CO),
              lambda r, m: MASTER_BALL in bag(r) or has_badge(r, MARSH_BADGE) or m.get("surf_deferred", False),
              area=(ROUTE2_GATE, ROUTE11_GATE, PATH_ROUTE6, ROUTE6_GATE, ROUTE7_GATE, ROUTE5, SILPH_ELEVATOR),
              at_goal="talk to the president", prepare=True),
    Milestone("marsh_badge", "Beat Sabrina at the Saffron City gym for the Marsh Badge",
              [SILPH_CO_11F] + list(reversed(SILPH_CO[:-1])) + [SAFFRON, SAFFRON_GYM],
              lambda r, m: has_badge(r, MARSH_BADGE) or m.get("surf_deferred", False),   # the way from Cinnabar is by Surf
              # BUG-0711: no SILPH_ELEVATOR: never visited, it drew the explorer from Saffron back into Silph Co. 1F
              area=(ROUTE6_GATE,), at_goal="challenge the gym leader", prepare=True),
    Milestone("earth_badge", "Beat Giovanni at the Viridian City gym for the Earth Badge",
              [SAFFRON_GYM, SAFFRON, ROUTE6, VERMILION, ROUTE11, DIGLETT_ROUTE11, DIGLETTS_CAVE, DIGLETT_ROUTE2,
               ROUTE2, VIRIDIAN, VIRIDIAN_GYM],
              lambda r, m: has_badge(r, EARTH_BADGE) or m.get("surf_deferred", False),   # the gym wants 7 badges, Blaine's among them
              # BUG-0715: Diglett's house lands on Route 2's north half; the known way south is the forest (Route 2's own
              # gate is never visited). Off the guide, its north gate sent the runner back to Route 2, round and round
              area=(ROUTE2_GATE, ROUTE11_GATE, PATH_ROUTE6, ROUTE6_GATE, FOREST_NORTH_GATE, VIRIDIAN_FOREST, FOREST_SOUTH_GATE),
              at_goal="challenge the gym leader", prepare=True),
    # After the Earth Badge is the Elite Four (Lorelei, Bruno, Agatha, Lance) on Indigo Plateau.
    # Reaching the Hall of Fame room (after Lance) is the run's goal; the in-battle heuristic
    # already chooses moves.
    Milestone("hall_of_fame", "Take Route 22, Route 23 and Victory Road to Indigo Plateau and beat the Elite Four",
              # BUG-0878: Victory Road 1F is a dead end for the runner: its boulder at (2, 10) seals the
              # one-wide corridor to the stairs at (1, 1) and the push cannot be set up (the square it
              # starts from, (2, 9), is out of reach). The way on is Route 23's second warp,
              # (14, 31) -> Victory Road 2F (194): the runner walks 1F back to Route 23 and takes it,
              # so 1F comes before Route 23 on the waypoints and Victory Road 2F after it.
              # BUG-0880: that second warp is not a way on for a runner that comes through the gate: the
              # measured world graph of Route 23 holds (7,139)/(8,139) -> 193 (the gate), (4,31) -> 108
              # (Victory Road 1F) and (14,31) -> 194, but the warp to 194 sits in another part of the map
              # (the plaza, x = 14..19) than the player (the gate and the west road), so `route 34 -> 194`
              # is None and the guide asked for a map the runner cannot reach: every tick answered "no
              # route" and the player stood still on Route 23 (the same_spot stall of run 20261023-213300).
              # The way on from the gate is Route 23 -> Victory Road 1F (the warp at (4, 31), 81 steps
              # away and reachable), so Route 23 comes before 1F on the waypoints.
              #
              # BUG-0962: the upper floors of Victory Road are not waypoints to the Elite Four.
              # Measured on the live save (the world graph of the run 20261026-193346), Victory Road 3F
              # (198) is a DEAD END: its four exits all lead back to Victory Road 2F (194) - (23, 7),
              # (26, 8), (27, 15) and (2, 0) - and it has no edge exit at all. The way to Indigo
              # Plateau is Route 23's north edge (map 34's north edge -> 9), and Route 23 is reached
              # from Victory Road 1F ((8, 17) and (9, 17)) or from Victory Road 2F's east side
              # ((29, 7) and (29, 8)). With 2F and 3F on the waypoints, the runner climbed from 2F to
              # 3F, could not use the exit that leads to the way out (the warp at (26, 8), the one
              # that lands next to Route 23 - a boulder was in the way), fell back to 2F and was sent
              # up again: the lane ping-ponged between the two floors for ever (no_progress, the run
              # 20261026-193346, map 194 at (6, 8)). Victory Road 1F stays a waypoint (the runner
              # comes through the Route 22 gate and crosses it), but the floors above it are no
              # waypoints: the waypoints are the way out (Route 23) and the goal.
              [VIRIDIAN_GYM, VIRIDIAN, ROUTE_22, ROUTE22_GATE, ROUTE_23,
               VICTORY_ROAD_1F, INDIGO_PLATEAU, INDIGO_PLATEAU_LOBBY, HALL_OF_FAME],
              # BUG-0662: deferred when Surf is (Route 23 is crossed by Surf): without it the runner wandered Cerulean
              # for 10 stalls with no route
              lambda r, m: r(ADDR["map"], 1)[0] == HALL_OF_FAME or m.get("surf_deferred", False),
              area=VICTORY_ROAD + (INDIGO_PLATEAU_LOBBY, INDIGO_PLATEAU, HALL_OF_FAME, ROUTE_22, ROUTE_23, ROUTE22_GATE),
              prepare=True),
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
