import { describe, expect, it, vi } from 'vitest';

import { whepFailureText, whepFallbackNotice } from '../../frontend/src/utils/whepFallback';

/**
 * BUG-0832 — "WebRTC unavailable — back on HLS" told the operator nothing: no
 * device, no host, no reason, and the bell row linked back to whatever page
 * happened to be open (the heatmap) because the stream modal never changes the
 * URL. Four separate defects, one notification.
 */
describe('whepFallbackNotice — the WebRTC→HLS fallback notification', () => {
  const base = { hostName: 'host-clone-1', deviceLabel: 'Sauce_S23_FE', deviceId: 'capture2', reason: 'timeout' };

  it('names the host and the device — the two things the old message omitted', () => {
    const { message } = whepFallbackNotice(base);
    expect(message).toContain('host-clone-1');
    expect(message).toContain('Sauce_S23_FE');
  });

  it('carries the reason, so the operator can tell a timeout from a blocked request', () => {
    expect(whepFallbackNotice(base).message).toContain('no frame in time');
    expect(whepFallbackNotice({ ...base, reason: 'Failed to fetch' }).message).toContain('CORS');
  });

  it('links to that device on Device Control, not to the page the modal was opened from', () => {
    const { action } = whepFallbackNotice(base);
    expect(action.to).toBe('/device-control?device=host-clone-1%2Fcapture2');
    // The heatmap is the page this bug was reported from: a `to` defaulting to
    // window.location is what sent the operator back there instead.
    expect(action.to).not.toContain('/monitoring');
  });

  it('gives every device its own id, so N devices failing are N bell rows', () => {
    // Keyed by page instead, these two collapsed into a single entry — the second
    // replaced the first and the operator could never tell how many had failed.
    const a = whepFallbackNotice(base);
    const b = whepFallbackNotice({ ...base, deviceId: 'capture3', deviceLabel: 'BStack_S23' });
    expect(a.id).not.toBe(b.id);

    // …but the same device failing again stays one row (a repeat is the same problem).
    expect(whepFallbackNotice(base).id).toBe(a.id);
  });

  it('is categorised and scoped as a device problem, not a generic action', () => {
    const { category, scope } = whepFallbackNotice(base);
    expect(category).toBe('device');
    expect(scope).toEqual({ host_name: 'host-clone-1', device_id: 'capture2' });
  });
});

describe('whepFailureText — the raw reason stays in the message', () => {
  it.each([
    ['timeout', 'no frame in time'],
    ['Failed to fetch', 'the WHEP request never got through (CORS, cookie or proxy)'],
    ['failed', 'connection dropped'],
    ['disconnected', 'connection dropped'],
    ['closed', 'connection dropped'],
  ])('spells out %s', (reason, expected) => {
    expect(whepFailureText(reason)).toBe(expected);
  });

  it('passes an unknown reason through rather than hiding it', () => {
    // A reason the app has never seen is still information; swallowing it would
    // reproduce the original complaint ("no logs, hard to understand").
    expect(whepFailureText('Something new from the browser')).toBe('Something new from the browser');
    expect(whepFailureText('unknown')).toBe('unknown');
  });
});