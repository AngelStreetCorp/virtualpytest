import { render, screen } from '@testing-library/react';
import { afterEach } from 'vitest';

const hookState = vi.hoisted(() => ({ loading: false }));
afterEach(() => { hookState.loading = false; });
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

// The models list is held empty on purpose: the loading branch must still draw the table's real
// header and placeholder rows rather than a spinner, and the header is the assertion that the
// skeleton shares the live geometry.
vi.mock('../../frontend/src/hooks/pages/useDeviceModels', () => ({
  useDeviceModels: () => ({
    models: [],
    supportedModels: [],
    isLoading: hookState.loading,
    error: null,
    createModel: vi.fn(),
    deleteModel: vi.fn(),
    isCreating: false,
    isDeleting: false,
  }),
}));

import Models from '../../frontend/src/pages/Models';

describe('Models page — first load', () => {
  it('draws the table header and placeholder rows instead of a centred spinner', () => {
    hookState.loading = true;

    const { container } = render(
      <BrowserRouter>
        <Models />
      </BrowserRouter>,
    );

    // The live table's header stays mounted, so the arriving rows line up with it.
    ['Name', 'Types', 'Version', 'Description', 'Default', 'Actions'].forEach((h) => {
      expect(screen.getByRole('columnheader', { name: h })).toBeInTheDocument();
    });
    // Placeholder rows, no spinner, and none of the empty-state wording.
    expect(container.querySelectorAll('.MuiSkeleton-root').length).toBeGreaterThan(10);
    expect(container.querySelectorAll('.MuiCircularProgress-root')).toHaveLength(0);
    expect(screen.queryByText('No Models Found')).not.toBeInTheDocument();
  });
});

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
