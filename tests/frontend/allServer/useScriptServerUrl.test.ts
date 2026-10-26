/**
 * TASK-113 — second migration tests: useScriptServerUrl.
 *
 * The hook's core logic is a Map<name, serverUrl> built from per-
 * server fetches. The tests below mock `useServerManager` to feed
 * the hook known host data, and assert the index correctly maps
 * each script to its home server.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

vi.mock('../../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData: [
      {
        server_info: { server_url: 'https://a.example.test', server_name: 'A' },
        hosts: [],
      },
      {
        server_info: { server_url: 'https://b.example.test', server_name: 'B' },
        hosts: [],
      },
    ],
    serverAuthStates: {
      'https://a.example.test': 'authenticated',
      'https://b.example.test': 'authenticated',
    },
    selectedServer: 'https://a.example.test',
  }),
}));

import { useScriptServerUrl } from '../../../frontend/src/hooks/allServer/useScriptServerUrl';

const makeResponse = (body: unknown) => ({
  ok: true,
  json: async () => body,
});

describe('useScriptServerUrl — single-server', () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('fetches from the selected server and indexes by name', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({
        success: true,
        executables: [{ name: 's-1' }, { id: 's-2' }],
      }),
    );
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.serverUrlFor('s-1')).toBe('https://a.example.test');
    expect(result.current.serverUrlFor('s-2')).toBe('https://a.example.test');
    expect(result.current.allEntries).toHaveLength(2);
    expect(result.current.allEntries[0]).toMatchObject({
      name: 's-1',
      server_url: 'https://a.example.test',
    });
  });

  it('falls back to the selected server when the script is not in the index', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({ success: true, executables: [] }),
    );
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.serverUrlFor('unknown-script')).toBe('https://a.example.test');
  });

  it('returns null for an empty name', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ success: true }));
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.serverUrlFor('')).toBeNull();
  });

  it('stamps every entry with the home server_url', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({
        success: true,
        executables: [{ name: 'a-1' }, { name: 'a-2' }],
      }),
    );
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    for (const e of result.current.allEntries) {
      expect(e.server_url).toBe('https://a.example.test');
    }
  });

  /**
   * BUG-0769: the URL was built by hand, so it carried no team_id and
   * `/server/campaigns/listExecutables` answered 400 "team_id is required" on
   * every load of every Run route. The hook swallowed the error, the index
   * stayed empty and the script-to-home-server lookup never resolved.
   */
  it('requests listExecutables with a team_id so the route does not answer 400', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({ success: true, executables: [{ name: 's-1' }] }),
    );
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const calledUrl = String(fetchMock.mock.calls[0]?.[0]);
    expect(calledUrl).toContain('/server/campaigns/listExecutables');
    expect(new URL(calledUrl).searchParams.get('team_id')).toBeTruthy();
  });

  it('indexes the scripts the route returns once team_id is carried', async () => {
    // The regression that matters: with team_id the route answers 200 and the
    // index is populated, so the Run page can resolve a script's home server.
    fetchMock.mockImplementation(async (url: string) => {
      const hasTeam = new URL(url).searchParams.get('team_id');
      return hasTeam
        ? makeResponse({ success: true, executables: [{ name: 's-1' }] })
        : { ok: false, status: 400, json: async () => ({ error: 'team_id is required' }) };
    });
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.serverUrlFor('s-1')).toBe('https://a.example.test');
    expect(result.current.allEntries).toHaveLength(1);
    expect(result.current.allEntries[0]).toMatchObject({
      name: 's-1',
      server_url: 'https://a.example.test',
    });
  });
});

describe('useScriptServerUrl — failures are surfaced (BUG-0769 review)', () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it('reports an error instead of an empty list when the route answers non-2xx', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      json: async () => ({ error: 'boom' }),
    });
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toContain('boom');
    expect(result.current.allEntries).toHaveLength(0);
  });

  it('has no error when the list loads', async () => {
    fetchMock.mockResolvedValue(makeResponse({ success: true, executables: [{ name: 's-1' }] }));
    const { result } = renderHook(() => useScriptServerUrl());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeNull();
  });
});
