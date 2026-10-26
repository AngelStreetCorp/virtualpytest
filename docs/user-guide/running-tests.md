# Running Tests — Web UI Guide

Use the **Run Tests** page to run scripts, test cases and campaigns.

<div data-technical>

Page path: `/test-execution/run-tests`.

</div>

---

## Page Layout

The page has three main areas:

1. **Target Panel** (left): choose the hosts and devices to run on.
2. **Script Selector** (right): choose the scripts or test cases.
3. **Run Bar** (bottom): the Run and Abort buttons and scheduling options.

Below these:
- **Selected Items**: settings for each selected script, per device.
- **Device Queue**: what runs or waits on each device.
- **Last Executions**: recent runs from this page.

---

## Selecting Targets

Tick one or more targets in the Target Panel. Each row shows:

| Column | Description |
|--------|-------------|
| Name | Device or host display name |
| Host | Backend host the device is connected to |
| Model | Device model |

- Only targets that fit the selected script are shown.
- A **lock icon** means another script is running on that target. You can still select it.
- **Favorites**: click the star on a device to make it yours. Favorites are listed first.

<div data-technical>

Model examples: `host_vnc`, `android_mobile`. Only targets matching the script's `target_rules` are listed.

The lock is checked when the run starts. Favorites follow you to other browsers and to the mobile app. They are listed first, in a *Favorites* group, in every device list: Run Tests, the Dashboard, the Device control filter, the navigation editor, the test case builder, the campaign builder, Manual run, Device info and the AI chat. Where you can pick several devices (Run Tests, the Dashboard and Device control filter, maintenance windows), the **Favorites** chip selects all of yours in one click. Click it again to clear.

</div>

---

## Selecting Scripts

Click a script in the right panel to select it. Use **S** (scripts) and **TC** (test cases) to switch lists. Click again to deselect.

- Use the **Folder** and **Tags** menus to narrow the list.
- The counter shows how many items you picked.
- **Favorites**: click the star on the left of an item to make it a favorite. Favorites are listed first.

<div data-technical>

Counter text: `N items selected`.

Favorites work the same way as for devices. They are listed first, in a *Favorites* group, wherever you pick one: this list, the Build campaign list, the Test cases and Campaigns pages and their load dialogs, the campaign builder toolbox, Manual run, the AI chat selects, the QuickTest and Virtual scripts lists, and the requirement link dialog. In the Run Tests lists, the gold **star + number** chip next to *select all* selects every favorite you can currently see. Click it again to clear them.

</div>

---

## Execution Modes

### One script: direct run

When you select **1 script** and click **Run**:

- The script runs at once on all selected targets, in parallel.
- Each target gets a pass or fail message. The history updates as each one finishes.
- If a target is busy, the run is queued instead of failing.

<div data-technical>

Report and log links appear in the history. The same queuing happens if the target becomes busy just before the backend starts the script. Queued runs are one-shot deployments (`max_executions=1`).

</div>

### Two or more scripts: the queue

When you select **2 or more scripts** and click **Run**, each script waits its turn on each target:

- Only one script runs on a device at a time. The others wait in order.
- When a script finishes, the next waiting script starts by itself.
- The **Device Queue** table appears and refreshes every 10 seconds. Results appear in **Test Reports**, one row per script.

<div data-technical>

The system creates one one-time deployment for each script and target pair. For example, 3 scripts on 2 targets give 6 deployments. Each one is a `max_executions=1` deployment. The backend host scheduler does the ordering, and a device holds at most 10 waiting scripts.

</div>

### Scheduled and repeating runs

Set **Start**, **Repeat** and **End** in the Run Bar. Follow the deployments in **Monitor Tests**.

| Setting | Options |
|---------|---------|
| **Start** | Now, In 1 hour, In 6 hours, Tomorrow, Next Monday, Pick date |
| **Repeat** | No repeat, Every 10 min, Every 30 min, Hourly, Every 2h, Every 6h, Daily, Weekly, Custom cron |
| **End** | No end, 1 day, 7 days, 30 days, 90 days, Pick date |
| **Max Iter.** | Maximum number of runs (optional) |

