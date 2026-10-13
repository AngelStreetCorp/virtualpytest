# MCP Script Tools

[← Back to MCP Documentation](./README.md)

---

### 🐍 Script Execution

#### execute_script

Start a Python script on a device and return its `execution_id` at once. The tool does **not**
wait for the script to end: read the result with `get_script_execution_status`.

**Parameters:**
```json
{
  "script_name": "my_validation.py",     // REQUIRED (a virtual script: its name)
  "virtual_script_id": "uuid",           // Required for a virtual (DB-stored) script - from list_scripts / save_virtual_script
  "host_name": "host1",                  // REQUIRED
  "device_id": "device1",                // Optional (defaults to 'host')
  "userinterface_name": "example_mobile",  // Optional (if script needs it)
  "parameters": "--param1 value1 --param2 value2",  // Optional - CLI args
  "force_unlock": false,                 // Optional - preempt the device lock
  "environment": "prod",                 // Optional - dev | test | prod
  "team_id": "team_1"                    // Optional
}
```

**Returns:** `structuredContent` `{execution_id, kind: "script", status: "running", done: false, host_name, device_id}`.

`list_scripts` gives each virtual script its `virtual_script_id`.

---

#### save_virtual_script / get_virtual_script

Feature `virtual-scripts` (`features/virtual-scripts/backend_server/mcp_tools/virtual_script_tools.py`).
`save_virtual_script` creates a virtual script, or overwrites its dev version if the name exists,
through `/server/virtual-script/save`: a syntax error comes back with its line, missing `@script` /
`_script_args` come back as warnings. `get_virtual_script` returns the dev source for an edit.
Atlas uses them through the `create-virtual-script` skill.

```json
{
  "name": "SC_NAV_01_GotoLive",          // REQUIRED - letters, digits, underscores
  "source": "#!/usr/bin/env python3 ...", // REQUIRED - full Python source
  "description": "...",                  // Optional - defaults to main._script_description
  "doc": "# ...",                        // Optional - editor Doc tab
  "folder": "atlas"                      // Optional - created if missing
}
```

**Returns:** `{virtual_script_id, action: created|updated, parameters, warnings}`.

---

#### get_script_execution_status

Read the state of a script started by `execute_script`. Waits up to `wait_seconds` for the script
to end, then answers. Call again while `done` is false.

**Parameters:**
```json
{
  "execution_id": "task-123",            // REQUIRED - from execute_script
  "wait_seconds": 20                     // Optional - default 20, max 50, 0 answers at once
}
```

**Returns:** the status shape below, plus `exit_code` and `script_success`.

**Status shape** (`structuredContent`, same for both status tools):
```json
{
  "execution_id": "ex-123",
  "kind": "testcase",            // or "script"
  "status": "running",           // running | completed | failed | aborted | unknown
  "done": false,                 // true once status is completed, failed or aborted
  "passed": null,                // true/false once done; completed + false = the test ran and failed
  "report_url": null,
  "logs_url": null,
  "execution_time_ms": null,
  "error": null
}
```
- `unknown` means the status read itself timed out or got a 5xx. The run goes on: read again.
- `isError` is set only when the execution_id is unknown to the server (404). A test that ran and
  FAILED is a result (`completed`, `passed: false`), not a tool error.
- Each status call answers within `wait_seconds` (default 20, max 50), so no MCP request stays open
  longer than a proxy allows (a proxy such as Cloudflare answers 524 after 100 s).

**Example:**
```python
run = execute_script({
    "script_name": "stress_test.py",
    "host_name": "host1",
    "parameters": "--iterations 100 --timeout 30"
})
execution_id = run["structuredContent"]["execution_id"]

status = get_script_execution_status({"execution_id": execution_id})
while not status["structuredContent"]["done"]:
    status = get_script_execution_status({"execution_id": execution_id})
# status["structuredContent"]["passed"] -> True / False
```
