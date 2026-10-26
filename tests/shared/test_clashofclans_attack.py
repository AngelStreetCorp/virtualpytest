"""Tests for the CoC attack harness (TASK-100): pixel screen checks, plan validation, the fight loop
and the play() hook. No phone, no API: synthetic 1170x540 screens, a fake device and a fake model."""

import base64
import io

import pytest
from PIL import Image, ImageDraw

from shared.src.lib.game.clashofclans import attack as at
from shared.src.lib.game.clashofclans import llm_player as lp


def _img(color=(120, 160, 60), boxes=()):
    im = Image.new("RGB", (lp.W_IMG, lp.H_IMG), color)
    d = ImageDraw.Draw(im)
    for box, col in boxes:
        d.rectangle(box, fill=col)
    return im


def _b64(im):
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode()


def _dev(x, y):
    d = lp.to_device({"x": x, "y": y})
    return (d["x"], d["y"])


RED = (200, 30, 30)
GREEN = (90, 220, 60)
ORANGE = (240, 150, 40)
DARK_PANEL = (55, 55, 55)
BATTLE = _img(boxes=[(at.SURRENDER_BOX, RED), (at.OVERALL_DAMAGE_BOX, DARK_PANEL)])
SCOUTING = _img(boxes=[(at.SURRENDER_BOX, RED)])          # battle not started yet: no Overall Damage panel
SCOUTING_NEXT = _img(boxes=[(at.SURRENDER_BOX, RED), (at.NEXT_BOX, ORANGE)])
RESULT = _img(boxes=[(at.RESULT_BOX, GREEN)])
PLAIN = _img()


def test_battle_and_result_detection():
    assert at.is_battle_screen(BATTLE)
    assert not at.is_battle_screen(PLAIN)
    assert not at.is_battle_screen(RESULT)
    assert at.is_result_screen(RESULT)
    assert not at.is_result_screen(PLAIN)
    assert not at.is_result_screen(BATTLE)


def test_battle_started_is_only_true_when_the_damage_panel_is_up():
    """The scouting screen ("Battle starts in: 29s") must not look like a running battle: a tap there
    deploys nothing (run 33caf775)."""
    assert at.is_battle_started(BATTLE)
    assert not at.is_battle_started(SCOUTING)
    assert not at.is_battle_started(PLAIN)
    assert not at.is_battle_started(RESULT)


def test_validate_point_accepts_grass_and_rejects_bad_points():
    assert at.validate_point((330, 340)) is None
    assert "deploy band" in at.validate_point((500, 415))     # clump reaches the troop tray
    assert "deploy band" in at.validate_point((130, 380))     # next to the Surrender box
    assert "deploy band" in at.validate_point((600, 90))      # clump reaches the top HUD strip
    assert "deploy band" in at.validate_point((930, 340))     # clump reaches the damage panel
    assert "too far" in at.validate_point((300, 160))         # far-left of run 1db8e986 (lost)


def test_clump_stays_within_20_px_of_the_point():
    pts = at.clump_points((400, 300), 40)
    assert len(pts) == 40 and pts[0] == (400, 300)
    assert all(((x - 400) ** 2 + (y - 300) ** 2) ** 0.5 <= at.CLUMP_R for x, y in pts)


def test_next_button_detection():
    ORANGE = (240, 150, 40)
    assert at.is_next_visible(_img(boxes=[(at.NEXT_BOX, ORANGE)]))
    assert not at.is_next_visible(PLAIN)


class FakeMeter:
    def __init__(self):
        self.added = []
        self.failures = 0

    def can_afford_next(self):
        return True

    def add(self, tin, tout):
        self.added.append((tin, tout))
        return 0.001

    def charge_failure(self):
        self.failures += 1
        return 0.002


