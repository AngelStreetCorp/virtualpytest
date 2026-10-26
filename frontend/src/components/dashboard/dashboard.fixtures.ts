/** Typed fixtures for the vitest suites only: nothing in the app imports this file. */
import type { DashboardSummary, DashboardSystem } from './dashboardTypes';

const NOW = '2026-10-18T10:00:00.000Z';

export const summaryFixture: DashboardSummary = {
  success: true,
  generated_at: NOW,
  range: '24h',
  running: {
    count: 5,
    queued: 2,
    items: Array.from({ length: 5 }, (_, i) => ({
      script_name: `script_${i}`,
      device_id: `device${i}`,
      host_name: 'vpt-pi1',
      started_at: NOW,
      result_id: `run-${i}`,
    })),
  },
  results: {
    total: 40,
    passed: 28,
    failed: 9,
    aborted: 3,
    trend: [
      { bucket_start: '2026-10-18T06:00:00Z', total: 10, passed: 9 },
      { bucket_start: '2026-10-18T07:00:00Z', total: 10, passed: 6 },
      { bucket_start: '2026-10-18T08:00:00Z', total: 20, passed: 13 },
    ],
  },
  failures: Array.from({ length: 7 }, (_, i) => ({
    result_id: `fail-${i}`,
    script_name: `failing_${i}`,
    host_name: 'vpt-pi1',
    device_id: `device${i}`,
    reason: 'timeout',
    finished_at: NOW,
  })),
  failing: [
    { script_name: 'failing_0', runs: 6, failed: 4, last_verdict: 'failed', last_at: NOW, last_result_id: 'fail-0' },
    { script_name: 'failing_1', runs: 5, failed: 1, last_verdict: 'passed', last_at: NOW, last_result_id: 'fail-1' },
  ],
  flaky: [{ script_name: 'vod_play', runs: 10, failed: 4 }],
  deployments: { active: 1, items: [{ name: 'nightly_smoke', next_run_at: '2026-10-19T02:00:00Z', state: 'active' }] },
  devices: {
    total: 18,
    free: 13,
    locked: 4,
    down: 1,
    locked_items: [{ host_name: 'vpt-pi1', device_id: 'device3', holder: 'anna', since: NOW }],
    down_items: [{ host_name: 'vpt-pi3', device_id: 'device1', device_name: 'Pixel' }],
    hosts: [
      { host_name: 'vpt-pi1', total: 12, down: 0, locked: 4 },
      { host_name: 'vpt-pi3', total: 6, down: 1, locked: 0 },
    ],
  },
};

export const systemFixture: DashboardSystem = {
  success: true,
  generated_at: NOW,
  storage: { disk_pct: 61, inode_pct: 83 },
  vms: [
    { id: 'server', name: 'Server', cpu: 12, load1: 0.4, ram: 41, disk: 52, status: 'ok', checked_at: NOW },
    { id: 'database', name: 'Database', cpu: 6, load1: 0.2, ram: 63, disk: 80, status: 'warning', checked_at: NOW },
    { id: 'storage', name: 'Storage', cpu: null, load1: null, ram: null, disk: null, status: 'stale', checked_at: NOW },
  ],
  services: { ok: 7, total: 8 },
  monitoring: { hosts_total: 12, hosts_ok: 11, problems: [{ host_name: 'vpt-pi3', detail: 'stalled 4 min' }] },
  ai_usage: { cost_7d: 12.4, top_model: 'sonnet' },
};
