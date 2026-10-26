// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react-dom/test-utils';
import { createRoot, Root } from 'react-dom/client';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';

import NavigationBar from '../../frontend/src/components/common/Navigation_Bar';
import { navItemSx, navLabelSx } from '../../frontend/src/components/common/Navigation_ItemStyle';

vi.mock('../../frontend/src/i18n/useI18n', () => ({
  useI18n: () => ({ t: (s: string) => s, tn: (_one: string, other: string) => other }),
}));
vi.mock('../../frontend/src/contexts/workspace/WorkspaceContext', () => ({
  useWorkspaceContext: () => ({ isPathHidden: () => false }),
}));
vi.mock('../../frontend/src/contexts/ThemeContext', () => ({
  useTheme: () => ({ menuIconColourResolved: undefined }),
}));
vi.mock('../../frontend/src/hooks/auth/usePermissions', () => ({
  usePermissions: () => ({ hasPermission: () => false }),
}));
vi.mock('../../frontend/src/hooks/customPages/useCustomPages', () => ({
  useCustomPages: () => ({ data: [] }),
}));

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  document.body.innerHTML = '';
});

const render = () => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<MemoryRouter><NavigationBar /></MemoryRouter>));
};

describe('the top-bar nav row (BUG-0773)', () => {
  it('cuts a long label instead of letting the row spill over its neighbour', () => {
    expect(navLabelSx.textOverflow).toBe('ellipsis');
    expect(navLabelSx.overflow).toBe('hidden');
    expect(navLabelSx.whiteSpace).toBe('nowrap');
    expect(navLabelSx.minWidth).toBe(0);
  });

  it('lets an item shrink: the label is what gets cut, never the row over its neighbour', () => {
    const sx = navItemSx(false) as Record<string, unknown>;
    // flexShrink 0 made the row wider than its box, so it painted over the
    // "N online" chip on the right (French "Paramètres", German "Einstellungen").
    expect(sx.flexShrink).toBe(1);
    expect(sx.minWidth).toBe(0);
    // The caret of a dropdown trigger must survive the squeeze.
    expect(sx['& .MuiButton-endIcon']).toEqual({ flexShrink: 0 });
    // Ten items x 12 px of padding left the row with no slack in FR/DE.
    expect(sx.px).toBe(0.75);
  });

  it('clips the row so it can never paint over the slot on its right', () => {
    render();
    const items = Array.from(container!.querySelectorAll('button, a'));
    expect(items.length).toBeGreaterThan(3);

    // Every nav item carries its label in the ellipsis wrapper.
    for (const item of items) {
      const label = Array.from(item.querySelectorAll('span')).find(
        (span) => (span.textContent ?? '').trim().length > 0,
      );
      expect(label).not.toBeNull();
      const style = window.getComputedStyle(label!);
      expect(style.textOverflow).toBe('ellipsis');
      expect(style.overflow).toBe('hidden');
    }

    // The row itself clips: the items may not spill over the header's right slot.
    const row = container!.querySelector('div');
    expect(row).not.toBeNull();
    expect(window.getComputedStyle(row!).overflow).toBe('hidden');
  });
});
