import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ManualSession, ManualStep } from '../../frontend/src/types/reports';

const api = vi.hoisted(() => ({
  fetchManualSession: vi.fn(),
  fetchManualSessions: vi.fn(),
  fetchTestcases: vi.fn(),
  createManualSession: vi.fn(),
  updateManualSession: vi.fn(),
  finalizeManualSession: vi.fn(),
}));

vi.mock('../../frontend/src/hooks/reports/runManagementApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../frontend/src/hooks/reports/runManagementApi')>();
  return { ...actual, ...api };
});

const scope = { serverKey: 'server-a', hostFilter: undefined, deviceFilter: undefined };
const permissions = { canRunManual: true };
vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useReportScope: () => scope,
  useReportPermissions: () => permissions,
}));

const hosts = vi.hoisted(() => [
  {
    host_name: 'host-1',
    devices: [
      { device_id: 'device1', device_name: 'Living room TV' },
      { device_id: 'device2', device_name: 'Bedroom STB' },
    ],
  },
]);
const workspace = vi.hoisted(() => ({
  // Workspace allows only device1 on host-1.
  isDeviceAllowed: (host: string, deviceId: string) => host === 'host-1' && deviceId === 'device1',
}));
vi.mock('../../frontend/src/hooks/useHostManager', () => ({ useHostData: () => ({ getAllHosts: () => hosts }) }));
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({ useWorkspaceContext: () => workspace }));
vi.mock('../../frontend/src/hooks/auth/useAuth', () => ({ useAuth: () => ({ user: { id: 'user-1' } }) }));

import { ApiError } from '../../frontend/src/hooks/reports/runManagementApi';
import ManualRun from '../../frontend/src/pages/ManualRun';

const step = (ordinal: number, overrides: Partial<ManualStep> = {}): ManualStep => ({
  ordinal,
  label: `Step ${ordinal}`,
  required: true,
  expected: null,
  outcome: null,
  note: null,
  evidence_url: null,
  evidence_missing: true,
  updated_by: null,
  updated_at: null,
  ...overrides,
});

// GET /server/manual-sessions/:id as the server presents it: actor_name is always null.
const session = (overrides: Partial<ManualSession> = {}): ManualSession => ({
  id: 'ms-1',
  status: 'in_progress',
  testcase_id: 'tc-1',
  testcase_name: 'Login flow',
  testcase_version: 3,
  actor_id: 'user-1',
  actor_name: null,
  host_name: 'host-1',
  device_name: 'Living room TV',
  environment: 'prod',
  notes: null,
  optimistic_version: 1,
  started_at: '2026-10-03T09:00:00Z',
  updated_at: '2026-10-03T09:05:00Z',
  finalized_at: null,
  script_result_id: null,
  steps: [step(1), step(2)],
  ...overrides,
});

