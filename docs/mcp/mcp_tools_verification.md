# MCP Verification Tools

[← Back to MCP Documentation](./README.md)

---

### ✅ Verification

#### verify_device_state

Verify device state with batch verifications (image, text, video, ADB).

**⚠️ PREREQUISITE:** `take_control()` should be called first.

**Parameters:**
```json
{
  "device_id": "device1",                 // REQUIRED
  "userinterface_name": "example_mobile",  // REQUIRED
  "verifications": [                      // REQUIRED
    {
      "command": "waitForElementToAppear",
      "params": {"search_term": "Replay", "timeout": 5},
      "verification_type": "adb"
    }
  ],
  "host_name": "host1",               // Optional (defaults to 'host1')
  "team_id": "team_1",                    // Optional (defaults to 'team_1')
  "tree_id": "main_navigation",           // Optional
  "node_id": "node-123",                  // Optional
  "include_screenshot": false             // Optional (default false) - set true to embed a screenshot of the verified screen
}
```

**Verification Structure:**
- `command`: Verification method name (from `list_verifications`)
- `params`: Method-specific parameters
- `verification_type`: Type category (adb, image, text, video)

**Returns:** Verification results after async completion (max 30s). When
`include_screenshot: true` is passed, the response also includes an **inline screenshot** of
the verified screen (a base64 `{type:"image"}` content block), on both pass and fail —
especially useful on failure to see *why* the verification did not match. It is **off by
default**; a failed screenshot capture never blocks the verification result.

**Example:**
```python
verify_device_state({
    "userinterface_name": "example_mobile",
    "verifications": [{
        "command": "waitForElementToAppear",
        "params": {"search_term": "Replay", "timeout": 5},
        "verification_type": "adb"
    }]
})
# MCP waits until verification completes
# Returns: ✅ Verification completed: 1/1 passed
```
