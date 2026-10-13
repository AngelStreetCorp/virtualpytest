import { describe, expect, it } from 'vitest';

import { clampWidth, followPane, initialSplitState, openPage, pageOptions, routerPath, toggleSplit, widthFromPointer } from './actions';
import { MAX_RECENT, MAX_WIDTH_PCT, MIN_WIDTH_PCT } from './constants';

describe('split view', () => {
  it('opens a page and keeps recent pages, newest first, without duplicates', () => {
    let s = openPage(initialSplitState, '/heatmap');
    s = openPage(s, '/device-control');
    s = openPage(s, '/heatmap');
    expect(s.open).toBe(true);
    expect(s.recent).toEqual(['/heatmap', '/device-control']);
    for (let i = 0; i < 10; i++) s = openPage(s, `/p${i}`);
    expect(s.recent).toHaveLength(MAX_RECENT);
  });

  it('toggles back to the last page', () => {
    const s = toggleSplit(toggleSplit(openPage(initialSplitState, '/heatmap')));
    expect(s).toMatchObject({ open: true, path: '/heatmap' });
  });

  it('follows the frame without adding to recent', () => {
    const s = followPane(openPage(initialSplitState, '/a'), '/b?x=1');
    expect(s.path).toBe('/b?x=1');
    expect(s.recent).toEqual(['/a']);
  });

  it('keeps the width between its limits, measured from the right', () => {
    expect(clampWidth(5)).toBe(MIN_WIDTH_PCT);
    expect(clampWidth(99)).toBe(MAX_WIDTH_PCT);
    expect(widthFromPointer(600, 0, 1000)).toBe(40);
  });

  it('offers in-app visible pages once', () => {
    const entries = [
      { path: '/a', label: 'A', section: 'Top' },
      { path: 'https://x', label: 'X', section: 'Plugins' },
      { path: '/hidden', label: 'H', section: 'Top' },
      { path: '/a', label: 'A2', section: 'Top' },
    ];
    expect(pageOptions(entries, (p) => p === '/hidden').map((e) => e.path)).toEqual(['/a']);
  });

  it('drops the proxy prefix from the frame location', () => {
    expect(routerPath('/pi4/monitoring/heatmap', '?d=1', '/pi4')).toBe('/monitoring/heatmap?d=1');
    expect(routerPath('/pi4', '', '/pi4')).toBe('/');
    expect(routerPath('/x', '', '')).toBe('/x');
  });
});
