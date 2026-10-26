import { describe, expect, it } from 'vitest';
import type { Host } from '../../types/common/Host_Types';
import { hostHasError, hostHasWarning, hostHealth, hostWarningReasons, isVersionMismatch, normalizeVersion } from './hostHealth';

const PROFILE_SERVICES = {
  tv_app: { img: true, audio: true, subtitle: true, archiver: true, kpi: true, avq: true },
  tv_lite: { img: false, audio: false, subtitle: false, archiver: false, kpi: false, avq: false },
};

const host = (over: Record<string, unknown> = {}): Host =>
  ({
    host_name: 'h1',
    status: 'online',
    deployed_version: 'main-2026.10.21-89530',
    devices: [{ device_id: 'd1' }, { device_id: 'd2' }],
    system_stats: { monitor_profiles: { d1: 'tv_lite', d2: 'tv_lite' }, monitor_profile_services: PROFILE_SERVICES },
    ...over,
  }) as unknown as Host;

const services = (list: Array<Record<string, unknown>>, profiles: Record<string, string> = { d1: 'tv_lite', d2: 'tv_lite' }) => ({
  operational_status: 'online',
  monitor_profiles: profiles,
  monitor_profile_services: PROFILE_SERVICES,
  service_health: { overall_status: 'online', services: list },
});

/**
 * vpt-nipogi's real payload, captured from the host (build_service_health_summary
 * on the box). TASK-144 stopped these four because no device profile asks for
 * them, so the backend demoted them to critical:false / not_needed:true and kept
 * overall_status online. The dashboard badge counted them as errors anyway —
 * "1 in error" with nothing red on the card.
 */
const NIPOGI = [
  { name: 'vpt-stream', label: 'Stream', status: 'active', critical: true, optional: false },
  { name: 'vpt-host', label: 'Host API', status: 'active', critical: true, optional: false },
  { name: 'vpt-monitor-img', label: 'Monitor (image)', status: 'stopped', critical: false, optional: false, not_needed: true },
  { name: 'vpt-archiver', label: 'Archiver', status: 'stopped', critical: false, optional: false, not_needed: true },
  { name: 'vpt-kpi', label: 'KPI', status: 'stopped', critical: false, optional: false, not_needed: true },
  { name: 'vpt-vnc', label: 'VNC', status: 'not_installed', critical: false, optional: true },
  { name: 'vpt-websockify', label: 'Websockify', status: 'not_installed', critical: false, optional: true },
  { name: 'vpt-monitor-audio', label: 'Monitor (audio)', status: 'stopped', critical: false, optional: false, not_needed: true },
  { name: 'vpt-monitor-subtitle', label: 'Monitor (subtitle)', status: 'not_installed', critical: false, optional: true },
  { name: 'vpt-emulator', label: 'Emulator', status: 'not_installed', critical: false, optional: true },
  { name: 'vpt-emulator-fifo', label: 'Screencap', status: 'not_installed', critical: false, optional: true },
];

describe('hostHealth — a stopped service nobody needs is not an error', () => {
  it('reports vpt-nipogi as ok: 4 services stopped on purpose, nothing down', () => {
    const health = hostHealth(host({ system_stats: services(NIPOGI) }));
    expect(health.severity).toBe('ok');
    expect(health.downRows).toHaveLength(0);
    expect(health.downServices).toHaveLength(0);
    expect(hostHasError(host({ system_stats: services(NIPOGI) }))).toBe(false);
  });

  it('is not fooled by the backend demoting critical while optional stays false', () => {
    // The exact shape that broke the old predicate: optional:false, stopped,
    // no profile wants it. buildHostServices files it under Optional as idle.
    const h = host({
      system_stats: services([
        ...NIPOGI.slice(0, 2),
        { name: 'vpt-monitor-img', label: 'Monitor (image)', status: 'stopped', critical: false, optional: false },
      ]),
    });
    expect(hostHasError(h)).toBe(false);
  });

  it('still errors when a service a device profile DOES need is stopped', () => {
    const h = host({
      system_stats: services(NIPOGI, { d1: 'tv_app', d2: 'tv_app' }),
    });
    const health = hostHealth(h);
    expect(health.severity).toBe('error');
    expect(health.downServices.map((s) => s.name).sort()).toEqual(
      ['vpt-monitor-audio', 'vpt-monitor-img', 'vpt-archiver', 'vpt-kpi'].sort(),
    );
  });

  it('errors on a needed service that is stuck, and on the backend saying error', () => {
    const stuck = host({
      system_stats: services(
        [
          ...NIPOGI.slice(0, 2),
          { name: 'vpt-monitor-img', label: 'Monitor (image)', status: 'stuck', critical: true, optional: false },
        ],
        { d1: 'tv_app', d2: 'tv_app' },
      ),
    });
    expect(hostHasError(stuck)).toBe(true);

    const backendError = host({
      system_stats: { operational_status: 'error', service_health: { overall_status: 'error', services: NIPOGI } },
    });
    expect(hostHasError(backendError)).toBe(true);
  });

  it('treats an offline host as an error even with no service data', () => {
    expect(hostHasError(host({ status: 'offline', system_stats: {} }))).toBe(true);
  });

  it('never lights the badge for a service that is merely not installed', () => {
    // The card files a not-installed service under the collapsed "Not installed (N)"
    // list and never draws a dot for it, so the badge must stay quiet too — the
    // invariant is "the badge only fires when something red is on screen".
    const h = host({
      system_stats: services(
        [
          ...NIPOGI.slice(0, 2),
          { name: 'vpt-monitor-img', label: 'Monitor (image)', status: 'not_installed', critical: true, optional: false },
        ],
        { d1: 'tv_app', d2: 'tv_app' },
      ),
    });
    expect(hostHealth(h).severity).toBe('ok');
    expect(hostHealth(h).downServices).toHaveLength(0);
  });

  it('keeps vpt-host out of the Auto-fix list — it has its own buttons', () => {
    const h = host({
      system_stats: services(
        [...NIPOGI.slice(0, 2), { name: 'vpt-monitor-img', label: 'Monitor (image)', status: 'error', critical: true, optional: false }],
        { d1: 'tv_app', d2: 'tv_app' },
      ),
    });
    expect(hostHealth(h).downServices.map((s) => s.name)).toEqual(['vpt-monitor-img']);
  });
});

