import { describe, expect, it } from 'vitest';

import type { RunEvent } from '../../../../frontend/src/mods/core/types';

import { applyRun, buildRows, countAlerts, countFailures, totals } from './actions';
import { SHOW_ACTIVE } from './constants';

const run = (over: Partial<RunEvent> = {}): RunEvent => ({ id: 'r1', kind: 'script', status: 'running', hostName: 'pi1', deviceId: 'd1', timestamp: 0, ...over });

describe('team devices widget', () => {
  it('tracks running runs per device until they end', () => {
    let running = applyRun({}, run());
    expect(running).toEqual({ r1: { hostName: 'pi1', deviceId: 'd1' } });
    expect(applyRun(running, run({ id: 'r2', hostName: undefined }))).toBe(running);
    running = applyRun(running, run({ status: 'failed' }));
    expect(running).toEqual({});
  });

  it('counts failed runs of the last 24 h per host and device name', () => {
    const now = Date.parse('2026-10-08T12:00:00Z');
    const counts = countFailures(
      [
        { host_name: 'pi1', device_name: 'STB', success: false, started_at: '2026-10-08T10:00:00Z' },
        { host_name: 'pi1', device_name: 'STB', success: false, started_at: '2026-10-06T10:00:00Z' },
        { host_name: 'pi1', device_name: 'STB', success: true, started_at: '2026-10-08T11:00:00Z' },
      ],
      now,
      24 * 60 * 60 * 1000,
    );
    expect(counts.byName).toEqual({ 'pi1:STB': 1 });
  });

  it('counts open alerts of the team per host and device id', () => {
    const counts = countAlerts(
      [
        { host_name: 'pi1', device_id: 'd1', team_id: 'team' },
        { host_name: 'pi1', device_id: 'd1', team_id: null },
        { host_name: 'pi1', device_id: 'd1', team_id: 'other' },
      ],
      'team',
    );
    expect(counts.byId).toEqual({ 'pi1:d1': 2 });
  });

  it('lists the busiest devices first, and filters to active ones', () => {
    const hosts = [
      { host_name: 'pi1', status: 'online', devices: [{ device_id: 'd1', device_name: 'STB' }, { device_id: 'd2', device_name: 'Apple TV' }] },
      { host_name: 'pi2', status: 'offline', devices: [{ device_id: 'd1', device_name: 'Pixel' }] },
    ];
    const rows = buildRows(hosts, { r1: { hostName: 'pi1', deviceId: 'd2' } }, { byName: { 'pi1:STB': 2 }, byId: {} }, 'all');
    expect(rows.map((r) => r.deviceName)).toEqual(['STB', 'Apple TV', 'Pixel']);
    expect(totals(rows)).toEqual({ devices: 3, offline: 1, running: 1, failed: 2 });
    expect(buildRows(hosts, {}, undefined, SHOW_ACTIVE).map((r) => r.deviceName)).toEqual(['Pixel']);
    expect(buildRows(hosts, {}, { byName: {}, byId: { 'pi2:d1': 1 } }, 'all')[0]).toMatchObject({ deviceName: 'Pixel', failed: 1 });
  });
});
