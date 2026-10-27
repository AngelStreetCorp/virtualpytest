"""Pokémon Blue showcase library (TASK-33 phase 4): memory decoding, the ROM table finder and the battle
options, on synthetic bytes only. No ROM, no emulator.

Run: pytest tests/shared/test_pokemon.py -v
"""
import os
import sys
import time
import types

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from shared.src.lib.game.pokemon import battle, learn  # noqa: E402
from shared.src.lib.game.pokemon import milestones as M  # noqa: E402
from shared.src.lib.game.pokemon.memory import ADDR, decode, text_box, text_box_open  # noqa: E402
from shared.src.lib.game.pokemon.rom import MOVES_SIGNATURE, TYPES_SIGNATURE, GameData  # noqa: E402


def _rom():
    """A fake ROM holding a move table and a type chart at made-up offsets."""
    rom = bytearray(0x4000)
    moves = bytearray(6 * 165)
    moves[0:9] = MOVES_SIGNATURE                                  # 1 Pound, 2 Karate Chop (start)
    moves[6 * 32:6 * 33] = bytes([0x21, 0x00, 35, 0x00, 242, 35])  # 33 Tackle: 35 power, Normal, 95 %
    moves[6 * 44:6 * 45] = bytes([0x2D, 0x12, 0, 0x00, 255, 40])   # 45 Growl: status move
    moves[6 * 21:6 * 22] = bytes([0x16, 0x00, 35, 0x16, 255, 10])  # 22 Vine Whip: Grass
    moves[6 + 4] = 255                                             # 2 Karate Chop: 100 % accuracy
    moves[6 * 72:6 * 73] = bytes([0x49, 0x54, 0, 0x16, 229, 10])   # 73 Leech Seed: Grass status
    moves[6 * 74:6 * 75] = bytes([0x4B, 0x00, 55, 0x16, 242, 25])  # 75 Razor Leaf: 55 power, Grass, 95 %
    moves[6 * 76:6 * 77] = bytes([0x4D, 0x42, 0, 0x03, 255, 35])   # 77 Poison Powder: Poison status
    rom[0x1000:0x1000 + len(moves)] = moves
    chart = bytes(TYPES_SIGNATURE) + bytes([0x16, 0x15, 20, 0x15, 0x16, 5, 0xFF])  # + Grass>Water, Water<Grass
    rom[0x3000:0x3000 + len(chart)] = chart
    return bytes(rom)


def test_game_data_is_found_and_decoded():
    data = GameData(_rom())
    assert data.moves_at == 0x1000 and data.types_at == 0x3000
    assert data.move(33)["power"] == 35 and data.move(33)["accuracy"] == 95
    assert data.effectiveness(0x14, [0x16, 0x03]) == 2.0     # Fire vs Grass/Poison
    assert data.effectiveness(0x16, [0x15, 0x15]) == 2.0     # a single type counts once
    assert data.effectiveness(0x00, [0x16, 0x03]) == 1.0


class _Mem:
    def __init__(self):
        self.m = bytearray(0x10000)

    def read(self, addr, n=1):
        return list(self.m[addr:addr + n])

    def mon(self, base, species, hp, types, level, stats, moves, pp):
        self.m[base] = species
        self.m[base + 1:base + 3] = hp.to_bytes(2, "big")
        self.m[base + 5:base + 7] = bytes(types)
        self.m[base + 8:base + 12] = bytes(moves)
        self.m[base + 14] = level
        for i, s in enumerate(stats):
            self.m[base + 15 + 2 * i:base + 17 + 2 * i] = s.to_bytes(2, "big")
        self.m[base + 25:base + 29] = bytes(pp)


def test_battle_options_have_facts_and_the_heuristic_picks_damage():
    mem, data = _Mem(), GameData(_rom())
    mem.m[ADDR["in_battle"]] = 1
    mem.mon(ADDR["battle_mon"], 0x99, 20, [0x16, 0x03], 5, [20, 11, 11, 10, 12], [33, 45, 22, 0], [35, 40, 10, 0])
    mem.mon(ADDR["enemy_mon"], 0xB1, 18, [0x15, 0x15], 5, [18, 10, 11, 10, 10], [33, 0, 0, 0], [35, 0, 0, 0])
    opts = battle.options(mem.read, data)
    ids = [o["id"] for o in opts]
    assert ids == ["move1", "move2", "move3", "run"]             # wild battle: run is an option
    vine = next(o for o in opts if o["id"] == "move3")["facts"]
    assert vine["effectiveness"] == 2.0 and vine["type"] == "Grass"
    assert next(o for o in opts if o["id"] == "move2")["facts"]["status_move"]
    assert battle.heuristic_choice(opts) == "move3"              # super effective + same type
    mem.m[ADDR["battle_mon"] + 25 + 2] = 0                       # no PP left on Vine Whip
    assert "move3" not in [o["id"] for o in battle.options(mem.read, data)]


def test_a_text_box_that_never_closes_gets_two_b_presses_on_the_sixtieth_text_tick():
    """BUG-0653: an NPC dialogue that cycles its lines forever (live run: 300 text ticks, zero events, the runner
    never moved). The 60th consecutive text tick emits text_stuck and presses B twice; a tick without a text box resets."""
    mem = _Mem()
    t = ADDR["tilemap"]
    mem.m[t:t + 360] = bytes([0x7F]) * 360
    mem.m[t + 12 * 20], mem.m[t + 17 * 20] = 0x79, 0x7D            # a text box is open for 61 ticks
    r = _runner(mem)
    r.in_intro = lambda: False
    r.learn_tick = lambda: None
    r.overworld_tick = lambda: "overworld"
    assert [r.tick() for _ in range(60)] == ["text"] * 59 + ["text stuck"]
    assert r.io.keys == ["A"] * 59 + ["B", "B"], f"BUG-0653: two B presses on the 60th text tick, got {r.io.keys!r}"
    assert [e["ticks"] for e in r.log if e["kind"] == "text_stuck"] == [60]
    assert r.text_ticks == 0, "BUG-0653: the count starts again after the B presses"
    assert r.tick() == "text" and r.text_ticks == 1
    mem.m[t + 12 * 20], mem.m[t + 17 * 20] = 0x7F, 0x7F            # the text box closes
    assert r.tick() == "overworld"
    assert r.text_ticks == 0


def test_text_box_and_decoding():
    mem = _Mem()
    t = ADDR["tilemap"]
    mem.m[t:t + 360] = bytes([0x7F]) * 360                      # blank tiles are spaces in the game
    mem.m[t + 12 * 20], mem.m[t + 17 * 20] = 0x79, 0x7D
    for i, b in enumerate([0x82, 0x87, 0x84, 0x8D, 0x9C]):        # "CHEN:"
        mem.m[t + 14 * 20 + 1 + i] = b
    assert text_box_open(mem.read) and text_box(mem.read) == "CHEN:"
    assert decode([0x80, 0x80, 0x50, 0x80]) == "AA"
    assert battle.keys_to_menu_item(1, 3) == ["DOWN", "DOWN"] and battle.keys_to_menu_item(3, 1) == ["UP", "UP"]


def test_option_text_reads_like_facts():
    move = {"id": "move3", "kind": "move", "slot": 3, "facts": {"type": "Grass", "power": 35, "accuracy_pct": 100,
            "pp_left": 10, "effectiveness": 2.0, "expected_damage": 9.1, "expected_ko": True, "status_move": False}}
    text = battle.option_text(move)
    assert "Grass" in text and "x2" in text and "knocks the enemy out" in text
    assert battle.option_text({"id": "run", "kind": "run", "facts": {}}).startswith("Run away")


def test_astar_goes_around_obstacles_and_stops_next_to_a_blocked_goal():
    from shared.src.lib.game.pokemon import overworld
    walk = {(x, y): True for x in range(6) for y in range(6)}
    for x in range(1, 5):
        walk[(x, 2)] = False                       # a table across the room
    path = overworld.astar(walk, (2, 1), (2, 4))
    assert path is not None and len(path) == 7      # around the end of the table
    walk[(5, 5)] = False                            # e.g. a door square drawn as blocked
    assert overworld.astar(walk, (5, 3), (5, 5)) == ["DOWN", "DOWN"]
    # off-screen goal: head for the closest reachable square
    path = overworld.toward(walk, (0, 0), (0, 20))
    assert path and path[0] == "DOWN"


def test_route_leaves_a_split_map_through_the_other_part():
    from shared.src.lib.game.pokemon.world import World
    # Route 2 (13) has a south part (0) and a north part (1). Warps: (x, y, dest_map, dest_warp).
    # From the south part only the forest's south gate (50) is reachable; the north edge (Pewter, 2)
    # belongs to the north part, which the forest's north gate (47) leads back to.
    w = World({
        13: {"edges": {"north": 2, "south": 1}, "warps": [(5, 40, 50, 1), (4, 10, 47, 0)], "width": 20, "height": 72,
             "parts": {"warp": [0, 1], "edge": {"north": [1], "south": [0]}}},
        50: {"edges": {}, "warps": [(5, 0, 51, 1), (4, 7, 13, 0)], "width": 10, "height": 8,
             "parts": {"warp": [0, 0], "edge": {}}},
        51: {"edges": {}, "warps": [(1, 0, 47, 1), (15, 47, 50, 0)], "width": 34, "height": 48,
             "parts": {"warp": [0, 0], "edge": {}}},
        47: {"edges": {}, "warps": [(4, 0, 13, 1), (4, 7, 51, 0)], "width": 10, "height": 8,
             "parts": {"warp": [0, 0], "edge": {}}},
    })
    in_south_part = lambda how: how in (("edge", "south"), ("warp", (5, 40)))  # what the player can reach
    route = w.route(13, 2, first_hop_ok=in_south_part)
    assert [m for m, _ in route] == [50, 51, 47, 13, 2]
    assert route[-1][1] == ("edge", "north")
    # the gate's south door lands back in the south part, so it is no shortcut
    assert w.route(13, 2, first_hop_ok=lambda how: how == ("warp", (5, 40)))[1][0] == 51


def test_strategy_applies_an_llm_answer_and_falls_back_without_one():
    from shared.src.lib.game.pokemon import strategy
    snap = {"milestone": "boulder_badge", "goal": "Beat Brock", "party": [{"name": "BULBIZARRE", "level": 12}],
            "money": 397, "badges": 0}
    memo = {}
    answer = '```json\n{"plan": "Train to 13 for Vine Whip", "lessons": ["Normal moves are weak on Rock"], "train_to_level": 13, "reason": "type advantage"}\n```'
    d = strategy.update(memo, "defeat at boulder_badge", snap, complete=lambda p, s: answer)
    mem = strategy.memory(memo)
    assert d["source"] == "llm" and mem["rules"]["train_to_level"] == 13 and mem["lessons"] == ["Normal moves are weak on Rock"]
    assert "defeat at boulder_badge" in mem["journal"][-1]
    # the same lesson twice is kept once; no LLM answer -> fallback (+2 levels after a defeat)
    d = strategy.update(memo, "defeat at boulder_badge", snap, complete=lambda p, s: "not json")
    assert d["source"] == "fallback" and mem["rules"]["train_to_level"] == 14
    assert "Lessons so far: Normal moves are weak on Rock" in strategy.prompt("x", snap, memo)


def test_move_names_fall_back_to_ids_without_a_names_table():
    data = GameData(_rom())          # the fake ROM is too short to hold the names table
    assert data.move_name(33) == "move 33"


def test_game_report_sums_ai_usage_and_times_events_on_the_video():
    import json, re
    from shared.src.lib.game.pokemon import report
    events = [
        {"kind": "strategy", "t": 100.5, "prompt": "p", "answer": "a", "usage": {"prompt_tokens": 500, "completion_tokens": 90}},
        {"kind": "battle_choice", "t": 110.0, "instructions": "i", "usage": {"input_tokens": 300, "output_tokens": 5}, "cost": 0.0001},
        {"kind": "battle_choice", "t": 120.0, "choice_name": "CHARGE"},       # heuristic: no AI call
        {"kind": "tick", "t": 121.0},                                          # not shown in the report
    ]
    tot = report.totals(events)
    assert tot == {"tokens_in": 800, "tokens_out": 95, "cost": 0.0001, "ai_calls": 2, "battle_decisions": 2}
    page = report.build_html(events, b"\x1a\x45\xdf\xa3", "video/webm", 100.0, {"end_milestone": "route3"}, video_end=130.0)
    data = json.loads(re.search(r"const D = (\{.*?\}), SEG", page, re.S).group(1))
    (seg,) = data["segments"]
    assert seg["src"] == "data:video/webm;base64,GkXfow==" and seg["dur"] == 30.0
    assert seg["marks"] == [[0.5, "strategy"], [10.0, "battle_choice"], [20.0, "battle_choice"]]
    assert len(seg["events"]) == 3


def test_series_chains_the_runs_and_serves_only_segment_files(tmp_path):
    import json, re, threading, urllib.request, urllib.error
    from shared.src.lib.game.pokemon import series
    for stamp, t0, ms in (("20261002-100000", 1000.0, "route3"), ("20261002-110000", 5000.0, "mt_moon")):
        (tmp_path / f"{stamp}.webm").write_bytes(b"0123456789")
        series.save_run(str(tmp_path), stamp, [{"kind": "milestone", "t": t0 + 5, "id": ms, "goal": "g"}],
                        {"start": t0, "end": t0 + 60}, {"start_milestone": ms, "end_milestone": ms, "badges": 1})
    (tmp_path / "state_latest.json").write_text("{}")      # private files next to the runs are never served
    runs = series.load_runs(str(tmp_path))
    assert [r["stamp"] for r in runs] == ["20261002-100000", "20261002-110000"]
    data = json.loads(re.search(r"const D = (\{.*?\}), SEG", series.build_series(runs), re.S).group(1))
    assert [(s["offset"], s["dur"], s["events_url"]) for s in data["segments"]] == \
        [(0.0, 60.0, "20261002-100000.json"), (60.0, 60.0, "20261002-110000.json")]
    assert data["summary"]["start_milestone"] == "route3" and data["summary"]["end_milestone"] == "mt_moon"
    srv = series.SeriesServer(str(tmp_path), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        req = urllib.request.Request(base + "20261002-100000.webm", headers={"Range": "bytes=2-4"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 206 and r.read() == b"234" and r.headers["Content-Range"] == "bytes 2-4/10"
        for bad in ("state_latest.json", "..%2Fstate_latest.json"):
            try:
                urllib.request.urlopen(base + bad)
                assert False, bad
            except urllib.error.HTTPError as e:
                assert e.code == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_rom_tables_for_ledges_and_cave_tile_pairs():
    from shared.src.lib.game.pokemon import overworld
    rom = bytearray(0x200)
    ledges = [0x00, 0x2C, 0x37, 0x80, 0x08, 0x2C, 0x27, 0x20, 0x0C, 0x2C, 0x0D, 0x10, 0xFF]
    pairs = [0x11, 0x20, 0x05, 0x11, 0x41, 0x05, 0x03, 0x30, 0x2E, 0xFF]
    rom[0x40:0x40 + len(ledges)] = bytes(ledges)
    rom[0x100:0x100 + len(pairs)] = bytes(pairs)
    assert overworld.ledge_table(bytes(rom)) == {(0x2C, 0x37): "DOWN", (0x2C, 0x27): "LEFT", (0x2C, 0x0D): "RIGHT"}
    tp = overworld.tile_pairs(bytes(rom))
    assert (0x11, 0x20, 0x05) in tp and (0x11, 0x05, 0x20) in tp and (0x03, 0x2E, 0x30) in tp


def test_astar_jumps_ledges_one_way_and_respects_walls():
    from shared.src.lib.game.pokemon import overworld
    walk = overworld.Grid({(x, y): y != 2 for x in range(3) for y in range(5)})   # row 2: a ledge line
    walk.jumps = {(1, 1): [("DOWN", (1, 3))]}
    assert overworld.astar(walk, (1, 0), (1, 4)) == ["DOWN", "DOWN", "DOWN"]   # walk, jump, walk
    assert overworld.astar(walk, (1, 4), (1, 0)) is None                       # no way back up
    assert (1, 3) in overworld.reachable(walk, (1, 0)) and (1, 1) not in overworld.reachable(walk, (1, 4))
    open_room = overworld.Grid({(x, y): True for x in range(3) for y in range(3)})
    open_room.walls = {((0, 0), (1, 0)), ((1, 0), (0, 0)), ((0, 1), (1, 1)), ((1, 1), (0, 1)),
                       ((0, 2), (1, 2)), ((1, 2), (0, 2))}                      # raised ground: column 0 apart
    assert overworld.astar(open_room, (0, 0), (2, 0)) is None


def test_parts_follow_edge_strips_and_ledges_go_downhill_only():
    from shared.src.lib.game.pokemon import overworld
    from shared.src.lib.game.pokemon.world import World, parts
    # a 6 x 4 map: west room (x 0-1) and east room (x 3-5) apart (column 2 is rock), except a ledge
    # from the east room down into the west one, (3, 1) -> (1, 1)
    walk = overworld.Grid({(x, y): x != 2 for x in range(6) for y in range(4)})
    walk.jumps = {(3, 1): [("LEFT", (1, 1))]}
    info = {"edges": {"south": 9}, "spans": {"south": [0, 2]}, "warps": [(5, 0, 7, 0)]}
    pr = parts(walk, info, pos=(4, 2))
    west, east = pr["warp"][0] ^ 1, pr["warp"][0]
    assert pr["edge"]["south"] == [west]                 # only the strip x 0-1 leads to map 9
    assert [tuple(d) for d in pr["down"]] == [(east, west)]
    assert pr["player"] == east
    w = World({8: {**info, "parts": pr, "width": 6, "height": 4}})
    assert [m for m, _ in w.route(8, 9, start_part=east)] == [9]      # down the ledge, out the south strip
    assert w.route(8, 7, start_part=west) is None                     # the east warp is up a ledge


def test_explore_targets_unvisited_maps_of_the_area_only():
    from shared.src.lib.game.pokemon.world import World
    # cave 1F (59) has a ladder to B1F (60, unvisited) and a door to a Pokémon Center (68, unvisited)
    w = World({59: {"edges": {}, "warps": [(5, 5, 60, 0), (14, 35, 68, 0)], "parts": {"warp": [0, 0], "edge": {}}}})
    assert w.explore(59, (59, 60, 61), start_part=0) == [(60, ("warp", (5, 5)))]
    assert w.explore(59, (59, 61), start_part=0) is None
    assert w.part_with_warp_to(59, 68) == 0


def test_a_route_does_not_re_enter_the_start_map_at_an_unknown_part():
    from shared.src.lib.game.pokemon.world import World
    # Cerulean (3): the player's part 0 reaches the north edge only; the south edge (to Route 5, 16) is in part 4.
    # Route 24 (35) returns to a north strip that spans parts 0 and 1: the landing part is unknown, which
    # must not make every hop of Cerulean look open.
    w = World({
        3: {"edges": {"north": 35, "south": 16}, "warps": [],
            "parts": {"warp": [], "edge": {"north": [0, 1], "south": [4]}, "down": []}},
        35: {"edges": {"south": 3}, "warps": [], "parts": {"warp": [], "edge": {"south": [0]}, "down": []}},
    })
    assert w.route(3, 16, first_hop_ok=lambda how: how == ("edge", "north"), start_part=0) is None
    assert [m for m, _ in w.route(3, 16, start_part=4)] == [16]


def test_a_route_does_not_leave_the_start_part_and_come_back_past_its_first_hop_filter():
    from shared.src.lib.game.pokemon.world import World
    # BUG-0644: the player is in Cerulean's part 0 and may not take the west edge (the first-hop filter). Their only
    # hop is the door (27,11) into house 62, whose other door leads back into part 0 of the same map, where the
    # west edge is open again: a route through the house must not get round the filter (the stall went 3 <-> 62).
    w = World({
        3: {"edges": {"west": 15}, "warps": [(27, 11, 62, 0)], "parts": {"warp": [0], "edge": {"west": [0]}, "down": []}},
        62: {"edges": {}, "warps": [(2, 7, 3, 0), (3, 0, 3, 0)], "parts": {"warp": [0, 0], "edge": {}, "down": []}},
        15: {"edges": {"east": 3, "north": 99}, "warps": [], "parts": {"warp": [], "edge": {"east": [0], "north": [0]}, "down": []}},
    })
    assert [m for m, _ in w.route(3, -1, start_part=0, unknown={99})] == [15, 99]
    assert w.route(3, -1, lambda how: how == ("warp", (27, 11)), start_part=0, unknown={99}) is None


def test_a_warp_on_no_walkable_square_takes_its_twins_part():
    from shared.src.lib.game.pokemon.world import World
    # Rock Tunnel 1F: the far exit's second row is drawn on no walkable square (part None); it must not be
    # a way out of the north part just because its part is unknown
    info = {"warps": [(15, 3, 21, 1), (15, 33, 21, 2), (15, 35, 21, 2)], "parts": {"warp": [10, 37, None], "edge": {}}}
    assert World.warp_part(info, 2) == 37 and World.warp_part(info, 0) == 10
    w = World({82: {"edges": {}, **info, "width": 40, "height": 36}, 21: {"edges": {}, "warps": [], "width": 20, "height": 36}})
    assert [how for _, how in w.hops((82, 10))] == [("warp", (15, 3))]


def test_a_header_read_in_the_middle_of_a_warp_is_not_stored_under_the_new_map():
    from shared.src.lib.game.pokemon.world import World
    w = World({3: {"width": 40, "height": 36, "edges": {}, "warps": [(27, 11, 62, 0)]}})
    stale = {"map": 62, "width": 40, "height": 36, "edges": {}, "warps": [(27, 11, 62, 0)]}
    assert w.stale(stale)                                         # the new id, Cerulean's header
    assert not w.stale({**stale, "map": 3})                       # a re-read of the same map
    assert not w.stale({**stale, "map": 62, "warps": [(3, 7, 3, 0)]})   # a real house


def test_battle_status_flee_and_english_move_names():
    from shared.src.lib.game.pokemon import names
    assert battle.status_name(0x02) == "asleep" and battle.status_name(0x08) == "poisoned" and battle.status_name(0) == ""
    run = {"id": "run", "kind": "run", "facts": {"levels_below": 12}}
    tackle = {"id": "move1", "kind": "move", "facts": {"expected_damage": 20.0}}
    assert battle.heuristic_choice([tackle, run], travelling=True) == "run"      # a Zubat 12 levels below
    assert battle.heuristic_choice([tackle, run], travelling=False) == "move1"   # training: fight it
    assert "little experience" in battle.option_text(run)
    assert names.move_en(22) == "Vine Whip" and names.move_en(33) == "Tackle" and len(names.MOVES_EN) == 165


def test_battle_outcome_covers_fled_lost_and_won():
    # fled: last choice was run, party still has HP; lost: party HP is 0; won otherwise
    assert battle.outcome(fled=True, party_hp_left=12) == "fled"
    assert battle.outcome(fled=False, party_hp_left=1) == "won"
    assert battle.outcome(fled=True, party_hp_left=0) == "lost"   # lost wins over fled
    assert battle.outcome(fled=False, party_hp_left=0) == "lost"


def test_jev_choose_logs_with_refs_and_returns_decision_id(monkeypatch):
    """jev_choose should call decisions.choose(log=True, refs=...) and surface decision_id."""
    from types import SimpleNamespace
    _import_game_pokemon(monkeypatch)
    from test_scripts.game import game_pokemon
    captured = {}

    def fake_choose(resolution, *, state, options, instructions, log, refs=None):
        captured.update(log=log, refs=refs, state=state, options=options, instructions=instructions)
        return {"success": True, "choice": "move1", "confidence": 0.7, "probabilities": {"move1": 0.7},
                "usage": {"input_tokens": 1, "output_tokens": 1}, "cost": 0.0, "ms": 5,
                "model": "jev-test", "decision_id": "dec-42"}

    def fake_resolve(profile, usage, team_id):
        return SimpleNamespace(team_id=team_id)

    from shared.src.lib.ai import decisions, router
    from shared.src.lib.game.ai_usage import AiUsage
    monkeypatch.setattr(decisions, "choose", fake_choose)   # attributes, not sys.modules: the package caches them
    monkeypatch.setattr(router, "resolve_profile", fake_resolve)
    refs = {"game": "pokemon", "save": "latest", "script_result_id": "x"}
    chooser = game_pokemon.jev_choose("team-1", refs, AiUsage("game_pokemon"))
    out = chooser("the state", [{"id": "move1", "facts": "f"}], "pick one")
    assert out["choice"] == "move1" and out["decision_id"] == "dec-42"
    assert captured["log"] is True and captured["refs"] == refs
    first_save = captured["refs"]["save"]
    # the first call already snapshotted a copy of refs; mutating refs after that does not change it
    refs["save"] = "mutated"
    chooser("the state", [{"id": "move1", "facts": "f"}], "pick one")
    assert first_save == "latest"
    assert captured["refs"]["save"] == "mutated"


def test_flash_choose_pins_the_free_profile_for_the_decision_calls(monkeypatch):
    """The volume lane must decide on MiniMax M3.1 Flash (free): the chooser pins the flash profile
    for text.decision, so no route and no paid fallback can serve the battles of a free run."""
    from types import SimpleNamespace
    _import_game_pokemon(monkeypatch)
    from test_scripts.game import game_pokemon
    captured = {}

    def fake_choose(resolution, *, state, options, instructions, log, refs=None):
        captured.update(resolution=resolution)
        return {"success": True, "choice": "move1", "confidence": 0.6, "probabilities": {"move1": 0.6},
                "usage": {"input_tokens": 1, "output_tokens": 1}, "cost": 0.0, "ms": 5,
                "model": "MiniMax-M3.1-Flash-Preview", "decision_id": "dec-7"}

    def fake_resolve(profile, usage, team_id):
        captured.update(profile=profile, usage=usage, team_id=team_id)
        return SimpleNamespace(team_id=team_id)

    from shared.src.lib.ai import decisions, router
    from shared.src.lib.game.ai_usage import AiUsage
    monkeypatch.setattr(decisions, "choose", fake_choose)
    monkeypatch.setattr(router, "resolve_profile", fake_resolve)
    chooser = game_pokemon.flash_choose("team-1", {"game": "pokemon"}, AiUsage("game_pokemon"))
    out = chooser("the state", [{"id": "move1", "facts": "f"}], "pick one")
    assert captured["profile"] == "minimax-m3-1-flash" and captured["usage"] == "text.decision"
    assert out["choice"] == "move1" and out["decision_id"] == "dec-7"
    # the flash chooser is one of the model choosers: the runner attaches the battle outcomes to its decisions
    assert "flash" in game_pokemon.CHOOSERS and "jev" in game_pokemon.CHOOSERS
    assert "heuristic" not in game_pokemon.CHOOSERS      # the heuristic calls no model


def test_outcome_writer_calls_set_outcome_and_swallows_errors(monkeypatch, capsys):
    """outcome_writer must call decisions.set_outcome for each non-empty id and never raise."""
    _import_game_pokemon(monkeypatch)
    from test_scripts.game import game_pokemon
    calls = []

    def fake_set_outcome(did, team_id, outcome):
        calls.append((did, team_id, outcome))
        if did == "boom":
            raise RuntimeError("db down")
        return True

    from shared.src.lib.ai import decisions
    monkeypatch.setattr(decisions, "set_outcome", fake_set_outcome)
    fn = game_pokemon.outcome_writer("team-1")
    fn(["d1", "", None, "d2"], {"result": "won", "turns": 3, "battle": "wild", "by": "game"})
    assert [c[0] for c in calls] == ["d1", "d2"]
    fn(["boom"], {"result": "lost", "turns": 1, "battle": "trainer", "by": "game"})
    assert "warning: set_outcome failed for boom: db down" in capsys.readouterr().out


def _import_game_pokemon(monkeypatch):
    """game_pokemon.py imports script_decorators, which transitively pulls in psutil; stub the heavy
    device/executor modules before importing it from a test environment without the device runtime."""
    monkeypatch.setitem(sys.modules, "shared.src.lib.executors",
                        types.ModuleType("shared.src.lib.executors"))
    sd_mod = types.ModuleType("shared.src.lib.executors.script_decorators")
    sd_mod.script = lambda *a, **kw: (lambda f: f)
    sd_mod.get_context = lambda: types.SimpleNamespace()
    sd_mod.get_args = lambda: types.SimpleNamespace()
    sd_mod.get_device = lambda: types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "shared.src.lib.executors.script_decorators", sd_mod)


def test_runner_battle_end_fires_once_after_in_battle_clears_and_a_blackout_is_lost():
    from shared.src.lib.game.pokemon.runner import PARTY_STRUCT, Runner
    mem, ended = _Mem(), []
    mem.m[ADDR["party_count"]] = 1
    base = ADDR["party_mons"]
    mem.m[base + 1:base + 3] = (20).to_bytes(2, "big")
    r = object.__new__(Runner)
    r.io, r.memo, r.log, r.disabled, r._last_tick = types.SimpleNamespace(wait=lambda ms: None), {}, [], None, 0.0
    r.read, r.money, r.in_intro, r.overworld_tick = mem.read, (lambda: 0), (lambda: False), (lambda: "overworld")
    r.on_battle_end = lambda ids, out: ended.append((ids, out))
    r.battle_ids, r.battle_turns, r.battle_kind, r.last_choice_kind, r.battle_wiped = ["d1", "d2"], 2, "wild", "move", False

    mem.m[ADDR["in_battle"]] = 1
    r.battle_tick = lambda: "battle"
    assert r.tick() == "battle" and not ended          # still in battle: nothing fires
    mem.m[base + 1:base + 3] = (0).to_bytes(2, "big")
    r.tick()                                           # the party is wiped while the battle is on
    mem.m[base + 1:base + 3] = (20).to_bytes(2, "big")  # then the Pokémon Center heals it
    mem.m[ADDR["in_battle"]] = 0
    r.tick(), r.tick()
    assert len(ended) == 1 and ended[0][0] == ["d1", "d2"] and ended[0][1]["result"] == "lost"
    assert r.battle_turns == 0 and not r.battle_wiped


def test_battle_state_survives_a_json_round_trip_so_a_resumed_run_finishes_the_battle():
    """A run that ends mid-battle saves the battle state in its memo. The next run, built from
    `json.loads` of that memo, finishes the battle: `on_battle_end` is called with the decision
    ids that the first run stashed (and never did)."""
    import json
    from shared.src.lib.game.pokemon.runner import Runner

    def fresh(ended):
        mem = _Mem()
        mem.m[ADDR["party_count"]] = 1
        base = ADDR["party_mons"]
        mem.m[base + 1:base + 3] = (20).to_bytes(2, "big")
        r = object.__new__(Runner)
        r.io = types.SimpleNamespace(wait=lambda ms: None)
        r.memo = {}
        r.log = []
        r.disabled = None
        r._last_tick = 0.0
        r.read = mem.read
        r.money = (lambda: 0)
        r.in_intro = (lambda: False)
        r.overworld_tick = (lambda: "overworld")
        r.on_battle_end = lambda ids, out: ended.append((ids, out))
        r.battle_tick = lambda: "battle"
        return r, mem

    # First run: a battle is in progress when the time budget runs out
    ended1 = []
    r1, _ = fresh(ended1)
    r1.memo["battle"] = {"ids": ["d1", "d2"], "turns": 2, "kind": "wild", "last": "move", "wiped": False}
    saved = json.dumps(r1.memo)                              # the run saves and ends
    assert ended1 == []                                       # the first run never finished the battle

    # New run: built from the saved memo (a resume). The battle state rides through json.
    ended2 = []
    r2, mem2 = fresh(ended2)
    r2.memo = json.loads(saved)
    mem2.m[ADDR["in_battle"]] = 1
    assert r2.tick() == "battle" and not ended2              # still in battle: no on_battle_end yet
    mem2.m[ADDR["in_battle"]] = 0                            # the battle ends on this run
    r2.tick()
    assert len(ended2) == 1                                   # ...and the saved ids reach on_battle_end
    assert ended2[0][0] == ["d1", "d2"]                       # (the same ids the first run stashed)
    assert ended2[0][1]["result"] == "won"
    assert r2.memo["battle"] == {"ids": [], "turns": 0, "kind": None, "last": None, "wiped": False}


def test_heal_options_states_distances_and_unknown_routes():
    from shared.src.lib.game.pokemon.runner import heal_options
    state, opts = heal_options(25, 67, 12, "Pewter Pokémon Center", 3, "Beat Brock", 2, [9, 10, 8])
    assert "25/67" in state and "PP left 12" in state and "Beat Brock" in state
    assert "9, 10, 8" in state
    ids = [o["id"] for o in opts]
    assert "heal" in ids and "push" in ids
    heal = next(o for o in opts if o["id"] == "heal")["facts"]
    push = next(o for o in opts if o["id"] == "push")["facts"]
    assert "Pewter Pokémon Center" in heal and "3 map(s) away" in heal
    assert "5 maps of travel" in heal                    # heal_maps (3) + goal_maps (2)
    assert "2 map(s) away" in push
    assert "HP 25/67" in push and "12 attacking PP" in push
    assert "halves the money" in push
    # a route unknown on either side renders "unknown" without raising
    state2, opts2 = heal_options(25, 67, 12, "Pewter Pokémon Center", None, "Beat Brock", None, [])
    heal2 = next(o for o in opts2 if o["id"] == "heal")["facts"]
    push2 = next(o for o in opts2 if o["id"] == "push")["facts"]
    assert "unknown" in heal2 and "unknown" in push2


def test_decide_heal_asks_once_per_situation():
    """The decide_heal factor: 'rule' without a chooser; forced HP/0 PP returns 'heal' with no chooser call;
    the same key caches the answer; a different key asks again."""
    from shared.src.lib.game.pokemon.runner import HEAL_FORCED_BELOW, Runner

    class _FakeWorld:
        """A world that knows a 3-hop route from map 0x01 to a Pokémon Center (0x3A)."""
        def __init__(self):
            self.maps = {1: {"map": 1, "width": 20, "height": 20}}
            self._routes = {(1, 0x3A): [(2, ("edge", "south")), (3, ("edge", "south")), (0x3A, ("edge", "south"))]}

        def route(self, a, b):
            return self._routes.get((a, b))

    def fresh():
        r = object.__new__(Runner)
        r.memo = {"done": []}      # current() walks MILESTONES; mark the bag empty from the start
        r.world = _FakeWorld()
        r.choose = None
        r.on_battle_end = None
        r.log = []
        r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
        r.read = lambda addr, n=1: [0] * n    # bag count 0, no badges, no party, no map change
        return r

    # No chooser: the method says "rule" without calling anything
    r = fresh()
    assert r._decide_heal(25, 100, 10, 1) == "rule"

    # Forced HP: returns "heal" with no chooser call
    calls = []
    r.choose = lambda s, o, i: (calls.append(1) or {"choice": "push"})
    forced_cur = int(HEAL_FORCED_BELOW * 100) - 1       # < HEAL_FORCED_BELOW
    assert r._decide_heal(forced_cur, 100, 10, 1) == "heal"
    assert calls == []                                  # no chooser call

    # Forced by 0 attacking PP
    r = fresh()
    r.choose = lambda s, o, i: (calls.append(1) or {"choice": "push"})
    assert r._decide_heal(30, 100, 0, 1) == "heal"
    assert calls == []

    # Low but not forced: same situation (same here/cur/PP key) caches; different key asks again
    r = fresh()
    calls.clear()
    r.choose = lambda s, o, i: (calls.append(1) or {"choice": "push", "confidence": 0.6,
                                                   "decision_id": "d1", "model": "m-test"})
    assert r._decide_heal(30, 100, 10, 1) == "push"
    assert r._decide_heal(30, 100, 10, 1) == "push"
    assert r._decide_heal(30, 100, 10, 1) == "push"
    assert len(calls) == 1                              # one call, cached
    # Different cur bucket (cur*10//tot changes): 25*10//100=2 vs 30*10//100=3, a new call
    assert r._decide_heal(25, 100, 10, 1) == "push"
    assert len(calls) == 2
    # Push decision ids are stashed in memo["heal_ids"]
    assert r.memo["heal_ids"] == ["d1", "d1"]


# --- catching, shopping, sending out the next Pokémon (TASK-33) -------------------------------------------

BAG_COUNT, BAG_ITEMS = 0xD31D + 5, 0xD31E + 5


def _wild_battle(party=(0x99,), bag=((0x04, 5),), enemy_species=0xB1, enemy_hp=18):
    """A wild battle with Bulbasaur-like leader, the party species list and the bag in memory."""
    mem = _Mem()
    mem.m[ADDR["in_battle"]] = 1
    mem.mon(ADDR["battle_mon"], 0x99, 20, [0x16, 0x03], 5, [20, 11, 11, 10, 12], [33, 45, 22, 0], [35, 40, 10, 0])
    mem.mon(ADDR["enemy_mon"], enemy_species, enemy_hp, [0x00, 0x00], 5, [18, 10, 11, 10, 10], [33, 0, 0, 0], [35, 0, 0, 0])
    mem.m[ADDR["enemy_mon"] + 7] = 255                           # catch rate
    mem.m[ADDR["party_count"]] = len(party)
    mem.m[ADDR["party_species"]:ADDR["party_species"] + len(party)] = bytes(party)
    mem.m[BAG_COUNT] = len(bag)
    for i, (item, n) in enumerate(bag):
        mem.m[BAG_ITEMS + 2 * i:BAG_ITEMS + 2 * i + 2] = bytes([item, n])
    return mem


def test_catch_option_has_facts_and_is_gated():
    data = GameData(_rom())
    opts = battle.options(_wild_battle().read, data)
    catch = next(o for o in opts if o["kind"] == "catch")
    f = catch["facts"]
    assert catch["id"] == "catch" and f["ball"] == "POKé BALL" and f["balls_left"] == 5
    assert f["enemy_hp_share"] == 1.0 and f["enemy_level"] == 5 and f["catch_rate"] == 255 and f["party_size"] == 1
    assert "Throw a POKé BALL" in battle.option_text(catch)
    assert "estimated catch chance" in battle.option_text(catch)
    ids = lambda mem: [o["id"] for o in battle.options(mem.read, data)]
    assert "catch" not in ids(_wild_battle(bag=()))                                  # no ball
    assert "catch" not in ids(_wild_battle(party=(0x99, 1, 2, 3, 4, 5)))             # party full
    assert "catch" not in ids(_wild_battle(party=(0x99, 0xB1)))                      # species already owned
    assert "catch" in ids(_wild_battle(bag=((0x01, 3), (0x02, 2))))                  # a Hyper Ball will do
    trainer = _wild_battle()
    trainer.m[ADDR["in_battle"]] = 2
    assert "catch" not in ids(trainer)                                               # never in a trainer battle


def test_catch_chance_matches_the_gen1_formula():
    # (a) catch rate 255, full HP 28/28, Poké Ball: f = floor(28*255/12) / max(1, 7) = 595/7 = 85
    #     s = 0, so p_first = 0, p_continue = (min(255, 255) - 0 + 1)/256 = 1.0, p_second = (85+1)/256
    chance_a = battle.catch_chance(255, 28, 28, 0x04)
    expected_a = 0 + (256 / 256) * ((85 + 1) / 256)
    assert 0.3 <= chance_a <= 0.4 and chance_a == round(expected_a, 2)

    # (b) same enemy at HP 1/28: denominator max(1, 0) = 1, f = 595 capped at 255, so p_second = 1.0
    assert battle.catch_chance(255, 1, 28, 0x04) == 1.0

    # (c) Master Ball always catches, regardless of the rest
    assert battle.catch_chance(45, 28, 28, 0x01) == 1.0

    # (d) catch rate 45, full HP, Poké Ball: p_continue = 46/256, p_second = 86/256
    chance_d = battle.catch_chance(45, 28, 28, 0x04)
    expected_d = 0 + (46 / 256) * (86 / 256)
    assert chance_d < 0.1 and chance_d == round(expected_d, 2)

    # (e) asleep adds the 25-point status bonus: p_first = 25/256 (was 0)
    awake = battle.catch_chance(45, 28, 28, 0x04)
    asleep = battle.catch_chance(45, 28, 28, 0x04, status="asleep")
    assert asleep > awake


def test_heuristic_switches_to_a_member_that_hurts_more_and_throws_a_ball_instead_of_a_ko():
    status = {"id": "move1", "kind": "move", "facts": {"expected_damage": 0.0}}
    switch = {"id": "switch", "kind": "switch", "slot": 2, "facts": {"expected_damage": 9.0}}
    assert battle.heuristic_choice([status, switch]) == "switch"
    ko = {"id": "move4", "kind": "move", "facts": {"expected_damage": 30.0, "expected_ko": True}}
    ball = {"id": "catch", "kind": "catch", "ball": 4, "facts": {"party_size": 1, "enemy_hp_share": 1.0, "catch_chance": 0.3}}
    assert battle.heuristic_choice([ko, ball]) == "catch"          # the only damaging move would KO: ball at full HP
    ball["facts"]["catch_chance"] = 0.1
    assert battle.heuristic_choice([ko, ball]) == "move4"          # hopeless odds: just win


def test_send_out_prefers_a_member_with_attacking_pp():
    mem = _wild_battle(party=(0x99, 0x05, 0x10))
    for i, (hp, pp) in enumerate(((30, 0), (20, 0), (10, 7))):
        base = ADDR["party_mons"] + 0x2C * i
        mem.m[base + 8:base + 12] = bytes([33, 0, 0, 0])
        mem.m[base + 0x1D] = pp
        mem.m[base + 1:base + 3] = hp.to_bytes(2, "big")
    assert battle.first_alive(mem.read) == 0                       # without move data: the first alive
    assert battle.first_alive(mem.read, GameData(_rom())) == 2     # with it: the one that can still attack


def test_ball_pick_and_list_cursor():
    items = {0x28: 1, 0x03: 2, 0x04: 5}
    assert battle.ball_to_throw(items) == 0x04 and battle.ball_to_throw({0x03: 1, 0x02: 1}) == 0x03
    assert battle.ball_to_throw({0x04: 0, 0x28: 1}) is None
    assert battle.ball_row(items, 0x04) == 2                                         # the bag keeps its order
    mem = _Mem()
    mem.m[0xCC26], mem.m[0xCC36] = 1, 2                                              # cursor in the window + scroll
    assert battle.list_cursor(mem.read) == 3


def test_heuristic_catches_a_new_species_when_weak_and_weakens_it_first():
    data = GameData(_rom())
    healthy = battle.options(_wild_battle().read, data)
    assert battle.heuristic_choice(healthy) in ("move1", "move3")          # share 1.0: attack, do not throw yet
    weak = battle.options(_wild_battle(enemy_hp=9).read, data)             # share 0.5
    assert battle.heuristic_choice(weak) == "catch"
    assert battle.heuristic_choice(weak, our_hp_share=0.2) == "run"        # our leader first
    # a full team of 3 is not worth the balls: plain attack
    big = battle.options(_wild_battle(party=(0x99, 1, 2), enemy_hp=9).read, data)
    assert battle.heuristic_choice(big) != "catch"
    # a far weaker new species is not skipped while travelling when we want a backup
    lvl = _wild_battle(enemy_hp=18)
    lvl.m[ADDR["battle_mon"] + 14] = 30
    assert battle.heuristic_choice(battle.options(lvl.read, data), travelling=True) != "run"


def test_party_select_screen_and_first_alive_member():
    mem = _Mem()
    t = ADDR["tilemap"]
    mem.m[t:t + 360] = bytes([0x7F]) * 360
    assert not battle.party_select(mem.read)
    row = "Faire combattre"
    for i, c in enumerate(row):
        mem.m[t + 14 * 20 + 1 + i] = (0x80 + ord(c) - 65) if c.isupper() else 0xA0 + ord(c) - 97 if c.islower() else 0x7F
    for i, c in enumerate("quel POKxMON?"):
        mem.m[t + 16 * 20 + 1 + i] = (0x80 + ord(c) - 65) if c.isupper() else 0xA0 + ord(c) - 97 if c.islower() else 0x7F if c == " " else 0xE6
    assert battle.party_select(mem.read)
    mem.m[ADDR["party_count"]] = 3                       # slot 0 and 1 fainted, slot 2 has HP
    for i, hp in enumerate((0, 0, 17)):
        mem.m[ADDR["party_mons"] + 0x2C * i + 1:ADDR["party_mons"] + 0x2C * i + 3] = hp.to_bytes(2, "big")
    assert battle.first_alive(mem.read) == 2
    mem.m[ADDR["party_mons"] + 0x2C * 2 + 2] = 0
    assert battle.first_alive(mem.read) is None


def test_shop_screens_and_ball_count():
    from shared.src.lib.game.pokemon import shop
    blank = ["." * 20] * 18
    rows = lambda **at: [at.get(f"r{i}", blank[i]) for i in range(18)]
    assert shop.screen(blank) == ""
    assert shop.screen(rows(r1="..ACHETER ..  6492..", r3=". VENDRE  ..........")) == "menu"
    assert shop.screen(rows(r1="..ACHETER ..  6492..", r3=". VE.              .", r4="..... POK. BALL    .")) == "list"
    box = rows(r1="..ACHETER ..  6492..", r10="..... A..03    600..")
    assert shop.screen(box) == "quantity" and shop.quantity(box) == 3
    assert shop.screen(rows(r8="..... REPOUSSE..OUI.", r10="..... A..03   . NON.")) == "confirm"
    assert shop.balls_to_buy(1000) == 5 and shop.balls_to_buy(6492) == 10 and shop.balls_to_buy(2500) == 5
    assert shop.balls_to_buy(1100) == 5 and shop.balls_to_buy(400) == 2             # never more than the money buys


class _FakeIO:
    def __init__(self, mem):
        self.mem, self.keys = mem, []

    def read(self, addr, n=1):
        return self.mem.read(addr, n)

    def press(self, key, hold=90):
        self.keys.append(key)

    def wait(self, ms):
        pass


def _runner(mem):
    from shared.src.lib.game.pokemon.runner import Runner
    r = Runner(_FakeIO(mem), _rom())
    return r


def test_runner_wants_balls_only_with_no_balls_small_party_and_money():
    mem = _wild_battle(bag=())
    mem.m[0xD347 + 5:0xD347 + 8] = bytes([0x00, 0x25, 0x00])         # 2500 as BCD
    r = _runner(mem)
    assert r.wants_balls()
    mem.m[BAG_COUNT], mem.m[BAG_ITEMS], mem.m[BAG_ITEMS + 1] = 1, 0x04, 3
    assert not r.wants_balls()                                       # has balls
    mem.m[BAG_COUNT] = 0
    mem.m[ADDR["party_count"]] = 3
    assert not r.wants_balls()                                       # a team of 3
    mem.m[ADDR["party_count"]] = 1
    mem.m[0xD347 + 5:0xD347 + 8] = bytes([0x00, 0x09, 0x50])
    assert not r.wants_balls()                                       # 950 money


def test_send_out_next_moves_the_cursor_to_the_first_alive_member():
    mem = _wild_battle(party=(0x99, 0x05, 0x10))
    for i, hp in enumerate((0, 0, 20)):
        mem.m[ADDR["party_mons"] + 0x2C * i + 1:ADDR["party_mons"] + 0x2C * i + 3] = hp.to_bytes(2, "big")
    r = _runner(mem)
    mem.m[0xCC26] = 0
    assert r.send_out_next() == "battle party" and r.io.keys == ["DOWN"]
    mem.m[0xCC26] = 2
    assert r.send_out_next() == "battle send out" and r.io.keys == ["DOWN", "A"]


def test_attack_pp_is_the_first_pokemon_with_hp_left():
    mem = _wild_battle(party=(0x99, 0x05))
    for i, (hp, pp) in enumerate(((30, 0), (20, 7))):
        base = ADDR["party_mons"] + 0x2C * i
        mem.m[base + 8:base + 12] = bytes([33, 0, 0, 0])
        mem.m[base + 0x1D] = pp
        mem.m[base + 1:base + 3] = hp.to_bytes(2, "big")
    r = _runner(mem)
    assert r.attack_pp() == 0                                        # a backup's PP does not hide the leader's
    mem.m[ADDR["party_mons"] + 1:ADDR["party_mons"] + 3] = bytes(2)
    assert r.attack_pp() == 7                                        # the leader fainted: the next one fights first


def _learner(mem, moves, pps=(5, 5, 5, 5), new=75, index=0):
    """A full-moves Pokémon in the party and the game's learn-a-move question state."""
    base = ADDR["party_mons"] + 0x2C * index
    mem.m[ADDR["party_count"]] = index + 1
    mem.mon(base, 0x09, 40, [0x16, 0x03], 24, [40, 20, 20, 20, 20], moves, [0] * 4)
    mem.m[base + 0x21] = 24
    mem.m[base + 0x1D:base + 0x21] = bytes(pps)
    mem.m[learn.NEW_MOVE], mem.m[learn.LEARNER] = new, index


def _say(mem, text, yes_no=False):
    """Draw the lower text box (two rows of `text` split at '/') and optionally the OUI / NON box."""
    t = ADDR["tilemap"]
    mem.m[t:t + 360] = bytes([0x7F]) * 360
    mem.m[t + 12 * 20], mem.m[t + 17 * 20] = 0x79, 0x7D

    def tiles(row, at, word):
        for i, c in enumerate(word):
            mem.m[t + row * 20 + at + i] = (0x80 + ord(c) - 65) if c.isupper() else 0xA0 + ord(c) - 97 if c.islower() \
                else 0xE6 if c == "?" else 0x7F
    for row, word in zip((14, 16), text.split("/")):
        tiles(row, 1, word)
    if yes_no:
        tiles(8, 15, "OUI")
        tiles(10, 15, "NON")


def test_learn_options_carry_the_facts():
    mem, data = _Mem(), GameData(_rom())
    _learner(mem, [33, 45, 73, 22])
    mon = learn.learner(mem.read, data, ADDR["party_mons"], 0)
    opts = learn.options(mon["moves"], learn.move_facts(data, 75))
    assert [o["id"] for o in opts] == ["keep", "forget1", "forget2", "forget3", "forget4"]
    tackle, growl, seed, whip = (o["facts"] for o in opts[1:])
    assert tackle["only_damaging_of_type"] and whip["only_damaging_of_type"] and not growl["only_damaging_of_type"]
    assert whip["new_covers_its_type"] and not tackle["new_covers_its_type"]
    assert tackle["pp_left"] == 5 and tackle["pp_max"] == 35 and tackle["type"] == "Normal"
    text = learn.option_text(opts[1])
    assert "Tackle" in text and "power 35" in text and "only damaging move of its type" in text and "PP 5/35" in text
    assert learn.option_text(opts[0]).startswith("Do not learn") and "Razor Leaf" in learn.describe("BULBI", mon, opts[0]["facts"]["new"])


def test_learn_options_leave_out_hm_moves():
    mem, data = _Mem(), GameData(_rom())
    _learner(mem, [15, 33, 45, 22])                                  # Cut is an HM: the game refuses to delete it
    mon = learn.learner(mem.read, data, ADDR["party_mons"], 0)
    assert "forget1" not in [o["id"] for o in learn.options(mon["moves"], learn.move_facts(data, 75))]


def _choice(moves, new):
    mem, data = _Mem(), GameData(_rom())
    _learner(mem, moves, new=new)
    mon = learn.learner(mem.read, data, ADDR["party_mons"], 0)
    return learn.heuristic_choice(learn.options(mon["moves"], learn.move_facts(data, new)))


def test_learn_heuristic_protects_the_last_damaging_move_of_a_type():
    assert _choice([33, 45, 73, 22], 75) == "forget2"          # Razor Leaf covers Grass; Growl is the weakest
    assert _choice([33, 22, 73, 45], 75) == "forget3"          # a status move goes before any attack
    assert _choice([33, 22, 75, 45], 77) == "keep"             # a status move is declined
    assert _choice([33, 1, 2, 22], 75) == "forget1"            # Tackle: not alone in Normal, the weakest attack


def test_learn_heuristic_keeps_when_the_new_move_is_weaker():
    assert _choice([1, 2, 22, 75], 33) == "keep"               # Tackle is worth less than all four
    assert _choice([33, 22, 73, 45], 77) == "keep"             # a status move never replaces anything


def test_learn_stage_reads_the_screen():
    mem = _Mem()
    assert learn.stage(mem.read) == ""
    _say(mem, "apprendre/TRANCHxHERBE?")
    assert learn.stage(mem.read) == "wait"                          # typed, the OUI / NON box not drawn yet
    _say(mem, "apprendre/TRANCHxHERBE?", yes_no=True)
    assert learn.stage(mem.read) == "ask"
    _say(mem, "Ne pas apprendre/TRANCHxHERBE?", yes_no=True)
    assert learn.stage(mem.read) == "abandon"
    _say(mem, "Oublier quelle/attaque?")
    assert learn.stage(mem.read) == "list"
    _say(mem, "Donner un surnom/a PARAS?", yes_no=True)
    assert learn.stage(mem.read) == ""                              # the nickname question is not ours


def _learn_runner(moves, new, choose=None):
    mem = _Mem()
    _learner(mem, moves, new=new)
    _say(mem, "apprendre/TRANCHxHERBE?", yes_no=True)
    from shared.src.lib.game.pokemon.runner import Runner
    return mem, Runner(_FakeIO(mem), _rom(), choose=choose)


def test_runner_declines_a_status_move_and_confirms_dropping_it():
    mem, r = _learn_runner([33, 45, 73, 22], 77)
    assert r.learn_tick() == "learn answer"                          # NON: the cursor is on OUI (0), DOWN, A
    assert r.io.keys[-1] == "A" and "DOWN" in r.io.keys
    ev = r.log[-1]
    assert ev["kind"] == "move_learn_choice" and ev["choice"] == "keep" and ev["forgotten"] is None and ev["by"] == "heuristic"
    _say(mem, "Ne pas apprendre/TRANCHxHERBE?", yes_no=True)
    r.io.keys.clear()
    assert r.learn_tick() == "learn answer" and r.io.keys == ["A"]   # OUI: drop the new move
    assert len(r.log) == 1                                            # a repeated question keeps its decision


def test_runner_forgets_the_chosen_move_through_the_list():
    mem, r = _learn_runner([33, 22, 73, 45], 75)
    assert r.learn_tick() == "learn answer" and r.io.keys == ["A"]   # OUI (the cursor starts on it)
    assert r.log[-1]["choice"] == "forget3" and r.log[-1]["forgotten"] == "move 73" and r.log[-1]["new_move"] == "move 75"
    _say(mem, "Oublier quelle/attaque?")
    mem.m[0xCC26] = 0
    r.io.keys.clear()
    assert r.learn_tick() == "learn pick" and r.io.keys == ["DOWN"]
    mem.m[0xCC26] = 2
    assert r.learn_tick() == "learn pick" and r.io.keys == ["DOWN", "A"]


def test_runner_uses_the_chooser_and_ignores_an_unknown_answer():
    seen = []

    def choose(state, options, instructions):
        seen.append((state, [o["id"] for o in options], instructions))
        return {"choice": "forget1", "model": "jev", "confidence": 0.8, "probabilities": {"forget1": 0.8}, "decision_id": "d1"}
    mem, r = _learn_runner([33, 45, 73, 22], 75, choose)
    r.learn_tick()
    assert seen[0][1] == ["keep", "forget1", "forget2", "forget3", "forget4"] and "damaging" in seen[0][2]
    ev = r.log[-1]
    assert ev["choice"] == "forget1" and ev["by"] == "jev" and ev["confidence"] == 0.8 and ev["decision_id"] == "d1"
    assert ev["options"][1]["name"] == "move 33" and ev["state"].startswith("Pokémon Blue.")
    mem2, r2 = _learn_runner([33, 45, 73, 22], 75, lambda *a: {"choice": "forget9"})
    r2.learn_tick()
    assert r2.log[-1]["by"] == "heuristic"                            # a bad answer falls back


def test_learn_waits_for_the_box_and_skips_other_questions():
    mem, r = _learn_runner([33, 45, 73, 22], 75)
    _say(mem, "apprendre/TRANCHxHERBE?")
    assert r.learn_tick() == "learn wait" and r.io.keys == []
    _say(mem, "Donner un surnom/a PARAS?", yes_no=True)
    assert r.learn_tick() is None
    _learner(mem, [33, 45, 73, 0])                                    # a free slot: the game just learns it
    _say(mem, "apprendre/TRANCHxHERBE?", yes_no=True)
    assert r.learn_tick() is None

def test_runner_grid_marks_memo_walls_of_the_current_map_and_leaves_other_maps_alone(monkeypatch):
    """Runner.grid wraps overworld.full_grid and sets the memo['walls'] squares of the current map
    to False; squares in other maps' wall lists stay as-is (the runner is only on one map at a time)."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    fake_grid = overworld.Grid({(x, y): True for x in range(4) for y in range(4)})
    fake_grid.jumps, fake_grid.walls = {}, set()
    monkeypatch.setattr(overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: fake_grid)
    r = object.__new__(runner_mod.Runner)
    r.memo = {"walls": {"1": [[1, 1], [2, 2]], "99": [[99, 99]]}}
    r.read = lambda addr, n=1: [1]                    # current map id = 1
    r.rom = b"\x00"
    out = r.grid()
    assert out is fake_grid                            # the wrapper hands back the same Grid (attributes kept)
    assert out[(1, 1)] is False and out[(2, 2)] is False
    assert out[(0, 0)] is True and out[(3, 3)] is True
    assert out.jumps == {} and out.walls == set()       # the .jumps / .walls attributes are preserved


def test_walk_stops_talking_to_a_blocker_after_three_talks_and_walls_it(monkeypatch):
    """Three talks to the same blocker square add it to memo['walls'] with a npc_walled event and a
    4th call does not talk again (the re-planned walk takes the next step)."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    fake_grid = overworld.Grid({(x, y): True for x in range(4) for y in range(4)})
    fake_grid.jumps, fake_grid.walls = {}, set()
    monkeypatch.setattr(overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: fake_grid)
    monkeypatch.setattr(overworld, "toward", lambda e, a, b: ["RIGHT"])
    monkeypatch.setattr(runner_mod, "links", lambda read: {"warps": []})
    calls = {"talk": 0, "walk_step": 0}

    def fake_astar(grid, start, goal):
        return None                                     # always no path: force the blocker path
    monkeypatch.setattr(overworld, "astar", fake_astar)
    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.log = []
    r.rom = b"\x00"
    r.read = lambda addr, n=1: [42]
    r.pos = lambda: (0, 0)
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    r.blocker_on_the_way = lambda start, target: (1, 0)  # always the same square, next to the player
    r.wakes = lambda blocker: False
    r.talk_at = lambda who: (calls.__setitem__("talk", calls["talk"] + 1) or "talk")

    def fake_step(direction):
        calls["fake_step"] = calls.get("fake_step", 0) + 1
        calls["walk_step"] += 1
        return True
    r.step = fake_step
    r.stuck = 0

    # First three calls: still no wall, every call talks to the blocker
    for _ in range(3):
        assert r.walk((3, 3)) == "talk"
    assert calls["talk"] == 3
    assert r.memo["blocker_talks"] == {"42:1,0": 3}
    assert r.memo["walls"] == {"42": [[1, 0]]}
    assert any(e["kind"] == "npc_walled" and e["square"] == [1, 0] and e["map"] == 42 and e["talks"] == 3 for e in r.log)

    # Fourth call: blocker is a wall, the re-plan walks instead of talking
    calls["talk"] = 0
    assert r.walk((3, 3)) == "walk"
    assert calls["talk"] == 0                           # no more talking to the same beaten trainer
    assert r.memo["walls"] == {"42": [[1, 0]]}          # walls stay permanent in the memo


def test_walk_logs_walk_stuck_once_per_stuck_episode(monkeypatch):
    """BUG-0646: four failed steps in a row log one walk_stuck event with the reachable part's size; a
    later stall after a step that moved is a new episode and logs again. Movement is unchanged."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    fake_grid = overworld.Grid({(x, y): True for x in range(4) for y in range(4)})
    fake_grid.jumps, fake_grid.walls = {}, set()
    monkeypatch.setattr(overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: fake_grid)
    monkeypatch.setattr(overworld, "astar", lambda grid, start, goal: ["RIGHT"])
    monkeypatch.setattr(runner_mod, "links", lambda read: {"warps": []})
    moves = {"moved": False}
    r = object.__new__(runner_mod.Runner)
    r.memo, r.log, r.rom = {}, [], b"\x00"
    r.read = lambda addr, n=1: [3]
    r.pos = lambda: (1, 2)
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    r.step = lambda direction: moves["moved"]
    r.stuck = 0
    for _ in range(6):                                  # six presses that do not move the player
        assert r.walk((3, 2)) == "walk"
    moves["moved"] = True
    assert r.walk((3, 2)) == "walk"                     # one step that moves resets the episode
    moves["moved"] = False
    for _ in range(6):
        assert r.walk((3, 2)) == "walk"
    stalls = [e for e in r.log if e["kind"] == "walk_stuck"]
    assert stalls == [
        {"kind": "walk_stuck", "map": 3, "pos": [1, 2], "target": [3, 2], "edge": None, "part_size": 16},
        {"kind": "walk_stuck", "map": 3, "pos": [1, 2], "target": [3, 2], "edge": None, "part_size": 16},
    ]


def test_walk_target_is_logged_only_when_the_target_or_its_branch_changes(monkeypatch):
    """BUG-0655 diagnostic: a target that flips every tick logs one walk_target event per change (4 for 4 ticks);
    a target that stays the same logs nothing after its first tick. Movement is unchanged."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    fake_grid = overworld.Grid({(x, y): True for x in range(4) for y in range(4)})
    fake_grid.jumps, fake_grid.walls = {}, set()
    monkeypatch.setattr(overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: fake_grid)
    monkeypatch.setattr(overworld, "astar", lambda grid, start, goal: ["RIGHT"])
    monkeypatch.setattr(runner_mod, "links", lambda read: {"warps": []})

    def make():
        r = object.__new__(runner_mod.Runner)
        r.memo, r.log, r.rom = {}, [], b"\x00"
        r.read = lambda addr, n=1: [3]
        r.pos = lambda: (1, 2)
        r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
        r.step = lambda direction: True
        r.stuck = 0
        return r

    flip = make()
    for target in [(3, 2), (0, 0), (3, 2), (0, 0)]:
        flip.note_walk_target(3, target, None, "route")
        assert flip.walk(target) == "walk"
    events = [e for e in flip.log if e["kind"] == "walk_target"]
    assert len(events) == 4
    assert [e["target"] for e in events] == [[3, 2], [0, 0], [3, 2], [0, 0]]
    assert events[0] == {"kind": "walk_target", "map": 3, "pos": [1, 2], "target": [3, 2],
                         "branch": "route", "edge": None}

    still = make()
    for _ in range(4):
        still.note_walk_target(3, (3, 2), None, "route")
        assert still.walk((3, 2)) == "walk"
    assert [e["target"] for e in still.log if e["kind"] == "walk_target"] == [[3, 2]]   # the first tick only
    still.note_walk_target(3, (3, 2), None, "guard")                                       # same square, new branch
    assert [e["branch"] for e in still.log if e["kind"] == "walk_target"] == ["route", "guard"]


def test_a_map_like_another_in_size_and_warps_is_not_taken_for_a_stale_read():
    from shared.src.lib.game.pokemon.world import World
    route1 = {"width": 20, "height": 36, "warps": [], "edges": {"north": 1, "south": 0}}
    w = World({12: route1})
    route24 = {"map": 35, "width": 20, "height": 36, "warps": [], "edges": {"south": 3, "east": 36}}
    assert not w.stale(route24)                                    # same size, no warps, other connections
    assert w.stale({**route1, "map": 35})                          # Route 1's header under a new id: stale


def _party_read(moves_per_mon):
    """A read() over a fake party: each Pokémon's 4 move bytes at +8 of its 44-byte struct."""
    mem = {ADDR["party_count"]: [len(moves_per_mon)]}
    for i, mv in enumerate(moves_per_mon):
        mem[ADDR["party_mons"] + 44 * i + 8] = (mv + [0, 0, 0, 0])[:4]
    return lambda addr, n=1: mem.get(addr, [0] * n)[:n]


def test_cut_user_is_the_party_member_knowing_cut():
    from shared.src.lib.game.pokemon import hm
    assert hm.cut_user(_party_read([[22, 75], [10, 15], [33]])) == 1
    assert hm.cut_user(_party_read([[22], [33]])) is None


def test_cut_learner_prefers_a_free_slot_then_the_lowest_level():
    from shared.src.lib.game.pokemon import hm
    rows = [""] * 18
    rows[1], rows[3], rows[5] = "            APTE    ", "            APTE    ", "            PAS APTE"
    flags = hm.compat(rows)
    assert flags == [True, True, False, None, None, None]
    full, spare, other = [1, 2, 3, 4], [10], [5]
    assert hm.pick_learner(flags, [full, spare, other], [31, 8, 10]) == 1     # the spare slot, not the strong one
    assert hm.pick_learner(flags, [full, [1, 2, 3, 4], other], [31, 8, 10]) == 1   # all full: lowest level
    assert hm.pick_learner(flags, [full, spare, other], [31, 8, 10], tried=[1]) == 0   # one that refused is skipped
    assert hm.pick_learner([False, None], [[1], [2]], [5, 5]) is None


def test_field_move_box_and_start_menu_rows():
    from shared.src.lib.game.pokemon import hm
    rows = [""] * 18
    rows[1] = "   HERBIZARRE.31    "
    rows[2] = "...........  49. 93"
    rows[10] = ".............COUPE ."
    rows[12] = ".............STATS ."
    rows[14] = ".S.lectionn. ORDRE ."
    rows[16] = ".POK.MON.  . RETOUR"
    assert hm.entries(rows) == ["COUPE", "STATS", "ORDRE", "RETOUR"]
    menu = [""] * 18
    for i, label in enumerate(["POK.DEX", "POK.MON", "OBJET", "AAAAAAA", "SAUVER"]):
        menu[2 + 2 * i] = "...........  " + label
    assert hm.start_entry(menu, "OBJET") == 2 and hm.start_entry(menu, "POK.MON") == 1
    assert hm.menu_open(rows) and not hm.menu_open([""] * 18)


def test_astar_goes_through_a_cuttable_tree_only_when_the_detour_is_long():
    from shared.src.lib.game.pokemon import overworld
    walk = overworld.Grid({(x, y): True for x in range(30) for y in range(3)})
    for y in range(3):
        walk[(5, y)] = False                      # a wall across the map ...
    walk[(5, 1)] = True                           # ... with a tree square the grid lists as walkable
    walk.cuts = {(5, 1)}
    path = overworld.astar(walk, (3, 1), (7, 1))
    assert path == ["RIGHT"] * 4                  # no other way: through the tree
    walk[(5, 0)] = True                           # a free gap beside the tree: the detour costs 2, less than a Cut
    assert (5, 1) not in _squares((3, 1), overworld.astar(walk, (3, 1), (7, 1)))


def _squares(start, path):
    from shared.src.lib.game.pokemon import overworld
    sq, out = start, []
    for d in path:
        sq = (sq[0] + overworld.STEP[d][0], sq[1] + overworld.STEP[d][1])
        out.append(sq)
    return out


def test_runner_cuts_a_tree_in_the_way_and_walls_one_that_stays(monkeypatch):
    from shared.src.lib.game.pokemon import hm, overworld, runner as runner_mod
    grid = overworld.Grid({(x, 0): True for x in range(5)})
    grid.cuts = {(2, 0)}
    r = object.__new__(runner_mod.Runner)
    r.memo, r.log, r.rom, r.stuck = {}, [], b"\x00", 0
    r.read = lambda addr, n=1: [7]
    r.pos = lambda: (1, 0)
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    r.step = lambda d: True
    r.grid = lambda sprites_block=True: grid
    r.party = lambda: [{"name": "SABELETTE"}] * 8
    monkeypatch.setattr(hm, "use_cut", lambda runner: True)
    monkeypatch.setattr(hm, "cut_user", lambda read: 1)
    monkeypatch.setattr(runner_mod, "links", lambda read: {"warps": []})
    assert r.walk((4, 0)) == "cut failed"                 # the tree is still there after the menu trip
    assert r.walk((4, 0)) == "cut failed"
    assert r.memo["walls"] == {"7": [[2, 0]]} and r.log[-1]["kind"] == "cut_failed"
    r.memo = {}                                           # a fresh try: now the tree is gone from the grid after the cut

    def cut(runner):
        grid.cuts = set()
        return True
    monkeypatch.setattr(hm, "use_cut", cut)
    assert r.walk((4, 0)) == "cut tree"
    assert r.log[-1] == {"kind": "cut_tree", "map": 7, "at": [2, 0], "pokemon": "SABELETTE"}


def test_trash_can_search_starts_over_after_a_reset():
    from shared.src.lib.game.pokemon import gym
    s = gym.new_state()
    empty = ["Mmmm! / Un joli tas", "Un joli tas / d'ordures...miam!"]
    assert gym.after(s, (1, 7), empty) == "nothing" and [1, 7] in s["tried"]
    assert gym.after(s, (1, 7), []) == "none" and gym.after(s, (3, 7), ["MARIN veut / se battre!"]) == "none"
    assert gym.next_can(s, (1, 6)) != (1, 7)                       # a can already looked under is not tried again
    assert gym.after(s, (9, 11), ["Oh! Un bouton / dans la poubelle!", "Le premier / verrouillage est levé!"]) == "first"
    assert s["first"] == [9, 11] and s["open"]
    assert gym.next_can(s, (0, 0)) in ((7, 11), (9, 9))             # the second is next to the first
    assert gym.after(s, (7, 11), ["Une poubelle bien / dégueulasse!", "Oups... Les / verrouillages sont en place!"]) == "reset"
    assert s["first"] is None and s["tried"] == [] and gym.next_can(s, (9, 11)) == (9, 11)   # the switches moved: search again
    assert gym.after(s, (9, 11), ["Le premier / verrouillage est levé!"]) == "first"
    assert gym.after(s, (9, 9), ["Le deuxième / verrouillage est levé!", "La porte s'ouvre!"]) == "solved"


def test_a_stale_first_can_is_dropped_when_it_says_nothing():
    from shared.src.lib.game.pokemon import gym
    s = {"first": [1, 11], "open": False, "tried": [], "bad": []}
    assert gym.after(s, (1, 11), ["Mmmm! / Un joli tas", "d'ordures...miam!"]) == "nothing"
    assert s["first"] is None and s["tried"] == [[1, 11]]


def test_thunder_badge_follows_the_cut_milestone_and_is_done_at_three_badges():
    from shared.src.lib.game.pokemon import milestones
    ids = [m.id for m in milestones.MILESTONES]
    assert ids[ids.index("thunder_badge") - 1:ids.index("thunder_badge") + 1] == ["ss_anne_cut", "thunder_badge"]
    ms = milestones.MILESTONES[ids.index("thunder_badge")]
    mem = {milestones.BADGES: [0b11]}
    assert not ms.done(lambda a, n=1: mem.get(a, [0] * n)[:n], {})
    mem[milestones.BADGES] = [0b111]
    assert ms.done(lambda a, n=1: mem.get(a, [0] * n)[:n], {})


def test_story_goes_on_from_the_third_to_the_fourth_badge():
    from shared.src.lib.game.pokemon import milestones as M
    ids = [m.id for m in M.MILESTONES]
    assert ids[ids.index("thunder_badge"):ids.index("rainbow_badge") + 1] == ["thunder_badge", "rock_tunnel", "celadon", "rainbow_badge"]
    at = lambda m: (lambda a, n=1: {M.ADDR["map"]: [m], M.BADGES: [0b1111]}.get(a, [0] * n)[:n])
    by = {m.id: m for m in M.MILESTONES}
    assert by["rock_tunnel"].done(at(M.LAVENDER), {}) and not by["rock_tunnel"].done(at(M.ROUTE10), {})
    assert by["celadon"].done(at(M.CELADON), {}) and by["rainbow_badge"].done(at(M.CELADON), {})
    assert {M.PATH_ROUTE8, M.PATH_WEST_EAST, M.PATH_ROUTE7} <= set(by["celadon"].area)


def test_an_exit_square_that_failed_three_times_is_left_out():
    from shared.src.lib.game.pokemon.runner import Runner
    r = Runner.__new__(Runner)
    r.memo, r.stuck, events = {}, 3, []
    r.event = lambda kind, **kw: events.append(kind)
    exits = [(0, 5), (0, 6), (0, 7)]
    assert r.open_exits(4, "west", (0, 6), exits) == [(0, 5), (0, 7)] and r.stuck == 0 and events == ["exit_blocked"]
    assert r.open_exits(4, "west", (0, 5), exits) == [(0, 5), (0, 7)]      # not stuck yet: nothing new is marked
    assert r.open_exits(4, "west", (0, 5), [(0, 6)]) == [(0, 6)]            # all marked: try them all again

def test_grind_progress_resets_on_xp_rise_and_stalls_after_240s_without_xp():
    """Progress = experience gained, not only levels. An XP rise resets grind_s (as a level-up does);
    GRIND_STALL_S with no XP gained drops the target."""
    from shared.src.lib.game.pokemon.runner import GRIND_STALL_S, Runner
    mem = _Mem()
    mem.m[ADDR["party_count"]] = 1
    base = ADDR["party_mons"]

    def set_xp(xp):
        mem.m[base + 0x0E:base + 0x0E + 3] = xp.to_bytes(3, "big")
    set_xp(100)

    r = object.__new__(Runner)
    r.io = _FakeIO(mem)
    r.memo = {"grinding": True, "grind_level": 25, "grind_xp": 100, "grind_s": 100.0}
    r.log = []
    r.read = mem.read
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    r.rethink = lambda *a, **k: None
    r.wander = lambda here, info: "wandering"

    # XP rises between two grind checks: grind_s resets to 0 and grind_xp is stored
    set_xp(150)
    assert r.grind(here=0, info={}, top=25, want=30) == "wandering"
    assert r.memo["grind_s"] == 0.0 and r.memo["grind_xp"] == 150

    # XP stays the same and grind_s reaches the stall: target is dropped, train_stalled fires
    r.memo["grind_s"] = GRIND_STALL_S
    r.memo["grind_xp"] = 150
    assert r.grind(here=0, info={}, top=25, want=30) == "training stalled"
    assert r.memo["stalled_target"] == 30 and r.memo["grinding"] is False
    assert any(e["kind"] == "train_stalled" and e["seconds"] == GRIND_STALL_S for e in r.log)

    # A level-up still resets grind_level, grind_xp and grind_s in tandem
    r.memo.update(grinding=True, grind_level=25, grind_xp=150, grind_s=50.0)
    set_xp(300)
    assert r.grind(here=0, info={}, top=26, want=30) == "wandering"
    assert r.memo["grind_s"] == 0.0 and r.memo["grind_xp"] == 300 and r.memo["grind_level"] == 26


def test_leader_xp_reads_three_bytes_big_endian_at_party_mons_offset_0x0E():
    """leader_xp reads 3 bytes big-endian at offset 0x0E of slot 0's party struct."""
    from shared.src.lib.game.pokemon.runner import Runner
    mem = _Mem()
    mem.m[ADDR["party_count"]] = 1
    base = ADDR["party_mons"]
    mem.m[base + 0x0E:base + 0x0E + 3] = bytes([0x00, 0x10, 0x00])          # 4096
    r = object.__new__(Runner)
    r.read = mem.read
    assert r.leader_xp() == 4096
    mem.m[base + 0x0E:base + 0x0E + 3] = bytes([0xAB, 0xCD, 0xEF])          # 0xABCDEF
    assert r.leader_xp() == 0xABCDEF


def _arrow_row(arrow_at, stop_at, width=6, wall_at=None):
    """A one-row facility floor: `arrow_at` {x: direction}, a stop tile at `stop_at`, a wall at `wall_at`."""
    from shared.src.lib.game.pokemon import overworld
    by_dir = {d: q for q, d in overworld.ARROWS.items()}
    plain = (1, 1, 1, 1)
    tiles = {(x, 0): overworld.SPIN_STOP if x == stop_at else 1 for x in range(width)}
    quads = {(x, 0): by_dir[arrow_at[x]] if x in arrow_at else plain for x in range(width)}
    out = overworld.Grid({(x, 0): x != wall_at for x in range(width)})
    out.jumps, out.walls, out.cuts = {}, set(), set()
    return out, tiles, quads


def test_an_arrow_square_is_a_jump_to_where_the_slide_ends():
    from shared.src.lib.game.pokemon import overworld
    out, tiles, quads = _arrow_row({1: "RIGHT"}, stop_at=4)
    overworld.add_arrows(out, tiles, quads, (0, 0))
    assert out[(1, 0)] is False                                    # nobody stands on an arrow
    assert out.jumps[(0, 0)] == [("RIGHT", (4, 0))]                # over the plain squares to the stop tile
    assert out.jumps[(2, 0)] == [("LEFT", (4, 0))]                 # the arrow pushes whichever side it is entered from
    assert overworld.astar(out, (0, 0), (5, 0)) == ["RIGHT", "RIGHT"]   # one step onto the arrow, one off the stop tile


def test_a_slide_ends_at_a_wall_and_a_second_arrow_turns_it():
    from shared.src.lib.game.pokemon import overworld
    out, tiles, quads = _arrow_row({1: "RIGHT"}, stop_at=9, wall_at=4)
    overworld.add_arrows(out, tiles, quads, (0, 0))
    assert out.jumps[(0, 0)] == [("RIGHT", (3, 0))]
    grid = overworld.Grid({(x, y): True for x in range(3) for y in range(3)})
    tiles = {sq: 1 for sq in grid}
    quads = {sq: (1, 1, 1, 1) for sq in grid}
    by_dir = {d: q for q, d in overworld.ARROWS.items()}
    quads[(1, 0)], quads[(2, 0)] = by_dir["RIGHT"], by_dir["DOWN"]
    tiles[(2, 2)] = overworld.SPIN_STOP
    grid.jumps, grid.walls = {}, set()
    overworld.add_arrows(grid, tiles, quads, (9, 9))
    assert grid.jumps[(0, 0)] == [("RIGHT", (2, 2))]               # right onto the first arrow, turned down by the second


def test_arrows_are_told_by_all_four_tiles_not_the_lower_left_one():
    from shared.src.lib.game.pokemon import overworld
    assert overworld.ARROWS[(0x20, 0x30, 0x20, 0x30)] == "DOWN" and overworld.ARROWS[(0x21, 0x21, 0x20, 0x20)] == "LEFT"
    lower_left = [q[2] for q in overworld.ARROWS]
    assert lower_left.count(0x20) == 2                              # two directions share the lower-left tile (B3F, verified)


def test_story_goes_on_from_the_fourth_badge_to_the_flute():
    from shared.src.lib.game.pokemon import milestones as M
    ids = [m.id for m in M.MILESTONES]
    assert ids[ids.index("rainbow_badge"):ids.index("soul_badge") + 1] == ["rainbow_badge", "lift_key", "silph_scope", "poke_flute", "fuchsia", "soul_badge"]
    by = {m.id: m for m in M.MILESTONES}
    bag = lambda *items: (lambda a, n=1: ({M.BAG_COUNT: [len(items)], M.BAG_ITEMS: [x for i in items for x in (i, 1)]}.get(a) or [0] * n)[:n]
                          if a in (M.BAG_COUNT, M.BAG_ITEMS) else [0] * n)
    assert not by["lift_key"].done(bag(), {}) and by["lift_key"].done(bag(M.LIFT_KEY), {})
    assert not by["silph_scope"].done(bag(M.LIFT_KEY), {}) and by["silph_scope"].done(bag(M.SILPH_SCOPE), {})
    assert by["poke_flute"].done(bag(M.POKE_FLUTE), {}) and not by["poke_flute"].done(bag(M.SILPH_SCOPE), {})
    assert (M.SILPH_SCOPE, M.POKE_FLUTE, M.LIFT_KEY) == (0x48, 0x49, 0x4A)       # verified in the bag on the emulator
    assert M.ROCKET_B4F in by["lift_key"].area and set(M.POKEMON_TOWER) <= set(by["poke_flute"].area)
    at = lambda m, b=0: (lambda a, n=1: {M.ADDR["map"]: [m], M.BADGES: [b]}.get(a, [0] * n)[:n])
    assert by["fuchsia"].done(at(M.FUCHSIA), {}) and not by["fuchsia"].done(at(M.ROUTE15), {})
    assert by["soul_badge"].done(at(M.FUCHSIA_GYM, 0b11111), {}) and not by["soul_badge"].done(at(M.FUCHSIA_GYM, 0b1111), {})


def test_a_door_in_a_wall_is_pressed_after_a_step_off_and_on_did_nothing():
    """The Rocket elevator's door only fires on a press into the wall: first the walkable side, next the wall."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    grid = overworld.Grid({(x, y): x == 1 and y <= 5 for x in range(4) for y in range(8)})   # a corridor ending at the door (1, 5)
    pressed = []
    r = object.__new__(runner_mod.Runner)
    r.stuck, r.grid = 0, lambda sprites_block=True: grid
    r.step = lambda d: pressed.append(d) or True
    info = {"height": 8, "width": 4, "warps": [(1, 5)]}
    for _ in range(3):
        assert r.step_off_warp(5, info, (1, 5)) == "exit mat"
    assert pressed[0] == "UP" and pressed[1] != "UP" and pressed[2] != pressed[1]   # the wall sides come after, one by one
    r.step_off_warp(6, info, (1, 5))                                               # another map: the tries start again
    assert pressed[3] == "UP"


def test_a_door_square_that_never_fires_is_marked_and_its_twin_is_taken():
    """BUG-0696: Route 7 gate's east door (18, 9) is drawn as wall, only (18, 10) fires. Each step off it moves the
    player, so `stuck` never marked it: after every side twice it goes to bad_warps, a sole door is never marked."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    grid = overworld.Grid({(x, y): x >= 18 for x in range(20) for y in range(18)})
    r = object.__new__(runner_mod.Runner)
    r.stuck, r.memo, r.grid, r.step = 0, {}, lambda sprites_block=True: grid, lambda d: True
    events = []
    r.event = lambda kind, **facts: events.append((kind, facts))
    info = {"height": 18, "width": 20, "warps": [[18, 9, 76, 2], [18, 10, 76, 3], [11, 9, 76, 0], [5, 13, 77, 0]]}
    for _ in range(5):
        r.step_off_warp(18, info, (18, 9))
    assert not r.memo.get("bad_warps")                                     # a few tries: a ladder or mat fires by then
    for _ in range(3):
        r.step_off_warp(18, info, (18, 9))
    assert r.memo["bad_warps"] == [[18, 18, 9]] and events == [("warp_unusable", {"map": 18, "warp": [18, 9]})]
    for _ in range(10):
        r.step_off_warp(18, info, (5, 13))                                 # the only door to map 77: left to BUG-0634
    assert [18, 5, 13] not in r.memo["bad_warps"]


def test_a_warp_the_game_draws_as_a_wall_is_not_the_one_the_runner_aims_at():
    """BUG-0938: the south gate of Viridian Forest (map 50) lists two warps north — (4, 0) to the
    forest's warp 3 and (5, 0) to its warp 4 — but only (5, 0) is a door: the game's own screen
    draws (4, 0) as the wall tile 4A and (5, 0) as the door tile 3B. The runner aimed at the wall,
    the game refused the step, and the fallback of the walk stepped the player back down: the run
    ping-ponged between (4, 1) and (4, 2) until the stall detector fired (20261026-075140)."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    from shared.src.lib.game.pokemon.world import World

    warps = [(4, 0, 51, 3), (5, 0, 51, 4), (4, 7, 13, 5), (5, 7, 13, 5)]

    def gate_runner(grid):
        r = object.__new__(runner_mod.Runner)
        r.memo, r.log, r.stuck, r.no_route_ticks = {}, [], 0, 0
        r.event = lambda kind, **facts: r.log.append((kind, facts))
        r.pos = lambda: (4, 1)
        r.grid = lambda sprites_block=True: grid
        r.world = World({
            50: {"edges": {}, "warps": warps, "width": 10, "height": 8},
            51: {"edges": {}, "warps": [], "width": 20, "height": 36},
        })
        walked = []
        r.walk = lambda target, edge=None: walked.append(target) or "walk"
        r.go_to_map(50, 51, {"spans": {}, "warps": warps, "edges": {}, "width": 10, "height": 8})
        return walked

    grid = overworld.Grid({(x, y): y > 0 for x in range(1, 9) for y in range(8)})
    grid[(4, 0)] = False          # the wall the game draws (tile 4A)
    grid[(5, 0)] = True           # the door (tile 3B)
    assert gate_runner(grid) == [(5, 0)], "the runner must aim at the door, not at the wall"

    # a warp the game does not show is not known to be a wall: the choice is not changed
    far = overworld.Grid({(x, y): True for x in range(1, 9) for y in range(1, 8)})
    assert gate_runner(far) == [(4, 7)], "a warp off screen is not known to be a wall"

    # every candidate is a wall: the old choice is kept (the screen may be stale)
    walled = overworld.Grid({(x, y): y > 0 for x in range(1, 9) for y in range(8)})
    walled[(4, 0)] = walled[(5, 0)] = False
    assert gate_runner(walled) == [(4, 0)], "no door to walk to: the first warp of the route is kept"


def test_a_locked_room_sends_the_player_to_the_nearest_guard_a_few_times_only(monkeypatch):
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    monkeypatch.setattr(overworld, "sprites", lambda read: [(3, 0), (1, 0), (9, 9)])
    r = object.__new__(runner_mod.Runner)
    r.memo, r.pos, r.event = {}, lambda: (0, 0), lambda kind, **facts: None   # the 3rd talk walls him (npc_walled)
    part = {(0, 0), (1, 0), (3, 0)}                                                  # (9, 9) is outside the player's part
    assert r.guard_in_reach(7, part) == (1, 0)
    for _ in range(runner_mod.BLOCKER_TALKS_MAX + 1):
        r.guard_in_reach(7, part)
    assert r.guard_in_reach(7, part) == (3, 0)                                       # the first one was talked to enough


def test_the_marowak_ghost_floor_and_a_woken_snorlax_are_fought_not_fled():
    from shared.src.lib.game.pokemon import milestones as M, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.read = lambda addr, n=1: [M.TOWER_6F]
    assert r.must_fight()
    r.read = lambda addr, n=1: [M.TOWER_1F]
    assert not r.must_fight()
    r.memo["woken"] = True
    assert r.must_fight()


def test_exits_that_lead_to_a_dead_end_are_found_by_the_shift_seen_on_the_crossing():
    from shared.src.lib.game.pokemon.runner import prev_exits
    # west edge of map 24 crossed at (0, 20) landed at (19, 6) on the next map: its rows are 14 lower
    entry = {"from": 24, "side": "west", "exit": [0, 20], "map": 25, "landing": [19, 6]}
    assert prev_exits(entry, {"width": 30, "height": 40}, [(19, 6), (19, 4)]) == [[24, 0, 18], [24, 0, 20]]
    entry = {"from": 3, "side": "south", "exit": [7, 35], "map": 4, "landing": [2, 0]}   # a south edge: columns shift by -5
    assert prev_exits(entry, {"width": 20, "height": 36}, [(2, 0), (3, 0)]) == [[3, 7, 35], [3, 8, 35]]


def test_fallback_does_not_train_after_a_defeat_by_attrition():
    from shared.src.lib.game.pokemon import strategy
    party = [{"level": 47}, {"level": 8}]
    weak = strategy.fallback("defeat at fuchsia", {"milestone": "fuchsia", "party": party, "opponent_levels": [25, 27, 26]})
    assert weak["train_to_level"] is None and "attrition" in weak["reason"]
    close = strategy.fallback("defeat at fuchsia", {"milestone": "fuchsia", "party": party, "opponent_levels": [40, 44]})
    assert close["train_to_level"] == 49
    assert strategy.fallback("defeat at fuchsia", {"milestone": "fuchsia", "party": party})["train_to_level"] == 49   # no levels seen


def test_the_runner_has_every_story_step_it_calls():
    """Each story hook of the Rocket Hideout and the tower exists (a method lost in an edit once went unseen
    because the saves used were past the Game Corner)."""
    from shared.src.lib.game.pokemon.runner import Runner
    for name in ("game_corner_poster", "hideout_step", "giovanni", "ride_lift", "pick_lift_floor", "talk_to_topmost",
                 "wake", "wakes", "unblock", "find_route", "retreat", "step_off_warp", "guard_in_reach", "avoid_warps"):
        assert callable(getattr(Runner, name)), name


def test_game_corner_poster_fights_the_guard_then_presses_the_switch(monkeypatch):
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.log, r.read = [], lambda addr, n=1: [0]
    r.event = lambda kind, **facts: r.log.append(kind)
    block = {"v": 42}
    monkeypatch.setattr(overworld, "block_at", lambda read, x, y: block["v"])
    sprites = {"v": [runner_mod.POSTER_GUARD]}
    monkeypatch.setattr(overworld, "sprites", lambda read: sprites["v"])
    r.talk_at = lambda who: "talk"
    assert r.game_corner_poster() == "talk"                       # the guard first (he fights)
    sprites["v"] = []
    r.pos, r.walk = lambda: (9, 6), lambda sq: "walk"
    assert r.game_corner_poster() == "walk"                       # then up to the square in front of the poster
    r.pos, r.step, r.read_texts = lambda: runner_mod.POSTER_SPOT, lambda d: True, lambda key: ["Un bouton secret"]
    assert r.game_corner_poster() == "poster" and r.log == ["poster_switch"]
    block["v"] = runner_mod.STAIRS_OPEN_BLOCK
    assert r.game_corner_poster() is None                         # stairs open: the guide takes over


def test_the_lift_key_rocket_is_talked_to_until_the_ball_shows_however_often(monkeypatch):
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo, r.pos = {"key_guard_talks": 3}, lambda: (10, 3)        # the host's stalled memo: the old talk cap was used up
    seen = {"v": [runner_mod.LIFT_KEY_GUARD]}                      # the ball is hidden (image 0xFF), not in the list
    monkeypatch.setattr(overworld, "sprites", lambda read: seen["v"])
    r.read = lambda addr, n=1: [0]
    r.talk_at = lambda who: who
    for _ in range(10):
        assert r.fetch_lift_key() == runner_mod.LIFT_KEY_GUARD       # the fight, then the beaten Rocket's talk, again and again
    seen["v"] = [runner_mod.LIFT_KEY_GUARD, runner_mod.LIFT_KEY_BALL]
    assert r.fetch_lift_key() == runner_mod.LIFT_KEY_BALL            # his talk revealed the ball: pick it up


def test_a_guard_walls_on_his_third_talk_and_the_route_path_walls_the_same_npc_on_its_third_talk(monkeypatch):
    # BUG-0657: the guard path released a guard at 4 talks and never walled him, and the route path walled at 3 with
    # its own counter. One counter per square now: three talks from the guard path wall him (and he is released),
    # and two guard talks leave the route path one talk before its wall.
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    monkeypatch.setattr(overworld, "sprites", lambda read: [(1, 0)])
    monkeypatch.setattr(overworld, "astar", lambda grid, start, goal: ["RIGHT"])
    monkeypatch.setattr(overworld, "toward", lambda grid, start, goal: ["RIGHT"])

    def new_runner(memo):
        r = object.__new__(runner_mod.Runner)
        r.memo, r.log, r.read = memo, [], lambda addr, n=1: [7]
        r.pos = lambda: (0, 0)
        r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
        r.grid = lambda *a, **k: None
        return r
    part = {(0, 0), (1, 0)}
    guard = new_runner({})
    for _ in range(3):
        assert guard.guard_in_reach(7, part) == (1, 0)           # talks 1, 2, 3
    assert guard.memo["blocker_talks"] == {"7:1,0": 3}
    assert guard.memo["walls"] == {"7": [[1, 0]]}
    assert [e["kind"] for e in guard.log] == ["npc_walled"]
    assert guard.guard_in_reach(7, part) is None                 # no fourth talk

    # the same NPC after two guard talks: the route path talks once more and walls him, then re-plans
    route = new_runner({"blocker_talks": {"7:1,0": 2}})
    talks = []
    route.blocker_on_the_way = lambda start, target: (1, 0)
    route.wakes = lambda blocker: False
    route.talk_at = lambda who: talks.append(who) or "talk"
    assert route.unblock((0, 0), (3, 3)) == ("talk", None)       # the third talk
    assert route.memo["walls"] == {"7": [[1, 0]]}
    assert route.unblock((0, 0), (3, 3))[0] is None              # no fourth talk: the walk is re-planned
    assert talks == [(1, 0)]


def test_the_guard_target_stays_put_when_his_sprite_is_hidden_once_the_player_is_close(monkeypatch):
    # BUG-0651: a sprite is hidden (image 0xFF) once it is on screen within 5 squares, so the nearest one flipped
    # every tick: (27,12) at x=21, (20,2) at x=22. The chosen guard is kept until he is adjacent or capped.
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo, r.read = {}, lambda addr, n=1: [0]
    part = {(27, 12), (20, 2)}
    here = 0x10
    seen = {"v": [(27, 12), (20, 2)]}
    monkeypatch.setattr(overworld, "sprites", lambda read: seen["v"])
    r.pos = lambda: (21, 12)
    assert r.guard_in_reach(here, part) == (27, 12)
    seen["v"] = [(20, 2)]                                         # the guard is hidden now that he is 5 squares away
    r.pos = lambda: (22, 12)
    assert r.guard_in_reach(here, part) == (27, 12)               # still his square: no step back towards (20, 2)
    r.pos = lambda: (26, 12)                                      # next to him: the talk counts, the target is chosen again
    seen["v"] = [(27, 12), (20, 2)]
    assert r.guard_in_reach(here, part) == (27, 12)
    assert r.memo["blocker_talks"] == {f"{here}:27,12": 1}


def test_an_adjacent_guard_stays_the_target_while_his_talks_are_below_the_cap(monkeypatch):
    # BUG-0656: next to guard A his sprite is hidden, so only guard B is listed. The target was released as soon as
    # the player was adjacent, and the runner ping-ponged between A and B without ever talking to A. A stays the
    # target (each adjacent call is a talk and counts) until his talks reach the cap.
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo, r.read = {}, lambda addr, n=1: [0]
    part = {(27, 12), (20, 2)}
    here = 0x10
    seen = {"v": [(27, 12), (20, 2)]}
    monkeypatch.setattr(overworld, "sprites", lambda read: seen["v"])
    r.pos = lambda: (26, 12)                                      # next to guard A (27, 12)
    assert r.guard_in_reach(here, part) == (27, 12)
    seen["v"] = [(20, 2)]                                         # A is hidden now that the player is adjacent
    assert r.guard_in_reach(here, part) == (27, 12)               # not B: A is still below the talk cap
    assert r.memo["blocker_talks"] == {f"{here}:27,12": 2}


def test_talking_to_a_person_on_the_players_own_square_steps_aside_first():
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.pos = lambda: (10, 2)
    r.grid = lambda sprites_block=True: overworld.Grid({(10, 3): False, (10, 1): False, (9, 2): False, (11, 2): True})
    stepped = []
    r.step = lambda d: stepped.append(d) or True
    assert r.talk_at((10, 2)) == "step aside" and stepped == ["RIGHT"]


def test_any_errand_in_giovannis_half_of_b4f_heads_for_the_elevator(monkeypatch):
    from shared.src.lib.game.pokemon import milestones as M, overworld, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo, r.log = {}, []
    r.event = lambda kind, **facts: r.log.append(kind)
    r.grid = lambda sprites_block=True: overworld.Grid({(0, 0): True})
    r.pos = lambda: (0, 0)
    r.in_giovanni_wing = lambda info: True
    asked = []
    def no_route(here, dest, *a):                                 # BUG-0655: find_route returns (route, exploring)
        asked.append(dest)
        return None, False                                        # no route: the call ends there
    r.find_route = no_route
    r.guard_in_reach = lambda here, part, layout=None: None
    r.world = types.SimpleNamespace(maps={}, explore=lambda *a, **k: None)
    assert r.go_to_map(M.ROCKET_B4F, 0x85, {"spans": {}}) == "no route"
    assert asked == [M.ROCKET_LIFT]                               # a heal at Celadon's Center goes through the lift
    r.go_to_map(M.ROCKET_B4F, M.ROCKET_LIFT, {"spans": {}})
    assert asked[-1] == M.ROCKET_LIFT
    r.in_giovanni_wing = lambda info: False
    r.go_to_map(M.ROCKET_B4F, 0x85, {"spans": {}})
    assert asked[-1] == 0x85                                       # the other half of the floor keeps its own errand


def test_surf_milestone_is_done_when_a_party_member_knows_surf():
    from shared.src.lib.game.pokemon import milestones as M
    ms = {m.id: m for m in M.MILESTONES}["surf"]
    assert [m.id for m in M.MILESTONES][-12:] == ["soul_badge", "surf", "surf_learner", "strength", "saffron",
                                                 "seafoam", "secret_key", "volcano_badge", "silph_co", "marsh_badge", "earth_badge",
                                                 "hall_of_fame"]
    assert not ms.done(_party_read([[22, 75], [10, 15]]), {})
    assert ms.done(_party_read([[22, 75], [10, 15, M.SURF]]), {})
    assert M.SAFARI_SECRET_HOUSE in ms.maps and set(M.SAFARI_ZONE) <= set(ms.area)


def test_seafoam_and_cinnabar_are_deferred_without_a_surf_or_strength_user():
    """BUG-0643: host run 20261018-223003 had surf_deferred and strength_deferred (no party member can learn either),
    so no route reaches Seafoam (by Surf) or Cinnabar: the runner was `lost` toward Seafoam B4F in the Fighting Dojo
    and stalled on one square. Both milestones are deferred like strength_deferred."""
    from shared.src.lib.game.pokemon import milestones as M
    ms = {m.id: m for m in M.MILESTONES}
    read = _party_read([[22, 75], [10, 15]])
    assert not ms["seafoam"].done(read, {}) and not ms["volcano_badge"].done(read, {})
    assert ms["seafoam"].done(read, {"surf_deferred": True})
    assert ms["volcano_badge"].done(read, {"surf_deferred": True})
    assert not ms["volcano_badge"].done(read, {"strength_deferred": True})   # Cinnabar needs Surf only
    memo = {"done": [m.id for m in M.MILESTONES[:M.MILESTONES.index(ms["seafoam"])]], "surf_deferred": True}
    assert M.current(read, memo).id == "hall_of_fame"
    assert memo["done"][-7:] == ["seafoam", "secret_key", "volcano_badge", "silph_co", "marsh_badge", "earth_badge", "hall_of_fame"]


def test_earth_badge_is_deferred_without_surf():
    """BUG-0662: host runs 20261018-2300 to 20261019-041502 stalled 10 times at earth_badge with surf_deferred (5 badges,
    no Surf user): Route 23 is crossed by Surf, so no route reached Victory Road and the runner wandered Cerulean,
    talking to guards. With Surf deferred the milestone is done and the story ends instead of stalling."""
    from shared.src.lib.game.pokemon import milestones as M
    read = _party_read([[22, 75], [10, 15]])
    for mid in ("silph_co", "marsh_badge", "earth_badge", "hall_of_fame"):
        earth = {m.id: m for m in M.MILESTONES}[mid]
        assert not earth.done(read, {}) and not earth.done(read, {"strength_deferred": True})
        assert earth.done(read, {"surf_deferred": True})


def test_dex_page_of_a_prize_pokemon_is_closed_with_a():
    """BUG-0643: replaying host run 20261018-223003 with Seafoam deferred, the runner took the Fighting Dojo's prize
    ball and stood at (4, 2) behind Hitmonlee's Pokédex page: no text box, so every tick walked and nothing moved.
    The page (tilemap read from that save) is told by its frame and closed with A."""
    from shared.src.lib.game.pokemon import memory
    page = [0x63] + [0x64] * 18 + [0x65] + [0x66] + [0x7F] * 18 + [0x67]
    page += [0x7F] * (9 * 20 - len(page)) + [0x68] + [0x69, 0x6B] * 9 + [0x6A] + [0x7F] * 160
    blank = [0x7F] * 360
    read = lambda tiles: (lambda addr, n=1: tiles[:n] if addr == memory.ADDR["tilemap"] else [0] * n)
    assert memory.dex_page_open(read(page))
    assert not memory.dex_page_open(read(blank)) and not memory.text_box_open(read(page))


def test_pending_hm_is_the_first_one_in_the_bag_nobody_knows(monkeypatch):
    from shared.src.lib.game.pokemon import hm
    monkeypatch.setattr(hm, "bag", lambda read: {hm.HM01_CUT: 1, hm.HM03_SURF: 1})
    read = _party_read([[22, hm.CUT], [33]])
    assert hm.pending_hm(read, {}, 3)[0] == "Surf"                 # Cut is known, Surf is not
    assert hm.pending_hm(read, {"Surf": 3}, 3) is None             # tries used up
    monkeypatch.setattr(hm, "bag", lambda read: {})
    assert hm.pending_hm(read, {}, 3) is None


def test_safari_menu_is_told_by_its_two_rows():
    from shared.src.lib.game.pokemon import battle
    rows = [""] * 18
    rows[14], rows[16] = "..BALL.30    APPAT .", ". CAILLOU    FUITE ."
    assert battle.safari_menu_open(rows) and not battle.safari_menu_open([""] * 18)


def test_can_learn_reads_the_hm_flag_of_the_species_base_stats():
    from shared.src.lib.game.pokemon import rom as R
    stats = bytearray(28 * 3)
    stats[:10] = R.BULBASAUR_STATS
    stats[28 + 20 + 6] = 1 << (R.HM_SURF_BIT % 8)          # dex 2: Surf flag only
    data = object.__new__(R.GameData)
    data.rom = b"\x00" * 7 + bytes(stats) + R.DEX_ORDER
    data.stats_at, data.dex_at = 7, 7 + len(stats)
    # internal species 9 (Ivysaur) is dex 2 in the order table; the table's 9th entry is 2
    assert data.can_learn(9, R.HM_SURF_BIT) and not data.can_learn(9, R.HM_STRENGTH_BIT)
    assert not data.can_learn(0, R.HM_SURF_BIT) and not data.can_learn(200, R.HM_SURF_BIT)


def test_surf_is_wanted_only_when_nobody_in_the_party_can_learn_it(monkeypatch):
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    species = [24, 9]
    r.read = lambda addr, n=1: [len(species)] if addr == runner_mod.ADDR["party_count"] else species[:n]
    r.data = type("D", (), {"can_learn": staticmethod(lambda s, bit: s == 2 or s == 5)})()
    assert r.surf_wanted(5)           # the wild one can, the party cannot
    assert not r.surf_wanted(7)       # the wild one cannot
    species.append(2)
    assert not r.surf_wanted(5)       # a party member already can


# --- stuck detector (TASK-33) ----------------------------------------------------------------------------
def test_stall_detector_flags_no_progress_after_n_minutes_of_game_time_and_a_new_map_resets_it():
    from shared.src.lib.game.pokemon import stall
    memo = {}
    d = stall.StallDetector(memo, no_progress_min=1, same_spot_ticks=10_000)
    t, out = 1000.0, None
    for i in range(100):                      # 5 s of game time per tick (the cap), walking along one map
        t += 5
        out = d.observe("walk", "lift_key", 202, (i % 7, 3), 18, now=t) or out
    assert out == "no_progress"
    d2 = stall.StallDetector({}, no_progress_min=1, same_spot_ticks=10_000)
    t = 0.0
    for i in range(100):
        t += 5
        assert d2.observe("walk", "x", 100 + i // 8, (i % 7, 3), 18, now=t) is None   # a new map every 8 ticks: progress


def test_stall_detector_sees_a_dead_browser_page_where_every_read_waits_out_its_timeout():
    # 2026-10-23: the page stopped answering (every JS read waited 15 s), so a tick lasted a minute. The old 5 s
    # cap counted 5 s of game time per tick: the stall needed 60 ticks (an hour) and the run outlived its budget
    # instead of reporting the stall. The real time of a slow tick now counts.
    from shared.src.lib.game.pokemon import stall
    d = stall.StallDetector({}, no_progress_min=5, same_spot_ticks=10_000)
    t, out = 1000.0, None
    for i in range(12):                       # 12 ticks of a minute each: 12 minutes of a dead page
        t += 60
        out = d.observe("walk", "lift_key", 202, (5, 3), 18, now=t) or out
    assert out == "no_progress"


def test_stall_detector_flags_the_same_spot_but_not_long_battles_and_a_stop_between_runs_adds_nothing():
    from shared.src.lib.game.pokemon import stall
    d = stall.StallDetector({}, no_progress_min=60, same_spot_ticks=20)
    for _ in range(500):
        assert d.observe("battle move", "m", 5, (1, 1), 3, now=1.0) is None
    assert [d.observe("talk", "m", 5, (10, 3), 3, now=1.0) for _ in range(20)][-1] == "same_spot"
    memo = {}
    d = stall.StallDetector(memo, no_progress_min=1, same_spot_ticks=10_000)
    d.observe("walk", "m", 5, (1, 1), 3, now=0.0)
    d.observe("walk", "m", 5, (2, 1), 3, now=36_000.0)                 # ten hours between two runs
    assert memo["stall"]["progress_s"] <= 5


def test_stall_detector_does_not_count_a_long_gym_leader_battle_but_counts_a_wedged_one():
    # BUG-0706: Blaine's fight (Cinnabar gym, (3, 4)) took 4.7 of the 5 min and the run stalled mid-battle
    from shared.src.lib.game.pokemon import stall
    memo = {}
    d = stall.StallDetector(memo, no_progress_min=5, same_spot_ticks=10_000)
    t = 0.0
    d.observe("walk", "volcano_badge", 166, (3, 5), 29, now=t)
    for _ in range(120):                      # 10 min of one battle on the same square
        t += 5
        assert d.observe("battle move", "volcano_badge", 166, (3, 5), 29, now=t) is None
    assert memo["stall"]["progress_s"] == 0.0
    out = None
    for _ in range(240):                      # 20 more min: past the grace, a wedged fight is a stall
        t += 5
        out = d.observe("battle text", "volcano_badge", 166, (3, 5), 29, now=t) or out
    assert out == "no_progress"


def test_stall_detector_counts_a_first_visit_to_a_square_as_progress_until_the_milestone_changes():
    from shared.src.lib.game.pokemon import stall
    memo = {}
    d = stall.StallDetector(memo, no_progress_min=1, same_spot_ticks=10_000)
    t = 0.0
    for i in range(100):                      # exploring one cave floor: every tick a new square
        t += 5
        assert d.observe("walk", "seafoam", 159, (i, 2), 30, now=t) is None
    out = None
    for i in range(100):                      # then walking the same loop of squares again: no progress
        t += 5
        out = d.observe("walk", "seafoam", 159, (i % 10, 2), 30, now=t) or out
    assert out == "no_progress"
    d.observe("walk", "articuno", 159, (0, 2), 31, now=t + 5)          # a new milestone forgets the squares
    assert memo["stall"]["cells"] == ["159:0:2"] and memo["stall"]["progress_s"] == 0.0
    rep = stall._counters(memo["stall"])
    assert rep["cells"] == 1


def test_a_run_is_not_killed_by_a_no_progress_clock_it_inherited():
    """BUG-0897: the run of 20261025-000846 played 16 seconds and the stall detector fired on its
    very first tick. The memo carried the no-progress clock of the run before it (300.19 s, already
    over the 5 min threshold) because that run's stall report never made it back to the dispatcher,
    so the save was unlocked with an overdue clock in it. The clock of a milestone does span its runs
    - but a clock that is already overdue when a run starts is not that run's: the run starts its own.
    """
    from shared.src.lib.game.pokemon import stall
    memo = {"stall": {"progress_s": 300.19465494155884, "maps": [108, 34], "milestones": 33,
                      "spot": [108, [9, 14]], "spot_ticks": 1, "ms": "hall_of_fame",
                      "cells": ["108:9:14"]}}
    d = stall.StallDetector(memo, no_progress_min=5, same_spot_ticks=300)
    assert d.observe("walk", "hall_of_fame", 108, (9, 14), 33, now=1000.0) is None, \
        "the run must not be killed by the clock of the run before it"
    assert memo["stall"]["progress_s"] == 0.0, "the run starts its own clock"

    # a clock under the threshold still carries over: the time of a stuck milestone spans its runs
    memo2 = {"stall": {"progress_s": 120.0, "maps": [108], "milestones": 33, "spot": None,
                       "spot_ticks": 0, "ms": "hall_of_fame", "cells": ["108:9:14"]}}
    d2 = stall.StallDetector(memo2, no_progress_min=5, same_spot_ticks=300)
    d2.observe("walk", "hall_of_fame", 108, (9, 14), 33, now=1000.0)
    assert memo2["stall"]["progress_s"] == 120.0, "a clock under the threshold carries over"

    # the same for the counter of the square the player stands on
    memo3 = {"stall": {"progress_s": 0.0, "maps": [108], "milestones": 33, "spot": [108, [9, 14]],
                       "spot_ticks": 300, "ms": "hall_of_fame", "cells": ["108:9:14"]}}
    d3 = stall.StallDetector(memo3, no_progress_min=5, same_spot_ticks=300)
    assert d3.observe("walk", "hall_of_fame", 108, (9, 14), 33, now=1000.0) is None
    assert memo3["stall"]["spot_ticks"] == 1, "the run counts its own ticks on the square"


def test_the_stall_report_and_the_lock_are_written_before_the_game_report_is_uploaded():
    """BUG-0897: the report and the lock of a stalled run were written after the upload of the game
    report (a video of tens of MB). A run that dies in between leaves the save unlocked with an
    overdue no-progress clock in its memory: the dispatcher starts the next run without
    --clear_stall yes and that run is killed by the clock of the run before it within seconds
    (the run of 20261025-000846: 16 s of play, then a stall)."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "..", "test_scripts", "game", "game_pokemon.py")).read()
    assert src.index("game_stall.write_report") < src.index("report_url = upload_game_report(html_text"), \
        "the lock must be on the host before the run uploads its game report"
    assert src.index("game_stall.write_report") < src.index("game_series.save_run"), \
        "the lock must be on the host before the run writes its segment"


def test_a_story_done_only_by_deferred_milestones_is_a_stall():
    from shared.src.lib.game.pokemon import stall
    assert stall.deferred_end({"done": ["x"], "surf_deferred": True, "strength_deferred": False}) == "deferred_end"
    assert stall.deferred_end({"done": ["x"], "strength_deferred": False}) is None      # a real end of the story
    assert stall.deferred_flags({"surf_deferred": True, "a_deferred": 0}) == ["surf_deferred"]


def test_the_same_milestone_ending_three_runs_with_no_progress_is_a_stall():
    from shared.src.lib.game.pokemon import stall
    memo = {}
    assert [stall.note_run(memo, "lift_key", False) for _ in range(3)] == [None, None, "no_progress_runs"]
    assert stall.note_run(memo, "lift_key", True) is None and memo["no_progress_runs"]["n"] == 0
    assert stall.note_run(memo, "lift_key", False) is None
    assert stall.note_run(memo, "silph_scope", False) is None          # another milestone starts the count over


def test_a_simulated_stall_stops_the_run_writes_the_report_locks_the_save_and_the_alert_names_the_report(tmp_path, monkeypatch):
    import json, os
    from shared.src.lib.game.pokemon import runner as runner_mod, stall
    r = object.__new__(runner_mod.Runner)
    r.memo, r.log, r.io = {"done": ["starter"], "key_guard_talks": 3}, [], type("IO", (), {"wait": lambda self, ms: None})()
    r.read = lambda addr, n=1: [202] * n
    r.pos = lambda: (10, 3)
    r.tick = lambda: "talk"
    monkeypatch.setattr(runner_mod, "current", lambda read, memo: type("M", (), {"id": "lift_key"})())
    for i in range(50):
        r.event("battle_end", n=i, prompt="x" * 5000)
    result = r.run(60, stall=stall.StallDetector(r.memo, no_progress_min=30, same_spot_ticks=25))
    assert result["stalled"] == "same_spot" and result["ticks"] == 25 and r.log[-1]["kind"] == "stalled"
    detail = stall.describe(result["stalled"], 30, 25)
    report = stall.build_report(reason=result["stalled"], detail=detail, milestone=result["milestone"], map_id=result["map"],
                                pos=result["pos"], log=r.log, memo=r.memo, save="latest", run_id="20261014-190000",
                                saved={"state": "state_latest.json", "memory": "memory_latest.json", "backup_stamp": "20261014-190100"},
                                private_dir=str(tmp_path))
    assert (report["milestone"], report["map"], report["pos"], report["run_id"]) == ("lift_key", 202, [10, 3], "20261014-190000")
    assert len(report["last_events"]) == stall.EVENTS_IN_REPORT and report["last_events"][-1]["kind"] == "stalled"
    assert "prompt" not in report["last_events"][0] and report["key_memo"] == {"key_guard_talks": 3}
    assert report["saves"]["backup_stamp"] == "20261014-190100" and "plan" in report["last_plan"]
    path = stall.write_report(str(tmp_path), report)
    assert json.load(open(path))["kind"] == "pokemon_stall" and oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert stall.locked(str(tmp_path), "latest")["report"] == path          # the deployment's next run refuses to start
    assert stall.stalled_message(detail, "lift_key", 202, (10, 3), path).startswith("STALLED: the same map position")
    assert path in stall.stalled_message(detail, "lift_key", 202, (10, 3), path)
    assert stall.clear(str(tmp_path), "latest") and stall.locked(str(tmp_path), "latest") is None


# --- strength boulder solver (TASK-34) ------------------------------------------------------------------
def _strength_read(boulders, here, player=(15, 10)):
    """A `read` function that returns `boulders` as live on-screen sprite positions on map `here`.

    Mirrors the wire format `overworld.sprite_list` reads: picture at C100 + 16 * i, position
    at C200 + 16 * i + 4 (y + 4, x + 4). Boulder picture = 0x3F = 63 (pokered SPRITE_BOULDER).
    The list is read on every call, so a test that pushes a boulder sees it move.
    """
    mem = bytearray(0x10000)
    px, py = player
    mem[ADDR["x"]] = px
    mem[ADDR["y"]] = py
    mem[ADDR["map"]] = here

    def read(addr, n=1):
        for i, (bx, by) in enumerate(list(boulders), start=1):
            if i > 15:
                break
            sprite_base = 0xC100 + 16 * i
            mem[sprite_base + 0] = 63                          # picture: boulder
            mem[sprite_base + 2] = 0                           # image (0 = visible, not 0xFF)
            mem[0xC200 + 16 * i + 4] = by + 4                  # y4
            mem[0xC200 + 16 * i + 5] = bx + 4                  # x4
        return list(mem[addr:addr + n])

    return read


def test_seafoam_b3f_layout_returns_four_pushes_for_four_boulders():
    """Synthetic Seafoam B3F: 4 boulders at 4 positions, the plan is 4 DOWN pushes. The boulder
    sprite count from `read` opens the puzzle; the canonical plan covers all 4 holes."""
    from shared.src.lib.game.pokemon import strength
    layout = strength.PUZZLES[strength.SEAFOAM_B3F]
    assert layout.boulders_open == 4 and layout.name == "Seafoam B3F"
    boulders = [(10, 6), (12, 6), (10, 8), (12, 8)]
    read = _strength_read(boulders, strength.SEAFOAM_B3F)
    plan = strength.plan_strength_puzzle(read, strength.SEAFOAM_B3F)
    assert plan is not None and len(plan) == 4
    for push in plan:
        assert len(push) == 3 and isinstance(push[1], str) and isinstance(push[2], int)
        assert push[1] == "DOWN"                                 # all four pushes go DOWN into holes
        assert push[2] > 0                                       # a positive step count


def test_seafoam_b4f_layout_has_currents_and_pushes_up():
    """Synthetic Seafoam B4F: 4 boulders, plan pushes UP (the canonical B4F layout), and the
    layout carries current tile overrides for the runner to apply post-step."""
    from shared.src.lib.game.pokemon import strength
    layout = strength.PUZZLES[strength.SEAFOAM_B4F]
    assert layout.boulders_open == 4 and layout.currents         # B4F is the only floor with currents
    boulders = [(10, 12), (12, 12), (10, 14), (12, 14)]
    read = _strength_read(boulders, strength.SEAFOAM_B4F)
    plan = strength.plan_strength_puzzle(read, strength.SEAFOAM_B4F)
    assert plan is not None and len(plan) == 4
    for push in plan:
        assert push[1] == "UP"


def test_victory_road_2f_layout_returns_three_pushes_in_canonical_order():
    """Victory Road 2F has 3 boulders blocking the path; the canonical order (the boulder of the
    south first, then the switch) lets the runner reach each next boulder without backtracking."""
    from shared.src.lib.game.pokemon import strength
    layout = strength.PUZZLES[strength.VICTORY_ROAD_2F]
    assert layout.boulders_open == 3 and layout.name == "Victory Road 2F"
    boulders = [(4, 14), (5, 5), (23, 16)]
    read = _strength_read(boulders, strength.VICTORY_ROAD_2F)
    plan = strength.plan_strength_puzzle(read, strength.VICTORY_ROAD_2F)
    assert plan is not None and len(plan) == 3
    expected = [((4, 14), "LEFT", 1), ((3, 14), "DOWN", 2), ((3, 16), "LEFT", 2)]
    assert plan == expected                                     # the exact canonical order


def test_the_plan_of_victory_road_2f_pushes_the_boulder_of_the_south_onto_the_switch():
    """BUG-0955: the plan of Victory Road 2F named boulders the floor does not have ((10, 12),
    (12, 8), (8, 6)), so the chain never found a rock of the floor, the plan was given up and the
    lane ping-ponged between the two floors until the detector wrote no_progress (the run
    20261026-145622, map 194). The plan is the published walkthrough's (Bulbapedia,
    "Walkthrough:Pokemon Red and Blue/Part 15", §2F: "Push this boulder left, down, down, and left
    onto the button"): the boulder to the south of the landing square (0, 8) - the one at (4, 14) -
    is pushed southwestward onto the switch at (1, 16)."""
    from shared.src.lib.game.pokemon import strength
    layout = strength.PUZZLES[strength.VICTORY_ROAD_2F]
    assert layout.switch_at == (1, 16), "BUG-0955: the plan ends on the switch of the floor"

    # the boulders of the fresh floor, measured on the live save
    live = {(4, 14), (5, 5), (23, 16)}
    step = strength.chain_step(layout.plan, live)
    assert step is not None, "BUG-0955: the chain finds no rock of the floor's plan"
    index, rock, target, direction, steps = step
    assert (index, rock, target, direction, steps) == (0, (4, 14), (3, 14), "LEFT", 1), (
        "BUG-0955: the chain starts at the boulder to the south of the landing square")

    # every push starts where the previous one leaves the rock
    after = strength.chain_step(layout.plan, {(3, 14), (5, 5), (23, 16)}, upto=1)
    assert after is not None and after[1] == (3, 14) and after[2] == (3, 16) and after[3] == "DOWN"
    last = strength.chain_step(layout.plan, {(3, 16), (5, 5), (23, 16)}, upto=2)
    assert last is not None and last[1] == (3, 16) and last[2] == (1, 16) and last[3] == "LEFT"

    # the last push lands the rock on the switch of the floor
    assert strength.switch_step(layout) == 2, "BUG-0955: the last push is the one on the switch"


def test_the_way_to_the_elite_four_does_not_go_through_the_dead_end_of_victory_road():
    """BUG-0962: the waypoints of the `hall_of_fame` milestone sent the runner from Victory Road 2F
    into Victory Road 3F - a floor whose four exits all lead back to Victory Road 2F. The runner
    climbed up, could not use the exit that leads to the way out (the warp at (26, 8), the one that
    lands next to Route 23: a boulder was in the way), fell back to 2F and was sent up again: the
    lane ping-ponged between the two floors until the detector wrote no_progress (the run
    20261026-193346, map 194 at (6, 8)). Victory Road's floors are a detour: the way to Indigo
    Plateau is Route 23's north edge."""
    from shared.src.lib.game.pokemon import milestones as M, strength
    from shared.src.lib.game.pokemon.world import World

    # the world graph as measured on the live save (the run 20261026-193346)
    world = World({
        198: {"width": 30, "height": 18, "edges": {}, "warps": [(23, 7, 194, 3), (26, 8, 194, 5),
                                                                 (27, 15, 194, 4), (2, 0, 194, 6)]},
        194: {"width": 30, "height": 18, "edges": {}, "warps": [(0, 8, 108, 2), (29, 7, 34, 3),
                                                                 (29, 8, 34, 3), (23, 7, 198, 0),
                                                                 (25, 14, 198, 2), (27, 7, 198, 1),
                                                                 (1, 1, 198, 3)]},
        108: {"width": 20, "height": 18, "edges": {}, "warps": [(8, 17, 34, 2), (9, 17, 34, 2),
                                                                 (1, 1, 194, 0)]},
        34: {"width": 20, "height": 144, "edges": {"north": 9, "south": 33},
             "warps": [(7, 139, 193, 2), (8, 139, 193, 3), (4, 31, 108, 0), (14, 31, 194, 1)]},
    })

    # Victory Road 3F is a dead end: every one of its exits leads back to Victory Road 2F
    assert {w[2] for w in world.maps[198]["warps"]} == {194}, "BUG-0962: 3F is a dead end"
    assert not world.maps[198]["edges"], "BUG-0962: 3F has no edge exit either"

    # the way to Indigo Plateau leaves Victory Road over Route 23 (its north edge)
    route = world.route(198, strength.INDIGO_PLATEAU)
    assert route is not None and [m for m, _ in route] == [194, 34, strength.INDIGO_PLATEAU], (
        "BUG-0962: the way to Indigo Plateau goes over Route 23")

    # the floors of Victory Road above 1F are not waypoints to the Elite Four any more
    ms = {m.id: m for m in M.MILESTONES}["hall_of_fame"]
    for floor in (strength.VICTORY_ROAD_2F, strength.VICTORY_ROAD_3F):
        assert floor not in ms.maps, f"BUG-0962: Victory Road's floor {floor} is not a waypoint"
    # the way out (Route 23) is on the waypoints, and Indigo Plateau comes right after it
    assert ms.maps.index(strength.ROUTE_23) < ms.maps.index(strength.INDIGO_PLATEAU), (
        "BUG-0962: Indigo Plateau comes after Route 23")
    # the floors stay in the area: the runner is in one of them and has to get out
    for floor in strength.VICTORY_ROAD:
        assert floor in ms.area, "BUG-0962: the floors stay in the milestone's area"


def test_plan_returns_none_for_a_map_with_no_strength_puzzle():
    """Pallet Town and the road maps are not Strength maps. The solver returns None immediately,
    before reading any memory."""
    from shared.src.lib.game.pokemon import strength
    read = _strength_read([], 0x00)                              # Pallet Town (PALLET in milestones.py)
    assert strength.plan_strength_puzzle(read, 0x00) is None
    # A bare read function that raises if called: confirms `None` is returned before any memory touch
    def explode(addr, n=1):
        raise AssertionError("read must not be called for a non-puzzle map")
    assert strength.plan_strength_puzzle(explode, 0x5E) is None  # VERMILION_DOCK: not in PUZZLES


def test_plan_returns_none_when_boulders_are_missing_already_solved():
    """When fewer boulder sprites are on the map than the puzzle's `boulders_open` count, the puzzle
    is partially or fully solved and a new plan is not returned."""
    from shared.src.lib.game.pokemon import strength
    # Seafoam B3F expects 4 boulders; only 3 remain: one is already in a hole
    read = _strength_read([(10, 6), (12, 6), (10, 8)], strength.SEAFOAM_B3F)
    assert strength.plan_strength_puzzle(read, strength.SEAFOAM_B3F) is None
    # Zero boulders: floor fully drained
    read = _strength_read([], strength.SEAFOAM_B3F)
    assert strength.plan_strength_puzzle(read, strength.SEAFOAM_B3F) is None


def test_one_push_one_step_layout_returns_single_minimal_push(monkeypatch):
    """A minimal synthetic puzzle (a single boulder that needs a one-step push) returns a single
    push with steps=1. The layout is injected into `PUZZLES` for the duration of the test."""
    from shared.src.lib.game.pokemon import strength
    one_step = strength.PuzzleLayout(
        name="one step",
        plan=(((3, 3), "RIGHT", 1),),
        boulders_open=1,
    )
    monkeypatch.setitem(strength.PUZZLES, 0xF0, one_step)
    read = _strength_read([(3, 3)], 0xF0)
    assert strength.plan_strength_puzzle(read, 0xF0) == [((3, 3), "RIGHT", 1)]
    # No boulder on this synthetic map: puzzle is "solved", returns None
    assert strength.plan_strength_puzzle(_strength_read([], 0xF0), 0xF0) is None


def test_seafoam_victory_road_map_ids_match_pokered_disassembly():
    """Map id sanity: confirmed against pokered/constants/map_constants.asm (commit ref-pret)."""
    from shared.src.lib.game.pokemon import strength
    assert strength.SEAFOAM_1F == 0xC0 and strength.SEAFOAM_B1F == 0x9F
    assert strength.SEAFOAM_B2F == 0xA0 and strength.SEAFOAM_B3F == 0xA1
    assert strength.SEAFOAM_B4F == 0xA2
    assert strength.VICTORY_ROAD_1F == 0x6C and strength.VICTORY_ROAD_2F == 0xC2
    assert strength.VICTORY_ROAD_3F == 0xC6
    assert strength.CINNABAR_GYM == 0xA6 and strength.HALL_OF_FAME == 0x76
    assert strength.BOULDER_PICTURE == 63                      # SPRITE_BOULDER in sprite_constants.asm


def test_milestones_after_saffron_are_seafoam_volcano_badge_earth_badge():
    """The new milestones follow `saffron` in the order `seafoam`, `volcano_badge`, `earth_badge`.
    Each declares the puzzle maps it owns (no overlap with `saffron` and the upstream journey)."""
    from shared.src.lib.game.pokemon import milestones as M
    ids = [m.id for m in M.MILESTONES]
    assert ids[-7:] == ["seafoam", "secret_key", "volcano_badge", "silph_co", "marsh_badge", "earth_badge",
                        "hall_of_fame"]   # BUG-0697, BUG-0708, BUG-0710
    by = {m.id: m for m in M.MILESTONES}
    assert by["seafoam"].maps[-1] == M.CINNABAR_ISLAND and M.SEAFOAM_B3F in by["seafoam"].area
    assert by["seafoam"].done(_mem_read({M.ADDR["map"]: [M.SEAFOAM_B4F]}), {}) is False
    # Volcano Badge: `badges >= 7`
    assert not by["volcano_badge"].done(_mem_read({M.BADGES: [0x3F]}), {})
    assert by["volcano_badge"].done(_mem_read({M.BADGES: [0x7F]}), {})
    # the run's end: at HALL_OF_FAME (set after Lance's room — the in-battle heuristic is unchanged)
    assert not by["hall_of_fame"].done(_mem_read({M.ADDR["map"]: [M.VICTORY_ROAD_2F]}), {})
    assert by["hall_of_fame"].done(_mem_read({M.ADDR["map"]: [M.HALL_OF_FAME]}), {})
    assert M.VICTORY_ROAD_1F in by["hall_of_fame"].maps and M.HALL_OF_FAME in by["hall_of_fame"].maps


def test_sabrina_and_giovanni_come_before_victory_road():
    """BUG-0708: host run 20261019-212631 beat Blaine (6 badges, no Marsh Badge) and the next milestone was Victory Road,
    whose guide started on Victory Road 1F: no route from Blaine's gym, the runner talked to every quiz machine, went
    `lost` toward the Hall of Fame and stood 300 ticks on (16, 14). Route 23's guards and Giovanni's gym need the
    Marsh Badge, so Sabrina is next, by a guide that starts in Blaine's gym; then Giovanni; then Victory Road."""
    from shared.src.lib.game.pokemon import milestones as M
    six = _mem_read({M.BADGES: [0x5F], M.ADDR["map"]: [M.CINNABAR_GYM], M.BAG_COUNT: [0]})   # Boulder..Soul + Volcano
    done = [m.id for m in M.MILESTONES][:[m.id for m in M.MILESTONES].index("silph_co")]
    ms = M.current(six, {"done": list(done)})
    assert ms.id == "silph_co" and ms.maps[0] == M.CINNABAR_GYM and ms.maps[-1] == M.SILPH_CO_11F   # BUG-0710
    done.append("silph_co")
    seven = _mem_read({M.BADGES: [0x7F], M.ADDR["map"]: [M.SAFFRON_GYM], M.BAG_COUNT: [0]})
    ms = M.current(seven, {"done": list(done)})
    assert ms.id == "earth_badge" and ms.maps[0] == M.SAFFRON_GYM and ms.maps[-1] == M.VIRIDIAN_GYM
    eight = _mem_read({M.BADGES: [0xFF], M.ADDR["map"]: [M.VIRIDIAN_GYM], M.BAG_COUNT: [0]})
    ms = M.current(eight, {"done": list(done)})
    assert ms.id == "hall_of_fame" and ms.maps[0] == M.VIRIDIAN_GYM and M.ROUTE22_GATE in ms.maps


def test_silph_co_teleporter_pad_is_no_way_through_and_the_card_key_comes_first():
    """BUG-0711: stall 20261019-221517 stood on Silph Co. 11F (7, 2): the stairs end in a part with no way to Giovanni
    (his room is behind a Card Key gate in the part the 7F teleporter lands in). The Card Key (5F) comes first. On 5F the
    pad (9, 15) joined a strip shut by a beaten Rocket to the corridor north, so the route took a warp the walk never
    reached; 11F's dead (5, 5) entry is the only way into the president's row and stays walkable."""
    from shared.src.lib.game.pokemon import hm, overworld
    from shared.src.lib.game.pokemon.world import INERT_WARPS, parts
    # a 1 x 5 corridor: rows 0-1 north, (0, 2) a pad, rows 3-4 the strip
    walk = overworld.Grid({(0, y): True for y in range(5)})
    info = {"map": M.SILPH_5F, "edges": {}, "warps": [(0, 2, 233, 4), (0, 0, 208, 4)]}
    pr = parts(walk, info, pos=(0, 4))
    assert pr["player"] != pr["warp"][1]                   # the strip does not reach the north warp over the pad
    assert parts(walk, info, pos=(0, 2))["warp"][1] == parts(walk, info, pos=(0, 2))["player"]   # standing on it: both ways
    # 11F's row 5, x 4-7: the dead entry (5, 5) joins the two sides
    assert (M.SILPH_CO_11F, 5, 5) in INERT_WARPS
    row = overworld.Grid({(x, 5): True for x in range(4, 8)})
    inert = {"map": M.SILPH_CO_11F, "edges": {}, "warps": [(5, 5, 10, 9), (7, 5, 212, 3)]}
    pr = parts(row, inert, pos=(4, 5))
    assert pr["player"] == pr["warp"][1]
    assert (M.CARD_KEY, M.SILPH_3F, M.SILPH_5F, M.SILPH_7F) == (0x30, 0xD0, 0xD2, 0xD4)
    assert hm.tossable([0x10, 0x28]) == 0x10 and hm.tossable([0x28]) == 0x28   # Full Restore, then the Rare Candies
    by = {m.id: m for m in M.MILESTONES}
    assert M.SILPH_ELEVATOR not in by["marsh_badge"].area


def test_silph_step_fetches_the_card_key_on_5f_first():
    """BUG-0711: without the Card Key, any Silph floor leads to 5F; on 5F the balls are taken."""
    from shared.src.lib.game.pokemon import runner as R
    r = object.__new__(R.Runner)
    r.read = _mem_read({M.BAG_COUNT: [0]})
    calls = []
    r.go_to_map = lambda here, dest, info, **kw: calls.append(("go", here, dest)) or "walk"
    r.ball_step = lambda here: calls.append(("balls", here)) or "talk"
    assert r.silph_step(M.SILPH_CO_11F, {}) == "walk" and calls[-1] == ("go", M.SILPH_CO_11F, M.SILPH_5F)
    assert r.silph_step(M.SILPH_5F, {}) == "talk" and calls[-1] == ("balls", M.SILPH_5F)


def _mem_read(mem):
    """A read function backed by an addr -> bytes-int dict, like `_party_read`."""
    return lambda addr, n=1: list(mem.get(addr, [0] * n))[:n]


# --- strength boulder runner integration (TASK-34 wire) ----------------------------------------------
class _StrengthPuzzleIO:
    """A stub IO that records every `press` and `wait` call so a test can assert the exact sequence.

    Mirrors the surface `Runner.strength_puzzle_step` uses: `press(key, hold_ms)` and `wait(ms)`."""
    def __init__(self):
        self.presses = []        # [(key, hold_ms), ...]
        self.waits = []           # [ms, ...]

    def press(self, key, hold_ms=90):
        self.presses.append((key, hold_ms))

    def wait(self, ms):
        self.waits.append(ms)


def _strength_puzzle_runner(here, boulders):
    """A Runner with stubbed `pos`, `step`, `walk`, `event` and a fixed-4-boulder `read`. Each call to
    `strength_puzzle_step` moves the runner one tick: the stub `walk` parks the player on the
    opposite side of the next boulder's push direction, and `step` shifts the player one square in
    the pressed direction (so the post-push position lines up with what the next push expects)."""
    from shared.src.lib.game.pokemon import hm, overworld, runner as runner_mod, strength as s_mod
    r = object.__new__(runner_mod.Runner)
    r.io = _StrengthPuzzleIO()
    r.read = _strength_read(boulders, here)
    r.rom = b"\x00"
    r.memo = {}
    pos_state = [(15, 10)]                                     # mutable container, swapped by stubs
    r.pos = lambda: pos_state[0]
    events = []
    r.event = lambda kind, **facts: events.append({"kind": kind, **facts})
    r.log = events                                              # the override above captures into `events`

    walks = []
    def fake_walk(target):
        walks.append(tuple(target) if isinstance(target, (list, tuple)) else target)
        bx, by = int(target[0]), int(target[1])
        # The runner expects to push the boulder in the plan's direction; park the player one
        # square on the opposite side so the next `step(direction)` actually faces the boulder.
        # When the map is not a puzzle at all (no PUZZLES entry), fall back to a no-op position.
        layout = s_mod.PUZZLES.get(here)
        if layout is None:
            pos_state[0] = (bx, by)
            return "walk"
        # Find the push for this exact boulder (VR plans vary by boulder; B3F / B4F plans don't).
        push = next((p for p in layout.plan if p[0] == (bx, by)), None)
        if push is None:
            pos_state[0] = (bx, by)
            return "walk"
        dx, dy = overworld.STEP[push[1]]
        pos_state[0] = (bx - dx, by - dy)                         # opposite side of the push direction
        return "walk"
    r.walk = fake_walk
    r._test_walks = walks

    steps = []
    state = {"strength": False, "rock": None, "direction": None, "moved": 0}
    real_use_strength = hm.use_strength

    def use_strength(runner):
        state["strength"] = True
        state["moved"] = 0
        layout = s_mod.PUZZLES.get(here)
        index = r.memo.get("seafoam_pushes_done", 0)
        if layout and index < len(layout.plan):
            (bx, by), push_direction, count = layout.plan[index]
            state["rock"], state["direction"], state["count"] = (bx, by), push_direction, count
        return real_use_strength(runner)

    hm.use_strength = use_strength      # monkeypatch (of the test) restores the real one at teardown

    def fake_step(direction):
        steps.append(direction)
        dx, dy = overworld.STEP[direction]
        pos_state[0] = (pos_state[0][0] + dx, pos_state[0][1] + dy)
        if state["strength"] and state["rock"] and state["direction"] == direction:
            # the game slides the rock of the push one square when the push direction is pressed -
            # and a rock that runs into another rock does not move at all
            for i, (bx, by) in enumerate(boulders):
                if (bx, by) == state["rock"]:
                    nxt = (bx + dx, by + dy)
                    if not any((ox, oy) == nxt for ox, oy in boulders):
                        state["rock"] = nxt
                        boulders[i] = nxt
                        state["moved"] += 1
                        if state["moved"] >= state.get("count", 1):
                            state["strength"] = False     # the push of the plan is over
                    break
        return True
    r.step = fake_step
    r._test_steps = steps
    return r


def test_strength_puzzle_step_walks_to_each_boulder_in_order_and_presses_a(monkeypatch):
    """Victory Road 2F has 3 boulders; the runner pushes each one in order: walk to the square the
    push starts from (one tick), then press A to use Strength and walk `steps` squares in the
    canonical direction (the next tick), emitting `boulder_push`. Three pushes, three A-presses,
    three events — one per push.
    BUG-0874: the walk goes to the square the push starts from, not to the boulder: A* parks the
    player on an arbitrary side of the boulder, which is not always the side the push needs.
    BUG-0895: the push presses until the rock has really moved, so a push costs the press that
    faces the boulder plus one press per square of the plan. The floor used here is the one whose
    plan does not send a rock through the square of the next rock: the canonical Seafoam positions
    are a fiction and their paths cross each other."""
    from shared.src.lib.game.pokemon import hm, overworld, strength
    # Live boulders on the squares the plan of the floor names, so the solver's check passes.
    # BUG-0874: the push uses the field move (START, POKéMON, the Strength user, FORCE) the way Surf
    # and Cut are used: pressing A on the boulder alone never moves it.
    monkeypatch.setattr(hm, "use_strength", lambda runner: True)
    r = _strength_puzzle_runner(strength.VICTORY_ROAD_2F, [(4, 14), (5, 5), (23, 16)])
    plan = strength.PUZZLES[strength.VICTORY_ROAD_2F].plan
    for push_idx, push in enumerate(plan):
        # First tick of the push: walk to the square the push starts from.
        assert r.strength_puzzle_step(strength.VICTORY_ROAD_2F, {}) == "walk"
        # Second tick: the player is in position, so the push runs — press A, walk `steps` squares.
        assert r.strength_puzzle_step(strength.VICTORY_ROAD_2F, {}) == "boulder push"

    # The push itself presses no key: the field move is used by `hm.use_strength` (faked here).
    a_presses = [p for p in r.io.presses if p[0] == "A"]
    assert a_presses == []

    # One walk per push, each to the square the push starts from (the boulder, one square back).
    assert len(r._test_walks) == 3
    assert [tuple(t) for t in r._test_walks] == [(5, 14), (3, 13), (4, 16)]

    # Each push emits a boulder_push event with the right shape and plan_index 0..2 in order.
    pushes = [e for e in r.log if e["kind"] == "boulder_push"]
    assert len(pushes) == 3
    for i, (event, push) in enumerate(zip(pushes, plan)):
        boulder_xy, direction, steps = push
        bx, by = boulder_xy
        dx, dy = overworld.STEP[direction]
        # the runner's `boulder` key is the source position; `to` is the boulder's final position
        assert event["boulder"] == [bx, by]
        assert event["to"] == [bx + dx * steps, by + dy * steps]
        assert event["direction"] == direction and event["steps"] == steps
        assert event["map"] == strength.VICTORY_ROAD_2F and event["plan_index"] == i

    # The push directions and step counts match the canonical plan, in order.
    push_directions = [e["direction"] for e in pushes]
    push_steps = [e["steps"] for e in pushes]
    assert push_directions == [p[1] for p in plan]
    assert push_steps == [p[2] for p in plan]

    # Each push took exactly `1 face-step + steps push-steps` step presses, plus the wait between
    # A and the push slides (one extra `wait` per push, no extra `step`).
    expected_steps = []
    for _, direction, steps in plan:
        expected_steps.append(direction)                         # the face-step
        expected_steps.extend([direction] * steps)               # the push slides
    assert r._test_steps == expected_steps


def test_strength_puzzle_step_returns_none_for_a_non_puzzle_map(monkeypatch):
    """A 4-boulder Seafoam layout doesn't matter when `here` is Route 22 (0x21): the solver sees no
    entry in `PUZZLES` and returns None, so `strength_puzzle_step` returns None on the very first
    call. No A-press, no event."""
    from shared.src.lib.game.pokemon import strength
    r = _strength_puzzle_runner(0x21, [(12, 6), (14, 6), (12, 8), (14, 8)])
    assert r.strength_puzzle_step(0x21, {}) is None
    assert r.io.presses == [] and r.io.waits == []
    assert [e for e in r.log if e["kind"] == "boulder_push"] == []
    # No per-map memo was written: the runner should not have started tracking this non-puzzle map.
    assert r.memo == {}


def test_strength_puzzle_step_records_drain_flags_when_plan_finishes(monkeypatch):
    """Walking through the full 4-push Seafoam B3F plan ends with `memo["seafoam_drained_b3f"]`
    set, so the `seafoam` milestone predicate can fire. B4F's flag is untouched in this run."""
    from shared.src.lib.game.pokemon import hm, strength
    monkeypatch.setattr(hm, "use_strength", lambda runner: True)     # BUG-0874: the field move is used
    r = _strength_puzzle_runner(strength.SEAFOAM_B3F,
                                 [(12, 6), (14, 6), (12, 8), (14, 8)])
    plan = strength.PUZZLES[strength.SEAFOAM_B3F].plan
    for push in plan:
        assert r.strength_puzzle_step(strength.SEAFOAM_B3F, {}) == "walk"
        assert r.strength_puzzle_step(strength.SEAFOAM_B3F, {}) == "boulder push"
    # The flag fires the moment the last push completes — no follow-up call required.
    assert r.memo.get("seafoam_drained_b3f") is True
    assert "seafoam_drained_b4f" not in r.memo
    assert r.memo["seafoam_pushes_done"] == len(plan)            # the counter is past the last push
    # One more call: the puzzle is finished, the runner returns None and the guide takes over.
    assert r.strength_puzzle_step(strength.SEAFOAM_B3F, {}) is None


def test_surf_hunt_and_training_time_do_not_count_toward_the_stall():
    """The Safari Surf hunt (SURF_HUNT_GIVE_UP ticks, ~7 min) and training (GRIND_STALL_S without XP) end themselves.
    With the 5-min stall detector they would be killed first (stall 20261015-021503 was the 30-min version of that),
    so the runner marks their ticks `guarded` and the detector adds no time for them."""
    from shared.src.lib.game.pokemon import runner as R, stall
    r = object.__new__(R.Runner)
    r.read = lambda addr, n=1: [R.SAFARI_ZONE[0]] * n
    r.memo = {"hunt_area": R.SAFARI_ZONE[0], "hunt_total": 10}
    assert r.self_guarded() is True
    r.memo["hunt_total"] = R.SURF_HUNT_GIVE_UP
    assert r.self_guarded() is False                                   # past its give-up the hunt is not guarded
    r.memo = {"grinding": True}
    assert r.self_guarded() is True
    d = stall.StallDetector({}, no_progress_min=1, same_spot_ticks=10_000)
    t = 0.0
    for i in range(200):
        t += 5
        assert d.observe("walk", "surf", 220, (i % 3, 1), 20, now=t, guarded=True) is None


# --- strength milestone defer when no party learner (TASK-33, 2026-10-15) -------------------------
def test_strength_milestone_defers_when_no_party_can_learn():
    """The party has Venusaur (species 3) + Golbat (species 42) — neither learns Strength in
    Gen 1. With HM04 in the bag, the teach loop would fail 3 times and the runner would loop
    at the Warden's House pressing A on the Warden (stall report
    20261015-080004, diagnosis at
    ~/vpt-private/pokemon/stalls/strength_20261015-080004.diagnosis.md). The fix is to set
    `strength_deferred = True` immediately, so the milestone predicate fires and the guide walks
    the runner on."""
    from shared.src.lib.game.pokemon import milestones as M
    ms = {m.id: m for m in M.MILESTONES}["strength"]
    # No party at all: the party has 0 Pokémon (shouldn't happen in practice, but the predicate
    # falls through to the `or strength_deferred` clause only when the party exists and is empty).
    # The "no learner" check is in `strength_step` — covered by the test below. Here we just
    # verify the predicate.
    assert ms.done(_party_read([[22, 75]]), {"strength_deferred": True}) is True
    assert ms.done(_party_read([[22, 75]]), {}) is False


def test_strength_step_sets_strength_deferred_when_no_learner(monkeypatch):
    """Runner.strength_step, called with HM04 in the bag and a party of Venusaur (species 3)
    + Golbat (species 42) — neither learns Strength in Gen 1 — must set `strength_deferred = True`
    and reset `hm_tries["Strength"]` so the milestone fires and the next run starts fresh."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon import milestones as M

    r = object.__new__(runner_mod.Runner)
    r.memo = {"hm_tries": {"Strength": 3}}   # the existing 3 from the stall
    r.log = []

    # Read returns: bag (count, items) and party (count, species, ...).
    bag_count = 0xD31D + 5
    bag_items = 0xD31E + 5
    party_count = 0xD8A4 + 5 if False else None
    # In the real ROM the addresses are SH-shifted; the test uses the same constants as the
    # production code to avoid drift.
    from shared.src.lib.game.pokemon.memory import ADDR

    def fake_read(addr, n=1):
        out = [0] * n
        a = addr
        # bag count = 1 (just HM04)
        if a == bag_count:
            return [1]
        if a == bag_items:
            return [M.HM04_STRENGTH, 1]   # item id + qty 1
        # party: 2 Pokémon, Venusaur (3) and Golbat (42)
        if a == ADDR["party_count"]:
            return [2]
        if a == ADDR["party_species"]:
            return [3, 42, 0, 0, 0, 0]
        return out

    r.read = fake_read
    # GameData stub: can_learn always returns False for the two species here.
    class FakeData:
        def can_learn(self, species, bit):
            return False
    r.data = FakeData()

    out = r.strength_step(here=M.WARDENS_HOUSE, info={})

    # The fix: out is None (so the guide walks the runner on) and `strength_deferred` is set.
    assert out is None
    assert r.memo.get("strength_deferred") is True
    # The HM teach counter is reset so a future new party member starts fresh.
    assert "Strength" not in r.memo.get("hm_tries", {}), (
        "hm_tries['Strength'] should be cleared when strength_deferred fires"
    )
    # The event was recorded for the host report.
    assert any(e.get("kind") == "strength_deferred" for e in r.log), (
        f"expected a strength_deferred event, got log={r.log}"
    )


# --- Saffron stall (2026-10-15 09:15 UTC) -----------------------------------------------------------
def test_saffron_step_walks_runner_to_saffron_edge_when_stuck_in_south_of_celadon():
    """The saffron stall at 09:15 UTC had the runner at Celadon (6) pos (39, 20) with a drink
    in the bag. The runner's part (from `overworld.reachable`) is the south-east corner of
    Celadon and does NOT include any saffron-edge square (Route 7 / ROUTE7_GATE / path /
    gate maps around Saffron). The world A*'s `first_hop_ok` rejects all edges in that part
    and the BFS picks a south-gate warp (39, 19) as the first hop — the runner stalls at
    `warp_unusable`. The fix: when saffron_step sees the runner is in such a "wrong" part of
    Celadon, walk the runner to the closest saffron-edge square.
    """
    from shared.src.lib.game.pokemon import runner as runner_mod, milestones as M

    r = object.__new__(runner_mod.Runner)
    r.memo = {"drink_bought": True}   # the saffron drink was already bought on MART_ROOF
    r.log = []

    # Bag: 1 Fresh Water (0x3C). Read returns bag count, then item/qty pairs.
    bag_count_addr = 0xD31D + 5
    bag_items_addr = 0xD31E + 5

    def fake_read(addr, n=1):
        if addr == bag_count_addr:
            return [1]
        if addr == bag_items_addr:
            return [0x3C, 1]
        return [0] * n

    r.read = fake_read
    r.pos = lambda: (39, 20)
    r.io = type("IO", (), {"press": lambda self, *a, **kw: None, "wait": lambda self, *a, **kw: None})()
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})

    # Stub `walk` to record the call without doing grid A*.
    walked_to = []
    r.walk = lambda target, edge=None: walked_to.append(target) or "walked"

    # Stub `grid` so the runner's part is just the south-east squares, and the saffron-edge
    # squares are at the east edge in a different part.
    # The walkable squares: (39, 20) area (south-east) and (29, 10), (30, 10) (east edge).
    # max(xs) = 39. The east edge squares at x=39, y in [10, 11) are (39, 10). For (39, 10) to be
    # a saffron-edge square, it must be walkable; for the runner's part to NOT include it, the
    # runner at (39, 20) must be in a separate connected component.
    walk_grid = {(39, 20): True, (39, 19): True, (38, 20): True, (38, 19): True,
                 (39, 10): True}   # saffron-edge square at (39, 10), disconnected from the runner
    r.grid = lambda sprites_block=True: walk_grid

    # info: Celadon connects east to Route 7 (0x12 = 18). The east edge connection strip is
    # y in [10, 11). The east edge square (39, 10) is in this strip.
    info = {
        "spans": {"east": [10, 11]},
        "edges": {"east": 0x12},
    }

    out = r.saffron_step(here=M.CELADON, info=info)

    # The runner's part is {(39, 20), (39, 19), (38, 20), (38, 19)} — disconnected from
    # (39, 10). The saffron-edge square (39, 10) is the only one in the connection strip.
    # The runner walks to (39, 10) — Manhattan distance from (39, 20) is 10.
    assert out == "walked"
    assert walked_to == [(39, 10)], f"expected walk to (39, 10), got {walked_to}"


def test_saffron_step_walks_to_saffron_edge_when_player_already_in_part_with_saffron_edge():
    """BUG-0596: even when the runner's own part technically owns the saffron-edge square, the A*
    in overworld_tick's go_to_map can still pick a south-gate warp as the first hop (e.g. (39, 19)
    on Celadon — same stall shape as the BUG-0589 south-east partition, just on a different
    partition). Walk to the saffron-edge on every CELADON observe while the drink is in the bag,
    so the next observe's A* starts from the edge and crosses east to Route 7. The runner's pos
    is (29, 5); the saffron-edge is (29, 10) — walk toward it."""
    from shared.src.lib.game.pokemon import runner as runner_mod, milestones as M

    r = object.__new__(runner_mod.Runner)
    r.memo = {"drink_bought": True}
    r.log = []

    bag_count_addr = 0xD31D + 5
    bag_items_addr = 0xD31E + 5

    def fake_read(addr, n=1):
        if addr == bag_count_addr:
            return [1]
        if addr == bag_items_addr:
            return [0x3C, 1]
        return [0]

    r.read = fake_read
    r.pos = lambda: (29, 5)
    r.io = type("IO", (), {"press": lambda self, *a, **kw: None, "wait": lambda self, *a, **kw: None})()
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    captured = {}

    def fake_walk(target, edge=None):
        captured["target"] = target
        captured["edge"] = edge
        return "walk"

    r.walk = fake_walk
    # The runner's part is a connected column from (29, 5) up to (29, 10) (the saffron-edge
    # square at the east edge). max(xs) = 29, so the east edge squares at x=29, y in [10, 11)
    # include (29, 10). The runner's part includes (29, 10) — but saffron_step should still walk
    # the runner there explicitly (BUG-0596).
    walk_grid = {(29, y): True for y in range(0, 11)}
    r.grid = lambda sprites_block=True: walk_grid

    info = {
        "spans": {"east": [10, 11]},
        "edges": {"east": 0x12},
    }

    out = r.saffron_step(here=M.CELADON, info=info)
    assert out == "walk", f"expected 'walk' (BUG-0596 forces a walk to saffron-edge), got {out!r}"
    assert captured.get("target") == (29, 10), f"expected walk toward (29, 10), got {captured.get('target')!r}"


# --- saffron-step GUIDE-skip (TASK-33, EG-20261017) ------------------------------------------------
#
# The saffron milestone lists MART_ROOF between two CELADON entries:
# `[..., ROUTE7, CELADON, MART_ROOF, CELADON, ROUTE7, SAFFRON]`. Before the fix, when the runner
# was on CELADON with the drink in the bag but GUIDE still pointing at the first CELADON, the
# overworld_tick would route the runner back to MART_ROOF for a redundant drink-buy trip.
# At positions like (39, 20), every UP press is the south-gate warp and the runner spins in
# place: stalled with `same_spot` (a saffron instance replay hit this guide-detour wall in
# stalls 20261015-091504, 20261015-121504 and 20261015-124503 on host-clone-1).
def _saffron_skip_runner(guide_i, drink_bought=True, here=None):
    """A minimal Runner on Celadon with the saffron milestone GUIDE pointer set, used by the
    GUIDE-skip regression tests. `current(self.read, self.memo)` resolves the milestone from
    `done`, so we mark every milestone BEFORE saffron as done (and not saffron itself) to make
    saffron the active milestone in the test."""
    if here is None:
        from shared.src.lib.game.pokemon import milestones as M
        here = M.CELADON
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    from shared.src.lib.game.pokemon.milestones import MILESTONES
    done_before_saffron = [m.id for m in MILESTONES if m.id != "saffron"]
    r.memo = {"guide_i": guide_i, "drink_bought": drink_bought, "done": done_before_saffron}
    r.log = []
    bag_count_addr = 0xD31D + 5
    bag_items_addr = 0xD31E + 5

    def fake_read(addr, n=1):
        # sprite reads need 3-byte length; other code paths ask for 1 or 2. Always return
        # the right length for the address — same pattern as `_strength_read` in TASK-34.
        if addr == bag_count_addr:
            return [1]
        if addr == bag_items_addr:
            return [0x3C, 1]
        return [0] * max(n, 1)

    r.read = fake_read
    r.pos = lambda: (39, 20)
    r.io = type("IO", (), {"press": lambda self, *a, **kw: None, "wait": lambda self, *a, **kw: None})()
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    # BUG-0596: saffron_step walks toward the saffron-edge on every CELADON observe while the drink
    # is in the bag. Capture the walk target so tests can assert it, but allow it to fire.
    r._saffron_walk_target = None

    def fake_walk(target, edge=None):
        r._saffron_walk_target = target
        return "walk"

    r.walk = fake_walk
    # The runner is in a part that already has a saffron-edge square (no walk needed), and the
    # first hop to (49, 10) is reachable — the saffron_step walks the runner explicitly to
    # (49, 10) (BUG-0596) and bumps GUIDE.
    walk_grid = {(x, y): True for x in range(0, 50) for y in range(0, 24)}
    walk_grid[(49, 10)] = True
    r.grid = lambda sprites_block=True: walk_grid

    info = {
        "spans": {"east": [10, 11]},
        "edges": {"east": 0x12},
    }
    return r, info


def test_saffron_step_skips_drink_detour_when_guide_is_on_first_celadon():
    """With GUIDE on the first CELADON (index 9 in the saffron maps list), saffron_step must
    advance GUIDE to the second CELADON (index 11) so the route uses the saffron-area edge
    instead of routing back to MART_ROOF. BUG-0596: saffron_step also returns a walk toward the
    saffron-edge so the runner actually moves east."""
    r, info = _saffron_skip_runner(guide_i=9)

    out = r.saffron_step(here=M.CELADON, info=info)

    assert out == "walk", f"BUG-0596: saffron_step must walk toward saffron-edge, got {out!r}"
    assert r.memo["guide_i"] == 11, f"expected GUIDE bumped from 9 to 11, got {r.memo['guide_i']}"
    assert r._saffron_walk_target == (49, 10), f"expected walk to (49, 10), got {r._saffron_walk_target!r}"
    # a `guide_skip` event is recorded so the stall detector and review scripts notice the path
    skips = [e for e in r.log if e.get("kind") == "guide_skip"]
    assert skips, "expected a guide_skip event"
    assert skips[0]["from_"] == 9 and skips[0]["to"] == 11
    assert skips[0]["map"] == M.CELADON and skips[0]["milestone"] == "saffron"


def test_saffron_step_does_not_skip_when_runner_not_on_celadon():
    """The GUIDE skip is only valid when the runner is ON Celadon: on a different saffron-area
    map (e.g. SAFFRON itself, after the gate guard let them through), saffron_step's first branch
    talks to the gate guard and falls through to the runner's normal A* — the GUIDE skip in
    `_saffron_skip_drink_detour` must not fire because here is not CELADON. (This test uses
    SAFFRON to avoid hitting `talk_to_nearest` and the sprite-list read.)"""
    r, info = _saffron_skip_runner(guide_i=13)   # SAFFRON in the saffron maps list (= maps[-1])

    out = r.saffron_step(here=M.SAFFRON, info={})

    assert out is None
    assert r.memo["guide_i"] == 13, f"GUIDE must not change off-Celadon, got {r.memo['guide_i']}"
    assert not [e for e in r.log if e.get("kind") == "guide_skip"]


def test_saffron_step_does_not_skip_when_drink_not_bought():
    """Without a drink, saffron_step routes the runner to MART_ROOF (the vending machine).
    The GUIDE skip is only right once `drink_bought` is true — otherwise we are running the
    intended buy-detour path."""
    r, info = _saffron_skip_runner(guide_i=9, drink_bought=False)
    # Without the drink in the bag, saffron_step must NOT walk to the saffron-edge (it would skip
    # the MART_ROOF vending-machine detour). Replace the runner's read with an empty-bag version.
    empty_bag_count_addr = r.read.__closure__[0].cell_contents if r.read.__closure__ else None
    bag_count_addr = 0xD31D + 5
    bag_items_addr = 0xD31E + 5

    def empty_bag_read(addr, n=1):
        if addr == bag_count_addr:
            return [0]
        if addr == bag_items_addr:
            return [0, 0]
        return [0] * max(n, 1)

    r.read = empty_bag_read

    out = r.saffron_step(here=M.CELADON, info=info)

    assert out is None
    assert r.memo.get("guide_i", 9) == 9, "GUIDE must not be bumped when drink not bought"
    assert not [e for e in r.log if e.get("kind") == "guide_skip"]


def test_saffron_step_idempotent_when_guide_already_advanced():
    """If GUIDE is already past the first CELADON (e.g. it was advanced on a prior tick and
    the runner is still on Celadon), saffron_step must not jump GUIDE again, which would
    leave it stuck at the second CELADON repeating itself until something else moves it.
    BUG-0596: saffron_step still walks the runner toward the saffron-edge."""
    r, info = _saffron_skip_runner(guide_i=11)

    out = r.saffron_step(here=M.CELADON, info=info)

    assert out == "walk", f"BUG-0596: saffron_step must walk even when GUIDE is already advanced, got {out!r}"
    assert r._saffron_walk_target == (49, 10), f"expected walk to (49, 10), got {r._saffron_walk_target!r}"
    assert r.memo["guide_i"] == 11, f"GUIDE already advanced; must not move (got {r.memo['guide_i']})"


def test_saffron_skip_resets_same_spot_stall_when_guide_is_bumped():
    """On a host that has failed 600+ times at the same position (Celadon (39, 20)), the
    memo carries `stall.spot = [6, [39, 20]]` and `stall.spot_ticks = 600`. After the GUIDE
    bump (the runner's plan changed — saffron-area edge instead of MART_ROOF detour), the
    next overworld_tick would observe() the same spot, tick one more spot counter to 601,
    and trigger `same_spot` even though the runner's plan just changed. The bump must also
    reset the stall counters so the runner gets 600 real ticks to walk before the next stall.
    BUG-0597: the bump fires on the SAME call as saffron_step's walk (not delayed until the
    runner reaches the saffron-edge many ticks later)."""
    r, info = _saffron_skip_runner(guide_i=9)
    # Simulate the host's accumulated stall state from earlier failing runs.
    r.memo["stall"] = {
        "progress_s": 0.0,
        "maps": [6, 12, 19, 5],
        "milestones": 24,
        "spot": [6, [39, 20]],
        "spot_ticks": 600,
    }

    out = r.saffron_step(here=M.CELADON, info=info)

    assert out == "walk", f"saffron_step should walk on every Celadon observe (got {out!r})"
    assert r.memo["guide_i"] == 11, f"GUIDE bumped (got {r.memo['guide_i']})"
    stall = r.memo["stall"]
    assert stall["spot_ticks"] == 0, f"spot_ticks must reset (got {stall['spot_ticks']})"
    assert stall["spot"] is None, f"spot must reset (got {stall['spot']})"
    assert stall["progress_s"] == 0.0, f"progress_s must reset (got {stall['progress_s']})"


def test_saffron_skip_does_not_reset_stall_when_no_bump():
    """If saffron_step does NOT bump GUIDE (runner is on a non-Celadon map, drink not yet
    bought, or GUIDE is already past the first CELADON), the stall counters must be left
    untouched — the runner's plan hasn't changed. saffron_step still walks (BUG-0596 /
    BUG-0597) but with no GUIDE change there's no plan change to log."""
    r, info = _saffron_skip_runner(guide_i=11)   # GUIDE already past — no bump
    r.memo["stall"] = {
        "progress_s": 0.0,
        "maps": [6],
        "milestones": 24,
        "spot": [6, [39, 20]],
        "spot_ticks": 600,
    }

    out = r.saffron_step(here=M.CELADON, info=info)

    assert out == "walk", f"saffron_step should walk on every Celadon observe (got {out!r})"
    stall = r.memo["stall"]
    assert stall["spot_ticks"] == 600, f"spot_ticks must NOT reset (got {stall['spot_ticks']})"
    assert stall["spot"] == [6, [39, 20]], f"spot must NOT reset (got {stall['spot']})"


# --- Surf-learner gifts: catch_surf_learner (TASK-105) ----------------------------------------------
def _surf_gift_runner(here, party_count, species_list, pos):
    """A Runner wired with a mutable `_Mem` so talk_to_nearest can add the gift mid-test.

    The runner is parked at map `here`, position `pos`, with a party of `party_count` Pokémon
    (`species_list`, padded with 0 for empty slots). `talk_to_nearest` mutates the memory so the
    post-gift read sees the new species — tests just call `r.catch_surf_learner(here, info)`
    once and inspect the runner afterwards. No actual IO is performed."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.log = []
    mem = bytearray(0x10000)
    mem[ADDR["party_count"]] = party_count
    for i, s in enumerate(species_list):
        mem[ADDR["party_species"] + i] = s
    mem[ADDR["map"]] = here
    mem[ADDR["x"]] = pos[0]
    mem[ADDR["y"]] = pos[1]
    r._mem = mem
    r.read = lambda addr, n=1: list(mem[addr:addr + n])
    r.pos = lambda: (mem[ADDR["x"]], mem[ADDR["y"]])
    r.io = type("IO", (), {"press": lambda self, *a, **kw: None, "wait": lambda self, *a, **kw: None})()
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})

    # A world graph with both gift maps registered (mirrors the long-play after Mt. Moon B2F).
    # `route(here, dest)` is a True/False probe used by `_pick_surf_gift_source`; for the tests
    # where the runner is already on the gift map, route is never called.
    def _route(start, goal, *a, **kw):
        return start == goal
    r.world = types.SimpleNamespace(
        maps={runner_mod.MT_MOON_B2F: {}, runner_mod.SILPH_CO_7F: {}},
        route=_route,
    )
    r.go_to_map = lambda *a, **kw: "walk to map"   # would only fire when `here` is off the gift map
    r.walk = lambda *a, **kw: "walk"                # would only fire when `pos` is not the gift square
    r.hunt_surf_learner = lambda *a, **kw: "safari hunt"   # the fallback after `catch_surf_learner` returns None

    # talk_to_nearest advances the dialogue and, on the last press, the gift Pokémon joins the
    # party: bump it and write the expected species at the new slot. The method is called multiple
    # times during a single gift (one A per tick), so the bump only fires once on the final tick.
    state = {"done": False}
    def talk_to_nearest():
        if state["done"]:
            return "talk"
        state["done"] = True
        mem[ADDR["party_count"]] = party_count + 1
        mem[ADDR["party_species"] + party_count] = species_list[party_count]
        return "talk"
    r.talk_to_nearest = talk_to_nearest
    return r


def test_catch_surf_learner_takes_magikarp_at_mt_moon_b2f():
    """The runner is parked on Mt. Moon B2F next to the Magikarp fisherman. One call to
    `catch_surf_learner` walks to the gift square (no-op since the runner is already there),
    talks to the fisherman, the Magikarp joins the party, and `memo["surf_learner"]` is set
    to 129. The next milestone's guide takes over from there."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = _surf_gift_runner(runner_mod.MT_MOON_B2F, 1, [0x99, runner_mod.MAGIKARP],
                          runner_mod.MT_MOON_MAGIKARP_GIFT)
    out = r.catch_surf_learner(runner_mod.MT_MOON_B2F, {})
    assert out == "got Magikarp at Mt. Moon"
    assert r.memo["surf_learner"] == runner_mod.MAGIKARP
    assert r.memo["surf_taught"] is False
    # Post-gift state: party grew by 1 and the new slot is Magikarp (species 129).
    assert r.read(ADDR["party_count"])[0] == 2
    assert r.read(ADDR["party_species"] + 1, 1)[0] == runner_mod.MAGIKARP
    # The surf_gift_try event was logged, then the surf_learner event on success.
    kinds = [e["kind"] for e in r.log]
    assert "surf_gift_try" in kinds and "surf_learner" in kinds
    assert kinds.index("surf_gift_try") < kinds.index("surf_learner")
    surf_event = next(e for e in r.log if e["kind"] == "surf_learner")
    assert surf_event["source"] == "Mt. Moon" and surf_event["species"] == runner_mod.MAGIKARP


def test_catch_surf_learner_takes_lapras_at_silph_co_7f():
    """Same pattern as the Magikarp test, but on Silph Co. 7F with the Lapras gift. The
    long-play's milestone flow skips Silph Co., so the runner never visits it in practice —
    but the method works the same when the runner is on the gift map."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = _surf_gift_runner(runner_mod.SILPH_CO_7F, 2, [0x99, 0xB1, runner_mod.LAPRAS],
                          runner_mod.SILPH_LAPRAS_GIFT)
    out = r.catch_surf_learner(runner_mod.SILPH_CO_7F, {})
    assert out == "got Lapras at Silph Co."
    assert r.memo["surf_learner"] == runner_mod.LAPRAS
    assert r.read(ADDR["party_count"])[0] == 3
    assert r.read(ADDR["party_species"] + 2, 1)[0] == runner_mod.LAPRAS
    surf_event = next(e for e in r.log if e["kind"] == "surf_learner")
    assert surf_event["source"] == "Silph Co." and surf_event["species"] == runner_mod.LAPRAS


def test_catch_surf_learner_logs_surf_gift_missed_when_party_is_full(monkeypatch):
    """A full party (party_count == 6) means the game refuses the gift. `catch_surf_learner`
    must NOT loop on the same square: it logs `surf_gift_missed` once and yields to the
    Safari Zone hunt. The dispatch in `story_step` then calls `hunt_surf_learner`."""
    from shared.src.lib.game.pokemon import runner as runner_mod, milestones as M
    r = _surf_gift_runner(runner_mod.MT_MOON_B2F, 6,
                          [0x99, 0xB1, 0xC3, 0xD5, 0xE0, 0xF2],   # a 6-mon party: no room for the gift
                          runner_mod.MT_MOON_MAGIKARP_GIFT)
    # The dispatch: `story_step` calls `catch_surf_learner` first; on None it falls through to
    # `hunt_surf_learner`. Confirm the wiring with a small `story_step`-shaped wrapper.
    r.needs_surf_learner = lambda: True
    called = []
    r.hunt_surf_learner = lambda *a, **kw: called.append("hunt") or "safari hunt"
    # A minimal stand-in for the `ms` object used by `story_step`: only `id` is read.
    ms = type("MS", (), {"id": "surf"})()
    # Mirror `story_step`'s logic exactly.
    if ms.id == "surf" and r.needs_surf_learner():
        gift = r.catch_surf_learner(runner_mod.MT_MOON_B2F, {})
        if gift is not None:
            out = gift
        else:
            out = r.hunt_surf_learner(runner_mod.MT_MOON_B2F, {})
    else:
        out = None
    assert out == "safari hunt" and called == ["hunt"]                # the Safari hunt ran as fallback
    assert r.memo.get("surf_gift_missed") is True
    kinds = [e["kind"] for e in r.log]
    assert "surf_gift_missed" in kinds
    miss = next(e for e in r.log if e["kind"] == "surf_gift_missed")
    assert miss["reason"] == "party_full"


# --- saffron_step saffron-edge preference (TASK-33, BUG-0607) ----------------------------------------
#
# BUG-0607: when the runner is on a saffron-area map OTHER than Celadon, saffron_step must prefer
# saffron-edges whose destination is closest to SAFFRON (via the world graph). Without this filter,
# on Route 7 (0x12) the runner at the west edge (e.g. (0, 3), entering from Celadon — host run
# 20261017-174506) can pick the south edge to PATH_ROUTE7 (0x4D) over the east edge to ROUTE7_GATE
# (0x4C) by Manhattan distance (the two are roughly tied). The runner then walks into PATH_ROUTE7
# → Route 8 west → PATH_ROUTE8 → Route 7 east → ROUTE7_GATE and ends up back on Celadon's east
# side at (48, 11) (host run 20261017-194505: `lost: [77, 18]` = PATH_ROUTE7 (0x4D = 77) at y=18,
# then re-entry to Celadon at (48, 11)). The fix: compute the saffron-edge dest's hop-distance
# to SAFFRON and pick the minimum.
class _SaffronWorld:
    """A fake-world whose `route(start, goal)` returns a fixed-length list per saffron-area pair.

    The saffron-area hop distances are computed against SAFFRON (= 0x0A):
      - SAFFRON = 0 hops (immediate goal)
      - ROUTE7_GATE = 1 hop (the only direct Celadon→Saffron gate)
      - PATH_ROUTE5, PATH_ROUTE6, ROUTE12_GATE, PATH_WEST_EAST = 2 hops (gate/path maps adjacent to Saffron)
      - ROUTE7 = 2 hops (Route 7 → ROUTE7_GATE → SAFFRON)
      - PATH_ROUTE8 = 3 hops (PATH_ROUTE8 → Route 7 east → ROUTE7_GATE → SAFFRON)
      - PATH_ROUTE7 = 5 hops (PATH_ROUTE7 → Route 8 west → PATH_ROUTE8 → Route 7 east → ROUTE7_GATE → SAFFRON)
    Distances are returned as lists of `(map, how)` tuples whose length matches the hop count.
    Unknown pairs return None.
    """
    SAFFRON = 0x0A
    ROUTE7 = 0x12
    ROUTE7_GATE = 0x4C
    PATH_ROUTE5 = 0x47
    PATH_ROUTE6 = 0x4A
    PATH_ROUTE7 = 0x4D
    PATH_ROUTE8 = 0x50
    PATH_WEST_EAST = 0x79
    ROUTE12_GATE = 0x57
    # ROUTE_8_WEST (between Cycling Road and Lavender west), not in saffron_maps but is the path
    # out of PATH_ROUTE7. Tests don't need its id — they just verify saffron_step doesn't take it.
    _HOP = 1

    def __init__(self):
        self.maps = {
            self.SAFFRON: {"map": self.SAFFRON},
            self.ROUTE7_GATE: {"map": self.ROUTE7_GATE},
            self.PATH_ROUTE5: {"map": self.PATH_ROUTE5},
            self.PATH_ROUTE6: {"map": self.PATH_ROUTE6},
            self.ROUTE12_GATE: {"map": self.ROUTE12_GATE},
            self.PATH_WEST_EAST: {"map": self.PATH_WEST_EAST},
            self.ROUTE7: {"map": self.ROUTE7},
            self.PATH_ROUTE8: {"map": self.PATH_ROUTE8},
            self.PATH_ROUTE7: {"map": self.PATH_ROUTE7},
        }
        # `route(start, goal)` returns a list of `(next_map, how)` whose length is the hop count.
        # `how` is just a placeholder; saffron_step only inspects the length.
        self._routes = {
            (self.SAFFRON, self.SAFFRON): [],
            (self.ROUTE7_GATE, self.SAFFRON): [(self.SAFFRON, ("edge", "east"))],
            (self.PATH_ROUTE5, self.SAFFRON): [(self.SAFFRON, ("edge", "south"))],
            (self.PATH_ROUTE6, self.SAFFRON): [(self.SAFFRON, ("edge", "south"))],
            (self.ROUTE12_GATE, self.SAFFRON): [(self.SAFFRON, ("edge", "south"))],
            (self.PATH_WEST_EAST, self.SAFFRON): [(self.SAFFRON, ("edge", "south"))],
            (self.ROUTE7, self.SAFFRON): [(self.ROUTE7_GATE, ("edge", "east")),
                                           (self.SAFFRON, ("edge", "east"))],
            (self.PATH_ROUTE8, self.SAFFRON): [(self.ROUTE7, ("edge", "north")),
                                               (self.ROUTE7_GATE, ("edge", "east")),
                                               (self.SAFFRON, ("edge", "east"))],
            # PATH_ROUTE7 (0x4D, west end of underground) loops east through Route 8 west →
            # PATH_ROUTE8 → Route 7 east → ROUTE7_GATE → SAFFRON (5 hops). This is the bug shape:
            # choosing the south edge of Route 7 here walks the runner into PATH_ROUTE7 which has
            # to traverse 5 maps to reach Saffron (instead of 2 via ROUTE7_GATE).
            (self.PATH_ROUTE7, self.SAFFRON): [(0x13, ("edge", "south")),
                                               (self.PATH_ROUTE8, ("edge", "north")),
                                               (self.ROUTE7, ("edge", "north")),
                                               (self.ROUTE7_GATE, ("edge", "east")),
                                               (self.SAFFRON, ("edge", "east"))],
        }

    def route(self, start, goal, *a, **kw):
        return self._routes.get((start, goal))


def _saffron_pref_runner(here, info, walk_target_holder, world=None):
    """A minimal Runner for BUG-0607 tests. The saffron milestone is the active one (mark every
    earlier milestone as done); the drink is already in the bag so saffron_step takes the
    saffron-edge branch. `walk_target_holder` is a dict that the fake `walk` writes into so the
    test can assert the target without doing real grid A*."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon.milestones import MILESTONES
    r = object.__new__(runner_mod.Runner)
    done_before_saffron = [m.id for m in MILESTONES if m.id != "saffron"]
    r.memo = {"drink_bought": True, "done": done_before_saffron}
    r.log = []
    bag_count_addr = 0xD31D + 5
    bag_items_addr = 0xD31E + 5

    def fake_read(addr, n=1):
        if addr == bag_count_addr:
            return [1]
        if addr == bag_items_addr:
            return [0x3C, 1]
        return [0] * max(n, 1)

    r.read = fake_read
    r.pos = lambda: (0, 3)         # the runner's west-edge position on Route 7 (host run 20261017-174506)
    r.io = type("IO", (), {"press": lambda self, *a, **kw: None, "wait": lambda self, *a, **kw: None})()
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    # The runner walks a full grid so any saffron-edge square is reachable from (0, 3).
    r.grid = lambda sprites_block=True: {(x, y): True for x in range(0, 30) for y in range(0, 30)}
    r.world = world if world is not None else _SaffronWorld()

    def fake_walk(target, edge=None):
        walk_target_holder["target"] = target
        return "walk"

    r.walk = fake_walk
    return r


def test_saffron_step_on_route_7_prefers_east_edge_over_south_edge():
    """BUG-0607: on Route 7 (0x12) with both an east edge to ROUTE7_GATE (0x4C) and a south edge
    to PATH_ROUTE7 (0x4D), saffron_step must walk EAST. The previous code picked the closest
    saffron-edge by Manhattan distance (host run 20261017-174506: tied distances — runner walked
    south into PATH_ROUTE7 → 5-hop loop back to Celadon). After the fix, the world-graph
    hop-distance to SAFFRON identifies ROUTE7_GATE (1 hop) vs PATH_ROUTE7 (5 hops); the runner
    walks east.

    The runner's part includes the saffron-edge squares (Route 7's east edge strip and south
    edge strip). With a 30x30 walkable grid (max xs = 29): east strip at y in [10, 11) → saffron-
    edge square (29, 10); south strip at x in [0, 10) → saffron-edge squares (0, 19)..(9, 19).
    Manhattan from (0, 3):
      - to (29, 10): 36
      - to (0, 19): 16
      - to (9, 19): 25
    The closest-by-Manhattan is (0, 19) (south, into PATH_ROUTE7). Without BUG-0607 the runner
    walks south — host run 20261017-174506 picked south because the runner entered Route 7 at
    (0, 3) (west edge, so the south-edge strip x in [0, 10) is closer than the east-edge strip
    at x=29). The BUG-0607 filter rejects PATH_ROUTE7 (5 hops to SAFFRON) and keeps only the east
    edge (1 hop to SAFFRON via ROUTE7_GATE). The runner walks to (29, 10)."""
    from shared.src.lib.game.pokemon import runner as runner_mod, milestones as M
    info = {
        "spans": {"east": [10, 11], "south": [0, 10]},
        "edges": {"east": M.ROUTE7_GATE, "south": M.PATH_ROUTE7},
    }
    walk_target = {}
    r = _saffron_pref_runner(here=M.ROUTE7, info=info, walk_target_holder=walk_target,
                             world=_SaffronWorld())

    out = r.saffron_step(here=M.ROUTE7, info=info)

    assert out == "walk", f"BUG-0607: saffron_step must walk on Route 7 (got {out!r})"
    target = walk_target.get("target")
    assert target is not None, "saffron_step must call walk"
    assert target == (29, 10), (
        f"BUG-0607: saffron_step must prefer east edge (29, 10) over south edge (closest: "
        f"{(0, 19)}). South edge (PATH_ROUTE7) is closer to (0, 3) but leads to a 5-hop loop "
        f"back to Celadon; east edge (ROUTE7_GATE) is 1 hop to SAFFRON. Got {target!r}")
    # The runner must NOT walk to a south-edge square (PATH_ROUTE7).
    assert target not in [(0, 19), (1, 19), (2, 19), (3, 19), (4, 19), (5, 19), (6, 19), (7, 19),
                          (8, 19), (9, 19)], \
        f"BUG-0607: saffron_step must NOT walk south into PATH_ROUTE7 (got {target!r})"


class _NoRouteWorld:
    """SAFFRON is not in the world graph yet (the runner has never been there): no route is known."""

    def route(self, start, goal, *a, **kw):
        return None


def test_saffron_step_on_route_7_takes_the_gate_while_saffron_is_unknown():
    """BUG-0629: until SAFFRON is in the world graph, every saffron-edge ties at 'unknown' in the
    BUG-0607 hop filter, and the Manhattan tie-break walks the runner from the west entry (0, 3) to
    the south edge (PATH_ROUTE7). That is the underground loop back to Celadon (host run
    20261018-143002: maps 19 → 80 → 121 → 77 → 18 → 6, Celadon re-entered every ~85 s). ROUTE7_GATE
    is the gate to Saffron, so with no route known the east edge must still win."""
    from shared.src.lib.game.pokemon import milestones as M
    info = {
        "spans": {"east": [10, 11], "south": [0, 10]},
        "edges": {"east": M.ROUTE7_GATE, "south": M.PATH_ROUTE7},
    }
    walk_target = {}
    r = _saffron_pref_runner(here=M.ROUTE7, info=info, walk_target_holder=walk_target,
                             world=_NoRouteWorld())

    out = r.saffron_step(here=M.ROUTE7, info=info)

    assert out == "walk", f"BUG-0629: saffron_step must walk on Route 7 (got {out!r})"
    assert walk_target.get("target") == (29, 10), (
        f"BUG-0629: with SAFFRON unknown, saffron_step must still walk to the ROUTE7_GATE edge (29, 10), "
        f"not the PATH_ROUTE7 edge (closest by Manhattan: (0, 19)). Got {walk_target.get('target')!r}")


def test_saffron_step_on_path_route_8_walks_north_not_south():
    """BUG-0607: on PATH_ROUTE8 (0x50) with a north edge to Route 7 (0x12) and a south edge to
    Route 8 (0x13), saffron_step must walk NORTH. The north edge leads to Route 7 → ROUTE7_GATE
    → SAFFRON (3 hops total from PATH_ROUTE8). Route 8 (0x13) is NOT a saffron map, so the south
    edge is filtered out by the saffron_maps tuple even before the BUG-0607 hop filter runs. But
    if there were a south edge to a saffron map (e.g. PATH_WEST_EAST 0x79), the BUG-0607 filter
    still picks the closer-to-SAFFRON edge."""
    from shared.src.lib.game.pokemon import runner as runner_mod, milestones as M
    info = {
        "spans": {"north": [0, 10], "south": [0, 10]},
        # north → Route 7 (in saffron_maps). south → Route 8 (NOT in saffron_maps; never a
        # saffron-edge). Add a fake east edge to PATH_WEST_EAST (in saffron_maps, 2 hops to
        # SAFFRON) so the BUG-0607 hop filter has to pick between north (3 hops) and east (2 hops)
        # — and east wins, demonstrating the hop filter chooses correctly.
        "edges": {"north": M.ROUTE7, "south": 0x13, "east": M.PATH_WEST_EAST},
    }
    walk_target = {}
    r = _saffron_pref_runner(here=M.PATH_ROUTE8, info=info, walk_target_holder=walk_target,
                             world=_SaffronWorld())

    out = r.saffron_step(here=M.PATH_ROUTE8, info=info)

    assert out == "walk", f"BUG-0607: saffron_step must walk on PATH_ROUTE8 (got {out!r})"
    target = walk_target.get("target")
    assert target is not None, "saffron_step must call walk"
    # south (Route 8 0x13) is filtered out: not in saffron_maps.
    # BUG-0607 picks the saffron-edge whose dest is closer to SAFFRON:
    #   - north → Route 7 (0x12): 2 hops to SAFFRON (ROUTE7 → ROUTE7_GATE → SAFFRON)
    #   - east → PATH_WEST_EAST (0x79): 1 hop to SAFFRON (PATH_WEST_EAST → SAFFRON)
    # East wins. The east-edge square at x=29, y in [0, 10).
    assert target[0] == 29, (
        f"BUG-0607: saffron_step must walk east (x=29) — PATH_WEST_EAST is 1 hop to SAFFRON vs "
        f"Route 7 (2 hops). Got {target!r}")
    # The runner must NOT walk south (Route 8 is not a saffron-area map).
    assert target not in [(x, 29) for x in range(0, 10)], \
        f"BUG-0607: saffron_step must NOT walk south to Route 8 (got {target!r})"


def test_saffron_step_on_celadon_uses_part_logic_not_hop_filter():
    """BUG-0607 only constrains saffron-edges when the runner is NOT on Celadon. On Celadon, the
    runner might be in a wrong partition (e.g. (39, 20) — BUG-0589/0596) and must walk to the
    closest saffron-edge to satisfy first_hop_ok. The hop-distance filter is unnecessary on
    Celadon (every saffron-edge from Celadon is correct), and the existing BUG-0589/0596 logic
    is unchanged.

    This test confirms the hop-filter is bypassed when the runner's `world.route(dest, SAFFRON)`
    returns None for all saffron-edge dests (e.g. the runner's world graph doesn't know how to
    reach SAFFRON yet). In that case saffron_step falls back to the closest-by-Manhattan path."""
    from shared.src.lib.game.pokemon import runner as runner_mod, milestones as M
    info = {
        "spans": {"east": [10, 11]},
        "edges": {"east": M.ROUTE7},   # the only saffron-edge: east → Route 7
    }
    walk_target = {}
    # A world that returns None for every route — saffron_step can't compute hop distances and
    # falls back to Manhattan (the BUG-0589/0596 path). This is the worst-case at the start of
    # the saffron milestone when the runner has not yet visited any saffron-area map.
    class _EmptyWorld:
        def route(self, *a, **kw):
            return None
    r = _saffron_pref_runner(here=M.CELADON, info=info, walk_target_holder=walk_target,
                             world=_EmptyWorld())

    out = r.saffron_step(here=M.CELADON, info=info)

    assert out == "walk", f"on Celadon, saffron_step must still walk toward the saffron-edge (got {out!r})"
    target = walk_target.get("target")
    assert target is not None, "saffron_step must call walk"
    assert target == (29, 10), (
        f"on Celadon, saffron_step walks to the saffron-edge (29, 10) by Manhattan distance. "
        f"Got {target!r}")


def test_saffron_step_on_route_7_walks_to_the_gate_door_while_the_gate_is_unvisited():
    """BUG-0632: Route 7's east connection leads to SAFFRON (0x0A), so the saffron-edge list is empty on
    Route 7 and saffron_step returned None. go_to_map then took the known world route to SAFFRON, which
    went through PATH_ROUTE7 (warp (5, 13)) and Route 8 (host run 20261018-160003: Celadon → Route 7 →
    PATH_ROUTE7 → Route 8 → PATH_ROUTE8 → underground → Celadon, 1987 s, no milestone change). The gate
    house ROUTE7_GATE (0x4C) is unvisited, and the runner's own west part reaches its west door (11, 9).
    saffron_step must walk to that door, not leave the choice to the known route to SAFFRON."""
    from shared.src.lib.game.pokemon import runner as runner_mod, milestones as M
    from shared.src.lib.game.pokemon.world import World
    route7 = {
        "map": M.ROUTE7, "width": 20, "height": 18, "edges": {"west": M.CELADON, "east": M.SAFFRON},
        "spans": {"west": [0, 18], "east": [0, 18]},
        "warps": [[18, 9, M.ROUTE7_GATE, 2], [18, 10, M.ROUTE7_GATE, 3], [11, 9, M.ROUTE7_GATE, 0],
                  [11, 10, M.ROUTE7_GATE, 1], [5, 13, M.PATH_ROUTE7, 0]],
        "parts": {"warp": [1, 1, 0, 0, 0], "edge": {"west": [0], "east": [1, 2]}, "down": [], "player": 0},
    }
    path_route7 = {
        "map": M.PATH_ROUTE7, "width": 8, "height": 8, "edges": {}, "spans": {},
        "warps": [[3, 7, M.ROUTE7, 4], [4, 7, M.ROUTE7, 4], [4, 4, 0x79, 0]],
        "parts": {"warp": [0, 0, 0], "edge": {}, "down": [], "player": 0},
    }
    info = dict(route7)
    walk_target = {}
    r = _saffron_pref_runner(here=M.ROUTE7, info=info, walk_target_holder=walk_target,
                             world=World({M.ROUTE7: route7, M.PATH_ROUTE7: path_route7}))
    r.stuck = 0
    r.no_route_ticks = 0

    out = r.saffron_step(here=M.ROUTE7, info=info)

    assert out == "walk", f"BUG-0632: saffron_step must walk toward the gate on Route 7 (got {out!r})"
    assert walk_target.get("target") == (11, 9), (
        f"BUG-0632: the west door of ROUTE7_GATE is (11, 9); PATH_ROUTE7's warp (5, 13) leads the loop. "
        f"Got {walk_target.get('target')!r}")


def test_saffron_without_drink_rebuys_through_the_mart_door_not_the_marked_one():
    """BUG-0634: host run 20261018-193002 stood at Celadon (39, 20) for 600 ticks with no event but
    `hm_failed`. The bag held no drink (saffron_step's note_items snapshot), so saffron_step returned None
    while `drink_bought` stayed True: the MART_ROOF buy was skipped for ever and go_to_map routed the
    runner to the roof through the Celadon Mart door (39, 19). That door was already in `bad_warps`, and
    it is the only route, so go_to_map kept walking into it (the warp_unusable escalation sits behind
    `if cands:` and never ran for the sole door). The fix clears the stale flag on Celadon and retries
    the sole door instead of walking into the mark forever."""
    from shared.src.lib.game.pokemon import runner as runner_mod, overworld
    from shared.src.lib.game.pokemon.world import World
    celadon = {"map": M.CELADON, "width": 50, "height": 36, "edges": {}, "spans": {},
               "warps": [[39, 19, 0x88, 0]], "parts": {"warp": [0], "edge": {}, "down": [], "player": 0}}
    mart_5f = {"map": 0x88, "width": 10, "height": 10, "edges": {}, "spans": {},
               "warps": [[5, 5, M.MART_ROOF, 0]], "parts": {"warp": [0], "edge": {}, "down": [], "player": 0}}
    r = object.__new__(runner_mod.Runner)
    done_before_saffron = [m.id for m in M.MILESTONES if m.id != "saffron"]
    r.memo = {"guide_i": 9, "drink_bought": True, "done": done_before_saffron, "bad_warps": [[M.CELADON, 39, 19]]}
    r.world = World({M.CELADON: celadon, 0x88: mart_5f})
    r.read = lambda addr, n=1: [0] * max(n, 1)          # empty bag, no sprites, map 0
    r.pos = lambda: (39, 20)
    r.grid = lambda sprites_block=True: overworld.Grid({(x, y): True for x in range(50) for y in range(36)})
    r.event = lambda kind, **facts: None
    r.stuck, r.no_route_ticks = 0, 0
    walked = []
    r.walk = lambda target, edge=None: walked.append(target) or "walk"
    info = dict(celadon)

    assert r.saffron_step(here=M.CELADON, info=info) is None
    assert r.memo["drink_bought"] is False, "BUG-0634: no drink in the bag means the flag must not say one was bought"
    assert r.go_to_map(M.CELADON, M.MART_ROOF, info) == "walk"
    assert walked == [(39, 19)], f"BUG-0634: the mart door is the only route; got walk to {walked!r}"
    assert [M.CELADON, 39, 19] not in r.memo["bad_warps"], "BUG-0634: the sole door must be retried, not kept marked"


def test_warp_retried_once_then_dead_is_not_walked_again():
    """BUG-0635: the BUG-0634 retry looped. Celadon's mart door (39, 19) is the only route to the roof, is marked
    unusable, and the retry drops the mark. The runner walks into it, fails six steps, marks it again, and
    the next go_to_map retried it again: 98 UP presses at (39, 20). Now a door that failed after its one
    retry is dead for the milestone: go_to_map must not return a walk to it (no other route here, so no route)."""
    from shared.src.lib.game.pokemon import runner as runner_mod, overworld
    from shared.src.lib.game.pokemon.world import World
    celadon = {"map": M.CELADON, "width": 50, "height": 36, "edges": {}, "spans": {},
               "warps": [[39, 19, 0x88, 0]], "parts": {"warp": [0], "edge": {}, "down": [], "player": 0}}
    mart_5f = {"map": 0x88, "width": 10, "height": 10, "edges": {}, "spans": {},
               "warps": [[5, 5, M.MART_ROOF, 0]], "parts": {"warp": [0], "edge": {}, "down": [], "player": 0}}
    r = object.__new__(runner_mod.Runner)
    r.memo = {"bad_warps": [[M.CELADON, 39, 19]]}
    r.world = World({M.CELADON: celadon, 0x88: mart_5f})
    r.read = lambda addr, n=1: [0] * max(n, 1)
    r.pos = lambda: (39, 20)
    r.grid = lambda sprites_block=True: overworld.Grid({(x, y): True for x in range(50) for y in range(36)})
    r.event = lambda kind, **facts: None
    r.no_route_ticks = 0
    walked = []
    r.walk = lambda target, edge=None: walked.append(target) or "walk"
    info = dict(celadon)

    # first failure after the retry: the door is walked into, six steps stuck, marked again
    r.stuck = 6
    assert r.go_to_map(M.CELADON, M.MART_ROOF, info) == "walk"
    assert walked == [(39, 19)], "BUG-0635: the first retry walks to the door once"
    assert [M.CELADON, 39, 19] in r.memo["bad_warps"]

    # second failure: the door is dead, the next go_to_map must not walk to it again
    r.stuck = 6
    out = r.go_to_map(M.CELADON, M.MART_ROOF, info)
    assert walked == [(39, 19)], f"BUG-0635: the dead door must not be walked to again; walks={walked!r} out={out!r}"
    assert out == "no route", f"BUG-0635: no other route from Celadon, so no route; got {out!r}"
    assert [M.CELADON, 39, 19] in r.memo["bad_warps"], "BUG-0635: the dead door stays marked"


def test_a_dead_end_entered_by_an_edge_is_left_and_its_exits_are_not_taken_again():
    """BUG-0639: Saffron (10) north edge meets Route 7 (16), whose south strip spans parts 6-8. The crossing at
    (18, 0) lands in part 8 at (8, 35): a pocket whose only other door is an unvisited gate house. The landing
    part is unknown to the world graph, so from Saffron the route to a Pokémon Center goes north through the
    pocket, and from the pocket the route goes back south and round by Route 6. Host run 20261018-211502 walked
    10 <-> 16 for 30 minutes. The dead end must be marked on the Saffron north exits that land in it, and those
    exits must no longer be the first hop of a route."""
    from shared.src.lib.game.pokemon import runner as runner_mod, overworld
    from shared.src.lib.game.pokemon.world import World
    A, B, C, D = 10, 16, 3, 17
    a = {"map": A, "width": 40, "height": 36, "edges": {"north": B, "south": D},
         "spans": {"north": [10, 30], "south": [10, 30]}, "warps": [],
         "parts": {"warp": [], "edge": {"north": [1], "south": [1]}, "down": [], "player": 1}}
    b = {"map": B, "width": 20, "height": 36, "edges": {"north": C, "south": A},
         "spans": {"north": [0, 20], "south": [0, 20]}, "warps": [(5, 5, D, 0)],
         "parts": {"warp": [0], "edge": {"north": [0], "south": [6, 7, 8]}, "down": [], "player": 8}}
    d = {"map": D, "width": 20, "height": 36, "edges": {"north": A}, "spans": {"north": [0, 20]},
         "warps": [(3, 3, B, 0)], "parts": {"warp": [0], "edge": {"north": [0]}, "down": [], "player": 0}}
    c = {"map": C, "width": 20, "height": 36, "edges": {"south": B}, "spans": {"south": [0, 20]}, "warps": [],
         "parts": {"warp": [], "edge": {"south": [0]}, "down": [], "player": 0}}
    pocket = overworld.Grid({(x, y): y <= 10 or y >= 30 for x in range(20) for y in range(36)})   # rows 11-29 are rock
    open_a = overworld.Grid({(x, y): True for x in range(40) for y in range(36)})
    r = object.__new__(runner_mod.Runner)
    r.memo = {"entry": {"from": A, "side": "north", "exit": [18, 0], "map": B, "landing": [8, 35]}}
    r.world = World({A: a, B: b, C: c, D: d})
    cur, pos = {}, {"xy": (8, 35)}
    r.grid = lambda sprites_block=True: cur["walk"]
    r.pos = lambda: pos["xy"]
    r.event = lambda kind, **facts: None
    r.stuck, r.no_route_ticks = 0, 0
    walked = []
    r.walk = lambda target, edge=None: walked.append((target, edge)) or "walk"

    cur["walk"] = pocket
    assert r.go_to_map(B, C, dict(b)) == "walk"
    assert walked[-1][1] == "south", f"BUG-0639: the pocket's way on is back south; walked {walked!r}"
    assert sorted(x for m, x, _ in r.memo.get("bad_exits", []) if m == A) == list(range(10, 30)), \
        "BUG-0639: the north exits of Saffron that land in the pocket must be marked"

    cur["walk"], pos["xy"] = open_a, (18, 1)
    walked.clear()
    assert r.go_to_map(A, C, dict(a)) == "walk"
    assert walked[-1][1] == "south", \
        f"BUG-0639: every north exit of Saffron leads into the pocket, so the route is round by Route 6; walked {walked!r}"


def test_a_pocket_entered_by_an_edge_takes_its_unvisited_door_before_going_back():
    """BUG-0640: Route 5's south pocket (part 8, entered from Saffron) has a door at (10, 33) to the gate house (map 70),
    never visited. BUG-0639 read the pocket as a dead end and went back to Saffron, where the north exits it had just
    marked left no way on: host run 20261018-211502 replayed on the emulator ended `lost` on Route 5 after 1360 ticks
    without a route. The unvisited door is the way on: it is walked to, both while a route back exists and once none is
    left."""
    from shared.src.lib.game.pokemon import runner as runner_mod, overworld
    from shared.src.lib.game.pokemon.world import World
    A, B, C, G = 10, 16, 3, 70
    a = {"map": A, "width": 40, "height": 36, "edges": {"north": B}, "spans": {"north": [10, 30]}, "warps": [],
         "parts": {"warp": [], "edge": {"north": [1]}, "down": [], "player": 1}}
    b = {"map": B, "width": 20, "height": 36, "edges": {"north": C, "south": A},
         "spans": {"north": [0, 20], "south": [0, 20]}, "warps": [(10, 33, G, 0)],
         "parts": {"warp": [8], "edge": {"north": [0], "south": [6, 7, 8]}, "down": [], "player": 8}}
    c = {"map": C, "width": 20, "height": 36, "edges": {"south": B}, "spans": {"south": [0, 20]}, "warps": [],
         "parts": {"warp": [], "edge": {"south": [0]}, "down": [], "player": 0}}
    pocket = overworld.Grid({(x, y): y >= 30 for x in range(20) for y in range(36)})   # the gate house walls it off
    r = object.__new__(runner_mod.Runner)
    r.memo = {"entry": {"from": A, "side": "north", "exit": [18, 0], "map": B, "landing": [8, 35]}}
    r.world = World({A: a, B: b, C: c})
    r.grid = lambda sprites_block=True: pocket
    r.pos = lambda: (8, 35)
    r.event = lambda kind, **facts: None
    r.stuck, r.no_route_ticks = 0, 0
    walked = []
    r.walk = lambda target, edge=None: walked.append((target, edge)) or "walk"

    assert r.go_to_map(B, C, dict(b)) == "walk"
    assert walked[-1][0] == (10, 33), f"BUG-0640: the pocket's way on is the unvisited gate house door; walked {walked!r}"
    assert not r.memo.get("bad_exits"), "BUG-0640: a pocket with an unvisited door is no dead end"

    r.memo["bad_exits"] = [[B, x, 35] for x in range(20)]   # the way back already closed (the state BUG-0639 left)
    walked.clear()
    assert r.go_to_map(B, C, dict(b)) == "walk"
    assert walked[-1][0] == (10, 33), f"BUG-0640: with no route left the door is still taken; walked {walked!r}"


def test_a_cutscene_with_no_text_box_gets_an_a_press_on_the_twentieth_busy_tick():
    """BUG-0648: the input-ignore flag held with no text box on screen made the busy branch only wait, forever.
    The 20th busy tick (about 5 s) presses A once; a tick that is not busy resets the count."""
    mem = _Mem()
    mem.m[ADDR["joy_ignore"]] = 0xFC                 # a cutscene owns the controls, no text box is drawn
    r = _runner(mem)
    r.in_intro = lambda: False
    r.learn_tick = lambda: None
    r.overworld_tick = lambda: "overworld"
    assert [r.tick() for _ in range(25)] == ["cutscene"] * 25
    assert r.io.keys == ["A"], f"BUG-0648: one A on the 20th busy tick, got {r.io.keys!r}"
    assert [e["ticks"] for e in r.log if e["kind"] == "cutscene_stuck"] == [20]
    assert r.busy_ticks == 25
    mem.m[ADDR["joy_ignore"]] = 0                    # the cutscene ends
    assert r.tick() == "overworld"
    assert r.busy_ticks == 0


def test_a_deferred_surf_is_played_by_the_good_rod_and_cleared_once_learned():
    """BUG-0673: host run 20261019-113003 stalled `deferred_end` at 5 badges: the Safari hunt had set surf_deferred and
    nothing looked for a Surf learner again; strength_deferred stayed set though Hitmonlee knew Strength. The
    `surf_learner` milestone (Good Rod in Fuchsia) comes next, a wild Surf learner is caught at any party size, and a
    defer flag whose move the party knows is cleared with the milestones it let through."""
    from shared.src.lib.game.pokemon import milestones as M
    from shared.src.lib.game.pokemon import runner as runner_mod
    ids = [m.id for m in M.MILESTONES]
    assert ids.index("surf_learner") == ids.index("surf") + 1
    no_surf, surfer = _party_read([[22, 75], [10, 15], [70]]), _party_read([[22, 75], [57], [70]])
    memo = {"done": [i for i in ids if i != "surf_learner"], "surf_deferred": True, "strength_deferred": True}
    assert M.current(no_surf, memo).id == "surf_learner"
    assert M.current(surfer, {"done": ids[:ids.index("surf_learner")]}).id != "surf_learner"
    # a wild Surf learner is wanted with a party of 3 (the backup rule stops at 2)
    big = battle.options(_wild_battle(party=(0x99, 1, 2), enemy_hp=9).read, GameData(_rom()))
    assert battle.heuristic_choice(big, must_catch=True) == "catch"
    # the stale strength flag is cleared now, the surf one once Surf is known; their skipped milestones re-open
    r = object.__new__(runner_mod.Runner)
    r.memo, r.log, r.read = memo, [], no_surf
    r.lift_defers()
    assert "strength_deferred" not in memo and memo["surf_deferred"] and "seafoam" in memo["done"]   # BUG-0690: Surf only
    assert "earth_badge" in memo["done"]
    r.read = surfer
    r.lift_defers()
    assert "surf_deferred" not in memo and not {"seafoam", "volcano_badge", "earth_badge"} & set(memo["done"])
    assert [e["flag"] for e in r.log if e["kind"] == "deferred_cleared"] == ["strength_deferred", "surf_deferred"]


def test_seafoam_guide_surfs_from_fuchsia_and_the_runner_gets_on_the_water(monkeypatch):
    """BUG-0681: the seafoam guide started on Cinnabar and water was never walkable, so the run was `lost` at Fuchsia
    (31, 22) with Surf taught. The guide now goes Fuchsia, Route 19, Route 20; water is a way once Surf is known, and a
    land-to-water step is a Surf menu trip."""
    from shared.src.lib.game.pokemon import hm, overworld, runner as runner_mod
    ms = next(m for m in M.MILESTONES if m.id == "seafoam")
    assert ms.maps[0] == M.FUCHSIA and {M.ROUTE19, M.ROUTE20} <= set(ms.area)   # BUG-0693: on by Pallet and Route 21
    walk = overworld.Grid({(x, y): x < 3 for x in range(30) for y in range(3)})   # a shore, then the sea
    walk.water = {(x, y) for x in range(3, 30) for y in range(3)}
    walk.update({sq: True for sq in walk.water})
    path = overworld.astar(walk, (1, 1), (8, 1))
    assert path == ["RIGHT"] * 7                         # over the water, no other way
    grid = overworld.Grid({(x, 0): x < 2 for x in range(5)})
    grid.water = {(2, 0), (3, 0), (4, 0)}
    r = object.__new__(runner_mod.Runner)
    r.memo, r.log, r.rom, r.stuck = {}, [], b"\x00", 0
    r.read = lambda addr, n=1: [7]
    at = [(1, 0)]
    r.pos = lambda: at[0]
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    r.step = lambda d: True
    r.party = lambda: [{"name": "POISSIRENE"}] * 4
    r.grid = lambda sprites_block=True: _with_surf(grid)
    monkeypatch.setattr(hm, "surf_user", lambda read: 3)
    monkeypatch.setattr(hm, "use_surf", lambda runner: False)
    monkeypatch.setattr(runner_mod, "links", lambda read: {"warps": []})
    assert r.walk((4, 0)) == "surf failed" and r.walk((4, 0)) == "surf failed"
    assert r.memo["walls"] == {"7": [[2, 0]]} and r.log[-1]["kind"] == "surf_failed"
    r.memo = {}

    def surf(runner):
        at[0] = (2, 0)                                   # Gen 1: Surf hops the player onto the water square
        return True
    monkeypatch.setattr(hm, "use_surf", surf)
    assert r.walk((4, 0)) == "surf"
    assert r.log[-1] == {"kind": "surf", "map": 7, "at": [2, 0], "pokemon": "POISSIRENE"}
    assert r.walk((4, 0)) == "walk"                      # already on the water: a plain step, no second menu trip


def test_seafoam_area_holds_the_good_rod_house_so_the_pond_is_left_by_its_front_door():
    """BUG-0683: the Surf learner is fished at Fuchsia's pond (31, 22), whose only way out is the Good Rod house's back
    door. Off the seafoam area the runner headed "back to Fuchsia" by that same back door and ping-ponged pond <-> house
    for a whole run. In the area, the house leads on to Route 19: out its front door (2, 7), then Fuchsia's south edge."""
    from shared.src.lib.game.pokemon.world import World
    ms = next(m for m in M.MILESTONES if m.id == "seafoam")
    assert M.GOOD_ROD_HOUSE in ms.area
    w = World({7: {"edges": {"south": M.ROUTE19}, "warps": [[31, 27, M.GOOD_ROD_HOUSE, 1], [31, 24, M.GOOD_ROD_HOUSE, 0]]},
               M.GOOD_ROD_HOUSE: {"edges": {}, "warps": [[2, 0, 7, 1], [2, 7, 7, 0]]}})
    assert w.route(M.GOOD_ROD_HOUSE, M.ROUTE19)[-1] == (M.ROUTE19, ("edge", "south"))


def test_seafoam_b1f_takes_the_ladder_into_the_part_of_b2f_that_leads_on():
    """BUG-0689: on Seafoam B1F the next path map is B2F; its nearest ladder (4, 2) lands in a dead-end corner of B2F
    whose only way on to B3F is back up, and the runner went up and down that ladder for a whole run. The goal part of
    B2F is the one with the warp to B3F: the route takes the ladder (13, 7) instead."""
    from shared.src.lib.game.pokemon.world import World
    w = World({159: {"edges": {}, "warps": [[4, 2, 160, 0], [7, 5, 192, 4], [13, 7, 160, 2], [19, 15, 160, 3],
                                            [23, 15, 192, 6], [25, 11, 160, 5], [25, 3, 192, 5]],
                     "parts": {"warp": [0, 0, 0, 0, 2, 2, 1], "edge": {}, "down": []}},
               160: {"edges": {}, "warps": [[5, 3, 159, 0], [5, 13, 161, 0], [13, 7, 159, 2], [19, 15, 159, 3],
                                            [25, 3, 161, 3], [25, 11, 159, 5], [25, 14, 161, 4]],
                     "parts": {"warp": [0, 2, 2, 2, 1, 3, 3], "edge": {}, "down": []}}})
    assert w.route(159, 160, start_part=0) == [(160, ("warp", (4, 2)))]          # the dead-end ladder: the stall
    goal_part = w.part_with_warp_to(160, 161)
    assert goal_part == 2
    assert w.route(159, 160, start_part=0, goal_part=goal_part) == [(160, ("warp", (13, 7)))]


def _with_surf(grid):
    out = type(grid)(grid)
    out.water, out.cuts, out.jumps, out.walls = grid.water, set(), {}, set()
    out.update({sq: True for sq in grid.water})
    return out


def test_seafoam_is_done_at_cinnabar_without_the_boulder_puzzle():
    """BUG-0690: run 20261019-150537 stood 300 ticks on Seafoam B3F (12, 6): the puzzle plan's first "boulder" was the
    player's own square, so the walk to it never moved. In Generation I the boulders only open Articuno's floor; Route 20
    is surfed to Cinnabar. The milestone ends at Cinnabar, the runner plays no Seafoam puzzle, a strength_deferred skips
    nothing, and a puzzle plan cached on one floor is never replayed on another."""
    from shared.src.lib.game.pokemon import milestones as M
    from shared.src.lib.game.pokemon import runner as R
    ms = {m.id: m for m in M.MILESTONES}["seafoam"]
    assert ms.done(_mem_read({M.ADDR["map"]: [M.CINNABAR_ISLAND]}), {})
    assert not ms.done(_mem_read({M.ADDR["map"]: [M.SEAFOAM_B4F]}), {"strength_deferred": True})
    assert M.DEFERRED_BY["strength_deferred"] == ()
    r = R.Runner.__new__(R.Runner)
    r.memo, r.read = {"seafoam_puzzle_map": M.SEAFOAM_B3F, "seafoam_plan": [[[12, 6], "DOWN", 3]]}, _mem_read({})
    assert r.story_step(ms, M.SEAFOAM_B3F, {}) is None
    assert r.strength_puzzle_step(M.VICTORY_ROAD_2F, {}) is None


def test_a_saved_guide_pointer_past_a_shorter_route_is_clamped():
    """BUG-0690: the save stalled on Seafoam B3F with guide_i = 6 (the old 8-map seafoam route); the new route has 4 maps,
    and the first tick of run 978c33a8 died with "list index out of range" on `maps[i]`."""
    import inspect
    from shared.src.lib.game.pokemon import runner as R
    src = inspect.getsource(R.Runner.overworld_tick)
    assert "min(self.memo.get(GUIDE, 0), len(maps) - 1)" in src


def test_seafoam_reaches_cinnabar_by_pallet_and_route21_not_route20():
    """BUG-0693: Route 20's Fuchsia side meets the Cinnabar side only through the Seafoam Islands (boulder puzzle): the
    run 20261019-152852 went in and out of the cave for 5 min. The guide walks back to Pallet and surfs Route 21 south;
    a save standing on Route 20 or in the islands is in `area`, so the guide leads on from there."""
    ms = {m.id: m for m in M.MILESTONES}["seafoam"]
    assert ms.maps[0] == M.FUCHSIA and ms.maps[-3:] == [M.PALLET, M.ROUTE21, M.CINNABAR_ISLAND]
    assert M.ROUTE20 not in ms.maps and M.ROUTE20 in ms.area and M.SEAFOAM_1F in ms.area


def test_seafoam_goes_by_diglett_cave_not_back_over_route4_ledge():
    """BUG-0694: run 20261019-160255 went from Cerulean west to Route 4, whose ledge is one-way, then ping-ponged in
    Route 5's pocket for 5 min. The guide leaves Route 12 west by Route 11 and Diglett's Cave to Route 2."""
    ms = {m.id: m for m in M.MILESTONES}["seafoam"]
    assert not {M.CERULEAN, M.ROUTE4, M.ROUTE3, M.PEWTER, M.LAVENDER} & set(ms.maps)
    i = ms.maps.index
    assert i(M.ROUTE12) < i(M.ROUTE11) < i(M.DIGLETT_ROUTE11) < i(M.DIGLETTS_CAVE) < i(M.DIGLETT_ROUTE2) < i(M.ROUTE2) \
        < i(M.VIRIDIAN) < i(M.PALLET)


def test_a_cleared_stall_forgets_the_way_marks_that_walled_it_in():
    """BUG-0694: run 20261019-160255 kept Route 5's exits to Saffron and Cerulean marked bad from older milestones and
    ping-ponged in the gate house. Clearing the lock drops the way-marks with the counters."""
    from shared.src.lib.game.pokemon import stall
    memo = {"bad_exits": [[16, 10, 35]], "bad_warps": [[6, 39, 19]], "warp_retried": [[6, 39, 19]], "entry": {"map": 16},
            "lost": [70, 7], "hm_tries": {"1": 3}, "stall": {"t": 1}, "no_progress_runs": 2, "milestone": "seafoam", "walls": {}}
    stall.forget_on_unlock(memo)
    assert memo == {"milestone": "seafoam", "walls": {}}



def test_volcano_badge_waits_for_the_secret_key_from_the_mansion_basement():
    """BUG-0697: run 20261019-180126 walked into Blaine's gym door for 5 min: "La porte est fermée...". The door opens with
    the Secret Key, an item ball on the Pokémon Mansion's B1F (2F north-west stairs, 3F switch and hole, 1F, B1F)."""
    ids = [m.id for m in M.MILESTONES]
    assert ids.index("seafoam") < ids.index("secret_key") == ids.index("volcano_badge") - 1
    ms = {m.id: m for m in M.MILESTONES}["secret_key"]
    assert ms.maps == [M.CINNABAR_ISLAND, M.MANSION_1F, M.MANSION_2F, M.MANSION_3F, M.MANSION_1F, M.MANSION_B1F]
    assert set(ms.area) == set(M.MANSION) and "secret_key" in M.DEFERRED_BY["surf_deferred"]
    assert not ms.done(lambda a, n: [0] * n, {}) and ms.done(lambda a, n: [0] * n, {"surf_deferred": True})


def test_mansion_3f_presses_the_switch_when_the_holes_are_gated_then_takes_the_hole():
    """BUG-0697: 3F's holes are behind gates the floor's switch opens; the hole (16, 14) drops into 1F's stairs part."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    grid = overworld.Grid({(x, y): x < 15 for x in range(30) for y in range(18)})   # the holes' side is gated
    r = object.__new__(runner_mod.Runner)
    walked = []
    r.memo, r.grid, r.pos = {}, lambda sprites_block=True: grid, lambda: (5, 12)
    r.walk = lambda target, edge=None: walked.append(target) or "walk"
    assert r.mansion_step(runner_mod.MANSION_3F) == "walk" and walked == [runner_mod.MANSION_3F_SWITCH_SPOT]
    grid.update({(x, y): True for x in range(30) for y in range(18)})          # the switch opened the gates
    r.mansion_step(runner_mod.MANSION_3F)
    assert walked[-1] == runner_mod.MANSION_HOLES[0] == (16, 14) and r.memo["mansion_on_3f"]


def test_prepare_for_the_mansion_heals_at_cinnabar_not_back_in_viridian():
    """BUG-0698: run 20261019-190740's `prepare` for `secret_key` knew no Center on Cinnabar, walked Route 21, Pallet and
    Route 1 to Viridian's, then explored Viridian's houses (back over Route 1 read as a dead end) until the stall."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon.world import World
    assert {runner_mod.CINNABAR_CENTER, runner_mod.SAFFRON_CENTER} <= set(runner_mod.POKEMON_CENTERS)
    world = World({M.CINNABAR_ISLAND: {"edges": {"north": 0x20}, "warps": [[11, 11, runner_mod.CINNABAR_CENTER, 0]]},
                   runner_mod.CINNABAR_CENTER: {"edges": {}, "warps": [[3, 7, M.CINNABAR_ISLAND, 2]]},
                   0x20: {"edges": {"north": 0x00, "south": M.CINNABAR_ISLAND}, "warps": []},
                   0x00: {"edges": {"north": 0x0C, "south": 0x20}, "warps": []},
                   0x0C: {"edges": {"north": 0x01, "south": 0x00}, "warps": []},
                   0x01: {"edges": {"south": 0x0C}, "warps": [[23, 25, 0x29, 0]]},
                   0x29: {"edges": {}, "warps": [[3, 7, 0x01, 0]]}})
    r = object.__new__(runner_mod.Runner)
    went = []
    r.memo, r.world = {"prepared": []}, world
    r.go_to_map = lambda here, dest, info: went.append(dest) or "walk"
    r.prepare(next(m for m in M.MILESTONES if m.id == "secret_key"), M.CINNABAR_ISLAND)
    assert went == [runner_mod.CINNABAR_CENTER]


def test_mansion_b1f_makes_room_in_a_full_bag_before_the_secret_key_ball():
    """BUG-0699: with 20 kinds of items in the bag the Secret Key's ball (5, 13) answered "no room"; it was marked taken
    all the same and the runner stood above it. A Nugget is tossed first, and a ball still on the floor is not taken."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"balls_taken": [[runner_mod.MANSION_B1F, 5, 13]]}
    r.note_items = lambda: None
    full = [0x31] + list(range(100, 119))
    tossed = []
    r.read = lambda addr, n=1: [0] * n
    r.event = lambda *a, **k: None
    orig_bag, orig_toss, orig_sprites = runner_mod.bag, runner_mod.hm.toss_item, runner_mod.overworld.screen_sprites
    try:
        runner_mod.bag = lambda read: {i: 1 for i in full}
        runner_mod.hm.toss_item = lambda self: tossed.append(0x31) or 0x31
        assert r.mansion_step(runner_mod.MANSION_B1F) == "toss item" and tossed == [0x31]
        full.remove(0x31)
        runner_mod.overworld.screen_sprites = lambda read: [(runner_mod.BALL_PICTURE, (5, 13), False)]
        r.next_ball = lambda here: (5, 13) if [here, 5, 13] not in r.memo["balls_taken"] else None
        r.take_ball = lambda here, ball: f"take {ball}"
        assert r.mansion_step(runner_mod.MANSION_B1F) == "take (5, 13)"
    finally:
        runner_mod.bag, runner_mod.hm.toss_item, runner_mod.overworld.screen_sprites = orig_bag, orig_toss, orig_sprites


def test_mansion_b1f_keeps_the_mark_of_a_taken_ball_off_screen_and_marks_one_seen_hidden(monkeypatch):
    """BUG-0703: a taken ball reads hidden (image 0xFF) only inside the visible window; off screen it looks like one still on
    the floor. The BUG-0699 retry dropped the mark of every such ball, so at (18, 20) the runner went for (19, 25) and at
    (18, 21), where it shows hidden, turned back for the next one: 5 min on two squares. Only a ball on screen and not hidden
    drops its mark, and a ball on screen and hidden is marked taken."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    here = runner_mod.MANSION_B1F
    r = object.__new__(runner_mod.Runner)
    r.memo = {"balls_taken": [[here, 10, 2]]}
    r.note_items = lambda: None
    r.read = lambda addr, n=1: [0] * n
    r.event = lambda *a, **k: None
    monkeypatch.setattr(runner_mod, "bag", lambda read: {1: 1})
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites", lambda read: [(runner_mod.BALL_PICTURE, (19, 25), True)])
    r.next_ball = lambda h: None
    r.mansion_switch_toward = lambda h, goals: None
    r.mansion_step(here)
    assert [here, 10, 2] in r.memo["balls_taken"]   # off screen: the mark stays
    assert [here, 19, 25] in r.memo["balls_taken"]   # on screen and hidden: taken


def test_cinnabar_gym_walks_to_the_quiz_machine_in_reach_when_blaine_is_behind_the_gates(monkeypatch):
    """BUG-0705: Blaine (3, 3) is behind six quiz gates. goal_action aimed at him, found no path and shuffled (16, 8) <->
    (15, 8) for 5 min. With him out of reach the nearest machine in reach not answered yet is walked to (the square below
    it), and once all in reach are answered the runner waits for the gate before asking them again."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "leaders_seen": ["volcano_badge"]}
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.read = lambda addr, n=1: [runner_mod.CINNABAR_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (16, 8)
    r.grid = lambda sprites_block=True: {}
    reach = {(16, 8), (15, 8)}   # the entrance room: machine 0 (15, 7) is faced from (15, 8)
    monkeypatch.setattr(runner_mod.overworld, "astar", lambda walk, a, b: [] if tuple(b) in reach else None)
    monkeypatch.setattr(runner_mod.overworld, "sprite_list", lambda read: [(10, (3, 3)), (12, (17, 8)), (36, (16, 13))])
    walked = []
    r.walk = lambda target, edge=None: walked.append(tuple(target)) or "walk"
    assert r.goal_action(type("M", (), {"id": "volcano_badge"})()) == "walk"
    assert walked == [(15, 8)]
    r.memo["quiz_done"] = [0]   # answered, the gate not redrawn yet: wait, do not ask again at once
    for _ in range(runner_mod.QUIZ_IDLE_TICKS - 1):
        assert r.cinnabar_quiz() == "quiz wait"
    assert r.memo["quiz_done"] == [0]
    r.cinnabar_quiz()
    assert r.memo["quiz_done"] == []   # Blaine still shut off after a long wait: every machine is asked again


def test_volcano_badge_is_done_on_its_own_bit_without_the_marsh_badge():
    """BUG-0707: Sabrina is skipped, so Blaine's badge is the 6th: a count of 7 never came and the runner stood by Blaine."""
    from shared.src.lib.game.pokemon import milestones
    ms = {m.id: m for m in milestones.MILESTONES}
    mem = {milestones.BADGES: [0b0001_1111]}   # five badges, no Volcano
    read = lambda a, n=1: mem.get(a, [0] * n)[:n]
    assert not ms["volcano_badge"].done(read, {})
    mem[milestones.BADGES] = [0b0101_1111]     # + Volcano, no Marsh: 6 badges
    assert ms["volcano_badge"].done(read, {}) and ms["secret_key"].done(read, {})


def test_route6_gate_is_no_guide_map_and_silph_co_comes_before_sabrina():
    """BUG-0710: host run 20261019-213934 stalled `no_progress` on `marsh_badge` on Route 6 (10, 1). Rocket grunts stand
    below Saffron's doors (the memo's walls (7, 6), (34, 4), (13, 12)), the gym's among them, until Giovanni is beaten in
    Silph Co., so Saffron was a dead end. And Route 6's gate (0x49) stands inside Route 6: its north door lands on Route 6's
    north strip, so with the gate as the guide map after Route 6 the runner went in and out of it for 5 min. Silph Co.
    comes first, by its stairs to 11F; the gate is an area map, never a guide map."""
    from shared.src.lib.game.pokemon import milestones as M
    by = {m.id: m for m in M.MILESTONES}
    for mid in ("silph_co", "earth_badge"):
        assert M.ROUTE6_GATE not in by[mid].maps and M.ROUTE6_GATE in by[mid].area
        i = by[mid].maps.index(M.ROUTE6)
        assert {by[mid].maps[i - 1], by[mid].maps[i + 1]} == {M.SAFFRON, M.VERMILION}
    silph = by["silph_co"].maps
    assert silph[silph.index(M.SAFFRON) + 1] == M.SILPH_CO_1F and silph[-1] == M.SILPH_CO_11F == 0xEB
    assert by["marsh_badge"].maps[-2:] == [M.SAFFRON, M.SAFFRON_GYM]
    read = _mem_read({M.BADGES: [0x5F], M.ADDR["map"]: [M.SILPH_CO_11F], M.BAG_COUNT: [0]})
    assert not by["silph_co"].done(read, {})
    read = _mem_read({M.BADGES: [0x5F], M.ADDR["map"]: [M.SILPH_CO_11F], M.BAG_COUNT: [1], M.BAG_ITEMS: [M.MASTER_BALL, 1, 0xFF]})
    assert by["silph_co"].done(read, {})


def test_sabrina_gym_room_is_reached_by_a_chain_of_teleporter_pads():
    """BUG-0712: Saffron's gym is rooms joined only by pads leading to the same map; the walk saw no path to Sabrina
    and stood at (8, 13) 5 min. pad_route picks the first pad of the shortest chain (three rooms in a row here)."""
    from shared.src.lib.game.pokemon.world import pad_route
    walk = {(x, y): x not in (4, 9) for x in range(14) for y in range(3)}   # three rooms, walls at x 4 and 9
    warps = [(3, 1, M.SAFFRON_GYM, 1), (5, 1, M.SAFFRON_GYM, 0), (8, 1, M.SAFFRON_GYM, 3), (10, 1, M.SAFFRON_GYM, 2),
             (0, 0, 10, 0)]
    info = {"map": M.SAFFRON_GYM, "warps": warps, "edges": {}}
    assert pad_route(walk, info, (1, 1), (12, 1)) == (3, 1)
    assert pad_route(walk, info, (5, 1), (12, 1)) == (8, 1)   # just landed on a pad: its own room's next pad
    assert pad_route(walk, info, (10, 1), (12, 1)) is None    # Sabrina's room: walk on to her
    info["warps"] = warps[:2] + [(8, 1, 10, 0)]
    assert pad_route(walk, info, (1, 1), (12, 1)) is None     # no chain of pads reaches her


def test_saffron_gym_leader_is_the_person_in_the_players_room_not_a_hidden_trainer(monkeypatch):
    """BUG-0716: host run 20261020-112433 stalled `no_progress` on `marsh_badge` in Saffron's gym (178) at (9, 13).
    The eight psychic trainers of the other rooms are hidden (image 0xFF) and one of them (picture 13 at (9, 8)) has a
    picture of his own in the room's list: the runner took him for the leader, the walk had no path to another room
    and it went back and forth on two squares for 5 min. The leader is the person standing in the player's room
    (Sabrina, picture 36 at (10, 15), on screen); the hidden trainers are left out."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    people = [(13, (9, 8)), (25, (10, 1)), (4, (17, 1)), (25, (3, 7)), (4, (17, 7)), (25, (3, 13)),
              (4, (17, 13)), (4, (3, 1)), (36, (10, 15))]
    alone = [p for p in people if [q[0] for q in people].count(p[0]) == 1] or people
    assert min(alone, key=lambda p: p[1][1]) == (13, (9, 8))   # the old rule: a trainer of another room
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "leaders_seen": []}
    r.read = lambda addr, n=1: [runner_mod.SAFFRON_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (9, 13)
    r.grid = lambda sprites_block=True: {}
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.event = lambda *a, **k: None
    monkeypatch.setattr(runner_mod.overworld, "sprite_list", lambda read: people)
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites",
                        lambda read: [(36, (10, 15), False)] + [(pic, pos, True) for pic, pos in people[:-1]])
    assert r.gym_leader(people) == (36, (10, 15))
    talked = []
    r.walk = lambda target, edge=None: talked.append(tuple(target)) or "walk"
    r.talk_at = lambda who: talked.append(tuple(who)) or "talk"
    assert r.goal_action(type("M", (), {"id": "marsh_badge"})()) == "talk"
    assert talked == [(10, 15)]    # Sabrina, not the trainer of (9, 8)
    # nobody on screen: the leader is in another room (BUG-0712's case): the old rule and the pad chain stay
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites", lambda read: [(pic, pos, True) for pic, pos in people])
    assert r.gym_leader(people) is None


def test_viridian_gym_leader_is_not_the_poke_ball_and_the_kid_is_skipped(monkeypatch):
    """BUG-0718: host run 20261020-123129 stalled `no_progress` on `earth_badge` in the Viridian gym (45) at (16, 12):
    the leader rule took the Poké Ball lying at the top of the gym's north corridor (picture 61, at (16, 9)) for the
    gym leader, walked to it and the game's ledge bounced the player back down for ever (563 cutscene ticks and 228
    walk ticks in 5 min, no progress). The ball is not a person, and the kid who stands in the player's room at
    (16, 15) answers with a plain dialogue ("I don't know who the champion of Viridian is"): not a trainer either.
    The leader is the trainer of the gym's north-west room, at (2, 1)."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    people = [(23, (2, 1)), (7, (12, 7)), (14, (11, 11)), (33, (10, 7)), (14, (3, 7)), (7, (13, 5)),
              (14, (10, 1)), (33, (2, 16)), (7, (6, 5)), (36, (16, 15)), (61, (16, 9))]
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "leaders_seen": []}
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (16, 12)
    r.grid = lambda sprites_block=True: {}
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.event = lambda *a, **k: None
    r.answer_texts = []
    monkeypatch.setattr(runner_mod.overworld, "sprite_list", lambda read: people)
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites",
                        lambda read: [(36, (16, 15), False), (61, (16, 9), False)])
    # the ball on the floor is not a person: it is never the leader
    assert r.gym_leader(people) == (36, (16, 15))
    talked = []
    r.walk = lambda target, edge=None: talked.append(tuple(target)) or "walk"
    r.talk_at = lambda who: talked.append(tuple(who)) or "talk"
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "talk"
    assert talked == [(16, 15)]        # the kid of the player's room, never the ball at (16, 9)
    # the kid answers with a plain dialogue and not with a battle: he is not the leader, the next candidate is
    r.answer_texts = ["Salut! Champion en herbe!", "je ne sais pas qui est le CHAMPION de JADIELLE!"]
    # BUG-0723: the game is quiet, so the runner steps into his line of sight before it judges him
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "challenged"
    r.memo["leader_challenged"] = runner_mod.GYM_CHALLENGE_TRIES
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "not the leader"
    assert r.memo["not_leaders"] == [[16, 15]]
    assert r.gym_leader(people) is None       # nobody of the player's room is a candidate any more
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "talk"
    assert talked[-1] == (2, 1)                # the trainer of the north-west room
    assert (16, 9) not in talked               # the ball is never talked to
    # a trainer answers with a battle line: he stays the candidate
    r.memo["not_leaders"] = []
    r.answer_texts = ["GIOVANNI veut se", "battre!"]   # a trainer's line, on two pages
    r.memo["leader_talked"] = [16, 15]
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "talk"
    assert r.memo.get("not_leaders", []) == []


def test_the_gym_candidate_does_not_change_under_the_runners_feet(monkeypatch):
    """BUG-0957: host run 20261026-163011 stalled `no_progress` on `cascade_badge` in the Cerulean gym (65) at
    (5, 11): the trainer at (8, 7) was on screen, the runner walked one square down to reach him, the trainer went
    off screen, the leader at the top of the room (4, 2) became the candidate again and the runner walked back up:
    it ping-ponged between (5, 11) and (5, 12) for ever (220 walks and no other action in 100 s of play). The
    candidate is remembered now: it stays the same until the person is gone or judged not to be the leader."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    people = [(29, (4, 2)), (6, (2, 3)), (34, (8, 7)), (36, (7, 10))]
    where = {"pos": (5, 11)}
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "leaders_seen": [], "not_leaders": [[7, 10]]}   # the trainer of (7, 10) is known
    r.read = lambda addr, n=1: ([where["pos"][0]] if addr == runner_mod.ADDR["x"] else
                                 [where["pos"][1]] if addr == runner_mod.ADDR["y"] else
                                 [M.CERULEAN_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n)
    r.pos = lambda: where["pos"]
    r.grid = lambda sprites_block=True: {}
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.event = lambda *a, **k: None
    r.answer_texts = []
    monkeypatch.setattr(runner_mod.overworld, "sprite_list", lambda read: people)

    def screen(read):
        px, py = read(runner_mod.ADDR["x"], 1)[0], read(runner_mod.ADDR["y"], 1)[0]
        return [(pic, pos, False) for pic, pos in people
                if -4 <= pos[0] - px <= 5 and -4 <= pos[1] - py <= 4]
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites", screen)
    walked = []
    r.walk = lambda target, edge=None: walked.append(tuple(target)) or "walk"
    r.talk_at = lambda who: walked.append(tuple(who)) or "talk"
    # the player stands at (5, 11): the trainer at (8, 7) is on screen and is the candidate
    assert r.goal_action(type("M", (), {"id": "cascade_badge"})()) == "talk"
    assert walked == [(8, 7)]
    # the runner walks one square down: the trainer goes off screen, but the candidate does not change
    where["pos"] = (5, 12)
    assert r.goal_action(type("M", (), {"id": "cascade_badge"})()) == "talk"
    assert walked == [(8, 7), (8, 7)]
    assert r.memo["leader_candidate"] == [M.CERULEAN_GYM, 8, 7]
    # the trainer is beaten and gone: the leader at the top of the room is the next candidate
    where["pos"] = (5, 11)
    people.remove((34, (8, 7)))
    assert r.goal_action(type("M", (), {"id": "cascade_badge"})()) == "talk"
    assert walked[-1] == (4, 2)
    # the candidate cannot be walked to: the next person of the gym is tried instead
    r.memo["leader_candidate"] = [M.CERULEAN_GYM, 4, 2]
    r.talk_at = lambda who: "no path"
    assert r.goal_action(type("M", (), {"id": "cascade_badge"})()) == "no path"
    assert "leader_candidate" not in r.memo


def test_a_gym_hop_tile_that_threw_the_player_back_is_never_walked_on_again(monkeypatch):
    """BUG-0718: the Viridian gym (45) has one-way hop tiles (the chevron squares): the game throws the player
    back down when he steps on one from the south, so the runner walked up and was thrown back for ever
    (563 cutscene ticks and 228 walk ticks in 5 min, no progress). The runner learns the square and walks around it."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.event = lambda *a, **k: None
    r.step_dir = "UP"          # the runner had stepped up onto the hop tile (16, 10)
    r.last_pos = (16, 10)
    r.note_hop(M.VIRIDIAN_GYM, (16, 11))    # the game pushed him back down
    assert r.memo["hops"] == {"45": [[16, 10, 16, 11]]}
    r.note_hop(M.VIRIDIAN_GYM, (16, 11))    # the same hop again is not recorded twice
    assert r.memo["hops"] == {"45": [[16, 10, 16, 11]]}
    # a hop the runner's own step made is not a hop tile
    r.step_dir, r.last_pos = "UP", (16, 11)
    r.note_hop(M.VIRIDIAN_GYM, (16, 10))
    assert r.memo["hops"] == {"45": [[16, 10, 16, 11]]}
    # the hop squares are not walkable: the A* goes around them
    r.pos = lambda: (16, 12)
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.rom = b""
    monkeypatch.setattr(runner_mod.overworld, "full_grid",
                        lambda read, rom, sprites_block=True, cut=False:
                        {(16, 9): True, (16, 10): True, (16, 11): True, (16, 12): True})
    monkeypatch.setattr(runner_mod.hm, "cut_user", lambda read: None)
    monkeypatch.setattr(runner_mod.hm, "surf_user", lambda read: None)
    walk = r.grid()
    assert walk[(16, 10)] is False      # the hop square is closed
    assert walk[(16, 11)] is True


def test_the_gym_leaders_step_aside_is_not_a_game_push_back_and_does_not_seal_the_square(monkeypatch):
    """BUG-0738: host run 20261020-175235 stalled `same_spot` on `earth_badge` in the Viridian gym (45) at (9, 4):
    the player was sealed in a pocket whose only way out was (10, 4). The runner had walked onto (10, 4) - the
    square the gym leader at (10, 3) looks at - and then stepped aside (BUG-0723) to (9, 4). That step of the
    runner was read as the game pushing him back off a one-way hop tile, so (10, 4) was closed for ever: the pocket
    had no way out and the runner stood still for 945 "no path" ticks. Only the game pushes the player back - the
    runner's own step never is - and a hop that changes map is not a hop either."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    class _MovingIO:
        """An io that moves the player the way the game does: a press that moves him is a real step."""

        def __init__(self, state):
            self.state, self.keys = state, []

        def press(self, key, hold=90):
            self.keys.append(key)
            d = {"LEFT": (-1, 0), "RIGHT": (1, 0), "UP": (0, -1), "DOWN": (0, 1)}.get(key)
            if d:
                self.state["pos"] = (self.state["pos"][0] + d[0], self.state["pos"][1] + d[1])

        def wait(self, ms):
            pass

    state = {"pos": (10, 4)}
    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.event = lambda *a, **k: None
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: state["pos"]
    r.io = _MovingIO(state)
    r.step_dir = "RIGHT"             # the walk onto (10, 4), the square the leader at (10, 3) looks at
    r.last_pos = (10, 4)
    assert r.step("LEFT") is True    # the challenge's "step aside" (BUG-0723): the runner moves to (9, 4)
    assert state["pos"] == (9, 4)
    assert r.step_dir == "LEFT"       # the step the runner made himself is the one he was pressed from
    r.note_hop(M.VIRIDIAN_GYM, state["pos"])
    assert r.memo.get("hops", {}) == {}       # the game did not push him back: (10, 4) is no hop tile
    # the game pushing the player back is still a hop: the tile is learned
    r.step_dir, r.last_pos = "UP", (16, 10)
    r.note_hop(M.VIRIDIAN_GYM, (16, 11))
    assert r.memo["hops"] == {"45": [[16, 10, 16, 11]]}
    # a hop that changes map is not a hop: the square he came from is on the map he left
    r.last_map = M.CELADON_GYM
    r.step_dir, r.last_pos = "UP", (16, 12)
    r.note_hop(M.VIRIDIAN_GYM, (16, 13))
    assert r.memo["hops"] == {"45": [[16, 10, 16, 11]]}
    # a cleared stall forgets the hop tiles: the wrong one walled the player in (BUG-0738)
    from shared.src.lib.game.pokemon import stall
    memo = {"hops": {"45": [[10, 4]]}, "walls": {}}
    stall.forget_on_unlock(memo)
    assert memo == {"walls": {}}
    # a hop mark on the plain floor of the map is a wrong one: the square stays walkable
    from shared.src.lib.game.pokemon import overworld as ow
    g = ow.Grid()
    g.tiles = {(9, 4): 0x11, (10, 4): 0x11, (16, 10): 0x4C, (16, 11): 0x11}
    for sq in g.tiles:
        g[sq] = True
    r.memo = {"hops": {"45": [[10, 4], [16, 10]]}}
    r.rom = b""
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    monkeypatch.setattr(runner_mod.overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: g)
    monkeypatch.setattr(runner_mod.hm, "cut_user", lambda read: None)
    monkeypatch.setattr(runner_mod.hm, "surf_user", lambda read: None)
    walk = r.grid()
    assert walk[(10, 4)] is True      # the plain floor is no hop tile: the way out of the pocket stays open
    assert walk[(16, 10)] is False    # the pit tile is a hop tile: it is closed


def test_earth_badge_walks_south_through_viridian_forest_from_digletts_house():
    """BUG-0715: host run 20261020-094747 stalled `no_progress` on `earth_badge`, in and out of Viridian Forest's north gate
    (47) from Route 2 (3, 11) for 5 min. Diglett's house lands on Route 2's north half; the world's way to Viridian is the
    forest (Route 2's own gate was never visited). The gate is no guide map, and off the guide `story` led back to Route 2.
    Every map of that route must be on the milestone's guide or in its area."""
    from shared.src.lib.game.pokemon.world import World
    w = World({
        M.ROUTE2: {"edges": {"north": M.PEWTER, "south": M.VIRIDIAN},
                   "warps": [(12, 9, M.DIGLETT_ROUTE2, 0), (3, 11, M.FOREST_NORTH_GATE, 1), (3, 43, M.FOREST_SOUTH_GATE, 2)],
                   "parts": {"warp": [0, 0, 7], "edge": {"north": [0], "south": [7]}}},
        M.FOREST_NORTH_GATE: {"edges": {}, "warps": [(5, 0, M.ROUTE2, 1), (4, 7, M.VIRIDIAN_FOREST, 0)],
                              "parts": {"warp": [0, 0], "edge": {}}},
        M.VIRIDIAN_FOREST: {"edges": {}, "warps": [(1, 0, M.FOREST_NORTH_GATE, 1), (15, 47, M.FOREST_SOUTH_GATE, 0)],
                            "parts": {"warp": [0, 0], "edge": {}}},
        M.FOREST_SOUTH_GATE: {"edges": {}, "warps": [(4, 0, M.VIRIDIAN_FOREST, 1), (4, 7, M.ROUTE2, 2)],
                              "parts": {"warp": [0, 0], "edge": {}}},
    })
    route = w.route(M.ROUTE2, M.VIRIDIAN, start_part=0)
    assert [m for m, _ in route] == [M.FOREST_NORTH_GATE, M.VIRIDIAN_FOREST, M.FOREST_SOUTH_GATE, M.ROUTE2, M.VIRIDIAN]
    ms = {m.id: m for m in M.MILESTONES}["earth_badge"]
    assert all(m in ms.maps or m in ms.area for m, _ in route)


def test_a_gym_leader_is_never_blacklisted_on_a_speech_that_is_still_being_written(monkeypatch):
    """BUG-0719: host run 20261020-134355 stalled `same_spot` on `earth_badge` in the Viridian gym (45) at (6, 8):
    533 "at goal" ticks with the gym's leader (picture 23 at (2, 1)) in the runner's blacklist, so no candidate was
    left and the runner stood still. The blacklist entry came from a wrong verdict: the runner read Giovanni's
    battle speech while the game was still writing it ("destin repose / entre des main", cut in the middle of a
    word), the trainer's battle line ("GIOVANNI veut se battre!") was never read, and "no 'veut' in the answer"
    was taken for "he is not a trainer". The battle started 13 s later (a trainer battle, level 38: Giovanni's).
    The answer must settle before it is judged, and a battle proves the person is a trainer."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    people = [(23, (2, 1)), (36, (16, 15))]
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "leaders_seen": []}
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (6, 8)
    r.grid = lambda sprites_block=True: {(2, 2): True, (1, 1): True, (3, 1): True}
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.event = lambda *a, **k: None
    r.answer_texts = []
    monkeypatch.setattr(runner_mod.overworld, "sprite_list", lambda read: people)
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites",
                        lambda read: [(23, (2, 1), False), (36, (16, 15), False)])
    challenged = []
    r.walk = lambda target, edge=None: challenged.append(tuple(target)) or "walk"
    # the runner talks to the leader: the answer is the leader's speech, caught half written
    r.talk_at = lambda who: "talk"
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "talk"
    assert r.memo["leader_talked"] == [2, 1]
    r.answer_texts = ["J.uis le ROI du / KARATE! Ton      .", "KARATE! Ton / destin repose    .",
                      "destin repose / entre des main"]
    r.answer_at = time.time()      # the game wrote the last page just now
    r.answer_since = r.answer_at
    # the answer has not settled: the trainer's battle line may still come, the leader is not judged yet
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "answer pending"
    assert r.memo.get("not_leaders", []) == []
    # BUG-0723: while the game is talking the runner does not move: a step cancels the leader's script
    assert challenged == []
    # the game is quiet: the runner walks onto the square the leader looks at (in Gen 1 his line of sight
    # starts the fight), and only then may he be judged
    r.answer_at = time.time() - runner_mod.GYM_ANSWER_QUIET_S - 1
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "challenged"
    assert challenged == [(2, 2)]
    r.memo["leader_challenged"] = runner_mod.GYM_CHALLENGE_TRIES
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "not the leader"
    assert r.memo["not_leaders"] == [[2, 1]]
    # a battle proves the person is a trainer: he comes out of the blacklist (the game does not lie)
    r.memo["not_leaders"] = [[2, 1]]
    r.memo["talked_to"] = [2, 1]
    r.forget_not_leader()
    assert r.memo["not_leaders"] == []
    # the text of a battle is not an answer to a talk: the experience messages of the fight that just ended
    # are never taken for the answer of the next person the runner talks to
    r.answer_texts = ["FLORIZARRE gagne / 219 points .EXP!"]
    r.forget_not_leader()
    assert r.memo["not_leaders"] == []


def test_a_gym_that_has_no_candidate_left_never_stands_still(monkeypatch):
    """BUG-0719: the same run stalled `same_spot` on (6, 8) with every candidate of the gym in the runner's
    blacklist: `gym_leader` found nobody, the fallback found nobody, and `goal_action` returned "at goal" on
    every tick until the stall detector stopped the run. The blacklist is a memory of one visit: when it has
    emptied the gym, the runner forgets it and tries again instead of standing still."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    people = [(23, (2, 1)), (7, (12, 7))]
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "leaders_seen": [], "not_leaders": [[2, 1], [12, 7]]}
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (6, 8)
    r.grid = lambda sprites_block=True: {}
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.event = lambda *a, **k: None
    r.answer_texts = []
    monkeypatch.setattr(runner_mod.overworld, "sprite_list", lambda read: people)
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites", lambda read: [])
    # everybody is blacklisted: the gym has no candidate at all
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "forget the blacklist"
    assert r.memo["not_leaders"] == []
    # and the runner has a candidate again
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites",
                        lambda read: [(23, (2, 1), False), (7, (12, 7), False)])
    r.talk_at = lambda who: "talk"
    assert r.goal_action(type("M", (), {"id": "earth_badge"})()) == "talk"


def test_a_gym_leader_is_not_judged_while_the_game_is_talking_and_is_challenged_after(monkeypatch):
    """BUG-0723: host run 20261020-153325 stalled `same_spot` on `earth_badge` in the Viridian gym (45) at (6, 8).
    The leader (picture 23 at (2, 1)) was blacklisted with his OWN pre-battle speech as the evidence
    ("Tu ne pourras / acc.der . la LIGUE POK.MON ... battant notre / CHAMPION!"), so the gym had no candidate and
    the runner stood still for ever. Two things went wrong: while the game is talking the runner MOVED (a step
    cancels the leader's script and his speech starts again, so in 200 s of local replay the leader never
    fought), and the leader was judged as soon as his answer settled, before his fight could come (run
    20261020-134355: his trainer battle, level 38, started 13.7 s after his text was read). So: wait while the
    game talks, step into his line of sight once it is quiet, and only then judge him."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    people = [(23, (2, 1)), (36, (16, 15))]
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "leaders_seen": []}
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM] * n if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (2, 2)      # the runner stands on the square the leader looks at (it walked there to talk)
    r.grid = lambda sprites_block=True: {(2, 2): True, (1, 2): True, (1, 1): True, (3, 1): True}
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    r.event = lambda *a, **k: None
    r.answer_texts = []
    monkeypatch.setattr(runner_mod.overworld, "sprite_list", lambda read: people)
    monkeypatch.setattr(runner_mod.overworld, "screen_sprites",
                        lambda read: [(23, (2, 1), False), (36, (16, 15), False)])
    walked, stepped = [], []
    r.walk = lambda target, edge=None: walked.append(tuple(target)) or "walk"
    r.step = lambda d: stepped.append(d) or True
    r.talk_at = lambda who: "talk"
    ms = type("M", (), {"id": "earth_badge"})()
    # the runner talks to the leader: the game answers with his pre-battle speech
    assert r.goal_action(ms) == "talk"
    assert r.memo["leader_talked"] == [2, 1]
    r.answer_texts = ["Tu ne pourras / acc.der . la     .", "battant notre / CHAMPION!"]
    r.answer_at = time.time()      # the game wrote the last page just now
    r.answer_since = r.answer_at
    # the game is still talking: the runner must not move (a step cancels the leader's script)
    assert r.goal_action(ms) == "answer pending"
    assert walked == [] and stepped == []
    assert r.memo.get("not_leaders", []) == []
    # the game is quiet and no fight came: the runner steps into the leader's line of sight before judging him
    r.answer_at = time.time() - runner_mod.GYM_ANSWER_QUIET_S - 1
    assert r.goal_action(ms) == "challenged"
    assert r.memo["leader_challenged"] == 1
    assert stepped == ["LEFT"]      # it steps aside, so that coming back on the square starts his fight
    assert r.memo.get("not_leaders", []) == []
    # the tries are used up and no fight came: now the person is judged
    r.memo["leader_challenged"] = runner_mod.GYM_CHALLENGE_TRIES
    assert r.goal_action(ms) == "not the leader"
    assert r.memo["not_leaders"] == [[2, 1]]


def test_a_key_that_does_not_move_the_player_leaves_no_direction_behind(monkeypatch):
    """BUG-0740: host run 20261020-213314 stalled `no_progress` on `earth_badge` in the Viridian gym (45)
    at (6, 9): the runner had marked the gym's chevron squares as one-way hop tiles, and closing them cut
    off the whole east half of the gym - the leader was behind them. The A* found no path, so `walk()` fell
    back on the square closest to the goal and the runner walked between two squares for five minutes (542
    ticks of "walk" in a local replay of the stalled save).
    The marks were wrong: a gym's chevron blocks the key the runner presses and carries him a moment
    later. The key did not move him, so the direction of an EARLIER step was still in memory, and the
    carry (which happened to go the other way) was read as the game pushing him back. A key that does not
    move the player must not leave a direction behind: the game may still act on it."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.event = lambda *a, **k: None
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM]
    r.pos = lambda: (16, 10)
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    r.step_dir = "UP"        # the direction of an earlier step, still in memory
    # the runner presses a key the chevron blocks: the player does not move
    assert r.step("LEFT") is False
    assert r.step_dir is None
    # the game carries the player now: that is not a push-back, the square is no hop tile
    r.last_pos = (16, 10)
    r.note_hop(M.VIRIDIAN_GYM, (16, 11))
    assert r.memo.get("hops", {}) == {}
    # a key that DOES move the player still remembers its direction (BUG-0718: the game pushes him back
    # the way he came, and the square is then a one-way hop tile)
    r.pos = lambda: (16, 11)
    r.step = runner_mod.Runner.step.__get__(r)
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    moved = []
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: moved.append(key),
                           "wait": lambda self, ms: None})()
    r.pos = lambda: (16, 12)          # the player moves up onto the tile
    seq = iter([(16, 12), (16, 11), (16, 11)])
    r.pos = lambda: next(seq)
    assert r.step("UP") is True
    assert r.step_dir == "UP"


def test_the_runner_tries_another_key_when_the_planned_one_is_blocked_by_a_hop_tile(monkeypatch):
    """BUG-0740: the gym's chevron blocks the key the runner planned (RIGHT) and throws him to its landing
    square (6, 13) whichever key he presses. With the planned key alone the runner stood on the chevron
    for ever (the `same_spot` stall of run 20261020-175235); another key gets him through."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    fake_grid = overworld.Grid({(0, 0): True, (1, 0): True})
    fake_grid.jumps, fake_grid.walls, fake_grid.tiles = {}, set(), {}
    monkeypatch.setattr(overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: fake_grid)
    monkeypatch.setattr(runner_mod, "links", lambda read: {"warps": []})
    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.log = []
    r.rom = b"\x00"
    r.read = lambda addr, n=1: [42]
    r.pos = lambda: (0, 0)
    r.event = lambda kind, **facts: None
    r.stuck = 0
    pressed = []

    def fake_step(direction):
        pressed.append(direction)
        return direction == "DOWN"       # the chevron lets the player through on another key only

    r.step = fake_step
    assert r.walk((1, 0)) == "walk"
    assert pressed[0] == "RIGHT"          # the planned key first
    assert "DOWN" in pressed              # then another key: the hop tile carries him east
    assert r.stuck == 0                   # the runner moved: he is not stuck on the chevron


def test_the_gym_chevron_is_a_passage_and_a_beaten_trainer_is_not_a_guard(monkeypatch):
    """BUG-0741: host run 20261020-223419 (host-clone-1) won the Earth Badge and then stalled `same_spot` in the
    Viridian gym (45) at (2, 2): the way out ran over the gym's chevron squares, which the runner had marked as
    one-way hop tiles and closed for ever, so `go_to_map` found no route. With no route it fell back on talking to
    a guard and picked the beaten leader: his sprite is still in the game, the memo's walls are what say he is
    gone, and talking to him does nothing at all (three talks, then 300 ticks standing still).
    A chevron is a passage: the game carries the player over it, so the mark remembers where the carry lands and
    the grid jumps over the tile the way it jumps over the ledges. A beaten trainer is not a guard."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod

    def gym_grid(read, rom, sprites_block=True, cut=False):
        g = overworld.Grid({(x, 17): True for x in range(10, 17)})
        g.jumps, g.walls, g.tiles, g.cuts, g.water = {}, set(), {}, set(), set()
        return g

    r = object.__new__(runner_mod.Runner)
    r.event = lambda kind, **facts: None
    r.read = lambda addr, n=1: [M.VIRIDIAN_GYM] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (11, 17)
    r.rom = b""
    r.io = type("IO", (), {"wait": lambda self, ms: None})()
    monkeypatch.setattr(runner_mod.overworld, "full_grid", gym_grid)
    monkeypatch.setattr(runner_mod.hm, "cut_user", lambda read: None)
    monkeypatch.setattr(runner_mod.hm, "surf_user", lambda read: None)

    # the mark of the stalled run: the tile (13, 17) and where the game carried the player (12, 17)
    r.memo = {"hops": {"45": [[13, 17, 12, 17]]}}
    walk = r.grid()
    assert walk[(13, 17)] is False                        # the tile is no square to stop on
    assert walk.jumps[(14, 17)] == [("LEFT", (12, 17))]   # the passage: from the square before the tile
    assert walk.jumps[(13, 17)] == [("LEFT", (12, 17))]   # and from the tile itself
    assert overworld.astar(walk, (14, 17), (12, 17)) == ["LEFT"]   # the way over the tile is open

    # a mark without a landing (the old format) keeps the old behaviour: the tile is closed and nothing jumps
    r.memo = {"hops": {"45": [[13, 17]]}}
    walk = r.grid()
    assert walk[(13, 17)] is False and walk.jumps == {}

    # the beaten leader is not a guard: his sprite is still in the game, but he is gone
    monkeypatch.setattr(runner_mod.overworld, "sprites", lambda read: [(2, 1), (6, 7)])
    r.memo = {"walls": {"45": [[2, 1]]}}
    r.pos = lambda: (2, 2)
    assert r.guard_in_reach(M.VIRIDIAN_GYM, {(2, 1), (2, 2), (6, 7)}) == (6, 7)


# --- The water of a map that is not the overworld tileset (BUG-0852) ---------------------------------
def _water_map(tileset=23):
    """A synthetic map (6 x 10 tiles) with a band of water between two pieces of land, and the ROM the
    runner reads it with: the block table (land block 0, water block 1), the tileset's passable list
    (the land tile 0x23 only) and the map's own blocks in work RAM. The player stands on the land above
    the band, the goal is the land below it."""
    from shared.src.lib.game.pokemon import overworld

    land, water = 0x23, 0x14
    w, h = 3, 5                      # blocks: 6 x 10 tiles
    rom = bytearray(0x2000)
    rom[0x1000:0x1010] = bytes([land]) * 16       # the land block
    rom[0x1010:0x1020] = bytes([water]) * 16      # the water block
    rom[0x1100:0x1102] = bytes([land, 0xFF])      # the passable tiles of the tileset
    stride = w + 2 * overworld.BORDER
    ow = bytearray(stride * (h + 2 * overworld.BORDER))
    for by in range(h):             # the block row of the water band
        for bx in range(w):
            ow[(by + overworld.BORDER) * stride + (bx + overworld.BORDER)] = 1 if by == 3 else 0
    wram = bytearray(0x10000)
    wram[overworld.MAP_HEIGHT:overworld.MAP_HEIGHT + 2] = bytes([h, w])
    wram[overworld.CUR_TILESET] = tileset
    wram[overworld.TILESET_BANK] = 0
    wram[overworld.BLOCKS_PTR:overworld.BLOCKS_PTR + 2] = bytes([0x00, 0x10])
    wram[overworld.COLLISION_PTR:overworld.COLLISION_PTR + 2] = bytes([0x00, 0x11])
    wram[overworld.OVERWORLD_MAP:overworld.OVERWORLD_MAP + len(ow)] = ow
    wram[ADDR["x"]] = 2
    wram[ADDR["y"]] = 4

    def read(addr, n=1):
        return list(wram[addr:addr + n])

    return read, bytes(rom)


def test_the_water_of_a_map_that_is_not_the_overworld_tileset_is_known():
    """BUG-0852: Route 23 (tileset 23) is crossed by Surf, but the runner's grid only knew the water of the
    overworld tileset: the map was cut in two, `go_to_map` found no route to Victory Road and the runner stood
    still for 300 ticks (the same_spot stall of run 20261020-234745). The game knows the water by its tile
    id alone, so the runner must too."""
    from shared.src.lib.game.pokemon import overworld

    read, rom = _water_map()
    grid = overworld.full_grid(read, rom)

    # the water of the band is known, and it is not a square to walk on by itself
    assert (2, 6) in grid.water and (2, 7) in grid.water
    assert not grid.get((2, 6))
    # the band cuts the map in two: there is no way down without it
    assert overworld.astar(grid, (2, 4), (2, 8)) is None

    # what Runner.grid does when a party member knows Surf: the water becomes a way (A* charges the menu trip)
    grid.update({sq: True for sq in grid.water})
    assert overworld.astar(grid, (2, 4), (2, 8)) is not None


def test_the_surf_crossing_of_a_map_that_is_not_the_overworld_tileset_is_a_way():
    """The same map with a party member that knows Surf: `Runner.grid` opens the water, so the A* finds the
    way over the band to the far side (the way to Victory Road across Route 23)."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon import overworld

    read, rom = _water_map()
    r = object.__new__(runner_mod.Runner)
    r.read = read
    r.rom = rom
    r.memo = {}
    r.pos = lambda: (2, 4)
    monkey = runner_mod.hm
    real_surf_user, real_cut_user = monkey.surf_user, monkey.cut_user
    monkey.surf_user = lambda read: 0        # a party member knows Surf
    monkey.cut_user = lambda read: None
    try:
        walk = r.grid()
    finally:
        monkey.surf_user, monkey.cut_user = real_surf_user, real_cut_user
    assert (2, 6) in walk.water
    assert walk.get((2, 6)) is True           # the water is walkable with Surf
    assert overworld.astar(walk, (2, 4), (2, 8)) is not None


def test_a_dead_emulator_page_ends_the_run_instead_of_spinning_on_blank_reads():
    """BUG-0872: host run 20261023-132854 (host-clone-1) stalled `no_progress` on `hall_of_fame` at map 0,
    pos (0, 0) - a map the game was not on. The emulator page had died: the host's journal says
    "Page screenshot timed out after 20s" and then "the run has no live page to photograph". Every read of
    the game's memory waited out its 15 s timeout and answered with nothing, and `VptGameIO.wram()` (the
    host script) handed the runner 8 KB of zeros, which look exactly like an empty game.
    The runner took that for a hiccup: it waited 300 ms and read again, for ever, and logged no event at
    all for 9 min 35 s. The detector then called it "no_progress" (no milestone, no new map, no new square),
    wrote the report and the LOCK, and the dispatcher started no run at all until an agent cleared it.
    The game is gone: the run must end there, and the detector must never see a map and a position the
    game is not on."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    def game(alive=False):
        """The game's memory: zeros (the dead page's answer) or a game that is there."""
        mem = bytearray(0x10000)
        if alive:
            mem[ADDR["party_count"]] = 5
        return mem

    def runner_for(mem):
        presses = []
        r = object.__new__(runner_mod.Runner)
        r.io = type("IO", (), {"refresh": lambda self: None,
                               "read": lambda self, addr, n=1: list(mem[addr:addr + n]),
                               "wram": lambda self: list(mem[0xC000:0xE000]),
                               "press": lambda self, key, hold_ms=90: presses.append(key),
                               "wait": lambda self, ms: None})()
        r.presses = presses
        r.memo = {"done": ["starter"]}
        r.log = []
        r.events = []
        r.event = lambda kind, **facts: r.events.append((kind, facts))
        r.read = lambda addr, n=1: list(mem[addr:addr + n])
        r.pos = lambda: (mem[ADDR["x"]], mem[ADDR["y"]])
        r.last_pos, r.last_map, r.step_dir = None, None, None
        r.stuck, r.busy_ticks, r.blank_reads, r.text_ticks = 0, 0, 0, 0
        r._last_tick = 0.0
        r.overworld_tick = lambda: "walk"      # the test is about the blank reads, not the play
        return r

    # a blank read is a hiccup: the runner waits and reads again
    r = runner_for(game())
    assert r.tick() == "bad read"
    assert r.tick() == "bad read"
    assert r.blank_reads == 2
    # but a page that stays dead is the end of the run, not a spin
    assert r.tick() == "emulator gone"
    assert r.blank_reads == runner_mod.BLANK_READ_LIMIT
    assert [k for k, _ in r.events] == ["emulator_gone"]
    assert r.presses == []        # nothing was pressed: there is no game left to press

    # the run ends there, and the tick that ends it never reaches the stall detector
    seen = []

    class Stall:
        def observe(self, what, milestone, map_id, pos, done, now=None, guarded=False):
            seen.append((what, map_id, list(pos)))
            return None

    r = runner_for(game())
    result = r.run(30, stall=Stall())
    assert result["emulator_gone"] is True
    assert result["counts"].get("emulator gone") == 1
    assert [w for w, _, _ in seen] == ["bad read", "bad read"]
    assert "emulator gone" not in [w for w, _, _ in seen]

    # a game that answers again starts the count again
    r = runner_for(game())
    assert r.tick() == "bad read"
    mem = game(alive=True)
    r.read = lambda addr, n=1: list(mem[addr:addr + n])
    r.pos = lambda: (mem[ADDR["x"]], mem[ADDR["y"]])
    r.tick()                                # the game is there: the blank reads are forgotten
    assert r.blank_reads == 0


def test_the_victory_road_boulder_plan_names_the_boulder_that_blocks_the_corridor():
    """BUG-0874: the plan of Victory Road 1F must name a boulder of the floor and the square the push
    starts from. It said (8, 12) - the square the player already stands on - and "DOWN", which no
    boulder of that floor could answer. BUG-0881: it then named the boulder at (2, 10) as a push that
    could not be set up: that boulder stands in the one-wide passage to the stairs (1, 1) and the
    plan wanted the player north of it, at (2, 9), the far side of the boulder, which the boulder
    itself seals. BUG-0886: the boulder is pushed SOUTH out of the passage instead - three squares,
    to (2, 13) - and the player stands north of it at (2, 9), which it can reach (measured on the
    stalled save: with the boulder on (2, 13) the stairs are 27 steps away, with it on (2, 9),
    (2, 11) or (2, 12) they are out of reach)."""
    from shared.src.lib.game.pokemon import strength, overworld

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    assert plan[-1][0] == (2, 10)                   # the boulder in the corridor to the stairs
    (bx, by), direction, steps = plan[-1]
    dx, dy = overworld.STEP[direction]
    assert (bx - dx, by - dy) == (2, 9)              # the square the push starts from (north of it)
    assert (bx + dx * steps, by + dy * steps) == (2, 13)    # where the boulder ends up: out of the way


def test_the_runner_walks_to_the_side_the_push_needs_when_the_plan_names_no_boulder(monkeypatch):
    """BUG-0874: the boulder blocks its own square, so A* parks the player on an arbitrary side of it.
    When that is not the side the push needs, the runner walks to the boulder again and again: the
    "no path" spin of the run of 20261023-132854 on map 108 (612 no-path ticks in a local replay)."""
    from shared.src.lib.game.pokemon import runner as runner_mod, strength

    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: (((2, 10), "DOWN", 2),))
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": []}
    r.read = lambda addr, n=1: [0] * n
    r.pos = lambda: (7, 11)
    walked = []
    r.walk = lambda target, edge=None: walked.append(tuple(target)) or "walk"
    r.step = lambda direction: "step"
    # BUG-0879: the runner asks the grid whether the square the push starts from can be walked to
    # (the walk does not answer "no path" for a square it cannot reach): here it can.
    r.grid = lambda sprites_block=True: {(x, 11): True for x in range(2, 8)} | {(2, 10): True, (2, 9): True}
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    r.event = lambda kind, **facts: None

    # the plan names a square that holds no boulder: the player walks to the side the push needs
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(5, 15), (14, 2), (2, 10)])
    assert r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {}) == "walk"
    assert walked == [(2, 9)]

    # a plan whose boulder is live walks to the same square: the push always starts there
    walked.clear()
    r.memo["seafoam_pushes_done"] = 0
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(2, 10), (5, 15)])
    assert r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {}) == "walk"
    assert walked == [(2, 9)]


# --- a frozen emulator (BUG-0875) ------------------------------------------------------------------
class _FrozenGameIO:
    """A page that answers, but whose game never moves: the emulator's loop is dead (or the page is
    wedged), so every key press goes nowhere. `reboot_ok` says whether the page can restart itself."""

    def __init__(self, reboot_ok=True, moving=False):
        self.reboot_ok, self.moving = reboot_ok, moving
        self.reboots, self.presses = 0, []
        self.frame = 0

    def wram(self):
        self.frame += 1
        mem = [0] * 0x2000
        if self.moving:                       # a running game writes its OAM shadow every frame
            mem[0x0EF] = self.frame & 0xFF
        return mem

    def read(self, addr, n=1):
        return [0] * n

    def press(self, key, hold_ms=90):
        self.presses.append(key)

    def wait(self, ms):
        pass

    def reboot(self):
        self.reboots += 1
        return self.reboot_ok


def test_a_game_that_never_moves_is_restarted_and_never_locks_the_save():
    """BUG-0875: the second lane's new game of 2026-10-23 (run 20261023-144004) stood at the title menu
    for the whole run: the runner pressed A and START into a game whose memory never moved, the
    detector called it "no progress" after 5 min and the lock stopped every later run. A game that does
    not move at all is a frozen emulator: the runner restarts it, and a page that cannot be restarted is
    a dead game (BUG-0872): the run ends there, with no stall and no lock."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    io = _FrozenGameIO()
    r = runner_mod.Runner(runner_mod.SnapshotIO(io), _rom())
    kinds = [r.tick() for _ in range(runner_mod.FROZEN_TICKS + 1)]
    assert kinds[:-1] == ["intro"] * runner_mod.FROZEN_TICKS    # the runner kept pressing the frozen game
    assert kinds[-1] == "emulator restart"                      # then it saw the game was not moving
    assert io.reboots == 1

    # a page that cannot be restarted: the game is gone, the run ends there (no stall, no lock)
    io2 = _FrozenGameIO(reboot_ok=False)
    r2 = runner_mod.Runner(runner_mod.SnapshotIO(io2), _rom())
    kinds2 = [r2.tick() for _ in range(runner_mod.FROZEN_TICKS + 1)]
    assert kinds2[-1] == "emulator gone"
    assert io2.reboots == 1

    # a running game is never taken for a frozen one
    io3 = _FrozenGameIO(moving=True)
    r3 = runner_mod.Runner(runner_mod.SnapshotIO(io3), _rom())
    assert [r3.tick() for _ in range(runner_mod.FROZEN_TICKS + 2)] == ["intro"] * (runner_mod.FROZEN_TICKS + 2)
    assert io3.reboots == 0


def test_the_intro_of_a_new_game_is_not_counted_as_no_progress():
    """BUG-0875: the intro of a new game (the title screen, Oak's speech, the names) is a long phase in
    which the game moves nowhere. The stall detector must not call it "no progress" and lock the save."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon import stall as stall_mod

    io = _FrozenGameIO()
    r = runner_mod.Runner(runner_mod.SnapshotIO(io), _rom())
    assert r.tick() == "intro"
    assert r.intro_now is True
    assert r.self_guarded() is True            # the intro is guarded: its time does not count

    detector = stall_mod.StallDetector(r.memo, no_progress_min=0.001, same_spot_ticks=5)
    for _ in range(3):
        assert detector.observe("intro", "starter", 0, (0, 0), 0, guarded=r.self_guarded()) is None


def test_the_game_asks_the_browser_directly_and_never_queues_a_picture_on_its_channel(monkeypatch):
    """BUG-0876: the second lane's new game stalled `no_progress` on `starter` (run 20261023-152314,
    host-clone-1). The host's journal says the FIRST hang was a picture, not a read:
    "Page screenshot timed out after 5s", and every "vptGB.wram()" queued behind it answered
    "JavaScript execution timed out after 15.0s (page unresponsive or mid-navigation)" - 25 s a game
    action, the game never played another step, and the run wrote the lock.
    The cause: the game asked for its JavaScript through the action executor, which photographs the
    page before and after every action, and a page's command queue is ONE channel - a picture that
    never comes back blocks every read and key press behind it. The game must talk to the browser
    directly, so that only the game is ever queued on that channel, and its evidence must not be a
    page picture either."""
    _import_game_pokemon(monkeypatch)
    from test_scripts.game import game_pokemon

    class Web:
        def __init__(self):
            self.scripts = []

        async def execute_javascript(self, script, timeout=15.0):
            self.scripts.append(script)
            return {"success": True, "result": 42}

    class Av:
        capture_source = "x11grab"

        def take_screenshot(self):
            return "/tmp/game-pokemon.av.jpg"

    class Device:
        """The device offers the browser and the screen capture, and nothing else: the game's reads
        must not need the action executor (and its photographs)."""

        def __init__(self):
            self.web, self.av = Web(), Av()

        def _get_controller(self, kind):
            return {"web": self.web, "av": self.av}.get(kind)

    class Context:
        team_id = "team-1"

        def __init__(self):
            self.screenshot_paths = []

        def add_screenshot(self, path):
            self.screenshot_paths.append(path)

    device, context = Device(), Context()
    io = game_pokemon.VptGameIO(device, context)

    # the game's JavaScript goes to the browser, and its answer comes back
    assert io.js("() => vptGB.wram()") == 42
    assert device.web.scripts == ["() => vptGB.wram()"]

    # a browser that does not answer is a blank read (the runner ends the run), not a crash
    class Dead:
        async def execute_javascript(self, script, timeout=15.0):
            raise RuntimeError("the controller is gone")

    device.web = Dead()
    assert io.js("() => vptGB.wram()") is None

    # the game's evidence is the host's screen capture: no picture is queued on the game's channel
    device.web = Web()
    assert game_pokemon.evidence(device, context, "pokemon_start") == "/tmp/game-pokemon.av.jpg"
    assert device.web.scripts == []
    assert context.screenshot_paths == ["/tmp/game-pokemon.av.jpg"]


# --- a heal trip with no way to a Center (BUG-0877) ----------------------------------------------
def test_the_runner_keeps_playing_when_no_healing_place_is_reachable():
    """BUG-0877: the long play stood on Victory Road 1F for 300 ticks and the run was written off
    as a stall. The runner had started a heal trip (it fled a wild battle with 91 of 454 HP), but no
    Pokémon Center is reachable from there: `heal()` answered "no route to heal" on every tick and
    `overworld_tick()` returned that, so the runner never played a step again. The trip waits now and
    the story goes on."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon.world import World

    r = object.__new__(runner_mod.Runner)
    r.memo = {"healing": True}
    r.world = World({})                      # no map, no route to any Center
    r.read = lambda addr, n=1: [0] * n
    r.event = lambda kind, **facts: None
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    # the trip is on and the party is hurt: there is no place to heal at
    assert r.heal(108, 91, 454) == "no route to heal"
    assert r.memo["healing"] is True          # the trip waits, it is not restarted (and not logged again)
    # the runner goes on playing the story instead of answering "no route to heal" for ever
    r.memo["healing"] = True
    r.party_hp = lambda: (91, 454)
    r.attack_pp = lambda: 15
    r.heal = lambda here, cur, tot: "no route to heal"
    r.grid = lambda sprites_block=True: {}
    r.lift_defers = lambda: None
    r.note_entry = lambda here: None
    r.rethink = lambda *a, **k: None
    r.story_step = lambda ms, here, info: "walk"
    r.wants_balls = lambda: False
    r.party = lambda: []
    r.money = lambda: 0
    r.grind = lambda here, info, top, want: "walk"
    r.choose = None
    assert runner_mod.Runner.overworld_tick(r) == "walk"


def test_a_push_that_cannot_be_set_up_is_given_up_instead_of_asked_for_again(monkeypatch):
    """BUG-0877: Victory Road 1F's boulder at (2, 10) seals the one-wide corridor to the stairs at
    (1, 1), so the square the push starts from (2, 9) cannot be walked to. The runner asked for it
    on every tick ("no path", 300 ticks in a row) and stood still. The push is given up for the
    floor now and the guide walks the runner on."""
    from shared.src.lib.game.pokemon import runner as runner_mod, strength

    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: (((2, 10), "DOWN", 2),))
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "seafoam_puzzle_map": 108, "seafoam_pushes_done": 0}
    r.read = lambda addr, n=1: [0] * n
    r.pos = lambda: (2, 12)
    r.walk = lambda target, edge=None: "no path"          # the side of the boulder is out of reach
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    events = []
    r.event = lambda kind, **facts: events.append((kind, facts))
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(5, 15), (14, 2), (2, 10)])
    assert r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {}) is None   # the guide takes over
    assert events and events[0][0] == "push_unreachable"
    assert r.memo["seafoam_pushes_done"] == 1                            # the floor's plan is closed


def test_a_training_that_cannot_even_start_is_given_up_instead_of_asked_for_again():
    """BUG-0878: the run of 20261023-175436 stood on Victory Road 1F for 300 ticks and every tick
    answered "no grind area": the strategist wanted the leader trained to 70 and there is no way from
    that floor to a grass area, so the runner pressed no key at all and the stall detector wrote
    "same_spot". A training that cannot begin is hopeless like a stalled one: the target is dropped,
    the strategist is told, and the story goes on."""
    from shared.src.lib.game.pokemon.runner import Runner
    mem = _Mem()
    mem.m[ADDR["party_count"]] = 1
    r = object.__new__(Runner)
    r.io = _FakeIO(mem)
    r.memo = {"grinding": True, "grind_level": 65, "grind_xp": 0, "grind_s": 0.0}
    r.log = []
    r.read = mem.read
    r.event = lambda kind, **facts: r.log.append({"kind": kind, **facts})
    told = []
    r.rethink = lambda *a, **k: told.append(a[0] if a else "")
    r.wander = lambda here, info: "no grind area"          # no way from Victory Road 1F to a grass area

    assert r.grind(here=108, info={}, top=65, want=70) == "training stalled"
    assert r.memo["stalled_target"] == 70 and r.memo["grinding"] is False
    assert any(e["kind"] == "train_stalled" and e.get("reason") == "no grind area" for e in r.log)
    assert told and "grass area" in told[0]

    # the target is not asked for again: overworld_tick skips the training while it is the dropped one
    assert r.memo.get("stalled_target") == 70


def _victory_road_runner(here, guide_i):
    """A runner on the last mile, with the learned world graph of the canonical save (measured on the live
    maps): Route 23 (34) holds the gate's warps (7,139)/(8,139) -> 193, the warp (4,31) -> Victory Road 1F
    (108) and the warp (14,31) -> Victory Road 2F (194) - but the warp to 194 sits in another part of the map
    (the plaza) than the player (the gate and the west road, part 4). Victory Road 1F's stairs (1,1) -> 194
    sit in another part of that floor than the player either."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon.world import World
    info34 = {"map": 34, "width": 20, "height": 144, "edges": {"north": 9, "south": 33}, "spans": {},
              "warps": [(7, 139, 193, 2), (8, 139, 193, 3), (4, 31, 108, 0), (14, 31, 194, 1)],
              "parts": {"warp": [4, 4, 4, 0], "edge": {"north": [0], "south": [5, 6]}, "down": [], "player": 4}}
    info108 = {"map": 108, "width": 20, "height": 18, "edges": {}, "spans": {},
               "warps": [(8, 17, 34, 2), (9, 17, 34, 2), (1, 1, 194, 0)],
               "parts": {"warp": [1, 1, 0], "edge": {}, "down": [], "player": 1}}
    world = World({
        34: info34,
        108: info108,
        193: {"map": 193, "width": 8, "height": 8, "edges": {}, "spans": {},
              "warps": [(4, 7, 34, 0), (5, 7, 34, 0), (4, 0, 34, 0), (5, 0, 34, 1)],
              "parts": {"warp": [0, 0, 0, 0], "edge": {}, "down": [], "player": 0}},
        194: {"map": 194, "width": 20, "height": 16, "edges": {}, "spans": {}, "warps": [],
              "parts": {"warp": [], "edge": {}, "down": [], "player": 0}},
    })
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [m.id for m in M.MILESTONES][:-1], "milestone": "hall_of_fame",
              "guide_i": guide_i, "rules": {}}
    r.log = []
    r.world = world
    world.learn = lambda read, walk=None: info34 if here == 34 else info108
    r.read = lambda addr, n=1: ([here] if addr == ADDR["map"] else [0] * max(n, 1))
    r.grid = lambda sprites_block=True: {}
    r.party_hp = lambda: (100, 100)
    r.attack_pp = lambda: 10
    r.party = lambda: [{"level": 70}]
    r.prepare = lambda ms, h: None
    r.recruit = lambda *a: None
    r.wants_balls = lambda: False
    r.shop = lambda h: None
    r.story_step = lambda *a: None
    asked = []
    r.go_to_map = lambda h, dest, info, **kw: asked.append(dest) or "go"
    return r, asked


def test_the_hall_of_fame_waypoints_walk_route_23_to_victory_road_1f():
    """BUG-0880: the waypoints of the last mile walked Victory Road 1F -> Route 23 -> Victory Road 2F, so a
    runner standing on Route 23 was asked for Victory Road 2F - a map it cannot reach: the only warp to 194
    sits in another part of Route 23 (the plaza). The way on from the gate is Route 23 -> Victory Road 1F, the
    warp at (4, 31), which is 81 steps away and reachable.
    BUG-0962: the floors above Victory Road 1F are no waypoints: Victory Road 3F is a dead end (all four of
    its exits lead back to Victory Road 2F) and the runner ping-ponged between the two floors for ever."""
    from shared.src.lib.game.pokemon import milestones as M
    ms = [m for m in M.MILESTONES if m.id == "hall_of_fame"][0]
    assert ms.maps.count(M.ROUTE_23) == 1
    assert ms.maps.index(M.ROUTE_23) < ms.maps.index(M.VICTORY_ROAD_1F)
    assert ms.maps.index(M.VICTORY_ROAD_1F) < ms.maps.index(M.INDIGO_PLATEAU)
    assert M.VICTORY_ROAD_2F not in ms.maps and M.VICTORY_ROAD_3F not in ms.maps, (
        "BUG-0962: the floors of Victory Road above 1F are a dead end, not waypoints")


def test_the_guide_asks_for_victory_road_1f_from_route_23_and_not_for_the_unreachable_2f():
    """BUG-0880: the run 20261023-213300 stood on Route 23 at (10, 96) for 300 ticks: the guide asked for
    Victory Road 2F (194), the world graph knows no route to it from the player's part, and every tick
    answered "no route" (the `lost` event of the report: map 34, next 194). The way on is Victory Road 1F."""
    r, asked = _victory_road_runner(here=34, guide_i=4)
    r.overworld_tick()
    assert asked == [M.VICTORY_ROAD_1F], f"the guide must ask for Victory Road 1F, asked for {asked}"

    # a saved pointer that still sits on the old order (5 = Victory Road 1F) lands on Route 23 and asks for 1F
    r, asked = _victory_road_runner(here=34, guide_i=5)
    r.overworld_tick()
    assert asked == [M.VICTORY_ROAD_1F], f"the guide must ask for Victory Road 1F, asked for {asked}"


def test_a_waypoint_the_runner_cannot_reach_sends_it_back_instead_of_standing_still():
    """BUG-0880: Victory Road 1F's stairs (1, 1) -> Victory Road 2F sit in another part of the floor than the
    player, so the next waypoint cannot be reached: the answer was "no route" on every tick and the player
    stood still (the same_spot stall). The runner walks back to the waypoint it came from instead.
    BUG-0962: the next waypoint of Victory Road 1F is Indigo Plateau now (the floors above it are a dead
    end), but the answer is the same: the runner goes back to Route 23 instead of standing still."""
    r, asked = _victory_road_runner(here=108, guide_i=5)
    r.overworld_tick()
    assert asked == [M.ROUTE_23], f"the runner must go back to Route 23, asked for {asked}"
    events = [e for e in r.log if e["kind"] == "waypoint_unreachable"]
    assert events and events[0]["map"] == 108 and events[0]["wanted"] == M.INDIGO_PLATEAU
    assert events[0]["back"] == M.ROUTE_23


def test_a_push_whose_start_square_is_out_of_reach_is_given_up_even_when_the_walk_does_not_say_no_path(monkeypatch):
    """BUG-0879: `walk` does not answer "no path" for a square it cannot reach - it talks the blocker
    away and then steps greedily towards it - so the give-up of BUG-0877 never ran on Victory Road 1F.
    The runner asked for (2, 9) on every tick, the player ping-ponged between (2, 11) and (2, 12), the
    grass of the floor, with a wild battle every step (the run of 20261023-194719: 42 wild battles and
    no square beyond the two it could reach; the stall detector wrote "no_progress"). The reachability
    is asked of the grid itself now: the floor is given up and the guide walks the runner on."""
    from shared.src.lib.game.pokemon import runner as runner_mod, strength

    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: (((2, 10), "DOWN", 2),))
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "seafoam_puzzle_map": 108, "seafoam_pushes_done": 0}
    r.read = lambda addr, n=1: [0] * n
    r.pos = lambda: (2, 12)
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    events = []
    r.event = lambda kind, **facts: events.append((kind, facts))
    asked = []

    def walk(target, edge=None):
        asked.append(target)
        return "walk"          # the walk keeps "succeeding": it never says "no path"

    r.walk = walk
    r.grid = lambda sprites_block=True: {(2, 12): True}     # (2, 9) is out of the player's reach

    assert r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {}) is None   # the guide takes over
    assert asked == [(2, 9)]                                             # the push was asked for once
    assert events and events[0][0] == "push_unreachable"
    assert r.memo["seafoam_pushes_done"] == 1                            # the floor's plan is closed
    assert "seafoam_plan" not in r.memo


def test_the_victory_road_1f_plan_pushes_the_boulder_onto_the_pressure_switch():
    """BUG-0881: the plan of Victory Road 1F was a push that cannot be set up - the boulder at (2, 10)
    stands in the one-wide passage to the stairs (1, 1) and the plan wanted the player north of it at
    (2, 9), the far side of the boulder, which the boulder itself seals. BUG-0886: the boulder is
    pushed south out of the passage (three squares, to (2, 13)) and the puzzle of the floor is then
    the pressure switch: the boulder west of the entrance is pushed onto the switch east of it
    (Bulbapedia, "Walkthrough:Pokemon Red and Blue/Part 15"). The switch is the only tile 45 of the
    floor, at (17, 13), and the published push sequence ends exactly on it."""
    from shared.src.lib.game.pokemon import overworld, strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    assert plan[0][0] == (5, 15), "the boulder west of the entrance is the one to push first"
    assert plan[-1][0] == (2, 10), "the corridor boulder is pushed out of the way last"

    at = plan[0][0]
    for boulder, direction, steps in plan[:-1]:
        assert boulder == at, "every push of the switch starts where the last one ended"
        dx, dy = overworld.STEP[direction]
        at = (boulder[0] + dx * steps, boulder[1] + dy * steps)
    assert at == (17, 13), "the boulder must end on the pressure switch"


def test_a_push_plan_that_changed_starts_its_pushes_over(monkeypatch):
    """BUG-0881: the memo of the run that gave Victory Road 1F up kept the closed counter of the old
    plan of the floor (seafoam_pushes_done 1) and that plan in the memo, so the corrected plan was
    never executed: the pushes of the new plan have to start at the first one. BUG-0886: the first
    push of the new plan is the corridor boulder, and the runner stands north of it at (2, 9)."""
    from shared.src.lib.game.pokemon import runner as runner_mod, strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    r = object.__new__(runner_mod.Runner)
    r.memo = {"done": [], "seafoam_puzzle_map": 108, "seafoam_pushes_done": 1,
              "seafoam_plan": [[[2, 10], "DOWN", 2]]}
    r.read = lambda addr, n=1: [0] * n
    r.pos = lambda: (5, 16)
    asked = []
    r.walk = lambda target, edge=None: asked.append(target) or "walk"
    r.grid = lambda sprites_block=True: {(x, y): True for x, y in
                                         ((5, 16), (5, 15), (5, 14), (4, 14), (3, 14), (3, 13), (2, 13), (2, 12),
                                          (2, 11), (2, 10), (2, 9))}
    r.event = lambda kind, **facts: None

    r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {})
    assert asked == [(5, 14)], "the first push of the new plan is the one to ask for"
    assert r.memo["seafoam_pushes_done"] == 0, "the counter of the old plan does not carry over"


def test_a_boulder_is_never_talked_to_as_a_guard(monkeypatch):
    """BUG-0881: the fallback that talks to "the nearest person in the player's part" took the
    picture-63 boulders too: on Victory Road 1F the runner walked to the boulder next to it, pressed A
    on a rock three times and stood still for 300 ticks (the same_spot stall of the run
    20261023-231857). A boulder is not a person - the trainer next to it still is."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod, strength

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.pos = lambda: (5, 16)
    r.read = lambda addr, n=1: [0] * n
    r.event = lambda kind, **facts: None
    monkeypatch.setattr(overworld, "sprites", lambda read: [(5, 15), (7, 5)])
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(5, 15)])   # the boulder of (5, 15)

    part = {(5, 16), (5, 15), (7, 5)}
    assert r.guard_in_reach(108, part) == (7, 5), "the trainer is the one to talk to"
    assert r.guard_in_reach(108, {(5, 16), (5, 15)}) is None, "a boulder is not a person"


def test_an_exit_mat_may_be_crossed_on_the_way_to_a_warp_square(monkeypatch):
    """BUG-0881: the square the Strength push of Victory Road 1F starts from is the exit mat (9, 17),
    and it can only be reached over its twin (8, 17) - the runner has to cross a warp square to get
    there. An exit mat (a warp square on the border of the map) fires when the player steps off the
    map, not when he steps on it, so the border warp squares stay walkable when the runner walks to a
    warp square of the map. The stairs to Victory Road 2F are not crossed."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    r = object.__new__(runner_mod.Runner)
    r.read = lambda addr, n=1: [0] * n
    r.pos = lambda: (8, 16)
    monkeypatch.setattr(runner_mod, "links", lambda read: {
        "map": 108, "width": 20, "height": 18, "edges": {}, "spans": {},
        "warps": [(8, 17, 34, 2), (9, 17, 34, 2), (1, 1, 194, 0)]})

    walk = {(8, 16): True, (8, 17): True, (9, 17): True, (1, 1): True}
    r.avoid_warps(walk, (9, 17))
    assert walk[(8, 17)] is True, "the twin of the exit mat may be crossed"
    assert walk[(9, 17)] is True, "the target is walkable"
    assert walk[(1, 1)] is False, "the stairs to Victory Road 2F are not crossed"


def test_a_boulder_is_never_a_wall_of_the_map(monkeypatch):
    """BUG-0886: the runner used to talk to the boulders of Victory Road 1F (the fallback that talks
    to "the nearest person in the way"), and the three talks marked them as walls for good. The
    boulder at (2, 10) stands in the one-wide corridor to the stairs (1, 1): with its square walled
    the floor is cut in two (the player's part drops from 190 squares to 129 and the stairs to
    Victory Road 2F are out of reach), so the guide walked the runner back to Route 23, whose guide
    asked for Victory Road 1F again, and the two maps took turns for ever (the same_spot stall of
    the run 20261024-003359). A boulder is pushed with Strength, not walled: the marks on it are
    dropped, the marks on the people that stay are kept."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod, strength

    fake_grid = overworld.Grid({(x, y): True for x in range(4) for y in range(4)})
    fake_grid.jumps, fake_grid.walls = {}, set()
    monkeypatch.setattr(overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: fake_grid)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(1, 1)])   # a boulder on (1, 1)

    r = object.__new__(runner_mod.Runner)
    r.memo = {"walls": {"1": [[1, 1], [2, 2]]}}
    r.read = lambda addr, n=1: [1]                    # current map id = 1
    r.rom = b"\x00"
    out = r.grid()
    assert out[(1, 1)] is True, "the boulder is not walled: it is pushed, not talked to"
    assert out[(2, 2)] is False, "the people that stay (a beaten trainer) are still walls"


def test_victory_road_1f_pushes_the_corridor_boulder_out_of_the_way_last():
    """BUG-0886: the floor has a second boulder, the one in the corridor to the stairs (1, 1): it is
    the only link between the player's part of the floor and the stairs. Pushed south three squares
    it lands on (2, 13) and the way opens (measured on the stalled save: with the boulder on (2, 13)
    the stairs are 27 steps away, with it on (2, 9), (2, 11) or (2, 12) they are out of reach). It is
    the LAST push of the plan: the pressure switch comes first (it lifts the barrier on the rocky
    ridge, and only then can the player walk round to (2, 9), north of the boulder)."""
    from shared.src.lib.game.pokemon import strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    assert plan[0][0] == (5, 15), "the boulder west of the entrance is the one to push first"
    assert plan[-1] == ((2, 10), "DOWN", 3), "the corridor boulder is pushed south out of the corridor"
    assert plan[-2] == ((17, 12), "DOWN", 1), "the pressure switch is pushed before it"


def test_a_boulder_that_blocks_the_way_is_pushed_with_strength_and_not_walked_into(monkeypatch):
    """BUG-0887: the boulder that seals the one-wide corridor to the stairs of Victory Road 1F was
    walked into for ever: the greedy step of the walk's fallback was refused by the game, the
    hop-tile fallback (BUG-0740) stepped away again, and the player ping-ponged between (2, 11) and
    (2, 12) - the grass of the floor, a wild battle every step - for 18 minutes (48 wild battles, no
    new square for the last 5) until the stall detector wrote "no_progress" (the run of
    20261024-072503). A boulder is a rock, not a person: it is pushed with Strength."""
    from shared.src.lib.game.pokemon import hm, runner as runner_mod, strength

    # the corridor of Victory Road 1F: one square wide (x = 2), the stairs at (1, 1), the boulder at (2, 10)
    corridor = {(2, y): True for y in range(1, 13)}
    corridor[(1, 1)] = True
    sprite_grid = dict(corridor)
    sprite_grid[(2, 10)] = False          # the boulder stands in the corridor

    boulder = [(2, 10)]

    def use_strength(runner):
        boulder[0] = (2, 9)                # the game slides the boulder one square north
        return True

    monkeypatch.setattr(strength, "live_boulders", lambda read: list(boulder))
    monkeypatch.setattr(hm, "use_strength", use_strength)

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.read = lambda addr, n=1: [0] * n
    r.pos = lambda: (2, 11)               # the player stands south of the boulder
    r.grid = lambda sprites_block=True: dict(sprite_grid if sprites_block else corridor)
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    steps = []
    r.step = lambda d: steps.append(d) or True
    events = []
    r.event = lambda kind, **facts: events.append((kind, facts))

    assert r.walk((1, 1)) == "boulder push"
    assert steps == ["UP", "UP"], "the player faces the boulder and pushes it (Strength in use)"
    assert boulder == [(2, 9)], "the boulder moved out of the corridor's way"
    pushes = [e for e in events if e[0] == "boulder_push"]
    assert pushes and pushes[0][1]["moved"] and pushes[0][1]["direction"] == "UP"


def test_a_boulder_that_cannot_be_pushed_is_not_talked_to_either(monkeypatch):
    """BUG-0887: the game refuses the push (there is no room for the boulder that way): the runner
    does not press A on the rock (the game answers "the boulder won't budge"), it gives the push up
    and the walk takes its usual course."""
    from shared.src.lib.game.pokemon import hm, runner as runner_mod, strength

    corridor = {(2, y): True for y in range(1, 13)}
    corridor[(1, 1)] = True
    sprite_grid = dict(corridor)
    sprite_grid[(2, 10)] = False

    monkeypatch.setattr(strength, "live_boulders", lambda read: [(2, 10)])
    monkeypatch.setattr(hm, "use_strength", lambda r: True)      # the menus work, the rock does not move

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.read = lambda addr, n=1: [0] * n
    r.pos = lambda: (2, 11)
    r.grid = lambda sprites_block=True: dict(sprite_grid if sprites_block else corridor)
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    r.step = lambda d: True
    events = []
    r.event = lambda kind, **facts: events.append((kind, facts))
    talked = []
    r.talk_at = lambda who: talked.append(who) or "talk"

    out = r.walk((1, 1))
    assert out != "boulder push"
    assert not talked, "a boulder is not a person: it is never talked to"
    assert any(e[0] == "boulder_push" and not e[1]["moved"] for e in events)


def test_a_heal_trip_that_cannot_start_waits_instead_of_freezing_the_tick():
    """BUG-0888: the run of 20261024-085053 stood on Route 23 at (4, 32) for 300 ticks and the stall
    detector wrote "same_spot". The party was hurt (361 of 467 HP), so the runner started a heal trip
    to Pallet Town's Center (41): the world graph knows the way (Route 23's south edge -> Route 22 ->
    Viridian -> Pallet), but the south edge lies in another part of Route 23 than the part the player
    stands in, so the trip could never start. `go_to_map` answered "no route", `heal()` passed that on
    and `overworld_tick` returned it: no key was pressed at all, on any tick, for ever - the last event
    before the stall was "lost map 34 next 41". The trip waits now (BUG-0877's rule) and the runner
    goes on playing the story."""
    from shared.src.lib.game.pokemon import runner as runner_mod
    from shared.src.lib.game.pokemon.world import World

    # the world graph of the stalled save: Route 23's north part (4) holds the gate warps and the way
    # to Victory Road 1F, its south edge (parts 5 and 6) the way to Route 22, which is the way the
    # graph knows to Pallet Town's Center
    known = {
        34: {"map": 34, "width": 20, "height": 144, "edges": {"north": 9, "south": 33},
             "spans": {"north": [0, 20], "south": [0, 20]},
             "warps": [(7, 139, 193, 2), (8, 139, 193, 3), (4, 31, 108, 0), (14, 31, 194, 1)],
             "parts": {"warp": [4, 4, 4, 0], "edge": {"north": [0], "south": [5, 6]}, "down": [],
                       "player": 4, "also": []}},
        33: {"map": 33, "width": 20, "height": 36, "edges": {"north": 34, "east": 1},
             "warps": [(8, 5, 193, 0)],
             "parts": {"warp": [0], "edge": {"north": [], "east": [0]}, "down": [], "player": 0, "also": []}},
        1: {"map": 1, "width": 20, "height": 36, "edges": {"north": 13, "south": 12, "west": 33},
            "warps": [(23, 25, 41, 0), (29, 19, 42, 0), (21, 15, 43, 0), (21, 9, 44, 0), (32, 7, 45, 0)],
            "parts": {"warp": [0, 0, 0, 0, 0], "edge": {"north": [0], "south": [0, 1, 2, 3, 4], "west": [0]},
                      "down": [], "player": 0, "also": []}},
        41: {"map": 41, "width": 10, "height": 9, "edges": {}, "warps": [(3, 7, 1, 0), (4, 7, 1, 0)],
             "parts": {"warp": [0, 0], "edge": {}, "down": [], "player": 0, "also": []}},
        193: {"map": 193, "width": 10, "height": 9, "edges": {},
              "warps": [(4, 7, 34, 0), (5, 7, 34, 0), (4, 0, 34, 0), (5, 0, 34, 1)],
              "parts": {"warp": [0, 0, 0, 0], "edge": {}, "down": [], "player": 0, "also": []}},
    }
    world = World(known)
    # the graph knows the way to the Center, but not from the part the player stands in
    assert world.route(34, 41) is not None
    assert world.route(34, 41, start_part=4) is None

    r = object.__new__(runner_mod.Runner)
    r.memo = {"healing": True}
    r.world = world
    r.read = lambda addr, n=1: [0] * n
    r.event = lambda kind, **facts: None
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    asked = []
    r.go_to_map = lambda here, dest, info, **kw: asked.append(dest) or "no route"

    # the trip cannot start: it waits, and the runner is not sent on a trip that cannot begin
    assert r.heal(34, 361, 467) == "no route to heal"
    assert asked == [], "a trip that cannot start is not begun"
    assert r.memo["healing"] is True

    # and when the trip is begun but the route cannot be started after all, the tick is not frozen
    r.go_to_map = lambda here, dest, info, **kw: "no route"
    r.world = World({34: known[34], 41: known[41]})      # the Center is on this map, the route is not
    r.memo["healing"] = True
    assert r.heal(34, 361, 467) == "no route to heal"


def test_a_wall_mark_does_not_outlive_the_boulder_it_belongs_to(monkeypatch):
    """BUG-0889: BUG-0886 stopped the runner from *talking* to the boulders of Victory Road 1F, but the
    marks it had already left stayed on their squares - and a mark on a square the boulder has left is
    a wall on an empty square. The corridor boulder (2, 10) stands in the one-wide passage to the stairs
    (1, 1): with its square walled the floor is cut in two, the stairs are out of reach, the guide walks
    the runner back to Route 23 and the lane stalls with "no_progress" on map 108 (the run
    20261024-093928: 23 minutes of play, 37 boulder pushes, no new square). A boulder is a rock, not a
    person: the marks on the squares the floor's puzzle names are dropped."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod, strength

    fake_grid = overworld.Grid({(x, y): True for x in range(6) for y in range(16)})
    fake_grid.jumps, fake_grid.walls = {}, set()
    monkeypatch.setattr(overworld, "full_grid", lambda read, rom, sprites_block=True, cut=False: fake_grid)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(1, 1)])   # the boulder left (2, 10)

    r = object.__new__(runner_mod.Runner)
    r.memo = {"walls": {"108": [[2, 10], [2, 2]]}}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0]
    r.rom = b"\x00"
    out = r.grid()
    assert out[(2, 10)] is True, "the mark of a boulder that has been pushed away must not seal the floor"
    assert out[(2, 2)] is False, "the people that stay (a beaten trainer) are still walls"


def _boulder_push_runner(monkeypatch, boulder, here=108, pos=(2, 11), grid=None):
    """A runner with the mocks a boulder push needs: the grid of the floor, a rock that the game may
    or may not move, and the events of the run."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    # the floor has no warp of its own here: the links are read from the live game
    monkeypatch.setattr(runner_mod, "links", lambda read: {"warps": [], "width": 20, "height": 18})

    corridor = {(2, y): True for y in range(1, 13)}
    corridor[(1, 1)] = True
    sprite_grid = dict(corridor)
    sprite_grid[boulder] = False

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.read = lambda addr, n=1: [here] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: pos
    r.grid = lambda sprites_block=True: dict(grid or (sprite_grid if sprites_block else corridor))
    r.io = type("IO", (), {"press": lambda self, key, hold_ms=90: None,
                           "wait": lambda self, ms: None})()
    r.step = lambda d: True
    events = []
    r.event = lambda kind, **facts: events.append((kind, facts))
    r.talk_at = lambda who: "talk"
    return r, events


def test_the_plan_wins_over_the_generic_push_of_a_boulder(monkeypatch):
    """BUG-0890: the generic "push the boulder out of the way" shoved the corridor boulder of Victory
    Road 1F NORTH, against the plan of the floor, which wants it pushed SOUTH out of the corridor to
    the stairs (the run of 20261024-093928). The rock ended up in the alcove (2, 9), where the game
    refuses to move it at all, and the floor could never be finished. The plan has to win: a boulder
    the plan names is never pushed the other way."""
    from shared.src.lib.game.pokemon import hm, strength

    monkeypatch.setattr(strength, "live_boulders", lambda read: [(2, 10)])
    monkeypatch.setattr(hm, "use_strength", lambda r: True)

    r, events = _boulder_push_runner(monkeypatch, (2, 10))
    out = r.walk((1, 1))

    assert out != "boulder push", "the corridor boulder is not pushed the wrong way"
    assert not [e for e in events if e[0] == "boulder_push"], "no push against the plan at all"


def test_a_push_the_game_refuses_is_never_tried_again(monkeypatch):
    """BUG-0890: the game refused the push of the boulder at (2, 9) ("the boulder won't budge": the
    square north of it is a wall) and the runner tried it again on every tick for ever: 40 pushes of
    the same rock in 13 minutes and no new square, until the stall detector wrote "no_progress" (the
    run of 20261024-102539). A refused push is remembered and never tried again."""
    from shared.src.lib.game.pokemon import hm, strength

    monkeypatch.setattr(strength, "live_boulders", lambda read: [(2, 8)])
    monkeypatch.setattr(hm, "use_strength", lambda r: True)      # the menus work, the rock does not move

    r, events = _boulder_push_runner(monkeypatch, (2, 8), pos=(2, 9))
    r.walk((1, 1))
    assert [e for e in events if e[0] == "boulder_push"], "the push is tried once"
    assert r.memo.get("push_refused"), "the refusal of the game is remembered"

    events.clear()
    r.walk((1, 1))
    assert not [e for e in events if e[0] == "boulder_push"], "a refused push is never repeated"


def test_the_chain_of_a_floor_follows_its_boulders_and_not_the_memo(monkeypatch):
    """BUG-0890: the memo's counter pointed at the corridor push while the boulder of the corridor was
    wedged at (2, 9) and the boulder of the pressure switch was back where it started, (5, 15): the
    game puts the boulders of a floor back where they were when the player leaves it, so the chain
    has to start over. The step of the chain is the first square of the plan that holds a live
    boulder - the memo alone said the floor was done."""
    from shared.src.lib.game.pokemon import strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(5, 15)])

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_puzzle_map": 108, "seafoam_pushes_done": 7, "seafoam_plan_key": key,
              "seafoam_plan": list(plan)}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (5, 16)
    asked = []
    r.walk = lambda target, edge=None: asked.append(target) or "walk"
    r.grid = lambda sprites_block=True: {(x, y): True for x, y in
                                         ((5, 16), (5, 15), (5, 14), (4, 14), (3, 14), (3, 13), (2, 13),
                                          (2, 12), (2, 11), (2, 10), (2, 9))}
    r.event = lambda kind, **facts: None

    r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {})
    assert asked == [(5, 14)], "the chain starts again at the boulder that is really on the floor"


def test_a_boulder_that_seals_the_way_makes_the_hop_of_the_route_unwalkable(monkeypatch):
    """BUG-0891: the stairs of Victory Road 1F (1, 1) are the way to Victory Road 2F, but the boulder
    that wedged in the one-wide corridor to them (2, 10) seals it: the path to the stairs is no path.
    The walk has to say so, or the greedy step of its fallback only bounces the player between two
    squares of the grass for ever (the run of 20261024-105855: 42 wild battles and no new square in
    33 minutes)."""
    from shared.src.lib.game.pokemon import hm, strength

    monkeypatch.setattr(strength, "live_boulders", lambda read: [(2, 10)])
    monkeypatch.setattr(hm, "use_strength", lambda r: True)      # the menus work, the rock does not move

    r, _events = _boulder_push_runner(monkeypatch, (2, 10), pos=(2, 11))
    r.walk((1, 1))

    assert r._hop_unwalkable is True, "the hop of the route is not walkable: a boulder seals it"


def test_a_sealed_hop_sends_the_runner_back_to_the_waypoint_it_came_from():
    """BUG-0891: the world graph of the live save knows the stairs of Victory Road 1F as the way to
    Victory Road 2F and they are in the player's own part of the floor - but the boulder that sealed
    the corridor to them makes that hop unwalkable. The runner walked at the stairs for 33 minutes and
    42 wild battles without a new square, and the lane did not even lock. A hop the player cannot walk
    to is no route: the guide goes back to the waypoint it came from (Route 23), the game puts the
    boulders of the floor back where they were, and the floor can be solved."""
    from shared.src.lib.game.pokemon import milestones as M

    r, asked = _victory_road_runner(here=108, guide_i=5)
    # the live save: all three warps of the floor are in the player's own part, so the graph routes
    # to Victory Road 2F through the stairs
    r.world.maps[108]["parts"] = {"warp": [0, 0, 0], "edge": {}, "down": [], "player": 0}
    assert r.world.route(108, M.VICTORY_ROAD_2F, start_part=0), "the graph routes through the stairs"

    # the walk found the hop unwalkable (a boulder seals it)
    r.memo["hop_blocked"] = [[108, M.VICTORY_ROAD_2F]]
    r.overworld_tick()
    assert asked == [M.ROUTE_23], f"the runner must go back to Route 23, asked for {asked}"

    # and the waypoint it came from is walkable, so the runner goes on playing the story
    r, asked = _victory_road_runner(here=108, guide_i=5)
    r.world.maps[108]["parts"] = {"warp": [0, 0, 0], "edge": {}, "down": [], "player": 0}
    # BUG-0962: the north edge of Route 23 (the way to Indigo Plateau) is in the player's part of it
    r.world.maps[34]["parts"]["edge"]["north"] = [4]
    r.overworld_tick()
    assert asked == [M.INDIGO_PLATEAU], f"without a sealed hop the guide asks for the goal, asked for {asked}"


def test_the_marking_of_a_sealed_hop_is_forgotten_on_the_next_floor():
    """BUG-0891: the game puts the boulders of a floor back where they were when the player leaves it,
    so a hop that a boulder sealed on that floor is walkable on the next one."""
    from shared.src.lib.game.pokemon import milestones as M
    from shared.src.lib.game.pokemon import runner as runner_mod

    r, _asked = _victory_road_runner(here=108, guide_i=5)
    r.memo["hop_blocked"] = [[108, M.VICTORY_ROAD_2F]]
    r.memo["pokemon_map"] = 108
    r.read = lambda addr, n=1: ([194] if addr == ADDR["map"] else [0] * max(n, 1))
    r.lift_defers = lambda: None
    r.event = lambda kind, **facts: None
    r.overworld_tick()
    assert not r.memo.get("hop_blocked"), "another floor, another chance: the marking is dropped"


def test_the_chain_of_a_floor_does_not_jump_to_a_later_push_for_a_boulder_out_of_sight(monkeypatch):
    """BUG-0891: the boulders of a floor are read from the sprites on the screen, so a boulder that
    is out of sight is not a boulder that is gone. The chain of Victory Road 1F jumped from its
    second push to the last one (the corridor boulder, which happened to be in sight), the floor was
    given up again and the runner left the floor for ever. The chain starts over at an EARLIER
    square of the plan, never at a later one."""
    from shared.src.lib.game.pokemon import strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    # the chain boulder sits at (9, 16) - the third push of the plan - but out of sight; the corridor
    # boulder of the floor is in sight
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(2, 10)])

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_puzzle_map": 108, "seafoam_pushes_done": 2, "seafoam_plan_key": key,
              "seafoam_plan": list(plan)}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (9, 15)
    asked = []
    r.walk = lambda target, edge=None: asked.append(target) or "walk"
    r.grid = lambda sprites_block=True: {(x, y): True for x, y in
                                         ((9, 15), (9, 16), (9, 17), (8, 16), (8, 15), (8, 14), (9, 14))}
    r.event = lambda kind, **facts: None

    r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {})
    assert asked == [(9, 17)], "the chain goes on with its own push, not with a later one"


def test_the_chain_of_a_floor_follows_the_rock_and_not_the_counter(monkeypatch):
    """BUG-0896: the counter of the plan was the runner's own guess about the rock, and it lied.
    The run 20261024-225457 pushed the rock of Victory Road 1F two squares of the second push (the
    game swallows the presses of the dust of a push), counted the push as done all the same and
    went on with a rock that stood somewhere else: the six pushes after that one pushed air, the
    pressure switch was never pressed, the floor was given up and the lane ping-ponged between the
    floor and Route 23 until the stall detector wrote no_progress.

    The rock is the truth about the chain: the counter of the stalled save says the plan is done
    (8 pushes) while the rock of the chain stands on (9, 14) - the square the fourth push of the
    plan starts from. The chain does that push (the player stands on (8, 14) and the rock goes to
    (16, 14)), not the corridor push the counter would ask for."""
    from shared.src.lib.game.pokemon import strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    # the rock of the chain stands on (9, 14): the square the fourth push of the plan starts from
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(9, 14)])

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_puzzle_map": 108, "seafoam_pushes_done": 8, "seafoam_plan_key": key,
              "seafoam_plan": list(plan)}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (9, 15)
    asked = []
    r.walk = lambda target, edge=None: asked.append(target) or "walk"
    r.grid = lambda sprites_block=True: {(x, y): True for x, y in
                                         ((9, 15), (9, 14), (8, 14), (9, 13), (10, 14))}
    r.event = lambda kind, **facts: None

    r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {})
    # the stand of the push that starts on (9, 14) and goes RIGHT: (8, 14)
    assert asked == [(8, 14)], "the chain does the push of the rock that is really there"


def test_a_push_that_does_not_move_the_rock_does_not_advance_the_chain(monkeypatch):
    """BUG-0896: a push the game refuses (the rock does not budge) must not be counted as a push:
    the chain then goes on with a rock that is somewhere else and the floor is given up for
    nothing. The chain stays where it is, the event says the push was short, and the push is
    tried again (a rock that refuses to move is given up after a few tries)."""
    from shared.src.lib.game.pokemon import hm, strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(5, 15)])   # the rock never moves
    monkeypatch.setattr(hm, "use_strength", lambda runner: True)

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_puzzle_map": 108, "seafoam_pushes_done": 0, "seafoam_plan_key": key,
              "seafoam_plan": list(plan)}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (5, 14)          # the player already stands where the push starts
    r.walk = lambda target, edge=None: "walk"
    r.grid = lambda sprites_block=True: {(x, y): True for x, y in ((5, 14), (5, 15), (5, 16))}
    r.step = lambda direction: True  # the game refuses: the rock does not move
    events = []
    r.event = lambda kind, **facts: events.append({"kind": kind, **facts})

    assert r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {}) == "boulder push"
    # the chain did not move on: the rock is still where it was
    assert r.memo["seafoam_pushes_done"] == 0
    short = [e for e in events if e["kind"] == "push_short"]
    assert len(short) == 1 and short[0]["boulder"] == [5, 15]
    pushes = [e for e in events if e["kind"] == "boulder_push"]
    assert len(pushes) == 1 and pushes[0]["reached"] is False and pushes[0]["moved"] is False


def test_the_chain_pushes_a_rock_that_stands_between_two_squares_of_the_plan(monkeypatch):
    """BUG-0896: a push that was cut short leaves the rock between two squares of the plan (the
    run 20261024-225457: the rock stood at (7, 16) between (5, 16) and (9, 16)). The chain pushes
    that rock on to the end of the step it is in: the player stands on (6, 16) and the rock goes to
    (9, 16)."""
    from shared.src.lib.game.pokemon import strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(7, 16)])

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_puzzle_map": 108, "seafoam_pushes_done": 2, "seafoam_plan_key": key,
              "seafoam_plan": list(plan)}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (7, 17)
    asked = []
    r.walk = lambda target, edge=None: asked.append(target) or "walk"
    r.grid = lambda sprites_block=True: {(x, y): True for x, y in
                                         ((7, 17), (6, 16), (7, 16), (8, 16), (6, 17))}
    r.event = lambda kind, **facts: None

    r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {})
    # the stand of the push of the rock at (7, 16) that goes RIGHT: (6, 16)
    assert asked == [(6, 16)], "the rock is pushed from where it really stands"


def test_the_chain_pushes_a_rock_that_was_pushed_the_wrong_way(monkeypatch):
    """BUG-0896: the rock of the pressure switch of Victory Road 1F stood at (9, 14) with the player
    east of it, while the plan's push (east) needs the player west of it. The rock was pushed the
    wrong way to (8, 14): that is the same rock, one square behind the square the push starts from,
    and the chain pushes it on to the end of the step it is in - the player stands on (7, 14) and
    the rock goes to (16, 14)."""
    from shared.src.lib.game.pokemon import strength

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(8, 14)])

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_puzzle_map": 108, "seafoam_pushes_done": 3, "seafoam_plan_key": key,
              "seafoam_plan": list(plan)}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (9, 15)
    asked = []
    r.walk = lambda target, edge=None: asked.append(target) or "walk"
    r.grid = lambda sprites_block=True: {(x, y): True for x, y in
                                         ((9, 15), (8, 15), (7, 15), (7, 14), (8, 14))}
    r.event = lambda kind, **facts: None

    r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {})
    # the stand of the push of the rock at (8, 14) that goes RIGHT: (7, 14)
    assert asked == [(7, 14)], "the rock one square behind is pushed on to the end of the step"


def test_a_rock_that_seals_the_player_in_is_pushed_out_of_the_way(monkeypatch):
    """BUG-0896: the rock of the pressure switch of Victory Road 1F stood at (9, 14), the doorway
    to the pocket with the stairs: the player was east of it in a pocket of 24 squares and the
    plan's push (east) needs the player west of the rock, which it could not reach. The rock is
    then pushed out of the way - but only when that OPENS the plan's push: the player steps into
    the square the rock leaves and can then stand where the plan needs it."""
    from shared.src.lib.game.pokemon import hm, strength

    boulders = [(9, 14)]
    monkeypatch.setattr(hm, "use_strength", lambda runner: True)
    monkeypatch.setattr(strength, "live_boulders", lambda read: list(boulders))

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.rom = b"\x00"
    r.memo = {"hop_blocked": [[108, 194], [108, 34]]}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    pos = [(11, 14)]
    r.pos = lambda: pos[0]
    # the player's pocket (10, 14)/(11, 14) and the pocket west of the rock, with the way round it
    walk = {(11, 14): True, (10, 14): True, (9, 15): True, (8, 15): True, (7, 15): True,
            (7, 14): True, (8, 14): True}
    r.grid = lambda sprites_block=True: dict(walk)
    r.walk = lambda target, edge=None: "walk"

    def fake_step(direction):
        from shared.src.lib.game.pokemon import overworld
        dx, dy = overworld.STEP[direction]
        pos[0] = (pos[0][0] + dx, pos[0][1] + dy)
        for i, (bx, by) in enumerate(boulders):
            if (bx, by) == (9, 14) and direction == "LEFT":
                boulders[i] = (8, 14)       # the rock slides one square west
                break
        return True
    r.step = fake_step
    events = []
    r.event = lambda kind, **facts: events.append({"kind": kind, **facts})

    assert r.push_rock_aside((9, 14), "RIGHT") == "boulder push"
    assert boulders == [(8, 14)], "the rock was pushed out of the doorway"
    # the hops the rock stood in the way of are walkable again
    assert "hop_blocked" not in r.memo
    pushes = [e for e in events if e["kind"] == "boulder_push"]
    assert len(pushes) == 1 and pushes[0]["direction"] == "LEFT" and pushes[0]["aside"] is True


def test_a_push_that_does_not_open_the_plan_is_not_done(monkeypatch):
    """BUG-0896: the corridor boulder of Victory Road 1F (2, 10) may never be pushed aside: it
    would seal the corridor even tighter, and the game refuses the move in any case (BUG-0890)."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    r = object.__new__(runner_mod.Runner)
    r.rom = b"\x00"
    r.memo = {}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (2, 11)
    # the corridor: (2, 10) is the rock, (2, 11) is the player's side, (2, 9) the alcove (a wall)
    r.grid = lambda sprites_block=True: {(2, 11): True, (3, 11): True, (2, 12): True}
    r.walk = lambda target, edge=None: "walk"
    r.step = lambda direction: True
    r.event = lambda kind, **facts: None

    assert r.push_rock_aside((2, 10), "DOWN") is None


def test_the_runner_never_opens_a_barrier_the_game_has_not_opened(monkeypatch):
    """BUG-0893: the pressure switch of Victory Road 1F does not open the barrier on the rocky
    ridge. Measured on the live save: the boulder the chain pushes onto the switch tile (17, 13)
    falls into the hole that tile is (it is gone from the sprite list), the map's block table stays
    the one of the ROM and the game's own tile-pair collision keeps (5, 8) and (5, 9) apart for
    ever. BUG-0892 opened the barrier anyway, from the runner's own count of the chain: the grid
    planned a path into that wall, the player ping-ponged in the grass of the floor and the stall
    detector wrote "no_progress" (the run 20261024-134917: 22 wild battles, no new square in 11
    minutes, the save locked). The grid follows the game's own collision data now."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod, strength

    layout = strength.PUZZLES[strength.VICTORY_ROAD_1F]
    assert layout.switch_at == (17, 13)

    ridge = {((5, 8), (5, 9)), ((6, 8), (6, 9)), ((7, 8), (7, 9))}
    both = ridge | {(b, a) for a, b in ridge}

    def build(live, pushes_done=0):
        def fresh(read, rom, sprites_block=True, cut=False):
            fake = overworld.Grid({(x, y): True for x in range(6) for y in range(16)})
            fake.jumps, fake.walls = {}, set(both)
            return fake
        monkeypatch.setattr(overworld, "full_grid", fresh)
        monkeypatch.setattr(strength, "live_boulders", lambda read: live)
        r = object.__new__(runner_mod.Runner)
        r.memo = {"seafoam_pushes_done": pushes_done}
        r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0]
        r.rom = b"\x00"
        r.pos = lambda: (16, 12)
        return r

    # The game's own collision says the barrier is closed: the grid keeps it closed, whatever the
    # runner's chain counter says and whatever the runner thinks it sees on the switch tile.
    step = strength.switch_step(layout)
    assert step == 6, "the chain's seventh push lands the boulder on the switch"
    for pushes_done in (0, step, step + 1, len(layout.plan)):
        r = build([(2, 10)], pushes_done)
        assert (getattr(r.grid(), "walls", set()) & ridge), "the barrier stays closed"
        assert (getattr(r.grid(), "walls", set()) & {(b, a) for a, b in ridge}), "both ways"
    r = build([(2, 10), (17, 13)], step + 1)
    assert (getattr(r.grid(), "walls", set()) & ridge), "a boulder on the switch opens nothing"

    # When the game opens the barrier, the tiles of the floor change and the pairs are gone: the
    # grid follows the game and the stand square (2, 9) of the corridor push is reachable.
    def opened_grid(read, rom, sprites_block=True, cut=False):
        fake = overworld.Grid({(x, y): True for x in range(6) for y in range(16)})
        fake.jumps, fake.walls = {}, set()
        return fake
    monkeypatch.setattr(overworld, "full_grid", opened_grid)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(2, 10)])
    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_pushes_done": step + 1}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0]
    r.rom = b"\x00"
    r.pos = lambda: (16, 12)
    assert not (getattr(r.grid(), "walls", set()) & both), "the game's open barrier stays open"


def test_the_push_of_a_plan_presses_until_the_rock_has_really_moved(monkeypatch):
    """BUG-0895: a push of the plan is not one press per square of rock. The game moves the rock one
    square and swallows the presses that land in the animation of the push (pokered's
    `AnimateBoulderDust` runs eight steps of `Delay3` and `DoBoulderDustAnimation` discards the
    button press), during which the player cannot step into the square the rock left: a square of
    rock costs about four presses. The runner pressed the plan's `steps` times and believed the rock
    had moved `steps` squares - measured on the stalled save of Victory Road 1F, the four presses of
    the second push of the chain moved the rock from (5, 16) to (6, 16) and not to (9, 16). The six
    pushes after that pushed air, the chain never ended on the pressure switch (17, 13) - the game
    opens the barrier of the floor only while a rock lies on that switch - and the runner walked the
    floor for ever (the run of 20261024-152049: 24 boulder pushes, 390 ticks, no new map). The push
    is checked now: the runner presses until the rock has really left its square."""
    from shared.src.lib.game.pokemon import hm, strength
    from shared.src.lib.game.pokemon import runner as runner_mod

    plan = strength.PUZZLES[strength.VICTORY_ROAD_1F].plan
    key = "|".join(f"{p[0][0]},{p[0][1]}:{p[1]}:{p[2]}" for p in plan)
    monkeypatch.setattr(strength, "plan_strength_puzzle", lambda read, here: plan)
    monkeypatch.setattr(strength, "live_boulders", lambda read: [tuple(rock)])

    rock = [5, 16]           # the rock of the floor, after the first push of the chain
    presses = []
    state = {"strength": False, "busy": 0}

    def use_strength(runner):
        state["strength"] = True
        return True

    def step(direction):
        if state["strength"]:
            if state["busy"] > 0:
                state["busy"] -= 1        # the game is busy with the animation of the push
            else:
                rock[0] += 1              # the rock moves one square
                state["busy"] = 3          # and the player needs three presses to step after it
        presses.append(direction)
        return True

    monkeypatch.setattr(hm, "use_strength", use_strength)

    r = object.__new__(runner_mod.Runner)
    r.memo = {"seafoam_puzzle_map": 108, "seafoam_pushes_done": 1, "seafoam_plan_key": key,
              "seafoam_plan": list(plan)}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (4, 16)                  # the square the push of (5, 16) starts from
    r.walk = lambda target, edge=None: "walk"
    r.grid = lambda sprites_block=True: {(4, 16): True, (5, 15): True, (5, 16): True, (6, 16): True,
                                         (7, 16): True, (8, 16): True, (9, 16): True}
    r.event = lambda kind, **facts: None
    r.step = step

    r.strength_puzzle_step(strength.VICTORY_ROAD_1F, {})

    assert tuple(rock) == (9, 16), "the rock is pushed the four squares the plan asks for"
    assert r.memo["seafoam_pushes_done"] == 2, "the chain moves on to the next push of the plan"


def test_a_person_on_the_target_square_is_not_talked_to_through_the_walk(monkeypatch):
    """BUG-0919: the run of 20261025 died with "maximum recursion depth exceeded".

    The walk to the guard of Victory Road 1F failed (the boulder in the corridor keeps him out of
    reach), the walk asked the boulder to move, the push was refused, and unblock asked talk_at to
    walk to the guard - which asked unblock again, for ever. A person who stands on the target
    square is not talked to through the walk: there is no way on, the caller re-plans."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod

    r = object.__new__(runner_mod.Runner)
    r.memo, r.log = {}, []
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    r.pos = lambda: (11, 2)
    r.event = lambda kind, **facts: r.log.append(kind)
    asked = []
    r.talk_at = lambda who: asked.append(who) or "talk"

    # the guard stands on the target square: the way to him is blocked by himself
    monkeypatch.setattr(overworld, "sprites", lambda read: [(9, 2)])
    monkeypatch.setattr(runner_mod.Runner, "blocker_on_the_way", lambda self, start, target: (9, 2))
    monkeypatch.setattr(runner_mod.Runner, "wakes", lambda self, blocker: False)

    action, path = r.unblock((11, 2), (9, 2))
    assert (action, path) == (None, None), "no way on: the caller re-plans"
    assert asked == [], "he is not talked to: the walk to him is the caller's own work"


def test_talking_to_the_same_person_twice_does_not_walk_to_him_twice(monkeypatch):
    """BUG-0919: the safety net of the cycle walk -> unblock -> talk_at -> walk: we are already
    walking to him, so walking to him again would ask the same walk the same question."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.pos = lambda: (11, 2)
    asked = []
    r.walk = lambda who: asked.append(who) or "walk"

    r._walking_to = (9, 2)
    assert r.talk_at((9, 2)) == "no path", "no second walk to the same man"
    assert asked == [], "the walk was not asked again"
    r._walking_to = None
    assert r.talk_at((9, 2)) == "walk", "a man we are not walking to is walked to"
    assert asked == [(9, 2)]


def test_a_guard_a_boulder_seals_off_is_not_the_guard_to_talk_to(monkeypatch):
    """BUG-0919: the guard behind the corridor boulder of Victory Road 1F - a pocket with no other
    way in - was chosen as "the nearest person in the part" (the part is the layout's), and the
    runner pushed the boulder against him for ever. A person behind a rock is not in reach."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod, strength

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.pos = lambda: (11, 2)
    r.read = lambda addr, n=1: [0] * n
    r.event = lambda kind, **facts: None
    monkeypatch.setattr(overworld, "sprites", lambda read: [(9, 2), (17, 2)])
    monkeypatch.setattr(strength, "live_boulders", lambda read: [(10, 2)])      # the corridor boulder

    layout = {(11, 2): True, (10, 2): True, (9, 2): True, (17, 2): True}
    r.grid = lambda sprites_block=True: layout
    monkeypatch.setattr(overworld, "astar", lambda grid, start, goal: ["LEFT"] if goal == (9, 2) else ["RIGHT"])

    part = {(11, 2), (10, 2), (9, 2), (17, 2)}
    assert r.guard_in_reach(108, part, layout) == (17, 2), "the man behind the boulder is skipped"


def test_a_door_that_a_rock_seals_is_not_marked_unusable():
    """BUG-0925: Victory Road 1F has one way down, the stair at (1, 1), and a rock can seal the one-wide
    corridor to it. The part of the map ignores the sprites (a rock is a sprite), so the stair was in the
    player's part while the walk could not reach it: six steps that did not move marked the door
    unusable, and an unusable door is dead for the milestone (BUG-0635). Every tick then answered "no
    route" and the run of 20261026-020740 stood still for 300 ticks on one square. The rock is the
    problem: the hop is marked blocked (BUG-0891) and the door stays unmarked."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    from shared.src.lib.game.pokemon.world import World
    vr1f = {"map": 108, "width": 20, "height": 18, "edges": {}, "spans": {},
            "warps": [[1, 1, 194, 0]], "parts": {"warp": [0], "edge": {}, "down": [], "player": 0}}
    vr2f = {"map": 194, "width": 10, "height": 10, "edges": {}, "spans": {},
            "warps": [], "parts": {"warp": [], "edge": {}, "down": [], "player": 0}}

    def make_runner(rock):
        r = object.__new__(runner_mod.Runner)
        r.memo = {}
        r.world = World({108: vr1f, 194: vr2f})
        r.read = lambda addr, n=1: [0] * max(n, 1)
        r.pos = lambda: (2, 9)                       # the corridor, in front of the sealed stair
        r.grid = lambda sprites_block=True: overworld.Grid({(x, y): True for x in range(20) for y in range(18)})
        r.event = lambda kind, **facts: None
        r.stuck, r.no_route_ticks = 6, 0             # six steps that did not move
        r.boulder_on_the_way = lambda start, target, layout=None: rock
        r.walk = lambda target, edge=None: "walk"
        return r

    sealed = make_runner((2, 10))                   # a rock seals the corridor to the stair
    assert sealed.go_to_map(108, 194, dict(vr1f)) == "walk"
    assert [108, 1, 1] not in sealed.memo.get("bad_warps", []), (
        "BUG-0925: a door that a rock seals was never stepped on: it is no unusable door")
    assert sealed.memo.get("hop_blocked") == [[108, 194]], "BUG-0925: the hop is marked blocked instead"

    clear = make_runner(None)                       # nothing seals it: the door itself failed
    assert clear.go_to_map(108, 194, dict(vr1f)) == "walk"
    assert [108, 1, 1] in clear.memo.get("bad_warps", []), (
        "BUG-0635: a door that fails six steps in is marked unusable")


def test_the_door_the_player_stands_on_is_not_marked_unusable():
    """BUG-0947: the player stands ON the stair of Victory Road 1F (1, 1) and the warp does not fire
    from there. The six ticks that did not move are the walk's failure to step onto the square, not
    the door's failure to fire, but the rock test is vacuous (the layout path from the square to
    itself is empty), so the door was marked unusable. An unusable door is dead for the milestone
    (BUG-0635): every tick answered "no route" and the player stood still on (1, 1) until the
    detector wrote same_spot (the run of 20261026-121745, the lane ping-ponging between Victory
    Road 1F and 2F). The door is not marked: the hop is marked blocked instead, and the guide walks
    the runner back to the waypoint it came from (BUG-0891), where the game puts the boulders of the
    floor back where they were."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    from shared.src.lib.game.pokemon.world import World
    vr1f = {"map": 108, "width": 20, "height": 18, "edges": {}, "spans": {},
            "warps": [[1, 1, 194, 0]], "parts": {"warp": [0], "edge": {}, "down": [], "player": 0}}
    vr2f = {"map": 194, "width": 10, "height": 10, "edges": {}, "spans": {},
            "warps": [], "parts": {"warp": [], "edge": {}, "down": [], "player": 0}}

    def make_runner(pos, rock):
        r = object.__new__(runner_mod.Runner)
        r.memo = {}
        r.world = World({108: vr1f, 194: vr2f})
        r.read = lambda addr, n=1: [0] * max(n, 1)
        r.pos = lambda: pos
        r.grid = lambda sprites_block=True: overworld.Grid({(x, y): True for x in range(20) for y in range(18)})
        r.event = lambda kind, **facts: None
        r.stuck, r.no_route_ticks = 6, 0             # six steps that did not move
        r.boulder_on_the_way = lambda start, target, layout=None: rock
        r.walk = lambda target, edge=None: "walk"
        r.step_off_warp = lambda here, info, target: "exit mat"
        return r

    on_it = make_runner((1, 1), None)                # the player stands on the stair
    assert on_it.go_to_map(108, 194, dict(vr1f)) == "exit mat"
    assert [108, 1, 1] not in on_it.memo.get("bad_warps", []), (
        "BUG-0947: the door the player stands on is not marked unusable")
    assert on_it.memo.get("hop_blocked") == [[108, 194]], (
        "BUG-0947: the hop is marked blocked instead, so the guide walks the runner back")

    beside = make_runner((2, 1), None)               # the player is beside the stair, the door fails
    assert beside.go_to_map(108, 194, dict(vr1f)) == "walk"
    assert [108, 1, 1] in beside.memo.get("bad_warps", []), (
        "BUG-0635: a door that fails six steps in is still marked unusable")


def test_a_door_that_is_dead_for_the_milestone_is_tried_again():
    """BUG-0948: a door marked unusable by a walk that did not move is dead for the milestone
    (BUG-0635): the route cannot start with it, every tick answers "no route" and the player
    stands still on the stair of Victory Road 1F for 300 ticks (the runs of 20261026-121745 and
    20261026-125130). The mark is dropped and the route is tried again: a walk that could not
    step onto the square is not a broken door."""
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    from shared.src.lib.game.pokemon.world import World
    vr1f = {"map": 108, "width": 20, "height": 18, "edges": {}, "spans": {},
            "warps": [[1, 1, 194, 0]], "parts": {"warp": [0], "edge": {}, "down": [], "player": 0}}
    vr2f = {"map": 194, "width": 10, "height": 10, "edges": {}, "spans": {},
            "warps": [], "parts": {"warp": [], "edge": {}, "down": [], "player": 0}}

    r = object.__new__(runner_mod.Runner)
    r.memo = {"bad_warps": [[108, 1, 1]], "warp_retried": [[108, 1, 1]]}
    r.world = World({108: vr1f, 194: vr2f})
    r.read = lambda addr, n=1: [0] * max(n, 1)
    r.pos = lambda: (1, 1)                          # the player stands ON the stair
    r.grid = lambda sprites_block=True: overworld.Grid({(x, y): True for x in range(20) for y in range(18)})
    events = []
    r.event = lambda kind, **facts: events.append({"kind": kind, **facts})
    r.stuck, r.no_route_ticks = 0, 0
    r.boulder_on_the_way = lambda start, target, layout=None: None
    r.walk = lambda target, edge=None: "walk"
    r.step_off_warp = lambda here, info, target: "exit mat"

    assert r.go_to_map(108, 194, dict(vr1f)) == "exit mat", (
        "BUG-0948: the way down is tried again instead of answering 'no route' for ever")
    assert [108, 1, 1] not in r.memo.get("bad_warps", []), (
        "BUG-0948: the mark of the door is dropped: it is not proven broken")
    assert any(e["kind"] == "warp_revived" for e in events), "BUG-0948: the revival is logged"


def test_the_rock_that_seals_the_player_in_is_pushed_aside(monkeypatch):
    """BUG-0948: the rock of the plan's push is not always the rock that seals the player in.
    Victory Road 1F: the plan starts with the rock west of the entrance (5, 15) and ends with the
    rock in the corridor to the stairs (2, 10). A player who comes down the stair from Victory
    Road 2F stands in the pocket with the stairs, where the plan's first push cannot be set up,
    the plan is given up and the pocket has no other way out: the lane ping-ponged between the
    two floors until the detector wrote same_spot (the run of 20261026-125130). The rock that
    seals the player in is pushed aside, whatever rock of the floor it is."""
    from shared.src.lib.game.pokemon import hm, strength

    boulders = [(5, 15), (2, 10)]
    monkeypatch.setattr(hm, "use_strength", lambda runner: True)
    monkeypatch.setattr(strength, "live_boulders", lambda read: list(boulders))

    from shared.src.lib.game.pokemon import runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.rom = b"\x00"
    r.memo = {}
    r.read = lambda addr, n=1: [108] if addr == runner_mod.ADDR["map"] else [0] * n
    pos = [(2, 9)]                          # the pocket with the stairs, north of the corridor rock
    r.pos = lambda: pos[0]
    # the pocket (1, 1) - (2, 9) and the big floor south of the corridor rock (2, 10)
    walk = {(x, y): True for x in range(1, 4) for y in range(1, 10)}
    walk.update({(x, y): True for x in range(1, 12) for y in range(11, 18)})
    walk[(2, 10)] = False                    # the corridor rock: it seals the pocket
    r.grid = lambda sprites_block=True: dict(walk)
    r.walk = lambda target, edge=None: "walk"

    def fake_step(direction):
        from shared.src.lib.game.pokemon import overworld
        dx, dy = overworld.STEP[direction]
        pos[0] = (pos[0][0] + dx, pos[0][1] + dy)
        for i, (bx, by) in enumerate(boulders):
            if (bx, by) == (2, 10) and direction == "DOWN":
                boulders[i] = (2, 11)       # the corridor rock slides south, out of the corridor
                break
        return True
    r.step = fake_step
    events = []
    r.event = lambda kind, **facts: events.append({"kind": kind, **facts})

    assert r.push_sealing_rock_aside("DOWN") == "boulder push"
    assert boulders == [(5, 15), (2, 11)], (
        "BUG-0948: the rock that seals the player in is pushed out of the corridor")
    pushes = [e for e in events if e["kind"] == "boulder_push"]
    assert len(pushes) == 1 and pushes[0]["boulder"] == [2, 10] and pushes[0]["direction"] == "DOWN", (
        "BUG-0948: the corridor rock is pushed the way the plan wants it pushed")


def test_the_way_to_route_5_goes_through_the_trashed_house_and_not_back_to_route_24():
    """BUG-0963: the `vermilion` milestone asks for Route 5 from Cerulean City, but Cerulean's south
    exit is in another part of the city: the trashed house's two doors, (27, 11) and (27, 9), are the
    only way between the parts and stepping on them warps the player into the house. The world graph
    therefore knows no route to Route 5, and the guide walked the runner back to the waypoint it came
    from (Route 24) - whose own next waypoint is Cerulean again. The two swapped the runner for ever:
    no milestone, no new map and no new square for 5 min of game time (the run of 20261026-204910, the
    `second` lane, map 35 at (10, 35)). The milestone's area holds the way on (the trashed house, the
    path under Route 5, the underground path): the runner explores it."""
    from shared.src.lib.game.pokemon import milestones as M
    from shared.src.lib.game.pokemon.runner import Runner
    from shared.src.lib.game.pokemon.world import World

    # the world graph measured on the live save (the run 20261026-204910)
    world = World({
        3: {"width": 40, "height": 36, "edges": {"north": 35, "south": 16, "west": 15, "east": 20},
            "spans": {"north": [10, 30], "south": [10, 30], "west": [8, 26], "east": [8, 26]},
            "warps": [(27, 11, 62, 0), (13, 15, 63, 0), (19, 17, 64, 0), (30, 19, 65, 0), (13, 25, 66, 0),
                      (25, 25, 67, 0), (4, 11, 228, 0), (27, 9, 62, 2), (9, 11, 230, 1), (9, 9, 230, 0)],
            "parts": {"player": 0, "down": [], "warp": [0, 0, 0, 0, 0, 0, 5, 4, 0, 3],
                      "edge": {"north": [0, 1], "south": [4, 9], "west": [0, 5, 8], "east": [2, 4, 6, 7]}}},
        35: {"width": 20, "height": 36, "edges": {"south": 3, "east": 36},
             "spans": {"south": [0, 20], "east": [0, 18]}, "warps": [],
             "parts": {"player": 0, "down": [], "warp": [], "edge": {"south": [0, 2], "east": [0, 1, 2]}}},
    })
    ms = {m.id: m for m in M.MILESTONES}["vermilion"]

    # the next waypoint cannot be reached: the south exit of Cerulean is in another part of the city
    assert not world.route(3, M.ROUTE5, start_part=0), "BUG-0963: Route 5 is out of reach from Cerulean"
    # the way back to the waypoint the runner came from is open: that is the ping-pong
    assert world.route(3, M.ROUTE24, start_part=0), "BUG-0963: Route 24 is the way back"

    r = Runner(_FakeIO(_Mem()), _rom(), world=world)
    # the milestone's area holds the way on: the door of the trashed house is one step away
    assert r.way_on_in_area(3, ms.area, 0), "BUG-0963: the area holds the way on (the trashed house)"
    # and the runner explores it: the house is the first hop of the way to Route 5
    route, exploring = r.find_route(3, M.ROUTE5, lambda how: True, 0, None, ms.area, True)
    assert exploring and [m for m, _ in route] == [M.TRASHED_HOUSE], (
        "BUG-0963: the runner goes through the trashed house")


def test_the_runner_walks_out_through_the_door_next_to_it_when_the_graph_knows_no_way_out():
    """BUG-0965: the runner was sealed in the one square of the house of Route 5 (map 70) next to its
    door. A door square is not part of the walkable fill (stepping on it warps the player), so the
    square the player stands on and the door can be in two different parts, and the world graph knows
    no way out of the player's part. The runner then answered "no route" on every tick - 607 of them
    (the run of 20261026-223502) - and stood still until the stall detector wrote the run down. The
    door is one step away: the runner steps on it and is out."""
    from shared.src.lib.game.pokemon.runner import Runner
    from shared.src.lib.game.pokemon.world import World

    # the world graph measured on the live save (the run of 20261026-223502)
    world = World({
        70: {"width": 8, "height": 6, "edges": {},
             "warps": [(3, 5, 16, 2), (4, 5, 16, 2), (3, 0, 16, 1), (4, 0, 16, 0)],
             "parts": {"player": 0, "down": [], "warp": [2, 2, 2, 2], "edge": {}}},
        16: {"width": 20, "height": 36, "edges": {"north": 3, "south": 10},
             "warps": [(10, 29, 70, 3), (9, 29, 70, 2), (10, 33, 70, 0), (17, 27, 71, 0), (10, 21, 72, 0)]},
    })
    # the graph knows no way out of the part the player stands in: every door is in another part
    assert not world.route(70, 16, start_part=0), "BUG-0965: the graph knows no way out of the house"

    mem = _Mem()
    mem.m[ADDR["map"]] = 70
    mem.m[ADDR["x"]], mem.m[ADDR["y"]] = 2, 0            # the one square next to the door
    r = Runner(_FakeIO(mem), _rom(), world=world)
    info = {"warps": [(3, 5, 16, 2), (4, 5, 16, 2), (3, 0, 16, 1), (4, 0, 16, 0)]}
    grid = {(2, 0): True, (3, 0): True}

    # the door next to the player is the way out
    assert r.door_beside(70, info, grid) == (3, 0), "BUG-0965: the door is one step away"
    # a door the game refused before is not tried again
    r.memo["bad_warps"] = [[70, 3, 0]]
    assert r.door_beside(70, info, grid) is None, "BUG-0965: a broken door is not tried again"


def _elevator_world():
    """The world graph of the stalled save (the Rocket Hideout's floors, the elevator's cabin and the
    Game Corner), measured on the run of 20261027-033452."""
    from shared.src.lib.game.pokemon.world import World
    return World({
        199: {"width": 30, "height": 28, "edges": {}, "spans": {},
              "warps": [(23, 2, 200, 0), (21, 2, 135, 2), (24, 19, 203, 0), (21, 24, 200, 3), (25, 19, 203, 1)],
              "parts": {"player": 2, "warp": [0, 0, 2, 1, 2], "edge": {}, "down": []}},
        200: {"width": 30, "height": 28, "edges": {}, "spans": {},
              "warps": [(27, 8, 199, 0), (21, 8, 201, 0), (24, 19, 203, 0), (21, 22, 199, 3), (25, 19, 203, 1)],
              "parts": {"player": 15, "warp": [1, 1, 15, 15, 15], "edge": {}, "down": [(15, 1)]}},
        202: {"width": 30, "height": 24, "edges": {}, "spans": {},
              "warps": [(19, 10, 201, 1), (24, 15, 203, 0), (25, 15, 203, 1)],
              "parts": {"player": 1, "warp": [0, 1, 1], "edge": {}, "down": []}},
        203: {"width": 6, "height": 8, "edges": {}, "spans": {},
              "warps": [(2, 1, 199, 4), (3, 1, 199, 4)],
              "parts": {"player": 0, "warp": [0, 0], "edge": {}, "down": []}},
        135: {"width": 20, "height": 18, "edges": {}, "spans": {},
              "warps": [(15, 17, 6, 7), (16, 17, 6, 7), (17, 4, 199, 1)],
              "parts": {"player": 0, "warp": [0, 0, 0], "edge": {}, "down": []}},
    })


def _elevator_grid():
    """The layout of the elevator's corridor (the tiles of the Rocket Hideout's B1F, measured on the
    stalled save): the two door squares at the bottom of a two-square room, the floor above them and
    the walls around. The player stands on (24, 19)."""
    from shared.src.lib.game.pokemon import overworld
    walkable = {(24, 17), (25, 17), (26, 17), (24, 18), (25, 18), (26, 18), (24, 19), (25, 19)}
    walls = {(23, 16), (24, 16), (25, 16), (26, 16), (23, 17), (23, 18), (23, 19),
             (26, 19), (24, 20), (25, 20), (26, 20)}
    g = overworld.Grid({sq: True for sq in walkable})
    g.update({sq: False for sq in walls})
    return g


def test_the_runner_fires_the_door_it_stands_on_when_the_graph_knows_no_way_out():
    """BUG-0966: the player stands ON the elevator's door of the Rocket Hideout's B1F (24, 19) and the
    world graph knows no way out of his part: the corridor is a dead end (the only warp of the part is
    the elevator, and the elevator's cabin leads back to the floor it came from). The only door next to
    him is the twin of the one under his feet, and moving between the two halves of a door never
    triggers a warp: the runner walked from (24, 19) to (25, 19) and back for 300 s (the run of
    20261027-033452) and the lane was dead. The door under his feet is fired instead: the game fires
    it when the player presses into the wall next to it (measured on the stalled save: pressing DOWN on
    (24, 19) takes him to the elevator's cabin, map 203)."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    world = _elevator_world()
    # the graph knows no way out of the corridor: the elevator's cabin leads back to B1F
    assert not world.route(199, 135, start_part=2), "BUG-0966: the graph knows no way out of the corridor"

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.world = world
    r.read = lambda addr, n=1: [0] * max(n, 1)
    r.pos = lambda: (24, 19)                       # the player stands on the left door square
    r.grid = lambda sprites_block=True: _elevator_grid()
    r.event = lambda kind, **facts: None
    r.step = lambda direction: True
    r.find_route = lambda *a, **k: (None, False)   # the graph knows no route to the way out
    r.unvisited_door = lambda *a, **k: None
    walked = []
    r.walk = lambda target, edge=None: walked.append(target) or "walk"

    info = {"map": 199, "width": 30, "height": 28, "edges": {}, "spans": {},
            "warps": [(23, 2, 200, 0), (21, 2, 135, 2), (24, 19, 203, 0), (21, 24, 200, 3), (25, 19, 203, 1)],
            "parts": {"player": 2, "warp": [0, 0, 2, 1, 2], "edge": {}, "down": []}}

    assert r.go_to_map(199, 135, info) == "door press", "BUG-0966: the door under his feet is fired"
    assert walked == [], "BUG-0966: the runner does not walk onto the twin of the door he stands on"
    assert r.memo["door_presses"] == {"199:24:19": 1}, "BUG-0966: the press is counted"


def test_the_door_the_player_stands_on_is_fired_into_the_wall():
    """BUG-0966: the Rocket elevator's door is drawn in a wall: the warp fires when the player presses
    into the wall next to the square he stands on (the press is refused and the warp happens instead).
    The twin of the door is not a wall and is never pressed into: moving between the two halves of a
    door never triggers a warp."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.pos = lambda: (24, 19)
    r.grid = lambda sprites_block=True: _elevator_grid()
    r.event = lambda kind, **facts: None
    pressed = []
    r.step = lambda direction: pressed.append(direction) or True
    info = {"map": 199, "width": 30, "height": 28, "edges": {}, "spans": {},
            "warps": [(23, 2, 200, 0), (21, 2, 135, 2), (24, 19, 203, 0), (21, 24, 200, 3), (25, 19, 203, 1)]}

    assert r.fire_door(199, info) == "door press", "BUG-0966: the door is fired"
    assert pressed == ["DOWN"], f"BUG-0966: the press goes into the wall below the door, got {pressed!r}"
    # the twin is never pressed into: the two halves of a door do not warp
    r.memo = {}
    r.pos = lambda: (24, 19)
    pressed.clear()
    r.fire_door(199, info)
    r.memo["door_presses"] = {"199:24:19": 1}
    r.fire_door(199, info)
    assert pressed == ["DOWN", "LEFT"], f"BUG-0966: the other wall side is tried next, got {pressed!r}"
    # a player who does not stand on a door has no door to fire
    r.pos = lambda: (24, 18)
    assert r.fire_door(199, info) is None, "BUG-0966: no door under his feet"


def test_the_elevator_takes_the_floor_the_graph_knows_a_way_out_of():
    """BUG-0966: the elevator's cabin is a leaf of the world graph (its warps lead back to the floor it
    came from), so the graph cannot say where the elevator goes: the floor to take is the one the graph
    knows a way out of. The way out of the Rocket Hideout is the Game Corner's hole: from B1F's landing
    part (the corridor, part 2) the graph knows no way out, but from B2F's (part 15) it does - the
    ledges and the stairs at (27, 8). Riding "1ER" would bring the player back to the corridor."""
    from shared.src.lib.game.pokemon import runner as runner_mod

    world = _elevator_world()
    assert not world.route(199, 135, start_part=2), "BUG-0966: B1F's landing part is a dead end"
    assert world.route(200, 135, start_part=15), "BUG-0966: B2F's landing part has a way out"

    r = object.__new__(runner_mod.Runner)
    r.memo = {}
    r.world = world
    ms = types.SimpleNamespace(id="poke_flute")
    assert r.lift_floor(ms) == "2EME", "BUG-0966: the elevator takes the floor with a way out"
    silph = types.SimpleNamespace(id="silph_scope")
    assert r.lift_floor(silph) == "4EME", "BUG-0966: Giovanni's floor for the Silph Scope"


def _route15_world():
    """The world graph of the stalled save (Route 15 and the Route 14 below it), measured on the run of
    20261027-052520: the routes of Fuchsia, the parts of Route 15 (the upper strip the player lands in,
    the lower strip under the ledge, the strip west of the gate house) and the gate house's four doors."""
    from shared.src.lib.game.pokemon.world import World
    return World({
        26: {"width": 60, "height": 18, "edges": {"west": 7, "east": 25},
             "spans": {"west": [0, 18], "east": [0, 18]},
             "warps": [(7, 8, 184, 0), (7, 9, 184, 1), (14, 8, 184, 2), (14, 9, 184, 3)],
             "parts": {"player": 1, "warp": [2, 2, 3, 3], "down": [(1, 3)],
                       "edge": {"west": [0, 2, 4], "east": [1, 3, 4]}}},
        25: {"width": 20, "height": 54, "edges": {"west": 26, "east": 24},
             "spans": {"west": [36, 54], "east": [0, 18]}, "warps": [],
             "parts": {"player": 2, "warp": [], "down": [],
                       "edge": {"west": [2, 3], "east": [1, 2]}}},
        24: {"width": 60, "height": 18, "edges": {"north": 23, "west": 25},
             "spans": {"north": [40, 60], "west": [0, 18]}, "warps": [],
             "parts": {"player": 1, "warp": [], "down": [], "edge": {"north": [1], "west": [0, 1]}}},
    })


def test_the_way_to_fuchsia_goes_through_the_gate_house_of_route_15_and_not_back_to_route_14():
    """BUG-0968: the `fuchsia` milestone asks for Fuchsia City from Route 15, but the road to Fuchsia
    passes through the gate house across Route 15: its two doors are on the route, (7, 8) and (14, 8),
    and the route is cut in two without them (the lower strip west of the house is the only way to the
    west edge, where Fuchsia is). The world graph learns a map's links only when the runner has been
    inside it, so the graph knew the door led to a map it had never seen and knew no way on to
    Fuchsia. The guide then walked the runner back to the waypoint it came from (Route 14) - whose own
    next waypoint is Route 15 again: the two swapped the runner for ever (the run of 20261027-052520,
    the `second` lane, map 26 at (59, 6): 2261 walk_targets, no milestone, no new map and no new square
    for 5 min of game time). The milestone's area holds the way on (the gate house of Route 15): the
    runner explores it, learns its doors and walks on to Fuchsia."""
    from shared.src.lib.game.pokemon import milestones as M
    from shared.src.lib.game.pokemon.runner import Runner

    world = _route15_world()
    ms = {m.id: m for m in M.MILESTONES}["fuchsia"]

    # the graph knows no way on to Fuchsia: the gate house is a map it has never been inside
    assert not world.route(26, M.FUCHSIA, start_part=1), (
        "BUG-0968: the graph knows no way to Fuchsia from Route 15")
    # the way back is open: that is the other half of the ping-pong
    assert world.route(26, 25, start_part=1), "BUG-0968: Route 14 is the way back"

    r = Runner(_FakeIO(_Mem()), _rom(), world=world)
    # without the gate house the area holds no way on: the guide walks the runner back to Route 14
    assert not r.way_on_in_area(26, (M.ROUTE12_GATE,), 1), (
        "BUG-0968: the area without the gate house holds no way on (the ping-pong of the stall)")
    # the gate house of Route 15 is the way on
    assert r.way_on_in_area(26, ms.area, 1), (
        "BUG-0968: the area holds the way on (the gate house of Route 15)")
    # and the runner explores it: the gate house is the first hop of the way to Fuchsia
    route, exploring = r.find_route(26, M.FUCHSIA, lambda how: True, 1, None, ms.area, True)
    assert exploring and [m for m, _ in route] == [M.ROUTE15_GATE], (
        "BUG-0968: the runner goes through the gate house")
