# BUG-0760 — An hourly job leaks a Chrome on host-clone-2 every hour, and the browser-run cap cannot see it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0760                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (part 2: the cap sees the leaks and the host reclaims them, both deployed; part 1: the end of a run takes down the browser that run launched, by pid, whatever ended the run — merged on `fix/e68-run-end-kills-its-own-browser`) |
| Severity  | High (the host fills with dead browsers: 9 Chromes, ~2 GB, on a 3.9 GB host whose cap is 4; the counter that exists to prevent exactly this reports zero) |
| Area      | backend_host / testing                                       |
| Fixed in  | build 90145 |
| Commit    | part 2: 499d981b494a (int-mvjr3af53add43), deployed as main-2026.10.22-89622 · part 1: c29414dee65c + 69ec0e5c0a1b + 3726c8b0d340, deployed to host-clone-2 as main-2026.10.22-89676 · part 1 (the teardown): 3063d1f12 + fc172cfe2 |

---

## Symptom

`host-clone-2` carries **nine live Chromium browsers** and **zero running tests**. They hold the
whole run-port range, one new arrival per hour, and nothing in the platform knows they are there:

```
$ sudo -n ss -ltnp | grep ':93'
127.0.0.1:9300   users:(("chromium",pid=1636830))
127.0.0.1:9301   users:(("chromium",pid=1660279))
127.0.0.1:9302   users:(("chromium",pid=1683713))
… up to …
127.0.0.1:9308   users:(("chromium",pid=1820529))

$ ps aux | grep -cE '[v]ideo_check|[t]etris'
0                                     ← nothing is running

$ python3 -c "from shared.src.lib.utils.browser_run_slots import browser_run_status; print(browser_run_status())"
{'running': 0, 'waiting': 0, 'cap': 4}     ← the host believes it is idle
```

Host memory: 3915 MB total, 2194 MB used, 1720 MB available — on a host whose browser cap is 4
because that is what its memory allows (`memory_derived_cap() == 4`).

## Evidence

Every listener is a Chromium started by an hourly job, one per hour, each with its own per-run
profile directory under `backend_host/config/user_data_runs/<run id>` — the TASK-146 path, so the
allocator handed each one its own port and profile correctly:

| port | pid | profile (run id) | started (host time) | age | RSS |
|---|---|---|---|---|---|
| 9300 | 1636830 | `9a48531e-cadb-…` | Oct 21 23:06:11 | ~8 h | 174 MB |
| 9301 | 1660279 | `692116ec-9aca-…` | Oct 22 00:06:22 | ~7 h | 171 MB |
| 9302 | 1683713 | `0174f171-e4f6-…` | 01:06:47 | ~6 h | 175 MB |
| 9303 | 1707165 | `f9c20d00-1215-…` | 02:07:22 | ~5 h | 178 MB |
| 9304 | 1730239 | `8ff3c20c-30c0-…` | 03:08:30 | ~4 h | 186 MB |
| 9305 | 1752603 | `54c0a7dc-3407-…` | 04:08:45 | ~3 h | 225 MB |
| 9306 | 1775439 | `4c820e21-8a40-…` | 05:09:49 | ~2 h | 224 MB |
| 9307 | 1797984 | `9d2e2dff-0705-…` | 06:09:59 | ~1 h | 224 MB |
| 9308 | 1820529 | `4bf0cab7-da99-…` | 07:10:34 | ~1 h | 226 MB |

118 Chromium processes in total (each browser is a process group), one browser per hour on the
hour, for nine hours. The profile name on 9308 is `4bf0cab7-da99-4990-8c5f-e87696a3f7c1`, which
is the `owner_job_id` the device lock was reporting at the time.

## Root cause

**Two separate things, and only one of them is understood.**

1. **The teardown does not always kill the browser it launched.** A run gets a port and a profile
   from the TASK-146 allocator, launches its Chrome, and finishes — but the Chrome survives. The
   per-hour spacing says a *scheduled* job does this every hour, so this is not a one-off crash:
   some path that ends a run does not run the browser cleanup. Which path is not yet established;
   `game/game_tetris.py` is the obvious suspect (it launches a browser on the same per-run path
   but does not declare `browser_isolated`).

   **Established since (E68).** The path is the run's own cleanup, and it fails twice over:
   the run closes its browser over the Playwright controller loop, and a wedged loop — the very
   thing that made the run fail — means the close never runs; and even when it does run, the
   process kill sat *behind* the graceful close inside the cleanup routine, so a hang there left
   the browser alive while the controller had already reset its flags and believed there was no
   browser to close. Measured on the game host: the run ended at **17:05:54** with
   `Cleanup timed out or failed: TimeoutError:` and the Chromium was **still alive on port 9300**
   until the periodic reclaim pass took it at **17:09:59** — four minutes later, on a different
   path, for a different reason.

