/**
 * DeviceFilterBar reachability (BUG-0829) — what the operator is offered.
 *
 * The bug: the filter bar listed every value of the fleet while the grid is the
 * AND of all four axes, so picking a value that no surviving device carried
 * emptied the page ("No targets match the selected filters"). The bar now
 * receives a `reachableOptions` map and hides Models / Profiles / Tags that the
 * current selection can no longer reach.
 *
 * Two rules this file protects, and they pull in opposite directions:
 *  - **hide what cannot be picked** — a dead-end option is worse than a missing
 *    one, and the owner asked for hiding over disabling ("better to hide so
 *    that user is not confused").
 *  - **never touch the target filter's own meaning** — BUG-0822 gave the bar
 *    under the search box one absolute rule ("Select all" takes EVERY target,
 *    "Clear" drops EVERY target) precisely because a control whose meaning
 *    changes with context is hard to reason about. The target filter is a
 *    union, so adding a target can only widen the grid; it never needs the
 *    guard, and narrowing it would break that rule while fixing nothing.
 *
 * Lives in tests/frontend/** — the only glob the component-test CI job collects.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import { DeviceFilterBar } from '../../frontend/src/components/common/DeviceFilterBar';

vi.mock('../../frontend/src/i18n/useI18n', () => ({
  useI18n: () => ({
    // Interpolates {name} the way the real translator does — the closed target
    // control renders "{count} targets", and an un-interpolated mock would make
    // it unqueryable by accessible name.
    t: (s: string, params?: Record<string, unknown>) =>
      params ? s.replace(/\{(\w+)\}/g, (_m, k) => String(params[k])) : s,
  }),
}));
vi.mock('../../frontend/src/constants/agentChatTheme', () => ({
  useAgentChatPalette: () => ({
    textPrimary: '#000', accentText: '#0af', accent: '#f00', borderColor: '#ccc',
    gold: '#da0', hoverBg: '#eee', textSecondary: '#666', surface: '#fff', onAccent: '#fff',
  }),
}));
vi.mock('../../frontend/src/hooks/useDeviceFavorites', () => ({ useDeviceFavorites: () => ({ isFavorite: () => false }) }));
vi.mock('../../frontend/src/components/common/DeviceMaintenanceBadge', () => ({ DeviceMaintenanceBadge: () => null }));
vi.mock('../../frontend/src/components/common/DeviceFavoriteStar', () => ({ DeviceFavoriteStar: () => null }));
vi.mock('../../frontend/src/components/common/DeviceFavoriteGroupHeader', () => ({ DeviceFavoriteGroupHeader: () => null }));

// The reported fleet: two Tellos, one STB, one profile of each kind.
const TARGETS = ['Tello-F014A0 - drone-1', 'Tello-F014B1 - drone-1', 'example-v1 - node1'];
const TELLOS = ['Tello-F014A0 - drone-1', 'Tello-F014B1 - drone-1'];
const KEYS = Object.fromEntries(
  TARGETS.map((t) => [t, { host_name: t.split(' - ')[1], device_id: t.split(' - ')[0] }]),
);

type BarProps = Partial<React.ComponentProps<typeof DeviceFilterBar>>;

const renderBar = (over: BarProps = {}) => {
  const props: React.ComponentProps<typeof DeviceFilterBar> = {
    targetFilter: TELLOS,
    onTargetFilterChange: vi.fn(),
    deviceModelFilter: [],
    onDeviceModelFilterChange: vi.fn(),
    flagFilter: [],
    onFlagFilterChange: vi.fn(),
    profileFilter: [],
    onProfileFilterChange: vi.fn(),
    targetOptions: TARGETS,
    targetKeys: KEYS,
    uniqueDeviceModels: ['example_stb', 'tello'],
    uniqueFlags: ['alpha', 'beta'],
    uniqueProfiles: ['drone', 'tv_app'],
    hasActiveFilters: true,
    onClearFilters: vi.fn(),
    targetPlaceholder: 'All Targets',
    ...over,
  };
  return { props, ...render(<DeviceFilterBar {...props} />) };
};

/** Popovers render in portals on document.body, so read the whole document. */
const listedOptions = () =>
  Array.from(document.querySelectorAll('[role="menuitem"], [role="option"]')).map((el) => el.textContent?.trim() ?? '');

