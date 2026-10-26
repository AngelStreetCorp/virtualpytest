// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CARD_REGISTRY } from './cards/registry';
import { CustomizeDrawer } from './CustomizeDrawer';
import { resolveTabCards } from './dashboardLayout';

afterEach(cleanup);

describe('CustomizeDrawer', () => {
  it('uses the theme surface, not the default MUI dark overlay, and has a close icon and a switch per card', () => {
    render(
      <CustomizeDrawer open onClose={vi.fn()} tabTitle="Overview" cards={resolveTabCards('overview', 'admin', CARD_REGISTRY, undefined)} onToggle={vi.fn()} onReset={vi.fn()} isMobile={false} />,
    );
    const paper = screen.getByTestId('customize-drawer-paper');
    const cs = getComputedStyle(paper);
    expect(cs.backgroundImage).toBe('none');
    expect(cs.backgroundColor).not.toBe('');
    expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
    expect(screen.getAllByRole('checkbox').length).toBe(resolveTabCards('overview', 'admin', CARD_REGISTRY, undefined).length);
  });
});
