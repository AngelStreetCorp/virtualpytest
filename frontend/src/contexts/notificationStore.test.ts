import { describe, expect, it } from 'vitest';

import { addToList, inheritedRow, isResolved, MAX_AGE_MS, mergeHistory, NOTIFICATIONS_MAX, purgeOlderThan, RESOLVED_GRACE_MS, resolvePrefs, sortForBell, type NotificationItem, type NotificationPrefRow } from './notificationStore';

const item = (id: string, ts = 1) => ({ id, severity: 'error' as const, message: id, ts });

describe('addToList', () => {
  it('puts the newest first and de-duplicates by id', () => {
    let list: NotificationItem[] = [];
    list = addToList(list, item('a'));
    list = addToList(list, item('b'));
    list = addToList(list, item('a', 2));
    expect(list.map((n) => n.id)).toEqual(['a', 'b']);
    expect(list[0].ts).toBe(2);
  });
  it('keeps at most 200', () => {
    let list: NotificationItem[] = [];
    for (let i = 0; i < 210; i++) list = addToList(list, item(`n${i}`));
    expect(list).toHaveLength(NOTIFICATIONS_MAX);
    expect(list[0].id).toBe('n209');
  });
  it('a re-add of a resolved item clears resolved_at (the problem came back)', () => {
    let list: NotificationItem[] = [];
    list = addToList(list, { id: 'a', severity: 'error', message: 'a', ts: 1 });
    list = list.map((n) => (n.id === 'a' ? { ...n, resolved_at: 100 } : n));
    expect(isResolved(list[0])).toBe(true);
    list = addToList(list, { id: 'a', severity: 'error', message: 'a', ts: 2 });
    expect(isResolved(list[0])).toBe(false);
  });
});

describe('TASK-100 resolve state', () => {
  const live = (id: string, ts: number): NotificationItem => ({ id, severity: 'error', message: id, ts, read: false });
  const fixed = (id: string, ts: number, resolvedAt: number): NotificationItem => ({ ...live(id, ts), resolved_at: resolvedAt, read: true });

  it('isResolved is true only when resolved_at is a number', () => {
    expect(isResolved(live('a', 1))).toBe(false);
    expect(isResolved({ ...live('a', 1), resolved_at: null })).toBe(false);
    expect(isResolved(fixed('a', 1, 100))).toBe(true);
  });

  it('purgeOlderThan drops resolved items past the grace period', () => {
    const list = [fixed('a', 1, 100), fixed('b', 1, 1000), fixed('c', 1, 5000)];
    // now = 5000, grace 1000ms: 'a' is 4900ms past resolved (drop), 'b' is 4000ms past (drop), 'c' is 0ms past (keep)
    const kept = purgeOlderThan(list, 5000, 1000, Number.MAX_SAFE_INTEGER);
    expect(kept.map((n) => n.id)).toEqual(['c']);
  });

  it('purgeOlderThan drops anything older than the rolling window regardless of state', () => {
    // now = 10000, max_age 1500: ts >= 8500 keep, ts < 8500 drop. grace set to MAX so resolved_at never resolves.
    const list = [live('fresh-live', 9000), live('aged-live', 100), fixed('fresh-fixed', 9000, 9500), fixed('aged-fixed', 100, 200)];
    const kept = purgeOlderThan(list, 10000, Number.MAX_SAFE_INTEGER, 1500);
    expect(kept.map((n) => n.id).sort()).toEqual(['fresh-fixed', 'fresh-live']);
  });

  it('purgeOlderThan returns the same reference when nothing changes (no needless commits)', () => {
    const list = [live('a', 1)];
    expect(purgeOlderThan(list, 1, 1000, 10_000)).toBe(list);
  });

  it('sortForBell lists live before fixed, newest first inside each group', () => {
    const list = [fixed('old', 100, 200), live('new', 300), fixed('newer', 50, 250), live('oldest', 50)];
    const sorted = sortForBell(list);
    expect(sorted.map((n) => n.id)).toEqual(['new', 'oldest', 'newer', 'old']);
  });

  it('mergeHistory unions resolved_at from either side on the same ts', () => {
    const { merged } = mergeHistory(
      [{ id: 'a', severity: 'error', message: 'a', ts: 5, read: false, resolved_at: 7 }] as NotificationItem[],
      [{ id: 'a', severity: 'error', message: 'a', ts: 5, read: false, dismissed: false }] as never,
    );
    expect(merged[0].resolved_at).toBe(7);
    expect(merged[0].read).toBe(false);
  });

  it('mergeHistory preserves server resolve when local is older', () => {
    const local = [{ id: 'a', severity: 'error', message: 'a', ts: 3, read: false }] as NotificationItem[];
    const server = [{ id: 'a', severity: 'error', message: 'a', ts: 5, read: false, resolved_at: 8, dismissed: false }] as never;
    expect(mergeHistory(local, server).merged[0].resolved_at).toBe(8);
  });

  it('resolved grace and rolling window are public constants', () => {
    expect(RESOLVED_GRACE_MS).toBe(2 * 60 * 60 * 1000);
    expect(MAX_AGE_MS).toBe(48 * 60 * 60 * 1000);
  });
});

