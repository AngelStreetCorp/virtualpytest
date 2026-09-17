/**
 * Secondary destinations surfaced behind the mobile bottom nav's "More" tab.
 *
 * These mirror the desktop top nav's dropdown sections (see
 * `frontend/src/config/navItems.tsx` and `Navigation_Bar.tsx`) — AI, Test,
 * Interface, Monitoring, Docs, Settings — none of which fit individually
 * as a primary bottom-nav tab on a mobile viewport. Plugins is left out
 * here; that integration's own UI isn't mobile-ready yet. Each entry
 * below reuses an EXACT route path + icon pairing already defined for that
 * section on desktop (picking one representative destination per section,
 * since desktop renders these as multi-item dropdowns rather than single
 * links), so tapping a menu item lands the user on a real, existing page.
 */
import {
  AccountTree as InterfaceIcon,
  Build as SettingsIcon,
  HelpOutline as DocsIcon,
  RocketLaunch as AiIcon,
  Science as TestIcon,
  Warning as MonitoringIcon,
} from '@mui/icons-material';
import React from 'react';

export interface MobileMoreMenuItem {
  label: string;
  path: string;
  icon: React.ReactNode;
}

// Route this bottom-nav tab is highlighted for (it has no single destination
// of its own — tapping it opens a menu instead of navigating directly).
export const MORE_TAB_VALUE = 'more';

export const MOBILE_MORE_MENU_ITEMS: MobileMoreMenuItem[] = [
  { label: 'AI', path: '/ai-agent', icon: <AiIcon fontSize="small" /> },
  { label: 'Test', path: '/test-plan/test-cases', icon: <TestIcon fontSize="small" /> },
  { label: 'Interface', path: '/configuration/interface', icon: <InterfaceIcon fontSize="small" /> },
  { label: 'Monitoring', path: '/monitoring/incidents', icon: <MonitoringIcon fontSize="small" /> },
  { label: 'Docs', path: '/docs/faq', icon: <DocsIcon fontSize="small" /> },
  { label: 'Settings', path: '/configuration/settings', icon: <SettingsIcon fontSize="small" /> },
];

export default MOBILE_MORE_MENU_ITEMS;
