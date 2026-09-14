# AI Tree Creation - Automated 2-Level Navigation Tree Generation

## Overview

AI Tree Creation automatically explores user interfaces and generates complete navigation trees with nodes, edges, and subtrees. The system uses a **UNIVERSAL algorithm** that works identically for mobile, web, TV, and STB platforms by focusing on **destinations (nodes)** and **navigation actions (edges)**.

**🎯 Fixed 2-Level Exploration:** The system always explores **2 levels deep**:
- **Level 1**: Main navigation items (Home, Settings, TV Guide, etc.)
- **Level 2**: Sub-navigation items (Settings → WiFi, Bluetooth, Account, etc.)

This provides an immediate, usable navigation tree without requiring configuration.

## Architecture: 3-Component Design

The AI generation flow uses **3 separate components** for clean separation of concerns:

```
┌─────────────────────────────────────────┐
│  AIGenerationModal (Phase 1)            │
│  ├─ Configuration (depth)               │
│  ├─ AI explores & analyzes screen       │
│  ├─ Shows plan preview                  │
│  └─ Buttons: Abort | Retry | Create     │
└──────────────┬──────────────────────────┘
               │ onStructureCreated()
               ▼
┌─────────────────────────────────────────┐
│  ValidationReadyPrompt (Transition)     │
│  ├─ "✅ Preview"                         │
│  ├─ Stats: X nodes, Y edges             │
│  └─ Button: Start Validation            │
└──────────────┬──────────────────────────┘
               │ Opens ValidationModal
               ▼
┌─────────────────────────────────────────┐
│  ValidationModal (Phase 2b)             │
│  ├─ Progress: Step X/Y                  │
│  ├─ Real-time test results (✅/❌)      │
│  ├─ Auto-tests each step                │
│  └─ Buttons: Confirm & Save | Cancel    │
└─────────────────────────────────────────┘
```

### Why 3 Components?

**Benefits:**
- ✅ **Single Responsibility**: Each component does ONE thing
- ✅ **Clean Transitions**: Visual feedback at each phase
- ✅ **Easy to Maintain**: Test and debug independently
- ✅ **Better UX**: User sees clear progress through workflow
- ✅ **No Complex State**: No nested conditions or complex logic

---

## Core Principle: The Universal Algorithm

**Navigation targets (buttons, tabs, menu items) are EDGES, not nodes.**

- **Node** = A destination screen we can ENTER
- **Edge** = The actions required to reach that destination

### Example (Mobile):
- "TV Guide Tab" is an **EDGE** (the button you click)
- `tvguide` is the **NODE** (the screen you reach after clicking)

### Example (TV/STB):
- "tv_guide" menu item is an **EDGE** (what you navigate to + OK)
- `tvguide` is the **NODE** (the screen you enter after pressing OK)

---

## Quick Start

### Prerequisites
1. **NavigationEditor** - Open for your tree (e.g., `example_mobile`)
2. **Device Control** - Take control of device (button must be active)
3. **Home Screen** - Ensure device is on a stable home screen

### Starting AI Generation
1. Open NavigationEditor for your tree
2. Select host and device
3. Click "Take Control" button
4. **AI Generate** button appears in header (only when control is active)
5. Click **AI Generate** to open exploration modal
6. Click **Start** (Phase 1: Analysis) - No configuration needed!
   - The system automatically explores **2 levels** (main + sub-items)

---

## The 3-Phase Workflow

### Phase 1: Analysis (AI Anticipation)

**What happens:**
- System analyzes the home screen
- **Mobile/Web**: Parses UI dump to find clickable elements
- **TV/STB**: Uses AI vision to identify menu items

**You'll see:**
- Screenshot of home screen
- List of navigation targets found (chips)
- AI reasoning about interface structure

**Your Decision:**
- ✅ **Create Nodes** → Proceed to Phase 2a
- 🔄 **Retry** → Re-analyze with new screenshot
- ❌ **Abort** → Cancel without changes

