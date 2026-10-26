"""TASK-132: Garen bot rules, perception on synthetic frames, input guard."""

from __future__ import annotations

import numpy as np
import pytest

from shared.src.lib.game.leagueoflegends.game_input import GameInput, InputRefused, PracticeGuard
from shared.src.lib.game.leagueoflegends.garen_bot import (
    BUILD, IDLE_LIMIT_S, MINI_LANE_FARM, MINI_SAFE, GarenBot, Mem, State, anti_idle, decide, next_item, state_from_api,
)
from shared.src.lib.game.leagueoflegends.perception import PLAYER_XY, Bar, find_bars

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _exact_farm_loop(monkeypatch, request):
    """The exact-layer tests run against FARM_LOOP="exact"; the v2r tests ask for the default."""
    loop = "simple" if "simple_loop" in request.keywords else "marker" if "marker_loop" in request.keywords else "exact"
    monkeypatch.setattr("shared.src.lib.game.leagueoflegends.garen_bot.FARM_LOOP", loop)


def _frame() -> np.ndarray:
    return np.full((1200, 1920, 3), (90, 120, 60), dtype=np.uint8)


def _bar(img: np.ndarray, x0: int, y: int, filled: int, total: int, rgb=(197, 89, 89)) -> None:
    img[y - 1, x0 - 1:x0 + total + 1] = (12, 13, 14)
    img[y + 3, x0 - 1:x0 + total + 1] = (12, 13, 14)
    img[y:y + 3, x0:x0 + total] = (12, 13, 14)
    img[y:y + 3, x0:x0 + filled] = rgb


def _state(**kw) -> State:
    d = dict(t=100.0, game_t=200.0, hp=900.0, max_hp=1000.0, gold=100.0, level=3, dead=False, items=[])
    d.update(kw)
    return State(**d)


def test_find_bars_minion_health_fraction() -> None:
    img = _frame()
    _bar(img, 1000, 600, 31, 62)
    bars = find_bars(img, "enemy")
    assert len(bars) == 1 and bars[0].kind == "minion"
    assert bars[0].frac == pytest.approx(0.5, abs=0.05)


def test_find_bars_ignores_hud_and_minimap() -> None:
    img = _frame()
    _bar(img, 1000, 1100, 40, 62)  # bottom HUD
    _bar(img, 1700, 900, 40, 62)  # minimap / portraits
    assert find_bars(img, "enemy") == []


def test_find_bars_champion_is_wider() -> None:
    img = _frame()
    _bar(img, 700, 500, 120, 125)
    assert find_bars(img, "enemy")[0].kind == "champion"


def test_decide_dead_does_nothing() -> None:
    assert decide(_state(dead=True), Mem()) == []


def test_decide_walks_to_lane_when_no_minions() -> None:
    acts = decide(_state(), Mem())
    assert ("minimap",) + MINI_LANE_FARM in acts


def test_decide_last_hits_a_minion_within_one_auto_without_q_first() -> None:
    low = Bar("minion", PLAYER_XY[0] + 100, PLAYER_XY[1] - 40, 0.1, "enemy")  # about 50 hp <= 70 AD
    m = Mem(exact_enabled=False, last_lane_walk_t=100.0)
    acts = decide(_state(enemies=[low]), m)
    assert ("right", *low.body) in acts and ("key", "Q") not in acts  # Q is a reset after the auto, never first
    assert m.q_follow is not None  # ... pressed right after the auto lands if the minion is still alive


def test_decide_recalls_on_low_health_and_when_gold_covers_item() -> None:
    m = Mem()
    assert ("recall",) in decide(_state(hp=200.0), m) and m.mode == "RECALL"
    m2 = Mem()
    assert ("recall",) in decide(_state(gold=900.0), m2)


def test_recall_then_shop_then_return() -> None:
    m = Mem()
    decide(_state(hp=200.0), m)
    s = _state(t=100.0 + 10.0, hp=1000.0, gold=900.0)
    decide(s, m)  # channel done -> SHOP
    assert m.mode == "SHOP"
    acts = decide(s, m)
    assert ("shop", BUILD[0][0]) in acts and m.mode == "RETURN"


def test_next_item_skips_owned() -> None:
    assert next_item([BUILD[0][0]], Mem())[0] == BUILD[1][0]


def test_anti_idle_after_limit() -> None:
    m = Mem(last_action_t=0.0)
    assert anti_idle(_state(t=IDLE_LIMIT_S + 0.1), m) == [("minimap",) + MINI_LANE_FARM]
    assert anti_idle(_state(t=1.0), m) == []


def test_input_guard_refuses_outside_practice_tool() -> None:
    gi = GameInput(PracticeGuard(game_mode_fn=lambda: "CLASSIC", running_fn=lambda: True), dry_run=True)
    with pytest.raises(InputRefused):
        gi.key("Q")
    gi = GameInput(PracticeGuard(game_mode_fn=lambda: "PRACTICETOOL", running_fn=lambda: False), dry_run=True)
    with pytest.raises(InputRefused):
        gi.right_click(1, 1)
    gi = GameInput(PracticeGuard(game_mode_fn=lambda: "PRACTICETOOL", running_fn=lambda: True), dry_run=True)
    gi.key("Q")
    gi.right_click(5, 6)
    assert gi.log == [("key", "Q", False), ("right", 5, 6)]


def test_bot_loop_with_fakes_moves_and_farms() -> None:
    img = _frame()
    _bar(img, PLAYER_XY[0] + 80, PLAYER_XY[1] - 60, 12, 62)  # enemy minion at ~19 % health = 97 hp: one 100-damage auto kills it
    data = {"activePlayer": {"championStats": {"currentHealth": 900, "maxHealth": 1000, "attackDamage": 100}, "currentGold": 10, "level": 3,
                             "riotId": "me#1"},
            "allPlayers": [{"riotId": "me#1", "items": [], "isDead": False}], "gameData": {"gameTime": 200.0}}
    gi = GameInput(PracticeGuard(game_mode_fn=lambda: "PRACTICETOOL", running_fn=lambda: True), dry_run=True)
    t = {"now": 0.0}
    bot = GarenBot(gi, fetch=lambda: data, screenshot=lambda: img, sleep=lambda s: t.__setitem__("now", t["now"] + s),
                   clock=lambda: t["now"], tick_s=0.5)
    out = bot.run(max_s=10.0)
    kinds = [a[0] for _, a in bot.log]
    assert out["actions"] > 0 and "right" in kinds and bot.mem.lasthits


def test_state_from_api_reads_items() -> None:
    data = {"activePlayer": {"championStats": {"currentHealth": 1, "maxHealth": 2}, "currentGold": 3, "level": 4,
                             "summonerName": "me"},
            "allPlayers": [{"summonerName": "me", "items": [{"displayName": "Doran's Shield"}], "isDead": True}],
            "gameData": {"gameTime": 9}}
    s = state_from_api(data, [], [], 5.0)
    assert s and s.items == ["Doran's Shield"] and s.dead and s.level == 4


def test_presses_y_only_when_own_bar_missing() -> None:
    m = Mem()
    acts = decide(_state(self_visible=False, game_t=20.0), m)
    assert acts == [("key", "Y")]
    assert ("key", "Y") not in decide(_state(self_visible=False, game_t=20.0, t=105.0), m)  # not again within 10 s
    assert ("key", "Y") not in decide(_state(self_visible=True, game_t=40.0, t=200.0), Mem())


