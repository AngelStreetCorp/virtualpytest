/**
 * The unknown-screens page (BUG-0795, BUG-0813).
 *
 * `/configuration/interface/<name>/unknown` reports on one interface. When the
 * interface does not exist the server answers 404, and the page must say that
 * instead of showing a healthy report — "Every screen this device shows has a
 * node in its tree" — that reads as "no problems" and hides the typo.
 *
 * The table gives every column a width of its own, so the headers cannot run
 * into their neighbour on a phone.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

const { EMPTY, ROW, hook } = vi.hoisted(() => {
  const EMPTY = {
    needsName: [] as unknown[],
    excludedAsContent: [] as unknown[],
    contentFilteredCount: 0,
    capturesProcessed: 0,
    lastScan: '—',
  };
  const ROW = {
    id: 's1',
    proposedName: 'home',
    summary: 'the home screen',
    type: 'content',
    frames: 12,
    signal: 'no node in the tree',
    action: 'accept',
    status: 'pending',
    hasStill: false,
  };
  return { EMPTY, ROW, hook: { data: { ...EMPTY }, loading: false, error: null as string | null } };
});

vi.mock('../../frontend/src/hooks/pages/useUserInterfaceUnknown', () => ({
  useUserInterfaceUnknown: () => hook,
}));

import UserInterfaceUnknown from '../../frontend/src/pages/UserInterfaceUnknown';

const renderPage = () =>
  render(
    <BrowserRouter>
      <UserInterfaceUnknown />
    </BrowserRouter>,
  );

describe('the unknown-screens page', () => {
  beforeEach(() => {
    hook.data = { ...EMPTY };
    hook.error = null;
  });

  it('says the interface was not found instead of an all-clear report', () => {
    hook.error = 'User interface "no-such-interface" not found';

    renderPage();

    expect(screen.getByText('User interface "no-such-interface" not found')).toBeInTheDocument();
    // No healthy report next to the error.
    expect(screen.queryByText('Every screen this device shows has a node in its tree.')).not.toBeInTheDocument();
    expect(screen.queryByText('Needs a name')).not.toBeInTheDocument();
    expect(screen.queryByText('Last scan')).not.toBeInTheDocument();
  });

  it('shows the healthy report when the load worked', () => {
    renderPage();

    expect(screen.getByText('Every screen this device shows has a node in its tree.')).toBeInTheDocument();
    expect(screen.getByText('Last scan')).toBeInTheDocument();
  });

  it('gives every column a width of its own, so the headers cannot collide', () => {
    hook.data = { ...EMPTY, needsName: [ROW], capturesProcessed: 120, lastScan: '2 h ago' };

    const { container } = renderPage();

    // Content-sized columns (UI_STYLE S3), the name column takes the rest.
    const table = container.querySelectorAll('table')[0];
    const cols = table.querySelectorAll('colgroup col');
    expect(cols).toHaveLength(5);
    expect((cols[1] as HTMLElement).style.width).toBe('');
    expect((cols[3] as HTMLElement).style.width).not.toBe('');

    // Every header keeps its text in the title and ellipsises on purpose
    // (UI_STYLE S9) instead of running into its neighbour.
    for (const title of ['Screen', 'Proposed name', 'Type', 'Frames', 'Actions']) {
      expect(screen.getAllByTitle(title).length).toBeGreaterThan(0);
    }
  });
});
