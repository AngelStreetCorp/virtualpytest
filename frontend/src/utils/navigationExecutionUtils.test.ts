/**
 * BUG-0395: the Go To panel stayed on "Executing…" after the device had arrived,
 * because the status endpoint was only read once the socket wait had given up
 * (120 s). These tests pin the race: polling answers even when the socket never does.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./executionSocketWait', () => ({
  // A socket that never delivers the terminal event (refused / missed).
  waitForExecutionSocketEvent: vi.fn(() => new Promise(() => {})),
}));

vi.mock('./buildUrlUtils', () => ({
  buildServerUrl: (endpoint: string) => `http://server${endpoint}`,
}));

import { waitForNavigationOutcome } from './navigationExecutionUtils';
import { waitForExecutionSocketEvent } from './executionSocketWait';

const jsonResponse = (body: unknown) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(body) } as Response);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('waitForNavigationOutcome', () => {
  it('resolves from polling while the socket stays silent', async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ success: true, status: 'running' }))
      .mockReturnValueOnce(
        jsonResponse({ success: true, status: 'completed', result: { success: true } }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const event = await waitForNavigationOutcome('exec-1', 'host', 'device1', { pollIntervalMs: 1 });

    expect(event.status).toBe('completed');
    expect(event.result).toEqual({ success: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('treats aborted as terminal', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ success: true, status: 'aborted', error: 'stopped' })));
    const event = await waitForNavigationOutcome('exec-2', 'host', 'device1', { pollIntervalMs: 1 });
    expect(event.status).toBe('aborted');
  });

  it('rejects when the host no longer knows the execution', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse({ success: false, error: 'Execution exec-3 not found' })),
    );
    await expect(
      waitForNavigationOutcome('exec-3', 'host', 'device1', { pollIntervalMs: 1 }),
    ).rejects.toThrow(/no longer known/);
  });

  it('rejects on timeout so the panel leaves its executing state', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ success: true, status: 'running' })));
    await expect(
      waitForNavigationOutcome('exec-4', 'host', 'device1', { pollIntervalMs: 1, timeoutMs: 20 }),
    ).rejects.toThrow(/Timed out/);
  });

  it('takes the socket event when it arrives first', async () => {
    vi.mocked(waitForExecutionSocketEvent).mockResolvedValueOnce({
      type: 'execution_update',
      execution_id: 'exec-5',
      status: 'completed',
      result: { success: true, via: 'socket' },
    });
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ success: true, status: 'running' })));
    const event = await waitForNavigationOutcome('exec-5', 'host', 'device1', { pollIntervalMs: 1 });
    expect(event.result).toEqual({ success: true, via: 'socket' });
  });
});