2. **The cap counts runs, not browsers.** `browser_run_status()` reads the slot pool, and a slot
   is released when the run ends regardless of whether the browser it launched actually died. So
   a leak is invisible to the very mechanism that exists to stop the host overloading. A run that
   leaks its Chrome still frees its slot, and the next run is admitted on top of the corpse.

The consequence is the part that matters: **the cap is advisory, not a limit.** It correctly
prevents four runs from starting at once and does nothing about the ninth browser.

## Fix — part 2 done (the cap sees them), part 1 done too (the teardown)

**Part 2 — the cap counts what the host is carrying. SHIPPED.**

`BrowserSlotPool` tracked only what *this process* had started, and gave a slot back when the
run ended whether or not its Chrome died. So a browser that outlived its run cost the host
nothing and was invisible to the mechanism built to stop exactly that. The cap now adds
`leaked_browser_count()` — run ports with a live listener and no live owner — to the runs in
flight:

- a host carrying more dead browsers than its cap **admits nothing more**, and says why:
  *"host carries 9 browser(s) left over from finished runs, plus 0 running (limit 4)"*;
- a listener whose owner is **alive** is a run in progress and is deliberately not counted
  twice, which would make the cap stricter than the host really is;
- `status()` and the host's `browser_runs` stats carry `leaked` alongside `running`/`waiting`/
  `cap`, so the load the old count missed is visible;
- the sweep is **read-only and never kills anything** — reaping a leaked browser stays
  deliberate work. There is a test that asserts the function references no killing call at
  all, because the alternative cost this host its SSH.

**Part 1 — the teardown that skips the kill. FIXED (E68, `fix/e68-run-end-kills-its-own-browser`).**

That is the leak itself, and it is not fixed by noticing it: a host with nine corpses refuses
new work until someone clears them, which is honest but is not a repair. Someone still has to
find the path that ends a run without killing the browser it launched. The hourly spacing and
`game/game_tetris.py` remain the starting point.

**What the path turned out to be.** The run ends, and the browser survives, for two independent
reasons, both of which had to be closed:

1. **The close was scheduled on the loop that had already wedged.** The run closes its browser
   over the Playwright controller loop (`close_browser(wait=True)` → the cleanup coroutine on
   that loop). A wedged loop is exactly why the run failed — *"The Playwright controller loop did
   not answer within 120 s"* — so the close was queued on a loop that would never answer it. The
   journal shows it: `Waiting for browser cleanup` followed by `Cleanup timed out or failed:
   TimeoutError:`.
2. **The kill was behind the graceful close.** Inside the cleanup routine the process kill sat
   *after* the CDP `Browser.close` and `browser.close()`. When the routine died inside its own
   15 s budget, the kill never ran — and the `except` branch reset `_chrome_process` and
   `_chrome_running`, so the controller believed there was no browser any more. Nothing came back
   for it: the next run takes a different port, the reclaim pass refuses a profile outside
   `user_data_runs/`, and `leaked_browser_ports` only scans the 9300+ run range. The comment in
   that branch — an orphan is left for "the next connect" to handle — is wrong on this fleet.

**What changed.**

- **The run's end takes its own browser down, without the loop.** The executor's run end (and the
  abort path) now call a run-scoped reclaim: it finds the browser by the run's **own profile
  directory** (`user_data_runs/<run id>`), checks that no **live** run owns its port, and signals
  it by pid. Individual positive pids only — never a process group.
- **The cleanup reaches its kill even when the graceful close hangs.** The kill moved ahead of the
  graceful steps, and the timeout branch kills the browser as well: the guarantee no longer sits
  behind a step that can hang.
