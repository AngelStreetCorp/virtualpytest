import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useDeviceModels', () => ({
  useDeviceModels: () => ({
    models: [],
    isLoading: false,
    error: null,
    createModel: vi.fn(),
    deleteModel: vi.fn(),
    isCreating: false,
    isDeleting: false,
  }),
}));

import Models from '../../frontend/src/pages/Models';

describe('Models page', () => {
  it('renders device models heading', () => {
    render(
      <BrowserRouter>
        <Models />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Device Models' })).toBeInTheDocument();
    expect(screen.getByText('No Models Found')).toBeInTheDocument();
  });
});
