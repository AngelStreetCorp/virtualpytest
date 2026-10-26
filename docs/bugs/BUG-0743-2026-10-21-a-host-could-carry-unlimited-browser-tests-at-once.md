# BUG-0743 — A host could carry unlimited browser tests at once, and the UI could not see them

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0743                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium (the host runs out of memory and slows down; the user cannot tell why) |
| Area      | testing / platform                                           |
| Fixed in  | build 90145 |
| Commit    | c321f89ce                                                    |

---

## Symptom

After the browser isolation (BUG-0727), any number of browser-isolated web scripts could
start on the same host at the same time. Each one gets its own Chrome — its own debug
port, its own profile directory — which is the point, but nothing counted them:

- a host with 4 GB of RAM could end up with eight Chromes, each with a profile of its own;
  the runs slowed to a crawl and the host's other work (capture, monitoring, the KPI
  units) suffered with it;
- the user had no way to see it coming: the host card showed nothing about browsers, and
  the Run page still treated the device as exclusive.

## Root cause

The device lock answers "may this run use the device?", which was never a question about
the host's capacity. Once every browser run brought a Chrome of its own, the scarce
resource became the **host** — and no one was counting it.

The UI made it worse: the Run page split the selected targets into "runnable" and "busy"
by the device lock, and queued the busy ones. A device held by another browser run looked
exactly like a device held by a normal script, so the page queued a second browser test
that the server was perfectly willing to start beside the first.

## Fix

**The host counts and caps the browser runs it carries** (`shared/src/lib/utils/browser_run_slots.py`):

- the cap **follows the host's memory**: a browser test costs about 600 MB, the host keeps
  about 1.2 GB for itself, and the rest is what the browsers may use — never more than 6,
  never less than 1. The lab's smallest host (3.9 GB, 2 cores) therefore carries **4**
  browser tests; a 16 GB host carries 6. `VPT_MAX_PARALLEL_BROWSER_RUNS` overrides it per
  host;
- the slot is taken in the script executor, which is the one place every run passes
  through: the API, the Run page, and a queued deployment the host scheduler picks up all
  go through it, so the cap cannot be walked around;
- a run that finds the host full **waits** for a free slot (bounded by
  `VPT_BROWSER_SLOT_WAIT_SECONDS`, 600 s) instead of piling on or being refused. The wait
  happens in the host's background thread, so the caller is not blocked and the run starts
  by itself as soon as a slot frees;
- the slot comes back when the run ends, whatever ended it.

**The UI can now see and use the parallelism:**

- the host reports its browser load in its stats (`browser_runs: {running, waiting, cap}`);
  the server passes it through, and the host card shows a **"N/6 browsers"** chip — with
  the waiting runs named in its tooltip;
- the Run page no longer queues a target whose device is held by a **browser-isolated**
  run: that run drives a Chrome of its own, so the server starts the new one beside it.
  The server stays the arbiter — a script that is *not* browser-isolated is queued or
  refused there, exactly as before.

## Verification

`tests/backend_host/test_browser_run_slots.py` (16 tests):

- the cap follows the host's memory (4 on a 4 GB host, 6 on a 16 GB one, 1 on a 2 GB one),
  an operator's value overrides it, and a broken value falls back to the memory rule;
- the pool hands out slots up to the cap, refuses the next one, and the run that waits
  gets the slot as soon as one frees;
- a wait that runs out refuses the run instead of letting it through, and the refused run
  takes no slot;
- a script is recognised as browser-isolated from its `_target_rules`, and a broken or
  missing script does not break the run;
- a browser-isolated run **holds** a slot while it runs and **gives it back** when it ends
  (measured around the run), a plain script takes no slot, and a browser run that finds
  the host full does not start at all.

The frontend typechecks clean (`tsc --noEmit`).

Live, on `host-clone-2` (deploy `main-2026.10.21-89469`, merge `c321f89cec70`): two browser
scripts were started through the platform API, and the host reported its load to the server
while they ran:

```
before the runs   browser_runs = {'cap': 6, 'running': 0, 'waiting': 0}
during the runs   browser_runs = {'cap': 6, 'running': 2, 'waiting': 0}
after the runs    browser_runs = {'cap': 6, 'running': 0, 'waiting': 0}
```

The count goes up while the runs are alive and back to zero when they end, so the slots are
given back — and no Chromium was left behind after the two runs finished. The host card
reads that number as the **"N/6 browsers"** chip.
