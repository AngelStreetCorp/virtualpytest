import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchPublicShare: vi.fn() }));

vi.mock('../../frontend/src/hooks/reports/runManagementApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../frontend/src/hooks/reports/runManagementApi')>();
  return { ...actual, ...api };
});
vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({ showError: vi.fn(), showWarning: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn() }),
}));

import { ApiError } from '../../frontend/src/hooks/reports/runManagementApi';
import ShareRun from '../../frontend/src/pages/ShareRun';

const renderAt = (hash: string) => {
  window.history.replaceState(null, '', `/share/run/snap-1${hash}`);
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/share/run/snap-1']}>
        <Routes>
          <Route path="/share/run/:snapshotId" element={<ShareRun />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

// Stored payload shape (schema_version, kind, rows with started_at/environment, …) plus keys a
// server regression could leak; only the allowlisted fields may render.
const payloadWithLeaks = {
  schema_version: 1,
  kind: 'campaign',
  generated_at: '2026-10-03T08:00:00Z',
  rows_truncated: false,
  title: 'Nightly campaign',
  status: 'failed',
  counts: { total: 33, passed: 17, failed: 4, skipped: 12, running: 0, pending: 0, cancelled: 0, unknown: 0 },
  durations: { started_at: '2026-10-02T22:00:00Z', completed_at: '2026-10-02T23:00:00Z', execution_time_ms: 3600000 },
  safe_labels: ['release-1.4'],
  rows: [
    { name: 'zap_channel', status: 'passed', execution_time_ms: 61000, host_name: 'secret-host-17', logs_url: 'https://r2.example/logs' },
    { name: 'boot_check', status: 'failed', execution_time_ms: 5000, started_at: '2026-10-02T22:10:00Z', environment: 'prod' },
  ],
  host_name: 'secret-host-17',
  logs_url: 'https://r2.example/private-logs',
  metadata: { api_key: 'sk-leaked' },
};

beforeEach(() => {
  api.fetchPublicShare.mockReset();
});

describe('ShareRun (anonymous)', () => {
  it('reads the token from the fragment, strips it, and renders only allowlisted fields', async () => {
    api.fetchPublicShare.mockResolvedValue({
      snapshot: {
        id: 'snap-1',
        run_kind: 'campaign',
        created_at: '2026-10-03T08:00:00Z',
        expires_at: '2026-10-10T08:00:00Z',
        payload: payloadWithLeaks,
      },
    });
    renderAt('#t=secret-token');

    expect(await screen.findByTestId('share-title')).toHaveTextContent('Nightly campaign');
    expect(api.fetchPublicShare).toHaveBeenCalledWith('snap-1', 'secret-token');
    expect(window.location.hash).toBe('');
    expect(window.location.search).not.toContain('secret-token');

    expect(screen.getByTestId('count-total')).toHaveTextContent('33');
    expect(screen.getByTestId('count-failed')).toHaveTextContent('4');
    expect(screen.getByTestId('count-skipped')).toHaveTextContent('12');
    expect(screen.getByTestId('count-passed')).toHaveTextContent('17');
    expect(screen.getByTestId('count-unknown')).toHaveTextContent('0');
    expect(screen.getAllByTestId('share-row')).toHaveLength(2);
    expect(screen.getByText('release-1.4')).toBeInTheDocument();
    expect(screen.getByText(/later changes are not shown/)).toBeInTheDocument();

    const text = document.body.textContent ?? '';
    expect(text).not.toContain('secret-host-17');
    expect(text).not.toContain('r2.example');
    expect(text).not.toContain('sk-leaked');
    // No links back into the app for an anonymous visitor.
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });

  it.each([404, 410, 401, 403])('shows one invalid/expired/revoked message for HTTP %i', async (status) => {
    api.fetchPublicShare.mockRejectedValue(new ApiError(status, 'nope', { error: 'nope' }));
    renderAt('#t=some-token');
    expect(await screen.findByTestId('share-invalid')).toHaveTextContent(
      'This link is invalid, expired or revoked.',
    );
  });

  it('says the link is incomplete when the fragment carries no token', () => {
    renderAt('');
    expect(screen.getByTestId('share-incomplete')).toHaveTextContent('This link is incomplete');
    expect(api.fetchPublicShare).not.toHaveBeenCalled();
  });
});
