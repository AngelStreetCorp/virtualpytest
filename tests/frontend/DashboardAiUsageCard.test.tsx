import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { CustomThemeProvider } from '../../frontend/src/contexts/ThemeContext';
import { systemCards } from '../../frontend/src/components/dashboard/cards/systemCards';
import { fmtCost } from '../../frontend/src/components/aiUsage/format';
import { setLanguage } from '../../frontend/src/i18n';
import type { DashboardData } from '../../frontend/src/components/dashboard/dashboardTypes';

const aiUsageCard = systemCards.find((c) => c.id === 'ai-usage');
const Body = aiUsageCard?.Component;

const dataWith = (cost_7d: number): DashboardData =>
  ({
    system: { ai_usage: { cost_7d, top_model: 'claude' } },
    summary: null,
    summaryError: false,
    systemError: false,
    loading: false,
  }) as unknown as DashboardData;

const renderBody = (cost_7d: number) =>
  render(
    <CustomThemeProvider>
      <MemoryRouter>
        <Body data={dataWith(cost_7d)} range={'7d' as never} now={0} />
      </MemoryRouter>
    </CustomThemeProvider>,
  );

/**
 * BUG-0784: the dashboard's "AI usage" tile formatted the money by hand
 * (`$${formatNumber(cost)}`), and a bare formatNumber prints three decimals —
 * $22.039 — which a German reader parses as twenty-two thousand.
 */
describe('the dashboard AI usage tile prints money as money', () => {
  it('prints the 7-day spend with two decimals, not three', () => {
    renderBody(22.039);
    expect(screen.getByText('$22.04')).toBeInTheDocument();
    expect(screen.queryByText('$22.039')).not.toBeInTheDocument();
  });

  it('rounds a sub-dollar spend to two decimals too', () => {
    renderBody(0.4567);
    expect(screen.getByText('$0.46')).toBeInTheDocument();
  });

  it('keeps a whole spend whole', () => {
    renderBody(1200);
    expect(screen.getByText('$1,200')).toBeInTheDocument();
  });

  /**
   * The German rendering is the part that was a 1000x error: "$22,039" reads as
   * twenty-two thousand, not twenty-two dollars and thirty-nine cents.
   */
  it('prints two decimals in German too, not three', async () => {
    await setLanguage('de');
    try {
      renderBody(22.039);
      expect(screen.getByText('$22,04')).toBeInTheDocument();
      expect(screen.queryByText('$22,039')).not.toBeInTheDocument();
    } finally {
      await setLanguage('en');
    }
  });
});

afterEach(async () => {
  await setLanguage('en');
});

describe('fmtCost', () => {
  it('rounds to two decimals', () => {
    expect(fmtCost(22.039)).toBe('$22.04');
    expect(fmtCost(0.4567)).toBe('$0.46');
  });

  it('keeps a sub-cent amount readable instead of rounding it to zero', () => {
    expect(fmtCost(0.00004)).toBe('$0.00004');
  });

  it('prints no decimals for a whole amount of ten or more', () => {
    expect(fmtCost(1200)).toBe('$1,200');
  });

  it('says nothing for a missing value', () => {
    expect(fmtCost(null)).toBeNull();
  });
});