---

### Phase 2a: Structure Creation (2-Level Exploration)

**What happens (automatically after approval):**
- Creates `home_temp` node (root)
- **For each level-1 item:**
  1. Click level-1 item (e.g., "Settings")
  2. Analyze screen for level-2 items
  3. Create level-1 node: `settings_temp`
  4. **For each level-2 item found:**
     - Click level-2 item (e.g., "WiFi")
     - Press BACK to level-1
     - Create level-2 node with parent prefix: `settings_wifi_temp`
     - Create level-2 edge: `settings_temp` ↔ `settings_wifi_temp`
  5. Press BACK to home
  6. Create level-1 edge: `home_temp` ↔ `settings_temp`
  7. Create subtree: `settings` (if level-2 nodes exist)
- **Batch saves all nodes and edges**

**Node Naming (parent_child format):**
```
Level 1:
"Settings Tab" → settings_temp

Level 2 (with parent prefix):
"WiFi" → settings_wifi_temp
"Bluetooth" → settings_bluetooth_temp
"Account" → settings_account_temp

Another Level 1:
"TV Guide Tab" → tvguide_temp

Level 2 (with parent prefix):
"Channels" → tvguide_channels_temp
"Favorites" → tvguide_favorites_temp
```

**Rules:**
- Level-1 nodes: Remove "Tab", "Register", "Button", lowercase, underscore
- Level-2 nodes: `{parent}_{child}` format (e.g., `settings_wifi`)
- Subtrees: Created automatically for level-1 nodes with level-2 children

**Performance:** Completes in ~60-120 seconds for 10 level-1 items with 5 level-2 items each

**You'll see:**
- `X level-1 nodes created`
- `Y level-2 nodes created`
- `Z edges created`
- `N subtrees created`
- All with `_temp` suffix

**Your Decision:**
- ✅ **Start Validation** → Proceed to Phase 2b
- ❌ **Cancel** → Delete temp structure

---

### Phase 2b: Validation (INFORMATIVE ONLY)

**Modal: ValidationModal (small, fixed top-right corner)**

**Purpose:** Test if the created actions work correctly (INFORMATIVE - does NOT modify edges)

**What happens (auto-running test):**

For each edge, system tests navigation:

#### Mobile/Web:
```
1. Execute saved action: click_element("TV Guide Tab")
2. Wait 2s
3. Check if screen changed → Show ✅ or ❌
4. Execute saved action: press_key(BACK)
5. Check if returned home → Show ✅ or ⚠️
```

#### TV/STB:
```
1. Execute saved action: press_key(RIGHT) + press_key(OK)
2. Wait 2s
3. Check if screen changed (AI vision) → Show ✅ or ❌
4. Execute saved action: press_key(BACK)
5. Check if returned (AI vision) → Show ✅ or ⚠️
```

**Modal behavior:**
- Small, fixed to top-right corner
- No shadow
- Watch ReactFlow graph (edges already created with actions!)
- Modal just shows TESTING results

**Progress display:**
```
🔄 Testing 3/10

Step 1: "TV Guide Tab"
  Step 1.1 (Forward): home → tvguide
  ✅ SUCCESS (click_element "TV Guide Tab")
  
  Step 1.2 (Backward): tvguide → home  
  ✅ SUCCESS (press_key BACK)
```

**When complete:**
- ✅ **Confirm & Save** → Remove `_temp` suffix, make permanent
- ❌ **Cancel & Delete** → Delete all `_temp` nodes/edges

**User can decide** after seeing test results! If too many failures → Cancel instead of saving.

---

## How the Universal Algorithm Works

### Key Insight: Edges vs Nodes

**OLD thinking (WRONG):**
- Every clickable element = a node
- Causes confusion between focus states and actual screens

**NEW thinking (CORRECT):**
- Clickable element = an EDGE (action to navigate)
- New screen entered = a NODE (destination)

