# BUG-0860 — the shared profile validator refused ANY stat row, so the egg line's profile was unusable on the host

**Found** 2026-10-23, on `vpt-lenovo1`, when the monitor logged
`profile 'egg_quality_yolo' is unusable (ui.stats is ...); its devices count as tv_app`.

## What was wrong

There are two validators for a monitor profile:

- `backend_host/scripts/monitor/profiles.py` — the pydantic model the host's monitor loads, and
- `shared/src/lib/utils/monitor_profile.py` — `validate_manifest_light`, the one the host uses to
  decide **which services a device gets** (and the one the server's profile routes use).

They disagreed about `ui.stats`. The pydantic model accepted a stat that reads a KPI
(`{label: Eggs, kpi: count_total}`) and a stat that reads the observation count
(`{label: Detections, observations: true}`). The shared validator demanded that `observations` be a
bool on **every** stat:

```python
or isinstance(s.get('observations'), bool) is False
```

A stat that reads a KPI has no `observations` key at all, so `s.get('observations')` is `None`,
`isinstance(None, bool)` is `False`, and the check fired on **every** stat row. The message it
raised (`ui.stats is [{label, kpi: <plain kpi>} | {label, observations: true}]`) says what the row is
SUPPOSED to look like — the condition was simply the wrong way round for the KPI case.

So the profile that BUG-0848 shipped (`egg_quality_yolo`, with the `Eggs` / `Detections` row) was
**unusable** as far as the host's service decision was concerned, and the device fell back to
`tv_app`. The stat row the owner was given for that work was never actually a valid profile on the
host that runs it.

## Fix

```python
or ('observations' in s and not isinstance(s['observations'], bool))
```

The key is only checked when it is there. A stat with `observations: 'yes'` is still refused, a stat
with both `kpi` and `observations` is still refused, a stat with neither is still refused, and an
unknown key is still refused — the four bad shapes stay bad.

## Verification

- `tests/backend_host/test_yolo_seg_detect.py` — the shipped `egg_quality_yolo` profile passes the
  shared validator, and four broken shapes are still refused by it.
- Live on `vpt-lenovo1`: the monitor starts with **no** "profile is unusable" line, and capture3
  reports `Monitor profile: egg_quality_yolo` with the `ui.stats` row intact
  (`Eggs` / `Detections`).
