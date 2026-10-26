import { render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    }),
  );
});

// Status.tsx has `useEffect(..., [serverHostsData])` — a fresh [] literal per
// call makes that dependency look changed every render, causing an infinite
// re-render loop severe enough to crash the Vitest worker (hit this exact bug
// backfilling on 2026-09-06). Hoist to a stable reference instead.
let serverHostsData: unknown[] = [];
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData,
  }),
}));

import Status from '../../frontend/src/pages/Status';

const host = (host_name: string) => ({
  host_name,
  host_url: `/host/${host_name}`,
  host_api_url: 'http://10.0.0.5:6109',
  host_port: 6109,
  devices: [],
  device_count: 0,
  status: 'online',
  last_seen: 0,
  registered_at: '2026-10-22T00:00:00Z',
  system_stats: {
    service_health: {
      overall_status: 'online',
      services: [
        { name: 'vpt-stream', label: 'Stream', status: 'active' },
        { name: 'vpt-host', label: 'Host API', status: 'active' },
      ],
    },
  },
});

const server = (server_url: string, hosts: unknown[]) => ({
  server_info: { server_url },
  hosts,
});

describe('Status page', () => {
  it('renders the System Status heading', () => {
    // Status.tsx calls `useSearchParams()` from react-router-dom; wrap in a
    // MemoryRouter so the hook has a Router context. (LAN-3812 failure).
    serverHostsData = [];
    render(
      <MemoryRouter>
        <Status />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'System Status' })).toBeInTheDocument();
  });

  /**
   * BUG-0771: host-clone-1 and host-clone-2 are registered on the primary
   * server AND on the QualiAI server, so the page flat-mapped both catalogs
   * and listed the two machines twice — and counted their services twice in
   * the "Services healthy" tile.
   */
  it('lists a host registered on two servers once', async () => {
    serverHostsData = [
      server('https://primary', [host('host-clone-1'), host('labox-backend')]),
      server('https://qualiai', [host('host-clone-1'), host('host-clone-2')]),
    ];

    render(
      <MemoryRouter>
        <Status />
      </MemoryRouter>,
    );

    const cloneOne = await screen.findAllByRole('button', { name: /Host: host-clone-1/ });
    expect(cloneOne).toHaveLength(1);

    const cloneTwo = await screen.findAllByRole('button', { name: /Host: host-clone-2/ });
    expect(cloneTwo).toHaveLength(1);

    const labox = await screen.findAllByRole('button', { name: /Host: labox-backend/ });
    expect(labox).toHaveLength(1);
  });
});
