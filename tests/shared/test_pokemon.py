"""Pokémon Blue showcase library (TASK-33 phase 4): memory decoding, the ROM table finder and the battle
options, on synthetic bytes only. No ROM, no emulator.

Run: pytest tests/shared/test_pokemon.py -v
"""
import os
import sys
import types

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))

from shared.src.lib.game.pokemon import battle, learn  # noqa: E402
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
    monkeypatch.setattr(decisions, "choose", fake_choose)   # attributes, not sys.modules: the package caches them
    monkeypatch.setattr(router, "resolve_profile", fake_resolve)
    refs = {"game": "pokemon", "save": "latest", "script_result_id": "x"}
    chooser = game_pokemon.jev_choose("team-1", refs)
    out = chooser("the state", [{"id": "move1", "facts": "f"}], "pick one")
    assert out["choice"] == "move1" and out["decision_id"] == "dec-42"
    assert captured["log"] is True and captured["refs"] == refs
    first_save = captured["refs"]["save"]
    # the first call already snapshotted a copy of refs; mutating refs after that does not change it
    refs["save"] = "mutated"
    chooser("the state", [{"id": "move1", "facts": "f"}], "pick one")
    assert first_save == "latest"
    assert captured["refs"]["save"] == "mutated"


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
    """Three talks to the same blocker square add it to memo['walls'] with a blocker_wall event and a
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
    assert any(e["kind"] == "blocker_wall" and e["at"] == [1, 0] and e["map"] == 42 for e in r.log)

    # Fourth call: blocker is a wall, the re-plan walks instead of talking
    calls["talk"] = 0
    assert r.walk((3, 3)) == "walk"
    assert calls["talk"] == 0                           # no more talking to the same beaten trainer
    assert r.memo["walls"] == {"42": [[1, 0]]}          # walls stay permanent in the memo


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
    assert ids[ids.index("rainbow_badge"):] == ["rainbow_badge", "lift_key", "silph_scope", "poke_flute", "fuchsia", "soul_badge"]
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


def test_a_locked_room_sends_the_player_to_the_nearest_guard_a_few_times_only(monkeypatch):
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    monkeypatch.setattr(overworld, "sprites", lambda read: [(3, 0), (1, 0), (9, 9)])
    r = object.__new__(runner_mod.Runner)
    r.memo, r.pos = {}, lambda: (0, 0)
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


def test_the_lift_key_rocket_is_fought_before_the_ball_is_tried(monkeypatch):
    from shared.src.lib.game.pokemon import overworld, runner as runner_mod
    r = object.__new__(runner_mod.Runner)
    r.memo, r.pos = {}, lambda: (11, 3)                            # next to the Rocket at (11, 2)
    monkeypatch.setattr(overworld, "sprites", lambda read: [runner_mod.LIFT_KEY_GUARD])
    r.read = lambda addr, n=1: [0]
    r.talk_at = lambda who: who
    for _ in range(runner_mod.BLOCKER_TALKS_MAX):
        assert r.fetch_lift_key() == runner_mod.LIFT_KEY_GUARD       # the fight, then the beaten Rocket's talk
    assert r.fetch_lift_key() == runner_mod.LIFT_KEY_BALL            # the ball after that


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
    r.find_route = lambda here, dest, *a: asked.append(dest)      # no route: the call ends there
    r.guard_in_reach = lambda here, part: None
    r.world = types.SimpleNamespace(maps={})
    assert r.go_to_map(M.ROCKET_B4F, 0x85, {"spans": {}}) == "no route"
    assert asked == [M.ROCKET_LIFT]                               # a heal at Celadon's Center goes through the lift
    r.go_to_map(M.ROCKET_B4F, M.ROCKET_LIFT, {"spans": {}})
    assert asked[-1] == M.ROCKET_LIFT
    r.in_giovanni_wing = lambda info: False
    r.go_to_map(M.ROCKET_B4F, 0x85, {"spans": {}})
    assert asked[-1] == 0x85                                       # the other half of the floor keeps its own errand
