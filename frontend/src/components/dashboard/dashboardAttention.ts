import { INODE_ALERT_PCT } from './dashboardAlerts';
import { DASH_LINKS } from './dashboardLinks';
import type { TranslateFn } from './dashboardLayout';
import { formatAgo } from './dashboardFormat';
import type { DashboardData, DashboardSummary } from './dashboardTypes';

export interface AttentionItem {
  id: string;
  tone: 'error' | 'warning';
  /** Already translated or a data name (script, host, device). */
  name: string;
  /** Already translated: the word that says what is wrong. */
  detail: string;
  to: string;
}

export interface DeviceAttentionItem extends Omit<AttentionItem, 'tone'> {
  /** `muted` = a plain lock held for a normal time. */
  tone: AttentionItem['tone'] | 'muted';
}

export const LONG_LOCK_HOURS = 4;
/** A script that failed at least this share of its runs (and twice or more) is a spike, not a one-off. */
export const SPIKE_RATIO = 0.5;
const MAX_ITEMS = 50;
const HIGH_PCT = 80;
const CRITICAL_PCT = 90;

const levelTone = (pct: number): 'error' | 'warning' | null => (pct >= CRITICAL_PCT ? 'error' : pct >= HIGH_PCT ? 'warning' : null);

/**
 * Everything that needs a person right now, worst first: devices down, hosts with monitoring trouble and
 * machines past 80 % (admin data only), scripts that keep failing. Pure, so the order and thresholds are tested.
 */
export const buildAttention = (data: Pick<DashboardData, 'summary' | 'system'>, t: TranslateFn): AttentionItem[] => {
  const items: AttentionItem[] = [];
  const { summary, system } = data;
  for (const d of summary?.devices.down_items ?? []) {
    items.push({ id: `down:${d.host_name}/${d.device_id}`, tone: 'error', name: `${d.device_name} · ${d.host_name}`, detail: t('down'), to: DASH_LINKS.devices });
  }
  for (const p of system?.monitoring?.problems ?? []) {
    items.push({ id: `mon:${p.host_name}`, tone: p.severity ?? 'error', name: p.host_name, detail: p.detail, to: DASH_LINKS.status });
  }
  for (const vm of system?.vms ?? []) {
    if (vm.status === 'stale') {
      items.push({ id: `vm:${vm.id}`, tone: 'error', name: vm.name, detail: t('stale'), to: DASH_LINKS.status });
      continue;
    }
    const worst: Array<[string, number | null]> = [[t('CPU'), vm.cpu], [t('RAM'), vm.ram], [t('Disk'), vm.disk]];
    const [label, value] = worst.reduce((a, b) => ((b[1] ?? -1) > (a[1] ?? -1) ? b : a));
    const tone = value === null ? null : levelTone(value);
    if (tone && value !== null) items.push({ id: `vm:${vm.id}`, tone, name: vm.name, detail: `${label} ${Math.round(value)} %`, to: DASH_LINKS.status });
  }
  if (system?.storage && system.storage.inode_pct >= INODE_ALERT_PCT) {
    items.push({ id: 'inodes', tone: levelTone(system.storage.inode_pct) ?? 'warning', name: t('Inodes'), detail: `${Math.round(system.storage.inode_pct)} %`, to: DASH_LINKS.status });
  }
  for (const f of summary?.failing ?? []) {
    const spike = f.failed >= 2 && f.failed / f.runs >= SPIKE_RATIO;
    items.push({
      id: `script:${f.script_name}`,
      tone: spike ? 'error' : 'warning',
      name: f.script_name,
      detail: t('{failed} of {runs} failed', { failed: f.failed, runs: f.runs }),
      to: DASH_LINKS.report(f.last_result_id),
    });
  }
  const rank = (i: AttentionItem) => (i.tone === 'error' ? 0 : 1);
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item) - rank(b.item) || a.index - b.index)
    .map((e) => e.item)
    .slice(0, MAX_ITEMS);
};

/** Devices that need a person: down ones first, then locks held longer than LONG_LOCK_HOURS, then every other lock. */
export const buildDeviceAttention = (summary: DashboardSummary, now: number, t: TranslateFn): DeviceAttentionItem[] => {
  const down: DeviceAttentionItem[] = summary.devices.down_items.map((d) => ({
    id: `down:${d.host_name}/${d.device_id}`,
    tone: 'error',
    name: `${d.device_name} · ${d.host_name}`,
    detail: t('down'),
    to: DASH_LINKS.devices,
  }));
  const locks = summary.devices.locked_items.map((l) => ({
    long: Boolean(l.since) && now - new Date(l.since as string).getTime() >= LONG_LOCK_HOURS * 3_600_000,
    item: {
      id: `lock:${l.host_name}/${l.device_id}`,
      tone: 'muted' as const,
      name: `${l.device_id} · ${l.host_name}`,
      detail: `${l.holder} · ${formatAgo(l.since, now, t)}`,
      to: DASH_LINKS.devices,
    },
  }));
  return [
    ...down,
    ...locks.filter((l) => l.long).map((l) => ({ ...l.item, tone: 'warning' as const })),
    ...locks.filter((l) => !l.long).map((l) => l.item),
  ];
};
