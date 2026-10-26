// @vitest-environment jsdom
/**
 * The Activity audit table fits a phone (BUG-0817).
 *
 * Every cell of the Logs page inherits `white-space: nowrap`, which made the activity table
 * 974 px wide inside a 324 px phone box: only "When" and a word of "Event" were visible, and
 * Target, Details and Actor were off screen. The activity table lets its cells wrap, and the
 * target breaks inside a long path.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

const apiClient = vi.hoisted(() => vi.fn());

vi.mock('../../frontend/src/utils/apiClient', () => ({ apiClient }));
vi.mock('../../frontend/src/hooks/useServerManager', () => ({
  useServerManager: () => ({ serverHostsData: [], selectedServer: 'server-a' }),
}));

import Logs from '../../frontend/src/pages/Logs';

const activityRows = [
  {
    at: '2026-10-22T10:00:00Z',
    event: 'deploy.started',
    tone: 'running',
    target: 'device/labox-1/interface/stb_tv',
    details: 'A long detail that explains what the activity did',
    actor: 'agent-runner',
    source: 'vpt-server',
  },
];

describe('the Activity audit table on a phone (BUG-0817)', () => {
  it('lets the cells wrap, so the table is not pushed off the screen', async () => {
    apiClient.mockImplementation(async (url: string) => {
      if (String(url).includes('/server/activity')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ rows: activityRows, counts: {}, actors: [], skipped_sources: [] }),
        };
      }
      return { ok: true, status: 200, json: async () => ({ events: [], logs: '' }) };
    });

    render(<Logs />);

    // The Activity tab is the last one (MCP, API, ASK AI, Server, Host, Activity).
    fireEvent.click(screen.getByRole('tab', { name: 'Activity' }));

    const cell = (await screen.findByText('agent-runner')) as HTMLElement;
    expect(window.getComputedStyle(cell).whiteSpace).toBe('normal');

    const target = screen.getByText('device/labox-1/interface/stb_tv') as HTMLElement;
    expect(window.getComputedStyle(target).overflowWrap).toBe('anywhere');

    // The table fills its box instead of sizing itself to the longest cell.
    const table = cell.closest('table') as HTMLTableElement;
    const tableStyle = window.getComputedStyle(table);
    expect(tableStyle.width).not.toBe('auto');
    expect(tableStyle.tableLayout).toBe('fixed');
  });
});
