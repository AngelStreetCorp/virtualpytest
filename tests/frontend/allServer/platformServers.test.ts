/**
 * Platform server list store (TASK-179 P2).
 *
 * The picker's servers come from `GET /server/servers`: enabled rows only, in the table's
 * sort order, merged behind the primary (VITE_SERVER_URL) without duplicating it. The copy kept
 * in localStorage serves the first paint; whatever the server answers replaces it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiClientMock = vi.fn();
vi.mock('../../../frontend/src/utils/apiClient', () => ({
  apiClient: (...args: unknown[]) => apiClientMock(...args),
}));

import {
  PLATFORM_SERVERS_CACHE_KEY,
  getPlatformServers,
  getPlatformServersVersion,
  refreshPlatformServers,
  resetPlatformServersForTest,
  setPlatformServers,
  subscribePlatformServers,
} from '../../../frontend/src/lib/allServer/platformServers';
import { getAllServerUrls } from '../../../frontend/src/utils/buildUrlUtils';

const PRIMARY = 'https://primary.example.com';
const answer = (servers: unknown[]) =>
  apiClientMock.mockResolvedValue({
    ok: true,
    statusText: 'OK',
    json: async () => ({ success: true, servers, self_name: 'A', self_in_list: true, warning: null }),
  });

describe('platform server list store', () => {
  beforeEach(() => {
    localStorage.clear();
    apiClientMock.mockReset();
    resetPlatformServersForTest();
    (window as unknown as Record<string, unknown>).__VPT_CONFIG__ = { VITE_SERVER_URL: PRIMARY };
  });

  it('answers with the primary alone before anything is loaded or cached', () => {
    expect(getAllServerUrls()).toEqual([PRIMARY]);
  });

  it('uses the cached copy before the fetch lands', () => {
    localStorage.setItem(
      PLATFORM_SERVERS_CACHE_KEY,
      JSON.stringify([{ name: 'b', url: 'https://b.example.com', enabled: true, sort_order: 1 }]),
    );
    resetPlatformServersForTest();

    expect(getAllServerUrls()).toEqual([PRIMARY, 'https://b.example.com']);
  });

  it('merges the fetched rows behind the primary: sort order, no duplicate, no disabled', async () => {
    answer([
      { name: 'z', url: 'https://z.example.com', enabled: true, sort_order: 30 },
      { name: 'main', url: `${PRIMARY}/`, enabled: true, sort_order: 0 },
      { name: 'off', url: 'https://off.example.com', enabled: false, sort_order: 5 },
      { name: 'b', url: 'https://b.example.com', enabled: true, sort_order: 10 },
    ]);

    await refreshPlatformServers(`${PRIMARY}/server/servers`);

    expect(getAllServerUrls()).toEqual([PRIMARY, 'https://b.example.com', 'https://z.example.com']);
  });

  it('lets the fetched list win over the cache and rewrites the cache', async () => {
    setPlatformServers([{ name: 'old', url: 'https://old.example.com', enabled: true, sort_order: 1 }]);
    answer([{ name: 'new', url: 'https://new.example.com', enabled: true, sort_order: 1 }]);

    await refreshPlatformServers(`${PRIMARY}/server/servers`);

    expect(getAllServerUrls()).toEqual([PRIMARY, 'https://new.example.com']);
    expect(localStorage.getItem(PLATFORM_SERVERS_CACHE_KEY)).toContain('new.example.com');
  });

  it('keeps the current list when the fetch fails', async () => {
    setPlatformServers([{ name: 'b', url: 'https://b.example.com', enabled: true, sort_order: 1 }]);
    apiClientMock.mockRejectedValue(new Error('offline'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    await refreshPlatformServers(`${PRIMARY}/server/servers`);

    expect(getPlatformServers().map((s) => s.name)).toEqual(['b']);
    warn.mockRestore();
  });

  it('notifies subscribers only when the list really changes', () => {
    const listener = vi.fn();
    const stop = subscribePlatformServers(listener);
    const rows = [{ name: 'b', url: 'https://b.example.com', enabled: true, sort_order: 1 }];

    setPlatformServers(rows);
    setPlatformServers(rows);
    const version = getPlatformServersVersion();
    stop();
    setPlatformServers([]);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(version).toBe(1);
  });
});