---

### Phase 1: Analysis

#### For Mobile/Web:
```python
1. Parse UI dump (XML for Android, JSON for web)
2. Extract clickable elements:
   ["TV Guide Tab", "Replay Register", "Search Button", ...]
3. Strip accessibility hints (preserves element identifiers):
   "Live TV Tab, Double-tap to Open" → "Live TV Tab"
   "TV guide Tab currently selected" → "TV guide Tab"
4. Filter out and SKIP entirely:
   - Non-interactive elements (checked via clickable property)
   - Generic labels ("image", "icon", "loading")
   - Dynamic content (> 30 chars, or contains price/date patterns)
   NOTE: Dynamic content is SKIPPED, not renamed to "dynamic_X"
5. Return list of static navigation targets only (max 20)
```

#### For TV/STB:
```python
1. Capture screenshot
2. AI vision analysis:
   "List all visible menu items line by line"
3. Extract menu items:
   ["home", "tv_guide", "replay", "search", ...]
4. Return list of navigation targets
```

---

### Phase 2a: 2-Level Exploration

**Protection against duplicate nodes:**
- Before exploring each item, system checks if node already exists
- If node exists (important for subtrees re-exploration), skips that item
- Saves time and prevents unnecessary device interactions

**For each level-1 navigation target:**

```python
# 0. Check if node already exists (duplicate protection)
target_level1 = "Settings Tab"
node_level1 = "settings_temp"

if node_exists(node_level1):
    print("⏭️ Node already exists - skipping")
    continue

# 1. Click level-1 item
click_element(target_level1)
wait(2s)

# 2. Generate level-1 node name
node_level1 = "settings_temp"

# 3. Analyze screen for level-2 items
level2_items = parse_ui_dump()  # ["WiFi", "Bluetooth", "Account", ...]

# 4. For each level-2 item:
for level2_item in level2_items:
    # 4.0. Check if level-2 node exists (duplicate protection)
    node_level2 = f"settings_{level2_item.lower()}_temp"
    
    if node_exists(node_level2):
        print("⏭️ Node already exists - skipping")
        continue
    
    # 4.1. Click level-2 item
    click_element(level2_item)  # "WiFi"
    wait(2s)
    
    # 4.2. Press BACK to level-1
    press_key(BACK)
    wait(2s)
    
    # 4.3. Generate level-2 node name with parent prefix
    node_level2 = f"settings_wifi_temp"  # parent_child format!
    
    # 4.4. Create level-2 node
    create_node(
        id=node_level2,
        label="settings_wifi",
        position=calculated
    )
    
    # 4.5. Create level-2 edge WITH actions (not empty!)
    create_edge(
        id="edge_settings_temp_to_settings_wifi_temp",
        source="settings_temp",
        target="settings_wifi_temp",
        action_sets=[
            {
                id: "settings_to_settings_wifi",
                actions: [
                    {"command": "click_element", "params": {"text": "WiFi"}, "delay": 2000}
                ]
            },
            {
                id: "settings_wifi_to_settings",
                actions: [
                    {"command": "press_key", "params": {"key": "BACK"}, "delay": 2000}
                ]
            }
        ]
    )

# 5. Press BACK to home from level-1
press_key(BACK)
wait(2s)

# 6. Create level-1 node
create_node(
    id="settings_temp",
    label="settings",
    position=calculated
)

# 7. Create level-1 edge
create_edge(
    id="edge_home_temp_to_settings_temp",
    source="home_temp",
    target="settings_temp",
    action_sets=[...]
)

# 8. Create subtree (if level-2 nodes exist)
if level2_nodes_created:
    create_sub_tree(
        parent_node="settings_temp",
        name="settings_subtree"
    )
```

**Key Point:** All nodes and edges are created WITH actions already filled in!

---

### Phase 2b: Testing (INFORMATIVE ONLY!)

**The testing algorithm (does NOT modify edges):**

