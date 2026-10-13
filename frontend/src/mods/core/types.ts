/**
 * Mod layer types (TASK-77). A mod listens to app events and draws into named slots,
 * each through a `next()` chain, like Claude Code mods.
 */
import type { ComponentType, ReactNode } from 'react';

/** One `execution_update` from the /system socket, normalised. */
export interface RunEvent {
  id: string;
  /** `script`, `campaign`, `testcase`, … as the server sends it. */
  kind: string;
  status: string;
  progress?: number;
  message?: string;
  step?: string;
  stepNumber?: number;
  totalSteps?: number;
  hostName?: string;
  deviceId?: string;
  error?: string;
  timestamp: number;
}

/** A device was locked (Take Control, a run) or released. From `lock_changed`. */
export interface DeviceLockEvent {
  hostName: string;
  deviceId: string;
  locked: boolean;
  ownerName?: string;
  /** `manual_control`, `script`, … as the server sends it. */
  ownerType?: string;
  timestamp: number;
}

/** A host registered, unregistered or sent its heartbeat. From `host_registered` / `host_unregistered` / `host_ping`. */
export interface HostStatusEvent {
  hostName: string;
  status: 'online' | 'offline' | 'alive';
  timestamp: number;
}

/** Take Control finished setting up, or failed. From `control_ready` / `control_failed`. */
export interface DeviceControlEvent {
  hostName: string;
  deviceId: string;
  ready: boolean;
  error?: string;
  timestamp: number;
}

/** A deployment or one of its executions changed. From `deployment_changed` / `deployment_execution_changed`. */
export interface DeploymentEvent {
  action?: string;
  deploymentId?: string;
  executionId?: string;
  status?: string;
  timestamp: number;
}

/** An AI agent logged work (chat turn, verdict, decision). From `agent_activity`. */
export interface AgentActivityEvent {
  agentId: string;
  summary?: string;
  level?: string;
  timestamp: number;
}

/** Who is connected now in this team. From `presence_changed` (on every connect and disconnect). */
export interface PresenceEvent {
  online: number;
  users: { userId: string; name: string }[];
  /** Connections from a shared login (service key, auto-sign, open mode): not counted as people. */
  sharedSessions: number;
  timestamp: number;
}

/**
 * A page in this browser took or released control of a device. Sent by the app (useDeviceControl),
 * not the server; `owner` is the hook's session name ('navigation-editor-session', …).
 */
export interface ControlChangeEvent {
  hostName: string;
  deviceId: string;
  active: boolean;
  owner: string;
  timestamp: number;
}

/** Events a mod can hook, by name. */
export interface ModEvents {
  'run.update': RunEvent;
  'device.lock': DeviceLockEvent;
  'host.status': HostStatusEvent;
  'device.control': DeviceControlEvent;
  'deployment.change': DeploymentEvent;
  'agent.activity': AgentActivityEvent;
  'presence.update': PresenceEvent;
  'control.change': ControlChangeEvent;
}
export type ModEventName = keyof ModEvents;

/** One event with its name, as the socket mapper hands it over. */
export type ModEventEnvelope = { [K in ModEventName]: { name: K; e: ModEvents[K] } }[ModEventName];

/** A command about to be sent to a device. Asked before sending; a mod may refuse it. */
export interface DeviceCommandEvent {
  hostName: string;
  deviceId: string;
  /** `power_on`, `power_off`, `reboot`. */
  command: string;
  source: 'power';
}

export type GateResult = { allow: true } | { allow: false; reason: string };

/** Questions a mod can answer before the app acts: allow, or refuse with a reason. */
export interface ModGates {
  'device.command': DeviceCommandEvent;
}
export type GateName = keyof ModGates;

/** Slots a mod can draw into, by name, with the props the slot passes. */
export interface ModSlots {
  /** Right of the top navigation, before the user menu (desktop only). */
  'app.header': Record<string, never>;
  'app.band': Record<string, never>;
  /** A fixed layer over every page for floating panels (picture-in-picture); clicks pass through it. */
  'app.overlay': Record<string, never>;
  /** Beside the page content, full height (split view's second page). */
  'app.side': Record<string, never>;
  'app.pane': { paneId: string };
}
export type SlotName = keyof ModSlots;

