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

import { registerCatalogLoader } from '../i18n';
import type { ModDefinition } from '../mods/core/types';

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
  | 'plugins'
  | 'settings';

export interface FeatureNavItem {
  /** Navbar dropdown (or dropdown group) the item is appended to. */
  section: FeatureNavSection;
  label: string;
  path: string;
  icon?: ReactNode;
  /**
   * Makes the row an ACTION instead of a link: choosing it calls this and the app does not
   * navigate. `path` is then only the row's key (the page-visibility key, so give it a unique
   * pseudo path such as `/action/my-thing`), and no route needs to exist for it.
   */
  onSelect?: () => void;
  /**
   * Runtime gate, read each time the dropdown renders; return false to hide the row. For a feature
   * that can be switched off at runtime (its state lives on the server, not in the build).
   */
  isVisible?: () => boolean;
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

/**
 * Lets a feature draw on top of a device's video player (the live-TV companion strip is the case
 * this exists for). Core mounts every registered overlay inside the player with the device and
 * the player's mode; the feature fetches its own data and decides what, if anything, to render.
 * With no feature registering one, the player renders exactly as before.
 */
export interface FeatureVideoOverlay {
  Component: ComponentType<{
    hostName: string;
    deviceId: string;
    isLiveMode: boolean;
    /** The player's "Monitoring" toggle. */
    monitoringMode: boolean;
  }>;
}

/**
 * A notice a feature shows at the top of Settings (the APK's "update available" banner is
 * the case this exists for). Core mounts every registered one under the page title; the feature
 * decides whether there is anything to say and renders nothing otherwise.
 */
export type FeatureSettingsNotice = ComponentType;

/**
 * A row a feature adds to Settings -> Features -> "Feature Toggles" (its runtime on/off switch).
 * Core renders every registered one at the end of that list. The component renders ONE `<SettingRow>`
 * (`components/common/SettingRow`) itself and owns reading and writing its state. Takes no props.
 */
export type FeatureSettingsToggle = ComponentType;

/**
 * A component mounted once for the whole app, inside the Router, auth, toast and server providers
 * and next to the page (not in it). For things a feature opens from anywhere - a dialog started by
 * a `nav.onSelect` - without core knowing about them. Takes no props.
 */
export type FeatureAppOverlay = ComponentType;

/** fr/de strings of a feature, loaded with the app's own catalog so they are only bundled with it. */
export type FeatureTranslations = Partial<
  Record<'fr' | 'de', () => Promise<{ default: Record<string, string | Record<string, string>> }>>
>;

export interface FeatureDefinition {
  routes?: FeatureRoute[];
  nav?: FeatureNavItem[];
  deviceLinks?: FeatureDeviceLink[];
  previewActions?: FeaturePreviewAction[];
  targetReadiness?: FeatureTargetReadiness[];
  videoOverlays?: FeatureVideoOverlay[];
  settingsNotices?: FeatureSettingsNotice[];
  settingsToggles?: FeatureSettingsToggle[];
  appOverlays?: FeatureAppOverlay[];
  /** Catalogs merged into fr/de. English is the key, so there is no `en`. */
  translations?: FeatureTranslations;
  /** Mods (TASK-77, docs/agent/platform/MODS.md): each user turns them on or off on the Mods page. */
  mods?: ModDefinition[];
}

export interface LoadedFeature {
  name: string;
  entry: FeatureDefinition;
}

const FEATURES: LoadedFeature[] = loaded;

// Feature catalogs join the app's own at load time. Registered here, at module evaluation, which
// happens before main.tsx calls initI18n().
FEATURES.forEach((f) => {
  const loaders = f.entry.translations;
  if (loaders) registerCatalogLoader(async (code) => (code === 'fr' || code === 'de' ? (await loaders[code]?.())?.default : undefined) ?? {});
});

/** Names of the features compiled into this bundle. */
export function enabledFeatures(): string[] {
  return FEATURES.map((f) => f.name);
}

export function isFeatureEnabled(name: string): boolean {
  return FEATURES.some((f) => f.name === name);
}

/** Every mod an enabled feature ships, in feature-folder order. */
export function featureMods(): ModDefinition[] {
  return FEATURES.flatMap((f) => f.entry.mods ?? []);
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

/** Every overlay a feature draws on the device video player, in a stable order. */
export function featureVideoOverlays(): FeatureVideoOverlay[] {
  return FEATURES.flatMap((f) => f.entry.videoOverlays ?? []);
}

/** Every component a feature mounts once for the whole app, in a stable order. */
export function featureAppOverlays(): FeatureAppOverlay[] {
  return FEATURES.flatMap((f) => f.entry.appOverlays ?? []);
}

/** Every notice a feature shows at the top of Settings, in a stable order. */
export function featureSettingsNotices(): FeatureSettingsNotice[] {
  return FEATURES.flatMap((f) => f.entry.settingsNotices ?? []);
}

/** Every row a feature adds to the Settings "Feature Toggles" table, in a stable order. */
export function featureSettingsToggles(): FeatureSettingsToggle[] {
  return FEATURES.flatMap((f) => f.entry.settingsToggles ?? []);
}

/** True when `pathname` matches a feature route carrying the given flag. */
export function matchesFeatureRoute(
  pathname: string,
  flag: 'fullWidth' | 'hideFloatingAiButton',
): boolean {
  return featureRoutes().some((r) => r[flag] && matchPath(r.path, pathname) !== null);
}
