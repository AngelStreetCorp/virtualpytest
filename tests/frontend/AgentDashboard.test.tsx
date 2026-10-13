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

// The page reads the signed-in user's role through useProfile() -> useAuthContext(), which throws
// outside an AuthProvider; mock the hook rather than put a Supabase session behind a render test.
vi.mock('../../frontend/src/hooks/auth/useProfile', () => ({
  useProfile: () => ({ isAdmin: false }),
}));

import AgentDashboard from '../../frontend/src/pages/AgentDashboard';

describe('AgentDashboard page', () => {
  it('renders the Agents heading', async () => {
    render(<AgentDashboard />);

    expect(await screen.findByRole('heading', { name: 'Agents' })).toBeInTheDocument();
  });
});
