/**
 * Platform server list store (TASK-179 P2).
 *
 * The servers the picker shows come from the database (`GET /server/servers`), not from a
 * build-time variable. `VITE_SERVER_URL` stays the one bootstrap address (the primary); every
 * other server is a row of `platform_servers`.
 *
 * This module is framework-free (like `serverIdentity`): `getAllServerUrls()` runs outside React
 * and must answer synchronously. It keeps the last list in memory, mirrors it to localStorage so
 * the first paint after a reload already has the picker (a per-viewer convenience: the fetched
 * list always wins), and notifies subscribers so `ServerManagerProvider` re-runs its fan-out when
 * the list changes. It deliberately imports nothing that builds URLs: the caller passes the URL.
 */
import { apiClient } from '../../utils/apiClient';

export interface PlatformServer {
  name: string;
  url: string;
  enabled: boolean;
  sort_order: number;
}

export interface PlatformServersPayload {
  servers: PlatformServer[];
  self_name: string | null;
  self_in_list: boolean;
  warning: string | null;
}

export const PLATFORM_SERVERS_CACHE_KEY = 'virtualpytest:platformServers';

const isRow = (value: unknown): value is PlatformServer => {
  const row = value as Partial<PlatformServer> | null;
  return !!row && typeof row.name === 'string' && typeof row.url === 'string';
};

const normalizeRows = (rows: unknown): PlatformServer[] =>
  (Array.isArray(rows) ? rows : []).filter(isRow).map((r) => ({
    name: r.name,
    url: r.url,
    enabled: r.enabled !== false,
    sort_order: Number.isFinite(Number(r.sort_order)) ? Number(r.sort_order) : 0,
  }));

const readCache = (): PlatformServer[] => {
  try {
    const raw = localStorage.getItem(PLATFORM_SERVERS_CACHE_KEY);
    return raw ? normalizeRows(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
};

const writeCache = (rows: PlatformServer[]): void => {
  try {
    localStorage.setItem(PLATFORM_SERVERS_CACHE_KEY, JSON.stringify(rows));
  } catch {
    // Private window or blocked storage: the cache is a convenience only.
  }
};

let rows: PlatformServer[] = readCache();
let version = 0;
const listeners = new Set<() => void>();

const publish = (next: PlatformServer[]): void => {
  const same = JSON.stringify(next) === JSON.stringify(rows);
  rows = next;
  writeCache(next);
  if (same) return;
  version += 1;
  listeners.forEach((listener) => listener());
};

/** Enabled servers, in the table's sort order (ties keep the table's own order). */
export const getPlatformServers = (): PlatformServer[] =>
  rows
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => row.enabled)
    .sort((a, b) => a.row.sort_order - b.row.sort_order || a.index - b.index)
    .map(({ row }) => row);

export const subscribePlatformServers = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** Changes whenever the published list changes: a stable `useSyncExternalStore` snapshot. */
export const getPlatformServersVersion = (): number => version;

/**
 * Fetch the full list (disabled rows included) from the primary. Used by the Settings editor,
 * which also wants `self_name` / `warning`. Throws on a failed request.
 */
export const fetchPlatformServersPayload = async (serversUrl: string): Promise<PlatformServersPayload> => {
  const response = await apiClient(serversUrl);
  const data = await response.json();
  if (!response.ok || data?.success === false) {
    throw new Error(data?.error || response.statusText || 'Failed to load the server list');
  }
  return {
    servers: normalizeRows(data.servers),
    self_name: data.self_name ?? null,
    self_in_list: data.self_in_list === true,
    warning: data.warning ?? null,
  };
};

/** Fetch the list and publish it; a failure keeps what the store already has. */
export const refreshPlatformServers = async (serversUrl: string): Promise<void> => {
  try {
    const payload = await fetchPlatformServersPayload(serversUrl);
    publish(payload.servers);
  } catch (error) {
    console.warn('[@platformServers] Failed to load the server list:', error);
  }
};

/** Publish a list the caller already holds (after a successful Settings save). */
export const setPlatformServers = (next: PlatformServer[]): void => publish(normalizeRows(next));

/** Test seam: reset the in-memory list from storage and drop subscribers. */
export const resetPlatformServersForTest = (): void => {
  rows = readCache();
  version = 0;
  listeners.clear();
};
