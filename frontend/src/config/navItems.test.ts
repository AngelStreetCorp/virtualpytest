// @vitest-environment jsdom
/**
 * Regression test for the BUG-0569 / BUG-0571 stub leak: the matcher-history
 * refactor left an empty `{}` placeholder in CONFIGURATION_ITEMS that flowed
 * into <NavigationDropdown items={CONFIGURATION_ITEMS}>, where it crashed
 * `requiredPermissionForPath({})` on `path.startsWith` and took the whole
 * top nav down with it.
 *
 * Every exported dropdown array must be a flat list of well-formed NavItem:
 *   - `label` present
 *   - either `path` (internal link), or one of `href`/`externalHref`/
 *     `onSelect` (action / external)
 *
 * If this test fails, copy-paste the listed entry from the offending array
 * and either fill in the missing fields or remove it entirely — do NOT
 * weaken the test.
 */
import { describe, expect, it } from 'vitest';

import {
  AI_AGENT_ITEMS,
  CONFIGURATION_ITEMS,
  DOCS_ITEMS,
  INTEGRATIONS_ITEMS,
  MONITORING_ITEMS,
  TEST_GROUPS,
} from './navItems';

const DROPDOWN_ARRAYS: { name: string; items: Array<Record<string, unknown>> }[] = [
  { name: 'AI_AGENT_ITEMS', items: AI_AGENT_ITEMS as unknown as Array<Record<string, unknown>> },
  { name: 'MONITORING_ITEMS', items: MONITORING_ITEMS as unknown as Array<Record<string, unknown>> },
  { name: 'DOCS_ITEMS', items: DOCS_ITEMS as unknown as Array<Record<string, unknown>> },
  { name: 'INTEGRATIONS_ITEMS', items: INTEGRATIONS_ITEMS as unknown as Array<Record<string, unknown>> },
  { name: 'CONFIGURATION_ITEMS', items: CONFIGURATION_ITEMS as unknown as Array<Record<string, unknown>> },
  { name: 'TEST_GROUPS (each group.items)', items: TEST_GROUPS.flatMap((g) => g.items) as unknown as Array<Record<string, unknown>> },
];

describe('navItems — every dropdown entry must be a real NavItem', () => {
  for (const { name, items } of DROPDOWN_ARRAYS) {
    it(`${name} has no empty stub entries`, () => {
      // Catch the exact BUG-0569 regression: an item with no label, no path,
      // no href, no externalHref, no onSelect is a no-op row that the
      // NavigationDropdown will then try to render — see the comment in
      // CONFIGURATION_ITEMS for the historical "matcher history moved" stub.
      const stubs = items
        .map((it, i) => ({ it, i }))
        .filter(({ it }) =>
          !it.label &&
          !it.path &&
          !it.href &&
          !it.externalHref &&
          typeof it.onSelect !== 'function',
        );
      expect(stubs, `Empty stub entries in ${name}: indexes ${stubs.map((s) => s.i).join(', ')}`).toEqual([]);
    });

    it(`${name} has a label on every entry`, () => {
      const unlabeled = items
        .map((it, i) => ({ label: it.label, i }))
        .filter(({ label }) => !label);
      expect(unlabeled, `Unlabeled entries in ${name}: ${JSON.stringify(unlabeled)}`).toEqual([]);
    });
  }
});
