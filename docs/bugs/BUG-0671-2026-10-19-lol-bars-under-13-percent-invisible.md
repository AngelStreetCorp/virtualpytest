# BUG-0671 — The Garen bot could not see enemy minions under 13 % health

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0671                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | game / lol bot perception                                    |
| Fixed in  | build 90145 |
| Commit    | see the merge commit of feat/task-132-target-hp              |

---

## Symptom

Owner, watching a game: "Garen still ignores the lowest target minions". Across the last runs the bot made no attack on a minion that was a sliver from dying, and the hit rate stayed at 0.5-0.7 even when the Practice Tool's last-hit marker decided.

## Root cause

`perception.find_bars` dropped any bar run narrower than 8 px (of 62), so an enemy minion under about 13 % health was not a bar at all. On 300 saved frames of the last runs the old rule found 0 bars under 13 % health. Those are the minions one auto from dying, the ones a last-hit bot must take.

## Fix

`find_bars` keeps a 3-7 px run of the darker red kill segment (the only thing left of the fill once health is below one auto) as a minion bar: on the same 300 frames it now finds 97. Ten unit tests (sliver widths 3-12).

## Verification

`tests/shared/test_leagueoflegends_garen_bot.py::test_find_bars_sees_a_sliver_of_the_dark_kill_segment`; game numbers in TASK-132.

## Follow-up (same day)

The first fix also read the thin red outline of the targeted minion (and similar red strokes) as a sliver of the dark segment: on the same 300 frames 80 % of the 97 "slivers" were false, and the bot attacked healthy minions as "killable" (attempts at 1:05, when every minion is at full health). A sliver must now sit on the bar's near-black left frame; 17 slivers remain on those frames. Test: `test_find_bars_ignores_the_red_outline_of_the_targeted_minion`.