const renderAt = (path: string) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/test-results/manual" element={<ManualRun />} />
          <Route path="/test-results/manual/:sessionId" element={<ManualRun />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

const renderSession = () => renderAt('/test-results/manual/ms-1');

const lastButton = (name: RegExp) => {
  const buttons = screen.getAllByRole('button', { name });
  return buttons[buttons.length - 1];
};

describe('ManualRun session', () => {
  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
    permissions.canRunManual = true;
  });

  it('shows the actor honestly (no name is resolved) and states missing evidence explicitly', async () => {
    api.fetchManualSession.mockResolvedValue(session());
    renderSession();
    expect(await screen.findByText('Login flow')).toBeInTheDocument();
    expect(screen.getByText('Tester: You')).toBeInTheDocument();
    expect(screen.getByText('host-1 · Living room TV')).toBeInTheDocument();
    expect(api.fetchManualSession).toHaveBeenCalledWith('ms-1', scope);
    expect(screen.getAllByText(/No evidence attached/).length).toBeGreaterThan(0);
  });

  it('keeps Finalize disabled until every REQUIRED step has an outcome', async () => {
    api.fetchManualSession.mockResolvedValue(session());
    renderSession();
    await screen.findByText('Login flow');
    expect(screen.getByRole('button', { name: /^finalize$/i })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Passed' }));
    expect(screen.getByRole('button', { name: /^finalize$/i })).toBeDisabled();
  });

  it('lets an optional step stay without an outcome', async () => {
    api.fetchManualSession.mockResolvedValue(
      session({ steps: [step(1, { outcome: 'passed' }), step(2, { required: false })] }),
    );
    renderSession();
    await screen.findByText('Login flow');
    expect(screen.getByText('Optional')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^finalize$/i })).toBeEnabled();
  });

  it('reloads the session and explains a 409 conflict on save', async () => {
    api.fetchManualSession
      .mockResolvedValueOnce(session())
      .mockResolvedValue(session({ optimistic_version: 2, steps: [step(1, { outcome: 'failed' }), step(2)] }));
    // 409 body: {error, code, current} — the current session is shown without another request.
    api.updateManualSession.mockRejectedValue(
      new ApiError(409, 'version mismatch', {
        error: 'version mismatch',
        code: 'version_conflict',
        current: session({ optimistic_version: 2, steps: [step(1, { outcome: 'failed' }), step(2)] }),
      }),
    );
    renderSession();
    await screen.findByText('Login flow');

    fireEvent.click(screen.getByRole('button', { name: 'Passed' }));
    fireEvent.click(screen.getByRole('button', { name: /save progress/i }));

    expect(await screen.findByTestId('manual-conflict')).toHaveTextContent(/someone else saved this session/i);
    expect(api.updateManualSession).toHaveBeenCalledWith(
      'ms-1',
      expect.objectContaining({ expected_version: 1 }),
      scope,
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'Failed' })).toHaveAttribute('aria-pressed', 'true'));
  });

  it('retries finalize safely after a failure (the server is idempotent per session)', async () => {
    const recorded = session({ steps: [step(1, { outcome: 'passed' }), step(2, { outcome: 'skipped' })] });
    api.fetchManualSession.mockResolvedValue(recorded);
    api.finalizeManualSession
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce({
        session: { ...recorded, status: 'finalized', script_result_id: 'sr-42' },
        script_result_id: 'sr-42',
        idempotent: true,
      });
    renderSession();
    await screen.findByText('Login flow');

    fireEvent.click(screen.getByRole('button', { name: /^finalize$/i }));
    expect(screen.getByText(/2 step\(s\) without evidence/)).toBeInTheDocument();
    fireEvent.click(lastButton(/^finalize$/i));
    expect(await screen.findByText(/finalizing again is safe/i)).toBeInTheDocument();
    expect(api.finalizeManualSession).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /^finalize$/i }));
    fireEvent.click(lastButton(/^finalize$/i));
    expect(await screen.findByTestId('manual-finalized')).toBeInTheDocument();

    expect(api.finalizeManualSession).toHaveBeenCalledTimes(2);
    for (const call of api.finalizeManualSession.mock.calls) {
      expect(call[0]).toBe('ms-1');
      expect(call[1]).toEqual({ expected_version: 1 });
    }
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('link', { name: /open the run summary/i })).toHaveAttribute(
      'href',
      '/test-results/runs/script/sr-42',
    );
  });

  it('loads a finalized session read-only', async () => {
    api.fetchManualSession.mockResolvedValue(
      session({ status: 'finalized', script_result_id: 'sr-1', steps: [step(1, { outcome: 'passed' })] }),
    );
    renderSession();
    await screen.findByTestId('manual-finalized');
    expect(screen.queryByRole('button', { name: /^finalize$/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Passed' })).toBeDisabled();
  });
});

describe('ManualRun start', () => {
  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
    permissions.canRunManual = true;
    api.fetchManualSessions.mockResolvedValue({ items: [] });
    api.fetchTestcases.mockResolvedValue({ success: true, testcases: [{ testcase_id: 'tc-1', testcase_name: 'Login flow' }] });
  });

  it('requires a device of this server in the workspace and sends host + device display name', async () => {
    api.createManualSession.mockResolvedValue({ ...session(), created: true });
    renderAt('/test-results/manual');

    const testcaseInput = await screen.findByLabelText('Test case');
    fireEvent.mouseDown(testcaseInput);
    fireEvent.click(await screen.findByText('Login flow'));
    expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled();

    fireEvent.mouseDown(screen.getByLabelText('Device under test'));
    expect(screen.queryByText('host-1 · Bedroom STB')).not.toBeInTheDocument();
    fireEvent.click(await screen.findByText('host-1 · Living room TV'));
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));

    await waitFor(() => expect(api.createManualSession).toHaveBeenCalledTimes(1));
    expect(api.createManualSession.mock.calls[0][0]).toEqual(
      expect.objectContaining({ testcase_id: 'tc-1', host_name: 'host-1', device_name: 'Living room TV' }),
    );
    expect(api.createManualSession.mock.calls[0][0].idempotency_key).toBeTruthy();
  });
});
