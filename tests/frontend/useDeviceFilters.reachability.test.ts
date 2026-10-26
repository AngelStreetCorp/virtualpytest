/**
 * Filter reachability (BUG-0829) — the contract that makes "No targets match
 * the selected filters" unreachable by clicking.
 *
 * The grid is the AND of four axes (target, model, profile, tag) while the
 * option lists used to be built from the WHOLE fleet. So an axis could offer a
 * value that no surviving device had: filter targets down to a few Tellos,
 * open More, pick an STB model, and the grid emptied with no way to explain it.
 *
 * The rule under test: **a value is on offer only while at least one surviving
 * device carries it.** Each test asserts that rule, and the last one asserts
 * the invariant that falls out of it — adding any offered value always leaves
 * at least one device — rather than an implementation detail.
 */
import { describe, expect, it } from 'vitest';

import {
  narrowFilterOptions,
  reachableFilterOptions,
  type DeviceFilterAxes,
} from '../../frontend/src/hooks/useDeviceFilters';
import { Device, Host } from '../../frontend/src/types/common/Host_Types';

/** Axis state plus the tag combinator, exactly as the pages hold it. */
type FilterState = DeviceFilterAxes & { flagMatchMode: 'AND' | 'OR' };

const device = (device_name: string, device_model: string | undefined): Device =>
  ({ device_name, device_id: device_name, device_model } as Device);

const host = (host_name: string, profiles: Record<string, string> = {}): Host =>
  ({ host_name, system_stats: { monitor_profiles: profiles } } as Host);

/** The reported fleet: two Tellos on one host, one STB on another. */
const TELLOS = [device('Tello-F014A0', 'tello'), device('Tello-F014B1', 'tello')];
const STB = device('example-v1', 'example_stb');
const FLEET = [
  { host: host('drone-1'), device: TELLOS[0] },
  { host: host('drone-1'), device: TELLOS[1] },
  { host: host('node1'), device: STB },
];
const TELLO_TARGETS = ['Tello-F014A0 - drone-1', 'Tello-F014B1 - drone-1'];

const axes = (over: Partial<FilterState> = {}): FilterState => ({
  targetFilter: [],
  deviceModelFilter: [],
  profileFilter: [],
  flagFilter: [],
  flagMatchMode: 'AND',
  ...over,
});

/**
 * Surviving devices of an axis state — the same AND the grid applies, tags
 * included. This is exactly what the pages hand to `reachableFilterOptions`:
 * the already-filtered list, never the raw fleet. Spelled out here rather than
 * imported from the page so the test states the contract instead of agreeing
 * with the implementation by construction.
 */
const survivors = (
  pool: Array<{ host: Host; device: Device }>,
  state: FilterState,
  tagsOf: (hostName: string, deviceId: string) => string[] = () => [],
) =>
  pool.filter(({ host: h, device: d }) => {
    if (state.targetFilter.length > 0 && !state.targetFilter.includes(`${d.device_name} - ${h.host_name}`)) return false;
    if (state.deviceModelFilter.length > 0 && (!d.device_model || !state.deviceModelFilter.includes(d.device_model))) return false;
    if (state.profileFilter.length > 0 && !state.profileFilter.includes(getProfile(h, d))) return false;
    if (state.flagFilter.length > 0) {
      const tags = tagsOf(h.host_name, d.device_id);
      const ok = state.flagMatchMode === 'AND'
        ? state.flagFilter.every((f) => tags.includes(f))
        : state.flagFilter.some((f) => tags.includes(f));
      if (!ok) return false;
    }
    return true;
  });

const getProfile = (h: Host, d: Device) =>
  h.system_stats?.monitor_profiles?.[d.device_id] ?? h.system_stats?.monitor_profiles?.host ?? 'tv_app';

const targetLabels = (pool: Array<{ host: Host; device: Device }>) =>
  pool.map(({ host: h, device: d }) => `${d.device_name} - ${h.host_name}`);

