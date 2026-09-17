# 🧪 Test Automation

**Low-code automation for powerful testing.**

Python-based test automation with intuitive navigation trees and visual test builder. Designed for QA teams without requiring deep coding expertise.

---

## The Problem

Traditional test automation requires:
- ❌ Programming expertise
- ❌ Complex framework setup
- ❌ Brittle scripts that break easily
- ❌ Steep learning curve for QA teams

---

## The VirtualPyTest Solution

✅ **Low-code approach** - Focus on what to test, not how  
✅ **Navigation trees** - Visual representation of app structure  
✅ **Reusable components** - Build once, use everywhere  
✅ **Python-based** - Powerful yet accessible  
✅ **Web interface** - Create and run tests from browser  

---

## Core Concepts

> The snippets below are conceptual illustrations of the node/test-case/campaign model, not literal
> API calls — nodes and edges are actually stored in the database
> (`setup/db/schema/002_ui_navigation_tables.sql`) with a `verifications` array per node and
> `action_sets` per edge (forward/reverse actions, retries), not a flat `path` list. See
> [Navigation Tree Management](#navigation-tree-management) below for the real structure.

### 📍 Navigation Nodes

**Define where things are in your app.**

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

**Benefits:**
- Centralized app navigation logic
- Easy updates when UI changes
- Reusable across tests
- Visual graph representation

---

### 🧩 Test Cases

**Combine actions into reusable test scenarios.**

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

**Features:**
- Step-by-step execution
- Automatic verification
- Screenshot capture
- Error handling
- Retry logic

---

### 📋 Test Campaigns

**Run multiple tests in batches.**

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

---

## Web Interface

### 🖥️ Visual Test Builder

**Create tests without writing code.**

1. **Drag and drop actions** from palette
2. **Configure parameters** in sidebar
3. **Preview navigation** in real-time
4. **Save and execute** immediately

**Available actions:**
- Navigate to node
- Press key
- Enter text
- Verify text/image
- Wait for condition
- Take screenshot
- Custom Python code

---

### 🎯 Test Execution Interface

**Run tests from the browser.**

**Features:**
- Select device or multiple devices
- Choose test case or campaign
- Watch live execution
- View real-time logs
- See screenshots as they're captured
- Stop/pause execution

---

## Python Test Scripts

Scripts are plain Python files decorated with `@script` from
`shared.src.lib.executors.script_decorators`, run via `ScriptExecutor`
(`shared/src/lib/executors/script_executor.py`). There is no `ControllerFactory` or `TestExecutor`
class that test scripts import directly — script code calls navigation/verification helpers
against the execution context returned by `get_context()`.

See **[Writing Test Scripts](../user-guide/writing-scripts.md)** for the full, verified pattern
(parameter declaration via `_script_args`, target rules, step reporting) and a real minimal
script skeleton. For a complete working example, read `test_scripts/validation.py`, which drives
navigation-tree transitions end to end.

---

## Navigation Tree Management

### Create Navigation Trees

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

---

### Navigation Strategies

VirtualPyTest computes the path between nodes automatically (pathfinding across the navigation
graph) rather than requiring scripts to hardcode a sequence of key presses — see
[What is a navigation tree?](../faq/README.md#what-is-a-navigation-tree) for the concept and
`test_scripts/validation.py` for a real script that exercises pathfinding end to end.

---

## Campaign Management

### Create Campaigns

Campaigns are created and run through the web UI or the `/server/campaigns` REST API — there is
no test-author-facing `CampaignManager` Python class or cron-scheduling API. Internally, campaign
execution on the host is handled by `CampaignExecutor`
(`shared/src/lib/executors/campaign_executor.py`), which sequences the campaign's scripts and
supports abort requests — it isn't something a test script imports and drives directly.

For automatic recurring runs, use the [CI/CD feature](./cicd.md) (GitHub
Actions scheduling) or your own external scheduler calling the REST API — VirtualPyTest itself
doesn't ship a built-in cron scheduler for campaigns.

---

### Campaign Results

**Comprehensive reporting:**
- Overall pass/fail rate
- Per-device results
- Per-test-case results
- Execution duration
- Screenshots and logs
- Failure analysis

---

## Verification Methods

Real verification capabilities (text OCR, image template matching with a similarity threshold,
black-screen/freeze detection, AI-powered semantic screen checks — see
[AI Validation](./ai-validation.md)) are implemented under
`backend_host/src/controllers/verification/` (e.g. `VideoVerificationController.detect_freeze()`)
and attached to navigation nodes/edges as `verifications` entries in the database, not called as
loose `controller.verify_*()` methods from inside a test script. To actually exercise them from a
script, call `verify_screen()`/similar helpers exposed via the script execution context — see
[Writing Test Scripts](../user-guide/writing-scripts.md) for the real, current API.

---

## Test Structure

VirtualPyTest scripts are standalone Python files using the `@script` decorator — not pytest test
functions, fixtures, or page objects. There's no built-in Test Fixture / Page Object framework or
external YAML test-data loader; reuse comes from writing shared helper functions/modules that
multiple scripts import, the same way any Python project shares code. See
[Writing Test Scripts](../user-guide/writing-scripts.md) for the real script-authoring pattern.

---

## Running Across Multiple Devices

Rather than a `ThreadPoolExecutor` loop inside a script, run the same script against different
devices via campaigns (`/server/campaigns`) or by triggering multiple executions through the web
UI / REST API — the server and hosts handle concurrency, not the script itself.

---

## CI/CD Integration

### Jenkins

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

---

### GitHub Actions

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

---

## Benefits

### 🚀 Faster Test Creation
Visual tools and reusable components reduce test creation time by 80%.

### 💪 Lower Maintenance
Navigation trees mean updating one place updates all tests.

### 🎯 Better Coverage
Easy test creation leads to more comprehensive test coverage.

### 👥 Accessible to QA
Low-code approach means non-programmers can create effective tests.

---

## Next Steps

- 📖 [Unified Controller](./unified-controller.md) - Control devices
- 📖 [AI Validation](./ai-validation.md) - Smart verification
- 📚 User Guide - Test Builder
- 🔧 Technical Docs - Test Architecture

---

**Ready to automate your testing?**  
➡️ [Get Started](../get-started/README.md)


