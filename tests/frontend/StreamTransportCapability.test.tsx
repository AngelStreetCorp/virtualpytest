import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useStreamTransport } from '../../frontend/src/hooks/controller/useStreamTransport';
import { streamTransportStorageKey } from '../../frontend/src/constants/webrtcConstants';
import { STREAM_PROFILE } from '../../frontend/src/utils/streamCapability';

/**
 * BUG-0833 — the half of the fix that stops the error rather than explaining it.
 *
 * Disabling the WEB button is not enough on its own: the operator's per-device choice lives
 * in localStorage, so a device switched to WEB before the host was probed would keep asking
 * for WebRTC on every open — a 6 s timeout and an error each time, with the button now
 * disabled and no obvious link between the two.
 */
const HOST = 'host-clone-1';
const DEVICE = 'capture2';
const key = streamTransportStorageKey(HOST, DEVICE);

describe('useStreamTransport — a device that cannot do WebRTC never tries', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('starts on HLS for a device whose profile denies WebRTC', () => {
    const { result } = renderHook(() => useStreamTransport(HOST, DEVICE, STREAM_PROFILE.HLS_NO_WEBRTC_HOST));
    expect(result.current.transport).toBe('hls');
    expect(result.current.webrtcSupported).toBe(false);
  });

  it('clears a stored WebRTC choice that the profile now denies', () => {
    window.localStorage.setItem(key, JSON.stringify('webrtc'));
    const { result } = renderHook(() => useStreamTransport(HOST, DEVICE, STREAM_PROFILE.CLOUD_FARM));
    // The decisive assertion: `transport` drives LiveStreamSwitch's `webrtcEnabled`, so
    // 'hls' here is what actually stops the connection attempt.
    expect(result.current.transport).toBe('hls');
    expect(window.localStorage.getItem(key)).toBe(JSON.stringify('hls'));
  });

  it('clears it for every denied profile, not just farms', () => {
    for (const profile of [STREAM_PROFILE.CLOUD_FARM, STREAM_PROFILE.HLS_NO_WEBRTC_HOST, STREAM_PROFILE.HLS_NO_PUBLISHER]) {
      window.localStorage.setItem(key, JSON.stringify('webrtc'));
      const { result, unmount } = renderHook(() => useStreamTransport(HOST, DEVICE, profile));
      expect(result.current.transport, profile).toBe('hls');
      unmount();
    }
  });

  it('keeps a stored WebRTC choice on a device that still supports it', () => {
    window.localStorage.setItem(key, JSON.stringify('webrtc'));
    const { result } = renderHook(() => useStreamTransport(HOST, DEVICE, STREAM_PROFILE.WHEP));
    expect(result.current.transport).toBe('webrtc');
    expect(result.current.webrtcSupported).toBe(true);
  });

  it('keeps an operator choice on a host that reports nothing', () => {
    window.localStorage.setItem(key, JSON.stringify('webrtc'));
    const { result } = renderHook(() => useStreamTransport(HOST, DEVICE, undefined));
    // Fail-open: until every host is redeployed, an unreported device behaves as before.
    expect(result.current.transport).toBe('webrtc');
    expect(result.current.webrtcSupported).toBe(true);
  });

  it('toggling still works where WebRTC is supported', () => {
    const { result } = renderHook(() => useStreamTransport(HOST, DEVICE, STREAM_PROFILE.WHEP));
    act(() => result.current.toggleTransport());
    expect(result.current.transport).toBe('hls');
    act(() => result.current.toggleTransport());
    expect(result.current.transport).toBe('webrtc');
  });

  it('a whep device defaults to WebRTC on first visit', () => {
    const { result } = renderHook(() => useStreamTransport(HOST, DEVICE, STREAM_PROFILE.WHEP));
    expect(result.current.transport).toBe('webrtc');
  });
});