const openMore = () => {
  fireEvent.click(screen.getByRole('button', { name: /More/ }));
};

const openCategory = (label: string) => {
  fireEvent.click(screen.getByText(label, { selector: 'span' }));
};

describe('DeviceFilterBar — unreachable options are hidden (BUG-0829)', () => {
  it('hides a model no surviving device has', () => {
    // Two Tello targets selected; only they survive, so the STB model is out.
    renderBar({ reachableOptions: { models: ['tello'] } });
    openMore();
    openCategory('Models');
    expect(listedOptions()).toEqual(['tello']);
  });

  it('hides a tag no surviving device has', () => {
    renderBar({ reachableOptions: { flags: ['alpha'] } });
    openMore();
    openCategory('Tags');
    expect(listedOptions()).toEqual(['alpha']);
  });

  it('hides a profile no surviving device runs', () => {
    renderBar({ reachableOptions: { profiles: ['drone'] } });
    openMore();
    openCategory('Profiles');
    // The profile filter lists the short name of the profile ('Drone'), not its id.
    expect(listedOptions()).toEqual(['Drone']);
  });

  it('shows them all when nothing is filtered yet (no dead end exists)', () => {
    renderBar({ targetFilter: [], reachableOptions: { models: ['example_stb', 'tello'] } });
    openMore();
    openCategory('Models');
    expect(listedOptions().sort()).toEqual(['example_stb', 'tello']);
  });

  it('keeps a selected value visible even once nothing reachable remains', () => {
    // The selected device went offline. Hiding its own value would strand the
    // operator on an empty page with no way to unselect it.
    renderBar({
      deviceModelFilter: ['example_stb'],
      reachableOptions: { models: [] },
    });
    openMore();
    openCategory('Models');
    expect(listedOptions()).toEqual(['example_stb']);
  });

  it('falls back to the full lists when no reachability map is passed', () => {
    // DeviceFilterBar is also mounted before the pool is known; showing
    // everything there is the safe default and keeps older callers working.
    renderBar();
    openMore();
    openCategory('Models');
    expect(listedOptions().sort()).toEqual(['example_stb', 'tello']);
  });

  it('narrows the mobile inline selects too', () => {
    renderBar({ isMobile: true, reachableOptions: { models: ['tello'] } });
    // The mobile bar renders the model Select inline. MUI opens the menu from
    // the control root (role=combobox), not from the inner text node, so walk
    // up to it — `closest('.MuiSelect-select')` would match one level too low.
    const label = screen.getByText('All Models');
    const trigger = label.closest('[role="combobox"]') ?? label;
    fireEvent.mouseDown(trigger as HTMLElement);
    expect(listedOptions()).toEqual(['tello']);
  });
});

describe('DeviceFilterBar — the target filter keeps its absolute meaning (BUG-0822)', () => {
  it('still lists every target, even the ones the current filter removed', () => {
    renderBar({ reachableOptions: { models: ['tello'] } });
    fireEvent.click(screen.getByRole('button', { name: /2 targets/ }));
    // "example-v1 - node1" is not reachable, yet it must stay listed: the
    // target filter is a union, so adding it only widens the grid.
    expect(listedOptions()).toContain('example-v1 - node1');
  });

  it('"Select all" still takes EVERY target', () => {
    const onTargetFilterChange = vi.fn();
    renderBar({ onTargetFilterChange, reachableOptions: { models: ['tello'] } });
    fireEvent.click(screen.getByRole('button', { name: /2 targets/ }));
    fireEvent.click(screen.getByTestId('targets-select-all'));
    expect(onTargetFilterChange).toHaveBeenCalledWith(TARGETS);
  });

  it('"Clear" still drops EVERY target', () => {
    const onTargetFilterChange = vi.fn();
    renderBar({ onTargetFilterChange, reachableOptions: { models: ['tello'] } });
    fireEvent.click(screen.getByRole('button', { name: /2 targets/ }));
    fireEvent.click(screen.getByTestId('targets-clear'));
    expect(onTargetFilterChange).toHaveBeenCalledWith([]);
  });
});