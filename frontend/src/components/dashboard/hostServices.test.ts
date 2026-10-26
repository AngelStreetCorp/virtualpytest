import { describe, expect, it } from 'vitest';
import { buildHostServices, devicesUsing, profileMix, RawService } from './hostServices';

const svc = (name: string, label: string, status = 'active', critical = true): RawService =>
  ({ name, label, status, critical, optional: !critical });

const PROFILE_SERVICES = {
  tv_app: { img: true, audio: true, subtitle: true, archiver: true, kpi: true, avq: true },
  ad_meter: { img: true, audio: false, subtitle: false, archiver: true, kpi: true, avq: true },
  tv_lite: { img: false, audio: false, subtitle: false, archiver: false, kpi: false, avq: false },
};

const base = (over: Record<string, string> = {}): RawService[] => [
  svc('vpt-stream', 'Stream'),
  svc('vpt-host', 'Host API'),
  svc('vpt-monitor-img', 'Monitor (image)', over['vpt-monitor-img'] ?? 'active'),
  svc('vpt-archiver', 'Archiver', over['vpt-archiver'] ?? 'active'),
  svc('vpt-kpi', 'KPI', over['vpt-kpi'] ?? 'active'),
  svc('vpt-vnc', 'VNC', over['vpt-vnc'] ?? 'active', false),
  svc('vpt-websockify', 'Websockify', over['vpt-websockify'] ?? 'active', false),
  svc('vpt-monitor-audio', 'Monitor (audio)', over['vpt-monitor-audio'] ?? 'active', false),
  svc('vpt-monitor-subtitle', 'Monitor (subtitle)', over['vpt-monitor-subtitle'] ?? 'active', false),
  svc('vpt-emulator', 'Emulator', over['vpt-emulator'] ?? 'not_installed', false),
];

const input = (profiles: Record<string, string>) => ({
  monitorProfiles: profiles,
  profileServices: PROFILE_SERVICES,
  deviceCount: Object.keys(profiles).length,
});

const labels = (rows: { label: string }[]) => rows.map((r) => r.label);

describe('profile mix', () => {
  it('counts devices per profile and defaults to tv_app without data', () => {
    expect(profileMix(input({ a: 'tv_app', b: 'tv_app', c: 'tv_lite' }))).toEqual({ tv_app: 2, tv_lite: 1 });
    expect(profileMix({ deviceCount: 3 })).toEqual({ tv_app: 3 });
  });
  it('counts devices using a service per their profile', () => {
    const i = input({ a: 'tv_app', b: 'ad_meter', c: 'tv_lite' });
    expect(devicesUsing('img', i)).toBe(2);
    expect(devicesUsing('audio', i)).toBe(1);
    expect(devicesUsing('img', { deviceCount: 1 })).toBeNull();
  });
});

