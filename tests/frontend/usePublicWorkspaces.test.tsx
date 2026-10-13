/**
 * The anonymous public-workspaces fallback only asks a server that needs no login.
 *
 * `GET /server/workspaces` is not in the backend's UNAUTHENTICATED_SERVER_PREFIXES, so on
 * a server running in `supabase` mode it answers 401 to a caller with no session — and
 * this query is enabled *precisely because* there is no session. It therefore fired, and
 * failed, on every logged-out page load of a Supabase deployment. The `open` /
 * `public_key` deployments the fallback was written for still get their request.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const clients = vi.hoisted(() => ({ primary: { id: 'primary-client' } }));

vi.mock('../../frontend/src/lib/supabase', () => ({
  isAuthEnabled: true,
  supabase: clients.primary,
  PRIMARY_IDENTITY: 'https://primary.example.test/supabase',
  normalizeIdentity: (url: string) => (url || '').trim().replace(/\/+$/, '').toLowerCase(),
  getClientForIdentity: () => clients.primary,
  getSessionWithTimeout: async () => null,
}));

const SERVER = 'https://server.example.test';

vi.mock('../../frontend/src/utils/buildUrlUtils', () => ({
  getServerBaseUrl: () => SERVER,
  buildServerUrl: (path: string) => `${SERVER}${path}`,
}));

const apiGet = vi.hoisted(() => vi.fn());
vi.mock('../../frontend/src/utils/apiClient', () => ({
  api: { get: apiGet },
}));

import { usePublicWorkspaces } from '../../frontend/src/hooks/pages/useWorkspaces';
import {
  clearServerIdentities,
  registerServerIdentity,
} from '../../frontend/src/lib/serverIdentity';

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
};

describe('usePublicWorkspaces', () => {
  beforeEach(() => {
    localStorage.clear();
    clearServerIdentities();
    apiGet.mockReset();
    apiGet.mockResolvedValue([
      { id: 'w1', name: 'Public', is_public: true },
      { id: 'w2', name: 'Private', is_public: false },
    ]);
  });

  it('does not call a server that requires a Supabase login', async () => {
    registerServerIdentity(SERVER, {
      mode: 'supabase',
      identity: 'https://server.example.test/supabase',
      anonKey: 'anon',
    });

    const { result } = renderHook(() => usePublicWorkspaces(true), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiGet).not.toHaveBeenCalled();
  });

  it('does not call a server whose mode is not known yet', async () => {
    const { result } = renderHook(() => usePublicWorkspaces(true), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiGet).not.toHaveBeenCalled();
  });

  it('calls a server that needs no login, and keeps only the public workspaces', async () => {
    registerServerIdentity(SERVER, { mode: 'open' });

    const { result } = renderHook(() => usePublicWorkspaces(true), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual([
      { id: 'w1', name: 'Public', is_public: true },
    ]));
    expect(apiGet).toHaveBeenCalledWith(`${SERVER}/server/workspaces`);
  });

  it('stays silent while the caller has not enabled it, whatever the server mode', async () => {
    registerServerIdentity(SERVER, { mode: 'open' });

    const { result } = renderHook(() => usePublicWorkspaces(false), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiGet).not.toHaveBeenCalled();
  });
});
