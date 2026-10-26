import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useRunningLog } from '../../frontend/src/hooks/rec/useRunningLog';

/**
 * BUG-0780: a run whose log never appears — a deployment whose execution row is stuck in
 * 'running' while nothing runs on the host — was polled every two seconds for ever, and
 * every one of those requests 404ed. The poll now backs off after a grace period (and never stops).
 */

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }));

vi.mock('../../frontend/src/utils/buildUrlUtils', () => ({
  buildRunningLogUrl: (host: { host_name: string }, deviceId: string) =>
    `http://${host.host_name}/${deviceId}/running.log`,
}));

vi.mock('../../frontend/src/utils/recUtils', () => ({
  isRunningLogStale: () => false,
}));

const host = { host_name: 'h1' } as never;
const POLL_MS = 2000;

beforeEach(() => {
  fetchMock.mockReset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the running.log poll', () => {
  it('keeps polling while the log has not been written yet', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    const { result } = renderHook(() => useRunningLog(host, 'device1', true));

    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls.length).toBe(1);

    // A 404 right after the run starts is normal: the poll continues.
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(fetchMock.mock.calls.length).toBe(4);
    expect(result.current.logData).toBeNull();
  });

  it('backs off, but keeps asking, for a log that is late (BUG-0780 review)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    renderHook(() => useRunningLog(host, 'device1', true));

    await vi.advanceTimersByTimeAsync(0);
    // fifteen fast misses, then the poll slows down
    await vi.advanceTimersByTimeAsync(POLL_MS * 20);
    const afterFast = fetchMock.mock.calls.length;
    expect(afterFast).toBeGreaterThanOrEqual(15);
    expect(afterFast).toBeLessThan(20);

    // no longer every two seconds ...
    await vi.advanceTimersByTimeAsync(POLL_MS * 5);
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(afterFast + 1);
    // ... but never stopped
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(afterFast + 3);
  });

  it('shows the overlay data when a queued run writes its log after the backoff', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    const { result } = renderHook(() => useRunningLog(host, 'device1', true));
    await vi.advanceTimersByTimeAsync(POLL_MS * 20 + 1000);
    expect(result.current.logData).toBeNull();

    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ script_name: 'late_run', start_time: new Date().toISOString() }),
    });
    await vi.advanceTimersByTimeAsync(20_000);
    expect(result.current.scriptName).toBe('late_run');
  });

  it('starts the miss count again for a new device', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    const { rerender } = renderHook(({ id }) => useRunningLog(host, id, true), {
      initialProps: { id: 'device1' },
    });
    await vi.advanceTimersByTimeAsync(POLL_MS * 20);
    const before = fetchMock.mock.calls.length;
    rerender({ id: 'device2' });
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    // fast polling again: one immediate call plus one per two seconds
    expect(fetchMock.mock.calls.length - before).toBeGreaterThanOrEqual(3);
  });

  it('reads the log when the host has one', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ script_name: 'smoke_ui', start_time: new Date().toISOString() }),
    });
    const { result } = renderHook(() => useRunningLog(host, 'device1', true));

    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(result.current.scriptName).toBe('smoke_ui'));
  });
});
