/**
 * Model quality next to cost (TASK-147 F5): the pass rate a routing profile scored in the benchmarks, joined to the
 * profiles production used. The join key is the routing profile (`run.profile` == key of `row.profiles`).
 */
import type { BenchmarkRun } from './api';

export interface Quality {
  passed: number;
  scored: number;
  /** 0..1 */
  rate: number;
  /** Timestamp of the newest run counted. */
  ts: string | null;
}

/** Newest run of each profile on each usage key (one test of one key, not a history), runs with no scored case dropped. */
export const latestRuns = (runs: BenchmarkRun[], category?: string): BenchmarkRun[] => {
  const latest = new Map<string, BenchmarkRun>();
  runs.forEach((r) => {
    if (!r.scored || !r.profile || (category && r.category !== category)) return;
    const id = `${r.profile}\u0000${r.usage_key}`;
    const cur = latest.get(id);
    if (!cur || String(r.ts ?? '') > String(cur.ts ?? '')) latest.set(id, r);
  });
  return [...latest.values()];
};

/** Per profile: passed / scored summed over its latest run on each usage key. A profile with no run is absent. */
export const profileQuality = (runs: BenchmarkRun[], category?: string): Map<string, Quality> => {
  const out = new Map<string, Quality>();
  latestRuns(runs, category).forEach((r) => {
    const q = out.get(r.profile) ?? { passed: 0, scored: 0, rate: 0, ts: null };
    q.passed += r.passed;
    q.scored += r.scored;
    if (r.ts && (!q.ts || r.ts > q.ts)) q.ts = r.ts;
    q.rate = q.scored ? q.passed / q.scored : 0;
    out.set(r.profile, q);
  });
  return out;
};

/** Call-weighted pass rate of the profiles a feature used; profiles with no benchmark do not count. null: none has one. */
export const featureQuality = (calls: Record<string, number> | undefined, quality: Map<string, Quality>): number | null => {
  let weight = 0;
  let sum = 0;
  Object.entries(calls ?? {}).forEach(([profile, n]) => {
    const q = quality.get(profile);
    if (!q || n <= 0) return;
    weight += n;
    sum += n * q.rate;
  });
  return weight ? sum / weight : null;
};
