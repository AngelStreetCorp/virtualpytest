import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TimelineTile } from '../../frontend/src/components/timeline/TimelineGrid';
import type { TimelineCell } from '../../frontend/src/hooks/useTimeline';
import { deviceHasTimeline, supportKey, useTimelineSupport } from '../../frontend/src/hooks/useTimelineSupport';

// The host's static files: cam1 has a manifest and a sprite map, cam2 has no archive, cam3 has chunks but nothing built.
// cam4 has a manifest and a sprite map, but the host's Timeline service is not enabled for it.
vi.mock('../../frontend/src/utils/buildUrlUtils', () => ({
  buildArchiveManifestUrl: (host: { host_name: string }, id: string) => `http://${host.host_name}/${id}/manifest`,
  buildTimelineFileUrl: (host: { host_name: string }, id: string, hour: number, name: string) => `http://${host.host_name}/${id}/${hour}/${name}`,
  buildServerUrlWithParams: (endpoint: string, params: Record<string, string>) => {
    const qs = Object.entries(params)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join('&');
    return `${endpoint}?${qs}`;
  },
  fetchHostMedia: async (url: string) => {
    const now = Date.now() / 1000;
    if (url.includes('/manifest')) {
      if (url.includes('/cam2/')) return { ok: false, status: 404, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => ({ chunks: [{ hour: 5, chunk_index: 2, created: now - 600 }, { hour: 5, chunk_index: 1, created: now - 1200 }] }) };
    }
    return { ok: url.includes('/cam1/') && url.endsWith('timeline_2_6s.json'), status: 200 };
  },
}));

const host = { host_name: 'h1' };

/** The host's answer about its Timeline service, per device. */
const serviceStatus: Record<string, { enabled: boolean; chunks: number }> = {
  cam1: { enabled: true, chunks: 2 },
  cam2: { enabled: true, chunks: 0 },
  cam3: { enabled: true, chunks: 2 },
  cam4: { enabled: false, chunks: 2 },
};

const fetchMock = vi.fn(async (url: string) => {
  if (url.includes('/server/timeline/status')) {
    const device = new URL(url, 'http://x').searchParams.get('device_id') || '';
    const status = serviceStatus[device];
    if (!status) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ success: true, device_id: device, ...status }) };
  }
  throw new Error(`unexpected fetch: ${url}`);
});

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('which devices have a Timeline', () => {
  it('a device whose newest chunk has a sprite map has one; no archive or nothing built does not', async () => {
    expect(await deviceHasTimeline(host, 'cam1')).toBe(true);
    expect(await deviceHasTimeline(host, 'cam2')).toBe(false);
    expect(await deviceHasTimeline(host, 'cam3')).toBe(false);
  });

  it('the hook returns only the devices that have one, and says when it is done', async () => {
    const candidates = ['cam1', 'cam2', 'cam3'].map((id) => ({ host, device: { device_id: id } }));
    let latest: { supported: Set<string>; checking: boolean } = { supported: new Set(), checking: true };
    const Probe = () => {
      latest = useTimelineSupport(candidates);
      return <div data-testid="n">{latest.supported.size}</div>;
    };
    render(<Probe />);
    await waitFor(() => expect(latest.checking).toBe(false));
    expect([...latest.supported]).toEqual([supportKey('h1', 'cam1')]);
  });

  /**
   * BUG-0778: the page used to probe up to four sprite files per device with HEAD. The
   * Timeline service is opted in per device, so every probe for a device the service was
   * never enabled for 404ed — 14 to 17 failing requests on every load of the page.
   */
  it('asks the host once per device instead of probing files that cannot exist', async () => {
    // cam4 has a manifest and a sprite map, but the host's service is off for it: the
    // page must not ask for the file at all.
    expect(await deviceHasTimeline(host, 'cam4')).toBe(false);

    const statusCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/server/timeline/status'));
    expect(statusCalls).toHaveLength(1);
    // No HEAD probe for a device the service is off for.
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('timeline_'))).toHaveLength(0);
  });

  it('still probes the sprite file for a device the service is on', async () => {
    expect(await deviceHasTimeline(host, 'cam1')).toBe(true);
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/server/timeline/status'))).toHaveLength(1);
  });
});

describe('tile shape', () => {
  const cell = (aspect: number): TimelineCell => ({ key: 'k', tod: 0, spanS: 6, sprite: null, flags: null, hour: 0, chunkIndex: 0, aspect });

  it('a phone tile is taller than wide, a landscape tile wider than tall', () => {
    const { container, rerender } = render(<TimelineTile cell={cell(9 / 16)} selected={false} withSeconds onSelect={() => {}} onZoom={() => {}} />);
    expect(getComputedStyle(container.firstElementChild as Element).aspectRatio).toBe('0.5625');
    rerender(<TimelineTile cell={cell(16 / 9)} selected={false} withSeconds onSelect={() => {}} onZoom={() => {}} />);
    expect(Number(getComputedStyle(container.firstElementChild as Element).aspectRatio)).toBeGreaterThan(1.7);
    expect(screen.queryByText('FREEZE')).toBeNull();
  });
});