def test_walks_toward_far_minions() -> None:
    far = Bar("minion", PLAYER_XY[0] + 600, PLAYER_XY[1], 1.0, "enemy")
    acts = decide(_state(enemies=[far]), Mem())
    kinds = [a for a in acts if a[0] == "move"]
    assert kinds and kinds[0][1] > PLAYER_XY[0]


def test_retreats_when_past_the_middle_of_the_lane() -> None:
    far = Bar("minion", PLAYER_XY[0] + 600, PLAYER_XY[1], 1.0, "enemy")
    acts = decide(_state(enemies=[far], pos=(0.25, 0.07)), Mem())
    mm = [a for a in acts if a[0] == "minimap"]
    assert mm and mm[0][1:] != MINI_LANE_FARM
    acts = decide(_state(enemies=[far], pos=(0.12, 0.2)), Mem())
    assert [a for a in acts if a[0] == "move"]


def _turret(dx=0, dy=-300) -> Bar:
    return Bar("turret", PLAYER_XY[0] + dx, PLAYER_XY[1] + dy, 1.0, "enemy")


def test_does_not_enter_turret_range_without_three_allied_minions() -> None:
    m = Mem()
    acts = decide(_state(enemies=[_turret()], allies=[]), m)
    assert ("minimap",) + MINI_SAFE in acts and m.retreat_until > 100.0
    # with three allied minions inside the range it keeps farming
    allies = [Bar("minion", PLAYER_XY[0] + 40 * i, PLAYER_XY[1] - 250, 1.0, "ally") for i in range(3)]
    m2 = Mem()
    acts2 = decide(_state(enemies=[_turret()], allies=allies), m2)
    assert ("minimap",) + MINI_SAFE not in acts2


def test_leaves_when_the_turret_hits_us() -> None:
    allies = [Bar("minion", PLAYER_XY[0] + 40 * i, PLAYER_XY[1] - 250, 1.0, "ally") for i in range(3)]
    m = Mem()
    decide(_state(t=100.0, hp=1000.0, enemies=[_turret()], allies=allies), m)
    acts = decide(_state(t=101.0, hp=880.0, enemies=[_turret()], allies=allies), m)
    assert ("minimap",) + MINI_SAFE in acts


def test_recall_at_800_gold_only_when_safe() -> None:
    m = Mem()
    assert ("recall",) in decide(_state(gold=850.0, enemies=[]), m)
    champ = Bar("champion", PLAYER_XY[0] + 200, PLAYER_XY[1] - 40, 0.9, "enemy")
    m2 = Mem()
    assert ("recall",) not in decide(_state(gold=850.0, enemies=[champ]), m2)


def test_fights_laner_only_with_a_health_edge_and_logs_it() -> None:
    weak = Bar("champion", PLAYER_XY[0] + 200, PLAYER_XY[1] - 40, 0.5, "enemy")
    m = Mem()
    acts = decide(_state(hp=900.0, enemies=[weak]), m)
    assert ("key", "E") in acts and ("key", "Q") in acts and m.fights and m.fights[0]["action"] == "engage"
    strong = Bar("champion", PLAYER_XY[0] + 200, PLAYER_XY[1] - 40, 1.0, "enemy")
    m2 = Mem()
    acts2 = decide(_state(hp=500.0, enemies=[strong]), m2)
    assert ("key", "E") not in acts2 and m2.fights[0]["action"] == "avoid"


def test_ults_when_it_kills() -> None:
    low = Bar("champion", PLAYER_XY[0] + 200, PLAYER_XY[1] - 40, 0.2, "enemy")
    acts = decide(_state(level=6, hp=900.0, enemies=[low]), Mem())
    assert ("key", "R") in acts


def test_lane_geometry_blue_and_red_and_turret_down() -> None:
    from shared.src.lib.game.leagueoflegends.lane_map import enemy_top_turrets_down, lane_geometry, too_close
    blue = lane_geometry("ORDER", 0)
    red = lane_geometry("CHAOS", 0)
    assert blue["turret"][0] > 0.2 and red["turret"][1] > 0.2  # blue meets red T1 on the top edge, red meets blue T1 on the left edge
    assert blue["farm_px"][0] > red["farm_px"][0] - 1 and red["farm_px"][1] > blue["farm_px"][1]
    # after the first enemy turret falls the fence moves on and the farm spot moves toward the enemy
    assert lane_geometry("ORDER", 1)["farm_px"][0] > blue["farm_px"][0]
    assert lane_geometry("ORDER", 3)["turret"] is None
    assert too_close((0.25, 0.07), blue["turret"]) and not too_close((0.1, 0.1), blue["turret"])
    ev = [{"EventName": "TurretKilled", "TurretKilled": "Turret_TChaos_L2_P3_1_0"},
          {"EventName": "TurretKilled", "TurretKilled": "Turret_TOrder_L2_P3_2_0"},
          {"EventName": "TurretKilled", "TurretKilled": "Turret_TChaos_L1_P3_3_0"}]
    assert enemy_top_turrets_down(ev, "ORDER") == 1 and enemy_top_turrets_down(ev, "CHAOS") == 1


def test_red_side_fence_uses_the_blue_turret() -> None:
    from shared.src.lib.game.leagueoflegends.lane_map import lane_geometry
    g = lane_geometry("CHAOS", 0)
    far = Bar("minion", PLAYER_XY[0] + 600, PLAYER_XY[1], 1.0, "enemy")
    s = _state(enemies=[far], pos=(0.075, 0.25), fence_turret=g["turret"], farm_px=g["farm_px"], safe_px=g["safe_px"])
    acts = decide(s, Mem())
    assert ("minimap",) + g["safe_px"] in acts  # red Garen at (0.075, 0.25) is within 0.13 of the blue T1 (0.066, 0.295)


def test_shop_is_open_detects_the_tab_header() -> None:
    from pathlib import Path

    from PIL import Image

    from shared.src.lib.game.leagueoflegends.perception import shop_is_open

    tpl = np.asarray(Image.open(Path(__file__).resolve().parents[2] / "shared/src/lib/game/leagueoflegends/nav_templates/shop_tabs.png").convert("RGB"))
    img = _frame()
    assert not shop_is_open(img)
    img[118:118 + tpl.shape[0], 470:470 + tpl.shape[1]] = tpl
    assert shop_is_open(img)


# --- v2: start items, camera lock, base-only shop, watchdogs ---------------------------------------------------------------


def _guard_ok() -> PracticeGuard:
    return PracticeGuard(game_mode_fn=lambda: "PRACTICETOOL", running_fn=lambda: True)


def _own_bar_frame() -> np.ndarray:
    img = _frame()
    _bar(img, 814, 448, 120, 125, rgb=(40, 120, 220))  # our own bar where a locked camera puts it
    return img


def _bot(owned=None, frames=None) -> GarenBot:
    gi = GameInput(_guard_ok(), dry_run=True)
    owned = owned if owned is not None else []
    data = lambda: {"activePlayer": {"riotId": "me#1", "championStats": {"currentHealth": 1, "maxHealth": 1}},
                    "allPlayers": [{"riotId": "me#1", "items": [{"displayName": n} for n in owned]}]}
    t = {"now": 0.0}
    bot = GarenBot(gi, fetch=data, screenshot=frames or (lambda: _frame()), sleep=lambda s: t.__setitem__("now", t["now"] + s),
                   clock=lambda: t["now"])
    return bot