```python
for each target in navigation_targets:
    
    node_name = target_to_node_map[target]
    edge = get_edge(f"edge_home_temp_to_{node_name}_temp")
    
    # Edge already has actions! We just TEST them
    forward_actions = edge.action_sets[0].actions
    backward_actions = edge.action_sets[1].actions
    
    # ═══════════════════════════════════════
    # STEP 1: TEST FORWARD ACTION
    # ═══════════════════════════════════════
    
    try:
        execute(forward_actions)
        wait(2s)
        
        if screen_changed():
            forward_result = "✅ SUCCESS"
        else:
            forward_result = "❌ FAILURE - screen didn't change"
    except Exception as e:
        forward_result = f"❌ FAILURE - {e}"
    
    # ═══════════════════════════════════════
    # STEP 2: TEST BACKWARD ACTION
    # ═══════════════════════════════════════
    
    try:
        execute(backward_actions)
        wait(2s)
        
        if back_to_home():
            backward_result = "✅ SUCCESS"
        else:
            backward_result = "⚠️ WARNING - not back home"
    except Exception as e:
        backward_result = f"❌ FAILURE - {e}"
    
    # ═══════════════════════════════════════
    # STEP 3: SHOW RESULTS (don't modify edge!)
    # ═══════════════════════════════════════
    
    print(f"Step {idx}.1 (Forward): {source} → {target}")
    print(f"  {forward_result} ({forward_actions})")
    
    print(f"Step {idx}.2 (Backward): {target} → {source}")
    print(f"  {backward_result} ({backward_actions})")
```

**Key Point:** Testing is INFORMATIVE. Edges keep their actions regardless of test results!

---

## Element Filtering & Cleaning

### Accessibility Text Stripping (Phase 1)

**Problem:** UI elements often include accessibility hints that interfere with navigation:
- `"Live TV Tab, Double-tap to Open"` ❌ (comma triggers dynamic content filter)
- `"TV guide Tab currently selected"` ❌ (too long)

**Solution:** Strip accessibility hints BEFORE checking for dynamic content:

```python
accessibility_patterns = [
    ', Double-tap to Open',      # Accessibility instruction
    ', Double-tap to activate',   # Accessibility instruction
    ', Double-tap to select',     # Accessibility instruction
    ' currently selected',        # UI state
]

# Apply cleaning
for pattern in accessibility_patterns:
    if pattern.lower() in label.lower():
        label = re.sub(re.escape(pattern), '', label, flags=re.IGNORECASE).strip()

# Clean up trailing commas/spaces
label = label.rstrip(',').strip()
```

**Result:**
- `"Live TV Tab, Double-tap to Open"` → `"Live TV Tab"` ✅
- `"TV guide Tab currently selected"` → `"TV guide Tab"` ✅
- `"Search channel. Button"` → `"Search channel. Button"` ✅

**Important:** We ONLY strip instructions/state, NOT element types like "Tab" or "Button" - these are part of the identifier needed for clicking!

### Dynamic Content Detection (Phase 1)

**What is dynamic content?**
- Program titles: "Escape to the Country BBC One HD 6 November 16:00"
- Prices: "Premium Plan - $9.99/month"
- Descriptions: Long text > 30 characters with dates/times

**Detection rules:**
```python
# After stripping accessibility text, check for dynamic patterns
dynamic_indicators = [
    'available for replay', 'watch now', 'continue watching',
    'chf', 'usd', 'eur', 'gbp', '$', '€', '£',  # Prices
    ' from ', ' to ',  # Time/price ranges
    'season ', 'episode ', 's0', 'e0',  # TV series
    ','  # Remaining commas (after accessibility stripping)
]

# If label > 30 chars OR contains dynamic indicators
if len(label) > 30 or any(indicator in label.lower() for indicator in dynamic_indicators):
    continue  # SKIP entirely - don't create node
```

**Important:** Dynamic content is **SKIPPED entirely**, NOT renamed to `dynamic_1`, `dynamic_2`, etc.

