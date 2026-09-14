# MCP Script Tools

[← Back to MCP Documentation](./README.md)

---

### 🐍 Script Execution

#### execute_script

Execute Python script on device with CLI parameters.

**⚠️ PREREQUISITE:** `take_control()` should be called first if script uses device controls.

**Parameters:**
```json
{
  "script_name": "my_validation.py",     // REQUIRED
  "host_name": "host1",              // REQUIRED
  "device_id": "device1",                // Optional (defaults to 'device1')
  "userinterface_name": "example_mobile",  // Optional (if script needs it)
  "parameters": "--param1 value1 --param2 value2",  // Optional - CLI args
  "team_id": "team_1"                    // Optional (defaults to 'team_1')
}
```

**Returns:** Script execution results after async completion (max 2 hours).

**Example:**
```python
execute_script({
    "script_name": "stress_test.py",
    "host_name": "host1",
    "parameters": "--iterations 100 --timeout 30"
})
# MCP waits until script completes
# Returns: ✅ Script completed successfully (45.2s)
```
