/**
 * Monitoring → AI usage (TASK-87 round 2, R14): one frontend bundle talks to servers on older code.
 * A response without the newer fields (previous, overview, options, errors, failed_series) must render with "—"
 * instead of crashing, and a server without the AI usage API must say so.
 */
import { cleanup, render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fetchAiUsage: vi.fn(), fetchAiCalls: vi.fn(), fetchTrainingReport: vi.fn(), fetchBudget: vi.fn() }));

vi.mock('../../frontend/src/components/aiUsage/api', async (importActual) => ({
  ...(await importActual<typeof import('../../frontend/src/components/aiUsage/api')>()),
  fetchAiUsage: api.fetchAiUsage,
  fetchAiCalls: api.fetchAiCalls,
  fetchTrainingReport: api.fetchTrainingReport,
  fetchBudget: api.fetchBudget,
}));

import { AiUsageMissingError } from '../../frontend/src/components/aiUsage/api';
import MonitoringAiUsage from '../../frontend/src/pages/MonitoringAiUsage';

const oldRow = { key: 'vision.banner', calls: 10, errors: 1, error_rate: 0.1, tokens_in: 100, tokens_out: 10, cost: null, profiles: { gpu: 10 } };
// What a round-1 server answers: no previous, overview, options, errors, failed_series, series_len.
const oldServerReport = {
  success: true, group_by: 'category_caller', hours: 24, scope: 'team', source: 'calls', groups: ['usage', 'category_caller'],
  can_view_all: false, restricted_to_self: false, totals: { ...oldRow, key: 'total' }, rows: [oldRow],
  providers: [{ endpoint: 'lab', name: 'Lab', type: 'local', status: 'ok', enabled: true, calls: 10, errors: 1 }],
};

const renderPage = (tab = '') => render(<MemoryRouter initialEntries={[`/monitoring/ai-usage${tab}`]}><MonitoringAiUsage /></MemoryRouter>);

describe('AI usage page against an older server', () => {
  beforeEach(() => api.fetchBudget.mockResolvedValue({ success: true, spent: 0, forecast: 0, budget: null }));
  afterEach(cleanup);

  it('renders the Overview with "—" for the fields the server does not send', async () => {
    api.fetchAiUsage.mockResolvedValue(oldServerReport);
    renderPage();
    expect(await screen.findByText('Where the AI goes')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.queryByText(/errors?$/)).not.toBeInTheDocument(); // no badge without error causes
  });

  it.each(['?tab=usage', '?tab=errors', '?tab=providers'])('renders tab %s without the new fields', async (tab) => {
    api.fetchAiUsage.mockResolvedValue(oldServerReport);
    renderPage(tab);
    expect(await screen.findByRole('tablist')).toBeInTheDocument();
  });

  it('says so when the server has no AI usage API', async () => {
    api.fetchAiUsage.mockRejectedValue(new AiUsageMissingError('no api'));
    renderPage();
    expect(await screen.findByText('This server does not have AI usage yet.')).toBeInTheDocument();
  });
});

describe('AI usage page against a current server', () => {
  beforeEach(() => api.fetchBudget.mockResolvedValue({ success: true, spent: 0, forecast: 0, budget: null }));
  afterEach(cleanup);

  it('shows the errors badge, the categories and the callers', async () => {
    const split = { calls: 10, useful: 8, wasted: 2, saved: 0, tokens: 100, tokens_useful: 80, tokens_wasted: 20, tokens_saved: 0, cost: null, cost_useful: null, cost_wasted: null, cost_saved: null };
    api.fetchAiUsage.mockResolvedValue({
      ...oldServerReport, previous: { calls: 5, errors: 0, cost: null, priced_calls: 0, tokens_in: 1, tokens_out: 1 },
      overview: { totals: split, categories: [{ key: 'discard_script', ...split }], callers: [{ key: 'agent:sherlock', ...split, categories: { discard_script: 10 } }] },
      errors: { count: 1, causes: [{ endpoint: 'or', provider: 'OpenRouter', type: 'cloud', preset: 'openrouter', reason: 'no_credit', severity: 'error', errors: 2, since: '2026-10-13T08:00:00Z', last: '2026-10-13T08:51:00Z', skipped: 0, categories: ['discard_script'], features: [] }] },
    });
    renderPage();
    expect(await screen.findByText('1 error')).toBeInTheDocument();
    expect((await screen.findAllByText('Discard script')).length).toBeGreaterThan(0);
    expect(screen.getByText('Sherlock')).toBeInTheDocument();
  });
});
