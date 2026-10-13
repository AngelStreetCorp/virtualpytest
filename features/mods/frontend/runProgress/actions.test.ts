import { describe, expect, it } from 'vitest';

import type { RunEvent } from '../../../../frontend/src/mods/core/types';

import { applyRunEvent, endsRun, initialRunProgressState, pruneRows, rowPercent, sortedRows, summarize } from './actions';
import { FINISHED_TTL_MS } from './constants';

const ev = (over: Partial<RunEvent> = {}): RunEvent => ({
  id: 'task-1',
  kind: 'script',
  status: 'running',
  timestamp: 1000,
  ...over,
});

describe('run progress actions', () => {
  it('adds a row on the first update and merges later ones', () => {
    let s = applyRunEvent(initialRunProgressState, ev({ hostName: 'pi1', deviceId: 'device1' }));
    s = applyRunEvent(s, ev({ stepNumber: 2, totalSteps: 4, step: 'zap', timestamp: 2000 }));
    const row = s.rows['task-1'];
    expect(row.hostName).toBe('pi1');
    expect(row.step).toBe('zap');
    expect(row.startedAt).toBe(1000);
    expect(rowPercent(row)).toBe(50);
  });

  it('ignores Take Control kinds', () => {
    expect(applyRunEvent(initialRunProgressState, ev({ kind: 'action' }))).toBe(initialRunProgressState);
  });

  it('marks the outcome and ignores updates after the end', () => {
    let s = applyRunEvent(initialRunProgressState, ev());
    expect(endsRun(s, ev({ status: 'failed' }))).toBe(true);
    s = applyRunEvent(s, ev({ status: 'failed', error: 'boom' }));
    expect(s.rows['task-1'].outcome).toBe('failed');
    expect(endsRun(s, ev({ status: 'completed' }))).toBe(false);
    expect(applyRunEvent(s, ev({ status: 'running' }))).toBe(s);
  });

  it('shows the band again when a new run starts after hiding', () => {
    const s = applyRunEvent({ ...applyRunEvent(initialRunProgressState, ev()), hidden: true }, ev({ id: 'task-2' }));
    expect(s.hidden).toBe(false);
  });

  it('summarizes, counting finished runs as 100%', () => {
    let s = applyRunEvent(initialRunProgressState, ev({ progress: 0 }));
    s = applyRunEvent(s, ev({ id: 'task-2', status: 'completed', timestamp: 500 }));
    const rows = sortedRows(s);
    expect(rows[0].id).toBe('task-1');
    expect(summarize(rows)).toEqual({ running: 1, passed: 1, failed: 0, total: 2, percent: 50 });
  });

  it('prunes finished rows past their TTL only', () => {
    let s = applyRunEvent(initialRunProgressState, ev());
    s = applyRunEvent(s, ev({ id: 'done', status: 'completed' }));
    const pruned = pruneRows(s, 1000 + FINISHED_TTL_MS);
    expect(Object.keys(pruned.rows)).toEqual(['task-1']);
  });
});
