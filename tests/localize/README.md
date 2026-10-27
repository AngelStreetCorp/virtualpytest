# `localize` regression harness

A pytest harness that drives `MonitorLocalizer.localize_frame()` over a labeled
set of captures and asserts the per-frame `localize` payload against
expectations. It is the test bed for the operator capture job (item 3 in
`EXPERIMENT-01 §7.1` — the abstains-without-a-capture follow-up)
and the regression gate for the three commits that just landed on `main`:

  - `c3af47fec` — motion gate on the 1 Hz localize tick
  - `aacc08dff` — wire Tier 2 (`screen_state_cv`) into the per-frame payload
  - `861451d29` — userinterface `company` metadata (opt-in brand passthrough)

The harness pins the **payload composition** of `localize_frame()` (gate
decision, Tier-2 merge, `userinterface_company` passthrough, gate-skip
cache behaviour). It deliberately does NOT pin the fingerprint matcher or
the Tier-2 cascade — those have their own test suites, and coupling this
harness to them would mean every matcher regression breaks every payload
regression.

## Run it

```bash
# Default — only runs rows with a reachable real source.
# Synthetic placeholders are SKIPPED.
python3 -m pytest tests/localize/test_localize_regression.py

# Run synthetic rows too (placeholders for frames the operator has not yet
# captured). Synthetic rows generate a 64x64 grey placeholder in tmp_path
# so the per-row assertions still run end-to-end.
RUN_SYNTHETIC=1 python3 -m pytest tests/localize/test_localize_regression.py
```

The default run on a fresh clone, with no real frames reachable, will show
something like `9 passed, 26 skipped` (the 9 are the rows pointing at
captures that happen to be in the local cold pull; the 26 are synthetic).
With `RUN_SYNTHETIC=1`, all 35 rows run.

The end-of-run terminal summary includes a per-field precision/recall line
and a one-line run summary (`passed / failed / skipped_synthetic /
skipped_unreachable / warned_unlisted`).

## Manifest schema

The manifest is `tests/localize/manifest.json`. Schema:

```json
{
  "version": 1,
  "userinterfaces": [
    {"name": "stb-testop", "company": "brand_a"}
  ],
  "rows": [
    {
      "id": "stb_tv_home_static",
      "userinterface": "stb-testop",
      "source": "local:/abs/path/to/frame.jpg",
      "motion": {"kind": "static", "state": "static", "pct": 0.0},
      "expected": {
        "gate_skip": null,
        "node": "home",
        "loaded": "yes",
        "overlay": "none",
        "playback": "not_applicable",
        "error": "none",
        "userinterface_company": "brand_a",
        "confidence": 0.93
      },
      "note": "human-readable description of the scenario"
    }
  ]
}
```

`expected` fields are all **optional** — omit a field when the row is not
asserting on it. The harness treats absent as "don't care, but warn if a
value comes through that the manifest didn't list" so adding a new field
to `localize_frame()`'s payload does not break older rows; it just goes
un-asserted until a manifest row is added.

The trackable fields are: `node`, `gate_skip`, `confidence`,
`userinterface_company`, `loaded`, `overlay`, `playback`, `error`. Any
other key in `expected` is asserted on but does not contribute to the
per-field PR summary.

### `source` schemes

  - `"local:/abs/path/to/frame.jpg"` — read from a local file. The harness
    skips (with a warning) if the file does not exist. Pi hosts are not
    always on, so the harness must stay green on a missing source.

  - `"ssh://<host>:/abs/path/to/frame.jpg"` — the operator-side form
    pointing at the cold archive. The harness cannot resolve remote
    paths from this machine (no infra-connect plumbing here), so it
    skips with a warning. The harness is intended to run on the Pi's
    local copy of the repo, or on a machine where the cold archive is
    already pulled — the operator's job (item 3 in EXPERIMENT-01 §7.1)
    is to plumb the pulls so the harness sees the frames as
    `local:` paths.

  - `"synthetic"` — the harness generates a 64x64 grey placeholder in
    `tmp_path` and asserts the row's expected against it. Useful for
    scenarios the operator has not yet captured (error dialogs on
    Switch, the broadcast bugelogo detector, etc.). The placeholder is
    opt-in: synthetic rows are SKIPPED unless `RUN_SYNTHETIC=1` is set.

## How the harness works

  1. Load the manifest. Build one pytest test function per row.
  2. For each row:
     - Resolve the source path. If unreachable, log a warning and skip.
     - If `source == "synthetic"`, generate a placeholder JPEG in `tmp_path`.
     - Mock `scv.screen_state` and `scv.error` to return the row's expected
       Tier-2 values (the harness pins the merge, not the cascade).
     - Mock `_load_node_fps` and `_get_helpers` to inject a tiny
       `node_fps` set + a fake `identify_screen` so the harness can run
       without a real DB and without `DEVICE{N}_USERINTERFACE` env vars.
       Mirrors the fake pattern in
       `tests/backend_host/test_userinterface_company_passthrough.py`.
     - Prime the userinterface metadata cache so the per-frame payload
       carries (or omits) `userinterface_company` per the row's expected.
     - If the row expects `gate_skip`, pre-prime `_last_match` by issuing
       one `localize_frame` call with static motion first, then re-issue
       with the row's actual motion to exercise the gate-skip branch.
     - Call `localize_frame(device_id, frame_path, motion=...)` and assert
       every field in the row's `expected` against the payload.
     - Record TP/FP/FN per (field, value) pair for the PR summary.
     - Warn if a trackable field came through the payload but the row's
       `expected` did not list it (the row is now silent on a live field).

