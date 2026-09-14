# 📚 Navigation Tree History & Version Control

**Never lose your work. Restore any version instantly.**

Complete version control for navigation trees with Grafana-style restoration - create, save, and restore complete tree hierarchies including all subtrees, nodes, and edges.

---

## The Problem

Working with complex navigation trees is risky:
- ❌ "I accidentally deleted that subtree"
- ❌ "The tree got corrupted during editing"
- ❌ "I need to undo changes from 3 days ago"
- ❌ "The tree worked before, but now it's broken"
- ❌ "No way to compare different versions"

---

## The VirtualPyTest Solution

✅ **Complete snapshots** - Every save captures the entire tree hierarchy  
✅ **Grafana-style restoration** - Restore creates new versions (non-destructive)  
✅ **Full subtree support** - All nested trees, nodes, and edges preserved  
✅ **Visual version browser** - See all changes with timestamps  
✅ **One-click restoration** - Restore any version instantly  

---

## Features

### 🗂️ Complete Tree Snapshots

**Every save automatically captures your entire navigation tree hierarchy.**

#### What Gets Saved
```json
{
  "hierarchy": [
    {
      "tree_id": "main-tree",
      "tree_info": {
        "name": "Main Navigation",
        "depth": 0,
        "is_root_tree": true
      },
      "nodes": [
        {"node_id": "home", "label": "Home Screen"},
        {"node_id": "settings", "label": "Settings"}
      ],
      "edges": [
        {"source_node_id": "home", "target_node_id": "settings"}
      ]
    },
    {
      "tree_id": "settings-submenu",
      "tree_info": {
        "name": "Settings Options",
        "depth": 1,
        "parent_tree_id": "main-tree"
      },
      "nodes": [...],
      "edges": [...]
    }
  ],
  "total_trees": 2,
  "total_nodes": 15,
  "total_edges": 12,
  "snapshot_timestamp": "2025-12-19T16:30:00Z"
}
```

#### Automatic Versioning
- **Version 1**: Initial tree creation
- **Version 2**: Added settings submenu
- **Version 3**: Modified node positions
- **Version N**: Every save creates a new version

---

### 🔄 Grafana-Style Version Restoration

**Restore creates a new version (non-destructive approach).**

#### How It Works
```
Current State: Version 53
         ↓
Restore to Version 34
         ↓
Creates Version 54 (duplicate of Version 34)
         ↓
Version 54 becomes current
```

#### Example Workflow
```bash
# You're on Version 53 with complex changes
# But you want to go back to Version 34

POST /server/navigationTrees/tree-123/restore/34
{
  "restored_by": "user",
  "team_id": "team-456"
}

# Response:
{
  "success": true,
  "new_version": 54,
  "restored_from_version": 34,
  "trees_created": 3,
  "nodes_created": 25,
  "edges_created": 18
}
```

---

### 🎯 Visual Version Browser

**Browse, compare, and restore tree versions through an intuitive interface.**

#### Version History Dialog
- **Current version indicator** - See which version you're on
- **Complete version list** - All versions with timestamps
- **Version details** - Tree/node/edge counts per version
- **Change descriptions** - What changed in each version
- **One-click restore** - Restore any version instantly

#### Version Types
- 🟢 **CREATE** - Initial tree creation
- 🔵 **UPDATE** - Normal saves and modifications
- 🟠 **RESTORE** - Versions created from restoration

---

### 🏗️ Complete Hierarchy Preservation

**Subtrees, nodes, edges, and relationships are perfectly preserved.**

#### What Gets Restored
- ✅ **Root tree** - Main navigation structure
- ✅ **All subtrees** - Nested navigation trees
- ✅ **Node properties** - Labels, positions, styles, verifications
- ✅ **Edge connections** - Action sets, navigation logic
- ✅ **Parent-child relationships** - Tree hierarchy maintained
- ✅ **Fresh IDs** - New UUIDs prevent conflicts

#### Restoration Process
```sql
-- 1. Load version snapshot from history
-- 2. Create NEW trees with fresh IDs
INSERT INTO navigation_trees (id, name, userinterface_id, ...) VALUES (NEW-UUID, ...)

-- 3. Create NEW nodes with fresh IDs
INSERT INTO navigation_nodes (node_id, tree_id, label, ...) VALUES (NEW-UUID, ...)

-- 4. Create NEW edges with mapped node references
INSERT INTO navigation_edges (edge_id, source_node_id, target_node_id, ...) VALUES (...)

-- 5. Delete OLD trees
DELETE FROM navigation_trees WHERE userinterface_id = ? AND team_id = ?

-- 6. Save restoration as new version
INSERT INTO navigation_trees_history (version_number, modification_type, ...) VALUES (54, 'restore', ...)
```

---

## User Interface

### History Button
```
┌─────────────────────────────────────────────────┐
│ Tree Name * [Save] [Discard] [Undo] [Redo] History │
└─────────────────────────────────────────────────┘
```

**Smart Button States:**
- 🟢 **Enabled** - History available (2+ versions exist)
- 🔘 **Disabled** - No history (only 1 or 0 versions)
- 🚫 **Disabled** - Tree is locked
- 💡 **Tooltip** - Explains why button is disabled

### Version History Dialog
```
┌─ Tree Version History ──────────────────────────┐
│ Current: v53                                    │
├─────────────────────────────────────────────────┤
│ ▶ Version 53 [UPDATE]            [Current]      │
│   Today 2:30 PM                                │
│   Batch deleted 0 items, saved 12 nodes...     │
│   2 trees, 15 nodes, 8 edges                   │
│                                                │
│ ▶ Version 52 [UPDATE]            [Restore 🔄]   │
│   Today 2:25 PM                                │
│   Added settings subtree                        │
│   2 trees, 12 nodes, 7 edges                   │
│                                                │
│ ▶ Version 51 [RESTORE]           [Restore 🔄]   │
│   Yesterday 4:15 PM                            │
│   Restored from version 34                      │
│   1 trees, 8 nodes, 5 edges                    │
├─────────────────────────────────────────────────┤
│                    [Close]                      │
└─────────────────────────────────────────────────┘
```

