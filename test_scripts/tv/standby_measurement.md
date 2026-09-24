# standby_measurement

Measures the **standby → live wake KPI** (how long the STB takes to show live TV again after being woken from standby) for a configurable standby mode and a configurable dwell time in standby.

It is a focused sibling of [`kpi_measurement.py`](../kpi_measurement.md): instead of resolving an edge from the RunTests dropdown and pairing forward/reverse, it drives a fixed power-cycle and **reuses kpi_measurement's DB-fetch + reporting helpers** (`_fetch_kpi_results_from_db`, `_is_kpi_skip`, `_append_direction_metrics`) so the output looks identical and the KPI plumbing is not forked.

The script never times anything itself — the timing is produced by the standard KPI pipeline (`vpt-kpi.service` / `kpi_executor.py`, see [docs/agent/execution/KPI.md](../../docs/agent/execution/KPI.md)) when the `standby → live` edge is traversed.

## Usage

```bash
python test_scripts/tv/standby_measurement.py example_tv \
  --standby_mode_node settings_system_standby_eco --edge "live → standby" \
  --wait 1 --iterations 5 --device device4
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_tv` | UI interface name |
| `--variant` | string | _empty_ | Optional named variant; empty = base |
| `--standby_mode_node` | node | _empty_ | Optional node to select the standby mode in Settings. RunTests lists navigation nodes; its friendly `display_name` is shown when configured. |
| `--edge` | action-set label | _required_ | Select the `live → standby` action set. The script derives and measures the reverse `standby → live` action set. |
| `--wait` | int | `1` | Minutes to dwell in standby before waking |
| `--iterations` | int | `3` | Number of wake measurements to take |

`--standby_mode_node` is optional. Its node list is loaded for the selected user interface and variant. `--edge` is required and uses the edge selector; it offers the live-to-standby direction, while the measured wake direction is derived by the script.

## Display names: standby mode and edge

There are two different names involved in this run:

1. **Standby mode node display name** — set the selected Settings node's `display_name` in the navigation node editor. For example, if `settings_system_standby_eco` has display name `Eco Cold Standby`, the script uses that as the run-level KPI display name. This distinguishes runs that use different standby modes even though they share the same wake edge. The script resolves it from the active navigation graph, including the selected variant. If the node has no `display_name`, its node label (for example, `settings_system_standby_eco`) is used.
2. **Wake edge KPI display name** — set `kpi_name` on the measured `standby → live` action set in the edge editor. This is the edge's own friendly name. The `--edge` parameter selects the opposite `live → standby` direction, but the script times the reverse wake action set.

When a standby mode node is selected, its display name (or, if unset, its raw node label) is written as the KPI run-level display name. That run-level name takes precedence in KPI reports and the Grafana KPI dashboard over the wake edge's `kpi_name` and edge label. If no standby mode node is selected, the script does not set a run-level name, so the wake edge's `kpi_name` is used, falling back to its action-set label. The execution summary's KPI metrics block includes both the mode name and measured transition, for example `Eco Cold Standby (standby → live)`.

So to see the user's chosen friendly name on the recorded KPI when measuring a mode, set it on the **standby mode node**. Set `kpi_name` on the **wake action set** when you want a useful edge fallback for runs with no selected mode.

## Workflow

1. Resolve the root tree, warm the navigation cache, and resolve the `standby → live` action_set id (so fetched KPI rows can be filtered to the wake direction only — the per-iteration `goto(standby)` also produces an incidental `live → standby` row).
2. **Precondition (once, optional):** `goto(<standby_mode_node>)` to select the standby mode in Settings.
3. **Baseline (once):** `goto(<live_node>)` so the first power-down starts from a known state.
4. **For each iteration:**
   - `goto(<standby_node>)` — traverses the `live → standby` edge (POWER).
   - `sleep(<standby_wait>)` — dwell in standby.
   - `goto(<live_node>)` — traverses the **`standby → live`** edge (POWER), which the KPI pipeline auto-measures.
5. Poll `execution_results` every 3s (max 60s) until `--iterations` wake measurements have been post-processed by `vpt-kpi.service`.
6. Filter to the `standby → live` action_set, compute min/max/avg, and emit a per-iteration breakdown (reusing `_append_direction_metrics`).

## Output

The execution summary shows:

- **Header** — device, host, interface, variant (`base` when none), the selected standby mode and its display name when configured, the full cycle, the measured wake edge, requested iterations, and total script time.
- **KPI Metrics** — the mode display name plus `standby → live` when a mode node is selected; otherwise the wake edge label. Includes Successful/Skipped/Failed counts and Min/Max/Avg, with one inline row per iteration (each linking its `kpi_report` when present).
- **Success** when `len(wake_results) ≥ iterations`, no hard failures, and at least one real measurement landed. Sibling-skips (`⚠️`) don't count against the run.

## Prerequisites (navigation tree)

These live in the navigation tree, not the script:

1. If using the mode precondition, **the selected standby-mode node must exist and be reachable** in the chosen interface and variant. The precondition `goto` fails if it cannot reach that node.
2. **The selected `live → standby` edge must have a reverse `standby → live` action set**, because the script derives and traverses that reverse direction for each wake.
3. **The `standby → live` edge must anchor a KPI reference** — otherwise *zero* KPIs are produced (the edge is traversed but nothing is measured). Either:
   - add explicit `kpi_references` to the `standby → live` action set, **or**
   - keep `use_verifications_for_kpi: true` and give the **`live` node at least one verification** (e.g. a "live content present" / "not blackscreen" image check). As shipped, `live` has **0 verifications**, so the wake KPI cannot be measured until this is configured. (`standby` already has `blackscreen` + `no_signal` verifications, which is why `live → standby` already measures cleanly.)

## Relationship to kpi_measurement.py

| | `kpi_measurement.py` | `standby_measurement.py` |
|---|---|---|
| Edge selection | RunTests dropdown (`--edge` label), any KPI-enabled action_set | Fixed `standby → live` |
| Setup / precondition | `goto(from_label)` | `goto(<standby_mode_node>)` then `goto(live)` |
| Per-iteration shape | forward + reverse pair | `live→standby → wait → standby→live` |
| Extra knob | — | `--standby_wait` dwell time |
| Conditional-sibling fallback | yes | no (fixed power edges) |
| DB fetch + report rendering | own helpers | **reuses kpi_measurement's helpers** |

## Step count expectation

For N iterations with a mode precondition, expect: 1 precondition `goto` (depth varies) + 1 baseline `goto(live)` + `2N` cycle steps (N `live→standby` + N `standby→live`). The `standby→live` legs are the measured ones (N KPI rows expected).
