import { describe, expect, it } from 'vitest';

import { contrastWarnings, GOLD_DARK, GOLD_LIGHT, GOLD_THEME, contrast, derivePalettes, parseTheme } from './themeEngine';

describe('theme engine', () => {
  it('derives gold to exactly the built-in dark and light palettes', () => {
    const p = derivePalettes(GOLD_THEME);
    expect(p.dark).toEqual(GOLD_DARK);
    expect(p.light).toEqual(GOLD_LIGHT);
  });

  it('fills every palette key for any accent and tone', () => {
    for (const accent of ['#3b82f6', '#d6283a', '#ffff00', '#101010']) {
      for (const tone of ['neutral', 'warm', 'cool'] as const) {
        const p = derivePalettes({ accent, tone });
        expect(Object.keys(p.dark).sort()).toEqual(Object.keys(GOLD_DARK).sort());
        expect(Object.keys(p.light).sort()).toEqual(Object.keys(GOLD_DARK).sort());
      }
    }
  });

  it('keeps light-mode accent text readable on white (>= 4.5:1), even for pale accents', () => {
    for (const accent of ['#ffff00', '#f5d000', '#d4a574', '#3b82f6', '#ffffff']) {
      const p = derivePalettes({ accent, tone: 'neutral' });
      expect(contrast(p.light.accentText, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('never themes status colours, and exact overrides win elsewhere', () => {
    const p = derivePalettes({ accent: '#3b82f6', tone: 'cool', dark: { error: '#000000', background: '#010203' } });
    expect(p.dark.error).toBe(GOLD_DARK.error);
    expect(p.dark.background).toBe('#010203');
  });

  it('rejects malformed theme objects', () => {
    expect(parseTheme({ id: 'a', name: 'A', accent: 'red', tone: 'warm' })).toBeNull();
    expect(parseTheme({ id: 'a', name: 'A', accent: '#aabbcc', tone: 'hot' })).toBeNull();
    expect(parseTheme({ id: 'a', name: 'A', accent: '#aabbcc', tone: 'warm' })?.id).toBe('a');
  });
});

describe('background colour and tones', () => {
  it('derives a pale blue light page from a blue background, tone ignored', () => {
    const p = derivePalettes({ accent: '#7376d4', tone: 'warm', background: '#1a2744' });
    expect(p.dark.background).toBe('#1a2744');
    expect(p.dark.surface).not.toBe(p.dark.background);
    const [r, , b] = [1, 3, 5].map((i) => parseInt(p.light.background.slice(i, i + 2), 16));
    expect(b - r).toBeGreaterThanOrEqual(10);
  });

  it('tones are visibly different in light mode', () => {
    const spread = (hex: string) => {
      const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      return Math.max(...c) - Math.min(...c);
    };
    const l = (tone: 'neutral' | 'warm' | 'cool') => derivePalettes({ accent: '#7376d4', tone }).light.background;
    expect(spread(l('neutral'))).toBe(0);
    expect(spread(l('cool'))).toBeGreaterThanOrEqual(10);
    expect(spread(l('warm'))).toBeGreaterThanOrEqual(10);
  });

  it('only warns on real failures', () => {
    expect(contrastWarnings(derivePalettes({ accent: '#7376d4', tone: 'cool' }))).toEqual([]);
    expect(contrastWarnings(derivePalettes({ accent: '#d6283a', tone: 'neutral' }))).toEqual([]);
  });

  it('warns on a pale accent that vanishes on a light page', () => {
    expect(contrastWarnings(derivePalettes({ accent: '#ffff66', tone: 'neutral' }))).toContain('accent');
  });

  it('parses an optional background', () => {
    expect(parseTheme({ id: 'a', name: 'A', accent: '#aabbcc', tone: 'warm', background: '#102030' })?.background).toBe('#102030');
    expect(parseTheme({ id: 'a', name: 'A', accent: '#aabbcc', tone: 'warm', background: 'blue' })?.background).toBeUndefined();
  });
});

describe('button role tokens', () => {
  it('gold selectedText equals gold accentText in dark and light', () => {
    const p = derivePalettes(GOLD_THEME);
    expect(p.dark.selectedText).toBe(p.dark.accentText);
    expect(p.light.selectedText).toBe(p.light.accentText);
  });

  it('derives selectedText = accentText for a custom accent', () => {
    const p = derivePalettes({ accent: '#3b82f6', tone: 'cool' });
    expect(p.dark.selectedText).toBe(p.dark.accentText);
    expect(p.light.selectedText).toBe(p.light.accentText);
    expect(p.dark.dangerText).toBe(p.dark.error);
  });

  it('roles.selected recolours only the selected tokens', () => {
    const base = derivePalettes({ accent: '#3b82f6', tone: 'cool' });
    const withRole = derivePalettes({ accent: '#3b82f6', tone: 'cool', roles: { selected: '#22aa88' } });
    const sel = ['selectedBg', 'selectedBorder', 'selectedText'];
    for (const m of ['dark', 'light'] as const) {
      for (const k of Object.keys(base[m]) as (keyof typeof base.dark)[]) {
        if (sel.includes(k)) expect(withRole[m][k]).not.toEqual(base[m][k]);
        else expect(withRole[m][k]).toEqual(base[m][k]);
      }
    }
  });

  it('parseTheme keeps a valid roles.selected and drops an invalid one', () => {
    const t = { id: 'x', name: 'X', accent: '#112233', tone: 'neutral' };
    expect(parseTheme({ ...t, roles: { selected: '#AABBCC' } })?.roles).toEqual({ selected: '#aabbcc' });
    expect(parseTheme({ ...t, roles: { selected: 'red' } })?.roles).toBeUndefined();
  });
});

describe('font choice', () => {
  it('defaults to classic and the user font wins over the theme font', async () => {
    const { resolveFont, DEFAULT_FONT, FONT_STACKS } = await import('./themeFonts');
    expect(GOLD_THEME.font).toBe('classic');
    expect(DEFAULT_FONT).toBe('classic');
    expect(FONT_STACKS.classic.startsWith('Arial')).toBe(true);
    expect(resolveFont(null, undefined)).toBe('classic');
    expect(resolveFont(null, 'inter')).toBe('inter');
    expect(resolveFont('atkinson', 'inter')).toBe('atkinson');
    expect(parseTheme({ id: 'x', name: 'X', accent: '#112233', tone: 'neutral', font: 'inter' })?.font).toBe('inter');
    expect(parseTheme({ id: 'x', name: 'X', accent: '#112233', tone: 'neutral', font: 'comic' })?.font).toBeUndefined();
  });
});
