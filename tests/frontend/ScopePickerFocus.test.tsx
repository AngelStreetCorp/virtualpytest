// @vitest-environment jsdom
/**
 * The scope chip shows where the keyboard is (BUG-0799).
 *
 * The chip is the first tab stop of the app and it had no focus indicator at all (MUI drops
 * the outline on a ButtonBase), so a keyboard user could not tell where they were — while the
 * next stop, the Dashboard link, shows a gold underline. The chip now paints a gold ring on
 * keyboard focus.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../frontend/src/hooks/useServerPicker', () => ({
  useServerPicker: () => ({
    selectedServer: 'server-a',
    labelFor: (id: string) => `Server ${id}`,
    isServerChanging: false,
    servers: [],
    availableServers: [],
    handleChange: () => {},
    needsAuth: false,
    selectServer: () => {},
    refreshServers: () => {},
  }),
}));

vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => ({
    userWorkspaces: [],
    activeWorkspace: null,
    setActiveWorkspace: () => {},
    loading: false,
  }),
}));

vi.mock('../../frontend/src/hooks/common/useCurrentProject', () => ({
  useCurrentProject: () => ({
    currentProject: null,
    projects: [],
    setCurrentProject: () => {},
    loading: false,
    isOnScopeAwarePage: false,
  }),
}));

import ScopePicker from '../../frontend/src/components/common/ScopePicker';

/** The CSS rules that apply to the chip, straight out of the injected stylesheets. */
const rulesFor = (el: HTMLElement): string[] => {
  const classes = Array.from(el.classList);
  const found: string[] = [];
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try {
      rules = sheet.cssRules;
    } catch {
      continue;
    }
    for (const rule of Array.from(rules)) {
      const selector = (rule as CSSStyleRule).selectorText;
      if (!selector) continue;
      if (classes.some((cls) => selector.includes(cls))) found.push(rule.cssText);
    }
  }
  return found;
};

describe('the scope chip focus ring (BUG-0799)', () => {
  it('paints a visible ring on keyboard focus', () => {
    render(<ScopePicker />);
    const chip = screen.getByRole('button');
    const rules = rulesFor(chip);
    // Either the CSS pseudo-class or MUI's own keyboard-focus class is fine.
    const focusRule = rules.find(
      (rule) => rule.includes(':focus-visible') || rule.includes('Mui-focusVisible'),
    );
    expect(focusRule).toBeTruthy();
    expect(focusRule).toMatch(/outline/);
  });

  it('is the first tab stop, so it is reachable by keyboard', () => {
    render(<ScopePicker />);
    const chip = screen.getByRole('button');
    expect(chip.getAttribute('tabindex')).not.toBe('-1');
  });
});
