# Matcher history dashboard — operator walkthrough

`/match-runs` (under **Monitoring** in the top nav) is the dedicated
matcher history + fingerprint counter + auto-classify dashboard.
Built on top of the `match_runs` and `screen_fingerprints` tables; the
underlying data layer is shared with the Grafana dashboard
`/d/fingerprints` and the live monitor (`vpt-monitor-img` → queue →
worker → `match_runs`).

## Panels

1. **Status strip** — six tiles: total runs, match rate, uncertain
   (margin < 5%), unknown / low conf, active devices, avg confidence.
   `1h / 6h / 24h / 7d` window toggle.  Auto-refreshes every 10 s.
2. **Verdict distribution** — stacked bar over hourly buckets,
   one series per verdict.  Click a window to widen the bars.
3. **Per-device matchers** — one row per (host, device).  Each row
   has a per-cell heatmap of recent matches (green = matched, red =
   missed).  Click a row to load that device's sequence replay below.
4. **Uncertain hits backlog** — top 20 from `v_uncertain_hits` sorted
   by margin asc.  Open the frame link to see the actual screen.
5. **Sequence replay** — pick a device + UI, get the last 20 events
   for that chain (top-3 candidates + margin per event).

## What "is the matcher healthy right now" looks like

- Match rate ≥ 80 %: tiles green; verdict distribution shows mostly
  green (`known_node`) bars.
- Uncertain rate (margin < 5 %) < 5 %: tight matches are rare; the
  backlog stays empty.
- Unknown / low conf < 5 %: the matcher confidently lands on a node
  most of the time.
- Active devices matches `v_node_transitions` distinct hosts: the
  monitor is writing.

If any of these flip red, check the Grafana dashboard
`/d/fingerprints` for the cross-fleet view (per-profile, transitions
heat-map, auto-classify backlog, last-classify-run stat).

## Rate limiting

The four new endpoints are rate-limited per team, per minute.
Defaults: 60 rpm on `summary` / `sequence` / `recent`; 30 rpm on
`per_device` / `distribution`.  When the limit is hit, the endpoint
returns `429` with `Retry-After` and the operator's panel keeps the
prior data on screen (stale-while-revalidate).

Override per endpoint via env on the vpt-server:

```bash
MATCH_RUNS_RATE_BUDGET_SUMMARY=120
MATCH_RUNS_RATE_BUDGET_PER_DEVICE=60
```

Set to `0` to disable.  Monitor the live counters at:

```
GET /server/match-runs/metrics?team_id=<UUID>
```

Returns:

```json
{
  "by_endpoint": {
    "summary":     {"this_minute": 12, "denied_total": 0},
    "per_device":  {"this_minute": 8,  "denied_total": 3},
    "distribution": {"this_minute": 6,  "denied_total": 0}
  },
  "window_started_at": 1737001200,
  "team_id": "7fdeb4bb-..."
}
```

## Dedupe (monitor path)

If a vpt-host restarts between BRPOP and the next LPUSH, the same
`monitor_localize` row can be pushed twice.  The BUG-0571 dedupe
index `(team_id, profile, started_at) WHERE profile IS NOT NULL`
catches it; the worker logs `[BUG-0571] dedupe hit on profile=…` and
moves on.  The verify / localize_button / localize_check sources are
out of scope (their `profile` is NULL, so the index ignores them).

## Smoke

```bash
scripts/smoke_match_runs_dashboard.sh
```

Runs the 9 sections in <60 s.  Sections 1-4 probe the four new
endpoints; section 5 checks the Grafana JSON shape; section 6
verifies the live vpt-frontend dist; section 7 confirms the new
routes return the expected keys; section 8 probes the public URL;
section 9 reads the rate-limit metrics.  All 9 should be PASS.

The smoke uses `VPT_API_KEY` from the env (falls back to the live
dev value).  To rotate: edit `.env` and re-run.

## Related Grafana panels (`/d/fingerprints`)

- Per-profile activity — bar chart, one bar per `profile`, stacked by
  verdict.  "Are all my matcher profiles still healthy?"
- Auto-classify backlog — top 50 unknowns with `seen_count ≥ 5` and
  `classification_attempts < 3`.  What will auto-classify pick up
  tonight?
- Top transitions (panel 12) — `from_node × to_node` grid, cell
  colour = log(occurrences).  The prediction input.
- Auto-classify last run (panel 13) — stat, the wall-clock of the
  last successful classify.  If older than 24 h the nightly timer
  did not run.
