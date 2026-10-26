import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserRouter, MemoryRouter, Route, Routes } from 'react-router-dom';

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

  it('opens the workspace when the Postman workspace id is pasted (BUG-0796)', async () => {
    const workspaces = [{
      id: 'workspace-virtualpytest',
      name: 'VirtualPyTest API',
      description: '',
      workspaceId: '4e7a465c-a542-4440-8903-48787f03942a',
    }];
    const asked = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      json: async () => (url.includes('/collections')
        ? { success: true, collections: [] }
        : { success: true, workspaces }),
    }));
    vi.stubGlobal('fetch', asked);

    render(
      <MemoryRouter initialEntries={['/api/workspace/4e7a465c-a542-4440-8903-48787f03942a']}>
        <Routes>
          <Route path="/api/workspace/:workspaceId" element={<UserApiWorkspaceDetail />} />
        </Routes>
      </MemoryRouter>,
    );

    // The workspace was found, and the collections were asked for with the id
    // the backend resolves.
    await waitFor(() => {
      const urls = asked.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('/server/postman/workspaces/workspace-virtualpytest/collections'))).toBe(true);
    });
    expect(screen.queryByText('Workspace not found')).not.toBeInTheDocument();
  });
});
