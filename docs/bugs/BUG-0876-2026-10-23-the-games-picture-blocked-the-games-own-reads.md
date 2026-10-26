# BUG-0876 — The game's own picture blocked the game's own reads: a page that stops painting froze the Pokémon's lane

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0876                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (deployed)                                            |
| Severity  | High                                                        |
| Area      | games / pokemon                                              |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The second long-play lane (the parallel save `second`, TASK-164) stalled again, the same way as
BUG-0875 but for a different reason, and the run `20261023-152314` on host-clone-1 wrote the lock:

```json
{"kind": "pokemon_stall", "created": "2026-10-23T15:30:49+0200", "run_id": "20261023-152314",
 "save": "second", "reason": "no_progress",
 "detail": "no milestone, no new map and no new square for 5 min of game time",
 "milestone": "starter", "map": 0, "pos": [0, 0], "done": [], "deferred": [],
 "last_events": [{"t": 1792762193.97, "kind": "stalled", "reason": "no_progress"}]}
```

The report holds **one single event** (the `stalled` one), and the lane's dispatcher could not pull a
save out of the run (`pull lacks state_second.json`): the lane still has no save at all and starts a
new game every time.

The "latest" lane's run on the same host, an hour later, shows the same thing.

## Root cause

**The game was alive, and the harness could not talk to it any more: the picture the harness takes
after every action stands in the game's way.**

The host's journal of the stalled run (`host-clone-1`, `vpt-host.service`, 15:23-15:33):

```
15:23:24.500  JS start js:759574a3 () => typeof GameBoyCore !== 'undefined' && typeof vptGB !== 'undefined'
15:23:24.502  JS done  ... in 2ms                      <- the page answers
15:23:24.617  JS start js:80a887a7 () => vptGB.boot()
15:23:24.810  JS done  ... in 192ms                     <- the ROM boots
15:23:26.115  JS done  js:b435f58e () => vptGB.startRecording() in 3ms
15:25:47.561  Page screenshot timed out after 5s        <- THE FIRST HANG IS A PICTURE, NOT A READ
15:25:47.561  JS start js:a32db882 () => vptGB.wram()
15:26:02.577  JavaScript execution timed out after 15.0s (page unresponsive or mid-navigation)
15:26:07.578  Page screenshot timed out after 5s
15:26:12.579  Page screenshot timed out after 5s
15:26:12.580  JS start js:a32db882 () => vptGB.wram()
15:26:27.593  JavaScript execution timed out after 15.0s (page unresponsive or mid-navigation)
15:26:37.595  JS start js:b4bda3d9 () => vptGB.hold('a', 90)
15:26:52.609  JavaScript execution timed out after 15.0s (page unresponsive or mid-navigation)
```

The page answers in **2 ms** right up to the first hang, and the first hang is a **screenshot**. From
then on every game action costs **25 s**: a 5 s screenshot timeout, a 15 s JavaScript timeout and
another 5 s screenshot timeout — and the game is never actually asked anything. The run produced one
event, the detector counted 309 s of "game time", called it `no_progress` and wrote the lock.

The chain, in the code:

1. `test_scripts/game/game_pokemon.py:81` — `VptGameIO.js()` asked for the game's JavaScript through
   the **action executor** (`ExecutionOrchestrator.execute_actions`), and every read
   (`vptGB.wram()`) and every key press (`vptGB.hold('a', 90)`) went that way.
2. `backend_host/src/services/actions/action_executor.py:307` and `:1119` — the action executor
   photographs the page **before and after every action**.
3. `shared/src/lib/utils/device_utils.py:54` (`capture_run_page_screenshot`) →
   `backend_host/src/controllers/web/playwright.py:774` (`_photo_page`) — that photograph is a **page**
   screenshot of the very page the game is played on:
   `await page.screenshot(path=path, full_page=False, timeout=5000)`.
4. `backend_host/src/controllers/web/playwright.py:1692` (`execute_javascript`) — the game's own read
   is `page.evaluate()` on the same page, and **Playwright serializes the commands of a page**.

So: the page stops painting (the host's window is occluded and the box is busy — four `ffmpeg`
capture processes take 30 % of a core each on two cores), a screenshot of a page that produces no
frame never comes back, and every read and key press queued behind it waits out its own timeout. The
game is fine — the page answers in milliseconds on a second DevTools session and the emulated CPU
keeps ticking — but the harness can no longer reach it.

The proof that the page was never the problem: the run of 16:14 on the same host froze the same way
and recovered **by itself** when the controller relaunched the browser (16:42:25, a new Chrome on the
debug port 9301); the game went on playing at 16:42:39 (`JS done js:a32db882 () => vptGB.wram() in
45ms`).

## Fix

`test_scripts/game/game_pokemon.py`

* `VptGameIO.js()` asks the **web controller** for the game's JavaScript directly
  (`device._get_controller('web').execute_javascript(...)` — the pattern
  `test_scripts/web/netflix_video_check.py:630` already uses) instead of going through the action
  executor. Nothing but the game is ever queued on the game's channel now, so a page that stops
  painting costs the run its pictures, never its game. A browser that does not answer is a blank
  read (the runner ends the run, BUG-0872), not a crash.
* `evidence()` takes the game's picture from the **host's screen capture** (through a device view
  that hides the web controller), not from a page screenshot: the game's own evidence must not be
  queued on the game's channel either.

## Verification

Guard test in `tests/shared/test_pokemon.py` (the whole file passes: 174 tests):

* `test_the_game_asks_the_browser_directly_and_never_queues_a_picture_on_its_channel` — the game's
  JavaScript goes to the browser (and nowhere else), a browser that does not answer is a blank read,
  and the game's evidence is the screen capture: no picture is queued on the game's channel.

The test fails on the code of today (the old `js()` needs the action executor) and passes with the
fix.

**Deployed and measured on the host** (`main-2026.10.23-89800`, on host-clone-1 and host-clone-2): the
run the second lane started on host-clone-1 at 16:59 did **3198 JavaScript calls with 0 timeouts**
(no "Page screenshot timed out after 5s", no "JavaScript execution timed out after 15.0s") and **0
lines from the action executor**. It made **66 events in 724 s** — against the 11 ticks in 450 s and
the single event of the frozen runs — chose its starter (**BULBIZARRE L5**), walked **7 maps**, fought
**14 battles** and wrote a **save** for the lane for the first time (`state_second.json`, 633 KB).

Diagnosis: `~/vpt-private/pokemon/stalls/stall_second_20261023-152314.diagnosis.md`.

**No defer flag was involved**: `deferred` is empty and no `*_deferred` flag was set. The game needs the
starter Pokémon and the whole story; nothing was skipped to get here.

## What is still open (the platform, not the game)

The page still stops painting on a busy host. That costs the run its pictures, not its game — but a
host whose window is occluded is a host that renders nothing, and the emulator's own window should
stay un-occluded. The pictures the platform takes for its own reports are still taken on the page
(for the other scripts): the same channel argument applies to them one day.
