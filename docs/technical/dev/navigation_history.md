# Navigation Editor Undo/Redo System

## Overview

The Navigation Editor implements a comprehensive undo/redo system that allows users to revert and reapply changes to navigation trees. This system ensures that user actions can be safely undone while preventing system-generated changes from polluting the undo history.

## Architecture

### Core Components

#### 1. History State Management (`NavigationContext.tsx`)

The undo/redo system is managed within the `NavigationContext` with the following state:

```typescript
// History storage
const [history, setHistory] = useState<Array<{ nodes: UINavigationNode[]; edges: UINavigationEdge[] }>>([]);
const [historyIndex, setHistoryIndex] = useState(0); // Starts at 0 (allows first undo)
const [isRecordingHistory, setIsRecordingHistory] = useState(true); // Controls recording
```

#### 2. History Control Functions

- **`resetHistory()`**: Clears history and resets index (called when loading new trees)
- **`pauseHistoryRecording()`**: Temporarily disables history recording
- **`resumeHistoryRecording()`**: Re-enables history recording

#### 3. Core Undo/Redo Logic

```typescript
const undo = useCallback(() => {
  if (historyIndex > 0) {
    const prevState = history[historyIndex - 1];
    setNodes(prevState.nodes);
    setEdges(prevState.edges);
    setHistoryIndex(prev => prev - 1);
    setHasUnsavedChanges(true);
  }
}, [history, historyIndex, setNodes, setEdges]);

const redo = useCallback(() => {
  if (historyIndex < history.length - 1) {
    const nextState = history[historyIndex + 1];
    setNodes(nextState.nodes);
    setEdges(nextState.edges);
    setHistoryIndex(prev => prev + 1);
    setHasUnsavedChanges(true);
  }
}, [history, historyIndex, setNodes, setEdges]);
```

### History Recording Logic

#### Automatic History Recording

Changes to `nodes` and `edges` automatically trigger history snapshots:

```typescript
useEffect(() => {
  if (isRecordingHistory && (nodes !== prevNodesRef.current || edges !== prevEdgesRef.current)) {
    prevNodesRef.current = nodes as UINavigationNode[];
    prevEdgesRef.current = edges as UINavigationEdge[];
    if (nodes.length > 0) pushHistory();
  }
}, [nodes, edges, pushHistory, isRecordingHistory]);
```

#### Selective Recording

The system distinguishes between user actions and system operations:

- **User Actions** (recorded): Node creation, edge creation, property changes, manual layouts
- **System Operations** (not recorded): Tree loading, AI generation, validation cleanup

## User Interface Integration

### Keyboard Shortcuts

```typescript
// Undo: Ctrl+Z (or Cmd+Z on Mac)
if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'z' && !isInputField) {
  navigation.undo();
}

// Redo: Ctrl+Shift+Z or Ctrl+Y (or Cmd+Shift+Z/Cmd+Y on Mac)
if ((e.ctrlKey || e.metaKey) && (e.shiftKey && e.key === 'z' || e.key === 'y') && !isInputField) {
  navigation.redo();
}
```

### UI Buttons

Undo/redo buttons in the NavigationEditorHeader are enabled/disabled based on history state:

```typescript
const canUndo = historyIndex > 0;
const canRedo = historyIndex < history.length - 1;
```

## Key Features

### 1. Tree Isolation

Each navigation tree maintains its own undo history. When switching trees:

```typescript
// Reset history to prevent cross-tree undo operations
navigation.resetHistory();
```

### 2. System Operation Filtering

Critical system operations pause history recording:

```typescript
// During tree loading
navigation.pauseHistoryRecording();
// ... load tree data ...
navigation.resumeHistoryRecording();

// During AI generation
navigation.pauseHistoryRecording();
// ... AI operations ...
navigation.resumeHistoryRecording();
```

### 3. Change Tracking

The system marks trees as having unsaved changes when undoing:

```typescript
setHasUnsavedChanges(true);
```

## Implementation Details

### History Storage Format

