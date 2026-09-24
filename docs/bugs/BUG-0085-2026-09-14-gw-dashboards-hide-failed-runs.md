# BUG-0085 — Ookla, Superping and DNS dashboards never showed a failed run

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0085                                                                    |
| Reported  | 2026-09-14 (customer report: the Ookla speedtest dashboard shows no failing result) |
| Status    | Fixed (pushed to our Grafana; ships to customers with the next bundle)      |
| Severity  | Medium (a failing gateway test was invisible on the dashboard built to show it) |
| Area      | infra/monitoring/grafana/dashboards/ookla-speedtest.json · superping.json · dns-lookup.json |
| Fixed in  | build 8887                                                                  |
| Commit    | `43d5293faf`                                                                |

---

## Symptom

A customer runs `ookla_speedtest` on a schedule and opened the **Ookla Speedtest** dashboard to
look at the runs that failed. The **Nr. of failed test** counter in the top row went up, but:

- with the PASS/FAIL selector on **FAIL**, the `[TC014] Ookla Report` table and every
  time-series panel were empty ("No data");
- with the selector on **All**, the table listed only the passing runs — the failures were
  simply missing, with nothing to say a run had been skipped.

So there was no way, from the dashboard, to see *when* a speedtest failed or *why*.

The same behaviour existed on the two sibling gateway dashboards: **Superping Network Quality**
(`Recent Tests - Detailed Data`) and **DNS Lookup Time** (`Latest DNS Lookups`,
`DNS Lookup History (Last 100)`).

## Root cause

Every panel of the three dashboards filters on the selector:

```sql
AND success::text = ANY(string_to_array('${success:csv}', ','))
```

but all of them except the first counter *also* hardcode, on the next line:

```sql
AND success = true
```

Both conditions are ANDed, so the selector could only ever narrow the passing set. Selecting
FAIL produced `success IN (false) AND success = true`, which matches nothing.

For the averages stat and the time-series panels the hardcoded filter is actually right — a
failed run stores no `download_mbps` / `rtt_avg_ms` / `lookup_time_ms`, so there is nothing to
average or plot. For the **detail tables** it is a defect: those are the one place a failed row
belongs. On top of that, the tables did not select `error_msg`, so even without the filter a
failed row would have rendered as a timestamp followed by blank cells.

Verified on the live database (`.102`): `script_results` held 4455 passing and 7 failed
`ookla_speedtest` rows, every failed one with an `error_msg`
("No network interface with internet connectivity found") and no speed metrics in `metadata`.
The DNS dashboard was hiding a run of 100 consecutive failures on a host.

## Fix

`43d5293faf` — dashboard JSON only, no code and no DB migration.

In the four detail tables:

- removed the hardcoded `AND success = true`, leaving the PASS/FAIL selector in charge;
- added a **Status** column (`CASE WHEN success THEN 'PASS' ELSE 'FAIL' END`) with a
  green/red value mapping, on the Ookla and both DNS tables (Superping already had a ✓/✗
  `Success` column);
- added an **Error** column reading `error_msg`, so a FAIL row explains itself;
- Ookla only: the `Ookla Server` label is `NULLIF(CONCAT(...), ' ()')` so a failed row shows an
  empty cell instead of a stray ` ()`.

The averages stat and the time-series panels keep their passing-only filter on purpose.

## Customer overlay (added the same day)

The customer overlay carries its own copies of these three dashboards at the **same path**
(`infra/monitoring/grafana/dashboards/ookla-speedtest.json` and the two siblings), and the
overlay is rsynced on top of the platform tree at deploy — so the platform fix above never
reaches a customer install on its own. The overlay copies had the identical hardcoded filter; the
same table-only fix was applied there in the overlay repo and ships with
the next bundle.

The customer's live export of the Ookla dashboard (Grafana version 54) also turned out to be
one overlay commit behind (no `environment` filter, HGW variables still scanning
`script_results` instead of `gw_info_values`) and to carry a corrupted line in the averages
stat (`AND {server:csv}' = ''`, a syntax error that blanks that panel). A minimal hot-patch of
that live export — the table fix plus the repaired line, nothing else — was handed over for
import until the next bundle.

## Second root cause, found on the customer DB the same day

After the table fix was imported on the customer's Grafana, the failed runs were still absent.
Their DB held **885 failed vs 875 passing `ookla_speedtest` rows in 24 h** and the Details
query returned them when run by hand with every filter emptied — but Grafana does not render
"All" as an empty string: a query variable on "All" with no custom all-value expands to the
**full list of its options**. The Ookla *Test Server* options are built from passing runs
(`WHERE metadata->>'server_name' IS NOT NULL`), a failed run stores no server, so

```sql
AND ('${server:csv}' = '' OR metadata->>'server_name' = ANY(string_to_array('${server:csv}', ',')))
```

is `NULL` for every failed row and drops it — from the counter, the table and the series alike.
That is why the customer's counter showed no failures at all. Superping's *Target* filter has
the identical shape (56 of 57 failed pings on the lab DB carry no target). The DNS dashboard
has no metadata-based filter and was not affected. Verified on the lab DB: with the real
option list substituted, the Ookla table returned 0 failed rows before and 3 after.

Fix `0f79d68259` (platform) / overlay `d49af3d`: every occurrence of the two clauses gains
`OR metadata->>'server_name' IS NULL` / `OR metadata->>'target' IS NULL`, the same fallback the
HGW filters already had with `OR gw_x = 'Unknown'`.

**Lesson for validating Grafana SQL by hand:** substitute a variable on "All" with the *real
option list*, never with `''` — the `'' = ''` short-circuit only exists for the case where the
list is empty. See also the custom all-value trap in `docs/agent/` memory
(`reference_grafana_allvalue_bypasses_format`).

## Verification

- The four patched queries were run against the live database with the selector expanded to
  `'true,false'` and the other variables emptied (the same render Grafana produces under
  **All**): all four execute, the DNS tables now return FAIL rows carrying the nslookup error,
  and the Ookla table with the selector set to `'false'` returns the 7 failed runs with their
  `Error` text and empty metric cells.
- The three dashboards were pushed with `_push_dashboard.py` to our Grafana
  (Ookla → version 5, Superping and DNS → version 3); reading the stored Ookla dashboard back
  through the API confirms the new SQL.
- Customer installs run their own Grafana with a copy of these JSON files: the fix reaches them
  with the next bundle, and re-provisioning the three dashboards is the whole deploy step.
