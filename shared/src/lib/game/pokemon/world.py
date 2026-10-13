"""
World: the current map's links (edge connections and warps) and routes between maps.

From the map header in WRAM (French ROM, US addresses +5; verified in Pallet Town: north 0x0C, south
0x20, warps to 0x25 / 0x27 / 0x28):
- connections bitmask D375; connected map ids: north D376, south D381, west D38C, east D397 (0xFF = none).
  Each is the first byte of an 11-byte connection header (map, strip source, strip destination in
  wOverworldMap C6E8, strip length in blocks, alignments, window): the strip is the stretch of the edge
  that leads to the connected map (Route 4's south edge meets Route 3 only on its first 20 squares)
- number of warps D3B3, warp entries from D3B4 (y, x, destination warp, destination map); a destination
  of 0xFF ("outside") means the map in wLastMap (D36A)
- map height / width in 2 x 2-square blocks: D36D / D36E

The world graph is learned while playing: every map visited adds its links. Routes are a BFS over
it; the first hop is either an edge (walk off the map on that side) or a warp (walk onto it).
"""

from collections import deque
from typing import Dict, List, Optional, Tuple

from .memory import ADDR, Read

SH = 5
CONNECTION = {"north": 0xD371 + SH, "south": 0xD37C + SH, "west": 0xD387 + SH, "east": 0xD392 + SH}
N_WARPS, WARPS = 0xD3AE + SH, 0xD3AF + SH
HEIGHT, WIDTH = 0xD368 + SH, 0xD369 + SH
LAST_MAP = 0xD365 + SH  # wLastMap: where a warp with destination 0xFF ("outside") leads


OVERWORLD_MAP, BORDER = 0xC6E8, 3


def links(read: Read) -> Dict:
    """{map, width, height (in squares), edges {side: map}, spans {side: [first, end) square along the
    edge}, warps [(x, y, dest_map, dest_warp)]}."""
    edges, spans = {}, {}
    h, w = read(HEIGHT, 2)
    stride = w + 2 * BORDER
    for side, addr in CONNECTION.items():
        hdr = read(addr, 6)
        m = hdr[0]
        if m != 0xFF:
            edges[side] = m
            off, length = hdr[3] + 256 * hdr[4] - OVERWORLD_MAP, hdr[5]
            start = (off % stride if side in ("north", "south") else off // stride) - BORDER
            size = 2 * (w if side in ("north", "south") else h)
            spans[side] = [max(0, 2 * start), min(size, 2 * (start + length))]
    n = read(N_WARPS, 1)[0]
    last = read(LAST_MAP, 1)[0]
    warps = []
    for i in range(min(n, 32)):
        y, x, dest_warp, dest = read(WARPS + 4 * i, 4)
        warps.append((x, y, last if dest == 0xFF else dest, dest_warp))
    return {"map": read(ADDR["map"], 1)[0], "width": 2 * w, "height": 2 * h, "edges": edges, "spans": spans,
            "warps": warps}


class _EveryMap:
    """`unknown=ANY_MAP`: any map not visited yet is a target of explore (a last resort: with no known way
    on, a gate house or a house may hold the way)."""
    def __contains__(self, m) -> bool:
        return True


ANY_MAP = _EveryMap()
OPPOSITE = {"north": "south", "south": "north", "west": "east", "east": "west"}


def parts(walk: Dict[Tuple[int, int], bool], info: Dict, pos: Optional[Tuple[int, int]] = None) -> Dict:
    """Which connected part of the map each warp and each edge belongs to:
    {"warp": [part per warp], "edge": {side: [parts]}, "down": [[part, part]], "player": part of `pos`}.
    A part is the index of a flood-filled component of walkable squares (doors drawn as blocked join the
    part next to them; tile-pair walls split them). "down" lists the one-way ledge jumps between parts."""
    jumps, walls = getattr(walk, "jumps", {}), getattr(walk, "walls", set())
    comp, n = {}, 0
    for start, ok in walk.items():
        if not ok or start in comp:
            continue
        stack = [start]
        comp[start] = n
        while stack:
            x, y = stack.pop()
            nxt = [(x + dx, y + dy) for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))]
            for q in nxt:
                if walk.get(q) and q not in comp and ((x, y), q) not in walls:
                    comp[q] = n
                    stack.append(q)
        n += 1

    def part_of(sq):
        if sq in comp:
            return comp[sq]
        near = [comp[(sq[0] + dx, sq[1] + dy)] for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
                if (sq[0] + dx, sq[1] + dy) in comp]
        return near[0] if near else None
    xs = [p[0] for p in walk] or [0]
    ys = [p[1] for p in walk] or [0]
    spans = info.get("spans", {})

    def in_span(side, along):
        lo, hi = spans.get(side, (0, 10 ** 6))
        return lo <= along < hi
    on_edge = {"north": lambda p: p[1] == min(ys) and in_span("north", p[0]),
               "south": lambda p: p[1] == max(ys) and in_span("south", p[0]),
               "west": lambda p: p[0] == min(xs) and in_span("west", p[1]),
               "east": lambda p: p[0] == max(xs) and in_span("east", p[1])}
    return {"warp": [part_of((w[0], w[1])) for w in info["warps"]],
            "edge": {side: sorted({comp[p] for p in comp if on_edge[side](p)}) for side in info["edges"]},
            "down": sorted({(comp[sq], comp[land]) for sq, js in jumps.items() for _, land in js
                            if sq in comp and land in comp and comp[sq] != comp[land]}),
            "player": part_of(pos) if pos else None}


