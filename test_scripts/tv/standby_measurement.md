# standby_measurement

Measures the **standby → live wake KPI** (how long the STB takes to show live TV again after being woken from standby) for a configurable standby mode and a configurable dwell time in standby.

It is a focused sibling of [`kpi_measurement.py`](../kpi_measurement.md): instead of resolving an edge from the RunTests dropdown and pairing forward/reverse, it drives a fixed power-cycle and **reuses kpi_measurement's DB-fetch + reporting helpers** (`_fetch_kpi_results_from_db`, `_is_kpi_skip`, `_append_direction_metrics`) so the output looks identical and the KPI plumbing is not forked.

The script never times anything itself — the timing is produced by the standard KPI pipeline (`vpt-kpi.service` / `kpi_executor.py`, see [docs/agent/execution/KPI.md](../../docs/agent/execution/KPI.md)) when the `standby → live` edge is traversed.

## Usage

```bash
python test_scripts/tv/standby_measurement.py example_tv \
  --standby_mode_node settings_system_standby_eco --standby_wait 30 --iterations 5 --device device4
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_tv` | UI interface name |
| `--variant` | string | _empty_ | Optional named variant; empty = base |
| `--standby_mode_node` | choice | `settings_system_standby_active` | Standby mode to select in Settings before measuring. **Fixed dropdown**: `settings_system_standby_fast`, `settings_system_standby_active`, `settings_system_standby_eco` |
| `--standby_node` | string | `standby` | Navigation node representing standby state |
| `--live_node` | string | `live` | Navigation node representing live TV (the wake destination) |
| `--standby_wait` | int | `5` | Seconds to dwell in standby before waking |
| `--iterations` | int | `3` | Number of wake measurements to take |

`--standby_mode_node` is encoded with the `@script` decorator's `:default:choiceA|choiceB|choiceC` form, so argparse attaches `choices` (the CLI rejects anything else) and the RunTests parameter renderer surfaces it as a **dropdown** — no extra frontend wiring.

## Workflow

1. Resolve the root tree, warm the navigation cache, and resolve the `standby → live` action_set id (so fetched KPI rows can be filtered to the wake direction only — the per-iteration `goto(standby)` also produces an incidental `live → standby` row).
2. **Precondition (once):** `goto(<standby_mode_node>)` to select the standby mode in Settings.
3. **Baseline (once):** `goto(<live_node>)` so the first power-down starts from a known state.
4. **For each iteration:**
   - `goto(<standby_node>)` — traverses the `live → standby` edge (POWER).
   - `sleep(<standby_wait>)` — dwell in standby.
   - `goto(<live_node>)` — traverses the **`standby → live`** edge (POWER), which the KPI pipeline auto-measures.
5. Poll `execution_results` every 3s (max 60s) until `--iterations` wake measurements have been post-processed by `vpt-kpi.service`.
6. Filter to the `standby → live` action_set, compute min/max/avg, and emit a per-iteration breakdown (reusing `_append_direction_metrics`).

## Output

The execution summary shows:

- **Header** — device, host, interface, variant (`base` when none), the selected standby mode node, the full cycle (`live→standby → wait Ns → standby→live`), the measured edge, requested iterations, and total script time.
- **KPI Metrics (`standby → live (wake)`)** — Successful/Skipped/Failed counts and Min/Max/Avg, with one inline row per iteration (each linking its `kpi_report` when present). Identical rendering to `kpi_measurement.py`.
- **Success** when `len(wake_results) ≥ iterations`, no hard failures, and at least one real measurement landed. Sibling-skips (`⚠️`) don't count against the run.

## Prerequisites (navigation tree)

These live in the navigation tree, not the script:

1. **The three standby-mode nodes must exist** in `example_tv`: `settings_system_standby_fast`, `settings_system_standby_active`, `settings_system_standby_eco`. The precondition `goto` fails if the selected one is missing.
2. **The `live → standby` edge must exist** with both action sets (`live → standby` and `standby → live`). It already does.
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