class FakeDev:
    """Serves ``frames`` one by one (then the result screen). Without frames it serves the running
    battle until ``result_after_polls`` screenshots have been taken, then the result screen.

    The fake game: a tap on a troop card arms it, a tap on open grass drops a troop and the count
    badge of the armed card follows - that badge is the signal the deploy check reads. A tap on a
    roof is refused, and so is a tap on a ground the game does not want (``refuse_box``): the game
    takes the tap, says nothing and no troop ever comes out (``refuse=True`` refuses every tap)."""

    def __init__(self, result_after_polls=1, frames=None, refuse=False, refuse_box=None, roof_box=None,
                 troop_offset=0, count=80):
        self.taps = []
        self.shots = 0
        self.result_after_polls = result_after_polls
        self.frames = list(frames) if frames is not None else None
        self.refuse = refuse
        self.refuse_box = refuse_box        # a patch of ground the game refuses (model coordinates)
        self.roof_box = roof_box            # a building on the field (model coordinates)
        self.troop_offset = troop_offset    # the troops appear this far from the tap: the picture misses them
        self.deployed = []
        self.cards = [count, 16, 1]         # the troops still on each card
        self.armed = None                   # the card that is armed

    def shot(self, index):
        self.shots += 1
        if self.frames is not None:
            im = self.frames[self.shots - 1] if self.shots <= len(self.frames) else RESULT
        else:
            im = RESULT if self.shots > self.result_after_polls else BATTLE
        return _b64(self._with_troops(im)), f"/tmp/fake_{index}.jpg"

    def _with_troops(self, im):
        """The count badge of each army card follows the number of troops left on it."""
        im = im.copy()
        d = ImageDraw.Draw(im)
        for x, y in self.deployed:
            d.rectangle([x - 5, y - 5, x + 5, y + 5], fill=(230, 60, 40))
        if self.roof_box:
            d.rectangle(self.roof_box, fill=(96, 85, 82))
        for k, box in enumerate(at.COUNT_BOXES):
            x0, y0, x1, y1 = box
            w = 4 + (self.cards[k] % 7) * 4
            d.rectangle([x0 + 2, y0 + 2, x0 + 2 + w, y1 - 2], fill=(250, 250, 250))
        return im

    def tap(self, x, y):
        self.taps.append((x, y))
        mx, my = x // 2, y // 2
        for k, (cx, cy) in enumerate(at.CARD_TAPS):      # a tap on a card arms it
            if abs(mx - cx) <= 25 and abs(my - cy) <= 30:
                self.armed = k
                return
        if self.armed is None or self.refuse:
            return
        if self.refuse_box:
            x0, y0, x1, y1 = self.refuse_box
            if x0 <= mx <= x1 and y0 <= my <= y1:
                return
        if self.roof_box:                       # a tap on a building drops no troop
            x0, y0, x1, y1 = self.roof_box
            if x0 <= mx <= x1 and y0 <= my <= y1:
                return
        if my >= at.TRAY_Y:                    # the tray only selects cards
            return
        if my <= at.HUD_TOP_Y:
            return
        if any(at._in_box(mx, my, b) for b in at.HUD_BOXES):
            return
        self.deployed.append((mx + self.troop_offset, my + self.troop_offset))
        self.cards[self.armed] -= 1

    def swipe(self, *a, **k):
        raise AssertionError("the harness must not swipe")


def _counts(c):
    return '{"counts": %s}' % (c if isinstance(c, list) else [c])


def _ask_factory(plan_reply, counts):
    counts = list(counts)
    plans = list(plan_reply) if isinstance(plan_reply, list) else None

    def ask(system, b64, text):
        if system.startswith("You plan"):
            return (plans.pop(0) if plans is not None else plan_reply), 100, 20
        if system.startswith("Read the troop counts"):
            return _counts(counts.pop(0)), 100, 10
        if system.startswith("This is the end-of-battle"):
            return '{"outcome": "victory", "damage_pct": 55, "stars": 1}', 100, 10
        raise AssertionError("unexpected prompt")
    return ask


SLEEP = lambda _s: None   # noqa: E731


