# BUG-0390 — Generated Grafana charts mixed % with counts on one axis and overlapped their x labels

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0390                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | ai-agent                                                     |
| Fixed in  | build 90145 |

## What happened
On a draft built from "pass rate by device, failing test cases and incidents over time": the "Pass Rate by Device" barchart plotted `pass_rate` (%) and `run_count` on one axis whose unit was percent, so 730 runs read "730%" and flattened every pass rate; with 13 devices the x labels overlapped; stat tiles painted counts red (Grafana's default threshold at 80).

## Fix
Display only (`fieldConfig`/`options`), the SQL and its provenance hash are untouched (`GrafanaDraftService._apply_display`):
- every metric column gets its catalog unit as a `byName` override (tables: each column in its own unit, `ms` humanized by Grafana);
- charts plot the primary (first) metric; a supporting metric with a different unit (run_count, sample_count) is hidden from the visualization and legend (`custom.hideFrom.viz/legend`) and stays in the tooltip (`tooltip: multi`);
- a percent chart is fixed to 0-100;
- a barchart over more than 6 categories rotates its labels -45 degrees and truncates them at 18 characters (the category count is unknown at build time, so the preset's `max_categories`/limit decides);
- stat tiles use a neutral blue threshold.
Verified live on a pushed test draft: no query errors, labels readable, "100%" axis, "Mb/s", "2.50 mins".
