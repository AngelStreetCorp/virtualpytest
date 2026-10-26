# BUG-0677 — The game chat was read as enemy minion bars

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0677                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | game / lol bot perception                                    |
| Fixed in  | build 90145 |
| Commit    | see the merge commit of fix/lol-chat-bars                    |

---

## Symptom

lol-lasthit's minion-bar classifier, run over the bars `find_bars` returned on the 5 Hz data game, rejected 88 of 301: almost all were chat lines ("Urgot Bot (Urgot) has slain ...", the bot names in red and blue) in the bottom-left. Across the 1932 captured frames 1711 "minion bars" sat at x 131-519, y 430-882.

## Root cause

Chat text is coloured red on a dark panel: a run of red pixels with a near-black row above and below passed the bar tests. The bot saw an enemy "minion" about every frame at the left edge, which also feeds the far-minion walk and the wave counts.

## Fix

`find_bars` blanks the chat rectangle (x < 540, 430 < y < 890 on a 1920x1200 frame). On 97 saved frames this removes 83 of 462 minion bars, all inside the rectangle, none outside. Real minions that far from Garen (more than 420 px) are outside last-hit reach anyway. Test: `test_find_bars_ignores_chat_text_in_the_bottom_left`.

## Follow-up (same day)

lol-lasthit's Practice Tool classifier (trained with our data-game crops) vetoed 44 of 317 remaining bars; 16 sat in the right-edge strip (x 1900+, y 700-799): the red respawn digits over the team portraits. The portrait exclusion now starts at y 680 and the strip x >= 1880 below y 340 is blanked: 35 of 318 bars removed on 80 frames, none inside Garen's reach. Test: `test_find_bars_ignores_hud_digits_at_the_right_screen_edge`.
