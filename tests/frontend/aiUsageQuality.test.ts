import { describe, expect, it } from 'vitest';

import type { BenchmarkRun } from '../../frontend/src/components/aiUsage/api';
import { featureQuality, profileQuality } from '../../frontend/src/components/aiUsage/quality';

const run = (o: Partial<BenchmarkRun>): BenchmarkRun => ({
  run_id: 'r', ts: '2026-10-01T10:00:00Z', team_id: null, uc: 'k', usage_key: 'k', category: 'cat', profile: 'p', model: null, endpoint: null,
  cases: 10, scored: 10, passed: 5, score: 0.5, pass_rate: 0.5, ms: 0, tokens_in: 0, tokens_out: 0, cost: 0, ...o,
});

describe('profileQuality', () => {
  it('the latest run of a profile on a usage key wins', () => {
    const q = profileQuality([run({ ts: '2026-10-01T10:00:00Z', passed: 2 }), run({ ts: '2026-10-05T10:00:00Z', passed: 9 })]);
    expect(q.get('p')).toMatchObject({ passed: 9, scored: 10, ts: '2026-10-05T10:00:00Z' });
  });

  it('sums the latest run of each usage key, and ignores runs with no scored case', () => {
    const q = profileQuality([run({ usage_key: 'a', passed: 4 }), run({ usage_key: 'b', passed: 8, scored: 10 }), run({ usage_key: 'c', scored: 0, passed: 0 })]);
    expect(q.get('p')).toMatchObject({ passed: 12, scored: 20, rate: 0.6 });
  });

  it('keeps one feature only, and a profile with no run is absent', () => {
    const q = profileQuality([run({ category: 'x', profile: 'p' }), run({ category: 'y', profile: 'other' })], 'x');
    expect(q.has('p')).toBe(true);
    expect(q.has('other')).toBe(false);
    expect(q.get('nobody') ?? null).toBeNull();
  });
});

describe('featureQuality', () => {
  it('weights the pass rate of each profile by its calls; profiles with no run do not count', () => {
    const q = profileQuality([run({ profile: 'a', passed: 10 }), run({ profile: 'b', passed: 0 })]);
    expect(featureQuality({ a: 30, b: 10, none: 1000 }, q)).toBeCloseTo(0.75);
    expect(featureQuality({ none: 5 }, q)).toBeNull();
  });
});
