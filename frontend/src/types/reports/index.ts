/**
 * Run management (TASK-42) — the frontend contract.
 *
 * Every endpoint path, request body and response shape the run-management UI depends on
 * lives in this file, so a backend contract change is reconciled in one place. The API
 * functions in `hooks/reports/runManagementApi.ts` are the only code that calls these
 * endpoints; pages and widgets only consume the types.
 *
 * Status values are evidence-backed only: a value the server sends that is not one of
 * RUN_STATUSES renders as 'unknown', never as failed or passed.
 */

import type { Permission } from '../auth';

// ---------------------------------------------------------------------------
// Identity and status
// ---------------------------------------------------------------------------

export const RUN_KINDS = ['script', 'campaign', 'group'] as const;
export type RunKind = (typeof RUN_KINDS)[number];

/** `campaign` ids are campaign EXECUTION ids (one run of a campaign), not template ids. */
export interface RunIdentity {
  kind: RunKind;
  id: string;
}

export const isRunKind = (value: unknown): value is RunKind =>
  typeof value === 'string' && (RUN_KINDS as readonly string[]).includes(value);

export const RUN_STATUSES = [
  'passed',
  'failed',
  'running',
  'pending',
  'skipped',
  'cancelled',
  'unknown',
] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const TERMINAL_STATUSES: readonly RunStatus[] = ['passed', 'failed', 'skipped', 'cancelled'];

/** Map a server status string to a RunStatus. Anything unrecognised is 'unknown'. */
export const toRunStatus = (raw: unknown): RunStatus => {
  if (typeof raw !== 'string') return 'unknown';
  const value = raw.trim().toLowerCase();
  return (RUN_STATUSES as readonly string[]).includes(value) ? (value as RunStatus) : 'unknown';
};

export const isTerminalStatus = (status: RunStatus): boolean => TERMINAL_STATUSES.includes(status);

/**
 * Verdict of a raw script_results row, the server's rule: a row is inserted at start with
 * success=false and no duration, so `false` only means failed once the run recorded an
 * execution time. Before that the run may still be going (or was abandoned): unknown.
 */
export const scriptResultStatus = (row: { success?: boolean | null; execution_time_ms?: number | null }): RunStatus => {
  if (row.success === true) return 'passed';
  if (row.success === false && row.execution_time_ms !== null && row.execution_time_ms !== undefined) return 'failed';
  return 'unknown';
};

export type RunStatusCounts = Record<RunStatus, number> & { total: number };

export const emptyCounts = (): RunStatusCounts => ({
  total: 0,
  passed: 0,
  failed: 0,
  running: 0,
  pending: 0,
  skipped: 0,
  cancelled: 0,
  unknown: 0,
});

/** Normalise a counts object from the server: missing keys are 0, total is kept as sent. */
export const toCounts = (raw: Partial<Record<string, unknown>> | null | undefined): RunStatusCounts => {
  const out = emptyCounts();
  if (!raw) return out;
  for (const key of RUN_STATUSES) {
    const value = raw[key];
    out[key] = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  }
  const total = raw.total;
  out.total =
    typeof total === 'number' && Number.isFinite(total)
      ? total
      : RUN_STATUSES.reduce((sum, key) => sum + out[key], 0);
  return out;
};

// ---------------------------------------------------------------------------
// Permissions — the names the backend permission catalog grants. Reads reuse the
// existing Test Reports permission; writes have their own entries in types/auth.ts.
// ---------------------------------------------------------------------------

export const REPORT_PERMISSIONS = {
  view: 'reports.tests:view',
  edit: 'reports.runs:edit',
  defects: 'reports.defects:edit',
  share: 'reports.share:create',
  manual: 'reports.manual:execute',
  rerun: 'execution.run:run_test',
  stop: 'execution.run:run_test',
} as const satisfies Record<string, Permission>;