def _cam_frame(locked: bool) -> np.ndarray:
    img = _frame()
    icon = _tpl("camera_locked.png" if locked else "camera_unlocked.png")
    img[1168:1168 + icon.shape[0], 1529:1529 + icon.shape[1]] = icon
    return img


def test_lock_camera_presses_y_only_when_the_camera_button_shows_unlocked() -> None:
    bot = _bot()
    bot.screenshot = lambda: _cam_frame(("key", "Y", False) in bot.gi.log)
    assert bot.lock_camera() is True
    assert bot.gi.log.count(("key", "Y", False)) == 1
    locked = _bot(frames=lambda: _cam_frame(True))
    assert locked.lock_camera() is True and ("key", "Y", False) not in locked.gi.log  # already locked: never toggle it off


def test_lock_camera_fails_loudly_after_three_tries() -> None:
    bot = _bot(frames=lambda: _cam_frame(False))
    assert bot.lock_camera() is False
    assert bot.gi.log.count(("key", "Y", False)) == 3
    assert bot.mem.events[-1]["kind"] == "camera_locked" and "FAILED" in bot.mem.events[-1]["detail"]


def test_buy_start_items_buys_missing_items_and_verifies_through_the_api() -> None:
    owned: list = []
    bot = _bot(owned)
    bought: list = []

    def fake_buy(item: str, open_budget_s: float = 2.0) -> bool:
        bought.append(item)
        owned.append(item)
        return True

    bot.buy = fake_buy  # type: ignore[assignment]
    assert bot.buy_start_items() is True
    assert bought == ["Doran's Shield", "Health Potion"]
    assert bot.mem.events[-1] == {"t": 0.0, "kind": "start_items", "detail": "ok [\"Doran's Shield\", 'Health Potion']"}


def test_buy_start_items_retries_once_then_reports_failure() -> None:
    bot = _bot([])
    bot.buy = lambda item, open_budget_s=2.0: False  # type: ignore[assignment]
    assert bot.buy_start_items() is False
    assert "FAILED" in bot.mem.events[-1]["detail"]


def test_recall_arrives_in_the_fountain_then_shops_there_only() -> None:
    base = (0.08, 0.92)
    m = Mem()
    decide(_state(t=100.0, hp=200.0, pos=(0.1, 0.2)), m)  # low health: recall starts
    assert m.mode == "RECALL"
    decide(_state(t=104.0, pos=(0.1, 0.2)), m)
    assert m.mode == "RECALL"  # still on the lane: no shop
    decide(_state(t=109.0, pos=base), m)
    assert m.mode == "SHOP" and m.events[-1]["kind"] == "recall_arrived"
    acts = decide(_state(t=109.5, gold=900.0, pos=base), m)
    assert ("shop", BUILD[0][0]) in acts and m.mode == "RETURN"


def test_shop_is_refused_outside_the_fountain() -> None:
    m = Mem(mode="SHOP", mode_since=100.0)
    acts = decide(_state(t=101.0, gold=900.0, pos=(0.1, 0.4)), m)
    assert not [a for a in acts if a[0] == "shop"] and m.mode == "LANE" and m.events[-1]["kind"] == "shop_refused"


def test_recall_interrupted_by_damage_retreats_and_retries_later() -> None:
    m = Mem(mode="RECALL", mode_since=100.0, hp_hist=[(102.0, 1000.0)])
    acts = decide(_state(t=103.0, hp=900.0, pos=(0.1, 0.4)), m)
    assert m.mode == "LANE" and m.events[-1]["kind"] == "recall_interrupted" and acts and acts[0][0] == "minimap"
    assert m.last_recall_t > 100.0 - 150.0 + 14.0  # a retry is allowed in about 15 s


def test_watchdog_resets_every_timed_mode() -> None:
    for mode, limit in (("RECALL", 14.0), ("RETURN", 45.0)):
        m = Mem(mode=mode, mode_since=100.0)
        decide(_state(t=100.0 + limit + 1.0, pos=(0.1, 0.4), gold=0.0), m)
        assert m.mode == "LANE" and m.events[-1]["kind"] == "stuck" and m.stuck_s >= limit


def test_input_is_refused_when_the_game_window_is_not_in_the_foreground() -> None:
    gi = GameInput(PracticeGuard(game_mode_fn=lambda: "PRACTICETOOL", running_fn=lambda: True, foreground_fn=lambda: False),
                   dry_run=True)
    with pytest.raises(InputRefused):
        gi.key("P")


def _hud_frame() -> np.ndarray:
    img = _frame()
    img[1156:1166, 705:1085] = (30, 200, 40)  # the champion's green health bar in the bottom HUD
    return img


def test_hud_visible_only_with_the_in_game_hud() -> None:
    from shared.src.lib.game.leagueoflegends.perception import hud_visible
    assert hud_visible(_hud_frame()) and not hud_visible(_frame())


def test_wait_in_game_needs_a_rising_clock_past_25_s_and_the_hud() -> None:
    bot = _bot(frames=_hud_frame)
    clock = {"g": 5.0}
    bot._game_time = lambda: clock.__setitem__("g", clock["g"] + 10.0) or clock["g"]  # type: ignore[assignment]
    assert bot.wait_in_game() is True and bot.mem.events[-1]["kind"] == "in_game"
    loading = _bot(frames=lambda: _frame())  # clock fine, but no HUD: still the loading screen
    loading._game_time = lambda: 60.0  # type: ignore[assignment]
    assert loading.wait_in_game(timeout_s=6.0) is False and "FAILED" in loading.mem.events[-1]["detail"]


def test_start_sequence_stops_when_start_items_cannot_be_bought() -> None:
    bot = _bot([], frames=_hud_frame)
    bot._game_time = lambda: 60.0  # type: ignore[assignment]
    bot.buy = lambda item, open_budget_s=2.0: False  # type: ignore[assignment]
    assert bot.start_sequence() is False


# --- the shop purchase: find, type, buy by three methods, verify through the API ---------------------------------------------


def _tpl(name: str) -> np.ndarray:
    from pathlib import Path

    from PIL import Image

    base = Path(__file__).resolve().parents[2] / "shared/src/lib/game/leagueoflegends/nav_templates"
    return np.asarray(Image.open(base / name).convert("RGB"))


def _shop_frame(search_empty: bool) -> np.ndarray:
    img = _frame()
    tabs = _tpl("shop_tabs.png")
    img[118:118 + tabs.shape[0], 470:470 + tabs.shape[1]] = tabs
    if search_empty:
        ph = _tpl("shop_search_empty.png")
        img[188:188 + ph.shape[0], 470:470 + ph.shape[1]] = ph
    return img


def _shop_bot(works_with: str, search_empty: bool = False):
    owned: list = []
    gold = {"v": 900.0}
    gi = GameInput(_guard_ok(), dry_run=True)
    t = {"now": 0.0}

    def fetch():
        # the purchase "lands" only for the chosen method
        if works_with == "right-click" and any(a[0] == "right" for a in gi.log) and not owned:
            owned.append("Doran's Shield"); gold["v"] -= 450
        elif works_with == "double-click" and sum(1 for a in gi.log if a[0] == "left") >= 2 and not owned:
            owned.append("Doran's Shield"); gold["v"] -= 450
        elif works_with == "purchase-button" and sum(1 for a in gi.log if a[0] == "left") >= 4 and not owned:
            owned.append("Doran's Shield"); gold["v"] -= 450
        return {"activePlayer": {"riotId": "me#1", "currentGold": gold["v"], "championStats": {"currentHealth": 1, "maxHealth": 1}},
                "allPlayers": [{"riotId": "me#1", "items": [{"displayName": n} for n in owned]}]}

    bot = GarenBot(gi, fetch=fetch, screenshot=lambda: _shop_frame(search_empty), sleep=lambda s: t.__setitem__("now", t["now"] + s),
                   clock=lambda: t["now"])
    return bot


