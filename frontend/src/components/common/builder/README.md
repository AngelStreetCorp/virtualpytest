# Shared Builder Components

**Container-based architecture**: Each component is a CONTAINER with exact styling, accepting content as children/slots.

## Architecture Principle

```
Container (shared styling) + Content Slot (pluggable components)
```

Each builder (TestCase, Campaign, etc.) uses the SAME containers but plugs in different content.

## Layout Components

### 1. BuilderPageLayout
Fixed page container positioning content below navigation and above footer.

### 2. BuilderHeaderContainer  
Header container with exact TestCaseBuilder styling, accepts content as children.

### 3. BuilderSidebarContainer
Collapsible sidebar container, accepts any content inside.

### 4. BuilderMainContainer
Main content area container (sidebar + canvas).

### 5. BuilderStatsBarContainer
Bottom stats bar container with exact styling.

## Toolbox Components

### 6. ToolboxMainTabs
Main tab selector for builder toolboxes (Blocks / Config tabs).

### 7. ToolboxAccordion
Consistent accordion with left border accent, single-expand behavior.

### 8. ToolboxSearchBox
Search input for filtering toolbox items.

### 9. DraggableCommand
Draggable command block for testcase builder.

### 10. DraggableToolboxItem
Generic draggable item for testcases, scripts, etc.

## Tab Colors (TOOLBOX_TAB_COLORS)

```typescript
{
  standard: '#64748b',      // slate
  navigation: '#7c3aed',    // violet  
  actions: '#ea580c',       // orange
  verifications: '#2563eb', // blue
  api: '#0891b2',           // cyan
  testcases: '#9c27b0',     // purple
  scripts: '#f97316',       // orange
}
```

All styling matches TestCaseBuilder EXACTLY.
