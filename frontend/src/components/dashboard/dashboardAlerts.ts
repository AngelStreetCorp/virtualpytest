import { useEffect } from 'react';

import { notify, notificationStore, setActiveProblems, useNotifications, type NotificationCategory, type NotificationScope } from '../../contexts/notificationStore';

import { useI18n } from '../../i18n/useI18n';

import { DASH_LINKS } from './dashboardLinks';
import type { DashboardData } from './dashboardTypes';

export interface DashboardProblem {
  /** Distinct per problem: toasts once per episode (again after the cooldown, or when it cleared and came back). */
  id: string;
  /** Which preference row decides if it toasts / reaches the bell (TASK-145). */
  category: NotificationCategory;
  severity: 'error' | 'warning';
  /** English text = i18n key. */
  message: string;
  vars?: Record<string, string | number>;
  /** In-app page that shows the cause. */
  to: string;
  /** What it is about; a device problem carries `device_id` (`<host>/<device_id>`, unique across hosts) so one device can be muted. */
  scope?: NotificationScope;
  /** A host whose disk is full: the toast offers "Fix now" (expired capture cleanup on that host). */
  fixDiskHost?: string;
}

export const INODE_ALERT_PCT = 80;
export const FAILURE_SPIKE_MIN_RUNS = 10;
export const FAILURE_SPIKE_RATIO = 0.3;
export const AI_BUDGET_WARN_SHARE = 0.8;
export const AI_BUDGET_OVER_SHARE = 1;
export const AI_WASTE_SHARE_PCT = 20;
export const AI_WASTE_MIN_COST = 1;
export const AI_WASTE_MIN_TOKENS = 2_000_000; // when the models are unpriced

/** The problems visible in the data right now. Pure, so the thresholds are tested. */
export const detectProblems = (data: Pick<DashboardData, 'summary' | 'system'>): DashboardProblem[] => {
  const problems: DashboardProblem[] = [];
  const { summary, system } = data;
  // One notification per down device (so one noisy device can be muted on its own).
  for (const d of summary?.devices.down_items ?? []) {
    const key = `${d.host_name}/${d.device_id}`;
    problems.push({
      id: `device-down:${key}`,
      category: 'device',
      severity: 'error',
      message: '{name} is down',
      vars: { name: `${d.device_name} · ${d.host_name}` },
      to: DASH_LINKS.device(d.host_name, d.device_id),
      scope: { device_id: key, host_name: d.host_name },
    });
  }
  if (summary) {
    const { total, failed } = summary.results;
    if (total >= FAILURE_SPIKE_MIN_RUNS && failed / total >= FAILURE_SPIKE_RATIO) {
      problems.push({
        id: 'failures-spike',
        category: 'script',
        severity: 'warning',
        message: '{failed} of {total} runs failed',
        vars: { failed, total },
        // Same deep link as the Failures KPI tile: the failed runs, over the very window the counts came from.
        to: DASH_LINKS.reports({ status: 'failed', range: summary.range }),
      });
    }
  }
  if (system?.storage && system.storage.inode_pct >= INODE_ALERT_PCT) {
    problems.push({ id: 'inodes-high', category: 'storage', severity: 'warning', message: 'Storage inodes are at {pct} %', vars: { pct: Math.round(system.storage.inode_pct) }, to: '/status' });
  }
  for (const p of system?.monitoring?.problems ?? []) {
    problems.push({
      id: `monitoring:${p.host_name}`,
      // Offline / disk full is the host; anything else is capture or the stream pipeline.
      category: p.detail === 'offline' || p.detail.startsWith('disk') ? 'host' : 'capture',
      severity: p.severity ?? 'error',
      message: 'Monitoring problem on {hosts}: {detail}',
      vars: { hosts: p.host_name, detail: p.detail },
      to: `/status?host=${encodeURIComponent(p.host_name)}`,
      ...(p.detail.startsWith('disk') ? { fixDiskHost: p.host_name } : {}),
    });
  }
  const budget = system?.ai_usage?.budget;
  if (budget && budget.share >= AI_BUDGET_WARN_SHARE) {
    const over = budget.share >= AI_BUDGET_OVER_SHARE;
    problems.push({
      id: over ? 'ai-budget-over' : 'ai-budget-warn',
      category: 'ai_spend',
      severity: over ? 'error' : 'warning',
      message: over ? 'AI budget {label} is used up ({pct} %)' : 'AI budget {label} is at {pct} %',
      vars: { label: budget.label, pct: Math.round(budget.share * 100) },
      to: '/monitoring/ai-usage',
    });
  }
  const waste = system?.ai_usage?.waste;
  if (waste && waste.share_pct >= AI_WASTE_SHARE_PCT) {
    const priced = waste.cost !== null && waste.spend !== null;
    if (priced ? (waste.cost as number) >= AI_WASTE_MIN_COST : waste.tokens >= AI_WASTE_MIN_TOKENS) {
      problems.push({
        id: `ai-waste:${new Date().toISOString().slice(0, 10)}`,
        category: 'ai_spend',
        severity: 'warning',
        message: priced ? '${wasted} of ${spend} AI spend wasted today ({pct} %)' : '{tokens} AI tokens wasted today ({pct} %)',
        vars: priced
          ? { wasted: (waste.cost as number).toFixed(2), spend: (waste.spend as number).toFixed(2), pct: Math.round(waste.share_pct) }
          : { tokens: waste.tokens.toLocaleString('en-US'), pct: Math.round(waste.share_pct) },
        to: '/monitoring/ai-usage',
      });
    }
  }
  return problems;
};

