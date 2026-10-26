/**
 * The reports' outcome rule: a check that never ran (it was not configured) is
 * a skip, not a failure, and it stays visible as one (BUG-0756).
 *
 * The rule is pure, so it is tested without a browser, a backend or a run:
 * the payload is the only input.
 */
import { describe, expect, it } from 'vitest';

import { getResultOutcome, isSkippedResult } from '../../frontend/src/utils/resultOutcome';

describe('result outcome', () => {
  it('reads a success as a pass, whatever else the row carries', () => {
    expect(getResultOutcome({ success: true })).toBe('passed');
    expect(getResultOutcome({ success: true, skipped: true })).toBe('passed');
  });

  it('reads a row that carries the skip flag as skipped, not as failed', () => {
    expect(getResultOutcome({ success: false, skipped: true })).toBe('skipped');
  });

  it('decides the skip before the running heuristic', () => {
    // A skipped run did finish and wrote its row: a two-second span with no
    // duration is a finished skip, not a run that is still going.
    expect(
      getResultOutcome({
        success: false,
        skipped: true,
        started_at: '2026-10-24T10:00:00Z',
        completed_at: '2026-10-24T10:00:02Z',
        execution_time_ms: null,
      }),
    ).toBe('skipped');
  });

  it('keeps reading a row without the flag as a pass or a failure', () => {
    expect(
      getResultOutcome({
        success: false,
        started_at: '2026-10-24T10:00:00Z',
        completed_at: '2026-10-24T10:04:00Z',
        execution_time_ms: 240000,
      }),
    ).toBe('failed');
  });

  it('reads a short run that recorded no duration as still running', () => {
    expect(
      getResultOutcome({
        success: false,
        started_at: '2026-10-24T10:00:00Z',
        completed_at: '2026-10-24T10:00:02Z',
        execution_time_ms: null,
      }),
    ).toBe('running');
  });

  it('never guesses a skip from anything but the flag', () => {
    expect(isSkippedResult({ success: false })).toBe(false);
    expect(isSkippedResult({ success: false, skipped: false })).toBe(false);
    expect(isSkippedResult(null)).toBe(false);
    expect(isSkippedResult(undefined)).toBe(false);
  });
});