class World:
    """Maps learned while playing. Route nodes are (map, part): split maps (Route 2 either side of
    Viridian Forest) are told apart by where each warp lands (the warp's destination index)."""

    def __init__(self, known: Optional[Dict[int, Dict]] = None):
        self.maps: Dict[int, Dict] = dict(known or {})

    def learn(self, read: Read, walk: Optional[Dict] = None) -> Dict:
        info = links(read)
        if self.stale(info):
            return info
        old = self.maps.get(info["map"], {})
        if walk is not None:
            info["parts"] = parts(walk, info, (read(ADDR["x"], 1)[0], read(ADDR["y"], 1)[0]))
        elif old.get("parts") and len(old["parts"]["warp"]) == len(info["warps"]):
            info["parts"] = old["parts"]
        self.maps[info["map"]] = info
        return info

    def stale(self, info: Dict) -> bool:
        """The map id has changed but the header is still the previous map's (read in the middle of a warp):
        the same size, warps and connections as another known map. Such a read is not stored under the new
        id. Size and warps alone are not enough: Route 1 and Route 24 are both 20 x 36 with no warps."""
        return any(m != info["map"] and v.get("width") == info["width"] and v.get("height") == info["height"]
                   and [tuple(w) for w in v.get("warps", [])] == info["warps"]
                   and {k: int(x) for k, x in (v.get("edges") or {}).items()} == info["edges"]
                   for m, v in self.maps.items())

    def _land(self, dest: int, how: Tuple, dest_warp: Optional[int]) -> Tuple:
        """The (map, part) node where a hop lands; part None when that map's parts are unknown."""
        info = self.maps.get(dest)
        if not info or not info.get("parts"):
            return (dest, None)
        if how[0] == "warp":
            wp = info["parts"]["warp"]
            return (dest, wp[dest_warp] if dest_warp is not None and dest_warp < len(wp) else None)
        side_parts = info["parts"]["edge"].get(OPPOSITE[how[1]], [])
        return (dest, side_parts[0] if len(side_parts) == 1 else None)

    def downhill(self, m: int, part: int) -> set:
        """The parts of map `m` reachable from `part`: itself and those below it by ledges (one-way)."""
        down = (self.maps.get(m, {}).get("parts") or {}).get("down") or []
        seen, stack = {part}, [part]
        while stack:
            p = stack.pop()
            for a, b in down:
                if a == p and b not in seen:
                    seen.add(b)
                    stack.append(b)
        return seen

    def hops(self, node: Tuple) -> List[Tuple[Tuple, Tuple]]:
        m, part = node
        info = self.maps.get(m)
        if not info:
            return []
        pr = info.get("parts")
        ok = self.downhill(m, part) if part is not None else set()
        out = []
        for side, dest in info["edges"].items():
            if part is None or not pr or ok & set(pr["edge"].get(side, [])):
                out.append((self._land(dest, ("edge", side), None), ("edge", side)))
        for i, w in enumerate(info["warps"]):
            x, y, dest = w[0], w[1], w[2]
            dest_warp = w[3] if len(w) > 3 else None
            if dest == 0xFF:
                continue
            if part is None or not pr or self.warp_part(info, i) is None or self.warp_part(info, i) in ok:
                out.append((self._land(dest, ("warp", (x, y)), dest_warp), ("warp", (x, y))))
        return out

    @staticmethod
    def warp_part(info: Dict, i: int) -> Optional[int]:
        """The part of warp `i`; a warp drawn on no walkable square (Rock Tunnel's far exit rows) takes the
        part of its twin, the warp with the same destination (else it would look open from every part)."""
        pr = info["parts"]["warp"]
        if pr[i] is not None:
            return pr[i]
        dest = tuple(info["warps"][i][2:4])
        return next((pr[j] for j, w in enumerate(info["warps"]) if j != i and tuple(w[2:4]) == dest and pr[j] is not None), None)

    def neighbours(self, m: int) -> List[Tuple[int, Tuple]]:
        return [(n[0], how) for n, how in self.hops((m, None))]

    def part_with_warp_to(self, m: int, dest: int) -> Optional[int]:
        """The part of map `m` holding a warp to `dest` (Route 4's far side: where Mt. Moon's exit lands)."""
        info = self.maps.get(m) or {}
        wp = (info.get("parts") or {}).get("warp") or []
        return next((wp[i] for i, w in enumerate(info.get("warps", [])) if w[2] == dest and i < len(wp)), None)

    def explore(self, start: int, area, first_hop_ok=None, start_part: Optional[int] = None) -> Optional[List[Tuple[int, Tuple]]]:
        """The route to the nearest map of `area` not visited yet (a cave floor): visiting it teaches its
        links. Other unvisited maps (a Pokémon Center next to the cave) are never targets."""
        return self.route(start, -1, first_hop_ok, start_part, unknown=area if area is ANY_MAP else set(area))

    def route(self, start: int, goal: int, first_hop_ok=None, start_part: Optional[int] = None,
              goal_part: Optional[int] = None, unknown=None) -> Optional[List[Tuple[int, Tuple]]]:
        """[(next_map, how)] from start (in `start_part`) to goal (in `goal_part`, if given) over the maps
        learned so far, or None. `first_hop_ok(how)` further filters the hops out of the start (e.g.
        reachable from the player). With `unknown` (a set of maps), the goal is any of them not learned
        yet."""
        if start == goal and first_hop_ok is None and goal_part is None:
            return []
        begin = ("start", start_part)
        prev = {begin: None}
        q = deque([begin])
        while q:
            node = q.popleft()
            here = (start, start_part) if node == begin else node
            for nxt, how in self.hops(here):
                if node == begin and first_hop_ok and not first_hop_ok(how):
                    continue
                key = nxt if nxt[1] is not None else (nxt[0], None)
                if key in prev or (key == (start, None) and goal != start):
                    # back into the start map at an unknown part (an edge strip spanning two parts): every one of
                    # its hops would look open, though the player's own part has no way out
                    continue
                prev[key] = (node, how)
                reached = key[0] == goal and (goal_part is None or key[1] is not None and goal_part in self.downhill(goal, key[1]))
                if (key[0] not in self.maps and key[0] in unknown) if unknown else reached:
                    path, cur = [], key
                    while prev[cur]:
                        pnode, phow = prev[cur]
                        path.append((cur[0], phow))
                        cur = pnode
                    return list(reversed(path))
                q.append(key)
        return None


def hop_target(info: Dict, how: Tuple, pos: Tuple[int, int]) -> Tuple[int, int]:
    """Where to walk for one hop: onto the warp, or just past the map edge in line with the player."""
    kind, val = how
    if kind == "warp":
        return val
    x, y = pos
    return {"north": (x, -1), "south": (x, info["height"]), "west": (-1, y), "east": (info["width"], y)}[val]
