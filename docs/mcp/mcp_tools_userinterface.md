# MCP Userinterface Tools

[← Back to MCP Documentation](./README.md)

---

### 🎨 UserInterface Management

#### create_userinterface

Create a new userinterface (app model) for testing.

**Parameters:**
```json
{
  "name": "youtube_mobile",              // REQUIRED - Interface name
  "device_model": "android_mobile",      // REQUIRED - Device model type
  "description": "YouTube Mobile App",   // Optional
  "team_id": "team_1"                   // Optional (defaults to 'team_1')
}
```

**Device Models:**
Valid device models are fetched from `/server/devicemodel/getAllModels` and validated:
- `android_mobile` - Android mobile devices
- `android_tv` - Android TV devices
- `web` - Web browsers (Playwright)
- `host_vnc` - VNC hosts
- Custom models (if created for your team)

**Returns:**
```json
{
  "success": true,
  "userinterface_id": "abc-123-def",
  "name": "youtube_mobile",
  "device_model": "android_mobile",
  "root_tree_id": "tree-xyz-789"
}
```

**Example:**
```python
create_userinterface({
    "name": "youtube_mobile",
    "device_model": "android_mobile",
    "description": "YouTube Mobile App UI Model"
})
# Returns: ✅ Userinterface created: youtube_mobile
#          ID: abc-123-def
#          Device Model: android_mobile
#          Root Tree: tree-xyz-789
```

**Use Case:** Create app models (Netflix, YouTube, etc.) before building navigation trees.

---

#### list_userinterfaces

List all userinterfaces for the team.

**Parameters:**
```json
{
  "team_id": "team_1",                  // Optional (defaults to 'team_1')
  "force_refresh": false                // Optional (default: false)
}
```

**Returns:**
```json
{
  "interfaces": [
    {
      "id": "abc-123",
      "name": "youtube_mobile",
      "models": ["android_mobile"],
      "root_tree": {
        "id": "tree-xyz-789",
        "name": "youtube_mobile_root"
      }
    }
  ],
  "total": 10
}
```

**Example:**
```python
list_userinterfaces({})
# Returns: 📋 User Interfaces (10 total):
#          • youtube_mobile (ID: abc-123)
#            Models: android_mobile
#            ✅ Has navigation tree (ID: tree-xyz-789)
```

**Use Case:** Discover available app models before testing.

---

#### get_userinterface_complete

Get COMPLETE userinterface with ALL nodes, edges, subtrees in ONE call.

**Parameters:**
```json
{
  "userinterface_id": "abc-123-def",    // REQUIRED
  "team_id": "team_1",                  // Optional (defaults to 'team_1')
  "include_metrics": true               // Optional (default: true)
}
```

**Returns:**
```json
{
  "tree": {
    "id": "tree-xyz-789",
    "name": "youtube_mobile_root",
    "metadata": {
      "nodes": [...],    // ALL nodes (including subtrees)
      "edges": [...]     // ALL edges (including subtrees)
    }
  },
  "nodes": [...],
  "edges": [...],
  "metrics": {...},
  "total_nodes": 42,
  "total_edges": 56
}
```

**Example:**
```python
get_userinterface_complete({
    "userinterface_id": "abc-123-def"
})
# Returns complete tree structure with all nodes/edges
# This REPLACES multiple calls to list_nodes + list_edges
```

**Use Case:** Get full tree data in one call instead of multiple requests.

---

#### list_nodes

List all nodes in a navigation tree.

**Parameters:**
```json
{
  "tree_id": "tree-xyz-789",            // REQUIRED
  "team_id": "team_1",                  // Optional (defaults to 'team_1')
  "page": 0,                            // Optional (default: 0)
  "limit": 100                          // Optional (default: 100)
}
```

**Returns:**
```json
{
  "nodes": [
    {
      "node_id": "home",
      "label": "home",
      "type": "screen",
      "verifications": [...],
      "position": {"x": 0, "y": 0}
    }
  ],
  "total": 42,
  "page": 0,
  "limit": 100
}
```

**Example:**
```python
list_nodes({
    "tree_id": "tree-xyz-789"
})
# Returns: 📋 Nodes in tree (42 total):
#          • home (node_id: 'home')
#            Type: screen
#            Verifications: 3
```

**Use Case:** Check nodes after create/delete operations for verification.

---

#### list_edges

List all edges in a navigation tree.

**Parameters:**
```json
{
  "tree_id": "tree-xyz-789",            // REQUIRED
  "team_id": "team_1",                  // Optional (defaults to 'team_1')
  "node_ids": ["home", "settings"]      // Optional - filter by node IDs
}
```

**Returns:**
```json
{
  "edges": [
    {
      "edge_id": "edge_home_settings",
      "source_node_id": "home",
      "target_node_id": "settings",
      "action_sets": [
        {
          "id": "home_to_settings",
          "actions": [...]
        },
        {
          "id": "settings_to_home",
          "actions": [...]
        }
      ]
    }
  ],
  "total": 56
}
```

**Example:**
```python
list_edges({
    "tree_id": "tree-xyz-789"
})
# Returns: 📋 Edges in tree (56 total):
#          • home → settings (edge_id: 'edge_home_settings')
#            Action Sets: 2
#              - home_to_settings: 1 actions
#              - settings_to_home: 1 actions
```

**Use Case:** Check edges after create/delete operations for verification.

---

#### delete_userinterface

Delete a userinterface model (soft delete).

**⚠️ DESTRUCTIVE OPERATION - Requires explicit confirmation**

**Parameters:**
```json
{
  "userinterface_id": "abc-123-def",    // REQUIRED
  "confirm": true,                      // REQUIRED - Must be true to proceed
  "team_id": "team_1"                   // Optional (defaults to 'team_1')
}
```

**Two-Step Process:**

**Step 1: Attempt to delete (without confirmation)**
```python
delete_userinterface({
    "userinterface_id": "abc-123-def"
})
# Returns: ⚠️ DESTRUCTIVE OPERATION - Confirmation Required
#          You are about to delete userinterface: abc-123-def
#          This will remove the app model and may affect related navigation trees.
#
#          To proceed, call again with 'confirm: true'
```

**Step 2: Confirm and delete**
```python
delete_userinterface({
    "userinterface_id": "abc-123-def",
    "confirm": true
})
# Returns: ✅ Userinterface deleted: abc-123-def
#          💡 Use list_userinterfaces() to verify deletion
```

**Returns:**
```json
{
  "success": true,
  "status": "deleted"
}
```

**Safety Features:**
- ✅ **Requires explicit confirmation** - AI must call twice
- ✅ **Clear warning message** - Shows what will be deleted
- ✅ **Suggests verification** - Recommends list_userinterfaces() first
- ✅ **Prevents accidental deletion** - No single-call deletion

**Use Case:** Remove unused or test app models safely.
