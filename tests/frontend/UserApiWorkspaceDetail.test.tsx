import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import UserApiWorkspaceDetail from '../../frontend/src/pages/UserApiWorkspaceDetail';

describe('UserApiWorkspaceDetail page', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a not-found state when the workspace cannot be loaded', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: false }),
      }),
    );

    render(
      <BrowserRouter>
        <UserApiWorkspaceDetail />
      </BrowserRouter>,
    );

    expect(await screen.findByText('Workspace not found')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Back to Workspaces/i })).toBeInTheDocument();
  });
});
