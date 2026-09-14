# MCP Screenshot Tools

[← Back to MCP Documentation](./README.md)

---

### capture_screenshot

Capture screenshot for AI vision analysis.

```json
{
  "device_id": "device1",
  "team_id": "team_abc123",
  "include_ui_dump": false,  // Optional: include UI hierarchy
  "host_name": "host1"   // Optional: defaults to 'host1'
}
```

**Returns**: MCP-formatted response optimized for AI vision models:
```json
{
  "content": [{
    "type": "image",
    "data": "<base64_png_data>",
    "mimeType": "image/png"
  }],
  "isError": false
}
```

This format allows AI vision models (Claude, GPT-4V, etc.) to directly process the screenshot for analysis.

---

### generate_test_graph

Generate test case from natural language.

```json
{
  "prompt": "Navigate to Settings and enable subtitles",
  "device_id": "device1",
  "team_id": "team_abc123",
  "userinterface_name": "example_androidtv"
}
```

**Returns**: `graph` JSON + `analysis`
