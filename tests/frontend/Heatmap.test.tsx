import { render, screen } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/contexts/HostManagerProvider', () => ({
  HostManagerProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../frontend/src/contexts/device/DeviceDataContext', () => ({
  DeviceDataProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../frontend/src/components/MosaicPlayer', () => ({
  MosaicPlayer: () => <div data-testid="mosaic-player">Mosaic Player</div>,
}));

vi.mock('../../frontend/src/components/heatmap/HeatMapAnalysisSection', () => ({
  HeatMapAnalysisSection: () => <h2>Data Analysis</h2>,
}));

vi.mock('../../frontend/src/components/heatmap/HeatMapHistory', async () => {
  const ReactImport = await import('react');

  return {
    HeatMapHistory: ReactImport.forwardRef(function HeatMapHistoryMock() {
      return <h2>Heatmap History</h2>;
    }),
  };
});

vi.mock('../../frontend/src/components/rec/RecHostStreamModal', () => ({
  RecHostStreamModal: () => null,
}));

vi.mock('../../frontend/src/hooks/useResponsiveMode', () => ({
  useResponsiveMode: () => ({
    mode: 'desktop',
    isMobile: false,
    isTablet: false,
    isDesktop: true,
    theme: {},
  }),
}));

vi.mock('../../frontend/src/hooks/useHostManager', () => ({
  useHostData: () => ({
    getHostByName: () => null,
    getDevicesFromHost: () => [],
  }),
}));

// Mutable so a test can put the hook in the "this minute has no frame" state.
const heatmapState = { hasDataError: false };

vi.mock('../../frontend/src/hooks/useHeatmap', () => ({
  useHeatmap: () => ({
    timeline: [
      {
        timeKey: 'frame_1',
        displayTime: new Date('2026-02-26T10:00:00Z'),
        isToday: true,
      },
    ],
    currentIndex: 0,
    setCurrentIndex: () => {},
    analysisData: {
      hosts_count: 1,
      devices: [
        {
          host_name: 'host-1',
          device_id: 'device-1',
          analysis_json: { status: 'ok' },
        },
      ],
    },
    hasIncidents: () => false,
    goToLatest: () => {},
    loadedItem: null,
    hasDataError: heatmapState.hasDataError,
    generateReport: async () => {},
    getMosaicUrl: () => 'https://example.com/mosaic.jpg',
    getFilteredDevices: (devices: any[]) => devices,
  }),
}));

import Heatmap from '../../frontend/src/pages/Heatmap';

describe('Heatmap page', () => {
  beforeEach(() => {
    heatmapState.hasDataError = false;
  });

  it('renders timeline sections', () => {
    render(<Heatmap />);

    expect(screen.getByText('24h Heatmap')).toBeInTheDocument();
    expect(screen.getByText('Data Analysis')).toBeInTheDocument();
    expect(screen.getByText('Heatmap History')).toBeInTheDocument();
    expect(screen.getByTestId('mosaic-player')).toBeInTheDocument();
    expect(screen.queryByText(/No heatmap was generated/)).not.toBeInTheDocument();
  });

  // A minute the processor skipped still holds the previous day's frame in the HHMM
  // circular buffer; the page must say so instead of passing it off as this minute's.
  it('reports a missing frame for the selected minute', () => {
    heatmapState.hasDataError = true;

    render(<Heatmap />);

    expect(screen.getByText(/No heatmap was generated/)).toBeInTheDocument();
  });
});
