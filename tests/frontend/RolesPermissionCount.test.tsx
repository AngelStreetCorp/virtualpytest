import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

const { mockRoles, mockUpdateRole } = vi.hoisted(() => ({
  mockRoles: { manager: [] as string[], viewer: [] as string[] },
  mockUpdateRole: vi.fn().mockResolvedValue({}),
}));

vi.mock('../../frontend/src/hooks/pages/useRoles', () => ({
  useRoles: () => ({
    roles: mockRoles,
    catalog: [
      { role: 'manager', display_name: 'Manager', rank: 1, editable: true, allowed_devices: null },
      { role: 'viewer', display_name: 'Viewer', rank: 4, editable: true, allowed_devices: null },
    ],
    adminOnly: new Set<string>(),
    roleLabel: (role: string) => role,
    roleRank: () => 0,
    isLoading: false,
    error: null,
    updateRole: mockUpdateRole,
    isUpdating: false,
    updateError: null,
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useUsers', () => ({
  useUsers: () => ({ users: [] }),
}));

vi.mock('../../frontend/src/hooks/auth/usePermissions', () => ({
  usePermissions: () => ({ hasPermission: () => true }),
}));

import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';
import Roles from '../../frontend/src/pages/Roles';

/**
 * BUG-0787: the Roles page counted the stored list, the Users page counted the
 * effective one (the permissions the app knows). A role row holding a permission
 * the app has no route for (team:projects:view / :edit / :delete) made the two
 * pages disagree — Manager 68 vs 65 — and made every save of that role fail.
 */
describe('the Roles page counts the permissions the app can honour', () => {
  it('does not count a stored permission the app does not know', () => {
    mockRoles.manager = ['dashboard:view', 'device_control:view', 'team:projects:view', 'team:projects:edit'];
    mockRoles.viewer = ['dashboard:view'];

    render(
      <CustomThemeProvider>
        <MemoryRouter>
          <Roles />
        </MemoryRouter>
      </CustomThemeProvider>,
    );

    // Manager holds 2 known permissions (the two team:projects:* are unknown to the app).
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.queryByText('4')).not.toBeInTheDocument();
  });
});
