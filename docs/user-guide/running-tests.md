# Running Tests — Web UI Guide

How to execute scripts, test cases, and campaigns from the **Run Tests** page (`/test-execution/run-tests`).

---

## Page Layout

The Run Tests page has three sections:

1. **Target Panel** (left) — select which hosts/devices to run on
2. **Script Selector** (right) — pick scripts or test cases to execute
3. **Run Bar** (bottom) — Run/Abort buttons, scheduling options

Below those:
- **Selected Items** — per-device parameter overrides for each selected script
- **Device Queue** — appears when multi-script runs are in flight (running/queued per device)
- **Last Executions** — history of recent runs from this page

---

## Selecting Targets

Check one or more targets in the Target Panel. Each row shows:

| Column | Description |
|--------|-------------|
| Name | Device or host display name |
| Host | Backend host the device is connected to |
| Model | Device model (e.g., `host_vnc`, `android_mobile`) |

- Targets are **filtered by compatibility** — only targets compatible with the selected script's `target_rules` are shown.
- A **lock icon** next to a target means it's currently execution-locked (another script is running on it). You can still select it — lock handling happens at run time.

---

## Selecting Scripts

Click scripts in the right panel to select them. Toggle between **S** (scripts) and **TC** (test cases) using the filter buttons.

- **Single click** adds the script to your selection (shown in "Selected Items" below).
- **Click again** to deselect.
- Use **Folder** and **Tags** dropdowns to filter.
- The counter shows `N items selected`.

---

## Execution Modes

### Single Script (1 item selected) — Direct Execution

When you select **1 script** and click **Run**:

- Script executes **directly** on all selected targets in parallel.
- Live streaming — execution history updates in real-time as each target completes.
- Results: pass/fail toast per target, report/logs links in execution history.
- If a target is already locked, the run is converted to a one-shot queued deployment instead of failing immediately.
- If the target becomes locked after the frontend pre-check but before the backend starts the script, the run is also auto-queued as the same one-shot fallback.

### Multiple Scripts (2+ items selected) — Deployment Queue

When you select **2+ scripts** and click **Run**:

- Creates one **one-shot deployment** (`max_executions=1`) per script × target combination.
- Example: 3 scripts × 2 targets = 6 deployments.
- The backend host scheduler handles execution:
  - **1 script per device at a time** — others queue in FIFO order.
  - When a script finishes on a device, the next queued script starts automatically.
  - Max 10 queued scripts per device.
- A **Device Queue** table appears showing running/queued scripts per device (polls every 10s).
- Queue auto-hides when all scripts complete.
- Results appear in **Test Reports** as individual `script_results`.

### Scheduled / Periodic

Use the **Start**, **Repeat**, and **End** dropdowns in the Run Bar:

| Setting | Options |
|---------|---------|
| **Start** | Now, In 1 hour, In 6 hours, Tomorrow, Next Monday, Pick date |
| **Repeat** | No repeat, Every 10 min, Every 30 min, Hourly, Every 2h, Every 6h, Daily, Weekly, Custom cron |
| **End** | No end, 1 day, 7 days, 30 days, 90 days, Pick date |
| **Max Iter.** | Maximum number of executions (optional) |

When Start ≠ Now or Repeat is set, clicking Run creates **deployment records** visible in **Monitor Tests** (`/test-execution/monitor-tests`).

- If **Repeat** is set and **Start = Now**, the system tries to run the first execution immediately and also keeps the recurring cron schedule for later runs.
- Example: **Every hour** + **Start = Now** runs once now, then again at the next scheduled hourly slot.

---

## Per-Device Parameters

When a script has parameters (detected via `_script_args`), the **Selected Items** section shows an accordion per script. Expand it to see per-device parameter overrides:

```
[S] Get System Information
  ├── host-clone-1    [interface_type: auto] [interface: auto]
  └── host-clone-2    [interface_type: auto] [interface: auto]
```

- Default values come from script analysis.
- Override a value for a specific device by editing inline.
- Framework parameters (`--host`, `--device`) are added automatically — you don't configure them.

Parameter controls adapt to the declared type:

| Type | Control |
|------|---------|
| `str` | Text field |
| `str` with choices (e.g., `eth\|wifi`) | Dropdown |
| `int` | Number input |
| `bool` | Checkbox |
| `password` / `secret` / `token` | Masked text field |

For details on declaring parameters, see **[Writing Scripts](writing-scripts.md)**.

---

## Device Queue

The Device Queue table appears after a multi-script Run Now. It shows:

| Column | Description |
|--------|-------------|
| Device | `host_name:device_id` |
| Script | Script being run or waiting |
| Status | `running` (green) or `queued` (yellow) |
| Queued At | When the execution was scheduled |

- Polls every 10 seconds.
- Auto-disappears when all executions complete.
- Data comes from `deployment_executions` table (same data visible in Monitor Tests).

---

## Execution History

The **Last Executions** table at the bottom shows the last 20 runs from this session:

| Column | Description |
|--------|-------------|
| Target | Host + device with model |
| Script | Script name |
| Start / End | Timestamps |
| Status | running, queued, completed, skipped, failed, aborted |
| Results | SUCCESS / FAILURE |
| Report / Logs | Links to HTML report and execution logs (stored in R2) |

This is **session-local** — persisted in `localStorage`, cleared on browser reset.

- Lock-blocked runs that never start are shown as **queued** when the fallback deployment is created successfully.
- If the fallback deployment cannot be created, the row is shown as **skipped**.
- Only executions that actually started should end up as **failed** or **aborted**.

---

## Campaigns Tab

Switch to the **Campaigns** tab (top-right toggle) to run campaign bundles:

- Select a campaign from the list (DB-stored or file-based).
- Select targets.
- Click Run — campaigns execute all their contained scripts sequentially on each target.
- Campaign results appear in **Campaign Reports** (`/test-results/campaign-reports`).

---

## Where Results Appear

| Page | What you see |
|------|-------------|
| **Run Tests — Last Executions** | Session-local history (direct runs only) |
| **Monitor Tests** | Deployment-based runs: scheduled, running, completed |
| **Test Reports** | All `script_results` — one row per script×target execution |
| **AI Queue** | If AI analysis is enabled, analyzed/discarded results |
| **Grafana** | Script execution dashboards with duration, success rate trends |

---

## Test Reports Page (`/test-results/reports`)

The **Test Reports** page provides a unified view of all test execution results across all campaigns and standalone runs.

### Filtering & Search

- **Tabs** — Toggle between **Tests** (individual `script_results`) and **Campaigns** (per-campaign aggregate rows).
- **Search bar** — Filter the list by script name, host name, device ID, or campaign name. Search is applied on top of the active tab filter.

### Results Table

Each row represents one script × target execution:

| Column | Description |
|--------|-------------|
| Timestamp | When the execution started |
| Script | Script or campaign name |
| Host | Backend host |
| Device | Device ID or display name |
| Duration | Execution time |
| Result | PASS / FAIL / ERROR / RUNNING |
| Report | Link to the HTML report (stored in R2) |
| Logs | Link to raw execution logs |

- **Columns are resizable** — drag the column borders to adjust widths; sizes persist in `localStorage`.
- Click a row to expand details (if available).
