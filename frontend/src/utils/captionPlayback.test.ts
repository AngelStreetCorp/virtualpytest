import { describe, expect, it } from 'vitest';

import {
  findChunk, formatBehind, hostOffsetMs, hostSecondOfDay, languageCode, readyUntil, targetPosition,
} from './captionPlayback';

describe('captionPlayback', () => {
  it('places the target delay_s behind now in hour/chunk/offset, on the host clock', () => {
    const now = Date.UTC(2026, 9, 14, 15, 24, 30);
    expect(targetPosition(now, 150, 0)).toEqual({ hour: 15, chunkIndex: 2, offset: 120 });
    const wrap = Date.UTC(2026, 9, 14, 16, 0, 10);
    expect(targetPosition(wrap, 150, 0)).toEqual({ hour: 15, chunkIndex: 5, offset: 460 });
    // a host two hours ahead of UTC (CEST) names the same instant hour 17
    expect(targetPosition(now, 150, 2 * 3_600_000)).toEqual({ hour: 17, chunkIndex: 2, offset: 120 });
  });

  it('reads the host clock offset off the newest manifest chunk', () => {
    const created = Date.UTC(2026, 9, 15, 10, 50, 16) / 1000;
    const chunks = [
      { hour: 12, chunk_index: 3, created: created - 600, end_time: '2026-10-15T12:39:59.239467' },
      { hour: 12, chunk_index: 4, created, end_time: '2026-10-15T12:49:59.230385' },
    ];
    expect(hostOffsetMs(chunks)).toBe(2 * 3_600_000);
    expect(hostOffsetMs([{ hour: 1, chunk_index: 0, created: 1 }])).toBeNull();
    expect(hostOffsetMs([])).toBeNull();
    expect(hostSecondOfDay(Date.UTC(2026, 9, 15, 10, 50, 16), 2 * 3_600_000)).toBe(12 * 3600 + 50 * 60 + 16);
  });

  it('takes the newest manifest entry for a rolling-archive name', () => {
    const chunks = [{ hour: 3, chunk_index: 1, created: 5 }, { hour: 3, chunk_index: 1, created: 9 }];
    expect(findChunk(chunks, 3, 1)?.created).toBe(9);
    expect(findChunk(chunks, 3, 2)).toBeNull();
  });

  it('plays until the end of the last minute the host has processed', () => {
    expect(readyUntil(undefined)).toBe(0);
    const m = (minute: number, ready: boolean) => ({ minute, ready, caption_source: 'machine' as const });
    expect(readyUntil([m(0, true), m(1, true), m(2, false)])).toBe(120);
    expect(readyUntil([m(0, false)])).toBe(0);
  });

  it('maps the host language name to a picker code', () => {
    expect(languageCode('German')).toBe('de');
    expect(languageCode('fr')).toBe('fr');
    expect(languageCode(null)).toBeNull();
  });

  it('formats the offset as m:ss', () => {
    expect(formatBehind(150)).toBe('2:30');
    expect(formatBehind(61.4)).toBe('1:01');
  });
});
