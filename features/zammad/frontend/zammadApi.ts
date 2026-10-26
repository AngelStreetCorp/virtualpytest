/**
 * Zammad feature - typed calls to /server/zammad (the plugin page).
 *
 * Goes to the SELECTED server: each VirtualPyTest server keeps its own Zammad config in its own
 * zammad_instances.json (same reasoning as features/gitlab/frontend/gitlabApi.ts).
 * Creating a ticket lives in useSupportTickets.ts (the dialog's hook).
 */
import { buildServerUrl } from '../../../frontend/src/utils/buildUrlUtils';
import type { SupportTicket } from './useSupportTickets';

export interface ZammadConfig {
  name: string | null;
  base_url: string;
  public_url: string;
  enabled: boolean;
  has_token: boolean;
  configured: boolean;
  /** Where the URL in force came from: the page's form, the environment, or nowhere. */
  source: 'file' | 'env' | 'none';
}

export interface ZammadHealth {
  success: boolean;
  config: ZammadConfig;
  reachable: boolean;
  user?: string;
  error?: string;
}

export type TicketPeriod = 'today' | '7d' | '30d' | 'all';

export interface TicketFilters {
  period: TicketPeriod;
  /** Empty = the app's own team. */
  teamId?: string;
  /** created_by of the ticket. */
  user?: string;
  /** Workspace id: its teams and people (the AI usage Project filter). */
  project?: string;
  /** Ticket type, family and severity keys (ticketModel.ts). */
  type?: string;
  family?: string;
  severity?: string;
}

export interface TicketStats {
  opened: number;
  closed: number;
  /** Every ticket in scope, whatever the period. */
  total: number;
  /** People who opened tickets in scope, to fill the User filter. */
  users: { id: string; email: string }[];
}

/** A tickets URL with the filters applied. buildServerUrl always appends the app's team, so the team filter replaces it. */
function ticketsUrl(path: string, f: TicketFilters): string {
  const u = new URL(buildServerUrl(`/server/zammad${path}`), window.location.origin);
  if (f.teamId) u.searchParams.set('team_id', f.teamId);
  u.searchParams.set('period', f.period);
  if (f.user) u.searchParams.set('user', f.user);
  if (f.project) u.searchParams.set('project', f.project);
  if (f.type) u.searchParams.set('type', f.type);
  if (f.family) u.searchParams.set('family', f.family);
  if (f.severity) u.searchParams.set('severity', f.severity);
  return u.toString();
}

export interface FilterOption {
  key: string;
  label: string;
}

export interface ZammadConfigInput {
  base_url: string;
  /** Blank on edit keeps the stored token. */
  token?: string;
  public_url?: string;
  name?: string;
}

async function request<T>(path: string, init?: RequestInit, absolute = false): Promise<T> {
  const res = await fetch(absolute ? path : buildServerUrl(`/server/zammad${path}`), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((body as { error?: string }).error || `Request failed (${res.status})`);
  }
  return body as T;
}

export const zammadApi = {
  /** Team and Project dropdowns, from the same source as Monitoring -> AI usage. */
  filters: () => request<{ success: boolean; team: FilterOption[]; project: FilterOption[] }>('/filters'),

  health: () => request<ZammadHealth>('/health'),

  /** Tests the connection (GET /api/v1/users/me) first; a failure saves nothing and throws its reason. */
  saveConfig: (payload: ZammadConfigInput) =>
    request<{ success: boolean; config: ZammadConfig; user?: string }>('/config', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  setEnabled: (enabled: boolean) =>
    request<{ success: boolean; config: ZammadConfig }>('/enabled', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  tickets: (f: TicketFilters) =>
    request<{ success: boolean; tickets: SupportTicket[] }>(ticketsUrl('/tickets', f), undefined, true),

  stats: (f: TicketFilters) =>
    request<{ success: boolean } & TicketStats>(ticketsUrl('/tickets/stats', f), undefined, true),
};