**Empty State (No History):**
```
┌─ Tree Version History ──────────────────────────┐
│                                                │
│              No Version History                │
│      Save your tree to create the first        │
│         version and enable history.            │
│                                                │
├─────────────────────────────────────────────────┤
│                    [Close]                      │
└─────────────────────────────────────────────────┘
```

---

## Technical Implementation

### Database Schema
```sql
-- Complete hierarchy stored as JSONB
CREATE TABLE navigation_trees_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tree_id uuid REFERENCES navigation_trees(id) ON DELETE CASCADE,
    team_id uuid NOT NULL,
    version_number integer NOT NULL,
    modification_type text CHECK (modification_type IN ('create', 'update', 'restore')),
    tree_data jsonb NOT NULL,  -- Complete hierarchy snapshot
    changes_summary text,
    created_at timestamp with time zone DEFAULT now(),
    restored_from_version integer
);
```

### API Endpoints

#### Get Version History
```http
GET /server/navigationTrees/{tree_id}/history?team_id={team_id}
```

**Response:**
```json
{
  "success": true,
  "versions": [
    {
      "version_number": 53,
      "modification_type": "update",
      "created_at": "2025-12-19T16:30:00Z",
      "changes_summary": "Added new navigation path",
      "tree_data": {
        "total_trees": 2,
        "total_nodes": 15,
        "total_edges": 8
      }
    }
  ]
}
```

#### Restore Version
```http
POST /server/navigationTrees/{tree_id}/restore/{version_number}
Content-Type: application/json

{
  "restored_by": "user_id",
  "team_id": "team_id"
}
```

**Response:**
```json
{
  "success": true,
  "new_version": 54,
  "restored_from_version": 34,
  "trees_created": 3,
  "nodes_created": 25,
  "edges_created": 18
}
```

---

## Use Cases

### 🔧 Development & Testing
- **Safe experimentation** - Try changes, easily revert
- **A/B testing** - Compare different navigation approaches
- **Bug recovery** - Restore when trees get corrupted
- **Collaboration** - See what team members changed

### 📊 Quality Assurance
- **Regression testing** - Verify navigation still works after changes
- **Version comparison** - See what changed between releases
- **Audit trail** - Track who made what changes when
- **Compliance** - Maintain history for regulatory requirements

### 🚀 Production Support
- **Hot fixes** - Quickly restore working configurations
- **Incident response** - Roll back problematic changes
- **A/B deployments** - Switch between navigation versions
- **Performance optimization** - Compare different tree structures

---

## Benefits

| Feature | Benefit |
|---------|---------|
| **Complete snapshots** | Never lose work, restore entire hierarchies |
| **Non-destructive** | Restore creates new versions, originals preserved |
| **Subtree support** | Complex nested navigation fully preserved |
| **Visual interface** | Easy browsing and restoration |
| **Performance** | Fast saves, instant restores |
| **Storage efficient** | Only changed versions stored |
| **Team collaboration** | See and restore others' changes |

---

## Limitations

### ⚠️ Storage Considerations
- **JSONB storage** - Large trees = larger snapshots
- **Version accumulation** - Consider cleanup policies
- **Backup impact** - Include in database backups

### ⚠️ Performance Notes
- **Large hierarchies** - Restoration time scales with size
- **Frequent saves** - More versions = larger history table
- **Concurrent edits** - Only one user can edit at a time

### ⚠️ Current Constraints
- **Single tree focus** - Versions per tree, not per userinterface
- **No branching** - Linear version history (no Git-style branches)
- **No diffs** - Can't see exact changes between versions

---

## Configuration

### Environment Variables
```bash
# No special configuration needed
# Uses existing database and API setup
```

### Database Cleanup (Optional)
```sql
-- Remove old versions (keep last 50 per tree)
DELETE FROM navigation_trees_history
WHERE id IN (
  SELECT id FROM (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY tree_id ORDER BY version_number DESC) as rn
    FROM navigation_trees_history
  ) t
  WHERE rn > 50
);
```

---

## Getting Started

### 1. Enable Version History
```bash
# Already enabled - works automatically on save
```

### 2. View Version History
1. Open navigation tree editor
2. Click **"History"** button
3. Browse available versions
4. Click **restore icon** to restore

### 3. Restore a Version
1. Select target version
2. Click restore (🔄 icon)
3. Confirm restoration
4. Tree reloads with restored version

### 4. Monitor Usage
```sql
-- Check version history usage
SELECT
  tree_id,
  COUNT(*) as versions,
  MAX(version_number) as latest_version,
  MAX(created_at) as last_modified
FROM navigation_trees_history
GROUP BY tree_id
ORDER BY versions DESC;
```

---

## Troubleshooting

### Version Not Appearing
- **Check saves** - Only completed saves create versions
- **Verify permissions** - Ensure write access to database
- **Check errors** - Look for save failures in logs

### Restoration Failed
- **Check database** - Ensure target version exists
- **Verify permissions** - Confirm write access
- **Check conflicts** - Ensure tree not locked by others

### Performance Issues
- **Large trees** - Consider breaking into smaller hierarchies
- **Many versions** - Implement cleanup policies
- **Concurrent access** - Avoid simultaneous edits

---

**Navigation trees are now fully version controlled with complete restoration capabilities!** 🎯📚

**Perfect for:** Complex navigation testing, team collaboration, change management, and never losing work again.</content>

<parameter name="file_path">docs/features/README.md
