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
vi.mock('../../frontend/src/hooks/pages/useAlerts', () => {
  const getAllAlerts = async () => [];
  const updateCheckedStatus = vi.fn();
  const updateDiscardStatus = vi.fn();
  const deleteAllAlerts = vi.fn(async () => ({ success: true, deleted_count: 0 }));
  return {
    useAlerts: () => ({
      getAllAlerts,
      updateCheckedStatus,
      updateDiscardStatus,
      deleteAllAlerts,
    }),
  };
});

import MonitoringIncidents from '../../frontend/src/pages/MonitoringIncidents';

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