// ---------------------------------------------------------------------------
// Governance limits (mirrored from the server; the server stays the authority)
// ---------------------------------------------------------------------------

export const LABEL_NAME_MAX = 20;
export const LABELS_PER_ENTITY_MAX = 10;
export const GOVERNANCE_NAME_MAX = 100;

export const SHARE_TTL_DEFAULT_DAYS = 7;
export const SHARE_TTL_MAX_DAYS = 90;

export const LIVE_POLL_INTERVAL_MS = 2000;

export const QUALITY_DEFAULT_WINDOW = { flaky: 14, slow: 30, notExecuted: 30 } as const;
export const QUALITY_WINDOW_OPTIONS = [7, 14, 30, 60, 90] as const;
export const SUMMARY_TREND_DAYS = 30;

// ---------------------------------------------------------------------------
// Endpoint paths
// ---------------------------------------------------------------------------

const seg = (value: string | number) => encodeURIComponent(String(value));

export const ENDPOINTS = {
  summary: (kind: RunKind, id: string) => `/server/run-management/summary/${seg(kind)}/${seg(id)}`,
  query: () => '/server/run-management/query',
  live: (taskId: string) => `/server/run-management/live/${seg(taskId)}`,
  liveStop: (taskId: string) => `/server/run-management/live/${seg(taskId)}/stop`,

  runGroups: () => '/server/run-groups',
  runGroup: (id: string) => `/server/run-groups/${seg(id)}`,
  runGroupArchive: (id: string) => `/server/run-groups/${seg(id)}/archive`,
  runGroupRestore: (id: string) => `/server/run-groups/${seg(id)}/restore`,
  runGroupReport: (id: string) => `/server/run-groups/${seg(id)}/report`,
  runGroupRerun: (id: string) => `/server/run-groups/${seg(id)}/rerun`,

  milestones: () => '/server/milestones',
  milestone: (id: string) => `/server/milestones/${seg(id)}`,
  milestoneArchive: (id: string) => `/server/milestones/${seg(id)}/archive`,
  milestoneRestore: (id: string) => `/server/milestones/${seg(id)}/restore`,

  labels: () => '/server/run-labels',
  label: (id: string) => `/server/run-labels/${seg(id)}`,

  resultLabels: (resultId: string) => `/server/script-results/${seg(resultId)}/labels`,
  resultMilestone: (resultId: string) => `/server/script-results/${seg(resultId)}/milestone`,
  resultRunGroup: (resultId: string) => `/server/script-results/${seg(resultId)}/run-group`,
  batchAssignments: () => '/server/script-results/batch/assignments',
  testcaseLabels: (testcaseId: string) => `/server/testcase/${seg(testcaseId)}/labels`,

  defects: () => '/server/defects',
  defect: (id: string) => `/server/defects/${seg(id)}`,
  defectEvidence: (id: string) => `/server/defects/${seg(id)}/evidence`,
  defectPushJira: (id: string) => `/server/defects/${seg(id)}/push-jira`,
  defectRefreshJira: (id: string) => `/server/defects/${seg(id)}/refresh-jira`,

  flaky: () => '/server/script-results/flaky',
  slow: () => '/server/script-results/slow',
  notExecuted: () => '/server/script-results/never-executed',

  tql: () => '/server/tql',
  customReports: () => '/server/custom-reports',
  customReport: (id: string) => `/server/custom-reports/${seg(id)}`,

  shareSnapshots: () => '/server/run-share-snapshots',
  shareSnapshot: (id: string) => `/server/run-share-snapshots/${seg(id)}`,
  publicShare: (snapshotId: string) => `/server/share/run/${seg(snapshotId)}`,

  manualSessions: () => '/server/manual-sessions',
  manualSession: (id: string) => `/server/manual-sessions/${seg(id)}`,
  manualFinalize: (id: string) => `/server/manual-sessions/${seg(id)}/finalize`,

  // Existing endpoints reused by this surface
  scriptResults: () => '/server/script-results/getAllScriptResults',
  testcaseList: () => '/server/testcase/list',
  testcaseVersions: (testcaseId: string) => `/server/testcase/${seg(testcaseId)}/versions`,
} as const;