- **The reports say what happened.** The run's log distinguishes *closed normally*, *taken down by
  pid*, *already gone*, *left open* and *NOT reaped* — with the reason, verbatim. A browser nobody was allowed
  to signal is never reported as reclaimed, and `close_browser` no longer reports success for a
  browser that is still running: the `close_browser` command waits for the cleanup and answers
  with the browser's real state.

**Scope, deliberately.** The teardown only ever reaches a profile under the allocator's per-run
root, so the host's persistent service browser (the profile next door, outside `user_data_runs/`)
is out of reach by construction; a browser a live run is driving is left alone; a run that took no
browser slot pays nothing for the teardown.

**Two host switches decide whether the browser dies with the run.** A reader of this tracker has
to know both, because both can turn the fix off on a host:

| switch | what the operator asked for | what the run does | what the run reports |
|---|---|---|---|
| `VPT_KEEP_BROWSER_OPEN` (true-ish) | the browser to live — a documented, host-level opt-out for debugging or a sequence that wants the browser warm | the run-scoped teardown **leaves the browser alone**; the run's own close is skipped too | *left open because VPT_KEEP_BROWSER_OPEN is set*, with the pid — a deliberate outcome, never a silent skip |
| `VPT_REAP_LEAKED_BROWSERS=0` | no browser to be killed on that host at all | the run-scoped teardown refuses: a run's own browser belongs to no live run the moment the run ends, so the plain reading of the switch covers it | *NOT reaped - reaping is disabled by VPT_REAP_LEAKED_BROWSERS* |

Neither switch is set anywhere in the fleet today (0 occurrences in the `.env` of `host-clone-2`,
`vpt-pi1`, `vpt-pi4`, `vpt-mf1` and `labox-backend`; in the repo it exists only as a commented
example line), so this changes nothing in production and keeps both switches meaningful.

**On a host with `VPT_REAP_LEAKED_BROWSERS=0` the leak comes back — by the operator's own choice.**
That is the switch's meaning, not a defect: it is the escape hatch for a host where no browser may
be killed. The same is true of `VPT_KEEP_BROWSER_OPEN`, which asks for one browser to outlive its
run. Everything else on this page describes the default behaviour, which is the one the fleet runs.

Cleaning the nine dead browsers is a separate, immediate action: they are orphans by the
platform's own accounting (`running: 0`), and killing them frees ~2 GB. That treats the symptom;
the two items above are the fix.

> **Do not clean them up by signalling the Chromium process *group*.** Tried on
> `host-clone-2` 2026-10-22 and it took the host's SSH down with it. `kill -TERM -<pgid>` is only
> safe when that group is known to contain nothing but the browser's own tree, and reading
> `pgid` off the target pid does not establish that: the signalled group took the sshd session
> too, and sshd did not come back. Signal the **specific process tree** instead — the browser pid
> and its own descendants, matched on `--user-data-dir` under `config/user_data_runs/<run id>` —
> and check the list before signalling anything. Verify the run is gone first: no process holds
> the run's port and the host reports `running: 0` for it.

## Verification

Covered by `tests/backend_host/test_browser_run_leaks.py`:

- `browser_runs.leaked` on the host equals the number of live Chromium listeners on the run
  ports that no live run owns;
- with a leaked browser in place and a cap of N, a new run is refused or waits, and the message
  names the leak instead of saying the host is busy;
- `running + leaked >= cap` is the rule that admits a run — with `leaked: 0` the behaviour is
  exactly what it was before.

Verified on the deployed host, `host-clone-2`, build `main-2026.10.22-89622` (deploy
`a305d904`), 2026-10-22. The host was clean at the time — 0 listeners on the run ports, 1
Chromium that owns none of them — so `leaked` correctly reads 0 and the false-positive check
matters: the single unrelated Chromium is not counted.

```
$ python -c "from shared.src.lib.utils.browser_run_slots import browser_run_status, leaked_browser_ports; ..."
browser_run_status: {'running': 0, 'waiting': 0, 'leaked': 0, 'cap': 4}
leaked ports: ()
host stats browser_runs: {'running': 0, 'waiting': 0, 'leaked': 0, 'cap': 4}
```

The gate itself, probed in-process on that build with the leak count stubbed (the pool is
in-memory and writes nothing, so this left no state on the host and started no browser):

