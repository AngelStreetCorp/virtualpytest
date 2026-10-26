/**
 * Monitoring → AI usage (TASK-147): overview → group → call, three clicks at most, state in the URL.
 * A provider row opens its group with the short facts; Failed asks the server for failed calls only; a folded run
 * of identical failures opens one call with its repeat count.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchAiUsage: vi.fn(), fetchAiCalls: vi.fn(), fetchAiCall: vi.fn(), fetchBudget: vi.fn(), fetchBenchmarks: vi.fn(), fetchCredits: vi.fn() }));

vi.mock('../../frontend/src/components/aiUsage/api', async (importActual) => ({
  ...(await importActual<typeof import('../../frontend/src/components/aiUsage/api')>()),
  fetchAiUsage: api.fetchAiUsage,
  fetchAiCalls: api.fetchAiCalls,
  fetchAiCall: api.fetchAiCall,
  fetchBudget: api.fetchBudget,
  fetchBenchmarks: api.fetchBenchmarks,
  fetchCredits: api.fetchCredits,
}));

// UsageGroup and BudgetPanel read useProfile(), which needs an AuthProvider: a team admin, not a platform admin.
const who = vi.hoisted(() => ({ platformAdmin: false }));
vi.mock('../../frontend/src/hooks/auth/useProfile', () => ({
  useProfile: () => ({ profile: { id: 'u', team_id: 'a' }, loading: false, error: null, isPlatformAdmin: who.platformAdmin, refreshProfile: async () => {}, updateProfile: async () => {} }),
}));

import MonitoringAiUsage from '../../frontend/src/pages/MonitoringAiUsage';

const split = (calls: number, wasted = 0, cost = 0) => ({ calls, useful: calls - wasted, wasted, saved: 0, tokens: 0, tokens_useful: 0, tokens_wasted: 0, tokens_saved: 0, cost, cost_useful: cost, cost_wasted: 0, cost_saved: 0 });
const series = (n: number) => Array.from({ length: 24 }, (_, i) => (i === 10 ? n : 0));
const total = (calls: number, errors: number, cost: number) => ({ key: 'total', calls, errors, cost, series: series(calls), failed_series: series(errors), profiles: {}, last_error_ts: '2026-10-20T15:47:00Z' });
const base = {
  success: true, group_by: 'category', hours: 24, scope: 'team', source: 'calls', groups: [], can_view_all: true, restricted_to_self: false,
  series_start: '2026-10-19T23:00:00Z', step_s: 3600,
  totals: total(1000, 100, 2), rows: [], previous: { calls: 2000, errors: 0, cost: 4, priced_calls: 0, tokens_in: 0, tokens_out: 0 },
  providers: [
    { endpoint: 'openrouter', name: 'OpenRouter', status: 'degraded', calls: 600, errors: 90, reason: 'bad_request' },
    { endpoint: 'minimax', name: 'MiniMax', status: 'ok', calls: 400, errors: 10 },
  ],
  overview: {
    totals: split(1000, 100, 2),
    categories: [{ key: 'model_tests', ...split(500, 0, 0.1) }, { key: 'usage:agent.browser', ...split(100, 90, 0.7) }],
    callers: [], category_labels: { 'usage:agent.browser': 'Browser agent' },
  },
  options: { team: [{ key: 'a' }] },
};
const openrouter = {
  ...base, totals: { ...total(600, 90, 0.8), profiles: { 'o4-mini': 100 }, profile_errors: { 'o4-mini': 90 } }, rows: [{ ...total(600, 90, 0.8), key: 'model_tests', profiles: { jev: 500, 'o4-mini': 100 }, profile_labels: { jev: 'Jev 1.13', 'o4-mini': 'o4 Mini' }, profile_errors: { 'o4-mini': 90 } }],
  overview: { ...base.overview, totals: split(600, 90, 0.8), categories: [{ key: 'model_tests', ...split(500, 0, 0.1) }, { key: 'usage:agent.browser', ...split(100, 90, 0.7) }] },
};
const failedCall = (id: number, ts: string) => ({ id, ts, request_id: `r${id}`, usage_key: 'agent.browser', category: 'usage:agent.browser', model: 'o4-mini', endpoint: 'openrouter', ok: false, outcome: 'failed', error_type: 'bad_request', tokens_in: 0, tokens_out: 0, latency_ms: 80, cost: null, trace_url: null });

const renderPage = (qs = '') => render(<MemoryRouter initialEntries={[`/monitoring/ai-usage${qs}`]}><MonitoringAiUsage /></MemoryRouter>);

describe('AI usage: overview → group → call', () => {
  beforeEach(() => {
    window.scrollTo = vi.fn() as unknown as typeof window.scrollTo;
    api.fetchAiUsage.mockImplementation((q: { provider: string }) => Promise.resolve(q.provider === 'openrouter' ? openrouter : base));
    api.fetchAiCalls.mockResolvedValue({ success: true, calls: [failedCall(3, '2026-10-20T13:13:00Z'), failedCall(2, '2026-10-20T08:00:00Z'), failedCall(1, '2026-10-20T00:33:00Z')], sampled: 3, latency: { p50: 400, p95: 7000, n: 3 } });
    api.fetchAiCall.mockResolvedValue({ success: true, calls: [failedCall(3, '2026-10-20T13:13:00Z')], sampled: 1, latency: { p50: null, p95: null, n: 0 } });
    api.fetchBudget.mockResolvedValue({ success: true, team_id: 'a', buckets: [] });
    api.fetchCredits.mockResolvedValue({ success: true, endpoints: [{ endpoint: 'openrouter', has_key: true, balance: 74.47 }] });
    api.fetchBenchmarks.mockResolvedValue({ success: true, runs: [], cases: [], usage_keys: [], models: [], scope: 'team', team_id: null });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); who.platformAdmin = false; });

  it('answers spend, calls, failing now and wasted on the overview, one caption each', async () => {
    renderPage();
    expect(await screen.findByText('Failing now')).toBeInTheDocument();
    expect(screen.getAllByText('↓ 50 % vs previous')).toHaveLength(2);
    expect(screen.getByText('Wasted')).toBeInTheDocument();
    expect(screen.getByText('OpenRouter')).toBeInTheDocument();
    expect(screen.getByText('Model tests')).toBeInTheDocument();
  });

  it('marks a partly priced spend with ≥ and names the prompt-cache saving on hover', async () => {
    api.fetchAiUsage.mockResolvedValue({ ...base, totals: { ...base.totals, priced_calls: 400, cost_partial: true, cache_saved: 1.05 } });
    renderPage();
    expect(await screen.findByText('≥ $2.00')).toBeInTheDocument();
    expect(screen.getByTitle(/500 calls have no price · Prompt cache saved \$1\.05/)).toBeInTheDocument();
  });

  it('says "no price" when no call has one, and shows the provider credit on its page', async () => {
    who.platformAdmin = true; // credit is platform-admin data
    api.fetchAiUsage.mockImplementation((q: { provider: string }) => Promise.resolve(q.provider === 'openrouter'
      ? { ...openrouter, totals: { ...openrouter.totals, cost: null, priced_calls: 0 } } : base));
    renderPage('?provider=openrouter');
    expect(await screen.findByText('no price')).toBeInTheDocument();
    expect(await screen.findByTitle(/\$74\.47 credit left/)).toBeInTheDocument();
  });

  it('says so when the server has no AI usage API', async () => {
    const { AiUsageMissingError } = await import('../../frontend/src/components/aiUsage/api');
    api.fetchAiUsage.mockRejectedValue(new AiUsageMissingError('no AI usage API'));
    renderPage();
    expect(await screen.findByText('This server does not have AI usage yet.')).toBeInTheDocument();
  });

  it('shows "—" instead of failing when an older server leaves fields out', async () => {
    api.fetchAiUsage.mockResolvedValue({ ...base, totals: { key: 'total', calls: 5, errors: 0, cost: null }, previous: undefined, overview: undefined, providers: [] });
    renderPage();
    expect(await screen.findByText('Spend')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('opens a provider, filters its calls to failures, and opens a folded run as one call', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('OpenRouter'));
    expect(await screen.findByText('of calls')).toBeInTheDocument();
    expect(api.fetchAiUsage).toHaveBeenCalledWith(expect.objectContaining({ provider: 'openrouter' }), 'category');
    fireEvent.click(screen.getByRole('button', { name: /^Failed/ }));
    expect(api.fetchAiCalls).toHaveBeenCalledWith(expect.objectContaining({ provider: 'openrouter', result: 'failed' }), 200, false);
    fireEvent.click(await screen.findByText('3×'));
    expect(await screen.findByText(/^3× ·/)).toBeInTheDocument();
    expect(screen.getAllByText('Bad request').length).toBeGreaterThan(0);
    expect(await screen.findByText(/OpenRouter rejects the request/)).toBeInTheDocument();
    expect(api.fetchAiCall).toHaveBeenCalledWith(expect.anything(), 'r3');
  });
});

describe('30-day incident marker', () => {
  it('names a run of days that are almost all failures at many times the usual volume', async () => {
    const { incidentSlots } = await import('../../frontend/src/components/aiUsage/UsageOverview');
    const calls = [2000, 2100, 70000, 228000, 181000, 1900, 2200];
    const failed = [10, 20, 69000, 228000, 181000, 15, 9];
    expect(incidentSlots(calls, failed)).toEqual([2, 3, 4]);
    expect(incidentSlots([100, 120, 110], [1, 2, 3])).toEqual([]);
  });
});
