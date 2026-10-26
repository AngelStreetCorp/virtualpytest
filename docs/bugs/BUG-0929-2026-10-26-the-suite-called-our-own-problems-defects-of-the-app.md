# BUG-0929 — The suite called our own problems defects of the app: a missing play button, a timeout, a radio tile the tree cannot reach

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0929                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | testing (content suite, web / STB / harness)                 |
| Fixed in  | build 90145 |
| Commit    | see branch `feat/task168-web-session`                        |

---

## Symptom

Three rows of the content suite blamed the product for what we could not reach.

1. **A guest session on the web was reported as a defect.** The web run of
   2026-10-26 01:53 ended the replay case with *"the replay programme offers no
   play action"* and the cause **product**.
2. **A navigation that ran out of time was reported as a defect.** The harness
   bounded every navigation and said so in its own words (*"did not finish within
   90s: the screen never answered"*), but a node that is in the tree and a
   navigation that failed was still read as *"the surface is there and it did
   not work"* — a product defect.
3. **A radio app that was on the screen was reported as a defect.** The STB run
   of 2026-10-26 01:37 failed the radio case because the tree's reference
   picture for the radio tile did not match the app store of that box. The tile
   was right there on the screen; only the tree could not reach it.

## Root cause

1. **A guest session has no play button, and that is the session.** The app
   offers the playback of a programme to a signed-in user only. The suite
   knows the session it has (the app stores the account in `flutter.username`,
   quoted, so a guest carries `""` — a value that is truthy in Python and was
   therefore read as an account). With the session read correctly as a guest,
   the missing play button became a fact about the session, not about the app.
2. **`surface_failure` never honoured the timeout rule.** `navigate_to` says in
   its own docstring that *"a navigation that runs out of time is a platform
   fact, so it reads as a failure of the route, not as a defect of the
   product"* — but only the verification mismatch was classified as infra. A
   timeout on a node that is in the tree became a product defect.
3. **The tree's reference picture is stale, and the suite only knew the
   mismatch.** The radio tile sits in the app store of that box, but the tree's
   picture for it was captured with another layout, so the focus never landed
   on the tile and the screen showed a different one. The row said "the screen
   does not match the tree's reference picture" and stopped there: it never
   asked the screen whether the surface was there at all.

## Fix

- `test_scripts/content/_web_adapter.py`: the session is read with
  `app_account()` (the quoted empty string is a guest, not an account), and a
  missing play action in a **guest** session is reported as the session it is.
  A session that *is* signed in and still finds no play action stays a defect.
- `test_scripts/content/_mobile_adapter.py`: the same rule on the phone. The
  suite itself uses the app's guest bypass there, so it **knows** the session is
  a guest: an item that opens and plays nothing is the session, not a defect.
  And the app says why in its own words — *"Please sign in with your account to
  play this content."* — so that prompt is read on the screen and named in the
  row, the way the web adapter reads it. A session that is signed in and still
  plays nothing stays a defect.
- `test_scripts/content/_harness.py`: a navigation that ran out of time is
  classified **infra** (`navigation_timeout()`), next to the verification
  mismatch, and the reason says that the platform did not answer in time.
- `test_scripts/content/_stb_adapter.py`: the radio case reads the screen's own
  text before it gives up. A radio tile that is on the screen means the surface
  is present and the **tree** failed to reach it: the row says so and stays
  infra — never a defect of the product.

## Verification

`scripts/agent/vod_radio_offline_check.py` — 65/65 checks pass. The new checks
prove that a guest session with no play action is infra and names the guest
session, that a signed-in session with no play action is still a defect, that a
navigation timeout is infra, that a radio tile on the screen makes the radio row
a tree gap, and that a radio tile that is *not* on the screen leaves the
decision to the tree. On the phone the same rule holds: a guest session that
plays nothing is infra, a signed-in one that plays nothing is a defect, and
the app's own sign-in prompt ("Please sign in with your account to play this
content.") is read on the screen and named in the row.

Live, on the lab set-top box (2026-10-26): the radio case reports that the
radio app *is* on the box's app store while the tree's route does not reach it.

On the web the rule landed after the run of 01:53, so the two are not visible
in one report. That run reached the detail page of a real programme and found
no play action on it, and reported the row as **product** — its own evidence
already said **session: guest** (the commit that reads the app's account
correctly landed a minute before the run), but the rule that turns a guest
session with no play action into infra landed nineteen minutes later. The web
run of 2026-10-26 11:04 is the one that carries the rule: on the same host the
replay and VOD rows come back **infra** with the app's own sign-in prompt in
the row, and the platform reports **zero product defects**.

On the phone the rule is visible as the difference between two runs. The runs
of 2026-10-26 07:13 and 07:24 drove the app (the bypass worked) and still
reported the replay and VOD rows as **product** defects (*"3 replay item(s) on
'home_replay' were reachable but none of them started playback"*). The run of
2026-10-26 07:35, with the rule in place, reports the same two rows as
**infra** and names the app's own prompt in the row: *"the app asks for a
sign-in to play this content (please sign in with your account to play): the
session of this run covers the catalogue, not the playback"*. The suite also
stops at the **first** item that shows the prompt — that is why the final run
tried 1 replay item where the earlier runs tried 3.

## Evidence

- The web run of 2026-10-26 01:53: `~/vpt-deliverables/vod-radio-runs/2026-10-26T01-53-45Z-web/`
  — the replay row carried `session: guest` and the cause `product`.
- The web run of 2026-10-26 11:04: `~/vpt-deliverables/vod-radio-runs/2026-10-26T11-04-47Z-web2/`
  — the same host, with the rule live: the replay and VOD rows carry
  `session: guest` and the cause `infra`, and the platform reports **0 product
  defects**.
- The mobile run of 2026-10-26 07:35: `~/vpt-deliverables/vod-radio-runs/2026-10-26T07-35-05Z-mobile7/`
  — the replay and VOD rows carry the app's own sign-in prompt and the cause
  `infra`.
- The STB run of 2026-10-26 01:37: `~/vpt-deliverables/vod-radio-runs/2026-10-26T01-37-40Z/`
  — the radio row: *"reference: apps_radio.jpg not detected in source"*.
