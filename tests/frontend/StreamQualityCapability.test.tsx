import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { StreamQualityControl } from '../../frontend/src/components/rec/StreamQualityControl';
import { STREAM_PROFILE } from '../../frontend/src/utils/streamCapability';

/**
 * BUG-0833 — the WEB toggle used to render whenever the modal was in live mode, on every
 * device. On host-clone-1 (no MediaMTX) every press was a guaranteed 6 s timeout and an
 * error toast. It is now shown but disabled, with the reason on hover.
 */
const renderControl = (streamProtocol?: string) =>
  render(
    <StreamQualityControl
      quality="hd"
      transport="hls"
      disabled={false}
      streamProtocol={streamProtocol}
      onQualityChange={vi.fn()}
      onToggleTransport={vi.fn()}
    />,
  );

describe('StreamQualityControl — the WEB toggle respects the device profile', () => {
  it('is an active toggle on a whep device', () => {
    renderControl(STREAM_PROFILE.WHEP);
    const toggle = screen.getByTestId('web-toggle');
    expect(toggle).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /WEB/ })).toBeEnabled();
  });

  it.each([
    [STREAM_PROFILE.CLOUD_FARM, 'cloud farm'],
    [STREAM_PROFILE.HLS_NO_WEBRTC_HOST, 'no MediaMTX'],
    [STREAM_PROFILE.HLS_NO_PUBLISHER, 'no publisher'],
  ])('is disabled but still shown for %s (%s)', (profile) => {
    renderControl(profile);
    // Still shown, not hidden: an operator who cannot find WEB needs to be told why.
    expect(screen.queryByTestId('web-toggle')).not.toBeInTheDocument();
    expect(screen.getByTestId('web-unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'WEB' })).toBeDisabled();
  });

  it('stays active on a host that reports no profile', () => {
    renderControl(undefined);
    expect(screen.getByTestId('web-toggle')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /WEB/ })).toBeEnabled();
  });

  it('always offers the HLS resolutions, denied WEB or not', () => {
    renderControl(STREAM_PROFILE.CLOUD_FARM);
    // The point of the gate is to remove WEB, never the picture.
    expect(screen.getByRole('button', { name: /LOW/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /SD/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /HD/ })).toBeInTheDocument();
  });
});