def test_the_count_badge_sees_the_number_move_and_ignores_an_unchanged_card():
    """The deploy signal is the number on the army card: a troop that left the tray changes it.

    Measured on the real frames of run 33caf775 (2026-10-20): the card went x11 -> x10 -> x9 while
    the troops came out, 162 to 556 pixels of the badge moved, and a card that deploys nothing keeps
    its badge pixel-identical. The battlefield around the plan point cannot be used: the fight moves
    all the time, so it "changes" on every tap - that false positive sent 79 taps into a refused
    point on run 218ca432 (0 % damage)."""
    x0, y0, _, y1 = at.COUNT_BOXES[0]
    badge = _img(boxes=[((x0, y0, x0 + 24, y1), (250, 250, 250))])       # "x59"
    assert not at.count_changed(badge, badge)                          # nothing happened
    fewer = _img(boxes=[((x0, y0, x0 + 16, y1), (250, 250, 250))])      # "x55": the number moved
    assert at.count_changed(badge, fewer)
    assert not at.count_changed(badge, badge)                          # the badge of another card


def test_the_ground_check_sees_grass_and_refuses_a_roof():
    """A troop only comes out on open grass: the game refuses a tap on a roof, a wall or a path
    without saying anything. Run 218ca432 (2026-10-20) planned (700, 370), the roof of the dark
    elixir storage, and sent 79 taps there: 0 % damage, the count stayed at x59."""
    grass = _img()
    roof = _img(boxes=[((300, 300, 400, 400), (96, 85, 82))])
    assert at.is_grass(grass, 330, 340)
    assert not at.is_grass(roof, 330, 340)
    assert at.is_grass(roof, 250, 250)                     # the grass next to the roof
    spot = at.grass_spot(roof, 330, 340)                  # the point moves to the open grass
    assert spot is not None and spot != (330, 340)
    assert at.is_grass(roof, *spot)


def test_a_point_without_any_grass_around_it_is_not_used():
    walls = _img(boxes=[((0, 0, 1170, 540), (96, 85, 82))])
    assert at.grass_spot(walls, 330, 340) is None


def test_a_plan_on_a_roof_is_moved_to_the_open_grass():
    """The model points at the roof of a building: the game drops no troop there. Run 218ca432
    (2026-10-20) planned (700, 370), the roof of the dark elixir storage, and sent 79 taps there:
    0 % damage, the count badge stayed at x59 for the whole battle."""
    roof = _img(boxes=[((300, 300, 400, 400), (96, 85, 82))])
    dev = FakeDev(frames=[roof] * 40, roof_box=(300, 300, 400, 400))
    ask = _ask_factory('{"point": [330, 340]}', counts=[[6, 0], [0, 0]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(roof), 4, sleep=SLEEP)

    assert res.status == "deployed"
    assert res.plan["point"] != [330, 340], "the plan still points at the roof"
    assert at.is_grass(roof, *res.plan["point"])
    assert dev.deployed, "no troop appeared on the field"


def test_a_plan_without_any_grass_is_asked_again():
    """No grass anywhere near the point: the model is asked for another one, the harness does not
    spend the army on a building."""
    walls = _img(boxes=[((0, 0, 1170, 540), (96, 85, 82))])
    dev = FakeDev(frames=[walls] * 40)
    replies = iter(['{"point": [330, 340]}', '{"point": [330, 340]}'])
    seen = []

    def ask(system, b64, text):
        seen.append(text)
        if system.startswith("You plan"):
            return next(replies), 100, 20
        if system.startswith("Read the troop counts"):
            return '{"counts": [6, 0]}', 100, 10
        return '{"outcome": "victory", "damage_pct": 55, "stars": 1}', 100, 10

    res = at.run_attack(dev, ask, FakeMeter(), _b64(walls), 4, sleep=SLEEP)

    assert res.status == "no_valid_plan"
    assert not dev.deployed, "the harness dropped troops on a building"
    assert any("not on open grass" in t for t in seen), "the model was not told why"


def test_a_card_without_a_count_does_not_block_the_wave():
    """The King card and the spells carry no number: there is nothing to read, so the harness must
    not wait for a badge that can never move. The same holds when the card in the FIRST slot has
    no number drawn: an empty badge compared with an empty badge always read as "nothing moved",
    so every deploy was reported as refused and the army never came out."""
    badge = _img()
    assert at.count_changed(badge, badge, 0) is True      # no number on the card: no signal, no block
    assert at.count_changed(badge, badge, 2) is True


def test_the_deploy_check_waits_for_the_card_to_settle():
    """Arming a card lifts it a pixel or two and dims the other card, so the badge moves for 0.4 s
    (measured at 10 fps on the winning battle of run bcaa97d8: 80 to 366 pixels of the badge move
    when a card is armed, as much as a real count change). The picture that opens the comparison
    must therefore be taken after the card has settled, or the arming would read as a count change.
    """
    events = []
    dev = FakeDev(result_after_polls=3)
    shot, tap = dev.shot, dev.tap
    dev.shot = lambda index: (events.append("shot"), shot(index))[1]
    dev.tap = lambda x, y: (events.append("tap"), tap(x, y))[1]

    def sleep(s):
        events.append(("sleep", s))

    ask = _ask_factory('{"point": [330, 340]}', counts=[[6, 0], [0, 0]])
    at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=sleep)

    i = events.index("tap")                       # the card tap
    assert events[i + 1] == ("sleep", at.CARD_SETTLE_S), "the card is not given time to settle"
    assert events[i + 2] == "shot", "the picture is taken before the card has settled"
    assert at.CARD_SETTLE_S >= 1.0, "the settle is shorter than the 0.4 s arming animation"