The end-of-run summary (added by the `conftest.py` hook) prints
per-field P/R/F1 and the run totals, so a future classifier regression
shows up as a TP/FP shift on the relevant field.

## Adding a row

Six lines is the typical case:

```json
{
  "id": "my_new_scenario",
  "userinterface": "stb-testop",
  "source": "local:/path/to/frame.jpg",
  "motion": {"kind": "static", "state": "static", "pct": 0.0},
  "expected": {"node": "home", "loaded": "yes", "overlay": "none",
               "playback": "not_applicable", "error": "none",
               "userinterface_company": "brand_a", "confidence": 0.93},
  "note": "what this row pins and why"
}
```

Rules of thumb:

  - Pin `confidence` whenever you pin `node` (the fake matcher returns
    `0.93` on a match, `0.0` on an abstain). A row that doesn't pin
    `confidence` will trigger the "unlisted field" warning at run time
    because the payload carries the matcher's confidence verbatim.
  - Pin `gate_skip` to `null` (gate open, fresh matcher run) or to
    `"live"` / `"motion"` (gate fired, payload is the cached verdict).
    The harness pre-primes the cache automatically when `gate_skip` is
    non-null.
  - Use `brand_a` / `brand_b` / `brand_c` for the company label (the
    AGENTS.md leak-gate rule). Public brand names like `apps_netflix`
    go in the `note` field only when they describe a known app-grid
    node.
  - If you don't have a real frame yet, use `"source": "synthetic"`.
    The row will be skipped on a default run and exercised on
    `RUN_SYNTHETIC=1`.

## File layout

  - `manifest.json` — the labeled set. One row per test scenario.
  - `test_localize_regression.py` — the harness. Loads the manifest,
    builds one test per row, runs them, records PR.
  - `conftest.py` — pytest hooks. `pytest_terminal_summary` emits the
    per-field P/R/F1 and the run summary at the end of the run. The
    hook MUST live in `conftest.py` (pytest does not auto-discover
    hooks in test files).
  - `manifest_real_match.json` — the 11-row real-classifier set
    (EXPERIMENT-01 §1.2: 3 broadcast promos and 1 black-frame
    excluded — broadcast = `playback`'s job, black = capture-side).
  - `test_localize_real_match.py` — the real-classifier harness.
    Runs ONLY when `RUN_REAL_MATCHER=1` is set. Calls the REAL
    `ImageHelpers.identify_screen` + REAL `scv.screen_state` +
    REAL `scv.error` against the 11 rows, with stub node_fps loaded
    from `fixtures/<userinterface>_node_fps.json`. Skips individual
    rows whose source path is unreachable or whose frame is capture-
    side black (mean<15 AND std<12). Catches Tier-2 / ImageHelpers
    drift that the mock harness cannot surface.
  - `fixtures/<userinterface>_node_fps.json` — per-userinterface
    stub node fingerprint sets (the v6 shape: dhash + regions +
    focus + title + text). Loaded into `_load_node_fps()` instead
    of the DB. Stub values are intentional — the test pins payload
    plumbing, not matcher quality.
  - `results/real_match_11.json` — the per-frame diff written at
    session-finish time. Diff against this in future runs to catch
    Tier-2 regressions on real frames.

## Real-classifier test (`RUN_REAL_MATCHER=1`)

The mock harness is fakes-only: `_load_node_fps` is replaced, the
Tier-2 cascade is stubbed, the matcher returns a fake result. That
pins the payload composition but it cannot catch a Tier-2 field
that fails silently in production or an `ImageHelpers` / `scv`
integration drift (the mock harness never builds `ImageHelpers`).

The real-classifier harness is the complement: it runs the REAL
`ImageHelpers.identify_screen` + REAL `scv.screen_state` + REAL
`scv.error` against real frames, with stub node_fps loaded from
`fixtures/`. Runs ONLY when the operator opts in:

```bash
# Real signal — what the classifier actually does on real frames.
RUN_REAL_MATCHER=1 python3 -m pytest tests/localize/test_localize_real_match.py
```

A default run (no `RUN_REAL_MATCHER=1`) skips the whole file with a
one-line message. The 11 rows follow the EXPERIMENT-01 §1.2 set:
Switch HOME (frozen + focused), game title, 4 in-game cutscenes, 2
error dialogs, 2048 web game, Android quick-settings shade. Unreachable
rows skip with a warning; capture-side black frames skip with a
different warning (`mean<15 AND std<12` — uniform dark, not just
"low mean"; the Android quick-settings shade and the 2048 web game
both have low mean but high std, so they pass the pre-check). The
per-frame diff lands in `results/real_match_11.json` so a future
run can diff against it.