describe('hostHealth — degraded and version mismatch are warnings, not errors', () => {
  it('warns, not errors, when the backend says degraded', () => {
    const h = host({ system_stats: { operational_status: 'degraded', service_health: { overall_status: 'degraded', services: NIPOGI } } });
    expect(hostHealth(h).severity).toBe('warning');
    expect(hostHasError(h)).toBe(false);
    expect(hostHasWarning(h)).toBe(true);
  });

  it('warns, not errors, on a code mismatch with the server', () => {
    const h = host({ system_stats: services(NIPOGI), deployed_version: 'main-2026.10.20-89000' });
    expect(hostHealth(h, 'main-2026.10.21-89530').severity).toBe('warning');
    expect(hostHasError(h, 'main-2026.10.21-89530')).toBe(false);
  });

  it('stays ok when the host and the server run the same build', () => {
    const h = host({ system_stats: services(NIPOGI) });
    expect(hostHealth(h, 'main-2026.10.21-89530').severity).toBe('ok');
    expect(hostHealth(h, 'main-2026.10.21-89530').versionMismatch).toBe(false);
  });

  it('a real error outranks a version mismatch', () => {
    const h = host({
      deployed_version: 'main-2026.10.20-89000',
      system_stats: {
        ...services([...NIPOGI.slice(0, 2), { name: 'vpt-kpi', label: 'KPI', status: 'error', critical: true, optional: false }]),
        monitor_profiles: { d1: 'tv_app', d2: 'tv_app' },
      },
    });
    expect(hostHealth(h, 'main-2026.10.21-89530').severity).toBe('error');
  });

  it('ignores an unknown version on either side rather than flagging a mismatch', () => {
    expect(isVersionMismatch(undefined, 'main-1')).toBe(false);
    expect(isVersionMismatch('main-1', null)).toBe(false);
    expect(isVersionMismatch('main-2026.10.21-89530', 'current:main-2026.10.21-89530')).toBe(false);
    expect(normalizeVersion('current:main-2026.10.21-89530')).toBe('89530');
    expect(isVersionMismatch('main-2026.10.20-89000', 'main-2026.10.21-89530')).toBe(true);
  });
});
describe('disk in the host verdict (TASK-156)', () => {
  const withDisk = (disk_percent?: number) =>
    host({ system_stats: { ...services([]), disk_percent } });
  it('stays ok below 85 %', () => expect(hostHealth(withDisk(84)).severity).toBe('ok'));
  it('warns from 85 %', () => {
    const h = hostHealth(withDisk(85));
    expect([h.severity, h.diskLevel]).toEqual(['warning', 'warning']);
  });
  it('errors from 95 %, a full disk is never green', () => {
    expect(hostHealth(withDisk(100)).severity).toBe('error');
    expect(hostHasError(withDisk(95))).toBe(true);
  });
  it('ignores a missing reading', () => expect(hostHealth(withDisk(undefined)).diskLevel).toBeNull());
});

describe('hostWarningReasons — why the amber badge counts a host', () => {
  // The fixture host runs main-2026.10.21-89530, so that is the server build
  // here: a host is only amber for its build when the server runs something else.
  const SERVER = 'main-2026.10.21-89530';

  it('names a version mismatch', () => {
    const h = host({ deployed_version: 'main-2026.10.22-89574', system_stats: services([]) });
    expect(hostWarningReasons(h, SERVER)).toEqual(['version']);
  });

  it('names a degraded backend', () => {
    const h = host({ system_stats: { operational_status: 'degraded', service_health: { overall_status: 'degraded', services: [] } } });
    expect(hostWarningReasons(h, SERVER)).toEqual(['degraded']);
  });

  it('names a full disk', () => {
    const h = host({ system_stats: { ...services([]), disk_percent: 86.31 } });
    expect(hostWarningReasons(h, SERVER)).toEqual(['disk']);
  });

  it('lists every reason of a host that is amber for two of them', () => {
    const h = host({
      deployed_version: 'main-2026.10.22-89574',
      system_stats: { ...services([]), disk_percent: 86.31 },
    });
    expect(hostWarningReasons(h, SERVER)).toEqual(['version', 'disk']);
  });

  it('says nothing about a healthy host', () => {
    const h = host({ system_stats: services([]) });
    expect(hostWarningReasons(h, SERVER)).toEqual([]);
  });

  it('says nothing about a host in error — red outranks amber', () => {
    const h = host({
      deployed_version: 'main-2026.10.22-89574',
      system_stats: { ...services([]), disk_percent: 99 },
    });
    expect(hostHasError(h, SERVER)).toBe(true);
    expect(hostWarningReasons(h, SERVER)).toEqual([]);
  });

  it('says nothing about a host that reports no version at all', () => {
    const h = host({ system_stats: services([]) });
    expect(hostWarningReasons(h, undefined)).toEqual([]);
  });
});
