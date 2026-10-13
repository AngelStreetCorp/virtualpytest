"""
Overworld: which squares around the player are walkable, and A* paths on them.

The screen shows 10 x 9 squares (2 x 2 tiles each) with the player at square (4, 4). In Gen 1 a
square is walkable when its lower-left tile is in the current tileset's passable list; the list's
address is in wTilesetCollisionPtr (French ROM: D535) and the list itself (ending in 0xFF) is read
from the ROM. Visible sprites (NPCs) block their square: map position in wSpriteStateData2
(C200 + 16 * i, +4 = Y + 4, +5 = X + 4), hidden when wSpriteStateData1 image index (C100 + 16 * i + 2)
is 0xFF and the sprite is on screen (see sprite_list). Verified on the French ROM (TASK-33 §00000).

full_grid() covers the whole current map: the map's blocks are in WRAM (wOverworldMap, C6E8, with a
3-block border), each block's 16 tiles come from the tileset's block table in the ROM (bank in D530,
pointer in D531), and a square is walkable by the same lower-left-tile rule. Verified on Pallet Town
(the north exit gap at x = 10-11, the houses and the lab door). Paths are re-planned after every step.

Ledges are one-way jumps, only on the outdoor tileset: from a square whose lower-left tile is the
"standing" tile, pressing toward a ledge square jumps over it, two squares on. The game's own table
(player facing, standing tile, ledge tile, input; ending 0xFF) is read from the ROM: pokered's
LedgeTiles, found at 0x1A6D4 in the French ROM. full_grid() returns the jumps with the grid.

Some moves between two walkable squares are blocked by their tile pair: in caves, between the floor
and raised ground (pokered's TilePairCollisionsLand: tileset, tile, tile; ending 0xFF; at 0xC7E in the
French ROM). full_grid() returns them as `walls` (pairs of squares).
"""

import heapq
from typing import Dict, List, Optional, Set, Tuple

from .memory import ADDR, Read

COLLISION_PTR = 0xD530 + 5
CUR_TILESET, OVERWORLD_TILESET = 0xD367 + 5, 0   # ledges exist on the outdoor tileset only
LEDGE_TABLE_START = bytes([0x00, 0x2C, 0x37, 0x80])   # first entry: facing down, standing 2C, ledge 37, D_DOWN
FACING = {0x00: "DOWN", 0x04: "UP", 0x08: "LEFT", 0x0C: "RIGHT"}
TILE_PAIRS_START = bytes([0x11, 0x20, 0x05, 0x11, 0x41, 0x05])   # first entries: cavern 20/05, 41/05
TILESET_BANK, BLOCKS_PTR = 0xD52B + 5, 0xD52C + 5
MAP_HEIGHT, MAP_WIDTH = 0xD368 + 5, 0xD369 + 5
OVERWORLD_MAP, BORDER = 0xC6E8, 3
SPRITES1, SPRITES2 = 0xC100, 0xC200
PLAYER_SQUARE = (4, 4)
TREE_TILE = {0: 0x3D, 7: 0x50}   # tileset (overworld, gym) -> lower-left tile of a cuttable tree (what the game checks)
FACILITY_TILESET = 22            # the Rocket Hideout (and Silph Co.): arrow squares push the player
# an arrow square is told by all four of its tiles (top-left, top-right, bottom-left, bottom-right): the
# arrows are drawn from the same four pieces, so the lower-left tile alone says nothing (verified on B3F)
ARROWS = {(0x20, 0x30, 0x20, 0x30): "DOWN", (0x21, 0x31, 0x21, 0x31): "UP",
          (0x21, 0x21, 0x20, 0x20): "LEFT", (0x31, 0x31, 0x30, 0x30): "RIGHT"}
SPIN_STOP = 0x5E                 # a pushed player slides over plain squares until this tile (or a wall)
CUT_COST = 12                    # A* cost of a tree: a detour shorter than this beats the Cut menu trip
FACING_ADDR = 0xC109   # wSpritePlayerStateData1FacingDirection (not shifted)
FACING_KEY = {k: v for v, k in FACING.items()}
STEP = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def passable_tiles(read: Read, rom: bytes) -> Set[int]:
    lo, hi = read(COLLISION_PTR, 2)
    ptr = hi * 256 + lo
    out, i = set(), ptr
    while i < len(rom) and rom[i] != 0xFF and len(out) < 64:
        out.add(rom[i])
        i += 1
    return out