def test_buy_by_right_click_is_logged_and_verified() -> None:
    bot = _shop_bot("right-click")
    bot.close_shop = lambda: None  # type: ignore[assignment]  # the fake screen keeps showing the shop
    assert bot.buy("Doran's Shield") is True
    assert bot.mem.events[-1]["kind"] == "bought" and "right-click" in bot.mem.events[-1]["detail"]


def test_buy_falls_back_to_double_click_then_the_purchase_button() -> None:
    for method in ("double-click", "purchase-button"):
        bot = _shop_bot(method)
        bot.close_shop = lambda: None  # type: ignore[assignment]
        assert bot.buy("Doran's Shield") is True
        assert method in bot.mem.events[-1]["detail"]


def test_buy_fails_loudly_when_the_name_never_lands_in_the_search_box() -> None:
    bot = _shop_bot("right-click", search_empty=True)
    bot.close_shop = lambda: None  # type: ignore[assignment]
    assert bot.buy("Doran's Shield") is False
    kinds = [e["kind"] for e in bot.mem.events]
    assert kinds.count("shop_search") >= 2 and not any(a[0] == "right" for a in bot.gi.log)  # nothing clicked blindly


def test_shop_search_is_empty_reads_the_placeholder() -> None:
    from shared.src.lib.game.leagueoflegends.perception import shop_search_is_empty
    assert shop_search_is_empty(_shop_frame(True)) and not shop_search_is_empty(_shop_frame(False))


def test_camera_is_locked_reads_the_hud_button() -> None:
    from shared.src.lib.game.leagueoflegends.perception import camera_is_locked
    assert camera_is_locked(_cam_frame(True)) and not camera_is_locked(_cam_frame(False))


# --- last-hit by computed damage ---------------------------------------------------------------------------------------------


def _m(dx: int, frac: float, mtype=None, dy: int = -40) -> Bar:
    return Bar("minion", PLAYER_XY[0] + dx, PLAYER_XY[1] + dy, frac, "enemy", mtype)


def _lh_state(enemies, **kw) -> State:
    d = dict(enemies=enemies, ad=70.0, cs=10, level=1, game_t=60.0)  # level 1: no Q rank yet
    d.update(kw)
    return _state(**d)


def test_last_hit_waits_until_the_minion_dies_from_one_auto() -> None:
    healthy = _m(100, 0.9)  # about 420 hp: far from dying
    m = Mem(last_action_t=100.0, last_lane_walk_t=100.0)
    acts = decide(_lh_state([healthy]), m)
    assert not m.lasthits  # a healthy minion is farmed (see test_farm_hit...), but it is never counted as a last-hit attempt


def test_last_hit_attacks_when_health_is_within_one_auto() -> None:
    low = _m(100, 0.12)  # 0.12 x 480 = 58 hp <= 70 x 1.15
    m = Mem(exact_enabled=False)
    acts = decide(_lh_state([low]), m)
    assert ("right", *low.body) in acts and m.lasthits and m.lasthits[0]["result"] is None


def test_last_hit_takes_the_cannon_before_melee_and_caster() -> None:
    cannon, melee, caster = _m(120, 0.06, "cannon"), _m(60, 0.1, "melee"), _m(90, 0.15, "caster")
    acts = decide(_lh_state([melee, caster, cannon]), Mem(exact_enabled=False))
    rights = [a for a in acts if a[0] == "right"]
    assert rights[0][1:] == cannon.body


def test_last_hit_never_trades_a_cannon_for_a_caster() -> None:
    cannon = _m(120, 0.12, "cannon")  # about 103 hp: dies to auto + Q reset at level 8
    caster = _m(60, 0.1, "caster")  # about 28 hp: one auto
    m = Mem(exact_enabled=False)
    acts = decide(_state(enemies=[caster, cannon], ad=70.0, cs=10, level=8, game_t=60.0), m)
    assert [a for a in acts if a[0] == "right"][0][1:] == cannon.body and m.q_follow is not None


def test_q_is_pressed_after_the_auto_landed_when_the_minion_is_still_alive() -> None:
    m = Mem(exact_enabled=False, q_follow={"t": 100.0, "wait": 0.5, "x": PLAYER_XY[0] + 100, "y": PLAYER_XY[1] + 10})
    still = _m(100, 0.2, dy=-40)  # about 100 hp after our auto: within AD + Q bonus at level 8
    acts = decide(_state(enemies=[still], ad=70.0, cs=10, level=8, game_t=60.0, t=100.6), m)
    assert ("key", "Q") in acts and m.q_follow is None


def test_no_e_while_farming() -> None:
    wave = [_m(60 + 40 * i, 0.9) for i in range(4)]  # four healthy minions around us
    m = Mem(last_action_t=0.0, last_lane_walk_t=100.0)
    acts = decide(_state(enemies=wave, t=100.0), m)
    assert ("key", "E") not in acts  # E blocks autos for 3 s


def test_last_hit_results_are_resolved_from_the_creep_score() -> None:
    low = _m(100, 0.1)
    m = Mem(exact_enabled=False)
    decide(_lh_state([low], t=100.0), m)
    decide(_lh_state([], t=104.0, cs=11), m)
    assert m.lasthits[0]["result"] == "hit" and m.events[-1]["kind"] == "lasthit"
    decide(_lh_state([low], t=110.0, cs=11), m)
    decide(_lh_state([], t=114.0, cs=11), m)
    assert [h["result"] for h in m.lasthits] == ["hit", "miss"]


def test_last_hit_calibrates_the_health_estimate_from_our_own_hit() -> None:
    m = Mem(exact_enabled=False)
    decide(_lh_state([_m(100, 0.25)], t=100.0, ad=140.0), m)  # 0.25 x 480 = 120 hp <= 140: we hit it
    assert m.cal and m.hp_scale == 1.0
    # 1.5 s later the same bar is at 0.05: our 140 damage took 0.20 of its health => max health about 700 (the prior says 480)
    decide(_lh_state([_m(100, 0.05)], t=101.6, ad=140.0), m)
    assert m.hp_scale > 1.0 and m.cal_log and 600 < m.cal_log[0]["implied_max_hp"] < 800


def test_last_hit_predicts_health_at_impact_from_the_drop_rate() -> None:
    steady = Mem()
    for i, f in enumerate((0.20, 0.20, 0.20)):
        acts = decide(_lh_state([_m(100, f)], t=100.0 + 0.4 * i, ad=140.0), steady)
    assert [a for a in acts if a[0] == "right"]  # a steady 96 hp minion is hit
    dying = Mem()
    for i, f in enumerate((0.60, 0.45, 0.30, 0.20)):  # losing 0.35 of its health per second to allied minions
        acts = decide(_lh_state([_m(100, f)], t=100.0 + 0.4 * i, ad=140.0), dying)


def test_minion_tracker_drop_rate_follows_a_bar_between_ticks() -> None:
    from shared.src.lib.game.leagueoflegends.minion_track import MinionTracker
    tr = MinionTracker()
    for t, f in ((0.0, 0.8), (0.5, 0.7), (1.0, 0.6)):
        tr.update(t, [_m(100, f)])
    assert tr.drop_rate(_m(100, 0.6)) == pytest.approx(0.2, abs=0.02)
    assert tr.drop_rate(_m(400, 0.6)) == 0.0  # an unknown minion has no history


