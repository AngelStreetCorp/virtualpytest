import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useTimeline } from '../../frontend/src/hooks/useTimeline';
import { hostTimelineStatus } from '../../frontend/src/hooks/useTimelineSupport';

/**
 * BUG-0778 review: the probe in useTimeline re-runs on every `chunks` change and asked the
 * host's status route each time; and a failed status call was swallowed without a trace.
 */

vi.mock('../../frontend/src/utils/buildUrlUtils', () => ({
  buildArchiveManifestUrl: (host: { host_name: string }, id: string) => `http://${host.host_name}/${id}/manifest`,
  buildTimelineFileUrl: (host: { host_name: string }, id: string, hour: number, name: string) => `http://${host.host_name}/${id}/${hour}/${name}`,
  buildServerUrlWithParams: (endpoint: string, params: Record<string, string>) =>
    `${endpoint}?${Object.entries(params).map(([k, v]) => `${k}=${v}`).join('&')}`,
  ensureHostSessionOnce: async () => true,
  ensureHostSession: async () => true,
  isGatedHostPath: () => false,
  fetchHostMedia: async (url: string) => {
    const now = Date.now() / 1000;
    if (url.includes('/manifest')) {
      return { ok: true, status: 200, json: async () => ({ chunks: [{ hour: 5, chunk_index: 2, created: now - 600 }, { hour: 5, chunk_index: 1, created: now - 1200 }] }) };
    }
    return { ok: true, status: 200 };
  },
}));

const host = { host_name: 'h1' };
const statusCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).includes('/server/timeline/status')).length;

const fetchMock = vi.fn(async (_url: string, _init?: unknown) => ({
  ok: true,
  status: 200,
  json: async () => ({ enabled: true, chunks: 2 }),
}));

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('useTimeline asks the host about its service once', () => {
  it('does not repeat the status call when the host object is rebuilt and the chunks reload', async () => {
    const { result, rerender } = renderHook(({ h }) => useTimeline(h, 'cam1'), { initialProps: { h: { host_name: 'h1' } } });
    await waitFor(() => expect(result.current.built).toBe(true));
    expect(statusCalls()).toBe(1);

    // the same host as a new object: the chunk list is loaded again (new `chunks`), the answer is kept
    rerender({ h: { host_name: 'h1' } });
    await waitFor(() => expect(result.current.chunks.length).toBeGreaterThan(0));
    await act(async () => {});
    expect(statusCalls()).toBe(1);
  });

  it('asks again for another device and on an explicit reload', async () => {
    const { result, rerender } = renderHook(({ id }) => useTimeline(host, id), { initialProps: { id: 'cam1' } });
    await waitFor(() => expect(result.current.built).toBe(true));
    rerender({ id: 'cam2' });
    await waitFor(() => expect(statusCalls()).toBe(2));
    await act(async () => {
      await result.current.reload();
    });
    await waitFor(() => expect(statusCalls()).toBe(3));
  });
});

describe('a failed status call is not silent', () => {
  it('logs why it fell back to the file probe', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    fetchMock.mockRejectedValueOnce(new Error('network down'));
    const status = await hostTimelineStatus(host, 'cam1');
    expect(status).toBeNull();
    expect(warn).toHaveBeenCalled();
    expect(String(warn.mock.calls[0]?.join(' '))).toContain('network down');
  });
});
