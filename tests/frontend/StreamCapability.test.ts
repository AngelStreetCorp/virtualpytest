import { describe, expect, it } from 'vitest';

import {
  STREAM_PROFILE,
  webrtcSupportedFor,
  webrtcUnavailableReason,
} from '../../frontend/src/utils/streamCapability';

/**
 * BUG-0833 — the WEB toggle was rendered unconditionally, so on a host with no MediaMTX
 * (host-clone-1: `vpt-mediamtx` inactive, no `mediamtx.yml`) every press was a guaranteed
 * 6 s timeout and an error toast naming no device. These pin the gate that replaced it.
 */
describe('webrtcSupportedFor — may the WEB toggle be offered?', () => {
  it('allows WEB only for a whep device', () => {
    expect(webrtcSupportedFor(STREAM_PROFILE.WHEP)).toBe(true);
  });

  it.each([
    [STREAM_PROFILE.CLOUD_FARM, 'cloud farm session'],
    [STREAM_PROFILE.HLS_NO_WEBRTC_HOST, 'host without MediaMTX'],
    [STREAM_PROFILE.HLS_NO_PUBLISHER, 'capture with no publisher'],
  ])('denies WEB for %s (%s)', (profile) => {
    expect(webrtcSupportedFor(profile)).toBe(false);
  });

  it('fails open when a host has not reported a profile', () => {
    // A host whose backend predates the field must keep working exactly as before —
    // gating strictly on 'whep' would delete WebRTC from every lab v4l2 device
    // between the frontend deploy and the host deploy.
    expect(webrtcSupportedFor(undefined)).toBe(true);
    expect(webrtcSupportedFor(null)).toBe(true);
    expect(webrtcSupportedFor('')).toBe(true);
    expect(webrtcSupportedFor(STREAM_PROFILE.HLS)).toBe(true);
  });
});

describe('webrtcUnavailableReason — each denial says its own fix', () => {
  it('tells a farm operator it is never possible, not "install something"', () => {
    const reason = webrtcUnavailableReason(STREAM_PROFILE.CLOUD_FARM);
    expect(reason).toMatch(/vendor/i);
    // The actionable half matters: the host CAN be fixed, this device never can.
    expect(reason).not.toMatch(/install/i);
  });

  it('names MediaMTX when the host is the problem', () => {
    expect(webrtcUnavailableReason(STREAM_PROFILE.HLS_NO_WEBRTC_HOST)).toMatch(/MediaMTX/);
  });

  it('points at the capture when the device is the problem', () => {
    expect(webrtcUnavailableReason(STREAM_PROFILE.HLS_NO_PUBLISHER)).toMatch(/capture/i);
  });

  it('gives no reason when WEB is available', () => {
    expect(webrtcUnavailableReason(STREAM_PROFILE.WHEP)).toBeNull();
    expect(webrtcUnavailableReason(undefined)).toBeNull();
    expect(webrtcUnavailableReason(STREAM_PROFILE.HLS)).toBeNull();
  });

  it('gives a different sentence per denied profile', () => {
    const reasons = [
      STREAM_PROFILE.CLOUD_FARM,
      STREAM_PROFILE.HLS_NO_WEBRTC_HOST,
      STREAM_PROFILE.HLS_NO_PUBLISHER,
    ].map((p) => webrtcUnavailableReason(p));
    expect(new Set(reasons).size).toBe(3);
  });
});