const row = (over: Partial<NotificationPrefRow>): NotificationPrefRow => ({
  scope_type: 'team', scope_id: 't', category: 'script', bell: true, toast: false, email: false, min_severity: 'info', ...over,
});
const failure = { category: 'script' as const, severity: 'error' as const, scope: { workspace_id: 'w1', project_id: 'p1' } };

describe('resolvePrefs', () => {
  it('uses the platform default without rows', () => {
    expect(resolvePrefs([], failure, 'u1')).toEqual({ bell: true, toast: false, email: false });
    expect(resolvePrefs([], { category: 'device', severity: 'error' }, 'u1').toast).toBe(true);
    expect(resolvePrefs([], { category: 'device', severity: 'warning' }, 'u1').toast).toBe(false);
  });
  it('most specific wins: user > project > workspace > team', () => {
    const rows = [
      row({ toast: false }),
      row({ scope_type: 'workspace', scope_id: 'w1', toast: true }),
      row({ scope_type: 'project', scope_id: 'p1', toast: false }),
      row({ scope_type: 'user', scope_id: 'u1', user_id: 'u1', toast: true }),
    ];
    expect(resolvePrefs(rows, failure, 'u1').toast).toBe(true);
    expect(resolvePrefs(rows.slice(0, 3), failure, 'u1').toast).toBe(false);
    expect(resolvePrefs(rows.slice(0, 2), failure, 'u1').toast).toBe(true);
  });
  it('skips rows of other scopes and other users', () => {
    const rows = [
      row({ scope_type: 'workspace', scope_id: 'w2', toast: true }),
      row({ scope_type: 'user', scope_id: 'u2', user_id: 'u2', bell: false }),
    ];
    expect(resolvePrefs(rows, failure, 'u1')).toEqual({ bell: true, toast: false, email: false });
  });
  it('a locked row cannot be overridden by a more specific one', () => {
    const rows = [row({ locked: true, bell: true }), row({ scope_type: 'user', scope_id: 'u1', user_id: 'u1', bell: false })];
    expect(resolvePrefs(rows, failure, 'u1').bell).toBe(true);
  });
  it('mute-until silences until the date', () => {
    const rows = [row({ scope_type: 'user', scope_id: 'u1', user_id: 'u1', muted_until: '2026-10-21T00:00:00Z' })];
    expect(resolvePrefs(rows, failure, 'u1', Date.parse('2026-10-20T00:00:00Z'))).toEqual({ bell: false, toast: false, email: false });
    expect(resolvePrefs(rows, failure, 'u1', Date.parse('2026-10-22T00:00:00Z')).bell).toBe(true);
  });
  it('min severity gates toast and email, not the bell', () => {
    const rows = [row({ min_severity: 'error', toast: true })];
    expect(resolvePrefs(rows, { ...failure, severity: 'warning' }, 'u1')).toEqual({ bell: true, toast: false, email: false });
    expect(resolvePrefs(rows, failure, 'u1').toast).toBe(true);
  });
  it('an action error always toasts but can leave the bell', () => {
    const rows = [row({ category: 'action', scope_type: 'user', scope_id: 'u1', user_id: 'u1', bell: false, toast: false })];
    expect(resolvePrefs(rows, { category: 'action', severity: 'error' }, 'u1')).toEqual({ bell: false, toast: true, email: false });
  });
});

