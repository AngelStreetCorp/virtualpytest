import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
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

// This page gates UI on permissions via usePermissions() -> usePermissionContext(), which
// throws outside a PermissionProvider. Mocked at the module boundary, the same way every
// other provider in this suite is (see Dashboard.test.tsx), rather than wrapping the tree
// in real providers that would then want a real session.
vi.mock('../../frontend/src/contexts/auth/PermissionContext', () => ({
  PermissionProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePermissionContext: () => ({
    role: 'admin',
    permissions: ['*'],
    hasRole: () => true,
    hasPermission: () => true,
    canAccess: () => true,
  }),
}));

// The page renders the signed-in user; useAuthContext() throws outside an AuthProvider.
vi.mock('../../frontend/src/contexts/auth/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuthContext: () => ({
    user: null,
    profile: null,
    session: null,
    isLoading: false,
    isAuthenticated: true,
    signInWithGoogle: async () => {},
    signInWithGithub: async () => {},
    signInWithEmail: async () => {},
    signUpWithEmail: async () => {},
    resetPassword: async () => {},
    signOut: async () => {},
    refreshProfile: async () => {},
  }),
}));

import Users from '../../frontend/src/pages/Users';

// The page's own data hooks are mocked above, but something below it still reaches for a
// react-query client (useQueryClient in the un-mocked half of hooks/pages/useUsers's
// module graph). Give it a real client rather than mocking @tanstack/react-query — a real
// one with retry off is less code and cannot drift from the library's API.
const withProviders = (ui: React.ReactNode) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe('Users page', () => {
  it('renders the Users Management heading', () => {
    render(withProviders(<Users />));

    expect(screen.getByRole('heading', { name: 'Users Management' })).toBeInTheDocument();
    expect(screen.getByText('No users found.')).toBeInTheDocument();
  });
});
