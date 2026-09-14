import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useRequirements', () => ({
  useRequirements: () => ({
    requirements: [],
    isLoading: false,
    error: null,
    getRequirementCoverage: async () => null,
    unlinkTestcase: async () => ({ success: true }),
    coverageCounts: {},
  }),
}));

vi.mock('../../frontend/src/hooks/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    dialogState: {
      open: false,
      title: 'Confirm Action',
      message: '',
      confirmText: 'OK',
      cancelText: 'Cancel',
      confirmColor: 'primary',
      onConfirm: () => {},
    },
    confirm: () => {},
    handleConfirm: () => {},
    handleCancel: () => {},
  }),
}));

import Coverage from '../../frontend/src/pages/Coverage';

describe('Coverage page', () => {
  it('renders the coverage summary strip and empty state', () => {
    render(
      <BrowserRouter>
        <Coverage />
      </BrowserRouter>,
    );

    // No page-level <h1> — the sticky health strip is the stable content.
    expect(screen.getByText('Requirements')).toBeInTheDocument();
    expect(screen.getByText(/No requirements found/i)).toBeInTheDocument();
  });
});
