// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { TrendChart } from './TrendChart';

afterEach(cleanup);

const bucket = (hour: number, total: number, passed: number) => ({ bucket_start: `2026-10-18T${String(hour).padStart(2, '0')}:00:00Z`, total, passed });

describe('TrendChart', () => {
  it('skips buckets without runs: the last label is the last bucket that has runs', () => {
    render(<TrendChart trend={[bucket(6, 10, 9), bucket(7, 10, 8), bucket(8, 0, 0), bucket(9, 0, 0)]} range="24h" />);
    expect(screen.getByTestId('trend-last').textContent).toBe('80 %');
    const poly = document.querySelector('polyline')!.getAttribute('points')!.split(' ');
    expect(poly).toHaveLength(2);
  });

  it('keeps the last-value label on one line', () => {
    render(<TrendChart trend={[bucket(6, 10, 9), bucket(7, 10, 0)]} range="24h" />);
    expect(screen.getByTestId('trend-last').ownerDocument.defaultView!.getComputedStyle(screen.getByTestId('trend-last')).whiteSpace).toBe('nowrap');
  });
});
