import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LiveStreamSwitch } from '../../frontend/src/components/common/LiveStream/LiveStreamSwitch';

/**
 * BUG-0832 — the reason existed all along (`useWhepStream` logged it) but was
 * dropped on the floor at the `LiveStreamSwitch` boundary: the prop was
 * `() => void` and the callback fired with no argument, so the caller could only
 * ever say "WebRTC unavailable". This pins the argument actually arriving.
 */
const useLiveTransport = vi.fn();
vi.mock('../../frontend/src/hooks/controller/useLiveTransport', () => ({
  useLiveTransport: (...args: unknown[]) => useLiveTransport(...args),
}));

// jsdom has no media stack; the player is irrelevant to what is under test.
vi.mock('../../frontend/src/components/common/LiveStream/WebRTCVideoPlayer', () => ({
  WebRTCVideoPlayer: () => <div data-testid="webrtc-player" />,
}));

const transportState = (over: Record<string, unknown> = {}) => ({
  transport: 'hls',
  status: 'failed',
  stream: null,
  pc: null,
  failReason: null,
  showStats: false,
  ...over,
});

const renderSwitch = (onWebRTCFailed: (reason: string) => void) =>
  render(
    <LiveStreamSwitch
      streamUrl="https://example.test/stream/capture2/hot/output.m3u8"
      webrtcEnabled
      onWebRTCFailed={onWebRTCFailed}
    >
      <div data-testid="hls-player" />
    </LiveStreamSwitch>,
  );

describe('LiveStreamSwitch — hands the failure reason to its caller', () => {
  beforeEach(() => {
    useLiveTransport.mockReturnValue(transportState());
  });

  it('passes the reason through, so the notification can say why', () => {
    useLiveTransport.mockReturnValue(transportState({ failReason: 'Failed to fetch' }));
    const onWebRTCFailed = vi.fn();
    renderSwitch(onWebRTCFailed);
    expect(onWebRTCFailed).toHaveBeenCalledWith('Failed to fetch');
  });

  it('falls back to a placeholder rather than firing with undefined', () => {
    useLiveTransport.mockReturnValue(transportState({ failReason: null }));
    const onWebRTCFailed = vi.fn();
    renderSwitch(onWebRTCFailed);
    // "undefined" would render as "WebRTC unavailable (undefined)" — the same
    // unreadable notification this bug is about.
    expect(onWebRTCFailed).toHaveBeenCalledWith('unknown');
  });

  it('fires once per give-up, not once per render', () => {
    const onWebRTCFailed = vi.fn();
    const { rerender } = renderSwitch(onWebRTCFailed);
    rerender(
      <LiveStreamSwitch streamUrl="https://example.test/stream/capture2/hot/output.m3u8" webrtcEnabled onWebRTCFailed={onWebRTCFailed}>
        <div data-testid="hls-player" />
      </LiveStreamSwitch>,
    );
    expect(onWebRTCFailed).toHaveBeenCalledTimes(1);
  });

  it('does not fire while the session is healthy', () => {
    useLiveTransport.mockReturnValue(transportState({ status: 'playing', transport: 'webrtc' }));
    const onWebRTCFailed = vi.fn();
    renderSwitch(onWebRTCFailed);
    expect(onWebRTCFailed).not.toHaveBeenCalled();
  });
});