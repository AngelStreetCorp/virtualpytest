import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ runs: [], runners: [] }),
    }),
  );
});

import CICDReports from '../../features/cicd/frontend/CICDReportsPage';

describe('CICDReports page', () => {
  it('renders the CI/CD Reports heading', async () => {
    render(<CICDReports />);

    expect(await screen.findByRole('heading', { name: 'CI/CD Reports' })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/No reports yet/i)).toBeInTheDocument();
    });
  });
});
