/**
 * The outcome of a finished run, as the reports UI shows it.
 *
 * `success` alone cannot tell a failed check from a check that never ran. A
 * check that was never configured (no account, no parameters) writes the same
 * `success = false` as a broken one, so the reports read it as a red failure
 * for a check that never looked at anything.
 *
 * Such a run carries the `skipped` flag on its row: the run recorded the
 * outcome it gave itself (BUG-0756), and the flag is the only authority. It
 * has to be visible as a skip, never as a failure — a nightly campaign that
 * shows "FAIL" for a check it never ran reports a defect that does not exist.
 *
 * The flag is read, never guessed: a row without it keeps the old behaviour
 * (pass / fail), so a payload that predates the flag is not reinterpreted.
 */

/** What a run row means, once the skip is told apart from the failure. */
export type ResultOutcome = 'passed' | 'failed' | 'skipped' | 'running';

export interface OutcomeRow {
  success?: boolean;
  skipped?: boolean;
  started_at?: string | null;
  completed_at?: string | null;
  execution_time_ms?: number | null;
}

/**
 * A row that says it never ran.
 *
 * Only the flag says so — never the script name, never the error text: a
 * check that was configured and then failed is a failure, not a skip.
 */
export const isSkippedResult = (row: OutcomeRow | null | undefined): boolean =>
  row?.skipped === true;

/**
 * A run that has not finished yet: it started, it ended its row within a few
 * seconds, and it recorded no duration. The row is written at the end of the
 * run, so a missing duration next to a tiny span means the run is still going.
 */
const looksStillRunning = (row: OutcomeRow): boolean => {
  const start = new Date(row.started_at ?? '').getTime();
  const end = new Date(row.completed_at ?? '').getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return false;
  return Math.abs(end - start) < 5000 && !row.execution_time_ms;
};

/**
 * The outcome of one run row.
 *
 * A success is a pass, whatever the row says. A skip is decided before the
 * running heuristic: a skipped run *did* finish and write its row, and a short
 * run would otherwise be read as still running.
 */
export const getResultOutcome = (row: OutcomeRow | null | undefined): ResultOutcome => {
  if (!row) return 'failed';
  if (row.success) return 'passed';
  if (isSkippedResult(row)) return 'skipped';
  if (looksStillRunning(row)) return 'running';
  return 'failed';
};
