import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

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

import Users from '../../frontend/src/pages/Users';

describe('Users page', () => {
  it('renders the Users Management heading', () => {
    render(
      <BrowserRouter>
        <Users />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Users Management' })).toBeInTheDocument();
    expect(screen.getByText('No users found.')).toBeInTheDocument();
  });
});
