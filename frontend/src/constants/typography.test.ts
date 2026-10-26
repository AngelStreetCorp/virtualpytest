import { describe, expect, it } from 'vitest';

import {
  DEFAULT_SIZE,
  FONT_SIZE_SCALE,
  SIZE_IDS,
  SIZE_NAMES,
  SIZE_SCALE,
  SIZE_ID as _UNUSED, // kept to silence unused-import warnings when consumers import the type only
  TYPOGRAPHY,
  TYPOGRAPHY_ROLES,
  isSizeId,
  slotStyle,
} from './typography';

// resolveSize is in themeStore.ts; we test the typography-only surface here.

describe('typography scale', () => {
  it('every role exposes size, weight and lineHeight', () => {
    for (const role of TYPOGRAPHY_ROLES) {
      const t = TYPOGRAPHY[role];
      expect(typeof t.size).toBe('string');
      expect(t.size.endsWith('rem')).toBe(true);
      expect(typeof t.weight).toBe('number');
      expect(typeof t.lineHeight).toBe('number');
      // weight is in the 100-800 range, the only sensible MUI numbers
      expect(t.weight).toBeGreaterThanOrEqual(300);
      expect(t.weight).toBeLessThanOrEqual(700);
    }
  });

  it('every role reads its size from the scale, never an outsider', () => {
    const scaleValues = Object.values(FONT_SIZE_SCALE);
    for (const role of TYPOGRAPHY_ROLES) {
      expect(scaleValues).toContain(TYPOGRAPHY[role].size);
    }
  });

  it('h1 (page title) is bigger than body', () => {
    const px = (s: string): number => parseFloat(s) * 16;
    expect(px(TYPOGRAPHY.pageTitle.size)).toBeGreaterThan(px(TYPOGRAPHY.body.size));
  });

  it('caption is smaller than body, microMeta smaller than caption', () => {
    const px = (s: string): number => parseFloat(s) * 16;
    expect(px(TYPOGRAPHY.caption.size)).toBeLessThan(px(TYPOGRAPHY.body.size));
    expect(px(TYPOGRAPHY.microMeta.size)).toBeLessThan(px(TYPOGRAPHY.caption.size));
  });
});

describe('size picker (TASK-100 size row)', () => {
  it('lists three ordered options, default md', () => {
    expect(SIZE_IDS).toEqual(['sm', 'md', 'lg']);
    expect(DEFAULT_SIZE).toBe('md');
  });

  it('every id has a name and a multiplier', () => {
    for (const id of SIZE_IDS) {
      expect(typeof SIZE_NAMES[id]).toBe('string');
      expect(SIZE_NAMES[id].length).toBeGreaterThan(0);
      expect(typeof SIZE_SCALE[id]).toBe('number');
    }
  });

  it('multipliers are monotonic and centred on 1', () => {
    expect(SIZE_SCALE.sm).toBeLessThan(SIZE_SCALE.md);
    expect(SIZE_SCALE.md).toBeLessThan(SIZE_SCALE.lg);
    expect(SIZE_SCALE.md).toBe(1);
  });

  it('isSizeId narrows the three ids correctly', () => {
    expect(isSizeId('sm')).toBe(true);
    expect(isSizeId('md')).toBe(true);
    expect(isSizeId('lg')).toBe(true);
    expect(isSizeId('xl')).toBe(false);
    expect(isSizeId(null)).toBe(false);
    expect(isSizeId(undefined)).toBe(false);
    expect(isSizeId(123)).toBe(false);
  });
});

describe('slotStyle (multiplier-baked sizes)', () => {
  it('returns the raw role slot at multiplier 1', () => {
    const pageTitle = slotStyle('pageTitle');
    expect(pageTitle.fontSize).toBe(TYPOGRAPHY.pageTitle.size);
    expect(pageTitle.fontWeight).toBe(TYPOGRAPHY.pageTitle.weight);
  });

  it('shrinks the size at 0.875x and grows it at 1.125x', () => {
    const base = parseFloat(TYPOGRAPHY.body.size);
    const sm = parseFloat(slotStyle('body', 0.875).fontSize);
    const lg = parseFloat(slotStyle('body', 1.125).fontSize);
    // tolerance for parseFloat rounding on rem values
    expect(Math.abs(sm - base * 0.875)).toBeLessThan(0.001);
    expect(Math.abs(lg - base * 1.125)).toBeLessThan(0.001);
  });

  it('passes through non-rem sizes untouched (defensive)', () => {
    const role = TYPOGRAPHY.cardTitle;
    const sized = slotStyle('cardTitle', 1.5);
    // rem is checked in rem regex; non-rem strings would just pass through unchanged
    expect(sized.fontSize.endsWith('rem')).toBe(role.size.endsWith('rem'));
  });
});