def test_minion_type_is_unknown_from_the_bar_alone() -> None:
    img = _frame()
    _bar(img, 1000, 600, 40, 62)
    _bar(img, 1200, 600, 40, 70)  # a wider frame is NOT a cannon (a real cannon has the 62 px bar in patch 26.20)
    assert all(b.minion_type is None for b in find_bars(img, "enemy"))


def test_last_hit_closes_the_distance_before_attacking_and_counts_one_attempt_per_minion() -> None:
    far = _m(500, 0.12)  # killable, but 500 px away: out of attack range
    m = Mem(exact_enabled=False)
    acts = decide(_lh_state([far], t=100.0), m)
    assert not m.lasthits and [a for a in acts if a[0] == "move"][0][1] > PLAYER_XY[0]  # walks toward it, no attempt yet
    near = _m(100, 0.12)
    m2 = Mem(exact_enabled=False)
    decide(_lh_state([near], t=100.0), m2)
    decide(_lh_state([near], t=100.5), m2)  # the click is re-issued, it is not a second attempt
    assert len(m2.lasthits) == 1


def test_camera_state_reads_both_buttons_at_other_hud_scales() -> None:
    import cv2

    from shared.src.lib.game.leagueoflegends.perception import camera_state
    assert camera_state(_cam_frame(True)) is True and camera_state(_cam_frame(False)) is False
    assert camera_state(_frame()) is None  # no button on screen: cannot tell
    small = _frame()
    icon = cv2.resize(_tpl("camera_locked.png"), None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)  # a smaller minimap setting
    small[1170:1170 + icon.shape[0], 1700:1700 + icon.shape[1]] = icon
    assert camera_state(small) is True


def test_lock_camera_never_presses_y_when_the_button_cannot_be_read() -> None:
    bot = _bot(frames=lambda: _frame())  # no camera button on screen
    assert bot.lock_camera() is False
    assert ("key", "Y", False) not in bot.gi.log and "cannot be read" in bot.mem.events[-1]["detail"]


def test_start_sequence_logs_the_time_of_each_step() -> None:
    owned: list = []
    bot = _bot(owned, frames=lambda: _cam_frame(True) if False else _hud_with_camera())
    bot._game_time = lambda: 5.0  # type: ignore[assignment]

    def fake_buy(item: str, open_budget_s: float = 2.0) -> bool:
        owned.append(item)
        return True

    bot.buy = fake_buy  # type: ignore[assignment]
    assert bot.start_sequence() is True
    assert bot.mem.events[-1]["kind"] == "start_timing" and "ready" in bot.mem.events[-1]["detail"]
    assert owned == ["Doran's Shield", "Health Potion"]


def _hud_with_camera() -> np.ndarray:
    img = _hud_frame()
    icon = _tpl("camera_locked.png")
    img[1168:1168 + icon.shape[0], 1529:1529 + icon.shape[1]] = icon
    return img


def test_hud_calibrated_needs_the_camera_button_at_the_calibrated_place() -> None:
    import cv2

    from shared.src.lib.game.leagueoflegends.perception import hud_calibrated
    assert hud_calibrated(_cam_frame(True)) and hud_calibrated(_cam_frame(False))
    assert not hud_calibrated(_frame())
    small = _frame()  # a smaller minimap setting: the button is smaller and elsewhere
    icon = cv2.resize(_tpl("camera_locked.png"), None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA)
    small[1180:1180 + icon.shape[0], 1700:1700 + icon.shape[1]] = icon
    assert not hud_calibrated(small)


def test_start_sequence_marks_an_uncalibrated_hud_invalid_and_does_not_play() -> None:
    bot = _bot([], frames=_hud_frame)  # HUD up, but no camera button where calibrated
    bot._game_time = lambda: 10.0  # type: ignore[assignment]
    bot.buy = lambda item, open_budget_s=2.0: (_ for _ in ()).throw(AssertionError("must not buy on an invalid run"))  # type: ignore[assignment]
    assert bot.start_sequence() is False
    assert bot.mem.events[-1]["kind"] == "hud_calibration" and "INVALID" in bot.mem.events[-1]["detail"]


def test_pin_hud_restores_the_calibrated_settings_with_a_one_time_backup(tmp_path) -> None:
    import json

    from shared.src.lib.game.leagueoflegends.hud_settings import pin_hud

    (tmp_path / "game.cfg").write_text("[General]\nWidth=1920\nHeight=1200\n[HUD]\nMinimapScale=0.4500\nCameraLockMode=0\n", encoding="utf-8")
    (tmp_path / "PersistedSettings.json").write_text(json.dumps({"files": [{"sections": [{"settings": [
        {"name": "MinimapScale", "value": "0.45"}, {"name": "CameraLockMode", "value": "0"}, {"name": "Other", "value": "5"}]}]}]}),
        encoding="utf-8")
    changes = pin_hud(str(tmp_path))
    assert any("MinimapScale 0.4500 -> 1.2300" in c for c in changes) and any("CameraLockMode" in c for c in changes)
    cfg = (tmp_path / "game.cfg").read_text()
    assert "MinimapScale=1.2300" in cfg and "CameraLockMode=1" in cfg
    persisted = json.loads((tmp_path / "PersistedSettings.json").read_text())["files"][0]["sections"][0]["settings"]
    assert {s["name"]: s["value"] for s in persisted} == {"MinimapScale": "1.2300", "CameraLockMode": "1", "Other": "5"}
    assert (tmp_path / "game.cfg.bak-orig").exists()
    assert pin_hud(str(tmp_path)) == []  # idempotent: nothing to change the second time
    with pytest.raises(RuntimeError):
        pin_hud(str(tmp_path), game_running=True)


# --- movement layer: minimap only for far moves, no click when already there, one click per destination -----------------------


def _moves(acts) -> list:
    return [a for a in acts if a[0] in ("move", "minimap")]


def test_no_click_when_already_at_the_destination() -> None:
    from shared.src.lib.game.leagueoflegends.lane_map import to_pixels
    s0 = _state(pos=(0.133, 0.074), farm_px=to_pixels((0.133, 0.074)))  # standing on the farm spot, nothing in view
    m = Mem()
    clicks = 0
    for i in range(20):  # a fake position sequence that never leaves the destination
        clicks += len(_moves(decide(_state(t=100.0 + 0.5 * i, pos=(0.133, 0.074), farm_px=s0.farm_px, safe_px=s0.safe_px), m)))
    assert clicks == 0 and m.clicks["redundant_avoided"] > 0


def test_one_click_per_destination_until_garen_stops_short_of_it() -> None:
    m = Mem()
    far = to_dest = (1700, 1100)  # a far minimap destination (base side)
    first = _moves(decide(_state(t=100.0, pos=(0.5, 0.5), farm_px=to_dest), m))
    again = _moves(decide(_state(t=100.6, pos=(0.5, 0.49), farm_px=to_dest), m))  # still walking
    assert len(first) == 1 and first[0][0] == "minimap" and again == []
    stuck = [_moves(decide(_state(t=101.0 + 0.4 * i, pos=(0.5, 0.49), farm_px=to_dest), m)) for i in range(6)]  # stopped short for > 1 s
    assert sum(len(x) for x in stuck) == 1