export type ToastSeverity = 'success' | 'error' | 'warning' | 'info';

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmText: string;
  /** Red confirm button. */
  danger?: boolean;
}

/** `$`: everything a mod may reach outside itself. */
export interface ModApi {
  ui: {
    toast: (text: string, severity?: ToastSeverity) => void;
    openPane: (paneId: string) => void;
    closePane: () => void;
    /** Ask the user; resolves true on confirm, false on cancel. */
    confirm: (options: ConfirmOptions) => Promise<boolean>;
  };
  clock: { now: () => number };
}

/** Call `next(e)` to pass on (or a changed `e`); return without it to stop the chain. */
export type EventHook<K extends ModEventName> = (
  $: ModApi,
  e: ModEvents[K],
  next: (e: ModEvents[K]) => void,
) => void;

/** Return a tree to draw, or `next()` to leave it to lower mods / the default. */
export type SlotHook<K extends SlotName> = (
  $: ModApi,
  props: ModSlots[K],
  next: () => ReactNode,
) => ReactNode;

/** Return `next(e)` to leave the decision to later mods, or `{ allow: false, reason }` to refuse. */
export type GateHook<K extends GateName> = (
  $: ModApi,
  e: ModGates[K],
  next: (e: ModGates[K]) => Promise<GateResult>,
) => Promise<GateResult> | GateResult;

export interface On {
  <K extends ModEventName>(event: K, hook: EventHook<K>): void;
  <K extends SlotName>(slot: K, hook: SlotHook<K>): void;
  <K extends GateName>(gate: K, hook: GateHook<K>): void;
}

/** Widgets take a column span of a 6-column area: small 2, medium 3, large 6. */
export type WidgetSize = 'small' | 'medium' | 'large';

/** One setting of a widget, edited in its settings dialog. */
export interface WidgetSettingField {
  key: string;
  /** English, a t() key. */
  label: string;
  type: 'select' | 'boolean';
  /** For `select`: English labels are t() keys. */
  options?: { value: string; label: string }[];
  default: string | boolean;
}

export type WidgetSettings = Record<string, string | boolean>;

export interface WidgetProps {
  settings: WidgetSettings;
  $: ModApi;
}

/** A tile a mod offers; the user places it (several times if they like) in a widget area. */
export interface WidgetDefinition {
  id: string;
  /** English, a t() key. */
  name: string;
  description: string;
  size: WidgetSize;
  settings?: WidgetSettingField[];
  Component: ComponentType<WidgetProps>;
}

/** Where widgets can be placed. */
export type WidgetAreaName = 'dashboard';

/** One placed widget: which widget, with which settings. */
export interface WidgetInstance {
  id: string;
  widgetId: string;
  settings: WidgetSettings;
}

export interface ModDefinition {
  id: string;
  /** English, shown through t() on the Mods page. */
  name: string;
  description: string;
  /** On for a user who never touched its switch. */
  defaultEnabled: boolean;
  register: (on: On) => void;
  /** Widgets this mod offers while it is on. */
  widgets?: WidgetDefinition[];
}

export interface ModRegistry {
  mods: ModDefinition[];
  /** Widgets of the mods that are on. */
  widgets: WidgetDefinition[];
  emit: <K extends ModEventName>($: ModApi, event: K, e: ModEvents[K]) => void;
  dispatch: ($: ModApi, envelope: ModEventEnvelope) => void;
  /** Ask every mod hooked on `gate`; allowed when none refuses. */
  gate: <K extends GateName>($: ModApi, gate: K, e: ModGates[K]) => Promise<GateResult>;
  render: <K extends SlotName>($: ModApi, slot: K, props: ModSlots[K], fallback: ReactNode) => ReactNode;
}
