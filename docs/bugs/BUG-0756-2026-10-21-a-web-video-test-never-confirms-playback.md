# BUG-0756 — A web video test never confirms playback: YouTube and Dailymotion videos do not play on a lab host

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0756                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Open — the checks now report why they fail, and an unconfigured check no longer fails its campaign, neither in the row nor in the campaign's own verdict; playback itself is still unexplained |
| Severity  | Medium (the check that is supposed to prove video playback cannot prove it, on any host in this lab) |
| Area      | testing / backend                                            |
| Fixed in  | Unreleased                                                   |
| Commit    | `bb883fe40` — branch `fix/e72-video-check-legibility`         |

---

## Symptom

`web/youtube_video_check.py` and `web/dailymotion_video_check.py` both end on a failed
playback verdict on a working host, whether they run alone or several at a time:

```
❌ [youtube_video_check] Video was not playing during 25s monitoring window
🎯 Result: FAILED
```

and the run carries `SCRIPT_SUCCESS:false`. The run itself is healthy: the browser launches,
the site loads, the video element is found, the page stays open for the whole monitoring
window. Only the verdict is negative — the video element never reports playing, and the
samples collected over the window show no progression.

This was first noticed while verifying the browser isolation (TASK-146), where it looked
like a regression and had to be ruled out carefully — see below. It reproduces **without**
any parallelism, so it is not a browser-isolation defect.

## Evidence

Three runs on `host-clone-2` / `host` (`host_vnc`), all recorded in
[TASK-146](../tasks/TASK-146-parallel-browser-runs-one-host.md):

| Run | Port | Verdict |
|---|---|---|
| youtube + dailymotion in parallel, task `b559d57a-01c4-411f-8485-203f74e157` | 9300 | Video playback not confirmed during monitoring window |
| dailymotion in parallel, same start | 9301 | Video playback not confirmed during monitoring window |
| **solo control**, task `99c13e77-0d48-4e3a-8681-47a3ec60b559` (17:16:54 → 17:18:32) | 9300 | *"Video was not playing during 25s monitoring window"* |

The solo control is the important one: the same script, alone on the host, gives the same
negative verdict. Nothing about parallel runs is involved.

**Still reproducing on the current build** — 2026-10-21, `main-2026.10.21-89534`, `host-clone-2`
/ `host`, `https://www.youtube.com/watch?v=y9n6HkftavM`, 36 s:

| what the run recorded | value |
|---|---|
| `page_load_time_ms` | 2335 (the page loaded, and fast) |
| `cookie_result.injected` | true, consent cookies accepted, `modal_found: false` |
| `ad_result.ad_detected` | false |
| `video_result.playing` | **false** |
| `video_result.progress_seconds` | **0.0** over 4 samples in the 20 s window |
| `video_result.video_load_time_ms` | **null** |
| `video_result.first_frame_method` | **null** |

The last two are the new information. The browser's own first-frame signal reports **nothing at
all** — no first frame was ever produced, not a slow one. That is the strongest lead so far and
it is the cheapest to read: the page loaded in 2.3 s and the consent gate is already clear, so
whatever stops the video is between "the player exists" and "the first frame is painted".

## Root cause

**Not yet established.** The failure is confirmed and reproducible, the cause is not known.
What is ruled out so far:

- **Browser isolation** — the run has its own debug port and its own Chrome profile, and a
  solo run behaves exactly like a parallel one.
- **The navigation** — the page loads and the video element is found, so the failure is
  after the goto, in the monitoring loop.

Candidates worth checking, in the order they are cheap to test:

1. **Autoplay policy.** The video element is asked to play from script; the host's Chrome
   runs with no user gesture and no `--autoplay-policy=no-user-gesture-required`, so the
   element can stay paused and every sample reads `paused`. The script does force a play
   (`_JS_FORCE_PLAY`) and retries, but the retry never reports the element leaving `paused`.
2. **A consent / ad gate in front of the video.** The site may be showing a pre-roll or a
   consent interstitial that the script dismisses without ever reaching the player. Weaker than
   it was on 2026-10-21: the run recorded `ad_detected: false` and `modal_found: false`, so
   nothing obvious was in the way.
3. **The first-frame probe.** `_JS_GET_FIRST_FRAME` reports no first frame at all
   (`video_load_time_ms: null`, `first_frame_method: null`) — see above. Read this first: it is
   the browser's own signal and needs no inference.

