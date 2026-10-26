# BUG-0788 — Analytics shows two different "open incidents" numbers on its Overview and Incidents tabs, for minutes at a time

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0788                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend                                                      |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-17, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /monitoring/analytics (Overview and Incidents tabs)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open Monitoring > Analytics and read "Open incidents" on Overview.
2. Click Incidents and read "still open".
3. Repeat for a few minutes.

**Expected:** One number, or a label that says how old it is.

**Actual:** Overview read 209 then 212 while Incidents kept reading 206 for 2 min 50 s before catching up (samples in `ops-17-open-incidents-drift.txt`). The ANALYST persona saw 212 vs 204 eight minutes apart and judged it live data, not a bug; the OPS drift table shows the same figure, computed once (`shared/src/lib/database/analytics_db.py:197`), served with different cache lifetimes (`server_analytics_routes.py:41-48`: overview fresh 30 s / stale 600 s, incidents fresh 300 s / stale 3600 s), with no age shown on either tile.

Evidence:

- [ops-17-open-incidents-two-numbers.png](../tasks/qa-evidence/ops/ops-17-open-incidents-two-numbers.png)
- [ops-17-open-incidents-drift.txt](../tasks/qa-evidence/ops/ops-17-open-incidents-drift.txt)

## Root cause

One metric, two copies, two clocks.

- The figure is `get_incidents_section()['open']` — `analytics_db.py:197`.
- The **Incidents tab** serves the `incidents` section: one cache entry, fresh for 300 s, servable stale for an hour.
- The **Overview tab** serves the `overview` section, whose loader called `get_incidents_section(days=14)` **itself** — a second copy, recomputed on the overview's own 30 s clock.

So the Overview tile was never stale: it recomputed the figure every ~21 s, while the Incidents tab kept serving an entry that was minutes old. The QA's own sample shows it exactly — the Overview entry is recomputed every 21 s, the Incidents entry only when its 300 s window expires:

```
  t(s) overview_open  incidents_open  age_ov  age_inc  match
    0           209             206     0.3    143.1  *** MISMATCH ***
   84           212             206     0.5    226.5  *** MISMATCH ***
  168           212             206     0.3      0.2  *** MISMATCH ***   <- incidents cache recomputed here
  188           212             212    21.1     20.9  OK
```

(`open` does not depend on the `days` window — it counts the rows whose status is `open`/`in_progress` over all rows — so the two copies really were the same metric.)

The second half of the complaint — "no age shown on either tile" — came from the envelope: `generated_at` is the time the **response** was written, not the time the **data** was computed, so a client had no way to tell how old the number was.

## Fix

One metric, one cache entry, one number.

- `backend_server/src/routes/server_analytics_routes.py` — the Overview loader (`_overview_loader`) reads the incidents section from the **incidents cache** and hands it to `get_overview_section()`, instead of letting the Overview compute its own copy.
- `shared/src/lib/database/analytics_db.py` — `get_overview_section()` takes the incidents section as an argument (`incidents=`), so the Overview payload is built from the figure the cache holds.
- `backend_server/src/routes/server_analytics_routes.py` — and because the Overview payload is cached on its own clock, the route reads the figure from the incidents cache **at request time** and puts that value in `tiles.incidents_open`. So the tile is not even one pre-warm pass behind the Incidents tab: the two are the same value, read at the same moment.

The cost does not change: the Overview no longer reads the incidents rows itself, and the incidents entry was already recomputed every 30 s by the pre-warm loop.

## Verification

Tests (`tests/backend_server/test_analytics.py`, 3 new cases):

- `test_overview_reads_the_incidents_figure_it_is_given` — the Overview tile carries the figure the caller hands it.
- `test_the_overview_loader_takes_the_figure_from_the_incidents_cache` — the loader asks the cache for `incidents` and nothing else.
- `test_the_overview_response_carries_the_incidents_cache_figure` — the route's response for `overview` carries the incidents cache's value even when the cached Overview payload holds an older one (999 → 42).

All three fail against the pre-fix sources.

Live check after the deploy (`scripts/agent/analytics_incident_drift.py`, the same sampler the QA used, reading `tiles.incidents_open` and `open` plus the age of each cache entry):

| | before | after |
|---|---|---|
| Overview "Open incidents" | 209 → 212, recomputed every ~21 s | the incidents entry's value |
| Incidents "still open" | 206, up to 2 min 50 s old | the same value |

The sampler prints one line per sample with both numbers and both cache ages, so a mismatch is visible the moment it happens.

**After the deploy** (build main-2026.10.22-89636) the live app was sampled for 280 s: **both tabs read 213 in every one of the 15 samples, and the two cache entries carry the same age in every sample** — they are one entry now, read by both tabs. Before the fix the same sampler showed 209 vs 206 and then 212 vs 206 for 2 min 50 s.

Re-checked after the deploys that followed: a fresh 15-sample run over 280 s reads **216 in every sample** on both tabs, with the two cache ages equal in every sample.

Sample: [bug-0788-open-incidents-drift-after.txt](../../tasks/qa-evidence/fix/bug-0788-open-incidents-drift-after.txt) · [re-check](../../tasks/qa-evidence/fix/bug-0788-open-incidents-drift-recheck.txt).
