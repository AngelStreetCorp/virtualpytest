# AI Exploration Tools (7 tools) 🤖 **RECOMMENDED**

**AI-powered navigation tree building** - Automates the entire tree creation process.

---

## 🎯 Quick Workflow

### Automated Tree Building (RECOMMENDED):
```
1. start_ai_exploration → AI analyzes screen and proposes structure
2. approve_exploration_plan → Creates all nodes/edges in batch
3. validate_exploration_edges → Tests all edges sequentially  
4. get_node_verification_suggestions → AI suggests verifications
5. approve_node_verifications → Applies verifications to nodes
6. finalize_exploration → Removes _temp suffixes
```

### Manual Tree Building (Advanced):
```
1. dump_ui_elements → Inspect screen
2. analyze_screen_for_action → Get selector
3. create_node + create_edge → Build manually
4. execute_edge → Test individually
```

---

## When to Use AI vs Manual

| Scenario | Recommendation |
|----------|---------------|
| **New app exploration** | ✅ AI Exploration (3 steps) |
| **TV/STB dual-layer** | ✅ AI Exploration (handles automatically) |
| **Bulk node creation** | ✅ AI Exploration (creates all at once) |
| **Specific edge fix** | ⚠️ Manual (update_edge) |
| **Complex custom flow** | ⚠️ Manual (full control) |

---

## Tool Reference

### 1. `start_ai_exploration`

Start AI-powered exploration of a userinterface.

**What it does:**
1. Captures screenshot of home screen
2. Analyzes UI elements (buttons, tabs, menus)
3. Detects strategy (click for mobile/web, D-pad for TV)
4. Proposes nodes and edges structure
5. Returns plan for your approval

**Parameters:**
- `userinterface_name` (required): Interface to explore
- `tree_id` (optional): Auto-detected from userinterface
- `team_id` (optional): Defaults to team_1
- `original_prompt` (optional): Your goal/intent

**Returns:**
- `exploration_id`: For polling status
- `exploration_plan`: Proposed items to create
- `strategy`: 'click' (mobile/web) or 'dpad' (TV)
- `screenshot`: Visual of analyzed screen

**Example:**
```python
# Step 1: Get compatible host/device
hosts = get_compatible_hosts(userinterface_name='sauce-demo')

# Step 2: Start exploration
result = start_ai_exploration(
  userinterface_name='sauce-demo',
  original_prompt='Build navigation for e-commerce site'
)

# Step 3: Review plan
print(result['exploration_plan']['items'])
# Output: ['login', 'signup', 'search', 'cart', ...]
```

**Time Saved:**
- Manual: 10+ steps per edge × N edges
- AI: 1 call → Full plan in seconds

---

### 2. `get_exploration_status`

Poll AI exploration progress.

**Returns status:**
- `'exploring'`: AI analyzing screen
- `'awaiting_approval'`: Plan ready for review
- `'structure_created'`: Nodes/edges created
- `'validating'`: Testing edges
- `'validation_complete'`: Ready for finalization

**Example:**
```python
status = get_exploration_status(
  exploration_id='uuid',
  host_name='host1'
)

if status['status'] == 'awaiting_approval':
  # Review plan
  print(status['exploration_plan']['items'])
```

---

### 3. `approve_exploration_plan`

Approve AI plan and create navigation structure.

**What it creates:**
- All nodes in batch
- All edges with proper selectors
- Bidirectional navigation
- Platform-specific actions

**TV Dual-Layer (Automatic):**
- Focus nodes: `home_tvguide`, `home_apps`
- Screen nodes: `tvguide`, `apps`
- Edges: RIGHT/LEFT (horizontal), OK/BACK (vertical)

**Mobile/Web (Automatic):**
- Screen nodes: `login`, `signup`, `search`
- Edges: click_element + BACK

**Parameters:**
- `exploration_id` (required)
- `host_name` (required)
- `userinterface_name` (required)
- `selected_items` (optional): Which items to create
- `selected_screen_items` (optional): TV only - which screen nodes

**Example:**
```python
# Approve all items
result = approve_exploration_plan(
  exploration_id='uuid',
  host_name='host1',
  userinterface_name='sauce-demo'
)
print(f"Created: {result['nodes_created']} nodes, {result['edges_created']} edges")

# Or select specific items
result = approve_exploration_plan(
  exploration_id='uuid',
  host_name='host1',
  userinterface_name='sauce-demo',
  selected_items=['login', 'signup', 'search']
)
```

---

### 4. `validate_exploration_edges`

Auto-validate all created edges by testing them sequentially.

**What it tests:**
1. Execute forward action (click or D-pad)
2. Capture screenshot (visual proof)
3. Execute reverse action (BACK or LEFT)
4. Verify return to origin

**TV Validation (Depth-first):**
```
1. home → home_tvguide: RIGHT
2. home_tvguide ↓ tvguide: OK (screenshot)
3. tvguide ↑ home_tvguide: BACK
4. Repeat for next item
```

**Mobile/Web Validation:**
```
1. home → login: click (screenshot)
2. login → home: BACK
```

**Example:**
```python
# Start validation
result = validate_exploration_edges(
  exploration_id='uuid',
  host_name='host1',
  userinterface_name='sauce-demo'
)

# Poll until complete
while result.get('has_more_items'):
  print(f"Tested: {result['item']} - {result['click_result']}")
  result = validate_exploration_edges(...)

print("Validation complete!")
```

---

### 5. `get_node_verification_suggestions`

Get AI-suggested verifications for created nodes.

Analyzes UI dumps captured during validation to find unique elements per node.

**Returns:**
- Suggested verifications with confidence scores
- Uniqueness validation
- Ready-to-use verification parameters