describe('buildHostServices', () => {
  it('groups core / monitoring / optional and merges VNC + Websockify into Remote view', () => {
    const m = buildHostServices(base(), input({ a: 'tv_app' }));
    expect(labels(m.groups.core)).toEqual(['Stream', 'Host API', 'VNC']);
    expect(labels(m.groups.monitoring)).toEqual(['Image', 'Audio', 'Subtitle']);
    expect(labels(m.groups.optional)).toEqual(['Archiver', 'KPI']);
    expect(m.groups.monitoring[0].deviceCount).toBe(1);
  });

  it('a tv_lite host: stopped monitoring re-routes to Optional with reason "tv_lite: monitoring off"', () => {
    const m = buildHostServices(
      base({ 'vpt-monitor-img': 'stopped', 'vpt-monitor-audio': 'stopped', 'vpt-monitor-subtitle': 'stopped', 'vpt-archiver': 'stopped', 'vpt-kpi': 'stopped' }),
      input({ a: 'tv_lite', b: 'tv_lite' }),
    );
    expect(m.counts.down).toBe(0);
    // Idle rows collapse to Optional; Core/Monitoring stay empty so cards render tight
    // (no "tv_lite: monitoring off" subtitle to truncate inside Core/Monitoring).
    expect(labels(m.groups.core)).toEqual(['Stream', 'Host API', 'VNC']);
    expect(m.groups.monitoring).toEqual([]);
    expect(m.counts.idle).toBe(5);
    const img = m.groups.optional.find((r) => r.label === 'Image');
    const archiver = m.groups.optional.find((r) => r.label === 'Archiver');
    expect(img?.state).toBe('idle');
    expect(img?.reason).toBe('tv_lite: monitoring off');
    // Profile-driven services (img/audio/.../archiver/kpi) share the same idle reason
    // when ALL profiles are tv_lite (classify: "if deviceCount === 0 && allLite").
    // Core-group idle rows are the only ones forced to the generic "not needed on this host".
    expect(archiver?.reason).toBe('tv_lite: monitoring off');
  });

  it('profile mix decides what is expected', () => {
    const m = buildHostServices(
      base({ 'vpt-monitor-audio': 'stopped', 'vpt-monitor-subtitle': 'stopped' }),
      input({ a: 'ad_meter', b: 'ad_meter' }),
    );
    // Image stays active in Monitoring; Audio/Subtitle are idle and move to Optional.
    expect(m.groups.monitoring.map((r) => r.state)).toEqual(['active']);
    const audio = m.groups.optional.find((r) => r.label === 'Audio');
    const subtitle = m.groups.optional.find((r) => r.label === 'Subtitle');
    expect(audio?.state).toBe('idle');
    expect(audio?.reason).toBe('no device needs it');
    expect(subtitle?.state).toBe('idle');
    // one tv_app device makes audio expected again — idle flips to down, stays in monitoring
    const m2 = buildHostServices(base({ 'vpt-monitor-audio': 'stopped' }), input({ a: 'ad_meter', b: 'tv_app' }));
    expect(m2.groups.monitoring[1]).toMatchObject({ state: 'down', word: 'down', deviceCount: 1 });
  });

  it('a stopped or stuck core service is down', () => {
    const m = buildHostServices(base(), input({ a: 'tv_app' }));
    expect(m.counts.down).toBe(0);
    const bad = base();
    bad[0] = svc('vpt-stream', 'Stream', 'stopped');
    bad[1] = svc('vpt-host', 'Host API', 'stuck');
    const m2 = buildHostServices(bad, input({ a: 'tv_app' }));
    expect(m2.groups.core.map((r) => [r.state, r.word])).toEqual([['down', 'down'], ['down', 'stuck'], ['active', 'active']]);
  });

  it('Remote view is down with detail when expected and one half is down; idle on a host without VNC, then routes to Optional', () => {
    const vnc = base({ 'vpt-websockify': 'stopped' }).map((s) => (s.name.match(/vnc|websockify/) ? { ...s, critical: true, optional: false } : s));
    const m = buildHostServices(vnc, input({ a: 'tv_app' }));
    expect(m.groups.core[2]).toMatchObject({ state: 'down', reason: 'Websockify down' });
    const m2 = buildHostServices(base({ 'vpt-vnc': 'stopped', 'vpt-websockify': 'stopped' }), input({ a: 'tv_app' }));
    // Idle Remote-view collapses to Optional (was: m.groups.core[2].state === 'idle').
    expect(m2.groups.optional.find((r) => r.label === 'VNC')?.state).toBe('idle');
  });

  it('collapses not-installed services that are not expected into one list', () => {
    const m = buildHostServices(base(), input({ a: 'tv_app' }));
    expect(m.notInstalled).toEqual(['Emulator']);
    expect(labels(m.groups.optional)).not.toContain('Emulator');
  });

  it('a not-installed service goes to the collapsed list even when a profile expects it', () => {
    const m = buildHostServices(base({ 'vpt-kpi': 'not_installed' }), input({ a: 'tv_app' }));
    expect(m.notInstalled).toContain('KPI');
    expect(labels(m.groups.optional)).not.toContain('KPI');
  });

  it('summary counts', () => {
    const m = buildHostServices(base({ 'vpt-monitor-audio': 'stopped', 'vpt-kpi': 'stopped' }), input({ a: 'ad_meter', b: 'tv_app' }));
    // audio expected (tv_app) -> down, kpi expected -> down, subtitle active
    expect(m.counts).toEqual({ running: 6, down: 2, idle: 0 });
  });

  it('falls back to the critical flag when the host sends no profile mapping', () => {
    const m = buildHostServices(base({ 'vpt-monitor-audio': 'stopped', 'vpt-kpi': 'stopped' }), { deviceCount: 1 });
    // Audio (not critical) becomes idle and lands in Optional rather than Monitoring,
    // so Core/Monitoring stays tight.
    expect(m.groups.optional.find((r) => r.label === 'Audio')?.state).toBe('idle');
    expect(m.groups.optional.find((r) => r.label === 'KPI')?.state).toBe('down');   // kpi critical
  });
});
