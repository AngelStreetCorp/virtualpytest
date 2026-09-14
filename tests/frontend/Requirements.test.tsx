import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/pages/useRequirements', () => ({
  useRequirements: () => ({
    requirements: [],
    isLoading: false,
    error: null,
    createRequirement: async () => ({ success: true }),
    updateRequirement: async () => ({ success: true }),
    deleteRequirement: async () => ({ success: true }),
    getRequirement: async () => null,
    getRequirementByCode: async () => null,
    filters: {},
    setFilters: () => {},
    categories: [],
    priorities: ['P1', 'P2', 'P3'],
    appTypes: ['all'],
    deviceModels: ['all'],
    refreshRequirements: () => {},
    getRequirementCoverage: async () => null,
    getAvailableTestcases: async () => [],
    linkMultipleTestcases: async () => ({ success: true }),
    unlinkTestcase: async () => ({ success: true }),
    coverageCounts: {},
  }),
}));

import Requirements from '../../frontend/src/pages/Requirements';

describe('Requirements page', () => {
  it('renders the Requirements heading', () => {
    render(
      <BrowserRouter>
        <Requirements />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Requirements' })).toBeInTheDocument();
  });
});
