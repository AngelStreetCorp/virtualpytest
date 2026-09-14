import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useExecutionResults', () => ({
  useExecutionResults: () => ({
    getAllExecutionResults: async () => [],
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => ({
  useUserInterface: () => ({
    getAllUserInterfaces: async () => [],
  }),
}));

vi.mock('../../frontend/src/hooks/navigation/useMetrics', () => ({
  useMetrics: () => ({
    getNodeMetrics: () => null,
    getEdgeMetrics: () => null,
    getEdgeDirectionMetrics: () => null,
    fetchMetrics: async () => {},
  }),
}));

import ModelReports from '../../frontend/src/pages/ModelReports';

describe('ModelReports page', () => {
  it('renders the heading and prompts for a user interface selection', async () => {
    render(
      <BrowserRouter>
        <ModelReports />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Model Analysis Reports' })).toBeInTheDocument();
    expect(await screen.findByText('Select User Interface to Analyze')).toBeInTheDocument();
  });
});