**Why skip instead of rename?**
- ❌ Can't click on `"dynamic_1"` - it doesn't exist in the UI
- ❌ Creates useless action sets like `click_element(text="dynamic_1")`
- ❌ Wastes exploration time on non-navigable content
- ✅ Only real, clickable navigation elements are included

**Examples:**

| Element Text | After Cleaning | Result |
|-------------|----------------|--------|
| `"Live TV Tab, Double-tap to Open"` | `"Live TV Tab"` | ✅ Kept (navigation) |
| `"TV guide Tab currently selected"` | `"TV guide Tab"` | ✅ Kept (navigation) |
| `"Escape to the Country BBC One HD, Available for replay"` | (cleaned) | ❌ Skipped (dynamic - has comma + replay keyword) |
| `"Lost and Found in the Lakes BBC One HD 6 November 15:30"` | (cleaned) | ❌ Skipped (dynamic - > 30 chars + date) |
| `"Search channel. Button"` | `"Search channel. Button"` | ✅ Kept (navigation) |

---

## Screen Change Detection

### Mobile/Web:
```python
def screen_changed() -> bool:
    """Check if we left the home screen"""
    # Get all navigation targets from Phase 1
    home_elements = ["Home Tab", "TV Guide Tab", "Replay Tab", ...]
    
    # Try to find any of them
    for element in home_elements:
        if wait_for_element(element, timeout=1):
            return False  # Still see home element = still on home
    
    return True  # All home elements gone = entered new screen
```

### TV/STB:
```python
def screen_changed() -> bool:
    """Check if screen is different using AI vision"""
    current_screenshot = capture_screenshot()
    
    # Ask AI: "Is this a different screen from home?"
    is_different = ai_vision_compare(
        home_screenshot,
        current_screenshot
    )
    
    return is_different
```

### Verify Return to Home:
```python
def back_to_home() -> bool:
    """Check if we returned to home screen"""
    # Mobile/Web: Check if first navigation target is visible
    home_indicator = navigation_targets[0]  # e.g., "Home Tab"
    return wait_for_element(home_indicator, timeout=5)
    
    # TV/STB: Compare screenshot with original home screenshot
    return ai_vision_compare(current_screenshot, home_screenshot)
```

---

## Platform Comparison

| Aspect | Mobile/Web | TV/STB |
|--------|------------|--------|
| **Level-1 Navigation** | Click once | Direction + OK |
| **Level-2 Navigation** | Click once | Direction + OK |
| **Entry** | Immediate | After OK press |
| **Discovery** | UI Dump parsing | AI Vision |
| **Validation** | Same (screen_changed?) | Same (screen_changed?) |
| **Return** | Same (BACK key) | Same (BACK key) |
| **Depth** | **FIXED at 2 levels** | **FIXED at 2 levels** |
| **Naming** | `parent_child` | `parent_child` |

---

## Node Naming Convention

### Level-1 Nodes: Target → Node Name

**Function:**
```python
def target_to_node_name(target_text: str) -> str:
    """
    Convert navigation target to node name
    
    Examples:
    "TV Guide Tab" → "tvguide"
    "Replay Register" → "replay"
    "Films & Series" → "movies_and_series"
    "Aktuell gewählte Registerkarte Settings" → "settings"
    """
    text = target_text.lower()
    
    # Remove common words
    remove_words = [
        'tab', 'register', 'button', 'screen', 'menu', 'page',
        'aktuell gewählte registerkarte',  # "currently selected tab" (German)
        'currently selected',
        'doppeltippen zum öffnen',  # "double tap to open" (German)
        'double tap to',
    ]
    
    for word in remove_words:
        text = text.replace(word, ' ')
    
    # Replace special chars with underscore
    text = re.sub(r'[^a-z0-9]+', '_', text)
    
    # Clean up
    text = re.sub(r'_+', '_', text)  # Remove consecutive underscores
    text = text.strip('_')  # Strip leading/trailing
    
    return text or 'unknown'
```

