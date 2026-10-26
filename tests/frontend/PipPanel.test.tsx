// @vitest-environment jsdom
/**
 * The picture-in-picture panel (BUG-0777).
 *
 * Two things had to be true for the panel to show up:
 *  1. the AV player reads the VNC state, which throws without a provider — the pages
 *     that render the panels on their own had none, so picking a `host_vnc` device
 *     crashed the page instead of floating the stream;
 *  2. a right-anchored panel has to grow to the LEFT of its anchor, and the overlay has
 *     to give the panel an offset relative to its shell, not to the viewport — otherwise
 *     the panel hangs past the right edge of the screen.
 */
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

import { DeviceControlPanels } from '../../frontend/src/components/common/DeviceControlPanels';
import { panelAnchorEdges } from '../../frontend/src/components/controller/av/panelAnchor';

// The real player reads the VNC state; the mock reproduces that read, so the test
// fails exactly where the page crashed.
vi.mock('../../frontend/src/components/controller/av/VNCStream', async () => {
  const { useVNCState } = await vi.importActual<typeof import('../../frontend/src/contexts/VNCStateContext')>(
    '../../frontend/src/contexts/VNCStateContext',
  );
  return {
    VNCStream: () => {
      const { isVNCExpanded } = useVNCState();
      return <div data-testid="vnc-stream">{String(isVNCExpanded)}</div>;
    },
  };
});

const HOST = {
  host_name: 'host-clone-1',
  devices: [
    { device_id: 'host-clone-1_Host', device_name: 'Host', device_model: 'host_vnc', device_capabilities: {} },
  ],
};

describe('the picture-in-picture panel (BUG-0777)', () => {
  it('renders the player without a VNC provider above it', () => {
    // No provider here on purpose: the overlay and the builder pages have none.
    const { getByTestId } = render(
      <DeviceControlPanels
        showAVPanel
        selectedHost={HOST as any}
        selectedDeviceId="host-clone-1_Host"
        isControlActive
      />,
    );
    expect(getByTestId('vnc-stream')).toBeTruthy();
  });

  it('grows a right-anchored panel to the left of its anchor', () => {
    // A right-anchored panel that grew to the right would hang past the right edge.
    expect(panelAnchorEdges(true)).toEqual({ left: 'auto', right: 0 });
    expect(panelAnchorEdges(false)).toEqual({ left: 0, right: 'auto' });
  });
});
