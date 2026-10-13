import type { GateName, ModEventName, SlotName } from './types';

export const EVENT_NAMES: readonly ModEventName[] = [
  'run.update',
  'device.lock',
  'host.status',
  'device.control',
  'deployment.change',
  'agent.activity',
  'presence.update',
  'control.change',
];
export const GATE_NAMES: readonly GateName[] = ['device.command'];
export const SLOT_NAMES: readonly SlotName[] = ['app.header', 'app.band', 'app.overlay', 'app.side', 'app.pane'];

/** Statuses after which a run sends no more updates. */
export const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  'completed',
  'failed',
  'aborted',
  'error',
  'skipped',
]);

/** /system socket event carrying execution lifecycle + progress. */
export const SYSTEM_UPDATE_EVENT = 'system_update';
/** `system_update` types mapped to mod events (core/mappers.ts). */
export const SYSTEM_TYPES = {
  execution: 'execution_update',
  lock: 'lock_changed',
  hostRegistered: 'host_registered',
  hostUnregistered: 'host_unregistered',
  hostPing: 'host_ping',
  controlReady: 'control_ready',
  controlFailed: 'control_failed',
  deployment: 'deployment_changed',
  deploymentExecution: 'deployment_execution_changed',
  agentActivity: 'agent_activity',
  presence: 'presence_changed',
} as const;

export const ALLOW: { allow: true } = { allow: true };

export const PANE_WIDTH = 380;

/** Per-browser on/off choice per mod id, like browser extensions. */
export const ENABLED_MODS_STORAGE_KEY = 'virtualpytest:mods:enabled';

/** Feature endpoints (features/mods/backend_server). */
export const SNAPSHOT_PATH = '/server/mods/snapshot';
export const WIDGETS_PATH = '/server/mods/widgets';
export const PREFERENCES_PATH = '/server/mods/preferences';

/** postMessage type an embedded app (split view's frame) uses to hand app events to the main window. */
export const FRAME_EVENT_MESSAGE = 'vpt-mod-event';

/** Per-browser layout of every widget area. */
export const WIDGET_LAYOUT_STORAGE_KEY = 'virtualpytest:mods:widgets';

export const WIDGET_COLUMNS = 6;
export const WIDGET_SPAN = { small: 2, medium: 3, large: 6 } as const;

/** Every widget area, synced to the account on load. */
export const WIDGET_AREAS = ['dashboard'] as const;
/** Edits within this delay are saved together. */
export const WIDGET_SAVE_DELAY_MS = 600;
