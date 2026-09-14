import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useWorkspaces', () => ({
  useWorkspaces: () => ({
    workspaces: [],
    isLoading: false,
    error: null,
    refetch: () => {},
    createWorkspace: async () => {},
    updateWorkspace: async () => {},
    deleteWorkspace: async () => {},
    addWorkspaceUser: async () => {},
    addWorkspaceTeam: async () => {},
    removeWorkspaceMember: async () => {},
    isCreating: false,
    isUpdating: false,
    isDeleting: false,
    createError: null,
    updateError: null,
    deleteError: null,
  }),
  useWorkspaceMembers: () => ({
    data: [],
    isLoading: false,
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useTeams', () => ({
  useTeams: () => ({
    teams: [],
    isLoading: false,
    error: null,
    refetch: () => {},
    createTeam: async () => {},
    updateTeam: async () => {},
    deleteTeam: async () => {},
    isCreating: false,
    isUpdating: false,
    isDeleting: false,
    createError: null,
    updateError: null,
    deleteError: null,
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useUsers', () => ({
  useUsers: () => ({
    users: [],
    isLoading: false,
    error: null,
    refetch: () => {},
    updateUser: async () => {},
    deleteUser: async () => {},
    assignUserToTeam: async () => {},
    isUpdating: false,
    isDeleting: false,
    isAssigningTeam: false,
    updateError: null,
    deleteError: null,
    assignTeamError: null,
  }),
}));

vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    selectedServer: 'server-1',
    availableServers: ['server-1'],
    setSelectedServer: () => {},
    serverHostsData: [],
    isLoading: false,
    error: null,
    pendingServers: new Set(),
    failedServers: new Set(),
    isServerChanging: false,
    refreshServerData: async () => {},
  }),
}));

import Workspaces from '../../frontend/src/pages/Workspaces';

describe('Workspaces page', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the Workspaces Management heading', async () => {
    // The (closed) create/edit dialog fetches the script list unconditionally on mount.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, scripts: [] }),
      }),
    );

    render(
      <BrowserRouter>
        <Workspaces />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Workspaces Management' })).toBeInTheDocument();
    expect(
      await screen.findByText('No workspaces found. Create your first workspace to get started.'),
    ).toBeInTheDocument();
  });
});
