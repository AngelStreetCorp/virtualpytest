import { describe, expect, it } from 'vitest';

import { detectProblems, dueProblems, REALERT_MS, staleDashIds } from './dashboardAlerts';
import { summaryFixture, systemFixture } from './dashboard.fixtures';

describe('detectProblems', () => {
  it('flags a down device, a failure spike, high inodes and a monitoring problem', () => {
    const ids = detectProblems({ summary: { ...summaryFixture, results: { ...summaryFixture.results, failed: 14 } }, system: systemFixture }).map((p) => p.id);
    expect(ids).toEqual(['device-down:vpt-pi3/device1', 'failures-spike', 'inodes-high', 'monitoring:vpt-pi3']);
  });
  it('one notification per down device, scoped so a single device can be muted', () => {
    const down = [
      { host_name: 'h1', device_id: 'device1', device_name: 'Pixel' },
      { host_name: 'h2', device_id: 'device1', device_name: 'Shield' },
    ];
    const p = detectProblems({ summary: { ...summaryFixture, devices: { ...summaryFixture.devices, down: 2, down_items: down } }, system: null }).filter((x) => x.category === 'device');
    expect(p.map((x) => x.id)).toEqual(['device-down:h1/device1', 'device-down:h2/device1']);
    expect(p[1].scope).toEqual({ device_id: 'h2/device1', host_name: 'h2' });
    expect(p[1].to).toBe('/device-control?device=h2%2Fdevice1');
  });
  it('is quiet when everything is fine', () => {
    const ok = {
      summary: { ...summaryFixture, devices: { ...summaryFixture.devices, down: 0, down_items: [] }, results: { ...summaryFixture.results, failed: 1 } },
      system: { ...systemFixture, storage: { disk_pct: 50, inode_pct: 79 }, monitoring: { hosts_total: 3, hosts_ok: 3, problems: [] } },
    };
    expect(detectProblems(ok)).toEqual([]);
  });
  it('tolerates missing blocks', () => {
    expect(detectProblems({ summary: null, system: { ...systemFixture, storage: null, monitoring: null } })).toEqual([]);
  });
});

describe('spike threshold', () => {
  it('does not fire below 30 % failed', () => {
    const ids = detectProblems({ summary: summaryFixture, system: null }).map((p) => p.id);
    expect(ids).not.toContain('failures-spike');
  });
  it('sends the failure spike to the reports page narrowed to the failed runs, over the same window', () => {
    const spike = (range: '24h' | '7d' | '30d') =>
      detectProblems({ summary: { ...summaryFixture, range, results: { ...summaryFixture.results, failed: 14 } }, system: null })
        .find((p) => p.id === 'failures-spike');
    expect(spike('24h').to).toBe('/test-results/reports?status=failed&range=24h');
    expect(spike('7d').to).toBe('/test-results/reports?status=failed&range=7d');
  });
});

describe('dueProblems', () => {
  const p = (id: string) => ({ id, category: 'host' as const, severity: 'error' as const, message: 'm', to: '/' });
  it('toasts once, again after the cooldown, and again after the problem cleared', () => {
    const seen = new Map<string, number>();
    expect(dueProblems([p('a')], seen, 0).map((x) => x.id)).toEqual(['a']);
    expect(dueProblems([p('a')], seen, 1000)).toEqual([]);
    expect(dueProblems([p('a')], seen, REALERT_MS).map((x) => x.id)).toEqual(['a']);
    expect(dueProblems([], seen, REALERT_MS + 1)).toEqual([]);
    expect(dueProblems([p('a')], seen, REALERT_MS + 2).map((x) => x.id)).toEqual(['a']);
  });
});

describe('monitoring target', () => {
  it('points at Status filtered to the host, with the detail in the text', () => {
    const [m] = detectProblems({ summary: null, system: { ...systemFixture, storage: null, monitoring: { hosts_total: 1, hosts_ok: 0, problems: [{ host_name: 'labox-backend', detail: 'disk 93% full' }] } } });
    expect(m.to).toBe('/status?host=labox-backend');
    expect(m.vars).toMatchObject({ hosts: 'labox-backend', detail: 'disk 93% full' });
  });
});

