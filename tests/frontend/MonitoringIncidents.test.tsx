import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/components/heatmap/HeatMapFreezeModal', () => ({
  HeatMapFreezeModal: () => null,
}));

vi.mock('../../frontend/src/components/common/R2Image', () => ({
  R2Image: () => <div data-testid="r2-image" />,
}));

// Functions must be created once at module-mock-factory time (not per hook
// call) so `loadAlerts`'s useCallback([getAllAlerts]) dependency stays
// referentially stable across renders — otherwise the page's load-on-mount
// effect re-fires every render and never settles out of the loading state.
const alertsState = vi.hoisted(() => ({ pending: false }));

vi.mock('../../frontend/src/hooks/pages/useAlerts', () => {
  // A never-settling getAllAlerts holds the page in its loading state, without changing the
  // function's identity — the load-on-mount effect depends on it and must stay referentially
  // stable or it re-fires for ever (see the note above).
  const getAllAlerts = async () => (alertsState.pending ? new Promise(() => {}) : []);
  const updateCheckedStatus = vi.fn();
  const updateDiscardStatus = vi.fn();
  const deleteAllAlerts = vi.fn(async () => ({ success: true, deleted_count: 0 }));
  const deleteAlert = vi.fn();
  const getTriageStats = async () => ({ success: false });
  return {
    useAlerts: () => ({
      getAllAlerts,
      updateCheckedStatus,
      updateDiscardStatus,
      deleteAllAlerts,
      deleteAlert,
      getTriageStats,
    }),
  };
});

import MonitoringIncidents from '../../frontend/src/pages/MonitoringIncidents';

describe('MonitoringIncidents page — first load', () => {
  it('draws placeholder rows in both tables instead of one spinner row spanning them', async () => {
    alertsState.pending = true;
    try {
      const { container } = render(
        <BrowserRouter>
          <MonitoringIncidents />
        </BrowserRouter>,
      );

      // Both tables keep their real headers, so the arriving rows line up.
      ['Incident', 'Host', 'Device', 'Start', 'Duration'].forEach((h) => {
        expect(screen.getAllByRole('columnheader', { name: h }).length).toBeGreaterThan(0);
      });
      // Active is 7 columns, Closed 8 — 7 placeholder rows each.
      expect(container.querySelectorAll('tbody tr').length).toBeGreaterThanOrEqual(14);
      expect(container.querySelectorAll('.MuiSkeleton-root').length).toBeGreaterThan(50);
      expect(container.querySelectorAll('.MuiCircularProgress-root')).toHaveLength(0);
      // The empty states must not flash while the data is in flight.
      expect(screen.queryByText('No active alerts')).not.toBeInTheDocument();
      expect(screen.queryByText('No closed alerts')).not.toBeInTheDocument();
      // Nor may the stat tiles claim "0 active alerts" / "N/A most common" before looking.
      // 'Closed' also names a section heading, so only its presence is asserted.
      ['Active alerts', 'This week', 'Most common'].forEach((l) => {
        expect(screen.getByText(l)).toBeInTheDocument();
      });
      expect(screen.getAllByText('Closed').length).toBeGreaterThan(0);
      expect(screen.queryByText('N/A')).not.toBeInTheDocument();
    } finally {
      alertsState.pending = false;
    }
  });
});

describe('MonitoringIncidents page', () => {
  it('renders alerts heading and empty state sections', async () => {
    render(
      <BrowserRouter>
        <MonitoringIncidents />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Alerts' })).toBeInTheDocument();
    expect(await screen.findByText('No active alerts')).toBeInTheDocument();
    expect(screen.getByText('No closed alerts')).toBeInTheDocument();
  });
});
