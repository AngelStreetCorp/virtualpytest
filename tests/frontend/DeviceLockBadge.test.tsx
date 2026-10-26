// @vitest-environment jsdom
/**
 * The blue "device is in use" badge (owner 2026-10-22).
 *
 * The behaviour worth locking down is not the styling, it is the two cases that
 * silently produce a wrong screen:
 *
 *  1. It must render NOTHING when the device is free. A badge that always renders an
 *     empty chip puts a blue lock on every tile in the grid, which is worse than the
 *     missing indicator it replaced — the operator stops trusting the colour.
 *  2. It must render on EVERY kind of hold: a named human (manual control), a run with
 *     no owner name (script name is all there is), and an owner-less hold where only
 *     the script name is known.
 */
import { describe, expect, it, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import React from 'react';

import { DeviceLockBadge, lockBadgeShows } from '../../frontend/src/components/rec/DeviceLockBadge';

const renderBadge = (props: Record<string, unknown> = {}) =>
  render(<DeviceLockBadge {...props} />);

describe('DeviceLockBadge', () => {
  afterEach(cleanup);

  it('renders nothing at all when the device is not held', () => {
    // The regression this guards: a free device must look exactly as it did before the
    // badge existed, so there is no chip, no lock icon and no empty label in the corner.
    const { container } = renderBadge();
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId('device-lock-badge')).toBeNull();

    // Explicit nulls are what the hooks actually return when no lock is held.
    expect(renderBadge({ ownerName: null }).container.firstChild).toBeNull();
    expect(renderBadge({ ownerName: '' }).container.firstChild).toBeNull();
  });

  it('names the human holding the device', () => {
    renderBadge({ ownerName: 'device_operator' });
    expect(screen.getByTestId('device-lock-badge')).toBeTruthy();
    expect(screen.getByText('device_operator')).toBeTruthy();
  });

  it('shows NOTHING when the lock has no owner name, rather than repeating the script badge', () => {
    // The live regression this replaces: an owner-less run fell back to the script name,
    // so both bottom corners of one tile printed "game/game_tetris.py#browser is…" — and
    // because RunningScriptNameBadge takes 85% of the width, the right-hand pill painted
    // over the blue lock and hid the very thing this badge was added to show.
    //
    // The script name already has a home (bottom-right). This corner carries only what that
    // one cannot say, which is the human.
    renderBadge({ ownerName: null });
    expect(screen.queryByTestId('device-lock-badge')).toBeNull();
  });

  it('does not display the "take-control" action string as somebody\'s name', () => {
    // useDeviceLockLabel returns this sentinel when a manual lock exists but the owner
    // cannot be named. Rendered verbatim it reads as a person's name next to a lock icon.
    renderBadge({ ownerName: 'take-control' });
    expect(screen.queryByText('take-control')).toBeNull();
    expect(screen.getByText('In use')).toBeTruthy();
  });

  it('truncates a long name instead of letting the badge swallow the tile', () => {
    renderBadge({ ownerName: 'a'.repeat(80), maxChars: 10 });
    const label = screen.getByText(/a+…/);
    expect(label.textContent).toBe(`${'a'.repeat(10)}…`);
  });

  it('lockBadgeShows agrees with what the badge renders, so callers can reserve the corner', () => {
    // RecHostPreview and RecHostStreamModal trim the script badge's width using this
    // predicate. If the two ever disagreed, the badge would be drawn into a corner nobody
    // left room for — which is exactly the overlap this rule exists to prevent.
    expect(lockBadgeShows('device_operator')).toBe(true);
    expect(lockBadgeShows('take-control')).toBe(true);
    expect(lockBadgeShows(null)).toBe(false);
    expect(lockBadgeShows(undefined)).toBe(false);
    expect(lockBadgeShows('')).toBe(false);
  });
});