**Example:**
```python
suggestions = get_node_verification_suggestions(
  exploration_id='uuid',
  host_name='host1'
)

for suggestion in suggestions['suggestions']:
  print(f"Node: {suggestion['node_id']}")
  print(f"Verification: {suggestion['verification']}")
```

---

### 6. `approve_node_verifications`

Apply AI-suggested verifications to nodes.

Adds verifications + screenshots to nodes for reliable detection.

**Example:**
```python
result = approve_node_verifications(
  exploration_id='uuid',
  host_name='host1',
  userinterface_name='sauce-demo',
  approved_verifications=suggestions['suggestions']
)

print(f"Updated {result['nodes_updated']} nodes")
```

---

### 7. `finalize_exploration`

Finalize exploration by removing _temp suffixes.

**This is the final step** - makes all nodes and edges permanent.

**Example:**
```python
result = finalize_exploration(
  exploration_id='uuid',
  host_name='host1',
  tree_id='tree-uuid'
)

print(f"Finalized: {result['nodes_renamed']} nodes, {result['edges_renamed']} edges")
```

---

## Complete Example: Sauce Demo

```python
# Step 0: Get compatible host/device
hosts = get_compatible_hosts(userinterface_name='sauce-demo')
host_name = hosts['recommended_host']
device_id = hosts['recommended_device']

# Step 1: Start AI exploration
result = start_ai_exploration(
  userinterface_name='sauce-demo',
  original_prompt='Build e-commerce navigation'
)
exploration_id = result['exploration_id']

# Step 2: Review and approve plan
result = approve_exploration_plan(
  exploration_id=exploration_id,
  host_name=host_name,
  userinterface_name='sauce-demo',
  selected_items=['login', 'signup', 'search', 'cart']
)

# Step 3: Validate all edges
while True:
  result = validate_exploration_edges(
    exploration_id=exploration_id,
    host_name=host_name,
    userinterface_name='sauce-demo'
  )
  if not result.get('has_more_items'):
    break

# Step 4: Get verification suggestions
suggestions = get_node_verification_suggestions(
  exploration_id=exploration_id,
  host_name=host_name
)

# Step 5: Apply verifications
approve_node_verifications(
  exploration_id=exploration_id,
  host_name=host_name,
  userinterface_name='sauce-demo',
  approved_verifications=suggestions['suggestions']
)

# Step 6: Finalize
nodes = list_navigation_nodes(userinterface_name='sauce-demo')
tree_id = nodes['tree_id']

finalize_exploration(
  exploration_id=exploration_id,
  host_name=host_name,
  tree_id=tree_id
)

print("🎉 Navigation tree complete and ready!")
```

---

## Time Comparison

| Task | Manual Approach | AI Exploration |
|------|----------------|----------------|
| **Analyze screen** | Visual inspection | Automatic (1s) |
| **Find selectors** | Trial and error | AI analysis |
| **Create nodes** | 1 at a time | Batch creation |
| **Create edges** | 1 at a time + test | Batch creation |
| **Test edges** | Manual per edge | Sequential auto-test |
| **Add verifications** | Manual inspection | AI suggestion |
| **Total for 5 nodes** | ~2-3 hours | ~10-15 minutes |

**Time Saved: ~90%** for typical apps

---

## Prerequisites

1. **Userinterface must exist:**
   ```python
   create_userinterface(
     name='sauce-demo',
     device_model='host_vnc'
   )
   ```

2. **Device must be on home screen:**
   ```python
   # Navigate to home first if needed
   navigate_to_node(
     userinterface_name='sauce-demo',
     target_node_label='home'
   )
   ```

3. **Get compatible host/device:**
   ```python
   hosts = get_compatible_hosts(userinterface_name='sauce-demo')
   ```

---

## Error Handling

### Common Issues

**"No exploration found"**
- Cause: Exploration ID expired or invalid
- Fix: Start new exploration

**"Navigation to home failed"**
- Cause: Entry → home edge not configured
- Fix: Create/test entry → home edge first

**"Edge validation failed"**
- Cause: Selector changed or ambiguous
- Fix: Review failed edge, update selector manually

**"No unique verifications found"**
- Cause: Screen has no unique elements
- Fix: Add manual verifications or use image verification

---

## Advanced Usage

### Custom Item Selection (TV)

```python
# Only create focus nodes, skip screens
approve_exploration_plan(
  exploration_id='uuid',
  host_name='host1',
  userinterface_name='netflix_tv',
  selected_items=['tv guide', 'apps', 'search'],
  selected_screen_items=[]  # No screen nodes
)
```

### Partial Validation

```python
# Validate one edge at a time for debugging
result = validate_exploration_edges(...)
print(f"Edge: {result['item']}")
print(f"Screenshot: {result['screenshot_url']}")
# Fix issues before continuing
```

### Manual Verification Override

```python
# Get suggestions
suggestions = get_node_verification_suggestions(...)

# Modify before applying
custom_suggestions = suggestions['suggestions']
custom_suggestions[0]['verification']['params'] = {'search_term': 'custom-selector'}

# Apply modified verifications
approve_node_verifications(approved_verifications=custom_suggestions)
```

---

## See Also

- [Tree Tools](mcp_tools_tree.md) - Manual node/edge creation
- [Screen Analysis Tools](mcp_tools_screen_analysis.md) - Selector analysis
- [Navigation Tools](mcp_tools_navigation.md) - Navigate to nodes
- [UserInterface Tools](mcp_tools_userinterface.md) - Create userinterfaces

---

**Recommendation:** Start with AI Exploration for all new apps. Only use manual tools for edge cases or specific fixes.

