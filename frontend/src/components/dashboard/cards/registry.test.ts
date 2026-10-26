import { describe, expect, it } from 'vitest';

import { ALL_ROLES, DASH_TABS, LAYOUT_COLUMNS, REQUIRED_CARD_FIELDS } from '../dashboardLayout';

import { CARD_REGISTRY } from './registry';

describe('dashboard card registry', () => {
  it('has unique ids', () => {
    const ids = CARD_REGISTRY.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it.each(CARD_REGISTRY.map((c) => [c.id, c] as const))('card %s declares every required field', (_id, card) => {
    for (const field of REQUIRED_CARD_FIELDS) {
      const value = card[field];
      expect(value, `${card.id}.${field}`).toBeTruthy();
    }
    expect(card.roles.length).toBeGreaterThan(0);
    expect(card.roles.every((r) => ALL_ROLES.includes(r))).toBe(true);
    expect(card.tabs.length).toBeGreaterThan(0);
    expect(card.tabs.every((tab) => tab !== 'hosts' && DASH_TABS.some((d) => d.id === tab))).toBe(true);
    expect(Object.keys(LAYOUT_COLUMNS)).toContain(card.layout);
    expect(['summary', 'system']).toContain(card.source);
  });

  it('gives every tile an icon and a quarter of the row', () => {
    for (const card of CARD_REGISTRY.filter((c) => c.layout === 'tile')) {
      expect(card.icon, card.id).toBeTruthy();
      expect(LAYOUT_COLUMNS.tile * 4).toBe(12);
    }
  });

  it('keeps system cards admin-only', () => {
    for (const card of CARD_REGISTRY.filter((c) => c.source === 'system')) {
      expect(card.roles).toEqual(['admin']);
    }
  });
});
