/** Custom pages API (TASK-139). `buildServerUrl` appends the active team_id; failures throw `ApiError`. */

import type {
  Catalogue,
  CustomPage,
  CustomPageSummary,
  PageDefinition,
  PageOp,
  Sharing,
} from '../../types/customPages';
import { apiClient } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { ApiError } from '../reports/runManagementApi';

const BASE = '/server/custom-pages';

const request = async <T>(path: string, method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE' = 'GET', body?: unknown): Promise<T> => {
  const response = await apiClient(buildServerUrl(path), {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!response.ok) {
    const message =
      parsed && typeof parsed === 'object' && 'error' in parsed && typeof (parsed as { error: unknown }).error === 'string'
        ? (parsed as { error: string }).error
        : `HTTP ${response.status}`;
    throw new ApiError(response.status, message, parsed);
  }
  return parsed as T;
};

export const fetchPages = () => request<{ items: CustomPageSummary[] }>(BASE).then((r) => r.items);
export const fetchCatalogue = () => request<Catalogue>(`${BASE}/catalogue`);
export const fetchPage = (id: string) => request<CustomPage>(`${BASE}/${id}`);
export const createPage = (input: { title: string; definition?: PageDefinition | { blocks: unknown[] }; status?: 'draft' | 'saved' }) =>
  request<CustomPage>(BASE, 'POST', input);
export const updatePage = (
  id: string,
  input: { title?: string; definition?: PageDefinition; ops?: PageOp[]; status?: 'draft' | 'saved' },
) => request<CustomPage>(`${BASE}/${id}`, 'PATCH', input);
export const deletePage = (id: string) => request<{ deleted: boolean }>(`${BASE}/${id}`, 'DELETE');
export const fetchSharing = (id: string) => request<Sharing>(`${BASE}/${id}/sharing`);
export const saveSharing = (id: string, input: { visibility: 'private' | 'team'; shares: { user_id: string; can_edit: boolean }[] }) =>
  request<Sharing>(`${BASE}/${id}/sharing`, 'PUT', input);
