# 🎨 Color Consistency Guide

## Overview
This project uses **centralized theme colors** to ensure visual consistency across all pages and components.

## Centralized Theme Location
**File:** `frontend/src/constants/agentChatTheme.ts`

## Color Palette

### Primary Colors
```typescript
AGENT_CHAT_PALETTE = {
  // UI Structure
  background: '#1a1a1a',
  surface: '#242424',
  inputBg: '#2a2a2a',
  sidebarBg: '#1e1e1e',
  
  // Text Colors
  textPrimary: '#f0f0f0',
  textSecondary: '#9a9a9a',
  textMuted: '#666666',
  
  // Accent Colors
  accent: '#d4a574',        // ⭐ Muted gold - buttons, switches, main UI
  accentHover: '#c49464',   // Hover state for accent
  gold: '#FFD700',          // ⭐ Bright gold - skills, badges, awards, highlights
  
  // Status Colors
  success: '#22c55e',       // ✅ Success/pass state
  error: '#ef4444',         // ❌ Error/fail state
  
  // Bubble Colors
  agentBubble: '#262626',
  agentBorder: '#333333',
  userBubble: '#3a3a3a',
  userBorder: '#4a4a4a',
  
  // UI Elements
  borderColor: '#383838',
  hoverBg: '#2a2a2a',
  cardShadow: '0 2px 8px rgba(0,0,0,0.3)',
}
```

### Special Purpose Colors
```typescript
// Element highlight colors for overlays (UI element detection)
ELEMENT_HIGHLIGHT_COLORS = [
  '#FF0000',                    // Red
  '#0066FF',                    // Blue
  AGENT_CHAT_PALETTE.gold,     // Gold (theme color)
  '#00CC00',                    // Green
  '#9900FF',                    // Purple
]
```

## Usage Rules

### ✅ DO
- Import `AGENT_CHAT_PALETTE` from `constants/agentChatTheme`
- Use `AGENT_CHAT_PALETTE.gold` for all bright gold UI elements
- Use `AGENT_CHAT_PALETTE.accent` for primary accent colors
- Use `ELEMENT_HIGHLIGHT_COLORS` for overlay element highlighting

### ❌ DON'T
- Hardcode color values like `#FFD700` or `#d4a574`
- Create local color constants that duplicate theme colors
- Use different gold shades for similar UI elements

## Files Updated (2024)

### Core Theme
- ✅ `constants/agentChatTheme.ts` - Added `gold`, `success`, `error` colors + `ELEMENT_HIGHLIGHT_COLORS`

### Pages
- ✅ `pages/AgentChat.tsx` - Skill badge now uses `PALETTE.gold`
- ✅ `pages/AgentDashboard.tsx` - Trophy icon and local GOLD constants now use theme

### Components
- ✅ `components/controller/verification/VerificationCapture.tsx` - Fuzzy search highlights
- ✅ `components/controller/av/DragSelectionOverlay.tsx` - Selection borders
- ✅ `components/controller/remote/AndroidMobileOverlay.tsx` - Element highlight colors
- ✅ `components/controller/remote/AppiumOverlay.tsx` - Element highlight colors
- ✅ `components/controller/web/PlaywrightWebOverlay.tsx` - Element highlight colors

### Config
- ✅ `config/remote/appiumRemote.ts` - Element highlight colors config

## When to Use Which Gold

### `AGENT_CHAT_PALETTE.accent` (#d4a574 - Muted Gold)
Use for:
- Primary buttons
- Navigation highlights
- Main UI accents
- Active states
- **Skill badges** (better readability than bright gold)

### `AGENT_CHAT_PALETTE.gold` (#FFD700 - Bright Gold)
Use for:
- Achievement icons (🥇 trophies)
- Important highlights
- Selection indicators
- Fuzzy search areas
- Element overlay highlights

**Note:** Bright gold (#FFD700) can be hard to read on dark backgrounds. Prefer `accent` for text-based elements like chips and badges.

## Example Usage

```typescript
// Import the theme
import { AGENT_CHAT_PALETTE, ELEMENT_HIGHLIGHT_COLORS } from '../constants/agentChatTheme';

// Use in components
<Chip
  sx={{
    borderColor: AGENT_CHAT_PALETTE.gold,
    color: AGENT_CHAT_PALETTE.gold,
  }}
/>

// Use for element overlays
const COLORS = ELEMENT_HIGHLIGHT_COLORS;
```

## Before vs After

### Before (Inconsistent) ❌
```typescript
// AgentChat.tsx
borderColor: '#FFD700',  // Bright gold

// AgentDashboard.tsx
const GOLD = '#D4AF37';  // Yet another gold shade!

// Theme
accent: '#d4a574',  // Muted gold
```

### After (Consistent) ✅
```typescript
// All files use centralized theme
import { AGENT_CHAT_PALETTE } from '../constants/agentChatTheme';

borderColor: AGENT_CHAT_PALETTE.gold,  // ✨ Consistent!
```

## Maintaining Consistency

1. **Always check the theme first** before adding new colors
2. **Never hardcode colors** - use theme constants
3. **Add new colors to the theme** if needed across multiple files
4. **Document color purpose** in comments
5. **Review PRs** for hardcoded color values

---

**Last Updated:** December 2024  
**Maintained By:** Frontend Team  
**Questions?** Check `constants/agentChatTheme.ts` for all available colors

