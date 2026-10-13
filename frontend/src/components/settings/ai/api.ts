/**
 * Settings → AI API calls (TASK-30). All errors surface the backend `error` string
 * (api.* throws Error(body.error || body.message)).
 */

import { APP_CONFIG } from '../../../config/constants';
import { api } from '../../../utils/apiClient';
import { buildServerUrl, getServerBaseUrl } from '../../../utils/buildUrlUtils';

import type {
  AiConfig,
  AiScope,
  AiEndpoint,
  AiProfile,
  AiPrice,
  UnpricedEndpoint,
  BudgetResponse,
  AiRoute,
  AiUsageStats,
  EndpointTestResult,
  ProfileTestResult,
} from './types';

export const TEAM_ID: string = APP_CONFIG.DEFAULT_TEAM_ID;

/**
 * URL for a route of one layer. buildServerUrl always appends ?team_id=, which the
 * backend reads as "team override layer" on PUT/DELETE — the server-default layer
 * must be addressed without it.
 */
const routeUrl = (routeId: string, teamId: string | null): string =>
  teamId
    ? buildServerUrl(`/server/ai/routes/${routeId}`)
    : `${getServerBaseUrl()}/server/ai/routes/${routeId}`;

export type EndpointPayload = Partial<Omit<AiEndpoint, 'id' | 'has_secret' | 'needs_key' | 'secret_name'>> & {
  api_key?: string;
  clear_api_key?: boolean;
};
export type ProfilePayload = Partial<Omit<AiProfile, 'id'>>;
export type PricePayload = Partial<Omit<AiPrice, 'id' | 'created_at' | 'source'>>;
export type RoutePayload = Partial<Omit<AiRoute, 'id'>>;

export const aiApi = {
  getConfig: (scope: AiScope) =>
    api.get<AiConfig & { success: boolean }>(buildServerUrl(`/server/ai/config?scope_team=${encodeURIComponent(scope.team || 'all')}`)),
  getStats: (hours = 24, scope: AiScope = { team: '', project: '' }) =>
    api.get<{ success: boolean; usages: Record<string, AiUsageStats> }>(
      buildServerUrl(
        `/server/ai/stats?hours=${hours}&scope_team=${encodeURIComponent(scope.team || 'all')}${scope.project ? `&scope_project=${encodeURIComponent(scope.project)}` : ''}`,
      ),
    ),

  createEndpoint: (data: EndpointPayload) =>
    api.post<{ success: boolean; endpoint: AiEndpoint }>(buildServerUrl('/server/ai/endpoints'), data),
  updateEndpoint: (id: string, data: EndpointPayload) =>
    api.put<{ success: boolean; endpoint: AiEndpoint }>(buildServerUrl(`/server/ai/endpoints/${id}`), data),
  deleteEndpoint: (id: string) => api.delete<{ success: boolean }>(buildServerUrl(`/server/ai/endpoints/${id}`)),
  testEndpoint: (id: string, body: { api_key?: string; model?: string }) =>
    api.post<EndpointTestResult>(buildServerUrl(`/server/ai/endpoints/${id}/test`), body),

  createProfile: (data: ProfilePayload) =>
    api.post<{ success: boolean; profile: AiProfile }>(buildServerUrl('/server/ai/profiles'), data),
  updateProfile: (id: string, data: ProfilePayload) =>
    api.put<{ success: boolean; profile: AiProfile }>(buildServerUrl(`/server/ai/profiles/${id}`), data),
  deleteProfile: (id: string) => api.delete<{ success: boolean }>(buildServerUrl(`/server/ai/profiles/${id}`)),
  testProfile: (id: string, kind: ProfileTestResult['kind']) =>
    api.post<ProfileTestResult>(buildServerUrl(`/server/ai/profiles/${id}/test`), { kind }),

  getBudget: () => api.get<BudgetResponse>(buildServerUrl('/server/ai/usage/budget')),
  setBudget: (data: { team_id: string; month_limit_usd: number; mode: 'warn' | 'block'; warn_at: number }) =>
    api.put<{ success: boolean }>(buildServerUrl('/server/ai/budget'), data),
  deleteBudget: () => api.delete<{ success: boolean }>(buildServerUrl('/server/ai/budget')),
  listPrices: () => api.get<{ success: boolean; prices: AiPrice[]; unpriced?: UnpricedEndpoint[] }>(buildServerUrl('/server/ai/prices')),
  createPrice: (data: PricePayload) => api.post<{ success: boolean; price: AiPrice }>(buildServerUrl('/server/ai/prices'), data),
  deletePrice: (id: string) => api.delete<{ success: boolean }>(buildServerUrl(`/server/ai/prices/${id}`)),

  createRoute: (data: RoutePayload & { team_id: string | null }) =>
    api.post<{ success: boolean; route: AiRoute }>(buildServerUrl('/server/ai/routes'), data),
  updateRoute: (id: string, teamId: string | null, data: RoutePayload) =>
    api.put<{ success: boolean; route: AiRoute }>(routeUrl(id, teamId), data),
  deleteRoute: (id: string, teamId: string | null) => api.delete<{ success: boolean }>(routeUrl(id, teamId)),
};

export const errorMessage = (err: unknown, fallback: string): string =>
  err instanceof Error && err.message ? err.message : fallback;

/** '' → null, otherwise a number (NaN → null). */
export const numOrNull = (value: string): number | null => {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

export const strOrNull = (value: string): string | null => (value.trim() === '' ? null : value.trim());
