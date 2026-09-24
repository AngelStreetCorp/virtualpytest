import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Monitoring > Analytics.
 *
 * The property worth defending in a test is the PERFORMANCE CONTRACT, because it is
 * invisible and easy to regress: opening the page must fetch exactly one section, and
 * the expensive Devices rollup must not be among them. Everything else — which colour
 * a bar is, how a donut lays out — is better judged by looking at the page.
 */

const sectionCalls: string[] = [];

vi.mock('../../frontend/src/hooks/pages/useAnalytics', () => {
  const payloads: Record<string, unknown> = {
    overview: {
      tiles: {
        hosts_total: 8, hosts_reporting: 8,
        devices_total: 12, devices_up: 11, devices_issue: 1, devices_down: 0,
        incidents_open: 68, alerts_active: 12, pass_rate: 83,
      },
      device_counts: { up: 11, issue: 1, down: 0 },
      incidents_timeline: [{ day: '2026-09-17', critical: 5, high: 8 }],
      incident_severities: ['critical', 'high'],
      kpi_timeline: [{ day: '2026-09-17', passed: 24, failed: 6 }],
      pass_rate: 83,
      total_runs: 2921,
    },
    devices: {
      devices: [
        {
          host_name: 'host-clone-1', device_id: 'device2', device_name: 'Phone slot 1',
          device_model: 'phone_agent', ffmpeg_status: 'active', monitor_status: 'stuck',
          last_seen: '2026-09-17T06:00:00Z', status: 'issue',
        },
      ],
      counts: { up: 11, issue: 1, down: 0 },
      total: 12,
      by_model: [{ name: 'stb', value: 4 }],
      by_host: [{ name: 'vpt-pi1', value: 4 }],
      availability_worst: [{ name: 'Phone slot 1', value: 0 }],
      availability_timeline: [{ day: '2026-09-17', availability_percent: 92 }],
      availability_day: '2026-09-17',
    },
  };

  return {
    useAnalyticsSection: (section: string) => {
      sectionCalls.push(section);
      return {
        data: payloads[section] ?? null,
        loading: false,
        refreshing: false,
        error: null,
        cacheState: 'fresh',
        reload: vi.fn(),
      };
    },
    useProjectMetrics: () => ({ data: null, loading: false, missing: true, error: null }),
    prefetchSection: vi.fn(),
    invalidateAnalytics: vi.fn(),
  };
});

vi.mock('../../frontend/src/hooks/useResponsiveMode', () => ({
  useResponsiveMode: () => ({ isMobile: false }),
}));

import MonitoringAnalytics from '../../frontend/src/pages/MonitoringAnalytics';
import { prefetchSection } from '../../frontend/src/hooks/pages/useAnalytics';

const renderAt = (path = '/monitoring/analytics') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <MonitoringAnalytics />
    </MemoryRouter>,
  );

describe('MonitoringAnalytics page', () => {
  beforeEach(() => {
    sectionCalls.length = 0;
    vi.clearAllMocks();
  });

  it('shows every tab', async () => {
    renderAt();
    for (const label of ['Overview', 'System', 'Devices', 'KPI', 'Incidents', 'Alerts', 'Project']) {
      expect(await screen.findByRole('tab', { name: label })).toBeTruthy();
    }
  });

  it('fetches ONLY the overview section on first paint', async () => {
    renderAt();
    await waitFor(() => expect(sectionCalls.length).toBeGreaterThan(0));

    expect(new Set(sectionCalls)).toEqual(new Set(['overview']));
    // The whole point of the tabbed design: the 1382 ms availability rollup that
    // backs Devices must not load just because someone opened the page.
    expect(sectionCalls).not.toContain('devices');
  });

  it('renders the headline numbers', async () => {
    renderAt();
    expect(await screen.findByText('68')).toBeTruthy(); // open incidents
    expect(await screen.findByText('83%')).toBeTruthy(); // pass rate
    expect(await screen.findByText('11 / 12')).toBeTruthy(); // devices up
  });

  it('opens the section named in the URL, not overview', async () => {
    renderAt('/monitoring/analytics?section=devices');
    await waitFor(() => expect(sectionCalls.length).toBeGreaterThan(0));
    expect(new Set(sectionCalls)).toEqual(new Set(['devices']));
  });

  it('shows "service issue" as its own state, not folded into up or down', async () => {
    // A device that reports in but is not capturing is neither up nor down. The page
    // used to spell that out in a caption under the charts; it is now carried by the
    // fleet-status donut alone, so the count is what has to survive.
    renderAt('/monitoring/analytics?section=devices');
    expect(await screen.findByText('service issue')).toBeTruthy();
    const legend = (await screen.findByText('service issue')).closest('div')?.parentElement;
    expect(legend?.textContent).toContain('1');
  });

  it('prefetches a section on tab hover, before any click', async () => {
    const user = userEvent.setup();
    renderAt();
    await user.hover(await screen.findByRole('tab', { name: 'Incidents' }));
    expect(prefetchSection).toHaveBeenCalledWith('incidents');
  });

  it('does not try to prefetch Project, which has no API section', async () => {
    const user = userEvent.setup();
    renderAt();
    await user.hover(await screen.findByRole('tab', { name: 'Project' }));
    expect(prefetchSection).not.toHaveBeenCalledWith('project');
  });

  it('tells the user when the build-time metrics were never generated', async () => {
    renderAt('/monitoring/analytics?section=project');
    expect(await screen.findAllByText(/Not generated yet/i)).toBeTruthy();
  });
});
