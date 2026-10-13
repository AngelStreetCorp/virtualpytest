# BUG-0181 — A gateway correction overwrote device info on the device-information dashboard

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0181                                                     |
| Reported  | 2026-09-28                                                   |
| Status    | Fixed (pending Grafana re-import)                            |
| Severity  | Medium                                                       |
| Area      | grafana / device info                                        |
| Fixed in  | Unreleased                                                   |
| Commit    | `6139cee95`                                                  |

---

## Symptom

On the `device-information-get-info` Grafana dashboard, a value corrected on the **Gateway** tab of
the Device Info editor could appear as the **device**'s value — silently, and only on the
dashboard. The Device Info page itself, and the info embedded in the hosts listing, were correct.

Only keys that both info families use are affected. `serial_number` is the one the schema calls
out explicitly; any key present in both a device's `metadata->'info'` and its `gw_info` metadata
behaves the same way.

## Root cause

`device_info_overrides` serves both families, discriminated by `info_source` (`'device'` |
`'gateway'`), which is part of its unique key precisely because the two share keys
(`035_device_info_overrides.sql`).

`device_info_corrected` filters on it (`WHERE info_source = 'device'`). The dashboard does not
read that view — all five overlay panels ("Latest Device Info", "STB TV", "STB Android Mobile",
"IAD GUI", "STB Android TV") hand-roll the merge in SQL:

```sql
LEFT JOIN LATERAL (
  SELECT (sr.metadata->'info') || COALESCE(jsonb_object_agg(o.info_key, to_jsonb(o.corrected_value)), '{}'::jsonb) AS info
  FROM device_info_overrides o
  WHERE o.team_id = sr.team_id AND o.device_name = sr.device_name AND o.host_name = sr.host_name
    AND o.userinterface_name IS NOT DISTINCT FROM COALESCE(sr.userinterface_name, '')
) ci ON true
```

`AND o.info_source = 'device'` is missing, so `jsonb_object_agg` folds in the gateway rows too.
The duplication is what allowed the drift: the view was written with the filter, the copy never
had it. The gateway discriminator was added in `20260527_a_gateway_info_overrides.sql`; the
dashboard's LATERAL predates it and was never updated.

## Fix

Added `AND o.info_source = 'device'` to all five panels.

The panels were **not** repointed at `device_info_corrected`, which would have made the class of
bug impossible: they show the latest scan *within the dashboard's time range* under the
`success` / UI / flag template variables, and the view is unconditional-latest, all-time. The
duplication stays; `docs/agent/devices/DEVICE_INFO_CORRECTION.md` now records why, and that the
copy must carry the discriminator.

## Verification

All five `rawSql` blocks re-parsed from the dashboard JSON and asserted to contain the filter; the
JSON re-validates. Not reproduced against live data — the lab DB has two overrides, both
`info_source = 'device'`, so it has never been exposed to this.

**Deploy:** re-import `infra/monitoring/grafana/dashboards/device-information-get-info.json` into
Grafana; no deploy script does this.
