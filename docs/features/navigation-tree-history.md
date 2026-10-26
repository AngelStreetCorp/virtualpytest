# Navigation Tree History & Version Control

**Never lose your work. Restore any version.**

Every save of a navigation tree is kept as a version. If a change breaks the tree, you can go back to an older version. The whole tree comes back, including its subtrees, nodes and edges.

---

## The Problem

Editing a complex tree is risky. A change can break it, and there was no easy way back.

---

## The VirtualPyTest Solution

- **Complete snapshots:** every save keeps the whole tree
- **Restore never erases:** a restore adds a new version
- **Restore in one step:** pick a version and restore it

---

## Features

### Complete Tree Snapshots

**Every save keeps the whole navigation tree, including its subtrees.**

#### What Gets Saved

<div data-technical>

Each version stores the whole hierarchy as one document:

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
- **Version 1**: the first tree
- **Version 2**: a settings submenu was added
- **Version 3**: node positions were changed
- **Version N**: every save creates a new version

</div>

---

### Grafana-Style Version Restoration

**A restore creates a new version. It does not erase the newer ones.**

#### How It Works

If you are on version 53 and restore version 34, the platform makes a copy of version 34 and calls it version 54. Versions 34 and 53 are still there.

<div data-technical>

```
Current State: Version 53
         ↓
Restore to Version 34
         ↓
Creates Version 54 (duplicate of Version 34)
         ↓
Version 54 becomes current
```

</div>

#### Example Workflow

<div data-technical>

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

</div>

---

### Visual Version Browser

**Browse, compare and restore versions in the tree editor.**

Each version is listed with its time and what changed.

<div data-technical>

#### Version History Dialog
- **Current version:** shows which version you are on
- **Full list:** every version with its time
- **Version details:** how many trees, nodes and edges each version has
- **Change descriptions:** what changed in each version
- **Restore:** restore any version with one click

#### Version Types
- **CREATE:** the first version of a tree
- **UPDATE:** a normal save or change
- **RESTORE:** a version made by restoring an older one

</div>

---

### Complete Hierarchy Preservation

**Subtrees, nodes, edges and the links between them are kept intact.**

#### What Gets Restored
Subtrees, nodes and edges come back exactly as they were.

<div data-technical>

- **Root tree:** the main navigation structure
- **All subtrees:** the nested navigation trees
- **Node details:** labels, positions, styles and checks
- **Edge connections:** action sets and navigation logic
- **Parent-child links:** the tree hierarchy stays the same
- **New IDs:** a restore gives everything fresh IDs, so nothing clashes

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

</div>

---

## User Interface

### History Button

Click **History**, next to **Save**, to see the versions.

<div data-technical>

```
┌─────────────────────────────────────────────────┐
│ Tree Name * [Save] [Discard] [Undo] [Redo] History │
└─────────────────────────────────────────────────┘
```

**Button states:**
- **Enabled:** there is a history (two or more versions)
- **Disabled:** there is no history yet (only one or no versions)
- **Disabled:** the tree is locked
- **Tooltip:** explains why the button is disabled

</div>

### Version History Dialog

<div data-technical>

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

**Empty state (no history):**
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

</div>

---

## Technical Implementation

### Database Schema

<div data-technical>

The whole tree is stored as one JSON document per version.

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

</div>

### API Endpoints

The history can be read and restored through the API.

#### Get Version History

<div data-technical>

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

</div>

#### Restore Version

<div data-technical>

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

</div>

---

## Use Cases

Try a change safely, and go back if it breaks. Useful for experiments, bug recovery and audits.

<div data-technical>

### Development & Testing
- **Safe experiments:** try a change, and undo it if it goes wrong
- **Comparing approaches:** try two navigation designs side by side
- **Bug recovery:** go back when a tree gets corrupted
- **Teamwork:** see what other people changed

### Quality Assurance
- **Regression checks:** confirm navigation still works after a change
- **Version comparison:** see what changed between releases
- **Audit trail:** see who changed what, and when
- **Compliance:** keep a history for rules that require one

### Production Support
- **Quick fixes:** bring back a configuration that worked
- **Incidents:** roll back a change that caused a problem
- **Switching:** move between two navigation versions
- **Speed:** compare different tree structures

</div>

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

Big trees take more space and longer to restore. Only one person can edit a tree at a time.

<div data-technical>

### Storage Considerations
- **Large trees make large snapshots.** Each version is stored in full.
- **Old versions pile up.** Plan to clear them out from time to time.
- **Backups grow.** The history is part of the database backup.

**JSONB storage** - Large trees = larger snapshots
**Version accumulation** - Consider cleanup policies
**Backup impact** - Include in database backups

### Performance Notes
- **Big trees take longer to restore.**
- **Many saves mean a bigger history.**
- **Only one person can edit at a time.**

**Large hierarchies** - Restoration time scales with size
**Frequent saves** - More versions = larger history table
**Concurrent edits** - Only one user can edit at a time

### Current Constraints
- The history is kept per tree, not for the whole interface.
- There are no branches. The history is one straight line.
- You cannot see the exact differences between two versions.

**Single tree focus** - Versions per tree, not per userinterface
**No branching** - Linear version history (no Git-style branches)
**No diffs** - Can't see exact changes between versions

</div>

---

## Configuration

Nothing needs to be set. The history works as soon as you save.

<div data-technical>

### Environment Variables

None are needed.

```bash
# No special configuration needed
# Uses existing database and API setup
```

### Database Cleanup (Optional)

You can delete the oldest versions to save space. Keep the last 50 per tree.

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

</div>

---

## Getting Started

### 1. Enable Version History
The history is already on. It starts working as soon as you save.

<div data-technical>

```bash
# Already enabled - works automatically on save
```

</div>

### 2. View and Restore a Version
Click **History** in the tree editor, pick a version and click restore. Confirm, and the tree reloads.

### 3. Monitor Usage

<div data-technical>

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

</div>

---

## Troubleshooting

A version is only made by a save that completes. If a restore fails, check that nobody else has the tree locked.

<div data-technical>

### Version Not Appearing
- **Check the save:** only a completed save creates a version.
- **Check your access:** you need permission to write to the database.
- **Check the logs:** look for save errors.

### Restore Failed
- **Check the version:** make sure the target version still exists.
- **Check your access:** confirm you can write to the database.
- **Check for locks:** make sure nobody else has the tree locked.

### Performance Issues
- **Large trees:** split them into smaller hierarchies.
- **Many versions:** set up a cleanup.
- **Several editors:** avoid editing at the same time.

</div>

---

**Navigation trees are now fully version controlled, with complete restoration.**

**Good for:** complex navigation testing, teamwork, change control, and never losing work.
