# MCP Ai Tools

[← Back to MCP Documentation](./README.md)

---

### 🤖 AI Generation

> **⚠️ FOR AI AGENTS:** These tools use VPT's built-in AI (OpenRouter) to generate graphs.
> If you are an AI agent, **do NOT use `generate_and_save_testcase`** — build the `graph_json`
> yourself and use `save_testcase()` instead. See [TestCase Tools](mcp_tools_testcase.md) for
> the graph format and [the recommended workflow](README.md#automated-testing-ai-agent-recommended-workflow).

#### generate_test_graph

Generate test case from natural language using AI.

**Parameters:**
```json
{
  "prompt": "Navigate to settings and enable subtitles",  // REQUIRED
  "userinterface_name": "example_androidtv",  // REQUIRED
  "device_id": "device1",                // Optional (defaults to 'device1')
  "host_name": "host1",              // Optional (defaults to 'host1')
  "resolutions": {},                     // Optional - for disambiguation
  "team_id": "team_1"                    // Optional (defaults to 'team_1')
}
```

**Returns:**
```json
{
  "success": true,
  "graph": {
    "nodes": [...],
    "edges": [...],
    "scriptConfig": {...}
  },
  "analysis": "Generated 3-step test case...",
  "requires_disambiguation": false
}
```

**Disambiguation Handling:**
If `requires_disambiguation: true`, the response includes:
```json
{
  "requires_disambiguation": true,
  "ambiguities": [
    {
      "phrase": "settings",
      "suggestions": ["Settings Menu", "Account Settings", "System Settings"]
    }
  ],
  "auto_corrections": [...],
  "available_nodes": [...]
}
```

Resolve by calling again with `resolutions`:
```python
generate_test_graph({
    "prompt": "Navigate to settings and enable subtitles",
    "userinterface_name": "example_androidtv",
    "resolutions": {
        "settings": "Settings Menu"
    }
})
```