describe('device scope', () => {
  const dev = { category: 'device' as const, severity: 'error' as const, scope: { device_id: 'd1' } };
  const mute = (over: Partial<NotificationPrefRow> = {}) =>
    row({ category: 'device', scope_type: 'device', scope_id: 'd1', user_id: 'u1', bell: false, toast: false, ...over });
  it('mutes only that device for that user', () => {
    const rows = [mute()];
    expect(resolvePrefs(rows, dev, 'u1')).toEqual({ bell: false, toast: false, email: false });
    expect(resolvePrefs(rows, { ...dev, scope: { device_id: 'd2' } }, 'u1').toast).toBe(true);
    expect(resolvePrefs(rows, dev, 'u2').toast).toBe(true);
    expect(resolvePrefs(rows, { category: 'device', severity: 'error' }, 'u1').toast).toBe(true);
  });
  it('order: user+device > user > shared device > project', () => {
    const user = row({ category: 'device', scope_type: 'user', scope_id: 'u1', user_id: 'u1', toast: true });
    const shared = row({ category: 'device', scope_type: 'device', scope_id: 'd1', toast: false });
    const project = row({ category: 'device', scope_type: 'project', scope_id: 'p1', toast: true });
    const n = { ...dev, scope: { device_id: 'd1', project_id: 'p1' } };
    expect(resolvePrefs([project, shared], n, 'u1').toast).toBe(false);
    expect(resolvePrefs([project, shared, user], n, 'u1').toast).toBe(true);
    expect(resolvePrefs([project, shared, user, mute()], n, 'u1').toast).toBe(false);
  });
  it('an admin lock still wins over a device mute', () => {
    const lock = row({ category: 'device', locked: true, toast: true });
    expect(resolvePrefs([lock, mute()], dev, 'u1').toast).toBe(true);
  });
});

describe('mergeHistory', () => {
  const it0 = (id: string, ts: number, over: Partial<NotificationItem> = {}): NotificationItem => ({ id, severity: 'error', message: id, ts, read: false, ...over });
  it('unions by id, newest ts wins, and pushes what the server lacks', () => {
    const { merged, push } = mergeHistory([it0('a', 5), it0('c', 9)], [it0('a', 3), it0('b', 7)]);
    expect(merged.map((n) => n.id)).toEqual(['c', 'b', 'a']);
    expect(merged.find((n) => n.id === 'a')?.ts).toBe(5);
    expect(push.map((n) => n.id).sort()).toEqual(['a', 'c']);
  });
  it('a server tombstone beats an older local copy, a newer local copy revives it', () => {
    expect(mergeHistory([it0('a', 3)], [{ ...it0('a', 4), dismissed: true }]).merged).toEqual([]);
    expect(mergeHistory([it0('a', 6)], [{ ...it0('a', 4), dismissed: true }]).merged.map((n) => n.id)).toEqual(['a']);
  });
  it('keeps read state set on either side for the same entry', () => {
    const { merged, push } = mergeHistory([it0('a', 3, { read: true })], [it0('a', 3)]);
    expect(merged[0].read).toBe(true);
    expect(push).toHaveLength(1);
  });
});

describe('inheritedRow', () => {
  it('falls back to the platform default, then to the next less specific row', () => {
    expect(inheritedRow([], 'capture', 'user', 'u1')).toMatchObject({ bell: true, toast: true, min_severity: 'warning' });
    const rows = [row({ category: 'capture', toast: false }), row({ category: 'capture', scope_type: 'workspace', scope_id: 'w2', toast: true })];
    expect(inheritedRow(rows, 'capture', 'user', 'u1').toast).toBe(false);
    expect(inheritedRow(rows, 'capture', 'workspace', 'w2').toast).toBe(false);
    expect(inheritedRow(rows, 'capture', 'project', 'p1').toast).toBe(false);
  });
});
