import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  workspace: { activeWorkspace: null },
  server: { selectedServer: 'server-a' },
  permissions: { hasPermission: () => true },
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() },
}));

vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => mocks.workspace,
}));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({ useServerManager: () => mocks.server }));
vi.mock('../../frontend/src/hooks/auth/usePermissions', () => ({ usePermissions: () => mocks.permissions }));
vi.mock('../../frontend/src/hooks/useToast', () => ({ useToast: () => mocks.toast, default: () => mocks.toast }));
vi.mock('../../frontend/src/hooks/reports/runManagementApi', async () => {
  const actual = await vi.importActual<typeof import('../../frontend/src/hooks/reports/runManagementApi')>(
    '../../frontend/src/hooks/reports/runManagementApi',
  );
  return {
    ...actual,
    fetchDefects: vi.fn(),
    createDefect: vi.fn(),
    pushDefectToJira: vi.fn(),
  };
});

import * as rmApi from '../../frontend/src/hooks/reports/runManagementApi';
import { DefectsPanel, RESOLVE_NOTE } from '../../frontend/src/components/reports/DefectsPanel';
import { ApiError } from '../../frontend/src/hooks/reports/runManagementApi';
import type { Defect } from '../../frontend/src/types/reports';

const defect: Defect = {
  id: 'd-1',
  title: 'Zapping freezes on channel 4',
  severity: 'high',
  status: 'open',
  integration: 'local',
  assignee: null,
  description: null,
  external_key: null,
  external_status: null,
  external_updated_at: null,
  external_url: null,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-02T00:00:00Z',
};

const renderPanel = (ids: string[]) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DefectsPanel scriptResultIds={ids} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('DefectsPanel', () => {
  beforeEach(() => {
    vi.mocked(rmApi.fetchDefects).mockReset();
    vi.mocked(rmApi.createDefect).mockReset();
    vi.mocked(rmApi.pushDefectToJira).mockReset();
  });

  it('creates a local defect linked to every given result as evidence', async () => {
    vi.mocked(rmApi.fetchDefects).mockResolvedValue({ items: [] });
    vi.mocked(rmApi.createDefect).mockResolvedValue(defect);
    const user = userEvent.setup();
    renderPanel(['r-1', 'r-2']);

    expect(await screen.findByText('No defects linked.')).toBeInTheDocument();
    expect(screen.getByText(RESOLVE_NOTE)).toBeInTheDocument();
    // One query per result, no unscoped team-wide read.
    expect(rmApi.fetchDefects).toHaveBeenCalledWith({ script_result_id: 'r-1' }, expect.anything());
    expect(rmApi.fetchDefects).toHaveBeenCalledWith({ script_result_id: 'r-2' }, expect.anything());

    await user.click(screen.getByRole('button', { name: 'New defect' }));
    await user.type(screen.getByLabelText('Title'), '  Zapping freezes  ');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    expect(rmApi.createDefect).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Zapping freezes', severity: 'medium', script_result_ids: ['r-1', 'r-2'] }),
      expect.anything(),
    );
  });

  it('merges a defect linked to several results into one row', async () => {
    // GET /server/defects envelope: {items, total, limit, offset}.
    vi.mocked(rmApi.fetchDefects).mockResolvedValue({ items: [defect], total: 1 });
    renderPanel(['r-1', 'r-2']);
    expect(await screen.findAllByTestId('defect-d-1')).toHaveLength(1);
  });

  it('retries a Jira push explicitly and explains an unknown outcome (server dedupes per defect)', async () => {
    vi.mocked(rmApi.fetchDefects).mockResolvedValue({ items: [defect], total: 1 });
    vi.mocked(rmApi.pushDefectToJira)
      .mockRejectedValueOnce(new ApiError(504, 'Jira timed out', { state: 'unknown', retryable: true }))
      .mockResolvedValueOnce({ state: 'created', idempotent: true, external_key: 'QA-12', external_url: null });
    const user = userEvent.setup();
    renderPanel(['r-1']);

    await user.click(await screen.findByRole('button', { name: 'Push to Jira' }));
    await waitFor(() => expect(rmApi.pushDefectToJira).toHaveBeenCalledTimes(1));
    expect(mocks.toast.showError).toHaveBeenCalledWith(expect.stringMatching(/no duplicate will be created/));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Push to Jira' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Push to Jira' }));
    await waitFor(() => expect(rmApi.pushDefectToJira).toHaveBeenCalledTimes(2));
    // The push body carries no client key: the server keeps one push record per defect.
    expect(vi.mocked(rmApi.pushDefectToJira).mock.calls.map((call) => call[0])).toEqual(['d-1', 'd-1']);
  });
});
