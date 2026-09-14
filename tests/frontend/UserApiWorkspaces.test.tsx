import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

import UserApiWorkspaces from '../../frontend/src/pages/UserApiWorkspaces';

describe('UserApiWorkspaces page', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the API Testing Workspaces heading', async () => {
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

    expect(await screen.findByRole('heading', { name: 'API Testing Workspaces' })).toBeInTheDocument();
  });
});
