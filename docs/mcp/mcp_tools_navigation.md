# MCP Navigation Tools

[← Back to MCP Documentation](./README.md)

---

### 🗺️ Navigation

#### preview_userinterface

Get compact text preview of userinterface navigation tree.

Shows all nodes, edges, actions, and verifications in 8-10 lines.
Perfect for answering **"What do we test and how?"**

**✅ NO PREREQUISITES** - Just call with userinterface_name

**Parameters:**
```json
{
  "userinterface_name": "netflix_mobile",  // REQUIRED
  "team_id": "team_1"                      // Optional (defaults to default team)
}
```

**Returns:** Compact text showing all transitions

**Output Format:**
```
netflix_mobile (7 nodes, 13 transitions)

Entry→home: launch_app + tap(540,1645) [✓ Startseite]
home⟷search: click(Suchen) ⟷ click(Nach oben navigieren) [✓ Suchen]
home⟷content_detail: click(The Witcher) ⟷ BACK [✓ abspielen]
content_detail⟷player: click(abspielen) ⟷ BACK [✗ Startseite]
home⟷downloads: click(Downloads...) ⟷ click(Startseite) [✓ Downloads]
home⟷more: click(Mein Netflix) ⟷ click(Startseite) [✓ Mein Netflix]
search⟷content_detail: click(Frankenstein) ⟷ BACK [✓ abspielen]
```

**Example:**
```python
preview_userinterface({"userinterface_name": "netflix_mobile"})

# Returns compact preview of entire navigation tree
# Shows: nodes, transitions, actions, verifications
# Perfect for sharing with stakeholders or quick overview
```

**Use Cases:**
- Quick overview of test coverage
- Share navigation structure with stakeholders
- Understand what actions are tested
- Verify navigation completeness
- Answer "What do we test?" in seconds

---

#### navigate_to_node

Navigate to target node in UI tree using pathfinding.

**⚠️ PREREQUISITES:** 
- `take_control(tree_id='<tree>')` must be called first with the SAME tree_id
- All parameters (device_id, tree_id, userinterface_name) MUST match the take_control call

**Parameters:**
```json
{
  "tree_id": "main_navigation",           // REQUIRED - MUST match take_control
  "userinterface_name": "example_mobile",  // REQUIRED
  "target_node_label": "home_saved",      // Provide label OR id
  "target_node_id": "node-123",           // Provide label OR id
  "device_id": "device1",                 // Optional (defaults to 'device1')
  "host_name": "host1",               // Optional (defaults to 'host1')
  "current_node_id": "node-000",          // Optional (auto-detected if omitted)
  "team_id": "team_1",                    // Optional (defaults to 'team_1')
  "include_screenshot": false             // Optional (default false) - set true to embed a screenshot of the resulting screen
}
```

**Returns:** Navigation path + results after async completion (max 60s). When
`include_screenshot: true` is passed, the success response also includes an **inline
screenshot** of the resulting screen (a base64 `{type:"image"}` content block) so the model
can see where it landed. It is **off by default**. If the screenshot capture fails the text
result is still returned, just without the image.

**Example:**
```python
# Step 1: Take control with tree_id
take_control({"tree_id": "main_navigation"})

# Step 2: Navigate (must use SAME tree_id and userinterface_name)
navigate_to_node({
    "tree_id": "main_navigation",
    "userinterface_name": "example_mobile",
    "target_node_label": "home_saved"
})
# MCP waits until navigation completes
# Returns: ✅ Navigation to home_saved completed
```