def test_the_deploy_check_costs_no_model_call():
    """The picture is the signal, so a refused deploy is noticed without asking the model."""
    dev = FakeDev(frames=[BATTLE] * 40, refuse=True)
    ask = _ask_factory('{"point": [330, 340]}', counts=[[59, 11, 1], [59, 11, 1], [59, 11, 1]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)
    # plan + counts before + counts after each attempt + result: no extra call for the check
    assert res.haiku_calls <= 2 + 2 * at.MAX_DEPLOY_ATTEMPTS + 1


def test_run_attack_drops_every_troop_in_one_clump_until_troops_gone():
    dev = FakeDev(result_after_polls=3)
    ask = _ask_factory('{"point": [330, 340], "reason": "town hall side"}', counts=[6, 0])
    meter = FakeMeter()
    res = at.run_attack(dev, ask, meter, _b64(BATTLE), 7, sleep=SLEEP)

    assert res.status == "deployed"
    assert res.passes == 1 and res.taps == 6
    assert res.troops_left == 0
    assert res.result_seen
    assert res.haiku_calls == 4                              # plan + counts before + counts after + result
    assert res.cost == pytest.approx(0.004)
    assert len(meter.added) == 4
    assert (res.outcome, res.damage_pct, res.stars) == ("victory", 55, 1)

    assert dev.taps[0] == _dev(*at.CARD_TAPS[0])             # card selected first
    assert dev.taps[1:7] == [_dev(x, y) for x, y in at.clump_points((330, 340), 6)]
    assert dev.taps[-1] == _dev(*at.RESULT_TAP)              # then Return Home


def test_the_troop_counts_are_read_on_the_clear_scouting_frame():
    """The tray of the battle screen is busy and the model reads it wrong (run 33caf775: 59 read as
    59, then 59 again where the card said 21), so the counts are read once, on the scouting frame."""
    seen = []
    seen_count = [0]

    def ask(system, image_b64, text):
        seen.append((system[:12], image_b64))
        if system.startswith("You plan"):
            return '{"point": [330, 340]}', 100, 20
        if system.startswith("Read the troop counts"):
            reply = '{"counts": [59, 11, 1]}' if seen_count[0] == 0 else '{"counts": [0, 0, 0]}'
            seen_count[0] += 1
            return reply, 100, 10
        return '{"outcome": "victory", "damage_pct": 29, "stars": 1}', 100, 10

    dev = FakeDev(frames=[SCOUTING, BATTLE, BATTLE, BATTLE, BATTLE, BATTLE])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(SCOUTING), 3, sleep=SLEEP)
    counts_call = [img for system, img in seen if system.startswith("Read the")]
    assert counts_call and counts_call[0] == _b64(SCOUTING)
    assert res.taps == 71


