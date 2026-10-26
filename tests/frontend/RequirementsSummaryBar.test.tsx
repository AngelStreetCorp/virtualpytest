// @vitest-environment jsdom
/**
 * The Requirements summary bar keeps its stats on a phone (BUG-0818).
 *
 * The bar was a single non-wrapping row: on a 390 px phone it read
 * "RequirementsTotal 131 | Active 131 | No coverag…" and the P1/P2/P3 chips were gone. The bar
 * and the stats group now wrap, so every stat is still on screen.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

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

describe('the Requirements summary bar (BUG-0818)', () => {
  it('wraps the bar and its stats instead of running them off the screen', () => {
    render(
      <BrowserRouter>
        <Requirements />
      </BrowserRouter>,
    );

    const bar = screen.getByTestId('requirements-summary-bar');
    const stats = screen.getByTestId('requirements-summary-stats');

    expect(window.getComputedStyle(bar).flexWrap).toBe('wrap');
    expect(window.getComputedStyle(stats).flexWrap).toBe('wrap');
  });

  it('keeps every stat in the bar', () => {
    render(
      <BrowserRouter>
        <Requirements />
      </BrowserRouter>,
    );

    const stats = screen.getByTestId('requirements-summary-stats');
    const text = (stats.textContent ?? '').replace(/\s+/g, ' ');
    expect(text).toContain('Total');
    expect(text).toContain('Active');
    expect(text).toContain('No coverage');
    expect(text).toContain('P1:');
    expect(text).toContain('P2:');
    expect(text).toContain('P3:');
  });
});
