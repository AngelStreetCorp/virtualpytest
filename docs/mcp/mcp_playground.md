# MCP Playground Tools

[← Back to MCP Documentation](./README.md)

---

## MCP Playground - Web Interface

### Overview

The **MCP Playground** controls a device with plain-language requests, typed or spoken. It works well on a phone. It is a quicker alternative to the Test Case Builder for simple tasks.

**URL**: `https://dev.virtualpytest.com/builder/mcp-playground`

### Key Features

- **Voice first**: speak your request, and the words appear as you talk.
- **Works on phones**: the page fits the screen, with large buttons.
- **Run requests with AI**: your request becomes a command. If it could mean more than one thing, you choose.
- **Command history**: the last 50 requests, ready to run again.

<div data-technical>

Layout breakpoints: below 768px one column, 768px to 1024px two columns, above 1024px three columns. Touch targets are 56px on mobile and 40px on desktop. History is stored in `localStorage` (see below).

</div>

### User Interface Layout

One column on a phone, three on a computer. A phone shows the sections one under another.

<div data-technical>

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

</div>

### Workflow

1. **Select a device**: pick the host, the device and the interface.
2. **Take control**: the button locks the device to you. Green means locked.
3. **Enter a request**: type it, or hold the voice button and speak.
4. **Run it**: click "Execute", or press Cmd/Ctrl + Enter.
5. **See the result**: whether it worked, and a link to the full report.
6. **Run an earlier request again**: click it in the history.

<div data-technical>

- Step 1: host, device and interface are drop-down lists. On a phone the device picker folds away.
- Step 2: the lock stays in place across commands.
- Step 3: the text box has 4 rows on a phone and 2 on a computer.
- Step 4: the platform builds a test from your request. A progress bar shows while it runs. Quick actions are grouped as Navigation, Actions and Verification, with counts.
- Step 5: each step shows its status, and errors are shown if it failed.
- Step 6: each entry shows whether it worked, and when it ran (for example "5 minutes ago"). Clear the history with the "Clear history" button.

</div>

### Component Architecture

<div data-technical>

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

</div>

### Voice Input

Works in Chrome, Edge and Safari. Firefox has limited support.

1. Click the "Voice" button and allow microphone access.
2. Speak your request. Watch the words appear.
3. Click "Stop". The transcript is added to the request text.

<div data-technical>

Browsers: Chrome and Edge (computer and phone), Safari (iPhone, iPad and Mac). The voice input uses the browser's built-in speech feature (the Web Speech API).

Tips: speak slowly and clearly, use everyday language (for example "Navigate to home and take a screenshot"), pause between phrases, and avoid background noise.

</div>

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + Enter` | Execute prompt |
| `Cmd/Ctrl + K` | Focus prompt input |
| `Escape` | Clear prompt (when focused) |

### Local Storage

The history is saved in your browser only. Nothing is sent to the server. It is still there after you close the browser. Clear it with the "Clear" button.

<div data-technical>

Saved: the last 50 requests, when each one ran, whether it worked, and a short summary of the result. The history is stored under the key `mcp-playground-history`, as a JSON list:

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

</div>

### Mobile Optimizations

Buttons are large and nothing depends on hovering the mouse.

<div data-technical>

**Touch targets:**
- At least 56px tall on a phone
- 16px gaps between large buttons
- Buttons fill the width on a phone

**Text sizes:**
- Body text: 16px on a phone, 14px on a computer
- Headings: 20px on a phone, 16px on a computer
- Input boxes: at least 16px, so iPhones do not zoom in when you tap

**Touch:**
- Tap to open and close sections
- Dropdowns are easy to swipe through
- Hovering does nothing. Everything works with a click or tap.

**Speed:**
- Parts of the page load only when they are needed
- Voice input is debounced
- Available options are cached

</div>

### Use Cases

#### 1. Quick smoke test

Take control, type a request, then run it.

<div data-technical>

```
1. Take control
2. Type: "Navigate to home and verify Replay button"
3. Execute
4. Done in seconds!
```

</div>

#### 2. Voice-driven testing on a phone

Useful when you are away from your desk.

<div data-technical>

```
1. Take control
2. Hold voice button
3. Speak: "Swipe up three times and take a screenshot"
4. Release voice button
5. Execute
6. Perfect for on-the-go testing!
```

</div>

#### 3. Exploratory testing

Browse the quick actions and try things quickly.

<div data-technical>

```
1. Browse Quick Actions
2. Click "Navigate to settings"
3. Execute
4. See available verifications
5. Click "Verify element exists"
6. Execute
7. Iterate quickly!
```

</div>

#### 4. Repeat an earlier request

Run an earlier request that worked. If it still works, the feature is stable.

<div data-technical>

```
1. Open History
2. Replay previous successful command
3. Verify still works
4. Fast regression testing!
```

</div>

### MCP Playground vs Test Case Builder

| Feature | MCP Playground | Test Case Builder |
|---------|----------------|-------------------|
| **Focus** | Quick commands | Full test cases |
| **Interface** | Text prompt | Visual canvas |
| **Input** | Type or speak | Drag & drop blocks |
| **Mobile** | Made for phones | Desktop only |
| **Voice** | Built in | Not available |
| **History** | Last 50 commands | Saved test cases |
| **Complexity** | Simple | Advanced |
| **Use Case** | Quick testing | Complex workflows |
| **Save** | Local history | Database |
| **Target** | Phone-first | Desktop power users |

### Integration with MCP Tools

The playground uses the same MCP tools as the rest of the platform. It needs no new server code.

<div data-technical>

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

</div>

### Best Practices

- **Look around first.** Browse Quick Actions before you type.
- **Write requests the way you would say them.** "Navigate to home and verify the Replay button exists", not "nav home verify Replay".

<div data-technical>

Discovery tools: `list_actions`, `list_verifications`, `list_navigation_nodes`.

Keep the history tidy: clear failed requests, and run the working ones again to check for regressions. On a phone, fold away the sections you are not using. Landscape mode is recommended on tablets. Read the voice transcript before you run it, and use voice in a quiet place.

</div>

### Troubleshooting

**Voice does not work:** use Chrome or Safari, and allow microphone access.

**The request does not run:** check that device control is on (the green button) and that a host, device and interface are selected.

**The choice pop-up will not close:** pick a result and click "Resolve", or click "Cancel".

<div data-technical>

- Voice: on an iPhone, try Safari if Chrome fails. Check that the microphone is not muted.
- Requests: check that the backend server is running and that your network connection works.
- Choice pop-up: pick a result from the drop-down, click "Resolve", or click "Cancel" to stop.
- History is not saved: check that your browser allows local storage, that you are not in a private or incognito window, and try clearing the browser cache.

</div>