def sprite_list(read: Read) -> List[Tuple[int, Tuple[int, int]]]:
    """[(picture, (x, y))] for the sprites that are present, other than the player.

    The image byte (C100 + 16 i + 2) is 0xFF both for a hidden sprite and for any sprite outside the
    visible 10 x 9 window, so 0xFF means hidden only for sprites on screen (verified in Oak's lab:
    the cutscene double next to the player is 0xFF, the real Oak off screen at his desk too)."""
    px, py = read(ADDR["x"], 1)[0], read(ADDR["y"], 1)[0]
    out = []
    for i in range(1, 16):
        picture, _move, image = read(SPRITES1 + 16 * i, 3)
        if picture == 0:
            continue
        y4, x4 = read(SPRITES2 + 16 * i + 4, 2)
        x, y = x4 - 4, y4 - 4
        on_screen = -PLAYER_SQUARE[0] <= x - px <= 5 and -PLAYER_SQUARE[1] <= y - py <= 4
        if image == 0xFF and on_screen:
            continue
        out.append((picture, (x, y)))
    return out


def sprites(read: Read) -> List[Tuple[int, int]]:
    """Map (x, y) of the present sprites other than the player."""
    return [pos for _, pos in sprite_list(read)]


class Grid(dict):
    """{(x, y): walkable}, plus `jumps`: {square: [(direction, landing square)]} for the ledges, and
    `walls`: {(square, square)} moves blocked by their tile pair (both directions listed), `cuts`: the
    squares holding a cuttable tree (walkable in the grid only when Cut is known; A* charges for them)."""
    jumps: Dict[Tuple[int, int], List[Tuple[str, Tuple[int, int]]]] = {}
    walls: Set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
    cuts: Set[Tuple[int, int]] = set()


def tile_pairs(rom: bytes) -> Set[Tuple[int, int, int]]:
    """{(tileset, tile, tile)} (both orders) from the ROM's tile-pair collision table."""
    i, out = rom.find(TILE_PAIRS_START), set()
    while 0 <= i < len(rom) - 2 and rom[i] != 0xFF:
        out |= {(rom[i], rom[i + 1], rom[i + 2]), (rom[i], rom[i + 2], rom[i + 1])}
        i += 3
    return out


def ledge_table(rom: bytes) -> Dict[Tuple[int, int], str]:
    """{(standing tile, ledge tile): direction} from the ROM's ledge table."""
    i = rom.find(LEDGE_TABLE_START)
    out = {}
    while 0 <= i < len(rom) - 3 and rom[i] != 0xFF:
        facing, stand, ledge = rom[i], rom[i + 1], rom[i + 2]
        if facing in FACING:
            out[(stand, ledge)] = FACING[facing]
        i += 4
    return out


def rom_address(bank: int, ptr: int) -> int:
    return ptr if ptr < 0x4000 else bank * 0x4000 + (ptr - 0x4000)


