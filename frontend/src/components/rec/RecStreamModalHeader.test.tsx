// @vitest-environment jsdom
/**
 * tv_lite toolbar behavior — when a device's monitor is off (its profile
 * is tv_lite / no monitor), three controls in the stream modal header stop
 * being useful: Timeline (no 24h thumbnail stream to grid), AVQ feature link
 * (its cards read monitor-derived analysis), and the Ask-AI button (no
 * recent-frame context for the LLM). The "Source" item in the Actions menu
 * is the shortcut the operator gets in exchange: it opens the current
 * stream URL in a new tab, which is the question they want to answer first
 * when a stream freezes ("is the upstream itself down?").
 */
import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

import { RecStreamModalHeader } from './RecStreamModalHeader';
import { HostDataContext } from '../../contexts/HostDataContext';
import { HostControlContext } from '../../contexts/HostControlContext';
import type { HostDataContextType } from '../../contexts/HostDataContext';
import type { HostControlContextType } from '../../contexts/HostControlContext';

const TV_LITE_MONITORING_OFF_TITLE =
  'Monitoring is off for this device (profile tv_lite): stream and control only';

const mockApiGet = vi.fn();

vi.mock('../../utils/apiClient', () => ({
  api: {
    get: (...args: unknown[]) => mockApiGet(...args),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

const fakeHostData: HostDataContextType = {
  selectedServer: 'http://localhost:5109',
  availableServers: ['http://localhost:5109'],
  setSelectedServer: () => {},
  availableHosts: [],
  getHostByName: () => null,
  isLoading: false,
  error: null,
  getAllHosts: () => [],
  getHostsByModel: () => [],
  getAllDevices: () => [],
  getDevicesFromHost: () => [],
  getDevicesByCapability: () => [],
};

const fakeHostControl = {} as HostControlContextType;

const baseHost = {
  host_name: 'vpt-nipogi',
  status: 'online',
  host_url: 'http://vpt-nipogi:6109',
  // monitoring_off is the device_id list the host reports; tv_lite devices land here.
  system_stats: {
    monitoring_off: ['device1'],
    archive_video: true,
    service_health: { services: [] },
  },
  // fields the header does not read but the type still wants
  devices: [],
  host_info: {},
  tags: [],
} as any;

const tvDevice = {
  device_id: 'device1',
  device_model: 'rtsp_video',
  device_name: 'FR News 1 — France 24 (1080p)',
  device_info: {},
  gateway_info: {},
  video_capture_path: '/var/www/html/stream/capture1',
  preferred_userinterface: 'tv',
  preferred_variant: null,
} as any;

const renderHeader = (props: Record<string, unknown> = {}) =>
  render(
    <MemoryRouter>
      <HostDataContext.Provider value={fakeHostData}>
        <HostControlContext.Provider value={fakeHostControl}>
          <RecStreamModalHeader
            host={baseHost}
            device={tvDevice}
            monitoringMode={false}
            restartMode={false}
            isLiveMode
            currentQuality="low"
            streamTransport="hls"
            isMuted={false}
            isControlActive
            isControlLoading={false}
            showWeb={false}
            isDesktopDevice={false}
            hasPowerControl={false}
            canTakeControl
            onScreenshot={() => {}}
            onAIImageQuery={() => {}}
            onToggleLiveMode={() => {}}
            onQualityChange={() => {}}
            onToggleStreamTransport={() => {}}
            onToggleMute={() => {}}
            onToggleControl={() => {}}
            onToggleMonitoring={() => {}}
            onToggleRestart={() => {}}
            activePanel={null}
            onSelectPanel={() => {}}
            onToggleWeb={() => {}}
            onClose={() => {}}
            {...props}
          />
        </HostControlContext.Provider>
      </HostDataContext.Provider>
    </MemoryRouter>,
  );

describe('RecStreamModalHeader — tv_lite (monitoring off) behavior', () => {
  beforeEach(() => {
    mockApiGet.mockResolvedValue({ status: { source_url: 'https://example.test/stream.m3u8' } });
  });

  afterEach(() => {
    mockApiGet.mockReset();
    cleanup();
  });

  it('disables Timeline and AVQ feature link and the AI image-query button with the same monitoring-off tooltip', () => {
    renderHeader();

    // getByRole with `name` matches the aria-label on the IconButton. The toolbar
    // renders these once each, so a single match is the right one in both states.
    const timeline = screen.getByRole('button', { name: 'Timeline' }) as HTMLButtonElement;
    expect(timeline.disabled).toBe(true);
    expect(timeline.getAttribute('title')).toBe(TV_LITE_MONITORING_OFF_TITLE);

    const avq = screen.getByRole('button', { name: 'Audio/Video Quality' }) as HTMLButtonElement;
    expect(avq.disabled).toBe(true);
    expect(avq.getAttribute('title')).toBe(TV_LITE_MONITORING_OFF_TITLE);

    const askAi = screen.getByRole('button', { name: 'Ask AI about frame' }) as HTMLButtonElement;
    expect(askAi.disabled).toBe(true);
    expect(askAi.getAttribute('title')).toBe(TV_LITE_MONITORING_OFF_TITLE);
  });

  it('keeps Timeline / Ask AI / AVQ enabled when the device is NOT in monitoring_off', () => {
    renderHeader({
      host: { ...baseHost, system_stats: { ...baseHost.system_stats, monitoring_off: [] } },
    });

    expect((screen.getByRole('button', { name: 'Timeline' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'Ask AI about frame' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'Audio/Video Quality' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('adds a Source item to the Actions menu for rtsp_video devices and opens the URL in a new tab', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);

    renderHeader();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /^Actions/ }));

    const sourceItem = await screen.findByText('Source');
    // Reach the menuitem wrapper to check disabled state and click it (some
    // MUI MenuItem tests focus the inner span, which does not carry disabled).
    const sourceMenuItem = sourceItem.closest('[role="menuitem"]') as HTMLElement | null;
    expect(sourceMenuItem).toBeTruthy();
    await waitFor(() => {
      expect((sourceMenuItem as any).getAttribute('aria-disabled') === 'true').toBe(false);
    });

    await user.click(sourceItem);
    expect(openSpy).toHaveBeenCalledWith('https://example.test/stream.m3u8', '_blank', 'noopener');

    openSpy.mockRestore();
  });

  it('hides the Source item entirely for device models without a stream source', async () => {
    renderHeader({
      device: { ...tvDevice, device_model: 'host_vnc' },
    });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /^Actions/ }));

    expect(screen.queryByText('Source')).toBeNull();
  });

  it('disables the AI Agent item in Actions with the same monitoring-off tooltip', async () => {
    renderHeader();
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: /^Actions/ }));

    const aiAgent = await screen.findByText('AI Agent');
    const aiMenuItem = aiAgent.closest('[role="menuitem"]') as HTMLElement | null;
    expect(aiMenuItem).toBeTruthy();
    expect((aiMenuItem as any).getAttribute('aria-disabled')).toBe('true');
    expect((aiMenuItem as any).getAttribute('title')).toBe(TV_LITE_MONITORING_OFF_TITLE);
  });
});