### Level-2 Nodes: parent_child Format

**Level-2 nodes always use the parent prefix:**

```python
def generate_level2_node_name(parent_node: str, child_text: str) -> str:
    """
    Generate level-2 node name with parent prefix
    
    Examples:
    parent="settings_temp", child="WiFi" → "settings_wifi_temp"
    parent="tvguide_temp", child="Channels" → "tvguide_channels_temp"
    """
    parent_base = parent_node.replace('_temp', '')
    child_base = target_to_node_name(child_text)
    return f"{parent_base}_{child_base}_temp"
```

**Examples:**
```
Level 1: "Settings Tab" → settings_temp
  Level 2: "WiFi" → settings_wifi_temp
  Level 2: "Bluetooth" → settings_bluetooth_temp
  Level 2: "Display" → settings_display_temp

Level 1: "TV Guide Tab" → tvguide_temp
  Level 2: "Channels" → tvguide_channels_temp
  Level 2: "Favorites" → tvguide_favorites_temp
  Level 2: "Search" → tvguide_search_temp
```

---

## Benefits of 2-Level Fixed Exploration

1. **No Configuration Needed**: Click and go - no depth to set
2. **Complete Tree Immediately**: Get usable navigation structure in one run
3. **Automatic Organization**: Subtrees created automatically with logical structure
4. **Parent-Child Naming**: Clear relationship (`settings_wifi`, `settings_bluetooth`)
5. **Works Everywhere**: Mobile, web, TV, STB - same 2-level logic
6. **Time Efficient**: 60-120 seconds for complete 2-level structure
7. **Predictable**: Always know what you'll get (main + sub-items)
8. **Smart Filtering**: 
   - ✅ Strips accessibility hints while preserving element identifiers
   - ✅ Skips dynamic content (program titles, prices) automatically
   - ✅ Only includes real, clickable navigation elements
9. **Duplicate Protection**: 
   - ✅ Checks if nodes already exist before exploring
   - ✅ Important for subtree re-exploration
   - ✅ Saves time and prevents unnecessary device interactions

---

## How the 2-Level Algorithm Works

### Key Principle

**Navigation targets (buttons, tabs, menu items) are EDGES, not nodes.**

- **Node** = A destination screen we can ENTER
- **Edge** = The actions required to reach that destination
- **Level 1** = Main navigation destinations
- **Level 2** = Sub-navigation within each level-1 destination

---

1. **Works everywhere**: Mobile, web, TV, STB - same logic
2. **Simple**: Edges = actions, Nodes = destinations
3. **No intermediate states**: Only care about screens we can ENTER
4. **Robust**: Tests both forward and reverse navigation
5. **Accurate**: Names derived from actual UI elements
6. **Efficient**: Creates structure first, validates incrementally
7. **Transparent**: User sees real-time progress
8. **Smart Filtering**: Only real navigation elements (skips dynamic content)
9. **Duplicate Protection**: Prevents re-exploration of existing nodes

---

## Frontend Architecture

### Component Structure

**1. AIGenerationModal** (`frontend/src/components/navigation/AIGenerationModal.tsx`)
- **Phase 1**: Exploration & Approval
- Shows configuration (depth input)
- Displays AI analysis results
- Shows screenshot + plan preview
- Buttons: Abort, Retry, Create Nodes
- Closes after structure creation

**2. ValidationReadyPrompt** (`frontend/src/components/navigation/ValidationReadyPrompt.tsx`)
- **Transition**: Between Phase 2a and 2b
- Small prompt in top-right corner
- Shows nodes/edges created count
- Blinking "Start Validation" button
- Can cancel to abort workflow

