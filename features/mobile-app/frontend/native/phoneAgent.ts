/**
 * TS surface for the native `PhoneAgent` Capacitor plugin (docs/tasks/TASK-17 §3, W4/app).
 * The frontend never depends on @capacitor/* (not a package dependency here): the plugin is
 * reached through the `window.Capacitor.Plugins.PhoneAgent` global the native shell installs,
 * exactly like `isNativeApp()` in `frontend/src/config/runtimeConfig.ts`. On the web that
 * global does not exist, so every call below rejects (or, for `getStatus`, resolves an
 * "unconfigured" status) rather than throwing at import time — this keeps `ThisPhonePage`
 * safe to render on the web build (tests/e2e ui.pages.spec.js sweeps it).
 */

export interface PhoneAgentStatus {
  configured: boolean;
  serverUrl?: string;
  paired: boolean;
  hostName?: string;
  deviceId?: string;
  connected: boolean;
  /** A connect attempt is in flight or scheduled — the link is trying, not dead. */
  connecting?: boolean;
  captureActive: boolean;
  fps: number;
  accessibilityEnabled: boolean;
  projectionGranted: boolean;
  batteryUnrestricted: boolean;
  /** Android 13+ POST_NOTIFICATIONS. False means the link indicator cannot be shown. */
  notificationsEnabled: boolean;
  /** The phone draws what the host is doing on its own screen. */
  actionOverlay?: boolean;
  /** The running APK, e.g. "1.0.15 (16)". Undefined on the web build. */
  appVersion?: string;
  lastError?: string;
}

export interface PhoneAgentPlugin {
  scanQr(): Promise<{ value: string }>; // native scanner; rejects on cancel
  applyConfig(opts: { payload: string }): Promise<PhoneAgentStatus>; // raw QR JSON, kind 'config' or 'pair'
  setServer(opts: {
    serverUrl: string;
    supabaseUrl?: string;
    supabaseAnonKey?: string;
    projectName?: string;
  }): Promise<PhoneAgentStatus>;
  getStatus(): Promise<PhoneAgentStatus>;
  unpair(): Promise<PhoneAgentStatus>;
  openAccessibilitySettings(): Promise<void>;
  enableNotifications(): Promise<PhoneAgentStatus>; // system dialog on Android 13+
  requestProjection(): Promise<{ granted: boolean }>;
  openBatterySettings(): Promise<void>;
  reloadApp(): Promise<void>;
  setActionOverlay(options: { enabled: boolean }): Promise<PhoneAgentStatus>;
  addListener(eventName: 'statusChanged', cb: (s: PhoneAgentStatus) => void): Promise<{ remove: () => void }>;
}

declare global {
  interface Window {
    Capacitor?: {
      isNativePlatform?: () => boolean;
      Plugins?: Record<string, unknown>;
    };
  }
}

const UNAVAILABLE_ERROR = 'PhoneAgent is only available in the mobile app';

const NOT_CONFIGURED_STATUS: PhoneAgentStatus = {
  configured: false,
  paired: false,
  connected: false,
  connecting: false,
  captureActive: false,
  fps: 0,
  accessibilityEnabled: false,
  projectionGranted: false,
  batteryUnrestricted: false,
  notificationsEnabled: false,
  actionOverlay: true,
};

/** True when the native shell has registered the plugin (i.e. we are inside the APK). */
export const isPhoneAgentAvailable = (): boolean => {
  try {
    return Boolean(window.Capacitor?.Plugins?.PhoneAgent);
  } catch {
    return false;
  }
};

const nativePlugin = (): PhoneAgentPlugin | null => {
  try {
    return (window.Capacitor?.Plugins?.PhoneAgent as PhoneAgentPlugin | undefined) ?? null;
  } catch {
    return null;
  }
};

const unavailable = (): Promise<never> => Promise.reject(new Error(UNAVAILABLE_ERROR));

export const phoneAgent: PhoneAgentPlugin = {
  scanQr: () => nativePlugin()?.scanQr() ?? unavailable(),
  applyConfig: (opts) => nativePlugin()?.applyConfig(opts) ?? unavailable(),
  setServer: (opts) => nativePlugin()?.setServer(opts) ?? unavailable(),
  // getStatus resolves instead of rejecting so callers can render a first-run page on the
  // web without a try/catch around every mount.
  getStatus: () => nativePlugin()?.getStatus() ?? Promise.resolve(NOT_CONFIGURED_STATUS),
  unpair: () => nativePlugin()?.unpair() ?? unavailable(),
  openAccessibilitySettings: () => nativePlugin()?.openAccessibilitySettings() ?? unavailable(),
  enableNotifications: () => nativePlugin()?.enableNotifications() ?? unavailable(),
  requestProjection: () => nativePlugin()?.requestProjection() ?? unavailable(),
  openBatterySettings: () => nativePlugin()?.openBatterySettings() ?? unavailable(),
  reloadApp: () => nativePlugin()?.reloadApp() ?? unavailable(),
  setActionOverlay: (options) => nativePlugin()?.setActionOverlay(options) ?? unavailable(),
  // Verified live on a real Capacitor Android bridge (CDP inspection, TASK-17): despite the
  // @capacitor/core web fallback and the TS types both promising Promise<{remove}>, the actual
  // native-bridge.js compiled into capacitor-android returns the listener handle SYNCHRONOUSLY
  // ({remove}, no `.then`). ThisPhonePage's unguarded `.then()` therefore threw a TypeError on
  // every single mount, and with no error boundary above it that unmounted the whole app to a
  // blank screen — the "black screen" from tapping the Phone icon. Promise.resolve() normalises
  // either shape (adopts a real promise, wraps a plain value) so every caller can keep awaiting.
  addListener: (eventName, cb) => {
    const plugin = nativePlugin();
    if (!plugin) return unavailable();
    return Promise.resolve(plugin.addListener(eventName, cb)) as Promise<{ remove: () => void }>;
  },
};