Related, already reported and already fixed: [BUG-0121](BUG-0121-2026-09-16-youtube-selector-opens-the-sponsored-card.md)
(the YouTube selector opened the sponsored card instead of the video),
[BUG-0122](BUG-0122-2026-09-16-motion-check-measures-below-a-portrait-players-video.md)
(the motion check measured below a portrait player's video). Both are marked fixed, yet the
playback verdict is still negative, so one of them is either incompletely fixed or the
playback never starts for a different reason. Worth checking before opening a new line of
enquiry.

## Fix

**Partial, and deliberately so: this change makes the failure legible, it does not make the video
play.** The measured premise is that the three checks fail in three different ways, and the verdict
could not tell them apart. A failing run now says which stage failed, what `play()` did, and what
the probe saw.

What changed (branch `fix/e72-video-check-legibility`, commit `bb883fe40`):

- **The probe reports what it saw** (`shared/src/lib/utils/local_debug_playwright_js.py`). It
  still picks the best-scoring `<video>`, but it now also returns the element index, the media
  `error` code, `readyState`, `networkState`, the buffered range, the decoded-frame counters and
  the **host** of the media `src` — never the full URL, which can carry a token. When there is no
  `<video>` in the top document it says so and reports what it did see: how many iframes, whether
  any of them looks like a player, and whether the page looks like a consent wall.
- **The force-play reports the outcome of `play()`** (same file, one shared copy for the three
  scripts). It used to call `play()`, drop the promise and answer `attempted: true` — a blocked
  autoplay, an unsupported source, a DRM-protected stream and a decode error were all
  indistinguishable from a successful attempt. It now plays the same element the probe watches
  and awaits the promise (bounded), reporting `resolved` / `rejected` / `pending` / `threw` with
  the reason.
- **The verdict carries the reason** (`shared/src/lib/utils/web_video_legibility.py`, new). It
  names the stage that failed (`navigation` / `consent` / `ad` / `pre_monitoring` / `playback`),
  the `play()` outcome, the probe's diagnostics, and any hypothesis — marked as a hypothesis, never
  as a measurement.
- **An unconfigured check is not a playback failure** (`netflix_video_check.py`). A missing
  account now reports the outcome `not_configured`, with its own status and exit code, instead of a
  generic failure that a nightly campaign counts as a broken video.

Pass/fail semantics did not change: a video that never plays still fails, with a non-zero exit and
a failed result row.

### The three measured shapes this makes distinguishable

| script | what the run showed | what the verdict says now |
|---|---|---|
| `netflix_video_check.py` | never ran: no account configured | outcome `not_configured` — not a playback failure |
| `dailymotion_video_check.py` | page loaded in 175 ms, no consent stage, no ad stage, no video element ever seen | stage `pre_monitoring`, plus the probe's report of what the page did contain |
| `youtube_video_check.py` | page loaded in 3 s, consent accepted, no ad, a `<video>` element found on every sample but never playing | stage `playback`, the `play()` outcome with its reason, and the element's diagnostics |

### Deliberately not established

- **Why the Dailymotion page loads in 175 ms with no consent step.** The check now reports that it
  never reached the monitoring stage; it does not guess why.
- **Whether the `<video>` element YouTube serves is the real player.** The check now reports the
  element index it watched and the one it played, so a mismatch is visible; the probe was not
  widened into iframes.
- **Why the video does not play.** That is this bug, and it is not fixed here.

## The framework leg: an unconfigured check is skipped, not failed

The legibility fix above makes the verdict legible; the **framework** leg makes the count
honest. It is a separate change (branch `fix/e73-skipped-outcome`) because it touches the
platform's counting, not the check.

**What was wrong.** A check that was never configured (the Netflix check with no `--email`)
never looked at a video, but its row in `script_results` was written with `success = false` —
the same boolean a broken video gets. The nightly campaign counted that row as a failure, so
the campaign ended `failed` every night for a check that never looked at a video. The
campaign's own counting code already knew how to express "skipped"
(`scripts/nightly_campaigns/poll_results.py`), but no row could ever carry the field, so that
branch was dead code.

**What changed** (branch `fix/e73-skipped-outcome`):

- **`script_results` gains a `skipped` column** —
  `setup/db/migrations/20261024a_script_results_skipped.sql`, plus the fresh-database schema in
  `setup/db/schema/003_test_execution_tables.sql`. The migration is additive and idempotent:
  `ADD COLUMN IF NOT EXISTS skipped boolean NOT NULL DEFAULT false` — no drop, no type change,
  no data rewrite, so applying it twice is a no-op.
- **The flag is written by the run's final write** (`update_script_execution_result`), derived
  from the outcome metadata the run itself recorded — `status` / `outcome` /
  `counts_as_playback_failure` — never from the wording of the error and never from the script
  name (`shared/src/lib/utils/script_skipped.py`). A run that was configured and then failed is
  not a skip; a run that succeeded is never a skip. The start row keeps the column's default
  (`false`): at start time the outcome is not known yet.
- **A campaign counts a skipped row as skipped, not as a failure**
  (`shared/src/lib/database/campaign_executions_db.py`): a campaign whose rows all succeeded or
  were skipped ends `completed` / `success = true`; a campaign with one genuinely failed row
  still ends `failed` / `success = false`.
- **The field reaches the poller** through the campaign-results route's slim column set
  (`backend_server/src/routes/server_campaign_results_routes.py`). The payload stays slim —
  `metadata` and `error_msg` are still left out — and the poller itself is unchanged.
- **The executor counts a skipped run as skipped, not as a failed script**
  (`shared/src/lib/executors/campaign_executor.py`). The nightly deployment closes its campaign
  through the executor, and the executor carries its own verdict, so the flag had to be read there
  too — see the next section.

### The nightly path's own verdict (this round)

The first part of the framework leg fixed the **reconcile** path — the one that closes campaigns
whose worker disappeared. The **nightly** path closes its campaign through the *executor*, and the
executor has a verdict of its own: it read `failed_scripts == 0` and counted a not-configured check
as a failed script, so the campaign the nightly deployment writes still ended `failed` for a check
that never looked at a video.

**The executor now reads the row.** After a script run, the executor looks at the row that run
wrote (`script_results.skipped`) and, when the row says the check was skipped, routes the run into
the skip branch it already had: `skipped_scripts` counts it, `failed_scripts` does not, the run is
not a failure, and the campaign does not stop on it. The row is the authority, because the row is
what the run actually recorded — **not** the exit code (2 is ambiguous: argparse exits 2 for a usage
error too, which is exactly how the Netflix check first failed), **not** the wording of the error,
and **not** the name of the script.

**What did not change.** A script that was not run at all (an OS mismatch) is still skipped exactly
as before: no row, counted as skipped, and the campaign not failed by it. A genuinely failed check
still fails the campaign, and still stops it when `continue_on_failure` is false. The auto-abort on
consecutive host timeouts still fires for real timeouts. The migration is unchanged — this round
adds no column and touches no SQL.

**What the leg now claims.** The framework leg is complete: a check that never ran because it was
not configured is not counted as a failure in the row, not in the row-level count, and not in the
campaign's own ✓/✗. The leg does **not** claim that the video plays — that is the rest of this bug,
and it is still open.

**What did not change.** A video that never plays still fails, still fails its campaign and
still shows as a failure. A skipped row is *distinguishable*, not merely absent.

**Regression tests** — `tests/test_skipped_outcome.py` (offline: no network, no browser, no
host, no device, no database):

```
timeout 300 python3 -m pytest tests/test_skipped_outcome.py -q
```

They cover the six behaviours that matter: a campaign whose only check was never configured
ends `completed`; a campaign with one genuinely failed row still ends `failed`; a campaign with
one passed and one skipped row ends `completed`; a configured run that failed is written with
`skipped = false`; the nightly poller's own counting, over a payload carrying one skipped and
one failed row, gives `pass=0 fail=1 skip=1`; and the migration is additive and idempotent.
The same tests fail against the pre-fix sources (`ff35a0524`), which is the point of them.

**Regression tests for the executor's verdict** — `tests/test_campaign_skipped_verdict.py`
(offline: no network, no browser, no host, no device, no database — the row a run would have
written is faked, so the test needs neither a database nor the `skipped` column):

```
timeout 300 python3 -m pytest tests/test_campaign_skipped_verdict.py -q
```

They drive a real campaign through the executor and assert on its verdict: a campaign whose only
check was not configured ends `completed` with one skipped and no failed script; a genuinely
failed check still ends `failed`; a not-configured check does not stop the campaign while a real
failure still does; the row of a not-configured check is still linked to the campaign execution; an
OS-mismatch script is still skipped exactly as before (no row, no link); and the per-child outcome
record says the check was skipped and why. Two tests pin the signal down: a failure whose message
says "not configured" is still a failure (the wording decides nothing), and a failed check whose row
cannot be read is still a failure (no row, no evidence).

Against the pre-fix sources (`ff35a0524`) **3 of the 10 fail on the verdict itself** — the
campaign ends `failed` where the test expects `completed`, the campaign stops at the not-configured
check, and the outcome record does not say it was skipped — and the 7 that pass are the ones that
must not change (a genuine failure still fails and still stops the campaign, the row is still
linked, an OS mismatch is still skipped exactly as before, the wording is not a signal, an
unreadable row is a failure, a successful run is never a skip).

## Verification

Regression test (offline: no network, no browser, no host, no device):

```
timeout 300 python3 -m pytest tests/web/test_video_check_legibility.py -q
```

It drives the shared probe and the shared force-play through a small DOM double and asserts on the
result: the stage, the `play()` outcome, the diagnostics, the element that is played versus the
element that is watched, the "not configured" outcome and the pass/fail decision. The same tests
fail against the pre-fix sources (`git show 20aff4cba:…`), which is the point of them.

Once the cause behind the failing verdict is found, a solo run of each script on any host has to
end in a positive verdict, and two parallel runs have to end in the same positive verdict:

- `POST /server/script/execute` `web/youtube_video_check.py` — `Video playing confirmed —
  progressed <n>s`, `SCRIPT_SUCCESS:true`
- `POST /server/script/execute` `web/dailymotion_video_check.py` — same
- the two at the same time on one host — both positive, on their own ports (9300+)

A run that ends negative on a host that can plainly play the video is not a pass, whatever
the rest of the run reports.

## The visibility leg: the reports show the skip as a skip

The framework leg makes the **count** honest: the row carries the flag, the campaign counts it
apart from a failure, and the nightly poller can see it. The **visibility** leg makes it honest
in the place a human actually reads — the reports. It is a separate change (branch
`fix/e74-visible-skipped-nightly`) because it touches the UI, not the counting.

**What was wrong.** The Test Reports page had no word for a skip. `success` was the only thing it
knew, and a skipped run is `success = false` — exactly like a broken one. So the nightly campaign
row showed a red **FAIL** for a check that never looked at anything, and the check's own chip
inside the expanded campaign read **FAIL** too. The row said "skipped"; the screen said "failed".
An operator reading the page at 01:30 saw a platform with a broken video every night — for a check
that was never configured — which is exactly the defect the framework leg had just removed from
the counting. The counting was honest and the page was not.

**What changed** (branch `fix/e74-visible-skipped-nightly`):

- **One rule, in one place** (`frontend/src/utils/resultOutcome.ts`). `getResultOutcome()` reads a
  row and says what it means: `passed`, `failed`, `skipped` or `running`. The skip is decided by the
  row's own flag and by nothing else — never the script name, never the error text — and it is
  decided **before** the "still running" heuristic, because a skipped run did finish and wrote its
  row: a short skipped run would otherwise be read as a run that is still going. A row without the
  flag keeps the old reading (pass / fail), so a payload that predates the flag is never
  reinterpreted.
- **The reports show the skip as a skip** (`frontend/src/pages/TestReports.tsx`). A skipped run
  wears the muted grey of a skip — never the red of a failure: in the status cell of the run table,
  and in the chip of the check inside an expanded nightly campaign, which reads **SKIP** instead of
  **FAIL**.
- **The nightly row counts its skips apart** (`frontend/src/pages/TestReports.tsx`). A campaign row
  shows `passed/total` as before, and a campaign that had a skip now says so — `1 skipped` beside
  the ratio, and in the cell's tooltip — instead of leaving the skipped check to be read as a check
  that failed or was never run.

**What did not change.** A genuinely failed check still fails, still shows red, and still fails its
campaign. A run that succeeded is still a pass, whatever else the row carries. Nothing on this leg
decides what a run *means* — the run decides that, and this leg only reads it and shows it.

**What the leg claims.** The skip is visible where the nightly is read: a check that never ran is
never shown as a failure. The flag itself comes from the run (the framework leg); this leg only
shows it.