Each history entry contains a complete snapshot:

```typescript
interface HistoryEntry {
  nodes: UINavigationNode[];
  edges: UINavigationEdge[];
}
```

### Index Management

- **historyIndex = 0**: Initial state (can undo to this point)
- **historyIndex = history.length - 1**: Latest state (can redo from this point)
- **historyIndex > 0 && < history.length - 1**: Middle of history (can undo and redo)

### Push History Logic

```typescript
const pushHistory = useCallback(() => {
  if (!isRecordingHistory) return;

  const snapshot = { nodes: nodes as UINavigationNode[], edges: edges as UINavigationEdge[] };
  setHistory(prev => {
    // If we're at the end, append
    if (historyIndex === prev.length) {
      return [...prev, snapshot];
    }
    // If we're in the middle (after undo), replace from current index
    return [...prev.slice(0, historyIndex), snapshot];
  });
  setHistoryIndex(prev => prev + 1);
}, [nodes, edges, historyIndex, isRecordingHistory]);
```

## Usage Scenarios

### 1. User Node Editing

```typescript
// User adds a node -> recorded in history
addNewNode('screen', { x: 250, y: 250 });

// User can undo
navigation.undo(); // Removes the node

// User can redo
navigation.redo(); // Restores the node
```

### 2. Tree Loading (System Operation)

```typescript
// System loads tree -> history NOT recorded
navigation.pauseHistoryRecording();
await loadTreeData(treeId);
navigation.resetHistory(); // Clear any existing history
navigation.resumeHistoryRecording();
```

### 3. AI Generation (System Operation)

```typescript
// AI generates structure -> history NOT recorded
navigation.pauseHistoryRecording();
// ... AI generation process ...
await handleAIGenerated(); // Refreshes tree data
navigation.resumeHistoryRecording();
```

## Error Handling

The system includes try/finally blocks to ensure history recording is always resumed:

```typescript
try {
  navigation.pauseHistoryRecording();
  // ... system operation ...
} finally {
  navigation.resumeHistoryRecording(); // Always called
}
```

## Performance Considerations

- History snapshots are stored in memory only
- No persistence across browser sessions
- Automatic cleanup when trees are reloaded
- Minimal performance impact due to selective recording

## Testing

### Manual Testing Checklist

1. **Basic Undo/Redo**:
   - Add node → Undo → Redo
   - Edit node properties → Undo → Redo
   - Delete node → Undo → Redo

2. **Tree Switching**:
   - Edit Tree A → Switch to Tree B → Undo in Tree B should not affect Tree A

3. **System Operations**:
   - Load tree → Should not be undoable
   - AI generation → Should not pollute undo history
   - Validation cleanup → Should not be undoable

4. **Edge Cases**:
   - Multiple undos followed by new action (should truncate redo history)
   - Undo during system operations
   - Keyboard shortcuts in input fields (should be ignored)

## Future Enhancements

### Potential Improvements

1. **History Persistence**: Store undo history in localStorage for browser sessions
2. **Selective Undo**: Allow undoing specific types of operations (nodes only, edges only)
3. **History Compression**: Merge similar consecutive operations
4. **Visual History**: Show timeline of changes with previews
5. **Collaboration Support**: Handle concurrent edits with conflict resolution

## Troubleshooting

### Common Issues

1. **Undo not working after tree load**:
   - Check that `resetHistory()` is called during tree loading
   - Verify `pauseHistoryRecording()` is used during system operations

2. **Redo not available after undo**:
   - Ensure new actions properly truncate history when in middle of undo chain
   - Check `pushHistory` logic handles middle-of-history scenarios

3. **System operations polluting history**:
   - Verify `pauseHistoryRecording()` is called before system operations
   - Ensure `resumeHistoryRecording()` is called in finally blocks

### Debug Logging

Enable debug logging to trace history operations:

```typescript
console.log('[@NavigationContext] History state:', {
  historyLength: history.length,
  historyIndex,
  isRecordingHistory,
  canUndo,
  canRedo
});
```