/** The header carrying a share token on the public snapshot read. */
export const SHARE_TOKEN_HEADER = 'X-Share-Token';

// ---------------------------------------------------------------------------
// Scope — the active workspace's host names, applied server-side before limits
// (same `host_filter` parameter TestReports sends to getAllScriptResults).
// ---------------------------------------------------------------------------

export interface ReportScope {
  /** Host names of the active workspace; undefined when no workspace narrows the view. */
  hostFilter?: string[];
  /** The workspace's `host_name:device_id` keys; the server maps them to device names. */
  deviceFilter?: string[];
  /** Selected backend server; part of every cache key so a server switch refetches. */
  serverKey: string;
}

// ---------------------------------------------------------------------------
// Governance objects
// ---------------------------------------------------------------------------

export interface RunLabel {
  id: string;
  name: string;
  color: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface RunGroup {
  id: string;
  name: string;
  description: string | null;
  color: string | null;
  pinned: boolean;
  archived: boolean;
  created_at: string;
  updated_at: string;
  /** Only on the group report: distinct logical tests (latest attempt per identity). */
  member_count?: number;
  /** Only on the group report: every attempt linked to the group. */
  attempt_count?: number;
}

export interface Milestone {
  id: string;
  name: string;
  description: string | null;
  due_at: string | null;
  completed_at: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface Paged<T> {
  items: T[];
  next_cursor?: string | null;
  total?: number | null;
}

export interface RunGroupInput {
  name?: string;
  description?: string | null;
  color?: string | null;
  pinned?: boolean;
}

export interface MilestoneInput {
  name?: string;
  description?: string | null;
  due_at?: string | null;
  completed_at?: string | null;
}

export interface LabelInput {
  name: string;
  color?: string | null;
}

/** DELETE /server/run-labels/:id — the definition and its assignments; results untouched. */
export interface DeleteLabelResponse {
  removed_script_result_assignments: number;
  removed_testcase_assignments: number;
}

export interface BatchAssignmentInput {
  script_result_ids: string[];
  /** Omit to leave unchanged; null clears. */
  milestone_id?: string | null;
  /** Omit to leave unchanged; null clears. */
  run_group_id?: string | null;
  /** Omit to leave unchanged; replaces the label set of every selected result. */
  label_ids?: string[];
}

export interface BatchAssignmentResponse {
  updated: number;
  script_result_ids: string[];
}

// ---------------------------------------------------------------------------
// Run summary — GET ENDPOINTS.summary(kind, id)?limit&offset&status&trend_days
// ---------------------------------------------------------------------------

/** One child of a run: an execution (script_results row) or a campaign entry. */
export interface RunChild {
  /** script_results id; null for a campaign entry that never produced a result. */
  script_result_id: string | null;
  name: string;
  script_type: string | null;
  status: RunStatus;
  userinterface_name: string | null;
  environment: string | null;
  host_name: string | null;
  device_name: string | null;
  started_at: string | null;
  completed_at: string | null;
  execution_time_ms: number | null;
  discard: boolean;
  /** Group summaries: number of attempts for this logical identity. */
  attempts?: number | null;
  /** Campaign summaries: planned position, and why a child is skipped / unknown. */
  position?: number | null;
  skip_reason?: string | null;
  unknown_reason?: string | null;
  report_url?: string | null;
  logs_url?: string | null;
}

export interface TrendPoint {
  /** UTC day, YYYY-MM-DD. The server zero-fills empty days. */
  day: string;
  passed: number;
  failed: number;
  /** Terminal attempts that are neither passed nor failed (skipped, cancelled). */
  other: number;
  /** Denominator: every eligible attempt of the day. */
  total: number;
}

export interface RunSummaryEvidence {
  report_url: string | null;
  logs_url: string | null;
  /** Verification/step evidence when the run recorded it; null when it did not. */
  steps: { total: number; passed: number; failed: number } | null;
}

export interface RunSummaryMetadata {
  script_type?: string | null;
  userinterface_name?: string | null;
  environment?: string | null;
  host_name?: string | null;
  device_name?: string | null;
  executed_by?: string | null;
  campaign_name?: string | null;
  error?: string | null;
  milestone?: { id: string; name: string } | null;
  run_group?: { id: string; name: string } | null;
  labels?: RunLabel[];
}

export interface RunSummaryResponse {
  identity: RunIdentity;
  title: string;
  status: RunStatus;
  started_at: string | null;
  completed_at: string | null;
  execution_time_ms: number | null;
  /** Counts over ALL children, computed before pagination. */
  counts: RunStatusCounts;
  children: {
    items: RunChild[];
    total: number;
    limit: number;
    offset: number;
  };
  trend: {
    window_days: number;
    points: TrendPoint[];
    /** Attempts left out of the denominators (discarded, not terminal). */
    excluded?: { discarded: number; not_terminal: number };
  };
  metadata: RunSummaryMetadata;
  evidence: RunSummaryEvidence;
  /** Group summaries: counts over EVERY attempt, next to the latest-per-identity counts. */
  attempts?: RunStatusCounts;
  generated_at?: string;
}

export interface RunSummaryParams {
  limit: number;
  offset: number;
  status?: RunStatus | null;
  trendDays?: number;
}

// ---------------------------------------------------------------------------
// Group report and rerun
// ---------------------------------------------------------------------------

export interface GroupReportRow extends RunChild {
  attempts: number;
}

export interface RerunPreview {
  targets: number;
  skipped: RerunSkip[];
}

export interface GroupReportResponse {
  group: RunGroup;
  /** Rollup over the LATEST attempt of each logical identity. */
  counts: RunStatusCounts;
  attempts_total: number;
  /** Counts over every attempt. */
  attempts: RunStatusCounts;
  rows: GroupReportRow[];
  rerun_preview?: { all: RerunPreview; failures: RerunPreview };
}

export type RerunMode = 'all' | 'failures';

export interface RerunRequest {
  mode: RerunMode;
  idempotency_key: string;
}

export interface RerunSkip {
  script_result_id?: string | null;
  script_name?: string | null;
  /** e.g. manual_run, discarded, not_failed, no_rerun_payload, testcase_rerun_not_dispatchable_from_server */
  reason: string;
}

/**
 * Each dispatched item is a queued one-shot deployment of the source attempt. There is
 * no live task id at dispatch time (`task_id` is always null): the new result appears in
 * TestReports when the host has run it.
 */
export interface RerunResponse {
  request_id: string | null;
  status: string | null;
  /** True when the server recognised the idempotency key and returned the first dispatch. */
  idempotent_replay: boolean;
  dispatched: Array<{ script_result_id: string; deployment_id?: string | null; task_id: null }>;
  skipped_manual: string[];
  skipped_not_in_mode: string[];
  skipped: RerunSkip[];
  error?: string | null;
}

// ---------------------------------------------------------------------------
// Defects
// ---------------------------------------------------------------------------

export const DEFECT_SEVERITIES = ['critical', 'high', 'medium', 'low'] as const;
export type DefectSeverity = (typeof DEFECT_SEVERITIES)[number];
export const DEFECT_STATUSES = ['open', 'in_progress', 'resolved', 'closed'] as const;
export type DefectStatus = (typeof DEFECT_STATUSES)[number];

export interface Defect {
  id: string;
  title: string;
  description?: string | null;
  severity: DefectSeverity;
  status: DefectStatus;
  integration: 'local' | 'jira';
  assignee?: string | null;
  external_key: string | null;
  external_url: string | null;
  external_status?: string | null;
  external_updated_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DefectInput {
  title?: string;
  description?: string | null;
  severity?: DefectSeverity;
  status?: DefectStatus;
}

export interface DefectListParams {
  status?: DefectStatus | null;
  severity?: DefectSeverity | null;
  script_result_id?: string | null;
}

/** Push is idempotent per defect on the server (one push record per defect). */
export interface JiraPushResponse {
  state: 'created';
  external_key: string;
  external_url: string | null;
  idempotent: boolean;
}

export interface JiraRefreshResponse {
  applied: boolean;
  status: DefectStatus;
  external_status: string | null;
  external_updated_at: string | null;
  stale: boolean;
  defect: Defect;
}

// ---------------------------------------------------------------------------
// Quality (flaky / slow / not executed in window)
// ---------------------------------------------------------------------------

/** The comparable identity: attempts are only compared within one of these. */
export interface QualityIdentity {
  script_name: string;
  script_type: string | null;
  userinterface_name: string | null;
  environment: string | null;
  host_name: string | null;
  device_name: string | null;
}

export interface QualityWindow {
  window_days: number;
  window_start: string;
  window_end: string;
  /** Eligible attempts examined (terminal, not discarded). */
  sample_size: number;
  /** Minimum attempts an identity needs before it is ranked. */
  min_attempts: number;
  row_total: number;
  scope: { host_count: number; device_filter_applied: boolean };
  /** Flaky: identities with enough attempts that were examined. */
  identities_evaluated?: number;
  /** Not executed: size of the runnable catalog compared against the window. */
  runnable_total?: number;
}

export interface FlakyRow {
  identity: QualityIdentity;
  attempts: number;
  passes: number;
  failures: number;
  transitions: number;
  /** transitions / (attempts - 1), 0..1. */
  flaky_score: number | null;
  last_status: RunStatus;
  first_started_at: string | null;
  last_started_at: string | null;
  latest_script_result_id: string | null;
}

export interface SlowRow {
  identity: QualityIdentity;
  sample_count: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number | null;
  last_started_at: string | null;
  latest_script_result_id: string | null;
}

export interface NotExecutedRow {
  script_name: string;
  script_type: 'script' | 'testcase';
  testcase_id: string | null;
  userinterface_name: string | null;
  environment: string | null;
  /** Always null: the server only knows the test did not run in the window. */
  last_executed_at: null;
}

export interface QualityResponse<Row> extends QualityWindow {
  rows: Row[];
}

export interface QualityParams {
  windowDays: number;
  limit?: number;
}

// ---------------------------------------------------------------------------
// TQL, structured query, custom reports
// ---------------------------------------------------------------------------

export interface TqlValidation {
  ok: boolean;
  error?: string | null;
  /** 0-based character offset of the error, when the parser reports one. */
  position?: number | null;
  clauses?: Array<{ key: string; value: string; start: number; end: number }>;
}

export const REPORT_FILTER_SCHEMA_VERSION = 1;

export const REPORT_COLUMNS = [
  'id',
  'script_name',
  'script_type',
  'status',
  'userinterface_name',
  'environment',
  'host_name',
  'device_name',
  'started_at',
  'completed_at',
  'execution_time_ms',
  'discard',
  'milestone',
  'run_group',
  'labels',
] as const;
export type ReportColumn = (typeof REPORT_COLUMNS)[number];

export const REPORT_COLUMN_LABELS: Record<ReportColumn, string> = {
  id: 'Result id',
  script_name: 'Test',
  script_type: 'Type',
  completed_at: 'Completed',
  discard: 'Discarded',
  status: 'Status',
  userinterface_name: 'UI',
  environment: 'Environment',
  host_name: 'Host',
  device_name: 'Device',
  started_at: 'Started',
  execution_time_ms: 'Duration (ms)',
  milestone: 'Milestone',
  run_group: 'Group',
  labels: 'Labels',
};

export const REPORT_CHART_TYPES = ['none', 'status_by_day', 'status_by_group', 'status_share'] as const;
export type ReportChartType = (typeof REPORT_CHART_TYPES)[number];

export const REPORT_CHART_LABELS: Record<ReportChartType, string> = {
  none: 'No chart',
  status_by_day: 'Status by day',
  status_by_group: 'Status by field',
  status_share: 'Status share',
};

export const REPORT_GROUP_BY = ['script_name', 'host_name', 'device_name', 'userinterface_name', 'environment'] as const;
export type ReportGroupBy = (typeof REPORT_GROUP_BY)[number];

export interface ReportChartSpec {
  type: ReportChartType;
  /** Only for status_by_group. */
  group_by?: ReportGroupBy;
}

export interface ReportFilter {
  schema_version: number;
  tql: string;
}

export interface ReportQueryRequest {
  filter: ReportFilter;
  columns: ReportColumn[];
  chart: ReportChartSpec;
  limit: number;
  offset: number;
}

export interface ReportChartPoint {
  /** Day (status_by_day) or field value (status_by_group). */
  x: string;
  passed: number;
  failed: number;
  other: number;
}

/** Table, counts and chart are produced by the server from ONE validated filter. */
export interface ReportQueryResponse {
  columns: ReportColumn[];
  /** Each row holds the requested columns plus `script_result_id` (evidence link). */
  rows: Array<Record<string, string | number | boolean | null> & { script_result_id: string }>;
  total: number;
  counts: RunStatusCounts;
  chart: { type: ReportChartType; group_by?: ReportGroupBy | null; points: ReportChartPoint[] };
  /** The resolved time window (TQL since/until, default 30 days). */
  window: { since: string; until: string };
  limit: number;
  offset: number;
}

export interface CustomReport {
  id: string;
  name: string;
  created_by: string | null;
  filter: ReportFilter;
  columns: ReportColumn[];
  chart: ReportChartSpec;
  created_at: string;
  updated_at: string;
  /** False when the stored definition no longer validates (e.g. old schema_version). */
  valid: boolean;
  validation_error?: { error: string; position?: number; field?: string } | null;
}

export interface CustomReportInput {
  name: string;
  filter: ReportFilter;
  columns: ReportColumn[];
  chart: ReportChartSpec;
}

// ---------------------------------------------------------------------------
// Share snapshots
// ---------------------------------------------------------------------------

export interface ShareSnapshotMeta {
  id: string;
  run_kind: RunKind;
  run_id: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
}

export interface CreateShareRequest {
  run_kind: RunKind;
  run_id: string;
  ttl_days: number;
}

/** The plaintext token is returned exactly once, here. */
export interface CreateShareResponse {
  snapshot: ShareSnapshotMeta;
  token: string;
}

export interface ShareRevokeResponse {
  revoked: boolean;
  snapshot: ShareSnapshotMeta;
}

/** Allowlisted, sanitized payload stored in the snapshot. */
export interface SharePayload {
  title: string;
  status: RunStatus;
  counts: RunStatusCounts;
  durations: {
    started_at: string | null;
    completed_at: string | null;
    execution_time_ms: number | null;
  };
  safe_labels: string[];
  rows: Array<{ name: string; status: RunStatus; execution_time_ms: number | null }>;
  /** True when the snapshot kept only the first rows of a large run. */
  rows_truncated?: boolean;
  generated_at?: string;
}

export interface PublicShareResponse {
  snapshot: {
    id: string;
    run_kind: RunKind;
    created_at: string;
    expires_at: string;
    payload: SharePayload;
  };
}

// ---------------------------------------------------------------------------
// Manual sessions
// ---------------------------------------------------------------------------

export const MANUAL_STEP_OUTCOMES = ['passed', 'failed', 'skipped', 'blocked'] as const;
export type ManualStepOutcome = (typeof MANUAL_STEP_OUTCOMES)[number];

export interface ManualStep {
  ordinal: number;
  label: string;
  /** Finalize is refused (422) while a required step has no outcome. */
  required: boolean;
  /** What the tester should observe, copied from the testcase snapshot when present. */
  expected: string | null;
  outcome: ManualStepOutcome | null;
  note: string | null;
  /** Optional evidence reference (URL); null means no evidence was attached. */
  evidence_url: string | null;
  evidence_missing?: boolean;
  updated_by?: string | null;
  updated_at?: string | null;
}

export type ManualSessionStatus = 'in_progress' | 'finalizing' | 'finalized' | 'abandoned';

export interface ManualSession {
  id: string;
  status: ManualSessionStatus;
  testcase_id: string | null;
  testcase_name: string | null;
  testcase_version: number | null;
  actor_id: string | null;
  /** Not resolved by the server today (always null); show the actor id instead. */
  actor_name: string | null;
  host_name: string;
  device_name: string;
  environment: string | null;
  notes?: string | null;
  /** Optimistic concurrency token; send it back as expected_version. */
  optimistic_version: number;
  started_at: string;
  updated_at: string;
  finalized_at: string | null;
  /** The single script_results row produced by finalize. */
  script_result_id: string | null;
  steps: ManualStep[];
  summary?: {
    steps_total: number;
    steps_passed: number;
    steps_failed: number;
    steps_skipped: number;
    steps_blocked: number;
    required_without_outcome: number;
    steps_without_evidence: number;
  };
}

/** GET /server/manual-sessions rows: the caller's sessions, without steps or snapshot. */
export type ManualSessionListItem = Omit<ManualSession, 'steps' | 'summary' | 'actor_name'>;

/** host_name + device_name (display name) of a registered device in scope are required. */
export interface CreateManualSessionRequest {
  testcase_id: string;
  idempotency_key: string;
  host_name: string;
  device_name: string;
}

export interface UpdateManualSessionRequest {
  expected_version: number;
  steps: Array<Pick<ManualStep, 'ordinal' | 'outcome' | 'note' | 'evidence_url'>>;
}

/** Finalize is idempotent per session on the server: a repeat returns the same result id. */
export interface FinalizeManualSessionRequest {
  expected_version: number;
}

export interface FinalizeManualSessionResponse {
  session: ManualSession;
  script_result_id: string;
  idempotent: boolean;
}

// ---------------------------------------------------------------------------
// Live run status
// ---------------------------------------------------------------------------

export interface LiveRunStatus {
  task_id: string;
  status: RunStatus;
  /** The server has not heard from the producer recently; the status may be outdated. */
  stale: boolean;
  script_name: string | null;
  host_name: string | null;
  device_name: string | null;
  started_at: string | null;
  elapsed_ms: number | null;
  progress: { completed: number | null; total: number | null; message?: string | null } | null;
  eta_ms: number | null;
  updated_at: string | null;
  /** Durable result once one exists — the hand-off target. */
  script_result_id: string | null;
  /** A stop was requested and the host has not finished yet. */
  stop_requested: boolean;
  /** Whether the caller may stop this task (permission + team + scope, decided server-side). */
  can_stop: boolean;
}

/** 202 `{success: true, status: 'running', stop_requested: true}`; the task ends later. */
export interface LiveStopResponse {
  success: boolean;
  status: RunStatus;
  stop_requested?: boolean;
  error?: string;
}

// ---------------------------------------------------------------------------
// Testcase versions (existing endpoint; graph payload as stored)
// ---------------------------------------------------------------------------

export interface TestcaseGraphNode {
  id: string;
  type?: string;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TestcaseGraphEdge {
  id?: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  type?: string;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TestcaseGraph {
  nodes?: TestcaseGraphNode[];
  edges?: TestcaseGraphEdge[];
  [key: string]: unknown;
}

export interface TestcaseVersion {
  version_number: number;
  testcase_name?: string | null;
  description?: string | null;
  userinterface_name?: string | null;
  graph_json?: TestcaseGraph | string | null;
  modified_at?: string | null;
  snapshot_timestamp?: string | null;
  modified_by?: string | null;
  created_by?: string | null;
}

// ---------------------------------------------------------------------------
// Existing script result row (subset read by this surface)
// ---------------------------------------------------------------------------

export interface ScriptResultRow {
  id: string;
  script_name: string;
  script_type: string;
  success: boolean | null;
  execution_time_ms: number | null;
  started_at: string;
  completed_at: string | null;
  host_name: string;
  device_name: string;
  userinterface_name: string | null;
  metadata?: Record<string, unknown> | null;
  milestone_id?: string | null;
  run_group_id?: string | null;
  labels?: Array<Pick<RunLabel, 'id' | 'name' | 'color'>>;
}

/** Server-side filters added to getAllScriptResults for governance views. */
export interface ScriptResultGovernanceFilters {
  milestone_id?: string | null;
  run_group_id?: string | null;
  label_id?: string | null;
}

// ---------------------------------------------------------------------------
// Route helpers (frontend paths)
// ---------------------------------------------------------------------------

/** Tabs of the Quality page, as they appear in its `tab` URL parameter. */
export const QUALITY_TABS = ['flaky', 'slow', 'not-executed'] as const;
export type QualityTab = (typeof QUALITY_TABS)[number];

/** Tabs of the Run Management page, as they appear in its `tab` URL parameter. */
export const RUN_MANAGEMENT_TABS = ['groups', 'milestones', 'labels', 'defects', 'custom-reports', 'manual'] as const;
export type RunManagementTab = (typeof RUN_MANAGEMENT_TABS)[number];
const runManagement = (tab: RunManagementTab) => `/test-results/run-management?tab=${tab}`;

export const REPORT_ROUTES = {
  summary: (kind: RunKind, id: string) => `/test-results/runs/${seg(kind)}/${seg(id)}`,
  live: (taskId: string) => `/test-results/live/${seg(taskId)}`,
  runManagement,
  groups: runManagement('groups'),
  group: (id: string) => `/test-results/groups/${seg(id)}`,
  milestones: runManagement('milestones'),
  milestone: (id: string) => `/test-results/milestones/${seg(id)}`,
  labels: runManagement('labels'),
  defects: runManagement('defects'),
  quality: (tab: QualityTab = 'flaky') => `/test-results/quality?tab=${tab}`,
  customReports: runManagement('custom-reports'),
  manual: runManagement('manual'),
  manualSession: (id: string) => `/test-results/manual/${seg(id)}`,
  testReports: '/test-results/reports',
  share: (snapshotId: string) => `/share/run/${seg(snapshotId)}`,
} as const;

// ---------------------------------------------------------------------------
// Client-side label validation (mirrors the server; the server stays the authority)
// ---------------------------------------------------------------------------

/** Returns an error message, or null when the name is acceptable. */
export const validateLabelName = (
  rawName: string,
  existing: ReadonlyArray<Pick<RunLabel, 'id' | 'name'>>,
  editingId?: string,
): string | null => {
  const name = rawName.trim();
  if (name.length < 1) return 'Name is required';
  if (name.length > LABEL_NAME_MAX) return `At most ${LABEL_NAME_MAX} characters`;
  const lower = name.toLowerCase();
  if (existing.some((label) => label.id !== editingId && label.name.trim().toLowerCase() === lower)) {
    return 'A label with this name already exists';
  }
  return null;
};

/** Returns an error message when more than LABELS_PER_ENTITY_MAX labels are selected. */
export const validateLabelSelection = (labelIds: readonly string[]): string | null =>
  new Set(labelIds).size > LABELS_PER_ENTITY_MAX ? `At most ${LABELS_PER_ENTITY_MAX} labels per item` : null;