def test_a_deploy_that_puts_no_troop_on_the_field_is_retried_with_another_point():
    """The live run of 2026-10-20 deployed nothing: the game refused every tap at the point the
    model picked. The harness must see that the field did not change and try the next point."""
    dev = FakeDev(frames=[BATTLE] * 40, refuse_box=(300, 330, 360, 350))   # the plan point is refused
    ask = _ask_factory('{"point": [330, 340]}', counts=[[6, 0], [0, 0]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)

    assert res.status == "deployed"
    assert any("the game refused the point" in n for n in res.notes)
    assert dev.deployed, "no troop appeared on the field"
    assert all(not (300 <= p[0] <= 360 and 330 <= p[1] <= 350) for p in dev.deployed), \
        "the troop was deployed at the refused point"


def test_a_deploy_the_picture_misses_is_still_seen_in_the_tray():
    """The picture is the first signal, the tray the second: a deploy the picture missed (a troop
    that appears away from the point) must not throw the battle away."""
    dev = FakeDev(frames=[BATTLE] * 40, troop_offset=200)
    ask = _ask_factory('{"point": [330, 340]}', counts=[[6, 0], [0, 0]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)
    assert res.status == "deployed"


def test_a_battle_where_the_game_refuses_every_point_gives_up_instead_of_tapping_140_times():
    """The live case of 2026-10-20: 140 taps in 2 passes and not one troop. The harness must not
    spend the whole army on a point the game refuses."""
    dev = FakeDev(frames=[BATTLE] * 60, refuse=True)
    ask = _ask_factory('{"point": [330, 340]}', counts=[[59, 11, 1], [59, 11, 1], [59, 11, 1]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)

    assert res.status == "no_deploy"
    assert res.taps <= at.MAX_TOTAL_TAPS
    assert res.taps < 60, "the harness spent the whole army on a point the game refuses"
    assert any("refused" in n for n in res.notes)
    assert not dev.deployed


def test_the_harness_offers_many_points_before_it_gives_the_battle_up():
    """The live case of 2026-10-20: the game refused every point the harness tried, so the battle
    was lost with 0 % damage and the whole army still in the tray. The harness must keep offering
    points - a whole neighbourhood, not five spots 50 px apart - before it gives the battle up."""
    dev = FakeDev(frames=[BATTLE] * 60, refuse=True)
    ask = _ask_factory('{"point": [330, 340]}', counts=[[59, 11, 1], [59, 11, 1], [59, 11, 1]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)

    refused = [n for n in res.notes if "the game refused the point" in n]
    assert len(refused) >= 8, f"only {len(refused)} points were tried"
    assert res.status == "no_deploy"
    assert res.taps <= at.MAX_TOTAL_TAPS
    assert not dev.deployed


def test_the_harness_does_not_ask_the_model_again_inside_a_battle():
    """The planning call took 170 to 260 s in the runs of 19:00 and 20:00 - longer than a battle
    (3 min). Asking again inside the fight lost the battle while the model thought, so the second
    try takes the next points of the list instead of a new plan."""
    plans = []

    def ask(system, b64, text):
        if system.startswith("You plan"):
            plans.append(text)
            return '{"point": [330, 340]}', 100, 20
        if system.startswith("Read the troop counts"):
            return '{"counts": [59, 11, 1]}', 100, 10
        return '{"outcome": "defeat", "damage_pct": 0, "stars": 0}', 100, 10

    dev = FakeDev(frames=[BATTLE] * 60, refuse=True)
    at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)
    assert len(plans) == 1, "the model was asked again inside the battle"


def test_the_candidates_reach_out_of_the_base():
    """A plan inside the base stays refused, so the harness must be able to offer a point that is
    not in the same corner of the base: the list has to spread over the whole neighbourhood."""
    cands = at.deploy_candidates(PLAIN, (620, 280))
    far = [p for p in cands if abs(p[0] - 620) > 100 or abs(p[1] - 280) > 100]
    assert far, "every candidate is next to the plan point"
    assert len(cands) >= 8


def test_the_roomiest_ground_is_offered_before_the_ground_between_the_buildings():
    """The game refused every point that sat between the buildings of the base and took every point
    on the open field around it (the runs of 19:00 and 20:00). The harness must offer the open
    ground first."""
    field = _img(boxes=[((250, 360, 450, 430), (96, 85, 82))])      # a building south of the plan point
    cands = at.deploy_candidates(field, (330, 330))
    assert cands[0] == (330, 330)                                   # the plan point comes first
    opens = [at.ground_openness(field, x, y) for x, y in cands[1:]]
    assert opens == sorted(opens), "the roomiest ground must come first"
    assert 0.0 in opens, "no open ground was offered"


def test_a_battle_that_never_shows_the_damage_panel_deploys_anyway():
    """Fail-safe: a mode without the panel must not turn the attack into a no-op."""
    dev = FakeDev(frames=[SCOUTING] * 40)
    ask = _ask_factory('{"point": [330, 340]}', counts=[5, 0])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(SCOUTING), 3, sleep=SLEEP)
    assert res.status == "deployed" and res.taps == 5
    assert any("deploying anyway" in n for n in res.notes)


def test_a_battle_that_ended_before_the_deploy_is_not_deployed_into():
    dev = FakeDev(frames=[RESULT])
    ask = _ask_factory('{"point": [330, 340]}', counts=[5, 0])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(SCOUTING), 3, sleep=SLEEP)
    assert res.status == "battle_ended" and res.taps == 0


def test_barbarians_clump_first_then_archers_at_the_same_point():
    dev = FakeDev(result_after_polls=3)
    ask = _ask_factory('{"point": [330, 340]}', counts=[[10, 5], [0, 0]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 2, sleep=SLEEP)
    assert res.taps == 15
    assert dev.taps[0] == _dev(*at.CARD_TAPS[0])
    assert dev.taps[11] == _dev(*at.CARD_TAPS[1])            # second card only after all 10 of the first
    clump = {_dev(x, y) for x, y in at.clump_points((330, 340), 10)}
    assert set(dev.taps[1:11]) <= clump and set(dev.taps[12:17]) <= clump


def test_deploy_waits_for_the_battle_to_start_before_the_first_tap():
    """The frame the plan is made on is the scouting screen ("Battle starts in: 29s"): a tap there
    deploys nothing, so the harness waits for the Overall Damage panel."""
    dev = FakeDev(frames=[SCOUTING, BATTLE, BATTLE, BATTLE, BATTLE, BATTLE])
    ask = _ask_factory('{"point": [330, 340]}', counts=[4, 0])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(SCOUTING), 3, sleep=SLEEP)
    assert res.status == "deployed" and res.taps == 4
    assert dev.taps[0] == _dev(*at.CARD_TAPS[0])             # the card is selected, not a ground tap
    assert dev.shots >= 2                                   # it looked again before deploying


def test_one_deploy_wave_taps_the_army_once_and_never_the_treadmill():
    """The old loop re-read the tray after every pass; the count never reached 0 (the troops were
    dying), so it tapped 208 times for a 70-troop army and the battle ended at 4 % damage."""
    dev = FakeDev(frames=[BATTLE, BATTLE, BATTLE, BATTLE])
    ask = _ask_factory('{"point": [330, 340]}', counts=[[59, 11, 1], [0, 0, 0]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)
    assert res.taps == 71                                   # 59 Barbarians + 11 Archers + 1 King
    assert res.passes == 1
    assert res.haiku_calls == 4                             # plan + counts before + counts after + result


def test_the_total_taps_of_one_battle_are_capped():
    dev = FakeDev(frames=[BATTLE, BATTLE, BATTLE, BATTLE])
    ask = _ask_factory('{"point": [330, 340]}', counts=[[200, 200], [0, 0]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)
    assert res.taps <= at.MAX_TOTAL_TAPS
    assert res.taps == at.MAX_TOTAL_TAPS


def test_the_ranged_wave_lands_after_the_tanks_walk():
    """Barbarians first as tanks, then the Archers once they are pulling the defenses."""
    slept = []
    dev = FakeDev(frames=[BATTLE, BATTLE, BATTLE, BATTLE])
    ask = _ask_factory('{"point": [330, 340]}', counts=[[10, 4], [0, 0]])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=slept.append)
    assert res.taps == 14
    assert at.WAVE_GAP_S in slept                            # the gap between the two waves
    gap_at = slept.index(at.WAVE_GAP_S)
    assert gap_at > 0


def test_bad_base_is_skipped_with_next_then_attacked():
    # shot 1: the next base has loaded (the orange Next button is back), shot 2: the battle is running
    dev = FakeDev(frames=[SCOUTING_NEXT, BATTLE, BATTLE, BATTLE, BATTLE, BATTLE])
    ask = _ask_factory(['{"point": null, "skip": true, "reason": "walled"}', '{"point": [330, 340]}'], counts=[3, 0])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(SCOUTING_NEXT), 5, sleep=SLEEP)
    assert res.skips == 1 and dev.taps[0] == _dev(*at.NEXT_TAP)
    assert res.status == "deployed" and res.taps == 3


def test_next_waits_for_the_next_base_to_load_before_it_is_planned():
    """Planning on the old frame would put the deploy point on the village that was skipped."""
    dev = FakeDev(frames=[SCOUTING, SCOUTING_NEXT, BATTLE, BATTLE, BATTLE, BATTLE, BATTLE])
    ask = _ask_factory(['{"point": null, "skip": true, "reason": "walled"}', '{"point": [330, 340]}'], counts=[2, 0])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(SCOUTING_NEXT), 5, sleep=SLEEP)
    assert res.skips == 1
    assert res.status == "deployed" and res.taps == 2
    assert res.haiku_calls == 5                                    # 2 plans + counts before + counts after + result


