/**
 * Run Management: one page, six tabs (groups, milestones, labels, defects, custom reports,
 * manual runs). The tab is in the URL, each tab opens with a help line, the old list URLs
 * redirect to their tab (keeping their query), and manual runs need their own permission.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const perms = vi.hoisted(() => ({ canRunManual: true }));

vi.mock('../../frontend/src/hooks/reports/useRunManagement', () => ({
  useReportPermissions: () => perms,
}));
vi.mock('../../frontend/src/pages/RunGroups', () => ({ default: () => <div>groups-body</div> }));
vi.mock('../../frontend/src/pages/Milestones', () => ({ default: () => <div>milestones-body</div> }));
vi.mock('../../frontend/src/pages/RunLabels', () => ({ default: () => <div>labels-body</div> }));
vi.mock('../../frontend/src/pages/Defects', () => ({ default: () => <div>defects-body</div> }));
vi.mock('../../frontend/src/pages/CustomReportBuilder', () => ({ default: () => <div>custom-body</div> }));
vi.mock('../../frontend/src/pages/ManualRun', () => ({ default: () => <div>manual-body</div> }));

import { RunManagementTabRedirect } from '../../frontend/src/components/reports/TabRedirects';
import RunManagement from '../../frontend/src/pages/RunManagement';

const LocationProbe: React.FC = () => {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
};

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/test-results/run-management" element={<RunManagement />} />
        <Route path="/test-results/labels" element={<RunManagementTabRedirect tab="labels" />} />
        <Route path="/test-results/defects" element={<RunManagementTabRedirect tab="defects" />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );

beforeEach(() => {
  perms.canRunManual = true;
});

describe('RunManagement', () => {
  it('opens on Groups with its help line', () => {
    renderAt('/test-results/run-management');
    expect(screen.getByRole('heading', { name: 'Run Management' })).toBeInTheDocument();
    expect(screen.getByText('groups-body')).toBeInTheDocument();
    expect(screen.getByTestId('run-management-help')).toHaveTextContent(
      'A folder of finished runs showing the latest result per test, with Rerun failures.',
    );
  });

  it('reads the tab from the URL and writes it back on a switch', () => {
    renderAt('/test-results/run-management?tab=milestones');
    expect(screen.getByText('milestones-body')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('run-management-tab-custom-reports'));
    expect(screen.getByText('custom-body')).toBeInTheDocument();
    expect(screen.getByTestId('run-management-help')).toHaveTextContent('Saved Test Reports filters');
    expect(screen.getByTestId('location')).toHaveTextContent('/test-results/run-management?tab=custom-reports');
  });

  it('offers six tabs, and hides Manual runs without the permission', () => {
    const { unmount } = renderAt('/test-results/run-management');
    expect(screen.getAllByRole('button', { pressed: false }).length + 1).toBe(6);
    unmount();
    perms.canRunManual = false;
    renderAt('/test-results/run-management?tab=manual');
    expect(screen.queryByTestId('run-management-tab-manual')).not.toBeInTheDocument();
    expect(screen.getByText('groups-body')).toBeInTheDocument();
  });

  it('redirects an old list URL to its tab, keeping the query', () => {
    renderAt('/test-results/defects?status=open');
    expect(screen.getByText('defects-body')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/test-results/run-management?status=open&tab=defects');
  });
});
