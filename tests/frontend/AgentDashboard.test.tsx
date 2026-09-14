import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ agents: [], runs: [], leaderboard: [] }),
    }),
  );
});

vi.mock('socket.io-client', () => ({
  io: () => ({
    on: () => {},
    disconnect: () => {},
  }),
}));

import { AgentDashboard } from '../../frontend/src/pages/AgentDashboard';

describe('AgentDashboard page', () => {
  it('renders the Agent Management heading', async () => {
    render(<AgentDashboard />);

    expect(await screen.findByRole('heading', { name: 'Agent Management' })).toBeInTheDocument();
  });
});