def test_skip_without_next_button_deploys_nothing():
    dev = FakeDev(result_after_polls=1)
    ask = _ask_factory('{"skip": true}', counts=[])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 5, sleep=SLEEP)
    assert res.skips == 0 and res.status == "no_valid_plan" and res.taps == 0


def test_invalid_plan_deploys_nothing_and_still_waits_for_the_result():
    dev = FakeDev(result_after_polls=2)
    ask = _ask_factory('{"point": [130, 380], "reason": "on the button"}', counts=[])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 3, sleep=SLEEP)

    assert res.status == "no_valid_plan"
    assert res.taps == 0                                     # no deploy tap at all
    assert all(t == _dev(*at.RESULT_TAP) for t in dev.taps)
    assert any("plan rejected" in n for n in res.notes)
    assert res.result_seen


def test_unparseable_plan_is_not_guessed():
    dev = FakeDev(result_after_polls=1)
    ask = _ask_factory("I think you should attack the left side", counts=[])
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 3, sleep=SLEEP)
    assert res.status == "no_valid_plan"
    assert all(t == _dev(*at.RESULT_TAP) for t in dev.taps)


class PlayDev(FakeDev):
    """Battle screen first, then the running battle, then the result screen, then plain home screens."""

    def __init__(self):
        super().__init__()
        self.n = 0

    def shot(self, index):
        self.n += 1
        self.shots += 1
        im = BATTLE if self.n <= 6 else (RESULT if self.n == 7 else PLAIN)
        return _b64(self._with_troops(im)), f"/tmp/play_{index}.jpg"

    def swipe(self, *a, **k):
        pass