describe('reachableFilterOptions', () => {
  it('offers the whole fleet when nothing is filtered', () => {
    const found = reachableFilterOptions(FLEET, axes());
    expect([...found.models].sort()).toEqual(['example_stb', 'tello']);
    expect(targetLabels(FLEET).every((t) => found.targets.includes(t))).toBe(true);
  });

  it('drops the STB model once only Tellos are selected — the reported dead end', () => {
    const state = axes({ targetFilter: TELLO_TARGETS });
    const found = reachableFilterOptions(survivors(FLEET, state), state);
    expect(found.models).toEqual(['tello']);
    expect(found.models).not.toContain('example_stb');
  });

  it('keeps only profiles the surviving devices actually run', () => {
    const pool = [
      { host: host('drone-1', { 'Tello-F014A0': 'drone' }), device: TELLOS[0] },
      { host: host('drone-1', { 'Tello-F014A0': 'drone' }), device: TELLOS[1] },
      { host: host('node1'), device: STB },
    ];
    const state = axes({ targetFilter: TELLO_TARGETS });
    const found = reachableFilterOptions(survivors(pool, state), state);
    expect(found.profiles.sort()).toEqual(['drone', 'tv_app']);
  });

  it('never offers a model for a device that reports none', () => {
    // A capture the host never classified. `undefined` must not reach the
    // option list — "All Models" would then hold a value matching nothing,
    // which is the same dead end in a different costume.
    const pool = [{ host: host('win-box'), device: device('win-box_Host', undefined) }];
    expect(reachableFilterOptions(pool, axes()).models).toEqual([]);
  });

  it('still offers a model for a VNC device, which does report one', () => {
    const pool = [{ host: host('win-box'), device: device('win-box_Host', 'host_vnc') }];
    expect(reachableFilterOptions(pool, axes()).models).toEqual(['host_vnc']);
  });

  it('drops a tag whose only device did not survive the target filter', () => {
    const tagsOf = (_h: string, d: string) => (d === 'Tello-F014A0' ? ['alpha'] : d === 'example-v1' ? ['beta'] : []);
    const state = axes({ targetFilter: TELLO_TARGETS });
    const first = reachableFilterOptions(survivors(FLEET, state), state, tagsOf);
    // 'alpha' is on offer because a Tello carries it; 'beta' is not, because the
    // one device carrying it is the STB the target filter just removed.
    expect(first.flags).toEqual(['alpha']);
    // And picking it leaves the grid with a device — the property the bug is about.
    expect(survivors(FLEET, axes({ targetFilter: TELLO_TARGETS, flagFilter: ['alpha'] }), tagsOf).length).toBe(1);
  });

  it('narrows a second time once a tag has removed a device', () => {
    // Tello A = alpha, Tello B = beta. Under AND, picking alpha kills Tello B,
    // so beta must disappear from the list — otherwise the second click empties
    // the grid (the exact "4 targets + More 1 = no targets match" report).
    const pool = [
      { host: host('drone-1'), device: TELLOS[0] },
      { host: host('drone-1'), device: TELLOS[1] },
    ];
    const tagsOf = (_h: string, d: string) => (d === 'Tello-F014A0' ? ['alpha'] : ['beta']);
    const afterAlpha = axes({ targetFilter: TELLO_TARGETS, flagFilter: ['alpha'] });
    const found = reachableFilterOptions(survivors(pool, afterAlpha), afterAlpha, tagsOf);
    expect(found.flags).toEqual(['alpha']);
    expect(found.flags).not.toContain('beta');
  });

  it('keeps a selected value visible even when no surviving device has it', () => {
    // A selected device went offline: its value must stay removable or the
    // operator cannot clear their way out of an empty grid.
    const state = axes({ targetFilter: ['gone - offline'] });
    expect(reachableFilterOptions([], state).targets).toEqual(['gone - offline']);
  });

  it('INVARIANT: every offered value, added to the current selection, leaves a device', () => {
    // Walk the narrowing path from the bug report — pick targets, then a model,
    // then a profile — and assert no offered value can empty the grid at any
    // step. This is the property the report is really about.
    const pool = [
      { host: host('drone-1'), device: TELLOS[0] },
      { host: host('drone-1'), device: TELLOS[1] },
      { host: host('node1'), device: STB },
    ];
    const tagsOf = (_h: string, d: string) => (d === 'Tello-F014A0' ? ['alpha'] : ['beta']);

    let state = axes({ targetFilter: TELLO_TARGETS });
    expect(survivors(pool, state, tagsOf).length).toBeGreaterThan(0);

    for (const step of [
      { axis: 'deviceModelFilter' as const, value: 'tello' },
      { axis: 'profileFilter' as const, value: 'tv_app' },
    ]) {
      state = { ...state, [step.axis]: [step.value] };
      expect(survivors(pool, state, tagsOf).length).toBeGreaterThan(0);
    }

    // Every value the filter bar would now offer is safe to click.
    const live = survivors(pool, state, tagsOf);
    const found = reachableFilterOptions(live, state, tagsOf);
    expect(found.models.length).toBeGreaterThan(0);
    expect(found.flags.length).toBeGreaterThan(0);
    found.models.forEach((m) =>
      expect(survivors(pool, { ...state, deviceModelFilter: [m] }, tagsOf).length).toBeGreaterThan(0),
    );
    found.flags.forEach((f) =>
      expect(survivors(pool, { ...state, flagFilter: [...state.flagFilter, f] }, tagsOf).length).toBeGreaterThan(0),
    );
  });
});

describe('narrowFilterOptions', () => {
  const all = ['alpha', 'beta', 'gamma'];

  it('keeps only reachable values, in the caller order', () => {
    expect(narrowFilterOptions(all, ['gamma', 'alpha'])).toEqual(['alpha', 'gamma']);
  });

  it('never hides a selected value', () => {
    expect(narrowFilterOptions(all, ['alpha'], ['beta'])).toEqual(['alpha', 'beta']);
  });

  it('shows everything when no reachability map was passed', () => {
    expect(narrowFilterOptions(all, undefined)).toEqual(all);
  });

  it('keeps a value whose device disappeared mid-session', () => {
    expect(narrowFilterOptions(all, [], ['gamma'])).toEqual(['gamma']);
  });
});