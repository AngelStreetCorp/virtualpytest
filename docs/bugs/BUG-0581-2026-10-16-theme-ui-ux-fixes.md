# BUG-0581: Theme UI UX fixes

Date: 2026-10-16

## Summary

Three small UX fixes to the theme editor and theme picker:

## Fixes

1. **Hex input autocorrect** (`ColourThemeDialog.tsx`): the Accent and Background hex TextFields now normalize user input — prepend `#` if missing, strip non-hex chars, cap at 6 chars. User can type `aabbcc` or `#aabbcc` and get `#aabbcc`.

2. **Edit button size** (`PreferencesRows.tsx`): the circular pencil badge on the custom colour swatch grows from 12×12 px to 20×20 px, making it actually usable.

3. **System theme icon** (`PreferencesRows.tsx`, `ThemeToggle.tsx`): replaces `SettingsBrightness` (rectangle + star, hard to read) with `Brightness4` (half-circle, the standard dark-mode symbol that pairs naturally with LightMode/DarkMode).
