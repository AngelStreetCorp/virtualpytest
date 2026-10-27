// @vitest-environment jsdom
/**
 * The Unknown screens table keeps its headers apart on a phone (BUG-0813).
 *
 * The table is a fixed layout in percentage widths: on a 390 px phone "Screen" overflowed its
 * 34 px cell by 6 px and "Frames" its 27 px cell by 16 px, so the two headers ran into each
 * other. A minimum width gives every column room, and the container scrolls sideways.
 */
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/hooks/pages/useUserInterfaceUnknown', () => ({
  useUserInterfaceUnknown: () => ({
    data: {
      needsName: [
        {
          id: 's1',
          proposedName: 'home_screen',
          summary: 'A screen with no node',
          type: 'nav_row',
          frames: 12,
          signal: 'New cluster',
          action: 'accept',
          status: 'pending',
          hasStill: false,
        },
      ],
      excludedAsContent: [],
      contentFilteredCount: 0,
      capturesProcessed: 42,
      lastScan: '2 minutes ago',
    },
    loading: false,
    error: null,
    refetch: async () => {},
    acceptScreen: async () => {},
    dismissScreen: async () => {},
    pendingAction: null,
  }),
}));

import UserInterfaceUnknown from '../../frontend/src/pages/UserInterfaceUnknown';

describe('the Unknown screens table on a phone (BUG-0813)', () => {
  it('gives the table a minimum width and scrolls the container sideways', async () => {
    render(
      <MemoryRouter initialEntries={['/configuration/interface/stb-testop/unknown']}>
        <Routes>
          <Route path="/configuration/interface/:name/unknown" element={<UserInterfaceUnknown />} />
        </Routes>
      </MemoryRouter>,
    );

    const tables = await screen.findAllByRole('table');
    // The first table is the "Needs a name" one; the second lists the filtered-out content.
    const table = tables[0] as HTMLTableElement;
    const minWidth = parseInt(window.getComputedStyle(table).minWidth, 10);
    expect(minWidth).toBeGreaterThanOrEqual(480);

    const container = table.closest('.MuiTableContainer-root') as HTMLElement;
    expect(container).toBeTruthy();
    expect(window.getComputedStyle(container).overflowX).toBe('auto');
  });

  it('still shows every header', async () => {
    render(
      <MemoryRouter initialEntries={['/configuration/interface/stb-testop/unknown']}>
        <Routes>
          <Route path="/configuration/interface/:name/unknown" element={<UserInterfaceUnknown />} />
        </Routes>
      </MemoryRouter>,
    );

    const tables = await screen.findAllByRole('table');
    const headers = within(tables[0] as HTMLElement)
      .getAllByRole('columnheader')
      .map((cell) => (cell.textContent ?? '').trim());
    expect(headers).toEqual(['Screen', 'Proposed name', 'Type', 'Frames', 'Actions']);
  });
});
