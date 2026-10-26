import { describe, expect, it } from 'vitest';

import {
  collectAbortableRunningExecutions,
  type ExecutionRecord,
} from '../../frontend/src/utils/executionHistoryRecords';

/**
 * QA-OPS-20 — after a reload the Run page's Abort button was greyed out
 * although the page's own Last Executions table still showed the run as
 * running.
 *
 * The button read only the runs this browser session had started; the table
 * reads the server as well. The helper below is what both now share.
 */

const record = (overrides: Partial<ExecutionRecord> = {}): ExecutionRecord => ({
  id: 'exec-1',
  executionType: 'script',
  scriptName: 'av_check',
  hostName: 'labox-backend',
  deviceId: 'host',
  startTime: '13:54',
  status: 'running',
  ...overrides,
});

describe('collectAbortableRunningExecutions', () => {
  it('finds nothing when neither list has a running execution', () => {
    const finished = record({ status: 'completed' });
    expect(collectAbortableRunningExecutions([finished], [finished])).toEqual([]);
  });

  it('returns a run the server still reports as running, even with an empty local list', () => {
    // The reload case: this browser started nothing, the table shows the run.
    const serverRow = record({ id: 'from-server' });
    expect(collectAbortableRunningExecutions([], [serverRow])).toEqual([serverRow]);
  });

  it('returns a run this session started', () => {
    const local = record({ id: 'from-local' });
    expect(collectAbortableRunningExecutions([local], [])).toEqual([local]);
  });

  it('lists a target once when the local list and the server both carry it', () => {
    const local = record({ id: 'from-local' });
    const server = record({ id: 'from-server' });
    const merged = collectAbortableRunningExecutions([local], [server]);
    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe('from-local');
  });

  it('leaves campaign runs out — they keep the row-level stop button', () => {
    const campaign = record({ executionType: 'campaign' });
    expect(collectAbortableRunningExecutions([campaign], [campaign])).toEqual([]);
  });

  it('ignores a queued execution — it is not running yet', () => {
    const queued = record({ status: 'queued' });
    expect(collectAbortableRunningExecutions([queued], [queued])).toEqual([]);
  });
});
