// @vitest-environment jsdom
/**
 * The Interface table keeps whole names on a phone (BUG-0819).
 *
 * The table is a fixed layout in percentage widths inside a ~358 px box, so the name column
 * ended up a few characters wide: identifiers broke mid-word ("stb_android_mobil" / "e") and
 * one cell was clipped to 8 px. The table now asks for a minimum width and the container
 * scrolls sideways instead of cutting the table.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const rows = vi.hoisted(() => [] as unknown[]);

vi.mock('../../frontend/src/hooks/userinterface/useUserInterfaceVariants', () => ({
  primeAllVariants: async () => {},
  useUserInterfaceVariants: () => ({
    variants: [],
    loading: false,
    error: null,
    refresh: async () => {},
    refetch: async () => {},
    addVariant: async () => ({ success: true }),
    updateVariant: async () => ({ success: true }),
    updateVariantOverrides: async () => ({ success: true }),
    deleteVariant: async () => ({ success: true }),
    renameVariant: async () => ({ success: true }),
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useUserInterface', () => ({
  useUserInterface: () => ({
    getAllUserInterfaces: async () => rows,
    updateUserInterfaceWithValidation: async () => ({}),
    deleteUserInterface: async () => {},
    createUserInterfaceWithValidation: async () => ({}),
    duplicateUserInterface: async () => ({}),
    publishUserInterface: async () => ({}),
    exportUserInterface: async () => {},
    importUserInterface: async () => ({}),
  }),
}));

vi.mock('../../frontend/src/hooks/pages/useDeviceModels', () => ({
  useDeviceModels: () => ({
    models: [],
    isLoading: false,
    error: null,
    refetch: () => {},
    createModel: async () => {},
    updateModel: async () => {},
    deleteModel: async () => {},
    isCreating: false,
    isUpdating: false,
    isDeleting: false,
    createError: null,
    updateError: null,
    deleteError: null,
  }),
}));

vi.mock('../../frontend/src/hooks/useResponsiveMode', () => ({
  useResponsiveMode: () => ({ isMobile: true, isTablet: false, mode: 'mobile' }),
}));

import UserInterface from '../../frontend/src/pages/UserInterface';

describe('the Interface table on a phone (BUG-0819)', () => {
  it('asks for a minimum width and scrolls sideways instead of clipping', async () => {
    rows.push({
      id: 'u1',
      name: 'stb_android_mobile_test',
      models: ['android_tv'],
      mode: 'dev',
      min_version: null,
      max_version: null,
    });

    render(
      <BrowserRouter>
        <UserInterface />
      </BrowserRouter>,
    );

    const table = (await screen.findByRole('table')) as HTMLTableElement;
    const minWidth = parseInt(window.getComputedStyle(table).minWidth, 10);
    expect(minWidth).toBeGreaterThanOrEqual(480);

    const container = table.closest('.MuiTableContainer-root') as HTMLElement;
    expect(container).toBeTruthy();
    expect(window.getComputedStyle(container).overflowX).toBe('auto');
  });
});
