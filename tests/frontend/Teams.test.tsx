import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/hooks/pages/useTeams', () => ({
  useTeams: () => ({
    teams: [],
    isLoading: false,
    error: null,
    refetch: () => {},
    createTeam: async () => ({}),
    updateTeam: async () => ({}),
    deleteTeam: async () => {},
    isCreating: false,
    isUpdating: false,
    isDeleting: false,
    createError: null,
    updateError: null,
    deleteError: null,
  }),
  useTeamMembers: () => ({
    data: [],
    isLoading: false,
    refetch: async () => {},
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useUsers', () => ({
  useUsers: () => ({
    users: [],
    isLoading: false,
    error: null,
    refetch: () => {},
    updateUser: async () => ({}),
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

import Teams from '../../frontend/src/pages/Teams';

describe('Teams page', () => {
  it('renders the Teams Management heading', () => {
    render(<Teams />);

    expect(screen.getByRole('heading', { name: 'Teams Management' })).toBeInTheDocument();
  });
});
