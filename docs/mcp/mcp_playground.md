# MCP Playground Tools

[← Back to MCP Documentation](./README.md)

---

## 🎤 MCP Playground - Web Interface (NEW!)

### Overview

The **MCP Playground** is a mobile-first web interface for executing MCP commands through natural language prompts with voice support. It provides a simplified, user-friendly alternative to the Test Case Builder for quick device automation.

**URL**: `https://dev.virtualpytest.com/builder/mcp-playground`

### Key Features

✅ **Voice-First Design**
- Web Speech API integration
- Real-time voice transcription
- Hold-to-speak button
- Automatic text-to-prompt conversion

✅ **Mobile-First Responsive**
- Single-column layout on mobile (< 768px)
- Two-column layout on tablet (768px - 1024px)
- Three-column layout on desktop (> 1024px)
- Large touch targets (56px on mobile, 40px on desktop)
- Collapsible sections for mobile

✅ **Discovery & Suggestions**
- Browse available actions, verifications, and navigation nodes
- Quick-action buttons for common commands
- Real-time device capability detection

✅ **AI-Powered Execution**
- Natural language prompt to executable command
- Automatic disambiguation handling
- Real-time execution progress
- Success/failure feedback

✅ **Command History**
- Persistent history (localStorage)
- Replay previous commands
- Success/failure indicators
- Last 50 commands stored

### User Interface Layout

#### Mobile Layout (< 768px)
```
┌─────────────────────────┐
│ 🎤 MCP Playground       │ ← Header
├─────────────────────────┤
│ Device Selection ▼      │ ← Collapsible
│ Prompt Input (large)    │ ← Full-width
│ 🎤 Voice | ⚡ Execute   │ ← Large buttons
│ Execution Result        │ ← Auto-expand
│ Quick Actions ▼         │ ← Collapsible
│ History ▼               │ ← Collapsible
└─────────────────────────┘
```

#### Desktop Layout (> 1024px)
```
┌───────────────────────────────────────────────────┐
│ 🎤 MCP Playground                                 │
├─────────────┬───────────────────┬─────────────────┤
│ Device      │   Prompt Input    │  Quick Actions  │
│ Selection   │                   │                 │
│             │   🎤 Voice        │  • Navigate...  │
│ [Control]   │   ⚡ Execute      │  • Screenshot   │
│             │                   │  • Swipe...     │
│             ├───────────────────┤                 │
│ History     │ Execution Result  │  [Show all ▾]  │
│             │                   │                 │
│ 1. Nav...   │ ✅ Success        │                 │
│ 2. Verify.. │ ⏱️  2.3s          │                 │
└─────────────┴───────────────────┴─────────────────┘
```

### Workflow

1. **Select Device**
   - Choose host, device ID, and interface from dropdowns
   - Device selector collapses on mobile, persistent on desktop

2. **Take Control**
   - Single button to lock device
   - Clear visual feedback (green = locked, gray = unlocked)
   - Control state persists across commands

3. **Enter Prompt**
   - Type in large text area (4 rows on mobile, 2 on desktop)
   - OR hold voice button to speak
   - Real-time voice transcription display

4. **Quick Actions (Optional)**
   - Browse available commands by category (Navigation, Actions, Verification)
   - Click to auto-fill prompt
   - Stats chips show available counts

5. **Execute**
   - Click "Execute" button (or Cmd/Ctrl + Enter)
   - AI generates test graph from prompt
   - Handles disambiguation automatically (modal popup)
   - Shows real-time progress bar during execution

6. **View Result**
   - Success/failure alert with duration
   - Step-by-step block status
   - Error messages if failed
   - Link to detailed report

7. **Replay from History**
   - Click any previous command to reload
   - Success/failure indicators
   - Timestamps (relative time)
   - Clear history button

### Component Architecture

```
MCPPlayground.tsx (Main Page)
├── MCPPlaygroundContext.tsx (State Management)
│   ├── Device selection & control
│   ├── Available options (interfaces, nodes, actions, verifications)
│   ├── AI prompt generation & execution
│   ├── Command history (localStorage)
│   └── Unified execution state
│
├── MCPDeviceSelector.tsx (Responsive)
│   ├── Host/device/interface dropdowns
│   ├── Take/Release control button
│   └── Collapsible on mobile
│
├── MCPPromptInput.tsx (Responsive)
│   ├── Large text input
│   ├── Voice button (Web Speech API)
│   ├── Real-time transcription
│   └── Execute button (Cmd/Ctrl + Enter)
│
├── MCPQuickActions.tsx (Responsive)
│   ├── Tabbed interface (Navigation, Actions, Verification)
│   ├── Quick-click suggestions
│   └── Stats chips
│
├── MCPExecutionResult.tsx (Responsive)
│   ├── Progress bar (during execution)
│   ├── Success/failure alert
│   ├── Block-by-block status
│   └── Report link
│
└── MCPCommandHistory.tsx (Responsive)
    ├── Last 50 commands
    ├── Replay button
    ├── Success/failure indicators
    └── Relative timestamps
```

### Voice Input Details

**Supported Browsers:**
- ✅ Chrome/Edge (desktop & mobile)
- ✅ Safari (iOS & macOS)
- ❌ Firefox (limited support)