def test_play_hands_a_battle_to_the_harness_and_reports_it_as_one_step():
    dev = PlayDev()
    steps = []
    counts = [4, 0]

    def ask(system, b64, text):
        if system.startswith("You plan"):
            return '{"point": [330, 340]}', 100, 20
        if system.startswith("Read the troop counts"):
            return _counts(counts.pop(0)), 100, 10
        return '{"thought": "home, nothing to do", "action": "idle_ok"}', 1000, 50

    out = lp.play(dev, ask, FakeMeter(), "play", 8, steps.append, sleep=SLEEP, tick=lambda: None)

    attack_steps = [s for s in steps if s["action"] == "attack"]
    assert len(attack_steps) == 1
    assert "battle deployed" in attack_steps[0]["thought"]
    assert attack_steps[0]["cost"] > 0
    assert out["stop"] == "idle"                             # the run went back to home and ended normally


def _report_steps():
    base = {"tokens_in": 0, "tokens_out": 0, "cost": 0.001, "model_s": 1.0, "reply": "", "note": "",
            "screenshot": None, "device_ok": True}
    return [
        dict(base, index=0, action="tap", thought="Home village", goal="Collect gold from the mine"),
        dict(base, index=1, action="attack", thought="battle deployed", goal="Win the battle: deploy",
             outcome={"result": "victory", "damage_pct": 55, "stars": 1, "troops_left": 0, "taps": 20, "plan": None}),
        dict(base, index=2, action="attack", thought="battle deployed", goal="Win the battle: deploy",
             outcome={"result": "defeat", "damage_pct": 0, "stars": 0, "troops_left": 10, "taps": 10, "plan": None}),
    ]


