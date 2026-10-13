/**
 * One unreachable server must not blank the pages the reachable ones feed.
 *
 * Dashboard and Devices render from `ServerManagerContext.serverHostsData`, and that
 * array used to be assigned once per round — after `Promise.all` over every configured
 * server. So a server that was slow to fail held every healthy server's hosts off the
 * screen until it gave up, with `isLoading` stuck true the whole time. That is not a
 * hypothetical wait: a server whose Supabase is unreachable keeps supabase-js retrying a
 * token refresh for ~30 s, and the token is resolved BEFORE the request is issued, so the
 * per-request 10 s AbortSignal never even got to run.
 *
 * These tests pin the replacement: each server lands on its own as it answers, and a
 * server that fails only removes itself.
 */
import { render, screen, waitFor } from '@testing-library/react';
import React, { useContext } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const urls = vi.hoisted(() => ({
  FAST: 'https://fast.example.test',
  SLOW: 'https://slow.example.test',
}));

vi.mock('../../frontend/src/utils/buildUrlUtils', () => ({
  getAllServerUrls: () => [urls.FAST, urls.SLOW],
  buildServerUrlForServer: (serverUrl: string, path: string) => `${serverUrl}${path}`,
}));

vi.mock('../../frontend/src/utils/apiClient', () => ({
  apiClient: vi.fn(),
}));

vi.mock('../../frontend/src/utils/serverSocket', () => ({
  createServerSocket: () => ({
    on: vi.fn(),
    off: vi.fn(),
    emit: vi.fn(),
    disconnect: vi.fn(),
    connected: false,
  }),
}));

vi.mock('../../frontend/src/lib/supabase', () => ({
  isAuthEnabled: false,
}));

const identity = vi.hoisted(() => ({
  // Per-server auth state the provider consults before spending a request.
  states: new Map<string, string>(),
  known: new Set<string>(),
  discover: vi.fn(),
}));

vi.mock('../../frontend/src/lib/serverIdentity', () => ({
  discoverServerIdentity: vi.fn(async (serverUrl: string) => {
    identity.discover(serverUrl);
    identity.known.add(serverUrl);
    return null;
  }),
  getServerAuthInfo: (serverUrl: string) =>
    identity.known.has(serverUrl) ? { mode: 'supabase' } : undefined,
  getServerAuthState: vi.fn(async (serverUrl: string) =>
    identity.states.get(serverUrl) ?? 'no-auth-required',
  ),
}));

vi.mock('../../frontend/src/contexts/auth/AuthContext', () => ({
  useAuthContext: () => ({ isAuthenticated: true }),
}));

import { ServerManagerContext } from '../../frontend/src/contexts/ServerManagerContext';
import { ServerManagerProvider } from '../../frontend/src/contexts/ServerManagerProvider';
import { apiClient } from '../../frontend/src/utils/apiClient';

const apiClientMock = vi.mocked(apiClient);

/** A server that answers with one host. */
const hostsResponse = (serverName: string, hostName: string) => ({
  ok: true,
  status: 200,
  json: async () => ({
    server_info: { server_name: serverName },
    hosts: [{ host_name: hostName }],
  }),
});

const Probe: React.FC = () => {
  const context = useContext(ServerManagerContext);
  if (!context) return null;
  return (
    <div>
      <span data-testid="servers">
        {context.serverHostsData.map((entry) => entry.server_info.server_name).join(',')}
      </span>
      <span data-testid="hosts">
        {context.serverHostsData.flatMap((entry) => entry.hosts.map((h) => h.host_name)).join(',')}
      </span>
      <span data-testid="loading">{String(context.isLoading)}</span>
      <span data-testid="failed">{[...context.failedServers].join(',')}</span>
    </div>
  );
};

const renderProvider = () =>
  render(
    <ServerManagerProvider>
      <Probe />
    </ServerManagerProvider>,
  );

describe('ServerManagerProvider — per-server failure isolation', () => {
  beforeEach(() => {
    localStorage.clear();
    apiClientMock.mockReset();
    identity.states.clear();
    identity.known.clear();
    identity.discover.mockReset();
  });

  it('shows a reachable server’s hosts while another server is still hanging', async () => {
    apiClientMock.mockImplementation(async (url: string) => {
      // Never settles — the shape of a server stuck behind a stalled token refresh.
      if (url.startsWith(urls.SLOW)) return new Promise(() => {}) as any;
      return hostsResponse('Fast', 'host-a') as any;
    });

    renderProvider();

    await waitFor(() => expect(screen.getByTestId('servers')).toHaveTextContent('Fast'));
    expect(screen.getByTestId('hosts')).toHaveTextContent('host-a');
    // The spinner ends with the first answer too, rather than with the slowest server.
    expect(screen.getByTestId('loading')).toHaveTextContent('false');
  });

  it('drops only the server that failed, keeping the one that answered', async () => {
    apiClientMock.mockImplementation(async (url: string) => {
      if (url.startsWith(urls.SLOW)) throw new Error('network down');
      return hostsResponse('Fast', 'host-a') as any;
    });

    renderProvider();

    await waitFor(() => expect(screen.getByTestId('failed')).toHaveTextContent(urls.SLOW));
    expect(screen.getByTestId('servers')).toHaveTextContent('Fast');
    expect(screen.getByTestId('hosts')).toHaveTextContent('host-a');
  });

  it('never calls a server we hold no session for, even on the first paint', async () => {
    // The pre-filter reads a map that is still empty on the first load — filling it takes
    // a round trip per server — so the decision has to be made per server, inside the
    // fetch. Before that, a server behind a different Supabase was called once per load
    // and answered 401 every time.
    identity.states.set(urls.SLOW, 'needs-auth');
    apiClientMock.mockImplementation(async (url: string) => {
      if (url.startsWith(urls.SLOW)) throw new Error('should never be called');
      return hostsResponse('Fast', 'host-a') as any;
    });

    renderProvider();

    await waitFor(() => expect(screen.getByTestId('servers')).toHaveTextContent('Fast'));
    expect(apiClientMock).toHaveBeenCalledTimes(1);
    expect(apiClientMock.mock.calls[0][0]).toContain(urls.FAST);
  });

  it('does not report a server that only needs a login as failed', async () => {
    // failedServers drives the picker's "Offline" badge. A server waiting for a login is
    // reachable and selectable — collapsing the two reads as a broken deployment.
    identity.states.set(urls.SLOW, 'needs-auth');
    apiClientMock.mockImplementation(async () => hostsResponse('Fast', 'host-a') as any);

    renderProvider();

    await waitFor(() => expect(screen.getByTestId('servers')).toHaveTextContent('Fast'));
    expect(screen.getByTestId('failed')).toHaveTextContent('');
  });

  it('keeps the configured server order however the answers arrive', async () => {
    let releaseFast: (() => void) | undefined;
    const fastGate = new Promise<void>((resolve) => {
      releaseFast = resolve;
    });

    apiClientMock.mockImplementation(async (url: string) => {
      if (url.startsWith(urls.SLOW)) return hostsResponse('Slow', 'host-b') as any;
      await fastGate;
      return hostsResponse('Fast', 'host-a') as any;
    });

    renderProvider();

    // The second-configured server answers first and renders on its own...
    await waitFor(() => expect(screen.getByTestId('servers')).toHaveTextContent('Slow'));

    releaseFast?.();

    // ...and the first-configured one still takes its configured place once it lands.
    await waitFor(() => expect(screen.getByTestId('servers')).toHaveTextContent('Fast,Slow'));
  });
});
