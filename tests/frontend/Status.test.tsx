import { render, screen } from '@testing-library/react';
import React from 'react';
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
const serverHostsData: unknown[] = [];
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData,
  }),
}));

import Status from '../../frontend/src/pages/Status';

describe('Status page', () => {
  it('renders the System Status heading', () => {
    render(<Status />);

    expect(screen.getByRole('heading', { name: 'System Status' })).toBeInTheDocument();
  });
});
