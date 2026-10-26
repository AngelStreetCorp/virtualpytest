import { describe, expect, it } from 'vitest';

import { CARD_REGISTRY } from './cards/registry';
import { allowedTabs, normaliseLayout, resolveFavouriteTab, resolveTabCards, LAYOUT_COLUMNS, type StoredLayout } from './dashboardLayout';

const ids = (role: Parameters<typeof allowedTabs>[0]) => allowedTabs(role).map((t) => t.id);

describe('tabs per role', () => {
  it('admin sees all five, System included', () => {
    expect(ids('admin')).toEqual(['overview', 'hosts', 'scripts', 'devices', 'system']);
  });
  it('tester and developer get Scripts but never System', () => {
    for (const role of ['tester', 'developer'] as const) {
      expect(ids(role)).toEqual(['overview', 'hosts', 'scripts', 'devices']);
    }
  });
  it('viewer gets Overview, Hosts, Devices only', () => {
    expect(ids('viewer')).toEqual(['overview', 'hosts', 'devices']);
  });
});

describe('favourite tab', () => {
  it('opens the favourite when allowed', () => {
    expect(resolveFavouriteTab('admin', 'system')).toBe('system');
  });
  it('opens Overview when there is no favourite or the role lost it', () => {
    expect(resolveFavouriteTab('viewer', 'system')).toBe('overview');
    expect(resolveFavouriteTab('viewer', undefined)).toBe('overview');
  });
  it('lets a starred Hosts and devices tab win', () => {
    expect(resolveFavouriteTab('viewer', 'hosts')).toBe('hosts');
  });
});

describe('card layout', () => {
  it('never offers a system card to a non-admin', () => {
    const ids = resolveTabCards('system', 'tester', CARD_REGISTRY, undefined).map((c) => c.def.id);
    expect(ids).not.toContain('storage');
  });
  it('computes defaults from the registry', () => {
    const on = resolveTabCards('system', 'admin', CARD_REGISTRY, undefined).filter((c) => c.on).map((c) => c.def.id);
    expect(on).toEqual(['sys-services', 'sys-cpu', 'sys-ram', 'sys-disk', 'vms', 'storage', 'monitoring', 'ai-usage']);
  });
  it('puts Overview in the order tiles, trend, needs attention, favourites', () => {
    const on = resolveTabCards('overview', 'admin', CARD_REGISTRY, undefined).filter((c) => c.on).map((c) => c.def.id);
    expect(on).toEqual(['kpi-pass', 'kpi-running', 'kpi-devices', 'kpi-failures', 'trend', 'attention', 'favourites']);
  });
  it('lists no script card with the same script three times: failing scripts replace latest failures', () => {
    const ids = CARD_REGISTRY.map((c) => c.id);
    expect(ids).toContain('failing');
    expect(ids).not.toContain('failures');
  });
  it('fills every row of every default tab exactly (12 columns), in screen order', () => {
    for (const tab of ['overview', 'scripts', 'devices', 'system'] as const) {
      let used = 0;
      for (const c of resolveTabCards(tab, 'admin', CARD_REGISTRY, undefined).filter((x) => x.on)) {
        const cols = LAYOUT_COLUMNS[c.def.layout];
        expect(used + cols, `${tab}: ${c.def.id} would straddle a row`).toBeLessThanOrEqual(12);
        used = (used + cols) % 12;
      }
      expect(used, tab).toBe(0);
    }
  });
  it('applies only what the user changed', () => {
    const cards = resolveTabCards('overview', 'admin', CARD_REGISTRY, { trend: { on: false } });
    expect(cards.find((c) => c.def.id === 'trend')?.on).toBe(false);
    expect(cards.find((c) => c.def.id === 'attention')?.on).toBe(true);
  });
});

describe('stored layout from the S / M / L era', () => {
  it('drops the old size and keeps on / off', () => {
    const old = { tabs: { overview: { trend: { on: false, size: 'L' }, results: { size: 'S' } } }, favouriteTab: 'scripts' } as unknown as StoredLayout;
    const next = normaliseLayout(old);
    expect(next.favouriteTab).toBe('scripts');
    expect(next.tabs.overview?.trend).toEqual({ on: false });
    expect(JSON.stringify(next)).not.toContain('size');
  });
});