def test_in_lane_moves_use_the_screen_not_the_minimap() -> None:
    m = Mem()
    near_dest = (1655, 925)  # a destination about 0.03 minimap units from Garen: a screen click, never the minimap
    acts = _moves(decide(_state(t=100.0, pos=(0.12, 0.17), farm_px=near_dest), m))
    assert acts and acts[0][0] == "move" and m.clicks["move_minimap"] == 0 and m.clicks["move_screen"] == 1
    far = _moves(decide(_state(t=110.0, pos=(0.9, 0.9), farm_px=(1655, 925)), Mem()))
    assert far and far[0][0] == "minimap"  # a long walk still uses the minimap


def test_click_counters_split_attack_and_move() -> None:
    low = Bar("minion", PLAYER_XY[0] + 100, PLAYER_XY[1] - 40, 0.1, "enemy")
    m = Mem(exact_enabled=False, last_lane_walk_t=100.0)
    decide(_state(enemies=[low], t=100.0), m)
    assert m.clicks["attack"] == 1


# --- exact layer: left-click select + exact health from the target frame ----------------------------------------------------------


def test_exact_layer_selects_with_a_left_click_and_does_not_attack() -> None:
    soon = _m(100, 0.4)
    m = Mem()
    acts = decide(_lh_state([soon], t=100.0), m)
    sel = [a for a in acts if a[0] == "select"]
    assert sel and sel[0][1:] == soon.body and not [a for a in acts if a[0] == "right"] and m.sel is not None


def _selected(m: Mem, bar: Bar, cur: int, mx: int, t: float, s_kwargs=None):
    s = _lh_state([bar], t=t, ad=100.0, target_hp=(cur, mx), **(s_kwargs or {}))
    return decide(s, m)


def test_exact_layer_attacks_when_the_exact_health_is_within_our_damage() -> None:
    bar = _m(100, 0.2)  # 100 / 500
    m = Mem(last_lane_walk_t=100.0)
    decide(_lh_state([bar], t=99.0, ad=100.0), m)  # selects it
    acts = _selected(m, bar, 95, 500, 100.0)
    assert [a for a in acts if a[0] == "right"] and m.lasthits and m.lasthits[0]["hp_exact"] == 95 and m.lasthits[0]["hp_max"] == 500
    assert m.lasthits[0]["predicted_dmg"] == 100.0


def test_exact_layer_waits_without_clicking_when_the_minion_is_not_yet_killable() -> None:
    bar = _m(100, 0.5)  # 250 / 500: far from one auto of 100
    m = Mem(last_lane_walk_t=100.0, last_action_t=99.9)
    decide(_lh_state([bar], t=99.0, ad=100.0), m)
    acts = _selected(m, bar, 250, 500, 100.0)
    assert acts == [] or not [a for a in acts if a[0] in ("right", "move")]  # standing still is correct


def test_exact_layer_logs_predicted_against_measured_damage_and_alerts_on_a_mismatch() -> None:
    bar = _m(100, 0.2)
    m = Mem(last_lane_walk_t=100.0)
    decide(_lh_state([bar], t=99.0, ad=100.0), m)
    _selected(m, bar, 95, 500, 100.0)  # the attack at t 100
    _selected(m, bar, 95, 500, 100.4)
    _selected(m, bar, 95, 500, 100.9)
    low = _m(100, 0.12)
    _selected(m, low, 60, 500, 101.4)  # health fell 35 only: our hit did 35, we predicted 100
    h = m.lasthits[0]
    assert h["measured_dmg"] == 35.0
    assert m.events[-1]["kind"] == "dmg_check"


def test_exact_layer_falls_back_to_estimates_when_the_target_frame_is_unreadable() -> None:
    bar = _m(100, 0.4)
    m = Mem()
    decide(_lh_state([bar], t=100.0), m)
    assert m.sel is not None
    decide(_lh_state([bar], t=101.7), m)  # still unread after 1.5 s
    assert m.sel is None and m.exact_off_until > 101.7


def test_exact_layer_does_not_bet_on_allied_damage_to_make_the_kill() -> None:
    bar = _m(100, 0.2)  # 104 / 500 while our hit does 100: the auto alone cannot kill it
    m = Mem(last_lane_walk_t=100.0, last_action_t=99.9)
    decide(_lh_state([bar], t=99.0, ad=100.0), m)
    _selected(m, _m(100, 0.26), 130, 500, 99.6)
    acts = _selected(m, bar, 104, 500, 100.0)  # allies are taking about 40 hp/s: predicted 85 <= 100, but the exact health is 104 > 100
    assert not [a for a in acts if a[0] == "right"]


def test_exact_layer_takes_a_set_up_hit_only_when_it_cannot_kill_by_mistake() -> None:
    bar = _m(100, 0.44)  # 220 / 500 with our hit 100: after the hit 120 > 1.1 x 100
    m = Mem(last_lane_walk_t=100.0, last_action_t=99.9)
    decide(_lh_state([bar], t=99.0, ad=100.0), m)
    acts = _selected(m, bar, 220, 500, 100.0)
    assert [a for a in acts if a[0] == "right"] and m.clicks.get("setup") == 1 and not m.lasthits  # a set-up hit is not a last-hit attempt
    again = _selected(m, bar, 220, 500, 100.2)  # the attack timer is still running
    assert not [a for a in again if a[0] == "right"]


def test_minion_type_comes_from_the_exact_max_health() -> None:
    from shared.src.lib.game.leagueoflegends.garen_bot import type_from_max_hp
    assert [type_from_max_hp(v) for v in (284, 302, 465, 500, 570, 835, 900)] == ["caster", "caster", "melee", "melee", "melee", "cannon", "cannon"]
    bar = _m(100, 0.2)
    m = Mem(last_lane_walk_t=100.0)
    decide(_lh_state([bar], t=99.0, ad=100.0), m)
    _selected(m, bar, 95, 500, 100.0)
    assert m.lasthits[0]["type"] == "melee"


def test_steps_away_from_an_enemy_crowd_while_health_is_falling() -> None:
    crowd = [_m(60, 0.9, dy=-20), _m(120, 0.9, dy=-10), _m(90, 0.9, dy=0)]  # three healthy enemy minions on Garen's right
    m = Mem(last_lane_walk_t=100.0)
    decide(_state(t=99.0, hp=1000.0, enemies=crowd), m)
    acts = decide(_state(t=100.0, hp=950.0, enemies=crowd), m)  # lost 5 % in a second inside the crowd
    mv = [a for a in acts if a[0] == "move"]
    assert mv and mv[0][1] < PLAYER_XY[0] and m.events[-1]["kind"] == "backstep"  # away from them (they are on his right)
    calm = Mem(last_lane_walk_t=100.0)
    assert not [a for a in decide(_state(t=100.0, hp=1000.0, enemies=crowd), calm) if a[0] == "move" and a[1] < PLAYER_XY[0] - 100]


def test_exact_layer_follows_the_selected_bar_by_its_health_when_bars_swap_places() -> None:
    a, b = _m(100, 0.2), _m(140, 0.5)  # two close minions
    m = Mem(last_lane_walk_t=100.0)
    decide(_lh_state([a, b], t=99.0, ad=100.0), m)  # selects the weaker one at a.x
    # next tick the bars have drifted and swapped places; the target frame says 95 / 500 = 19 %, i.e. the 0.2 bar
    a2, b2 = _m(135, 0.2), _m(95, 0.5)
    s = _lh_state([a2, b2], t=99.4, ad=100.0, target_hp=(95, 500))
    decide(s, m)
    assert m.sel is not None and abs(m.sel["x"] - a2.x) < 1 and abs(m.sel["frac"] - 0.2) < 0.01


