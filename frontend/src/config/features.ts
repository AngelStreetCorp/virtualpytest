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
import type { ComponentType, ReactElement, ReactNode } from 'react';
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

/**
 * Lets a feature take over the click on a device's REC preview card, for a device model whose
 * card can be showing a stream with nothing useful behind it. `phone_agent` is the case this
 * exists for: an unpaired phone slot always has a stream (the host writes a placeholder frame
 * so ffmpeg has a source), so the card looks alive and the modal opens on a full-screen
 * "phone offline" picture — pairing is the useful offer instead.
 *
 * Core cannot judge that itself; the feature owns the data. So `Component` is mounted by the
 * card and reports back through `onCanHandleChange` whether it wants the click. While it says
 * no — a phone is connected and really is streaming — the card behaves exactly as before.
 */
export interface FeaturePreviewAction {
  /** `device_model` this applies to. */
  deviceModel: string;
  Component: ComponentType<{
    hostName: string;
    deviceId: string;
    open: boolean;
    onClose: () => void;
    onCanHandleChange: (canHandle: boolean) => void;
  }>;
}

/**
 * Lets a feature say whether a device of its model is usable as a run target right now.
 *
 * Core knows a device exists and what model it is; it does not know whether the thing behind
 * it is actually there. A `phone_agent` slot is the sharp case: the slot is configured and the
 * device is registered whether or not a phone is paired, connected or streaming, so Run Tests
 * would happily offer a phone that is asleep in someone's pocket and the run would fail on its
 * first action.
 *
 * `useReadiness` is a hook, so the feature can poll its own endpoint and re-render the picker
 * when a phone comes back. It is called once per registered provider on every render of the
 * page that uses it — the provider list is fixed at build time by the vpt-features plugin, so
 * the call order is stable and the rules of hooks hold.
 *
 * Returning `undefined` for a device means "no opinion": the device is left exactly as core
 * would have shown it.
 */
export interface FeatureTargetReadiness {
  /** `device_model` this applies to. */
  deviceModel: string;
  useReadiness: () => (
    hostName: string,
    deviceId: string,
  ) => { ready: boolean; reason?: string } | undefined;
}

export interface FeatureDefinition {
  routes?: FeatureRoute[];
  nav?: FeatureNavItem[];
  deviceLinks?: FeatureDeviceLink[];
  previewActions?: FeaturePreviewAction[];
  targetReadiness?: FeatureTargetReadiness[];
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

/** The feature claiming this device model's preview click, if any. */
export function featurePreviewAction(deviceModel?: string): FeaturePreviewAction | undefined {
  if (!deviceModel) return undefined;
  return FEATURES.flatMap((f) => f.entry.previewActions ?? []).find(
    (a) => a.deviceModel === deviceModel,
  );
}

/**
 * Every registered readiness provider, in a stable order.
 *
 * Stable because the underlying list is generated at build time — a caller may therefore call
 * each provider's hook in this order without breaking the rules of hooks.
 */
export function featureTargetReadiness(): FeatureTargetReadiness[] {
  return FEATURES.flatMap((f) => f.entry.targetReadiness ?? []);
}

/** True when `pathname` matches a feature route carrying the given flag. */
export function matchesFeatureRoute(
  pathname: string,
  flag: 'fullWidth' | 'hideFloatingAiButton',
): boolean {
  return featureRoutes().some((r) => r[flag] && matchPath(r.path, pathname) !== null);
}