**3. ValidationModal** (`frontend/src/components/navigation/ValidationModal.tsx`)
- **Phase 2b**: Testing (Informative)
- Small modal in top-right corner
- Auto-starts testing on mount
- Shows progress (Step X/Y)
- Displays real-time test results (✅/❌)
- Step X.1 (Forward): source → target
- Step X.2 (Backward): target → source
- Auto-continues through all steps
- **Two buttons when complete**:
  - ✅ **Confirm & Save** → Rename _temp to permanent
  - ❌ **Cancel & Delete** → Delete all _temp nodes/edges

### State Management

**NavigationEditor orchestrates all 3 components:**

```typescript
// Phase 1: AIGenerationModal
const [isAIGenerationOpen, setIsAIGenerationOpen] = useState(false);

// Transition: ValidationReadyPrompt
const [showValidationPrompt, setShowValidationPrompt] = useState(false);
const [validationNodesCount, setValidationNodesCount] = useState(0);
const [validationEdgesCount, setValidationEdgesCount] = useState(0);
const [explorationId, setExplorationId] = useState<string | null>(null);
const [explorationHostName, setExplorationHostName] = useState<string | null>(null);

// Phase 2b: ValidationModal
const [isValidationModalOpen, setIsValidationModalOpen] = useState(false);
```

**Flow:**
1. User clicks "AI Generate" → opens `AIGenerationModal`
2. After structure creation → closes modal, shows `ValidationReadyPrompt`
3. User clicks "Start Validation" → opens `ValidationModal`
4. Testing shows ✅/❌ for each step
5. User decides:
   - ✅ **Confirm & Save** → Remove _temp suffix, permanent nodes/edges
   - ❌ **Cancel & Delete** → Delete all _temp, nothing saved

---

## Technical Implementation

### Backend Routes

**`/start-exploration` (Phase 1)**
- Captures screenshot
- Analyzes with UI dump (mobile/web) or AI vision (TV/STB)
- Returns list of navigation targets
- Status: `awaiting_approval`

**`/continue-exploration` (Phase 2a)**
- Creates `home_temp` node
- Creates destination nodes for each target (using `target_to_node_name`)
- Creates edges with ACTIONS FILLED IN (not empty!)
- Stores `target_to_node_map`
- Status: `structure_created`

**`/start-validation` (Phase 2b init)**
- Initializes validation index
- Status: `awaiting_validation`

**`/validate-next-item` (Phase 2b loop)**
- Gets current target from list
- Looks up node name from mapping
- Gets edge (already has actions!)
- Tests forward action → Show ✅ or ❌
- Tests backward action → Show ✅ or ⚠️
- Does NOT modify edge
- Increments index
- Status: `awaiting_validation` or `validation_complete`

---

## Troubleshooting

### Phase 1: No items found
- **Mobile/Web**: Check if UI dump is working (`dump_elements()`)
- **TV/STB**: Check if screenshot is captured and AI vision is responding

### Phase 2a: Nodes not created
- Check console logs for database errors
- Verify `target_to_node_name()` is generating valid node names
- Check that edges are created with correct action format:
  ```json
  {"command": "click_element", "params": {"text": "..."}, "delay": 2000}
  ```

### Phase 2b: Test failures
- **If forward test fails**: Element text may have changed - check UI dump
- **If backward test fails**: Try different BACK strategy or check home detection
- **Important**: Test failures don't break the workflow! Edges keep their actions.

### Edges show "No action selected"
- This was a bug in older versions (action format mismatch)
- Fixed in Phase 2a - edges now use correct format: `{"command": ..., "params": ...}`
- If still seeing this, check backend logs for edge creation

---

## Future Enhancements

1. **Level-3 exploration**: Option to go deeper for specific subtrees
2. **Multiple AI models**: Allow user to select from 3 OpenRouter vision models
3. **Edge confidence scores**: Rate edge quality based on validation success
4. **Smart retry**: If edge fails, try alternative navigation sequences
5. **Parallel exploration**: Explore multiple level-1 items simultaneously
6. **Custom naming rules**: Allow user-defined naming patterns
