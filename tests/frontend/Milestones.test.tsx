/**
 * Milestones: archive/restore (never delete), permission-aware controls, no coverage claims.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
  const mutation = () => ({ mutateAsync: vi.fn(async () => ({})), isPending: false });
  return {
    permissions: { canEdit: true },
    milestones: {
      data: {
        items: [
          {
            id: 'm-1',
            name: 'Release 1.0',
            description: null,
            due_at: '2026-12-01T00:00:00Z',
            completed_at: null,
            archived: false,
            created_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-01T00:00:00Z',
          },
          {
            id: 'm-2',
            name: 'Old release',
            description: 'shipped',
            due_at: null,
            completed_at: '2025-01-15T00:00:00Z',
            archived: true,
            created_at: '2025-01-01T00:00:00Z',
            updated_at: '2025-01-15T00:00:00Z',
          },
        ],
      },
      isLoading: false,
      error: null,
    },
    mutations: {
      createMilestone: mutation(),
      updateMilestone: mutation(),
      archiveMilestone: mutation(),
      restoreMilestone: mutation(),
    },
  };
});

vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({ showSuccess: () => {}, showError: () => {}, showInfo: () => {}, showWarning: () => {} }),
}));
vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useMilestones: () => h.milestones,
  useReportPermissions: () => h.permissions,
  useGovernanceMutations: () => h.mutations,
}));

import Milestones from '../../frontend/src/pages/Milestones';

const renderPage = (url = '/test-results/milestones?archived=1') =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Milestones />
    </MemoryRouter>,
  );

describe('Milestones page', () => {
  beforeEach(() => {
    h.permissions.canEdit = true;
    Object.values(h.mutations).forEach((m) => m.mutateAsync.mockClear());
  });

  it('offers archive and restore, never delete', () => {
    renderPage();
    expect(screen.getByRole('button', { name: 'Archive' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
    expect(screen.queryByText(/delete/i)).toBeNull();
    expect(screen.queryByText(/coverage/i)).toBeNull();
  });

  it('archives and restores by id', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }));
    await waitFor(() => expect(h.mutations.archiveMilestone.mutateAsync).toHaveBeenCalledWith('m-1'));
    fireEvent.click(screen.getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(h.mutations.restoreMilestone.mutateAsync).toHaveBeenCalledWith('m-2'));
  });

  it('does not show a result count the list endpoint never sends', () => {
    renderPage();
    expect(screen.queryByRole('columnheader', { name: 'Results' })).toBeNull();
  });

  it('hides write controls without the edit permission', () => {
    h.permissions.canEdit = false;
    renderPage();
    expect(screen.queryByRole('button', { name: 'New milestone' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Archive' })).toBeNull();
  });

  it('marks an open milestone completed through completed_at', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Mark completed' }));
    await waitFor(() =>
      expect(h.mutations.updateMilestone.mutateAsync).toHaveBeenCalledWith({
        id: 'm-1',
        input: { completed_at: expect.any(String) },
      }),
    );
  });
});
