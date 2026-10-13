"""
Unit tests for ``shared.src.lib.game.clashofclans.tutorial`` (§81.1.10).

TutorialDriver is a pure state machine: it accepts (text, painted) tuples,
walks the step table, and emits structured events. Tests inject fixed
text inputs (no OCR, no real screenshot) and assert the state machine
advances correctly.

Mirrors the per-game ``test_<game>_*.py`` pattern (GAME_BOTS §1).
"""

from __future__ import annotations

import unittest

from shared.src.lib.game.clashofclans import tutorial as coc_tutorial


class TestTutorialDriver(unittest.TestCase):

    def test_initial_state_is_welcome(self):
        td = coc_tutorial.TutorialDriver()
        self.assertEqual(td.step_current, "welcome")
        self.assertFalse(td.is_complete())
        self.assertFalse(td.require_manual_handoff())

    def test_step_description_for_known_step(self):
        td = coc_tutorial.TutorialDriver()
        self.assertIn("Welcome Chief", td.step_description())

    def test_observe_bubble_not_painted_holds(self):
        td = coc_tutorial.TutorialDriver()
        out = td.observe("", painted=False)
        self.assertEqual(out["event"], "step_held")
        self.assertEqual(td.step_current, "welcome")

    def test_advances_through_full_tutorial(self):
        """Walk the canonical 11-step path with the right matches and
        verify the state machine ends on ``complete`` after the runner
        advances each step on a successful action.

        The driver only transits to ``complete`` when ``advance_to_next()``
        is called from the runner (the bubble doesn't render ``complete``,
        it's terminal)."""
        td = coc_tutorial.TutorialDriver()
        script = [
            ("welcome chief! tap okay to continue", True),
            ("build your town hall here", True),
            ("place your town hall on the grass", True),
            ("build a gold mine to start collecting", True),
            ("place the gold mine on the grass", True),
            ("build a cannon to defend", True),
            ("attack a nearby goblin village to train troops", True),
            ("welcome back, chief!", True),
            ("train some troops from the barracks", True),
            ("find a clan to join for troops", True),
        ]
        for text, painted in script:
            td.observe(text, painted)
        # The runner calls advance_to_next() after each successful action,
        # so simulate that for the build steps (1..6) + after_attack +
        # train_troops. join_clan is manual so the operator drives it.
        for _ in range(8):  # welcome, build_town, place_town, build_mine, place_mine, build_cannon, after_attack, train
            td.advance_to_next()
        # After 8 advances from join_clan with .next == complete, the
        # driver has walked past join_clan and is now on complete.
        self.assertTrue(td.is_complete())
        self.assertEqual(td.step_current, "complete")
        # every key step landed in the breadcrumb
        self.assertIn("welcome", td.past_steps)
        self.assertIn("build_town_hall", td.past_steps)
        self.assertIn("place_town_hall", td.past_steps)
        self.assertIn("train_troops", td.past_steps)

    def test_attack_tutorial_is_fully_automated(self):
        """The attack_tutorial step is no longer manual. The runner
        dispatches a scripted sequence of taps via the auto_advance
        action; the bot never parks for operator input."""
        td = coc_tutorial.TutorialDriver()
        for text in ("welcome chief", "build your town hall",
                     "place your town hall", "build a gold mine",
                     "place the gold mine", "build a cannon"):
            td.observe(text, True)
            td.advance_to_next()
        td.observe("attack a nearby goblin village", True)
        self.assertFalse(td.require_manual_handoff())
        self.assertEqual(td.step_current, "attack_tutorial")
        # The action is auto_advance with a list of taps in device coords.
        self.assertEqual(td.step_action(), "auto_advance")
        params = td.step_action_params()
        self.assertIn("taps", params)
        self.assertGreaterEqual(len(params["taps"]), 3)
        for tap in params["taps"]:
            self.assertIn("x", tap)
            self.assertIn("y", tap)
            self.assertIn("wait_time", tap)

    def test_unknown_text_holds_with_step_held_unknown(self):
        """A painted bubble whose text doesn't match any known step
        stays on the current step (the runner calls this "unrecognised
        dialog")."""
        td = coc_tutorial.TutorialDriver()
        out = td.observe("this is not a coc dialog at all", painted=True)
        self.assertEqual(out["event"], "step_held_unknown")
        self.assertEqual(td.step_current, "welcome")

    def test_jump_backward_is_treated_as_held(self):
        """If OCR reports a step id earlier than the current one
        (e.g. a slow bubble landed after the next step had already
        fired), the driver treats that as a held step, not a regression."""
        td = coc_tutorial.TutorialDriver()
        td.observe("welcome chief", True)
        td.advance_to_next()
        td.observe("build your town hall", True)
        td.advance_to_next()
        # Now we're at "place_town_hall". A stale OCR reading lands
        # at "welcome" -- the driver must not regress.
        out = td.observe("welcome chief", painted=True)
        self.assertEqual(out["event"], "step_held")
        self.assertEqual(td.step_current, "place_town_hall")

    def test_step_action_for_build_card_steps(self):
        """Each build step produces the right tap / swipe action."""
        td = coc_tutorial.TutorialDriver()
        # Match the tutorial text + advance to each step in turn.
        actions = []
        for text in ("welcome chief", "build your town hall",
                     "place your town hall",
                     "build a gold mine", "place the gold mine",
                     "build a cannon"):
            td.observe(text, painted=True)
            actions.append((td.step_action(), td.step_action_params()))
            td.advance_to_next()  # move to the next step so the next
            # observe() lands on the right action.
        # 1: welcome -> tap_bubble centred on the bubble box
        self.assertEqual(actions[0][0], "tap_bubble")
        self.assertIn("bubble_xy", actions[0][1])
        # 2: build_town_hall -> tap_dock_card with name="townhall"
        self.assertEqual(actions[1][0], "tap_dock_card")
        self.assertEqual(actions[1][1]["name"], "townhall")
        # 3: place_town_hall -> swipe_dock_to_grass. from_xy is the
        # town hall dock slot in DEVICE coords (2340x1080).
        self.assertEqual(actions[2][0], "swipe_dock_to_grass")
        self.assertEqual(actions[2][1]["from_xy"], (1024, 870))
        self.assertEqual(actions[2][1]["to_xy"], coc_tutorial.GRASS_DROP_XY)
        # 4: build_gold_mine -> mine slot
        self.assertEqual(actions[3][0], "tap_dock_card")
        self.assertEqual(actions[3][1]["name"], "mine")
        # 6: build_cannon -> cannon slot
        self.assertEqual(actions[5][0], "tap_dock_card")
        self.assertEqual(actions[5][1]["name"], "cannon")

    def test_snapshot_includes_past_steps(self):
        td = coc_tutorial.TutorialDriver()
        td.observe("welcome chief", True)
        td.advance_to_next()
        td.observe("build your town hall", True)
        snap = td.snapshot()
        self.assertEqual(snap["current"], "build_town_hall")
        self.assertIn("welcome", snap["past"])
        self.assertFalse(snap["complete"])

    def test_in_progress_until_complete(self):
        td = coc_tutorial.TutorialDriver()
        self.assertTrue(td.is_in_progress())
        td.observe("welcome chief", True)
        td.advance_to_next()
        td.observe("build your town hall", True)
        td.advance_to_next()
        td.observe("place your town hall", True)
        td.advance_to_next()
        td.observe("build a gold mine", True)
        td.advance_to_next()
        td.observe("place the gold mine", True)
        td.advance_to_next()
        td.observe("build a cannon", True)
        td.advance_to_next()
        td.observe("attack a nearby goblin village", True)
        # attack_tutorial is still in_progress; only "complete" flips
        # is_in_progress() to False.
        self.assertTrue(td.is_in_progress())
        td.advance_to_next()
        td.observe("welcome back chief", True)
        td.advance_to_next()
        td.observe("train some troops", True)
        td.advance_to_next()
        td.observe("find a clan", True)
        td.advance_to_next()
        # complete -> not in progress anymore
        self.assertFalse(td.is_in_progress())
        self.assertTrue(td.is_complete())


