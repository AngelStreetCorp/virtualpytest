import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// JiraIntegration fetches instances directly via global fetch (no data hook) —
// stub fetch so the component mounts without hitting the network.
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, instances: [] }),
    }),
  );
});

import JiraIntegration from '../../frontend/src/pages/JiraIntegration';

describe('JiraIntegration page', () => {
  it('renders the JIRA Integration heading and empty state', async () => {
    render(
      <BrowserRouter>
        <JiraIntegration />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'JIRA Integration' })).toBeInTheDocument();
    expect(await screen.findByText('No JIRA instances configured')).toBeInTheDocument();
  });
});
