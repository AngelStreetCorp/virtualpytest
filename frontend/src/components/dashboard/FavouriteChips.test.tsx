// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { fitCount, FavouriteChips, type FavouriteChip } from './FavouriteChips';

afterEach(cleanup);

const chips: FavouriteChip[] = Array.from({ length: 5 }, (_, i) => ({ key: `k${i}`, label: `device${i}`, tone: 'success', word: 'ok' }));

describe('fitCount', () => {
  it('shows everything when it fits on the line', () => {
    expect(fitCount([100, 100, 100], 400)).toBe(3);
  });
  it('keeps room for the +N badge when it does not', () => {
    expect(fitCount([100, 100, 100, 100], 250)).toBe(1);
    expect(fitCount([100, 100, 100, 100], 330)).toBe(2);
  });
  it('can collapse everything into the badge', () => {
    expect(fitCount([300, 300], 100)).toBe(0);
  });
});

describe('FavouriteChips', () => {
  it('stays on one line and collapses the rest into +N that opens a list', () => {
    const w = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
    const c = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 100 });
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 330 });
    try {
      render(<MemoryRouter><FavouriteChips chips={chips} /></MemoryRouter>);
      const line = screen.getByTestId('favourite-chips').firstElementChild as HTMLElement;
      expect(getComputedStyle(line).flexWrap).toBe('nowrap');
      expect(line.querySelectorAll('[data-testid="favourite-chip"]')).toHaveLength(2);
      const badge = screen.getByTestId('favourite-more');
      expect(badge.textContent).toBe('+3');
      fireEvent.click(badge);
      expect(screen.getByTestId('favourite-more-list').querySelectorAll('[data-testid="favourite-chip"]')).toHaveLength(3);
    } finally {
      if (w) Object.defineProperty(HTMLElement.prototype, 'offsetWidth', w);
      if (c) Object.defineProperty(HTMLElement.prototype, 'clientWidth', c);
    }
  });
  it('shows all chips and no badge when there is room (or no layout, as in jsdom)', () => {
    render(<MemoryRouter><FavouriteChips chips={chips} /></MemoryRouter>);
    expect(screen.queryByTestId('favourite-more')).toBeNull();
  });
});
