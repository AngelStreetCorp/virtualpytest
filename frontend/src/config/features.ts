/**
 * Optional features — frontend side. See docs/technical/FEATURES.md.
 *
 * `virtual:vpt-features` is generated at build time by the `vpt-features` plugin in
 * vite.config.ts: it imports `features/<name>/frontend/routes.tsx` for every feature
 * folder present on disk and NOT listed in VITE_DISABLED_FEATURES. A disabled (or
 * absent) feature is therefore never referenced, so none of its code is bundled.
 *
 * A feature's routes.tsx default-exports a `FeatureDefinition`.
 */
import type { ReactElement, ReactNode } from 'react';
import { matchPath } from 'react-router-dom';
import { features as loaded } from 'virtual:vpt-features';

export interface FeatureRoute {
  /** Full route path, e.g. `/monitoring/avq/:hostName/:deviceId`. */
  path: string;
  /** Usually a `React.lazy` page so it gets its own chunk. Rendered under the auth guard. */
  element: ReactElement;
  /** Render without the Container width limit (like /ai-agent). */
  fullWidth?: boolean;
  /**
   * The page brings its own AI entry point (or has no app chrome), so the global
   * floating Ask-AI button is hidden while the location matches this route
   * (see `matchesFeatureRoute(pathname, 'hideFloatingAiButton')`).
   */
  hideFloatingAiButton?: boolean;
}

/**
 * Navbar slot a feature nav item is appended to. `test-build`, `test-execute` and
 * `test-report` are the "Build" / "Execute" / "Report" groups of the Test dropdown
 * (Test Builder…, Run Tests…, Test Reports…); the others are whole dropdowns.
 */
export type FeatureNavSection =
  | 'ai'
  | 'test-build'
  | 'test-execute'
  | 'test-report'
  | 'monitoring'
  | 'docs'
  | 'settings';

export interface FeatureNavItem {
  /** Navbar dropdown (or dropdown group) the item is appended to. */
  section: FeatureNavSection;
  label: string;
  path: string;
  icon?: ReactNode;
}

/** Per-device shortcut rendered next to each device row on the Dashboard. */
export interface FeatureDeviceLink {
  label: string;
  icon: ReactNode;
  path: (hostName: string, deviceId: string) => string;
}

export interface FeatureDefinition {
  routes?: FeatureRoute[];
  nav?: FeatureNavItem[];
  deviceLinks?: FeatureDeviceLink[];
}

export interface LoadedFeature {
  name: string;
  entry: FeatureDefinition;
}

const FEATURES: LoadedFeature[] = loaded;

/** Names of the features compiled into this bundle. */
export function enabledFeatures(): string[] {
  return FEATURES.map((f) => f.name);
}

export function isFeatureEnabled(name: string): boolean {
  return FEATURES.some((f) => f.name === name);
}

export function featureRoutes(): FeatureRoute[] {
  return FEATURES.flatMap((f) => f.entry.routes ?? []);
}

export function featureNavItems(section: FeatureNavSection): FeatureNavItem[] {
  return FEATURES.flatMap((f) => (f.entry.nav ?? []).filter((n) => n.section === section));
}

export function featureDeviceLinks(): FeatureDeviceLink[] {
  return FEATURES.flatMap((f) => f.entry.deviceLinks ?? []);
}

/** True when `pathname` matches a feature route carrying the given flag. */
export function matchesFeatureRoute(
  pathname: string,
  flag: 'fullWidth' | 'hideFloatingAiButton',
): boolean {
  return featureRoutes().some((r) => r[flag] && matchPath(r.path, pathname) !== null);
}