export const REALERT_MS = 30 * 60 * 1000;

/** When each open problem last toasted (module scope: survives tab switches and remounts). */
const lastShown = new Map<string, number>();
export const resetShownProblems = () => lastShown.clear();

/** Which problems to toast now: new ones, and still-open ones whose last toast is older than the cooldown. Forgets cleared ones. */
export const dueProblems = (problems: DashboardProblem[], seen: Map<string, number>, now: number): DashboardProblem[] => {
  const open = new Set(problems.map((p) => p.id));
  for (const id of Array.from(seen.keys())) if (!open.has(id)) seen.delete(id);
  const due = problems.filter((p) => {
    const at = seen.get(p.id);
    return at === undefined || now - at >= REALERT_MS;
  });
  for (const p of due) seen.set(p.id, now);
  return due;
};

/**
 * TASK-100: which `dash-*` notifications should be auto-resolved on this poll (the underlying
 * problem is no longer in the live set). Pure; the actual `notificationStore.resolve()` call is
 * performed by the caller for each id.
 */
export const staleDashIds = (
  stored: ReadonlyArray<{ id: string; resolved_at?: number | null }>,
  liveIds: ReadonlySet<string>,
): string[] =>
  stored
    .filter((n) => n.id.startsWith('dash-') && typeof n.resolved_at !== 'number' && !liveIds.has(n.id))
    .map((n) => n.id);

/** One notification per problem episode (toast only where the viewer's preferences say so, bell by default). */
export const useDashboardAlerts = (data: DashboardData, fixDisk?: (host: string) => void) => {
  const { t } = useI18n();
  const stored = useNotifications();
  useEffect(() => {
    const problems = detectProblems(data);
    setActiveProblems(
      problems.filter((p) => p.id.startsWith('monitoring:')).map((p) => ({ id: p.id, message: t(p.message, p.vars), to: p.to })),
    );
    for (const problem of dueProblems(problems, lastShown, Date.now())) {
      notify({
        id: `dash-${problem.id}`,
        category: problem.category,
        severity: problem.severity,
        message: t(problem.message, problem.vars),
        to: problem.to,
        scope: problem.scope,
        duration: 8000,
        action: problem.fixDiskHost && fixDisk
          ? { label: t('Fix now'), onClick: () => fixDisk(problem.fixDiskHost as string) }
          : { label: t('Show'), to: problem.to },
      });
    }
  }, [data, t, fixDisk]);
  // TASK-100: between polls, mark any `dash-*` entry whose problem is no longer detected as resolved.
  // The companion `lastShown` map (above) already tracks which ids have been seen, so a *new* problem
  // would just re-`notify()` and `addToList` would clear `resolved_at`.
  useEffect(() => {
    const liveIds = new Set(detectProblems(data).map((p) => `dash-${p.id}`));
    for (const id of staleDashIds(stored, liveIds)) notificationStore.resolve(id);
    notificationStore.purgeOlderThan();
  }, [data, stored]);
  // Leaving the dashboard drops the chip and lets a reopened dashboard toast a still-open problem again.
  useEffect(
    () => () => {
      lastShown.clear();
      setActiveProblems([]);
    },
    [],
  );
};
