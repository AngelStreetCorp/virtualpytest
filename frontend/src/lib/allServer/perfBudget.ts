/**
 * TASK-113 — PR-F: the perf budget placeholder.
 *
 * The actual budget is set after the single-server baseline is
 * measured (test plan §"Performance budget"). Until that baseline
 * exists, every value here is `Infinity` — the helpers are
 * no-ops that pass whatever they see.
 *
 * The helper exists so the rest of the code can call it as a
 * contract; once the baseline lands, the constants are filled in
 * and the assertions become real.
 */
import { useEffect, useRef } from 'react';

export interface PerfBudget {
  /** Aggregate list p95 latency in ms, per server count. */
  listP95MsByServerCount: Record<number, number>;
  /** Initial render in ms, per server count. */
  initialRenderMsByServerCount: Record<number, number>;
  /** Active WebSockets allowed per session, per server count. */
  activeSocketsByServerCount: Record<number, number>;
  /** Stream bandwidth in Mb/s, per server count. */
  streamBandwidthByServerCount: Record<number, number>;
  /** Unhandled rejections per page-load, per server count. */
  unhandledRejectionsByServerCount: Record<number, number>;
}

/**
 * The placeholder budget. The keys are server counts; the values
 * are deliberately Infinity so an unset budget never trips an
 * assertion. Once the baseline is measured, replace these with
 * the real numbers (e.g. `{ 1: 250, 2: 375, 5: 750 }`).
 */
export const PERF_BUDGET: PerfBudget = {
  listP95MsByServerCount: { 1: Infinity, 2: Infinity, 5: Infinity },
  initialRenderMsByServerCount: { 1: Infinity, 2: Infinity, 5: Infinity },
  activeSocketsByServerCount: { 1: Infinity, 2: Infinity, 5: Infinity },
  streamBandwidthByServerCount: { 1: Infinity, 2: Infinity, 5: Infinity },
  unhandledRejectionsByServerCount: { 1: Infinity, 2: Infinity, 5: Infinity },
};

/** Look up the budget for a server count (falls back to Infinity). */
export const budgetFor = <K extends keyof PerfBudget>(
  category: K,
  serverCount: number,
): number => {
  const table = PERF_BUDGET[category];
  return table[serverCount] ?? Infinity;
};

/** Assert that a metric value fits the budget. Always passes with the placeholder. */
export const withinBudget = (
  category: keyof PerfBudget,
  serverCount: number,
  value: number,
): { ok: true; headroom: number } | { ok: false; overBy: number; budget: number } => {
  const budget = budgetFor(category, serverCount);
  if (value <= budget) return { ok: true, headroom: budget - value };
  return { ok: false, overBy: value - budget, budget };
};

/**
 * Tiny dev hook: logs a one-line summary of a metric against the
 * budget. Replace with a real telemetry call once the baseline is
 * measured.
 */
export const usePerfProbe = (
  category: keyof PerfBudget,
  serverCount: number,
  value: number,
): void => {
  const result = withinBudget(category, serverCount, value);
  const ref = useRef(result);
  ref.current = result;
  useEffect(() => {
    console.debug(
      `[perf] ${category} @ ${serverCount} servers: ${value} (${result.ok ? 'within budget' : `OVER budget by ${result.overBy}`})`,
    );
  }, [category, serverCount, value, result]);
};
