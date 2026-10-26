# Test Automation

**Low-code automation for powerful testing.**

Build tests with a map of your app and a visual test builder. You do not need deep coding skills. Tests are written in Python, but most of them can be built without writing code.

---

## The Problem

Traditional test automation often needs programming skills, a complex setup, and scripts that break easily.

---

## The VirtualPyTest Solution

- **Low-code approach:** focus on what to test, not how
- **Navigation trees:** a visual picture of the app's structure
- **Reusable components:** build once, use everywhere
- **Web interface:** create and run tests from a browser

---

## Core Concepts

The examples below show the idea. They are not exact code you can paste.

<div data-technical>

> The snippets below are conceptual illustrations of the node/test-case/campaign model, not literal
> API calls — nodes and edges are actually stored in the database
> (`setup/db/schema/002_ui_navigation_tables.sql`) with a `verifications` array per node and
> `action_sets` per edge (forward/reverse actions, retries), not a flat `path` list. See
> [Navigation Tree Management](#navigation-tree-management) below for the real structure.

</div>

### Navigation Nodes

**Define where things are in your app.** Update the map when the UI changes, and every test that uses it benefits.

<div data-technical>

```python
# Conceptual navigation tree structure
navigation_tree = {
    "home": {
        "children": ["settings", "netflix", "youtube"]
    },
    "settings": {
        "verification": "text:Settings"
    },
    "netflix": {
        "verification": "image:netflix_logo.png"
    }
}
```

</div>

---

### Test Cases

**Combine actions into reusable test scenarios.** Each test runs step by step, checks the result, takes screenshots and retries when needed.

<div data-technical>

```python
# Simple test case
test_case = {
    "name": "Launch Netflix",
    "steps": [
        {"action": "navigate_to", "target": "home"},
        {"action": "navigate_to", "target": "netflix"},
        {"action": "verify_text", "text": "Netflix"},
        {"action": "screenshot", "name": "netflix_home"}
    ]
}
```

Features: step-by-step execution, automatic verification, screenshot capture, error handling, retry logic.

</div>

---

### Test Campaigns

**Run multiple tests in batches**, on one device or several.

<div data-technical>

```python
# Conceptual campaign structure — created via the web UI or /server/campaigns API
campaign = {
    "name": "Nightly Regression",
    "devices": ["android_tv_1", "android_tv_2"],
    "test_cases": [
        "launch_netflix",
        "launch_youtube",
        "settings_navigation",
        "channel_zapping"
    ]
}
```

There's no built-in cron-style scheduler for campaigns — trigger recurring runs via the
[CI/CD feature](./cicd.md) or an external scheduler calling the REST API.

</div>

There is no built-in timer for campaigns. To run them on a schedule, use the [CI/CD feature](./cicd.md) or an outside scheduler.

---

## Web Interface

### Visual Test Builder

**Create tests without writing code.**

1. Drag and drop actions from the palette
2. Set the options in the sidebar
3. Preview the navigation as you go
4. Save and run straight away

<div data-technical>

**Available actions:**
- Navigate to node
- Press key
- Enter text
- Verify text/image
- Wait for condition
- Take screenshot
- Custom Python code

</div>

---

### Test Execution Interface

**Run tests from the browser.** Pick one device or several, choose a test case or a campaign, and watch the run live. You can read the logs, see screenshots as they are taken, and stop or pause the run.

---

## Python Test Scripts

Test scripts are ordinary Python files. You write the steps, and the platform runs them on the device.

<div data-technical>

Scripts are plain Python files decorated with `@script` from
`shared.src.lib.executors.script_decorators`, run via `ScriptExecutor`
(`shared/src/lib/executors/script_executor.py`). There is no `ControllerFactory` or `TestExecutor`
class that test scripts import directly — script code calls navigation/verification helpers
against the execution context returned by `get_context()`.

See **[Writing Test Scripts](../user-guide/writing-scripts.md)** for the full, verified pattern
(parameter declaration via `_script_args`, target rules, step reporting) and a real minimal
script skeleton. For a complete working example, read `test_scripts/validation.py`, which drives
navigation-tree transitions end to end.

</div>

For the full pattern, see **[Writing Test Scripts](../user-guide/writing-scripts.md)**: parameters, target rules and how steps are reported.

---

## Navigation Tree Management

### Create Navigation Trees

**In the web interface:** open **Interface**, select your model, add a node, set its path and check, then connect the nodes. The map is kept in the database. You do not edit it as a file.

<div data-technical>

**Via Web Interface:**
1. Go to **Interface** section
2. Select your model
3. Click **Add Node**
4. Define path and verification
5. Connect nodes visually

Nodes and edges are stored in the database (`navigation_nodes`, `navigation_edges` tables,
`setup/db/schema/002_ui_navigation_tables.sql`), not authored as flat JSON files. Each node holds
a `verifications` array (base verification set, with optional per-locale/platform
`variant_overrides`); each edge holds one or more `action_sets` (forward/reverse actions, retries,
failure handling) rather than a single fixed `path`.

</div>

---

### Navigation Strategies

The platform finds the route between two screens for you. Your script does not need a fixed list of key presses.

<div data-technical>

VirtualPyTest computes the path between nodes automatically (pathfinding across the navigation
graph) rather than requiring scripts to hardcode a sequence of key presses — see
[What is a navigation tree?](../faq/README.md#what-is-a-navigation-tree) for the concept and
`test_scripts/validation.py` for a real script that exercises pathfinding end to end.

</div>

---

## Campaign Management

### Create Campaigns

Create and run campaigns in the web UI, or through the `/server/campaigns` API.

<div data-technical>

Campaigns are created and run through the web UI or the `/server/campaigns` REST API — there is
no test-author-facing `CampaignManager` Python class or cron-scheduling API. Internally, campaign
execution on the host is handled by `CampaignExecutor`
(`shared/src/lib/executors/campaign_executor.py`), which sequences the campaign's scripts and
supports abort requests — it isn't something a test script imports and drives directly.

For automatic recurring runs, use the [CI/CD feature](./cicd.md) (GitHub
Actions scheduling) or your own external scheduler calling the REST API — VirtualPyTest itself
doesn't ship a built-in cron scheduler for campaigns.

</div>

---

### Campaign Results

**Reports show** the overall pass/fail rate, results per device and per test case, how long the run took, and the screenshots, logs and failure analysis.

---

## Verification Methods

The platform checks text on screen, matches images, spots black or frozen pictures, and can run AI checks on the screen. You set these checks on the navigation map. You do not write them into the script.

<div data-technical>

Real verification capabilities (text OCR, image template matching with a similarity threshold,
black-screen/freeze detection, AI-powered semantic screen checks — see
[AI Validation](./ai-validation.md)) are implemented under
`backend_host/src/controllers/verification/` (e.g. `VideoVerificationController.detect_freeze()`)
and attached to navigation nodes/edges as `verifications` entries in the database, not called as
loose `controller.verify_*()` methods from inside a test script. To actually exercise them from a
script, call `verify_screen()`/similar helpers exposed via the script execution context — see
[Writing Test Scripts](../user-guide/writing-scripts.md) for the real, current API.

</div>

---

## Test Structure

Scripts are simple Python files. There is no special test framework to learn. You share code by writing helper modules that several scripts import.

<div data-technical>

VirtualPyTest scripts are standalone Python files using the `@script` decorator — not pytest test
functions, fixtures, or page objects. There's no built-in Test Fixture / Page Object framework or
external YAML test-data loader; reuse comes from writing shared helper functions/modules that
multiple scripts import, the same way any Python project shares code. See
[Writing Test Scripts](../user-guide/writing-scripts.md) for the real script-authoring pattern.

</div>

---

## Running Across Multiple Devices

To run one script on several devices, start a campaign or run it several times from the web interface. The server and the hosts share the work.

<div data-technical>

Rather than a `ThreadPoolExecutor` loop inside a script, run the same script against different
devices via campaigns (`/server/campaigns`) or by triggering multiple executions through the web
UI / REST API — the server and hosts handle concurrency, not the script itself.

</div>

---

## CI/CD Integration

You can run the scripts from your own build pipeline. Two examples follow.

### Jenkins

<div data-technical>

```groovy
stage('VirtualPyTest Tests') {
    steps {
        sh '''
            cd virtualpytest
            source venv/bin/activate
            python test_scripts/validation.py --device android_tv_1
        '''
    }
    post {
        always {
            publishHTML([
                reportDir: 'test_results',
                reportFiles: 'report.html',
                reportName: 'VirtualPyTest Report'
            ])
        }
    }
}
```

</div>

---

### GitHub Actions

<div data-technical>

```yaml
name: VirtualPyTest Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Tests
        run: |
          python test_scripts/tv/fullzap.py --max_iteration 10
      - name: Upload Results
        uses: actions/upload-artifact@v2
        with:
          name: test-results
          path: test_results/
```

</div>

---

## Benefits

Visual tools and reusable components make tests quicker to build, and a change to the map updates every test that uses it.

<div data-technical>

- **Faster Test Creation:** visual tools and reusable components reduce test creation time by 80%.
- **Lower Maintenance:** navigation trees mean updating one place updates all tests.
- **Better Coverage:** easy test creation leads to more comprehensive test coverage.
- **Accessible to QA:** a low-code approach means non-programmers can create effective tests.

</div>

---

## Next Steps

- [Unified Controller](./unified-controller.md): control devices
- [AI Validation](./ai-validation.md): smarter checks
- User Guide: Test Builder
- Technical Docs: Test Architecture

---

**Ready to automate your testing?**
[Get Started](../get-started/README.md)
