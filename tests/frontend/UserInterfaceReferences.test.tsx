import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useUserInterfaceReferences', () => ({
  useUserInterfaceReferences: () => ({
    references: [],
    loading: false,
    error: null,
    refetch: () => {},
  }),
}));

vi.mock('../../frontend/src/components/verification/ReferenceHistoryModal', () => ({
  ReferenceHistoryModal: () => null,
}));

vi.mock('../../frontend/src/components/verification/ReferenceImagePreview', () => ({
  ReferenceImagePreview: () => null,
}));

import UserInterfaceReferencesPage from '../../frontend/src/pages/UserInterfaceReferences';

describe('UserInterfaceReferences page', () => {
  it('renders the references heading and empty state', () => {
    render(
      <BrowserRouter>
        <UserInterfaceReferencesPage />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: /References/i, level: 4 })).toBeInTheDocument();
    expect(screen.getByText('No references for this interface')).toBeInTheDocument();
  });
});
