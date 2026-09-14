import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({
    serverHostsData: [],
  }),
}));

vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({
    showSuccess: () => {},
    showError: () => {},
    showWarning: () => {},
    showInfo: () => {},
  }),
  default: () => ({
    showSuccess: () => {},
    showError: () => {},
    showWarning: () => {},
    showInfo: () => {},
  }),
}));

import RunCommand from '../../frontend/src/pages/RunCommand';

describe('RunCommand page', () => {
  it('renders the Run Command heading', () => {
    render(
      <BrowserRouter>
        <RunCommand />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Run Command on Hosts' })).toBeInTheDocument();
  });
});
