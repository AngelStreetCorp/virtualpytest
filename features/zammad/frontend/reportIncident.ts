/**
 * "Open a ticket" - state shared by the dialog host, the Settings entry and any caller that wants
 * to pre-fill the dialog.
 *
 * A module store, not a React context: the Settings entry is a nav action (`nav.onSelect`) that runs
 * outside any component, and the dialog is mounted by core as an app overlay, so there is no provider
 * to wrap callers in. From a component: `const { open } = useReportIncident(); open({ family, category, targetId, targetLabel, ... })`
 * (G6 context buttons inside this feature do exactly that).
 *
 * `reportEnabled` mirrors GET /server/zammad/status (the Enabled switch AND a configured Zammad). It is
 * false until the answer arrives, so the entry never flashes up for a server that has support off.
 */
import { useSyncExternalStore } from 'react';

import { buildServerUrl } from '../../../frontend/src/utils/buildUrlUtils';
import type { Severity, TicketContext, TicketType } from './ticketModel';

export interface SupportAttachment {
  filename: string;
  /** Base64 of the file bytes, no data: prefix. */
  data_b64: string;
  mime_type: string;
}

/** Everything a caller may pre-fill when opening the "Open a ticket" dialog. */
export interface ReportIncidentOptions extends TicketContext {
  /** Defaults to incident. */
  ticketType?: TicketType;
  severity?: Severity;
  title?: string;
  /** Extra text put under the description (log lines, report link, Grafana URL...). */
  details?: string;
  attachments?: SupportAttachment[];
}

interface State {
  isOpen: boolean;
  options: ReportIncidentOptions;
  reportEnabled: boolean;
}

let state: State = { isOpen: false, options: {}, reportEnabled: false };
const listeners = new Set<() => void>();

const set = (patch: Partial<State>) => {
  state = { ...state, ...patch };
  listeners.forEach((fn) => fn());
};
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

export const openReportIncident = (options?: ReportIncidentOptions) => {
  if (state.reportEnabled) set({ isOpen: true, options: options ?? {} });
};
export const closeReportIncident = () => set({ isOpen: false });

export const isReportEnabled = (): boolean => state.reportEnabled;
export const setReportEnabled = (enabled: boolean) => set({ reportEnabled: enabled });

/** Re-reads the switch from the server. Any failure (not signed in yet, server down) counts as off. */
export const refreshReportEnabled = async (): Promise<void> => {
  try {
    const res = await fetch(buildServerUrl('/server/zammad/status'));
    const body = res.ok ? await res.json() : null;
    setReportEnabled(Boolean(body?.enabled));
  } catch {
    setReportEnabled(false);
  }
};

export const useReportIncidentState = (): State => useSyncExternalStore(subscribe, () => state);

/** `useReportIncident().open({ family, category, targetId, targetLabel, attachments })` from any component. */
export const useReportIncident = () => ({ open: openReportIncident, close: closeReportIncident });
