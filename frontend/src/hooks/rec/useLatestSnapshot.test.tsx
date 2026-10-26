// @vitest-environment jsdom
/**
 * useLatestSnapshot — once the host keeps 404-ing `latest.jpg` (a ffmpeg-disabled
 * device, e.g. one dropped from .env between deploys), the hook must stop
 * hammering the proxy. It only resumes on a new `url` (the device coming back),
 * never on a timer.
 *
 * The HLS player already has this for the manifest (it stops on persistent
 * networkError); the snapshot path was the only place left where every dead
 * tile in a 24-device grid could keep firing 1 Hz requests.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

import { useLatestSnapshot } from './useLatestSnapshot';

const mockFetch = vi.fn();
const originalFetch = global.fetch;

beforeEach(() => {
  mockFetch.mockReset();
  global.fetch = mockFetch as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.useRealTimers();
});

describe('useLatestSnapshot — stop polling after persistent 404', () => {
  it('stops fetching once MAX_CONSECUTIVE_ERRORS in a row 404', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 404 } as Response);

    const { result } = renderHook(
      ({ url, enabled }) => useLatestSnapshot(url, enabled),
      { initialProps: { url: 'https://h/snap', enabled: true } },
    );

    // After the first 1 s tick + 2 retries, errorCount reaches 3 and givenUp
    // flips. A fourth tick is never scheduled.
    await waitFor(() => expect(result.current.error).toBe(true), { timeout: 5000 });
    const callsAtGiveUp = mockFetch.mock.calls.length;

    // Wait another 2 s — no new fetch should fire.
    await new Promise((r) => setTimeout(r, 2200));
    expect(mockFetch.mock.calls.length).toBe(callsAtGiveUp);
  });

  it('does not poll when document is hidden, then resumes on visibility', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 404 } as Response);

    const visibilitySpy = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);

    renderHook(() => useLatestSnapshot('https://h/snap', true));

    // While hidden: 1 s tick is scheduled but no fetch fires.
    await new Promise((r) => setTimeout(r, 1500));
    expect(mockFetch).not.toHaveBeenCalled();

    visibilitySpy.mockReturnValue(false);
    // The hook polls the flag once a second; wait until the next tick reads
    // document.hidden === false and fires the request.
    await waitFor(() => expect(mockFetch).toHaveBeenCalled(), { timeout: 3000 });
  });

  it('resets the error counter when a new url is supplied (device came back)', async () => {
    mockFetch.mockImplementation(async () => ({ ok: false, status: 404 } as Response));

    const { result, rerender } = renderHook(
      ({ url, enabled }) => useLatestSnapshot(url, enabled),
      { initialProps: { url: 'https://h/snap-old', enabled: true } },
    );

    await waitFor(() => expect(result.current.error).toBe(true), { timeout: 5000 });
    const callsBefore = mockFetch.mock.calls.length;

    // Host's device list refreshes: the dropped device came back with a
    // different capture dir, so the URL changes. The hook re-runs, the
    // errorCount resets, and a new polling loop starts.
    rerender({ url: 'https://h/snap-new', enabled: true });
    await waitFor(() => expect(mockFetch.mock.calls.length).toBeGreaterThan(callsBefore));
  });
});
