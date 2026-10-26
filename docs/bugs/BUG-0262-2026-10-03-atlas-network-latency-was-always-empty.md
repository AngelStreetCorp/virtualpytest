# BUG-0262 — Atlas network charts showed no latency and mixed Ookla, DNS and Superping results

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0262                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — wrong/empty values, no crash                           |
| Area      | `backend_server/src/lib/analytics/catalog.py` (network sources) |
| Fixed in  | build 90145 |
| Commit    | `8ee5bd2bc`                                                       |

---

## Symptom

`avg_latency_ms` of the `network_tests` source was always empty, and its success rate and
counts blended every script stored in `script_results`, not only the network tests.

## Root cause

The metric read `metadata->>'latency_ms'` / `'response_time_ms'`, keys no network script
writes (Ookla writes `ping_latency_ms`, DNS `lookup_time_ms`, Superping `rtt_avg_ms`), and the
source had no predicate restricting it to the network scripts.

## Fix

`network_tests` is replaced by three sources that match their dashboards: `ookla_speedtest`,
`dns_lookup` and `superping`, each restricted to its script and reading the keys its dashboard
reads, with the same gateway enrichment (newest scoped gateway info of the host).

## Verification

- `test_network_families_read_the_keys_their_scripts_write`.
- Parity cases `ookla_averages`, `dns_lookup_times` and `superping_quality` match the
  maintained panels exactly (`tests/backend_server/test_atlas_analytics_parity.py`).