class TestAdvanceToNext(unittest.TestCase):

    def test_advance_welcome_to_build(self):
        td = coc_tutorial.TutorialDriver()
        td.observe("welcome chief", True)
        out = td.advance_to_next()
        self.assertEqual(out["event"], "step_advanced")
        self.assertEqual(out["from"], "welcome")
        self.assertEqual(out["to"], "build_town_hall")
        self.assertEqual(td.step_current, "build_town_hall")

    def test_advance_after_complete_is_noop(self):
        td = coc_tutorial.TutorialDriver()
        td.observe("welcome chief", True)
        for _ in range(10):
            td.advance_to_next()
        out = td.advance_to_next()
        # already on complete; advance_to_next still emits tutorial_complete
        self.assertEqual(out["event"], "tutorial_complete")
        self.assertEqual(td.step_current, "complete")

    def test_advance_to_final_step_emits_complete_event(self):
        td = coc_tutorial.TutorialDriver()
        # fast-walk to join_clan
        for text in (
            "welcome chief", "build your town hall",
            "place your town hall",
            "build a gold mine", "place the gold mine",
            "build a cannon", "attack a nearby goblin village",
            "welcome back", "train some troops",
            "find a clan to join",
        ):
            td.observe(text, True)
        # advance through the manual step (the operator did it).
        td.advance_to_next()
        # Now we're on "join_clan".next == "complete"
        out = td.advance_to_next()
        self.assertEqual(out["event"], "tutorial_complete")
        self.assertEqual(td.step_current, "complete")
        self.assertTrue(td.is_complete())


class TestTutorialStepTable(unittest.TestCase):

    def test_table_has_unique_ids(self):
        ids = [s for s in coc_tutorial.TUTORIAL_STEPS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_known_ids_in_order(self):
        order = coc_tutorial.TUTORIAL_ORDER
        self.assertEqual(order[0], "welcome")
        self.assertEqual(order[-1], "complete")
        self.assertIn("attack_tutorial", order)

    def test_no_manual_steps_remain(self):
        # The tutorial is now fully automated -- the bot dispatches a
        # scripted sequence of taps for the attack_tutorial and
        # join_clan steps instead of parking for the operator.
        manual = [s for s in coc_tutorial.TUTORIAL_STEPS.values() if s.manual]
        self.assertEqual(manual, [],
                         f"expected no manual steps; found {sorted(m.id for m in manual)}")

    def test_dock_card_slots_cover_all_build_steps(self):
        """The three build steps (townhall / mine / cannon) all have
        a tap_xy in DOCK_CARD_SLOTS via the ``name`` keyword."""
        from shared.src.lib.game.clashofclans.tutorial import DOCK_CARD_SLOTS
        self.assertIn("townhall", DOCK_CARD_SLOTS)
        self.assertIn("mine", DOCK_CARD_SLOTS)
        self.assertIn("cannon", DOCK_CARD_SLOTS)


if __name__ == "__main__":
    unittest.main()
