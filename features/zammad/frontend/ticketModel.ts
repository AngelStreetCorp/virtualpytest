/**
 * The ticket model (TASK-96): the same enums as features/zammad/lib/model.py, which validates them on the
 * server. Keys only - the words are in useTicketLabels.ts so every one goes through t().
 */

export const TICKET_TYPES = ['incident', 'bug', 'request', 'question'] as const;
export type TicketType = (typeof TICKET_TYPES)[number];

/** Request and Question carry no severity. */
export const SEVERITY_TYPES: readonly TicketType[] = ['incident', 'bug'];
export const SEVERITIES = ['blocker', 'major', 'minor'] as const;
export type Severity = (typeof SEVERITIES)[number];

/** Set by the reporter on every type; P1 is preselected. */
export const PRIORITIES = ['P0', 'P1', 'P2'] as const;
export type Priority = (typeof PRIORITIES)[number];
export const DEFAULT_PRIORITY: Priority = 'P1';

export const FREQUENCIES = ['always', 'frequent', 'random', 'once'] as const;
export type Frequency = (typeof FREQUENCIES)[number];

export const FAMILIES = {
  platform: ['server', 'host', 'device', 'service'],
  scripting: ['script', 'campaign', 'virtual_script', 'testcase'],
  monitoring: ['heatmap', 'timeline', 'incident'],
  dashboards: ['grafana', 'report'],
  ai: ['agent'],
} as const;
export type Family = keyof typeof FAMILIES;
export type Category = (typeof FAMILIES)[Family][number];
export const FAMILY_KEYS = Object.keys(FAMILIES) as Family[];

/** The simplified status the reporter sees (GET /tickets sends it as `reporter_status`). */
export type ReporterStatus = 'open' | 'in_progress' | 'waiting' | 'delivered' | 'closed';

/** A pickable thing a ticket is about; `id` is what the support team searches for, `label` what the user reads. */
export interface TicketTarget {
  id: string;
  label: string;
}

/** What a caller of `useReportIncident().open()` may say about the thing it is opened from. */
export interface TicketContext {
  family?: Family;
  category?: Category;
  targetId?: string;
  targetLabel?: string;
}