- If **Repeat** is set and **Start** is **Now**, the first run starts right away, then the repeat follows its schedule.

<div data-technical>

For example, **Every hour** with **Start = Now** runs once now, then at each next hourly slot. Deployments are shown at `/test-execution/monitor-tests`. Repeats use a cron schedule.

</div>

---

## Per-Device Parameters

When a script has parameters, **Selected Items** shows a section for each script. Expand it to set values per device.

```
[S] Get System Information
  ├── host-clone-1    [interface_type: auto] [interface: auto]
  └── host-clone-2    [interface_type: auto] [interface: auto]
```

- The defaults come from the script itself. To change a value for one device, edit it in place.
- You do not set the host and device settings. The framework adds them.

Each parameter gets a matching control. Passwords and tokens are hidden.

<div data-technical>

| Type | Control |
|------|---------|
| `str` | Text field |
| `str` with choices (e.g., `eth\|wifi`) | Dropdown |
| `int` | Number input |
| `bool` | Checkbox |
| `password` / `secret` / `token` | Masked text field |

Parameters are read from `_script_args`. The framework fills `--host` and `--device`.

</div>

For how a script declares its parameters, see **[Writing Scripts](writing-scripts.md)**.

---

## Device Queue

The Device Queue table appears after a multi-script Run. It refreshes every 10 seconds and hides when all scripts finish.

| Column | Description |
|--------|-------------|
| Device | `host_name:device_id` |
| Script | Script being run or waiting |
| Status | `running` (green) or `queued` (yellow) |
| Queued At | When the execution was scheduled |

<div data-technical>

Refresh interval: 10s.

Data comes from the `deployment_executions` table, the same data you see in Monitor Tests.

</div>

---

## Execution History

The **Last Executions** table at the bottom shows the last 20 runs from this session:

| Column | Description |
|--------|-------------|
| Target | Host and device, with model |
| Script | Script name |
| Start / End | Timestamps |
| Status | running, queued, completed, skipped, failed, aborted |
| Results | SUCCESS / FAILURE |
| Report / Logs | Links to the HTML report and the execution logs |

The history is kept in this browser only. It clears when you reset the browser.

- A run blocked by a busy target shows as **queued** when its fallback deployment is created. If that deployment cannot be created, it shows as **skipped**.
- Only runs that actually started end as **failed** or **aborted**.

<div data-technical>

The history is stored in `localStorage`. Report and log links point to files stored in R2.

</div>

---

## Campaigns Tab

Switch to the **Campaigns** tab (top-right toggle). Select a campaign and its targets, then click Run. The campaign runs all its scripts one after another on each target. Results appear in **Campaign Reports**.

<div data-technical>

A campaign can be stored in the database or in a file. Campaign reports are at `/test-results/campaign-reports`.

</div>

---

## Where Results Appear

| Page | What you see |
|------|-------------|
| **Run Tests, Last Executions** | Runs from this browser (direct runs only) |
| **Monitor Tests** | Deployment runs: scheduled, running, completed |
| **Test Reports** | One row per script and target run |
| **AI Queue** | If AI analysis is on, the analyzed and discarded results |
| **Grafana** | Script dashboards: duration and success rate over time |

---

## Test Reports Page

The **Test Reports** page shows the results of all runs.

### Filtering and search

- **Tabs**: switch between **Tests** (one row per script run) and **Campaigns** (one row per campaign).
- **Search bar**: filter by script name, host name, device ID or campaign name. It works together with the active tab.

### Results table

Each row is one script run on one target:

| Column | Description |
|--------|-------------|
| Timestamp | When the run started |
| Script | Script or campaign name |
| Host | Backend host |
| Device | Device ID or display name |
| Duration | How long the run took |
| Result | PASS / FAIL / ERROR / RUNNING |
| Report | Link to the HTML report |
| Logs | Link to the raw execution logs |

- Drag the column borders to change the widths. Your sizes are kept in this browser.
- Click a row to see its details, when they are available.

<div data-technical>

Page path: `/test-results/reports`. Rows are `script_results`. Report and log links are stored in R2. Column widths are saved in `localStorage`.

</div>