describe('categories and AI budget', () => {
  const sys = (share: number) => ({ ...systemFixture, storage: null, monitoring: null, ai_usage: { cost_7d: 1, top_model: null, budget: { share, label: 'team' } } });
  it('gives each source its category', () => {
    const cats = detectProblems({ summary: { ...summaryFixture, results: { ...summaryFixture.results, failed: 14 } }, system: systemFixture }).map((p) => p.category);
    expect(cats).toEqual(['device', 'script', 'storage', 'capture']);
  });
  it('flags the AI budget at 80 % and 100 %', () => {
    expect(detectProblems({ summary: null, system: sys(0.79) })).toEqual([]);
    expect(detectProblems({ summary: null, system: sys(0.85) })[0]).toMatchObject({ id: 'ai-budget-warn', category: 'ai_spend', severity: 'warning' });
    expect(detectProblems({ summary: null, system: sys(1.2) })[0]).toMatchObject({ id: 'ai-budget-over', severity: 'error' });
  });

  it('flags wasted AI spend at >= 20 % and >= $1, or by tokens when unpriced', () => {
    const w = (waste: object) => detectProblems({ summary: null, system: { ...systemFixture, storage: null, monitoring: null, ai_usage: { cost_7d: 1, top_model: null, waste: { top: [], ...waste } as never } } });
    expect(w({ tokens: 9, cost: 3.4, spend: 9.1, share_pct: 37 })[0]).toMatchObject({ category: 'ai_spend', vars: { wasted: '3.40', spend: '9.10', pct: 37 } });
    expect(w({ tokens: 9, cost: 0.5, spend: 1, share_pct: 50 })).toEqual([]);
    expect(w({ tokens: 9, cost: 3, spend: 100, share_pct: 3 })).toEqual([]);
    expect(w({ tokens: 3_000_000, cost: null, spend: null, share_pct: 40 })[0].message).toContain('tokens');
  });
});

describe('TASK-100 auto-resolve', () => {
  it('detects the same set of ids on a healthy dashboard', () => {
    const ok = {
      summary: { ...summaryFixture, devices: { ...summaryFixture.devices, down: 0, down_items: [] }, results: { ...summaryFixture.results, failed: 1 } },
      system: { ...systemFixture, storage: { disk_pct: 50, inode_pct: 79 }, monitoring: { hosts_total: 3, hosts_ok: 3, problems: [] } },
    };
    expect(detectProblems(ok)).toEqual([]);
  });
  it('idempotent: re-detecting the same live problems does not change ids', () => {
    const a = detectProblems({ summary: summaryFixture, system: systemFixture });
    const b = detectProblems({ summary: summaryFixture, system: systemFixture });
    expect(a.map((p) => p.id)).toEqual(b.map((p) => p.id));
  });
  it('staleDashIds returns a stored dash-* id whose problem is gone', () => {
    const stored = [
      { id: 'dash-monitoring:host-a', severity: 'error' as const, message: 'm', ts: 1 },
      { id: 'dash-monitoring:host-b', severity: 'error' as const, message: 'm', ts: 1 },
      { id: 'dash-device-down:host-b/dev', severity: 'error' as const, message: 'm', ts: 1 },
      { id: 'script-99', severity: 'error' as const, message: 'm', ts: 1 },
    ];
    const live = new Set(['dash-monitoring:host-b']);
    expect(staleDashIds(stored, live)).toEqual(['dash-monitoring:host-a', 'dash-device-down:host-b/dev']);
  });
  it('staleDashIds skips items already resolved', () => {
    const stored = [
      { id: 'dash-monitoring:host-a', severity: 'error' as const, message: 'm', ts: 1, resolved_at: 50 },
      { id: 'dash-monitoring:host-b', severity: 'error' as const, message: 'm', ts: 1 },
    ];
    expect(staleDashIds(stored, new Set())).toEqual(['dash-monitoring:host-b']);
  });
});
