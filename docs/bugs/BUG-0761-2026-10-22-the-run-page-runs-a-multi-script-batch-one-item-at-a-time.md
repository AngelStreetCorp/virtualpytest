# BUG-0761 — The Run page runs a multi-script batch one item at a time, so it cannot start four runs at once

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0761                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium (the platform runs several web scripts at once — the Run page cannot start them; the user clicks Run on four items and gets them one after another) |
| Area      | frontend / testing                                           |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On the Run page, tick one browser target, select **four** web scripts — the page says
**"Selected Items (4)"** — and press **Run**. All four do run. But they run **one after
another**, never at the same time, and each one takes the **same debug port 9300**, because
the previous one has already released it.

Live on `host-clone-1`, 2026-10-22, four browser-isolated scripts in one batch:

```
08:41:13  [web/youtube_video_check.py]      Port 9300 free   ← run 1 ends
08:42:37  [web/youtube_video_check.py]      Port 9300 free   ← run 2 ends
08:43:45  [web/dailymotion_video_check.py]  Port 9300 free   ← run 3 ends
08:43:53  [web/netflix_video_check.py]      report generated ← run 4 ends
```

Every run starts after the previous one has freed 9300. No two overlap.

And a second, quieter gate: **while a batch is in flight the Run button is disabled** and
Abort is enabled. So the page cannot start a second batch beside the first either.

```
Run  (greyed)   Abort (red, enabled)     ← a batch is running
Run  (dark)     Abort (greyed)           ← nothing running
```

**The Run page therefore cannot start two concurrent runs on one host at all** — not four,
not two.

## Root cause

Two separate things, and only the first is a defect.

1. **The batch is sequential.** The page fires the selected items one after another and waits
   for each. The server has no reason to serialise them — they are all `browser_isolated`, so
   the server starts them side by side. Measured, not argued: four browser scripts fired at
   once through the API on `host-clone-1` (current main) gave

   ```
   08:49:40  dailymotion  port 9300
   08:49:41  youtube      port 9301
   08:49:42  facebook     port 9303
   ```

   four runs alive at once, each on its own port and profile, each report holding its own
   per-run step images (`1792651824741474561_youtube_home_state.png` and friends), and the
   executor's before/after device shots correctly **skipped** rather than filled with the
   shared screen. A fifth (`browser_task`) started at 08:49:38, **waited ~55 s for a slot**
   and launched at 08:50:33 once one of the four finished — the host cap of 4 doing its job.
   The serialisation is in the client, and only in the client.

2. **Run is disabled during a batch.** This one is deliberate and defensible: it stops a user
   double-submitting the same selection. But combined with (1) it means the UI has no way to
   express "these four at once", even though the backend can do it.

This contradicts [BUG-0743](BUG-0743-2026-10-21-a-host-could-carry-unlimited-browser-tests-at-once.md),
whose Verification claims *"the Run page starts a browser test beside another one instead of
queueing it"*. What is true is narrower: the page does not **queue** a target held by a
browser-isolated run — the lock badge appears but the target stays selectable, and a fresh
launch while nothing else is running is accepted. It is not true that one page can start two at
once. That claim has never been tested live; it is written as though it had been.

## Fix

Not started. The shape it should take, roughly:

- let the batch fire all of its items without waiting for each, so the server decides what runs
  beside what (it already arbitrates: browser-isolated runs beside each other, everything else
  queues or is refused);
- keep Run disabled only while *this* page's batch is submitting, then re-enable it, so a
  second batch can be started while the first is in flight — that is the gesture a user needs
  to run two things on one host;
- correct BUG-0743's Verification wording to what was actually measured.

The host cap (BUG-0743's `browser_run_slots`) is the thing that keeps this honest: once the
page can start four at once, the cap has to be the limit that bites, and today that cap has
also never been exercised live.

## Verification

- select four browser scripts against one target on the Run page and press Run once: all four
  are in flight at the same time, on four distinct ports (9300–9303), each with its own
  profile — or the excess is held by the host's cap and the page says so;
- with one batch running, a second Run click on the same target starts a second batch rather
  than being refused;
- a batch containing a **non** browser-isolated script still queues or is refused exactly as
  before — the change must not weaken the lock for ordinary scripts.
## Sightings

- also seen by QA sweep 2026-10-22 (TESTER-02, OPS concurrency check): one page batch is serialised, confirmed on labox-backend; but four browser tabs of the Run page, one Run click each, started four runs within 2.7 s on one host and all four ran to the end, so a fix that fires the batch in parallel can rely on the server side already supporting it.