def test_exact_layer_uses_q_first_when_only_the_empowered_auto_can_kill() -> None:
    bar = _m(100, 0.2)  # 130 / 500: our auto does 100, Q adds 30 + 50 = 80 (formula 180); the bot bets on 60 % of the Q bonus: 148
    m = Mem(last_lane_walk_t=100.0, last_action_t=99.9)
    decide(_lh_state([bar], t=99.0, ad=100.0, level=3), m)
    acts = _selected(m, bar, 130, 500, 100.0, {"level": 3})
    keys = [a for a in acts if a[0] in ("key", "right")]
    assert keys[0] == ("key", "Q") and keys[1][0] == "right" and m.lasthits[0]["action"] == "q" and m.lasthits[0]["predicted_dmg"] == 180.0
    # Q on cooldown: the plain auto cannot kill 130 hp with 100 damage: no attack
    cd = Mem(last_lane_walk_t=100.0, last_action_t=99.9, last_q_t=99.0)
    decide(_lh_state([bar], t=99.0, ad=100.0, level=3), cd)
    assert not [a for a in _selected(cd, bar, 130, 500, 100.0, {"level": 3}) if a[0] == "right"]


def test_q_uses_are_counted_by_minion_type() -> None:
    bar = _m(100, 0.2)
    m = Mem(last_lane_walk_t=100.0, last_action_t=99.9)
    decide(_lh_state([bar], t=99.0, ad=100.0, level=3), m)
    _selected(m, bar, 130, 500, 100.0, {"level": 3})
    assert m.sel_stats.get("q_melee") == 1 and m.sel_stats.get("q") == 1


def test_free_camera_recentres_with_space_after_a_move_and_never_with_b() -> None:
    gi = GameInput(_guard_ok(), dry_run=True)
    t = {"now": 0.0}
    data = {"activePlayer": {"riotId": "me#1", "championStats": {"currentHealth": 1000, "maxHealth": 1000}, "currentGold": 0, "level": 3},
            "allPlayers": [{"riotId": "me#1", "items": [], "isDead": False}], "gameData": {"gameTime": 200.0}}
    bot = GarenBot(gi, fetch=lambda: data, screenshot=lambda: _frame(), sleep=lambda s: t.__setitem__("now", t["now"] + s),
                   clock=lambda: t["now"], camera_mode="free")
    bot.execute(("move", 900, 500), 3)
    bot.step()
    keys = [a[1] for a in gi.log if a[0] == "key"]
    assert "SPACE" in keys and "B" not in keys
    t["now"] += 5.0
    gi.log.clear()
    bot.step()  # standing still, no recent move: no recentre tap
    assert "SPACE" not in [a[1] for a in gi.log if a[0] == "key"]


def test_recalls_at_800_gold_when_no_enemy_minion_is_close() -> None:
    far = Bar("minion", PLAYER_XY[0] + 900, PLAYER_XY[1], 1.0, "enemy")  # on screen, but far away
    m = Mem()
    assert ("recall",) in decide(_state(gold=850.0, enemies=[far]), m)
    near = Bar("minion", PLAYER_XY[0] + 200, PLAYER_XY[1], 1.0, "enemy")
    assert ("recall",) not in decide(_state(gold=850.0, enemies=[near]), Mem())


def test_farm_hit_attacks_the_lowest_minion_in_range_when_the_attack_is_ready() -> None:
    wave = [_m(60, 0.9), _m(100, 0.6), _m(140, 0.8)]  # all healthy: nothing to last-hit
    m = Mem(exact_enabled=False, last_lane_walk_t=100.0, last_attack_t=90.0)
    acts = decide(_lh_state(wave, t=100.0, ad=60.0), m)
    hit = [a for a in acts if a[0] == "right"]
    assert hit and hit[0][1:] == wave[1].body  # the lowest-health one
    again = decide(_lh_state(wave, t=100.2, ad=60.0), m)  # attack timer running: no second click
    assert not [a for a in again if a[0] == "right"]


def test_exact_layer_steps_into_range_when_the_selected_minion_is_about_to_become_killable() -> None:
    far = _m(280, 0.3)  # 150 / 500, 280 px away (out of the 210 px attack range)
    m = Mem(last_lane_walk_t=90.0, last_action_t=99.9, last_attack_t=99.0)
    decide(_lh_state([far], t=99.0, ad=100.0), m)
    acts = _selected(m, far, 150, 500, 100.0)
    mv = [a for a in acts if a[0] == "move"]
    assert mv and mv[0][1] > PLAYER_XY[0] and m.sel_stats.get("step_in") == 1


def test_farm_hit_avoids_leaving_a_minion_at_an_awkward_health() -> None:
    awkward = _m(60, 0.30)  # about 150 hp: after a 100-damage hit 50 would be left... use AD 80: 150 - 80 = 70 -> fine; make it awkward below
    m = Mem(exact_enabled=False, last_lane_walk_t=100.0, last_attack_t=90.0)
    # AD 80, minion 0.40 x 505 = 202 hp: left 122 hp = between 1 and 2 autos (80..160): awkward, so no farm-hit on it
    bad = _m(60, 0.40)
    acts = decide(_lh_state([bad], t=100.0, ad=80.0), m)
    assert not [a for a in acts if a[0] == "right"]
    # a healthy one (0.9 x 505 = 455 hp): left 375 hp > 2 autos: fine to hit
    ok = _m(60, 0.9)
    m2 = Mem(exact_enabled=False, last_lane_walk_t=100.0, last_attack_t=90.0)
    assert [a for a in decide(_lh_state([ok], t=100.0, ad=80.0), m2) if a[0] == "right"]


@pytest.mark.simple_loop
def test_simple_loop_attacks_what_one_auto_kills_and_pokes_the_weakest_otherwise():
    m = Mem()
    acts = decide(_lh_state([_m(100, 0.10), _m(200, 0.9)], t=100.0, ad=140.0), m)
    assert ("right", *_m(100, 0.10).body) in acts  # 0.10 of a ~480 hp minion dies to one auto
    m2 = Mem()
    acts = decide(_lh_state([_m(100, 0.9)], t=100.0, ad=140.0), m2)
    assert not [a for a in acts if a[0] == "right"]  # v2t: a healthy minion is not poked


def test_slow_drain_with_enemy_minions_near_retreats_behind_our_wave():
    m = Mem()
    for i, hp in enumerate((1000, 960, 920, 880)):  # 12 % of 1000 max within 10 s, no single 2 s drop big enough for the backstep
        acts = decide(_lh_state([_m(100, 0.9)], t=100.0 + 3.0 * i, ad=140.0, hp=float(hp), max_hp=1000.0), m)
    assert any(a[0] == "move" for a in acts) and not any(a[0] == "minimap" for a in acts)
    assert not [a for a in acts if a[0] == "right"]


def _mk(dx, dy, frac, mark):
    return Bar("minion", PLAYER_XY[0] + dx, PLAYER_XY[1] - 40 + dy, frac, "enemy", None, mark)


