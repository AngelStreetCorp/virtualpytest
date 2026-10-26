// @vitest-environment jsdom
/**
 * A KPI tile shows two numbers: the value and the figure after it (BUG-0816).
 *
 * Without a separator between them the tile reads "1915%" — the count and the rate as one
 * number — and the same happens on every page that uses a stat tile with an extra.
 */
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

import { StatTiles } from '../../frontend/src/components/common/PageChrome';

describe('a stat tile with a second figure (BUG-0816)', () => {
  it('separates the value from the figure after it', () => {
    const { container } = render(
      <StatTiles tiles={[{ label: 'Covered', value: '19', extra: '15%' }]} />,
    );
    const text = (container.textContent ?? '').replace(/\s+/g, ' ');
    expect(text).toContain('19 · 15%');
  });

  it('keeps a tile without a second figure untouched', () => {
    const { container } = render(<StatTiles tiles={[{ label: 'Requirements', value: '131' }]} />);
    const text = (container.textContent ?? '').replace(/\s+/g, ' ');
    expect(text).toContain('131');
    expect(text).not.toContain('·');
  });
});
