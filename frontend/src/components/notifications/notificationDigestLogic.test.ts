import { describe, expect, it } from 'vitest';

import { selectDigest } from './notificationDigestLogic';

const NOW = 1_700_000_000_000;
const HOUR = 60 * 60 * 1000;

const item = (over: Partial<Parameters<typeof selectDigest>[0][number]> = {}) => ({
  id: 'n1',
  severity: 'warning' as const,
  message: 'something',
  ts: NOW - HOUR,
  read: false,
  ...over,
});

describe('selectDigest', () => {
  it('returns nothing when there is no error and no warning in the window', () => {
    expect(selectDigest([], NOW)).toBeNull();
    expect(selectDigest([item({ severity: 'info' })], NOW)).toBeNull();
    expect(selectDigest([item({ ts: NOW - 25 * HOUR })], NOW)).toBeNull();
  });

  it('prefers errors over warnings', () => {
    const selection = selectDigest(
      [item({ id: 'w1', severity: 'warning' }), item({ id: 'e1', severity: 'error' })],
      NOW,
    );
    expect(selection?.severity).toBe('error');
    expect(selection?.items.map((n) => n.id)).toEqual(['e1']);
    expect(selection?.total).toBe(1);
  });

  it('falls back to warnings when there is no error', () => {
    const selection = selectDigest([item({ id: 'w1', severity: 'warning' })], NOW);
    expect(selection?.severity).toBe('warning');
    expect(selection?.total).toBe(1);
  });

  it('keeps the three most recent and counts them all', () => {
    const selection = selectDigest(
      [
        item({ id: 'e1', severity: 'error', ts: NOW - 4 * HOUR }),
        item({ id: 'e2', severity: 'error', ts: NOW - 1 * HOUR }),
        item({ id: 'e3', severity: 'error', ts: NOW - 3 * HOUR }),
        item({ id: 'e4', severity: 'error', ts: NOW - 2 * HOUR }),
      ],
      NOW,
    );
    expect(selection?.items.map((n) => n.id)).toEqual(['e2', 'e4', 'e3']);
    expect(selection?.total).toBe(4);
  });

  it('ignores a problem the platform has already seen clear', () => {
    const selection = selectDigest([item({ severity: 'error', resolved_at: NOW - HOUR })], NOW);
    expect(selection).toBeNull();
  });

  it('ignores problems older than the window', () => {
    expect(selectDigest([item({ severity: 'error', ts: NOW - 24 * HOUR - 1 })], NOW)).toBeNull();
    expect(selectDigest([item({ severity: 'error', ts: NOW - 23 * HOUR })], NOW)?.total).toBe(1);
  });
});