@pytest.mark.marker_loop
def test_marker_loop_attacks_when_no_pink_is_left_and_pokes_each_minion_once():
    m = Mem()
    acts = decide(_lh_state([_mk(100, 0, 0.16, 0.16), _mk(150, 0, 0.9, 0.17)], t=100.0, ad=81.0), m)
    assert [a for a in acts if a[0] == "right"][0][1:] == _mk(100, 0, 0.16, 0.16).body  # only the dark segment is left: one auto kills it
    assert m.lasthits and m.lasthits[-1]["action"] == "auto"
    m2 = Mem()
    first = decide(_lh_state([_mk(150, 0, 0.9, 0.17)], t=100.0, ad=81.0), m2)
    assert [a for a in first if a[0] == "right"] and len(m2.pokes) == 1  # a healthy minion gets its one set-up auto ...
    again = decide(_lh_state([_mk(150, 0, 0.9, 0.17)], t=102.0, ad=81.0), m2)
    assert len(m2.pokes) == 1  # ... and no second one


def test_find_bars_reads_the_kill_marker_segment():
    img = np.zeros((1200, 1920, 3), dtype=np.uint8)
    y, x0 = 500, 800
    img[y - 1:y + 5, x0 - 1:x0 + 63] = (8, 4, 0)  # near-black frame
    img[y:y + 4, x0:x0 + 11] = (124, 28, 3)  # the dark segment: 11 px of 62 (one auto of a melee minion)
    img[y:y + 4, x0 + 11:x0 + 62] = (190, 93, 90)  # pink health beyond it
    bars = find_bars(img)
    assert len(bars) == 1 and abs(bars[0].kill_mark - 11 / 62) < 0.03 and bars[0].frac > 0.95


@pytest.mark.marker_loop
def test_predictor_decides_and_the_marker_only_scores_it(monkeypatch) -> None:
    # frac 0.40 of a ~480 hp melee = 190 hp: our predictor waits; the marker (0.16) says 0.24 of pink is left: it waits too
    m = Mem()
    acts = decide(_lh_state([_mk(100, 0, 0.40, 0.16)], t=100.0, ad=81.0), m)
    assert m.sel_stats.get("agree_wait") == 1 and not m.lasthits
    # a caster (marker 0.29) at 0.30: the marker says kill (pink 0.01); a melee-based predictor says 0.30*480 = 144 hp > 85: false late
    m2 = Mem()
    decide(_lh_state([_mk(100, 0, 0.30, 0.29)], t=100.0, ad=81.0), m2)
    assert m2.sel_stats.get("false_late") == 1 and not m2.lasthits
    # the training reference mode follows the marker
    monkeypatch.setattr("shared.src.lib.game.leagueoflegends.garen_bot.LASTHIT_SOURCE", "marker")
    m3 = Mem()
    decide(_lh_state([_mk(100, 0, 0.30, 0.29)], t=100.0, ad=81.0), m3)
    assert m3.lasthits and m3.lasthits[-1]["source"] == "marker"


def test_stale_recorder_match_never_touches_the_stream_ffmpeg() -> None:
    from shared.src.lib.game.leagueoflegends.recorder_proc import is_stale_run_recorder, stop_recorder

    run = [r"C:\ffmpeg\bin\ffmpeg.exe", "-y", "-f", "gdigrab", "-i", "desktop", r"C:\virtualpytest\garen-run-20261018-191400\video.mp4"]
    assert is_stale_run_recorder(run)
    assert is_stale_run_recorder(run[:-1] + [r"C:\virtualpytest\bench-run-x\video.mp4"])
    assert not is_stale_run_recorder(["ffmpeg.exe", "-f", "dshow", "-i", "video=cap", r"C:\virtualpytest\stream\out.m3u8"])
    assert not is_stale_run_recorder(["ffmpeg.exe", "-f", "gdigrab", "-i", "desktop", r"C:\virtualpytest\stream\desk.mp4"])

    class _P:
        stdin = None

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    p = _P()
    assert stop_recorder(p, 0.1, lambda m: None) == "killed" and p.killed  # no stdin: killed, never left running
    assert stop_recorder(None) == "not running"


@pytest.mark.parametrize("width", [3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
def test_find_bars_sees_a_sliver_of_the_dark_kill_segment(width) -> None:
    """A minion one auto from dying shows only a few px of the dark segment: it must still be a bar (the lowest minions were ignored)."""
    img = np.zeros((1200, 1920, 3), dtype=np.uint8)
    y, x0 = 500, 800
    img[y - 1:y + 5, x0 - 1:x0 + 63] = (8, 4, 0)  # the bar's near-black frame
    img[y:y + 4, x0:x0 + width] = (124, 28, 3)
    bars = find_bars(img)
    assert len(bars) == 1 and bars[0].kind == "minion" and abs(bars[0].frac - width / 62) < 0.03 and bars[0].kill_mark >= bars[0].frac - 0.03


def test_find_bars_ignores_the_red_outline_of_the_targeted_minion() -> None:
    """The selected minion is outlined in thin red on grass, with no near-black frame: not a sliver of the dark kill segment."""
    img = np.zeros((1200, 1920, 3), dtype=np.uint8)
    img[...] = (50, 70, 30)  # grass
    img[600:604, 900:905] = (124, 28, 3)  # a 5 px red stroke of the outline
    assert find_bars(img) == []


def test_id_tracker_keeps_identities_and_rejects_a_fuller_neighbour() -> None:
    from shared.src.lib.game.leagueoflegends.minion_track import IdTracker

    tr = IdTracker()
    a = tr.update(0.0, [_mk(100, 0, 0.60, 0.17), _mk(160, 0, 0.90, 0.29)])
    assert [t.id for t in a] == [1, 2]
    # next frame: both moved a little, the first lost health; a fuller bar next to it must not be taken for it
    b = tr.update(0.2, [_mk(104, 0, 0.55, 0.17), _mk(150, 0, 0.90, 0.29)])
    assert sorted(t.id for t in b) == [1, 2]
    # a minion that vanishes and a new one far away: new id after keep_s
    c = tr.update(1.5, [_mk(-200, 0, 1.0, 0.17)])
    assert [t.id for t in c] == [3] and tr.tracks[0].ended


def test_find_bars_ignores_chat_text_in_the_bottom_left() -> None:
    """Red bot names in the game chat ("Urgot Bot has slain ...") sit on a dark panel and passed as bars; the chat rectangle is excluded."""
    img = np.zeros((1200, 1920, 3), dtype=np.uint8)
    img[500:800, 130:520] = (20, 25, 35)  # dark chat panel
    for y in (520, 560, 600):
        img[y - 1:y + 5, 150:420] = (8, 4, 0)
        img[y:y + 4, 150:215] = (190, 93, 90)  # a red text run 65 px wide with a dark frame above and below
    assert find_bars(img) == []
    img2 = np.zeros((1200, 1920, 3), dtype=np.uint8)
    img2[539:545, 949:1011] = (8, 4, 0)
    img2[540:544, 950:1010] = (190, 93, 90)
    assert len(find_bars(img2)) == 1  # the same bar in the lane is still a bar


def test_find_bars_ignores_hud_digits_at_the_right_screen_edge() -> None:
    """Red respawn digits over the team portraits (right edge) were read as bars; that strip is excluded."""
    img = np.zeros((1200, 1920, 3), dtype=np.uint8)
    img[598:604, 1898:1919] = (8, 4, 0)
    img[600:603, 1900:1919] = (190, 93, 90)
    img[699:705, 1850:1919] = (8, 4, 0)
    img[700:704, 1851:1918] = (190, 93, 90)
    assert find_bars(img) == []