```
leaked=2 -> {'ok': True,  'running': 1, 'leaked': 2, 'cap': 4, 'waited': 0}
leaked=5 -> {'ok': False, 'running': 0, 'leaked': 5, 'cap': 4, 'waited': 600,
             'error': 'host carries 5 browser(s) left over from finished runs, plus 0 running (limit 4)'}
leaked_browser_count co_names: ()
```

The last line is the load-bearing one: the measurement's code object names no function at all,
so it cannot be reaching for a kill. That is the same property the unit test asserts.

### Part 1 — the reclaim pass, live on `host-clone-2` (build `main-2026.10.22-89676`)

The cap could see the leaks but nothing cleared them, so a host that filled stayed wedged. The
reclaim pass runs **only when a run is already waiting for a slot**, so a healthy host never pays
for it. It signals **individual positive pids** matched from `/proc`; it never signals a process
group.

Two defects were found by testing against the real host, not by the unit tests, and both had to be
fixed before the pass was trustworthy:

1. `default_run_profile_root()` counted `dirname` levels and landed on `<root>/shared`, producing
   `shared/backend_host/config/user_data_runs`. No real browser carries that path, so the profile
   guard answered False for *every* genuine leak: the pass would have skipped all of them while
   looking like it worked. It now walks up to the directory that actually holds
   `backend_host/config`.
2. `browser_pid_for_port()` searched the whole command line as a **string**. An
   `ssh 'python -c "..."'` wrapper carries its whole script in one argv entry, so the entry
   *contains* `--remote-debugging-port=9397` while the wrapper is not the browser holding that port.
   The guard then refused it — right answer, wrong reason — and had that wrapper carried a
   run-scoped path, the pass would have signalled somebody's shell. The flag must now be an actual
   **argv entry**, on a process that looks like a browser.

Verified on the deployed host, 2026-10-22:

- discovery finds the **real** Chromium of a running Tetris job on port 9300 (pid 399915) and
  reads its run-scoped profile from argv;
- that browser's run is **alive**, so the pass leaves it alone — `leaked: 0`, no signal. This is
  the property that matters most, shown on a real browser in a real run;
- a browser-shaped process on a run-scoped profile **is** taken down: signalled `[413193]`,
  killed `[413193]`, gone;
- a profile outside `user_data_runs` is refused (the host's own display browser is off limits);
- `reap_browser_count().__code__.co_names` is empty, so the measurement cannot be reaching for a
  kill — asserted at the bytecode level, because the alternative cost this host its SSH.

**Not verified live:** the full production sequence — a real run dying and leaving a real Chromium
for the pass to reclaim. Every step was exercised separately; the one thing not observed is a real
leak being cleaned by a real waiting run. Manufacturing one on a shared host was refused: it would
have wedged that host's cap for every other agent.

Still to be added when part 1 lands:

- a scheduled browser run ends and leaves **no** listener on its port, checked after N runs;
- a host carrying leaked browsers says so on the card, so the user sees the load the count misses.

### Part 1 — the run's end kills the browser it launched (E68)

Covered by `tests/backend_host/test_run_end_browser_teardown.py`, which drives the **real** end of a
run (the executor's subprocess path) with a **real** process that looks like a browser in `/proc`,
so the assertions are about a process being alive or dead:

- a run whose own cleanup failed (the wedged-loop case) still ends with **no** browser alive, and
  the log says *taken down by pid*;
- a run whose own cleanup worked is left alone: nothing is signalled and the log says *closed
  normally*;
- a browser nobody is allowed to signal is reported as **NOT reaped**, with the reason, and is
  never reported as reclaimed;
- the host's persistent service browser (the profile next door) and the browser of another live
  run are **not** signalled;
- a run that took no browser slot grows no teardown;
- an **aborted** run leaves no browser behind either (Chrome is launched in its own session, so
  the abort's tree kill could never reach it);
- the `close_browser` command does not report success for a browser that is still running;
- with `VPT_KEEP_BROWSER_OPEN` set, the browser is **left open** and the run says so, with the pid
  — the operator's explicit opt-out is honoured, not silently overridden.

Every one of these tests fails on the pre-fix commit (`b22f63469`) on a behavioural assertion —
the browser outlived the run there — and passes on the branch.

**Not verified live:** the production sequence on a real host (a real hourly run ending and its
real Chromium being taken down by the run's own end). Manufacturing a real leak on a shared host
was refused before and still is; the sequence is exercised end to end in the test instead.