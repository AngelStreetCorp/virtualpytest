# kpi_measurement

Measures the KPI (action → visual-confirmation latency) for a navigation edge by repeating the forward transition. The script also navigates back between iterations so the reverse direction is captured too.

## Usage

```bash
python test_scripts/kpi_measurement.py --edge "home_apps → apps" --iterations 3
python test_scripts/kpi_measurement.py --edge "settings → home" --iterations 10
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface name |
| `--variant` | string | _empty_ | Optional named variant; empty = base |
| `--edge` | string | — | Action-set label, e.g. `"home_apps → apps"`. The RunTests modal preselects `ENTRY → home` when available, otherwise the first KPI-enabled action_set. |
| `--iterations` | int | `3` | Number of forward measurements to take |

The dropdown only lists action_sets that have **KPI measurement configured** — either `kpi_references` set, or `use_verifications_for_kpi=true` with the destination node carrying verifications. See `frontend/src/components/common/EdgeKpiSelector.tsx` and `GET /server/navigationTrees/kpi-action-sets`.

## Workflow

1. Resolve the chosen action_set label → forward `from`/`to` nodes + action_set ID. The reverse direction (the sibling action_set on the same edge) is captured at the same time.
2. **Initial setup (once):** navigate to `from_label`. Skipped when `from_label == ENTRY` (virtual start).
3. **For each iteration:**
   - **Forward:** `from_label → to_label` — KPI measured for the selected action_set.
   - **Reverse:** `to_label → from_label` — KPI measured for the sibling action_set if one exists; otherwise pathfinding takes whatever path is available. Skipped when `from_label == ENTRY`.
4. Poll `execution_results` every 3s (max 60s) until every iteration's forward measurement has been post-processed by `vpt-kpi.service` — accommodates async KPI patches without a fixed sleep.
5. Compute statistics over the forward measurements (min/max/avg) and emit a per-iteration breakdown that pairs `from-to` with `to-from` chronologically.

## Output

The execution summary shows:

- **Header** — device, host, interface, variant (`base` when none selected), edge label, transition, requested iterations, total script time.
- **KPI Metrics** — one block per direction (forward + reverse if a sibling exists), each with Successful/Failed counts and Min/Max/Avg. The `❌ failed/total` part is **only shown when there is at least one failure** — an all-pass direction reads just `✅ 2/2` (no `❌ 0/2` noise). Labels use the **friendly KPI name** when the edge's action_set has one set (Edge Edit dialog → "KPI display name", stored on `action_sets[i].kpi_name`), e.g. `📈 KPI Metrics ([TC259] Open TV Guide):`; otherwise they fall back to the action_set label, e.g. `📈 KPI Metrics (home_apps → apps):`. The same `kpi_name` drives the "Variant - Action Set" column on the Grafana KPI dashboard.
- **Per-iteration results**, labelled with the actual action_set names, e.g.:
  ```
  📋 PER-ITERATION RESULTS:
     1. home_apps → apps: ✅ 7580ms (7.58s)  [kpi_report](https://…)
     1. apps → home_apps: ✅ 1121ms (1.12s)  [kpi_report](https://…)
     2. home_apps → apps: ✅ 1060ms (1.06s)  [kpi_report](https://…)
     2. apps → home_apps: ✅ 1039ms (1.04s)  [kpi_report](https://…)
     3. home_apps → apps: ✅ 1080ms (1.08s)  [kpi_report](https://…)
     3. apps → home_apps: ✅ 1024ms (1.02s)  [kpi_report](https://…)
  ```
  The `[kpi_report](url)` markdown links are rendered as clickable `kpi_report` anchors in the HTML report (via `format_console_summary_for_html`).
- **Success** when every forward iteration measured successfully (`successful_kpis ≥ iterations AND len(filtered_forward) ≥ iterations`). Reverse measurements are informational and don't affect pass/fail.

## Conditional-sibling fallback

Some edges have a node on either end that is the planned outcome of a *conditional* press (e.g. `replay → replay_asset` on Example STB) where the device — depending on state — actually lands on a **sibling** node sharing the same source and action (`replay_asset_resume` when the asset has already been started). The originally-selected edge is then unreachable on this run, and naively retrying would produce only failures and no usable KPI rows.

The fallback can engage in **two places**:

| Trigger point | Selected edge looks like | What gets swapped |
|---|---|---|
| Initial setup (before iteration 1) | `replay_asset → replay_asset_stream` — `from_label` is itself the conditional target | `from_label` is swapped to the sibling (`replay_asset_resume`); we measure the sibling's *outbound* edge to the same `to_label` for all N iterations. No iteration is lost. |
| First forward iteration | `replay → replay_asset` — `to_label` is the conditional target | `to_label` is swapped to the sibling (`replay_asset_resume`); `iter_total` is bumped by 1 so the sibling's *inbound* edge gets exactly N measurements (the failed iteration counts as a bump, not a measurement). |

In both cases the host has already verified the sibling and surfaced it in `error_details.sibling_landed_node_label` (see `backend_host/.../navigation_executor.py` — the `sibling_landed` payload). The script then resolves the matching sibling edge against `action_set_map` and rebinds `selected_action_set_id`, `sibling_action_set_id`, `selected_label`, `sibling_label`, and the affected `from_label` / `to_label`.

### Triggering conditions (all must hold)

1. The swap hasn't already happened this run (at most one swap per script invocation, regardless of trigger point).
2. For the **iteration-loop** trigger: no forward iteration has succeeded yet — if the original edge has ever worked, the failure is transient noise, not a structural reachability problem. (The setup trigger has no equivalent guard — by definition no iteration has run yet.)
3. `error_details.sibling_landed_node_label` is set on the failure response (host populates this when sibling verification passed but no graph path back to the originally-requested target was found).
4. An edge connecting the sibling to the surviving endpoint exists in the action_set map: `(from_label, sibling)` for the iteration trigger, `(sibling, to_label)` for the setup trigger. If neither exists, the dropdown couldn't have offered it either; the script reports the failure honestly.

### What changes when fallback engages

- The affected endpoint (`from_label` for setup-trigger, `to_label` for iteration-trigger) plus `selected_action_set_id`, `sibling_action_set_id`, `selected_label`, `sibling_label` rebind to the sibling edge for the rest of the run.
- For the **iteration-loop trigger** only: `iter_total` is bumped by the iteration number where the swap happened (always `+1` under today's guard) so the sibling edge still gets exactly `--iterations` forward measurements. The running counter switches from `1/3` to `2/4` mid-loop. The **setup trigger** does **not** bump (no iteration was consumed).
- The polling expectation becomes `args.iterations` rows on the sibling forward action_set + `iter_total` rows on its reverse action_set.
- For the iteration-loop trigger: the original failed iteration's `execution_results` row is preserved in the report (it's tagged with the *original* action_set_id, which we add to `relevant_action_set_ids` before filtering).

### Example trace (`--iterations 3`, sibling fallback at iteration 1)

```
Iteration 1/3
⏱️  Forward: 'replay' → 'replay_asset'
❌ Iteration 1 forward FAILED
🔀 Conditional fallback engaged: 'replay → replay_asset' unreachable on this device — measuring 'replay → replay_asset_resume' instead from iteration 1 onwards. Total iterations bumped to 4 so 'replay → replay_asset_resume' gets the requested 3 measurements.
↩️  Reverse: 'replay_asset_resume' → 'replay'

Iteration 2/4
⏱️  Forward: 'replay' → 'replay_asset_resume'
✅ Iteration 2 forward SUCCESS
…
Iteration 4/4
✅ Iteration 4 forward SUCCESS

🎉 Completed 4 iterations
```

### Report block

The summary opens with a prominent fallback notice **before** the KPI metrics, so the reader can't conflate the originally-selected edge with what was actually measured:

```
⚠️  MEASUREMENT FALLBACK — original edge unreachable
    Originally selected : replay → replay_asset (→ replay_asset)
    Actually measured   : replay → replay_asset_resume (→ replay_asset_resume)
    Sibling detected    : replay_asset_resume
    Swapped at iteration: 1 (iteration 1..1 ran on the original edge and failed; loop extended to 4 so the sibling edge still gets the requested 3 measurements)
    Reason              : Conditional sibling detected: device landed on 'replay_asset_resume' instead of 'replay_asset'. Swapping measurement to the sibling's edge for the remaining iterations.
```

The numeric KPI block below this notice reports against the **actually-measured** `action_set_id` (the sibling edge). The pass/fail criterion is unchanged: `successful_kpis ≥ args.iterations`.

### When fallback does NOT engage

- The first forward iteration succeeded (any later failure is transient — the original edge is reachable).
- The host failure carries no `sibling_landed_*` fields (the conditional did not resolve to any known sibling, or there were no siblings at all).
- The sibling exists but has no outbound edge from the same source in the action_set map (the dropdown wouldn't list it either; the script reports the failure honestly).

Implementation: see `_run_kpi_measurement` in `kpi_measurement.py` (search for `Conditional-sibling fallback bookkeeping`). The sibling info is surfaced by the host's `NavigationExecutor` failure return (`backend_host/src/services/navigation/navigation_executor.py`, `sibling_landed` payload in `build_error_details`).

## Step count expectation

For 3 iterations of `home_apps → apps` starting from ENTRY, expect:
- 3 setup steps (`ENTRY → home → home_tvguide → home_apps`, varies by tree)
- 6 measurement steps (3 forward + 3 reverse)
- = 9 test steps total

The exact setup step count depends on how deep `from_label` is in the navigation tree.

When the conditional-sibling fallback engages, add `2 × swap_at_iteration` to the measurement count (one extra forward + one extra reverse per added iteration). For the canonical `--iterations 3` + swap-at-1 case that's 8 measurement steps instead of 6.
