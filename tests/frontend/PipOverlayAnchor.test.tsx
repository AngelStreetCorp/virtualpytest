// @vitest-environment jsdom
/**
 * Where the picture-in-picture panel is anchored (BUG-0777).
 *
 * The overlay's shell is the anchor point in the viewport (bottom-right, or bottom-left
 * when the remote is shown). The panels inside it are positioned absolutely, so the
 * offsets they get are read against the shell — passing the viewport offsets again put
 * the panel twice as far from the corner as it should be, and past the right edge of
 * the screen.
 */
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

import { PipOverlay } from '../../features/mods/frontend/pip/components/PipOverlay';

const { captured, pipState } = vi.hoisted(() => ({
  captured: [] as any[],
  pipState: { showRemote: false, collapsed: false, ownsControl: false },
}));

vi.mock('../../frontend/src/components/common/DeviceControlPanels', () => ({
  DeviceControlPanels: (props: any) => {
    captured.push(props);
    return <div data-testid="panels" />;
  },
}));

vi.mock('../../features/mods/frontend/pip/hooks/usePip', () => ({
  usePip: () => ({
    state: {
      selection: { hostName: 'host-clone-1', deviceId: 'host-clone-1_Host' },
      ownsControl: pipState.ownsControl,
      collapsed: pipState.collapsed,
      position: { x: 0, y: 0 },
    },
    hosts: [],
    host: { host_name: 'host-clone-1', devices: [] },
    device: { device_id: 'host-clone-1_Host', device_name: 'Host', device_model: 'host_vnc' },
    paused: false,
    showRemote: pipState.showRemote,
    select: vi.fn(),
    toggleRemote: vi.fn(),
    setCollapsed: vi.fn(),
    setPosition: vi.fn(),
    reclampPosition: vi.fn(),
  }),
}));

vi.mock('../../features/mods/frontend/pip/hooks/usePipControl', () => ({
  usePipControl: () => ({ take: vi.fn(), release: vi.fn() }),
}));

vi.mock('../../frontend/src/hooks/useResponsiveMode', () => ({
  useResponsiveMode: () => ({ isMobile: false, isTablet: false, isDesktop: true }),
}));

describe('the picture-in-picture overlay (BUG-0777)', () => {
  it('anchors the panel to its own shell, not to the viewport', () => {
    pipState.showRemote = false;
    captured.length = 0;
    render(<PipOverlay />);
    expect(captured.length).toBeGreaterThan(0);
    // Right edge and bottom edge of the shell — the shell itself carries the 20 px / 56 px
    // margin from the edge of the screen.
    expect(captured[0].customPosition).toEqual({ right: '0px', bottom: '0px' });
  });

  it('anchors the panel to the left of the shell when the remote is shown', () => {
    pipState.showRemote = true;
    captured.length = 0;
    render(<PipOverlay />);
    expect(captured.length).toBeGreaterThan(0);
    expect(captured[0].customPosition).toEqual({ left: '0px', bottom: '0px' });
  });
});
