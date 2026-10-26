import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// UserApiWorkspaces calls usePermissions() -> usePermissionContext(), which
// throws outside a PermissionProvider. Mock at the module boundary, the
// same way Settings.test.tsx and Dashboard.test.tsx do.
vi.mock('../../frontend/src/hooks/auth/usePermissions', () => ({
  usePermissions: () => ({
    role: 'admin',
    permissions: ['*'],
    hasRole: () => true,
    hasPermission: () => true,
    canAccess: () => true,
  }),
}));

import UserApiWorkspaces from '../../frontend/src/pages/UserApiWorkspaces';

describe('UserApiWorkspaces page', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the Postman heading', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, workspaces: [] }),
      }),
    );

    render(
      <BrowserRouter>
        <UserApiWorkspaces />
      </BrowserRouter>,
    );

    expect(await screen.findByRole('heading', { name: 'Postman' })).toBeInTheDocument();
  });

  it('prints the id that opens the workspace (BUG-0796)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          workspaces: [{
            id: 'workspace-virtualpytest',
            name: 'VirtualPyTest API',
            description: '',
            // The Postman workspace id — a different thing, and not the one the
            // app's URL resolves.
            workspaceId: '4e7a465c-a542-4440-8903-48787f03942a',
          }],
        }),
      }),
    );

    render(
      <BrowserRouter>
        <UserApiWorkspaces />
      </BrowserRouter>,
    );

    // The id under "Workspace ID" is the one /api/workspace/<id> resolves.
    const label = await screen.findByText('Workspace ID:');
    const row = label.parentElement as HTMLElement;
    expect(row).toHaveTextContent('workspace-virtualpytest');
    expect(row).not.toHaveTextContent('4e7a465c-a542-4440-8903-48787f03942a');

    // The Postman id is shown, but labelled as the Postman one.
    expect(screen.getByText('Postman workspace ID:').parentElement).toHaveTextContent(
      '4e7a465c-a542-4440-8903-48787f03942a',
    );
  });
});
