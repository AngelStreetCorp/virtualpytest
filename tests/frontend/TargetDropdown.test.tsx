/**
 * TargetDropdown — target selection contract (BUG-0822).
 *
 * The popover has two panes: a host rail on the left and the targets of the
 * active rail row on the right. Three rules, each in one place:
 *
 *  - **the bar under the search box is always the whole list.** "Select all"
 *    takes every target, "Clear" drops every target, whatever host is open.
 *    An earlier pass scoped both to the active host and the owner called it
 *    too hard to reason about; the scoped pair now lives on the host's own
 *    panel header instead, where the list it applies to is visible.
 *  - **the host header carries the scoped pair** — "Select all" / "Clear all"
 *    on that host's row, so a scoped action sits next to its list.
 *  - **a rail click cycles show → select all → clear.** The first click only
 *    navigates, so one click never both moves the panel and rewrites the
 *    selection the operator was reading.
 *
 * Lives here rather than beside the component: `tests/frontend/**` is the only
 * glob the component-test CI job collects (`frontend/src/**` never ran).
 */
import { fireEvent, render, waitFor } from '@testing-library/react';
import React, { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { TargetDropdown } from '../../frontend/src/components/common/TargetDropdown';

vi.mock('../../frontend/src/i18n/useI18n', () => ({ useI18n: () => ({ t: (s: string) => s }) }));
vi.mock('../../frontend/src/constants/agentChatTheme', () => ({
  useAgentChatPalette: () => ({ textPrimary: '#000', accent: '#f00', borderColor: '#ccc', gold: '#da0', hoverBg: '#eee' }),
}));
vi.mock('../../frontend/src/hooks/useDeviceFavorites', () => ({ useDeviceFavorites: () => ({ isFavorite: () => false }) }));
vi.mock('../../frontend/src/components/common/DeviceMaintenanceBadge', () => ({ DeviceMaintenanceBadge: () => null }));
vi.mock('../../frontend/src/components/common/DeviceFavoriteStar', () => ({ DeviceFavoriteStar: () => null }));
vi.mock('../../frontend/src/components/common/DeviceFavoriteGroupHeader', () => ({ DeviceFavoriteGroupHeader: () => null }));

const OPTIONS = ['cam1 - host-a', 'cam2 - host-a', 'tv1 - host-b'];
const KEYS = {
  'cam1 - host-a': { host_name: 'host-a', device_id: 'device1' },
  'cam2 - host-a': { host_name: 'host-a', device_id: 'device2' },
  'tv1 - host-b': { host_name: 'host-b', device_id: 'device1' },
};

// Opens the closed control; the popover renders in a portal on document.body.
const openDropdown = () => {
  const control = document.querySelector('button') as HTMLButtonElement;
  fireEvent.click(control);
};

const clickOption = (label: string) => {
  const row = Array.from(document.querySelectorAll('[role="menuitem"]')).find((el) => el.getAttribute('title') === label || el.textContent?.includes(label));
  if (!row) throw new Error(`option not found: ${label}`);
  fireEvent.click(row as HTMLElement);
};

// The host rail rows are the only elements carrying an explicit role="button"
// (menu rows are menuitem, buttons are <button>), and their title is the host
// label plus the count they are cycling through.
const railRow = (label: string) => {
  const row = Array.from(document.querySelectorAll('[role="button"]')).find((el) => el.getAttribute('title')?.startsWith(label));
  if (!row) throw new Error(`rail row not found: ${label}`);
  return row as HTMLElement;
};

const clickRailRow = (label: string) => fireEvent.click(railRow(label));

const clickButton = (testId: string) => {
  const button = document.querySelector(`[data-testid="${testId}"]`) as HTMLButtonElement | null;
  if (!button) throw new Error(`button not found: ${testId}`);
  fireEvent.click(button);
};

const buttonLabel = (testId: string) =>
  (document.querySelector(`[data-testid="${testId}"]`) as HTMLButtonElement | null)?.textContent ?? null;

// Controlled harness: the rail cycle only reads as a cycle when the selection
// it produced comes back around, so those cases drive a real stateful parent.
const StatefulTargetDropdown: React.FC<{ initial?: string[] }> = ({ initial = [] }) => {
  const [selected, setSelected] = useState<string[]>(initial);
  return (
    <>
      <TargetDropdown selected={selected} onChange={setSelected} options={OPTIONS} keys={KEYS} />
      <span data-testid="selection">{JSON.stringify(selected)}</span>
    </>
  );
};

const selectionOf = () => JSON.parse(document.querySelector('[data-testid="selection"]')!.textContent!);

describe('TargetDropdown', () => {
  it('single mode replaces the selection and closes the popover', async () => {
    const onChange = vi.fn();
    render(<TargetDropdown multiple={false} selected={['cam1 - host-a']} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickOption('tv1 - host-b');

    expect(onChange).toHaveBeenCalledWith(['tv1 - host-b']);
    // MUI keeps the popover mounted through its exit transition; wait it out.
    await waitFor(() => expect(document.querySelector('[role="menuitem"]')).toBeNull(), { timeout: 3000 });
  });

  it('multi mode toggles options into the selection and keeps it open', () => {
    const onChange = vi.fn();
    render(<TargetDropdown selected={['cam1 - host-a']} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickOption('cam2 - host-a');

    expect(onChange).toHaveBeenCalledWith(['cam1 - host-a', 'cam2 - host-a']);
    expect(document.querySelector('[role="menuitem"]')).not.toBeNull();
  });

  it('single mode hides the multi-only select all and clear controls', () => {
    render(<TargetDropdown multiple={false} selected={[]} options={OPTIONS} keys={KEYS} onChange={vi.fn()} />);

    openDropdown();

    const labels = Array.from(document.querySelectorAll('button')).map((b) => b.textContent);
    expect(labels).not.toContain('Select all');
    expect(labels).not.toContain('Clear');
  });
});

// BUG-0822: the bar is absolute, the host panel is scoped, and a rail click
// cycles show -> select all -> clear instead of selecting on the first click.
describe('TargetDropdown — the bar, the host panel and the rail cycle', () => {
  it('a first click on a host row only shows its devices, it selects nothing', () => {
    const onChange = vi.fn();
    render(<TargetDropdown selected={[]} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickRailRow('host-a');

    expect(onChange).not.toHaveBeenCalled();
    // The panel now lists that host's devices under its own header row.
    expect(Array.from(document.querySelectorAll('[role="menuitem"]')).some((el) => el.textContent?.includes('host-a (2)'))).toBe(true);
  });

  it('the bar Select all takes EVERY target, even with a host open', () => {
    const onChange = vi.fn();
    render(<TargetDropdown selected={[]} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickRailRow('host-a');
    clickButton('targets-select-all');

    expect(onChange).toHaveBeenCalledWith(OPTIONS);
  });

  it('the bar Clear drops EVERY target, even with a host open', () => {
    const onChange = vi.fn();
    render(<TargetDropdown selected={OPTIONS} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickRailRow('host-a');
    clickButton('targets-clear');

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('the host panel carries its own select all / clear all, scoped to that host', () => {
    const onChange = vi.fn();
    render(<TargetDropdown selected={['tv1 - host-b']} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickRailRow('host-a');

    // Two labels that never repeat in one place: the bar is the whole list, the
    // panel row is the host. "Clear" (bar) vs "Clear all" (host).
    expect(buttonLabel('targets-clear')).toBe('Clear');
    expect(buttonLabel('targets-host-select-all')).toBe('Select all');
    expect(buttonLabel('targets-host-clear-all')).toBe('Clear all');

    clickButton('targets-host-select-all');
    expect([...onChange.mock.calls.at(-1)![0]].sort()).toEqual([...OPTIONS].sort());
  });

  it('the host panel clear all drops that host and keeps the others', () => {
    const onChange = vi.fn();
    render(<TargetDropdown selected={OPTIONS} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickRailRow('host-a');
    clickButton('targets-host-clear-all');

    expect(onChange).toHaveBeenCalledWith(['tv1 - host-b']);
  });

  it('the host panel pair appears only when a host is open in multi mode', () => {
    const { unmount } = render(<TargetDropdown selected={[]} options={OPTIONS} keys={KEYS} onChange={vi.fn()} />);
    openDropdown();
    // "All hosts" is open on start: the list is the whole rack, the bar covers it.
    expect(document.querySelector('[data-testid="targets-host-select-all"]')).toBeNull();
    clickRailRow('host-a');
    expect(document.querySelector('[data-testid="targets-host-select-all"]')).not.toBeNull();
    unmount();

    render(<TargetDropdown multiple={false} selected={[]} options={OPTIONS} keys={KEYS} onChange={vi.fn()} />);
    openDropdown();
    clickRailRow('host-b');
    expect(document.querySelector('[data-testid="targets-host-select-all"]')).toBeNull();
  });

  it('the bar pair is greyed out when it has nothing left to do', () => {
    const { rerender } = render(<TargetDropdown selected={[]} options={OPTIONS} keys={KEYS} onChange={vi.fn()} />);
    openDropdown();
    expect((document.querySelector('[data-testid="targets-clear"]') as HTMLButtonElement).disabled).toBe(true);
    expect((document.querySelector('[data-testid="targets-select-all"]') as HTMLButtonElement).disabled).toBe(false);

    rerender(<TargetDropdown selected={OPTIONS} options={OPTIONS} keys={KEYS} onChange={vi.fn()} />);
    expect((document.querySelector('[data-testid="targets-clear"]') as HTMLButtonElement).disabled).toBe(false);
    expect((document.querySelector('[data-testid="targets-select-all"]') as HTMLButtonElement).disabled).toBe(true);
  });

  it('a second click selects the whole host and a third clears it', () => {
    render(<StatefulTargetDropdown />);

    openDropdown();
    clickRailRow('host-a');
    expect(selectionOf()).toEqual([]);

    clickRailRow('host-a');
    expect(selectionOf()).toEqual(['cam1 - host-a', 'cam2 - host-a']);

    clickRailRow('host-a');
    expect(selectionOf()).toEqual([]);

    // …and the cycle restarts cleanly from there.
    clickRailRow('host-a');
    expect(selectionOf()).toEqual(['cam1 - host-a', 'cam2 - host-a']);
  });

  it('the All hosts rail row cycles over the whole list', () => {
    render(<StatefulTargetDropdown />);

    openDropdown();
    // "All hosts" is active on open, so its first click is already the 2nd step.
    clickRailRow('All hosts');
    expect(selectionOf()).toEqual(OPTIONS);

    clickRailRow('All hosts');
    expect(selectionOf()).toEqual([]);
  });

  it('a host with some devices selected completes the rack on the next click', () => {
    render(<StatefulTargetDropdown initial={['cam1 - host-a']} />);

    openDropdown();
    clickRailRow('host-a');
    clickRailRow('host-a');

    expect(selectionOf()).toEqual(['cam1 - host-a', 'cam2 - host-a']);
  });

  it('switching hosts resets the cycle: the new host navigates before it selects', () => {
    render(<StatefulTargetDropdown initial={['cam1 - host-a', 'cam2 - host-a']} />);

    openDropdown();
    clickRailRow('host-a'); // navigate only, the selection is left alone
    expect(selectionOf()).toEqual(['cam1 - host-a', 'cam2 - host-a']);

    clickRailRow('host-a'); // active and full → clears
    expect(selectionOf()).toEqual([]);

    clickRailRow('host-b'); // a different host navigates before it selects
    expect(selectionOf()).toEqual([]);

    clickRailRow('host-b');
    expect(selectionOf()).toEqual(['tv1 - host-b']);
  });

  it('single mode keeps a rail click navigation-only', () => {
    const onChange = vi.fn();
    render(<TargetDropdown multiple={false} selected={[]} options={OPTIONS} keys={KEYS} onChange={onChange} />);

    openDropdown();
    clickRailRow('host-a');
    clickRailRow('host-a');

    expect(onChange).not.toHaveBeenCalled();
  });
});