def test_report_shows_goal_per_step_and_whether_the_attack_goal_was_reached():
    from shared.src.lib.game.clashofclans import llm_report as rep
    html_out = rep.build_html({"budget": {}}, _report_steps(), "run")
    assert "Goal: Collect gold from the mine" in html_out
    assert "Attack goals (2)" in html_out
    assert "55% damage" in html_out and "goal reached" in html_out
    assert "defeat, 0% damage" in html_out and "goal not reached" in html_out


def test_report_without_attacks_has_no_goal_card():
    from shared.src.lib.game.clashofclans import llm_report as rep
    html_out = rep.build_html({"budget": {}}, _report_steps()[:1], "run")
    assert "Attack goals" not in html_out
    assert "Goal: Collect gold from the mine" in html_out


def test_rejected_line_gets_one_retry_with_the_reason():
    dev = FakeDev(result_after_polls=3)
    replies = iter(['{"point": [130, 380]}', '{"point": [400, 360]}'])   # nothing nudges this one
    seen = []
    counts = iter([_counts(4), _counts(0), '{"outcome": "defeat", "damage_pct": 0, "stars": 0}'])

    def ask(system, b64, text):
        if system.startswith("You plan"):
            seen.append(text)
            return next(replies), 100, 20
        if system.startswith("Read the troop counts"):
            return next(counts), 100, 10
        return next(counts), 100, 10
    res = at.run_attack(dev, ask, FakeMeter(), _b64(BATTLE), 4, sleep=SLEEP)
    assert res.status == "deployed" and res.taps == 4
    assert len(seen) == 2 and "rejected" in seen[1] and "130, 380" in seen[1]
    assert any("plan rejected" in n for n in res.notes)


def test_rejected_point_is_nudged_toward_the_base_instead_of_waiting_out_the_timer():
    bad = (540, 415)                                       # clump reaches the troop tray
    assert at.validate_point(bad) is not None
    moved = at.nudge_point(bad)
    assert moved is not None and at.validate_point(moved) is None
    ask = _ask_factory("unused", counts=[])

    def model(system, b64, text):
        if system.startswith("You plan"):
            return '{"point": [540, 415], "skip": false, "reason": "left"}', 100, 20
        return ask(system, b64, text)
    res = at.AttackResult(status="deployed")
    plan = at.plan_deploy(model, _b64(BATTLE), res)
    assert plan is not None and plan.point == moved
    assert res.haiku_calls == 1                            # no second question: the nudge was enough
    assert any("plan nudged" in n for n in res.notes)


def test_point_too_far_to_nudge_is_still_refused():
    assert at.nudge_point((130, 380)) is None              # next to the Surrender box, 500+ px away from the base