def full_grid(read: Read, rom: bytes, sprites_block: bool = True, cut: bool = False) -> Grid:
    """{(x, y): walkable} for every square of the current map, with the ledge jumps (`.jumps`) and the
    tile-pair walls (`.walls`). Visible sprites block their square for walking; for the map's layout
    (`sprites_block=False`) they do not: a trainer fights and an item ball is picked up, so neither
    splits a cave floor (Mt. Moon B2F: the fossils and the Super Nerd stand in the way). With `cut`
    (a party member knows Cut) the cuttable trees count as walkable and are listed in `.cuts`."""
    h, w = read(MAP_HEIGHT, 2)
    bank = read(TILESET_BANK, 1)[0]
    lo, hi = read(BLOCKS_PTR, 2)
    blocks = rom_address(bank, hi * 256 + lo)
    ok_tiles = passable_tiles(read, rom)
    stride = w + 2 * BORDER
    ow = read(OVERWORLD_MAP, stride * (h + 2 * BORDER))
    blocked = set(sprites(read)) if sprites_block else set()
    px, py = read(ADDR["x"], 1)[0], read(ADDR["y"], 1)[0]
    out, tiles, quads = Grid(), {}, {}
    facility = read(CUR_TILESET, 1)[0] == FACILITY_TILESET
    for sy in range(2 * h):
        for sx in range(2 * w):
            blk = ow[(sy // 2 + BORDER) * stride + (sx // 2 + BORDER)]
            tile = rom[blocks + blk * 16 + ((sy % 2) * 2 + 1) * 4 + (sx % 2) * 2]
            tiles[(sx, sy)] = tile
            if facility:
                base = blocks + blk * 16 + (sy % 2) * 8 + (sx % 2) * 2
                quads[(sx, sy)] = (rom[base], rom[base + 1], rom[base + 4], rom[base + 5])
            out[(sx, sy)] = (tile in ok_tiles and (sx, sy) not in blocked) or (sx, sy) == (px, py)
    out.jumps, out.walls, out.cuts = {}, set(), set()
    tileset = read(CUR_TILESET, 1)[0]
    tree = TREE_TILE.get(tileset)
    out.cuts = {sq for sq, t in tiles.items() if t == tree and sq not in blocked and sq != (px, py)}
    if cut:
        out.update({sq: True for sq in out.cuts})
    pairs = {(a, b) for ts, a, b in tile_pairs(rom) if ts == tileset}
    if pairs:
        for sq, t in tiles.items():
            for dx, dy in ((1, 0), (0, 1)):
                nb = (sq[0] + dx, sq[1] + dy)
                if (t, tiles.get(nb)) in pairs:
                    out.walls |= {(sq, nb), (nb, sq)}
    if tileset == FACILITY_TILESET:
        add_arrows(out, tiles, quads, (px, py))
    if tileset == OVERWORLD_TILESET:
        ledges = ledge_table(rom)
        for sq, ok in out.items():
            if not ok:
                continue
            for d, (dx, dy) in STEP.items():
                over, land = (sq[0] + dx, sq[1] + dy), (sq[0] + 2 * dx, sq[1] + 2 * dy)
                if ledges.get((tiles[sq], tiles.get(over))) == d and out.get(land):
                    out.jumps.setdefault(sq, []).append((d, land))
    return out


def ride(arrows: Dict[Tuple[int, int], str], stops: Set[Tuple[int, int]], ok: Dict[Tuple[int, int], bool],
         start: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """Where the player ends after stepping onto the arrow square `start`: pushed along the arrow (a
    second arrow turns the slide) until a stop square or a wall. None when the slide ends on an arrow."""
    pos, d, seen = start, arrows[start], set()
    while pos not in seen:
        seen.add(pos)
        nxt = (pos[0] + STEP[d][0], pos[1] + STEP[d][1])
        if not ok.get(nxt):
            break
        pos = nxt
        if pos in stops:
            break
        d = arrows.get(pos, d)
    return None if pos in arrows else pos


def add_arrows(out: "Grid", tiles: Dict[Tuple[int, int], int], quads: Dict[Tuple[int, int], Tuple], player: Tuple[int, int]) -> None:
    """Arrow squares are no squares to stand on: stepping onto one is a jump to where the slide ends."""
    arrows = {sq: ARROWS[q] for sq, q in quads.items() if q in ARROWS and out[sq] and sq != player}
    stops = {sq for sq, t in tiles.items() if t == SPIN_STOP}
    land = {sq: ride(arrows, stops, out, sq) for sq in arrows}
    for sq in arrows:
        out[sq] = False
    for sq, ok in out.items():
        if not ok:
            continue
        for d, (dx, dy) in STEP.items():
            nb = (sq[0] + dx, sq[1] + dy)
            if land.get(nb):
                out.jumps.setdefault(sq, []).append((d, land[nb]))


def block_at(read: Read, x: int, y: int) -> int:
    """The map block under square (x, y): a switch can change one (the Game Corner's stairs)."""
    h, w = read(MAP_HEIGHT, 2)
    stride = w + 2 * BORDER
    return read(OVERWORLD_MAP + (y // 2 + BORDER) * stride + (x // 2 + BORDER), 1)[0]


def edge_squares(walk: Dict[Tuple[int, int], bool], side: str, span=None) -> List[Tuple[int, int]]:
    """The walkable squares on one edge of the map where the edge connection can be crossed: within
    `span` ([first, end) along the edge, from the connection header) when given."""
    xs = [p[0] for p in walk]
    ys = [p[1] for p in walk]
    lo, hi = span or (-10 ** 6, 10 ** 6)
    pick = {"north": lambda p: p[1] == min(ys) and lo <= p[0] < hi, "south": lambda p: p[1] == max(ys) and lo <= p[0] < hi,
            "west": lambda p: p[0] == min(xs) and lo <= p[1] < hi, "east": lambda p: p[0] == max(xs) and lo <= p[1] < hi}[side]
    return [p for p, ok in walk.items() if ok and pick(p)]


def grid(read: Read, rom: bytes) -> Dict[Tuple[int, int], bool]:
    """{(map_x, map_y): walkable} for the 10 x 9 visible squares."""
    px, py = read(ADDR["x"], 1)[0], read(ADDR["y"], 1)[0]
    tiles = read(ADDR["tilemap"], 360)
    ok_tiles = passable_tiles(read, rom)
    blocked = set(sprites(read))
    out = {}
    for r in range(9):
        for c in range(10):
            mx, my = px + c - PLAYER_SQUARE[0], py + r - PLAYER_SQUARE[1]
            t = tiles[(r * 2 + 1) * 20 + c * 2]
            out[(mx, my)] = (mx >= 0 and my >= 0 and t in ok_tiles and (mx, my) not in blocked) or (c, r) == PLAYER_SQUARE
    return out


def astar(walk: Dict[Tuple[int, int], bool], start: Tuple[int, int], goal: Tuple[int, int]) -> Optional[List[str]]:
    """Directions from start to goal on the walkable squares. The goal itself may be blocked (a door,
    a sign or an NPC): the last step then points into it, which walks through a door or turns the
    player to face the sign or NPC."""
    def h(p):
        return abs(p[0] - goal[0]) + abs(p[1] - goal[1])
    jumps, walls, cuts = getattr(walk, "jumps", {}), getattr(walk, "walls", set()), getattr(walk, "cuts", set())
    frontier = [(h(start), 0, start, [])]
    seen = {start}
    while frontier:
        _, cost, pos, path = heapq.heappop(frontier)
        if pos == goal:
            return path
        moves = [(d, (pos[0] + dx, pos[1] + dy)) for d, (dx, dy) in STEP.items()] + jumps.get(pos, [])
        for d, nxt in moves:
            if nxt in seen or nxt not in walk or (pos, nxt) in walls:
                continue
            if not walk[nxt] and nxt != goal:
                continue
            seen.add(nxt)
            step = 1 + (CUT_COST if nxt in cuts and walk[nxt] else 0)
            heapq.heappush(frontier, (cost + step + h(nxt), cost + step, nxt, path + [d]))
    return None


def toward(walk: Dict[Tuple[int, int], bool], start: Tuple[int, int], goal: Tuple[int, int]) -> Optional[List[str]]:
    """A path to the goal, or (goal off screen / unreachable) to the reachable square closest to it."""
    path = astar(walk, start, goal)
    if path is not None:
        return path
    best = sorted((abs(p[0] - goal[0]) + abs(p[1] - goal[1]), p) for p, ok in walk.items() if ok and p != start)
    for _, p in best:
        path = astar(walk, start, p)
        if path:
            return path
    return None


def reachable(walk: Dict[Tuple[int, int], bool], start: Tuple[int, int]) -> Set[Tuple[int, int]]:
    """Squares connected to `start` (the player's part of the map), plus the blocked squares next to
    them (doors and warps drawn as blocked can still be entered)."""
    jumps, walls = getattr(walk, "jumps", {}), getattr(walk, "walls", set())
    seen, stack = {start}, [start]
    while stack:
        x, y = stack.pop()
        for nxt in [(x + dx, y + dy) for dx, dy in STEP.values()] + [land for _, land in jumps.get((x, y), [])]:
            if nxt in walk and nxt not in seen and walk[nxt] and ((x, y), nxt) not in walls:
                seen.add(nxt)
                stack.append(nxt)
    fringe = {(x + dx, y + dy) for x, y in seen for dx, dy in STEP.values() if (x + dx, y + dy) in walk}
    return seen | fringe
