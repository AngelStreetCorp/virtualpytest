# Z-Index Management System

## Overview

All z-index values in the application are centrally managed through `frontend/src/utils/zIndexUtils.ts` to ensure consistent layering and prevent visual conflicts.

## Usage

```typescript
import { getZIndex } from '../utils/zIndexUtils';

// Basic usage
const zIndex = getZIndex('NAVIGATION_PANELS'); // Returns 110

// With offset for micro-adjustments
const zIndex = getZIndex('NAVIGATION_PANELS', 1); // Returns 111
```

## Z-Index Hierarchy

### Base Content Layers (10-50)
- **CONTENT** (10) - Base content, images, videos
- **NAVIGATION_NODES** (20) - Navigation nodes and their handles
- **NAVIGATION_NODE_HANDLES** (30) - Node connection handles
- **NAVIGATION_NODE_BADGES** (40) - Node badges (verification, subtree)
- **NAVIGATION_NODE_CURRENT_POSITION** (50) - Current position indicators

### Control Panels (60-100)
- **UI_ELEMENTS** (60) - General UI elements
- **DESKTOP_CONTROL_PANEL** (70) - Desktop Control Panel (behind navigation panels)
- **REMOTE_PANELS** (80) - Remote control panels
- **VIDEO_CAPTURE_CONTROLS** (90) - Video capture playback controls
- **VIDEO_CAPTURE_OVERLAY** (100) - Video capture drag selection

### Streaming & Visualization (110-140)
- **STREAM_VIEWER** (110) - Stream viewers
- **HDMI_STREAM** (120) - HDMI stream displays
- **VNC_STREAM** (130) - VNC stream displays
- **VERIFICATION_EDITOR** (140) - Verification editors

### Navigation Panels (150-200)
- **NAVIGATION_PANELS** (150) - General navigation panels
- **NAVIGATION_EDGE_PANEL** (160) - Edge editing panel
- **NAVIGATION_SELECTION_PANEL** (170) - Node selection panel
- **NAVIGATION_GOTO_PANEL** (180) - Navigation goto panel
- **NAVIGATION_CONFIRMATION** (190) - Navigation confirmation dialogs
- **NAVIGATION_DIALOGS** (200) - Navigation dialogs (create/edit)

### Interactive Overlays (210-230)
- **APPIUM_OVERLAY** (210) - Appium element overlays
- **ANDROID_MOBILE_OVERLAY** (220) - Android mobile overlays
- **DEBUG_OVERLAY** (230) - Debug information overlays

### Top-Level UI (240-270)
- **TOOLTIPS** (240) - Tooltips and hints
- **READ_ONLY_INDICATOR** (250) - Read-only mode indicators
- **HEADER** (260) - Page headers
- **HEADER_DROPDOWN** (270) - Header dropdown menus

### Modals (280-310)
- **MODAL_BACKDROP** (280) - Modal backdrop/overlay
- **MODAL_CONTENT** (290) - Modal content windows
- **SCREENSHOT_MODAL** (300) - Screenshot viewing modals
- **SCREENSHOT_CAPTURE_OVERLAY** (310) - Screenshot capture drag selection overlay

## Key Design Principles

1. **10-Point Intervals**: Each component gets 10 z-index points for micro-adjustments
2. **Logical Grouping**: Related components are grouped in ranges
3. **Clear Hierarchy**: Lower numbers = behind, higher numbers = in front
4. **Proper Layering**: Streams (110-140) at control panel level, Navigation panels (150-200) above streams

## Adding New Components

1. **Identify the appropriate layer** for your component
2. **Add to `Z_INDEX_ORDER`** in the correct position
3. **Use descriptive names** (e.g., `MY_COMPONENT_PANEL`)
4. **Update this documentation** with the new component

## CSS Integration

For backend-generated CSS (like reports), use the CSS z-index helper:

```python
# In report_template_css.py
from shared.lib.utils.report_template_css import get_css_z_index

modal_z = get_css_z_index('modal_backdrop')  # Aligns with frontend
```

## Common Patterns

- **Node handles**: Use `NAVIGATION_NODE_HANDLES`
- **Modal overlays**: Use `MODAL_BACKDROP` and `MODAL_CONTENT`
- **Control panels**: Use `*_PANELS` with appropriate prefix
- **Interactive overlays**: Use `*_OVERLAY` with component name

## ⚠️ Important Rules

1. **Never use hardcoded z-index values** in components
2. **Always import and use `getZIndex()`**
3. **Test layering** when adding new components
4. **Update documentation** when modifying the hierarchy

## Example Implementation

```typescript
// ✅ CORRECT
import { getZIndex } from '../../utils/zIndexUtils';

const MyComponent = () => (
  <div style={{ zIndex: getZIndex('NAVIGATION_PANELS') }}>
    <div style={{ zIndex: getZIndex('NAVIGATION_PANELS', 1) }}>
      Higher layer within same component
    </div>
  </div>
);

// ❌ INCORRECT
const MyComponent = () => (
  <div style={{ zIndex: 1500 }}> {/* Hardcoded - BAD */}
    Content
  </div>
);
```

## Debugging Z-Index Issues

1. **Check component hierarchy** - ensure component is in correct layer
2. **Verify import** - make sure `getZIndex` is imported
3. **Use browser DevTools** - inspect computed z-index values
4. **Call `getAllZIndexes()`** in console to see all current values

---

*Last updated: December 2024*
*Maintained by: Frontend Team*