**Usage:**
1. Click "Voice" button
2. Allow microphone access (browser will prompt)
3. Speak your command clearly
4. Watch real-time transcription
5. Click "Stop" to finish
6. Transcript auto-appends to prompt text

**Tips:**
- Speak slowly and clearly
- Use natural language (e.g., "Navigate to home and take a screenshot")
- Pause between phrases for better accuracy
- Background noise may affect accuracy

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + Enter` | Execute prompt |
| `Cmd/Ctrl + K` | Focus prompt input |
| `Escape` | Clear prompt (when focused) |

### Local Storage

The MCP Playground stores data locally in your browser:

```javascript
localStorage.setItem('mcp-playground-history', JSON.stringify([
  {
    timestamp: "2025-01-01T00:00:00Z",
    prompt: "Navigate to home",
    success: true,
    result: {...}
  }
]))
```

**Data Stored:**
- Last 50 commands
- Timestamps
- Success/failure status
- Result summaries

**Privacy:**
- Data stored locally only (not sent to server)
- Clear history anytime with "Clear" button
- Data persists across browser sessions

### Mobile Optimizations

✅ **Touch Targets:**
- Minimum 56px height on mobile
- Large button spacing (16px gaps)
- Full-width buttons on mobile

✅ **Font Sizes:**
- Body text: 16px (mobile) → 14px (desktop)
- Headers: 20px (mobile) → 16px (desktop)
- Inputs: 16px minimum (prevents iOS zoom)

✅ **Gestures:**
- Tap to expand/collapse sections
- Swipe-friendly dropdowns
- No hover states (click-only)

✅ **Performance:**
- Lazy-loaded components
- Debounced voice input
- Cached available options

### Use Cases

#### 1. Quick Smoke Test
```
1. Take control
2. Type: "Navigate to home and verify Replay button"
3. Execute
4. Done in seconds!
```

#### 2. Voice-Driven Testing (Mobile)
```
1. Take control
2. Hold voice button
3. Speak: "Swipe up three times and take a screenshot"
4. Release voice button
5. Execute
6. Perfect for on-the-go testing!
```

#### 3. Exploratory Testing
```
1. Browse Quick Actions
2. Click "Navigate to settings"
3. Execute
4. See available verifications
5. Click "Verify element exists"
6. Execute
7. Iterate quickly!
```

#### 4. Regression from History
```
1. Open History
2. Replay previous successful command
3. Verify still works
4. Fast regression testing!
```

### Comparison: MCP Playground vs Test Case Builder

| Feature | MCP Playground | Test Case Builder |
|---------|----------------|-------------------|
| **Focus** | Quick commands | Full test cases |
| **Interface** | Text prompt | Visual canvas |
| **Input** | Type or speak | Drag & drop blocks |
| **Mobile** | Optimized ✅ | Desktop-only |
| **Voice** | Built-in ✅ | Not available |
| **History** | Last 50 commands | Saved test cases |
| **Complexity** | Simple | Advanced |
| **Use Case** | Quick testing | Complex workflows |
| **Save** | Local history | Database |
| **Target** | Mobile-first | Desktop power users |

### Integration with MCP Tools

The MCP Playground uses the same backend MCP tools:

```
User Types Prompt
    ↓
MCPPlaygroundContext.handleGenerate()
    ↓
useTestCaseAI.generateTestGraph()
    ↓
Backend: /server/testcase/ai/generate
    ↓
Returns: Test graph JSON
    ↓
useTestCaseExecution.executeTestCase()
    ↓
Backend: /server/testcase/execute
    ↓
Waits for execution completion (socket push in frontend execution hook)
    ↓
Returns: Success/failure
    ↓
Display result + update history
```

**No new backend code needed!** The playground reuses all existing MCP tools and execution infrastructure.

### Best Practices

✅ **Discovery First:**
- Use `list_actions`, `list_verifications`, `list_navigation_nodes` to see what's available
- Browse Quick Actions before typing

✅ **Natural Language:**
- Write prompts as you would speak them
- Example: "Navigate to home and verify the Replay button exists"
- Not: "nav home verify Replay"

✅ **Voice Tips:**
- Use in quiet environment
- Speak clearly and slowly
- Review transcript before executing

✅ **Mobile Usage:**
- Collapse sections you're not using (saves screen space)
- Use voice input for hands-free testing
- Landscape mode recommended for tablets

✅ **History Management:**
- Review history periodically
- Clear failed commands
- Replay successful commands for regression

### Troubleshooting

**Voice Not Working:**
- Check browser supports Web Speech API (Chrome/Safari)
- Allow microphone access in browser settings
- Check microphone not muted
- Try Safari if Chrome fails on iOS

**Prompt Not Executing:**
- Ensure device control is active (green button)
- Check host/device/interface selected
- Verify backend server running
- Check network connectivity

**Disambiguation Modal Won't Close:**
- Select resolution from dropdown
- Click "Resolve" button
- Or click "Cancel" to abort

**History Not Saving:**
- Check browser allows localStorage
- Check not in Private/Incognito mode
- Try clearing browser cache
